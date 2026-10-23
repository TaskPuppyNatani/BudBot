"""Tenant provider administration and the narrow runtime decryption boundary."""
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from budbot.core.config import Settings
from budbot.core.exceptions import DomainError
from budbot.core.tenancy import TenantContext
from budbot.models.provider import BusinessAIProfile, ProviderCredential
from budbot.providers.ai.base import AICapabilities, AIProviderConfig
from budbot.providers.ai.config import provider_config_from_settings
from budbot.providers.ai.errors import AIError
from budbot.schemas.provider import ProviderRead, ProviderUpdate, CredentialUpdate, ProviderConnectionRead, ProviderDiagnosticCode as Code
from budbot.services.provider_diagnostics import diagnose_connection
from budbot.services.business_service import BusinessService
from budbot.services.secret_store import EncryptedSecretStore, SecretStore

class ProviderService:
    def __init__(self, session: AsyncSession, tenant: TenantContext, settings: Settings, secrets: SecretStore | None = None):
        self.session, self.tenant, self.settings, self.secrets = session, tenant, settings, secrets

    async def _profile(self):
        return await self.session.scalar(select(BusinessAIProfile).where(BusinessAIProfile.business_id == self.tenant.business_id))

    async def _credential(self):
        return await self.session.scalar(select(ProviderCredential).where(ProviderCredential.business_id == self.tenant.business_id))

    async def _lock(self):
        await BusinessService(self.session).get(self.tenant, self.tenant.business_id, for_update=True)

    def _store(self):
        return self.secrets or EncryptedSecretStore(self.settings.provider_root_key)

    async def read(self) -> ProviderRead:
        profile = await self._profile()
        credential_configured = await self._credential() is not None
        code = self._diagnostic_preflight(profile, credential_configured)
        status = "ready" if code is None else "disabled" if code == Code.DISABLED else "incomplete"
        if profile is None:
            return ProviderRead(configured=False, runtime_status=status, runtime_code=code)
        return ProviderRead(configured=True, provider=profile.provider, model=profile.model,
            enabled=profile.enabled, base_url=profile.base_url, tool_calling=profile.tool_calling,
            credential_configured=credential_configured, runtime_status=status, runtime_code=code)

    def _diagnostic_preflight(self, profile, credential_configured):
        if not self.settings.ai_tenant_enabled or (profile is not None and not profile.enabled):
            return Code.DISABLED
        if profile is None:
            return Code.CONFIGURATION_INVALID
        try:
            ProviderUpdate(provider=profile.provider, model=profile.model, base_url=profile.base_url,
                enabled=profile.enabled, tool_calling=profile.tool_calling)
        except Exception:
            return Code.CONFIGURATION_INVALID
        if profile.provider == "openai_compatible" and profile.base_url not in self.settings.ai_compatible_endpoints:
            return Code.ENDPOINT_DENIED
        if profile.provider != "openai_compatible" and not credential_configured:
            return Code.CREDENTIAL_MISSING
        if credential_configured and self.secrets is None and self.settings.provider_root_key is None:
            return Code.CONFIGURATION_INVALID
        return None

    async def test_connection(self, providers, harnesses) -> ProviderConnectionRead:
        profile = await self._profile()
        code = self._diagnostic_preflight(profile, await self._credential() is not None)
        if code is None:
            try:
                # Preflight requires a tenant profile: diagnostics never use the
                # legacy/global configuration fallback, even in development/tests.
                config = await self.runtime(allow_legacy=False)
            except Exception:
                code = Code.CONFIGURATION_INVALID
            else:
                code = await diagnose_connection(config, providers, harnesses)
        return ProviderConnectionRead(code=code,
            provider=profile.provider if profile and profile.provider in {"openrouter", "openai_compatible", "openai", "anthropic"} else None,
            model=profile.model if profile else None)

    def _endpoint_allowed(self, provider, url):
        if provider == "openai_compatible" and url not in self.settings.ai_compatible_endpoints:
            raise DomainError("Endpoint is not permitted by deployment policy. Ask the deployment operator to allow this exact base URL.", status_code=422)

    @staticmethod
    def _binding(profile):
        return profile.provider + ("|" + profile.base_url if profile.provider == "openai_compatible" else "")

    async def update(self, payload: ProviderUpdate):
        self._endpoint_allowed(payload.provider, payload.base_url)
        await self._lock()
        profile, credential = await self._profile(), await self._credential()
        if profile is not None and (profile.provider != payload.provider or profile.base_url != payload.base_url) and credential is not None:
            raise DomainError("Remove the credential before changing provider identity or endpoint.", code="PROVIDER_CHANGE_REQUIRES_REMOVAL", status_code=409)
        if payload.enabled and payload.provider != "openai_compatible" and credential is None:
            raise DomainError("Save disabled configuration, set a credential, then enable AI.", code="PROVIDER_CREDENTIAL_REQUIRED", status_code=409)
        if profile is None:
            profile = BusinessAIProfile(business_id=self.tenant.business_id, **payload.model_dump())
            self.session.add(profile)
        else:
            for name, value in payload.model_dump().items():
                setattr(profile, name, value)
        await self.session.flush()

    async def set_credential(self, payload: CredentialUpdate):
        await self._lock()
        profile = await self._profile()
        if profile is None:
            raise DomainError("Save provider configuration first.", status_code=409)
        credential = await self._credential()
        action = "replaced" if credential else "set"
        version, encrypted = self._store().seal(self.tenant.business_id, self._binding(profile), payload.credential)
        if credential is None:
            credential = ProviderCredential(business_id=self.tenant.business_id)
            self.session.add(credential)
        credential.version, credential.encrypted_value = version, encrypted
        await self.session.flush()
        return action

    async def remove_credential(self):
        await self._lock()
        profile, credential = await self._profile(), await self._credential()
        if credential is not None:
            await self.session.delete(credential)
        if profile is not None:
            profile.enabled = False
        await self.session.flush()

    async def runtime(self, *, allow_legacy: bool = True) -> AIProviderConfig:
        if not self.settings.ai_tenant_enabled:
            raise AIError("AI_DISABLED")
        profile = await self._profile()
        if profile is None:
            # Compatibility is restricted to tests or an explicitly bound single
            # tenant. Production never lends process credentials to arbitrary IDs.
            if allow_legacy and (self.settings.environment == "test" or self.settings.ai_legacy_business_id == self.tenant.business_id):
                return provider_config_from_settings(self.settings)
            raise AIError("AI_DISABLED")
        if not profile.enabled:
            raise AIError("AI_DISABLED")
        try:
            ProviderUpdate(provider=profile.provider, model=profile.model, base_url=profile.base_url, enabled=profile.enabled, tool_calling=profile.tool_calling)
            self._endpoint_allowed(profile.provider, profile.base_url)
            record = await self._credential()
            secret = self._store().open(self.tenant.business_id, self._binding(profile), record.version, record.encrypted_value) if record else None
            if profile.provider != "openai_compatible" and secret is None:
                raise ValueError()
            return AIProviderConfig(provider="openai_compatible" if profile.provider == "openrouter" else profile.provider,
                model=profile.model, harness={"openrouter":"generic_openai", "openai_compatible":"generic_openai", "openai":"openai_chat", "anthropic":"anthropic_native"}[profile.provider],
                base_url="https://openrouter.ai/api/v1" if profile.provider == "openrouter" else profile.base_url,
                api_key=secret.get_secret_value() if secret else None,
                timeout_seconds=self.settings.ai_timeout_seconds, connect_timeout_seconds=self.settings.ai_connect_timeout_seconds,
                max_output_tokens=self.settings.ai_max_output_tokens, capabilities=AICapabilities(tool_calling=profile.tool_calling))
        except Exception:
            raise AIError("AI_CONFIGURATION_INVALID") from None
