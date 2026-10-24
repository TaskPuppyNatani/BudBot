"""Write-only provider credentials stay outside command inputs and outputs."""

from budbot.commands.admin.common import actions, result, runtime
from budbot.services.provider_service import ProviderService


async def provider(context, parsed):
    state = runtime(context)
    profile = await ProviderService(context.session, context.tenant, state.settings).read()
    return result(context, parsed,
        f"Provider: {profile.provider or 'unconfigured'}\nModel: {profile.model or 'unconfigured'}\n"
        f"Runtime: {profile.runtime_status}\nCredential configured: {profile.credential_configured}\n"
        "Use the AI Provider dashboard to change configuration or credentials.")


async def test(context, parsed):
    state = runtime(context)
    diagnostic = await actions(context).test_provider(state.settings, state.providers, state.harnesses)
    return result(context, parsed, f"{diagnostic.code.value}\nProvider: {diagnostic.provider or 'unconfigured'}\nModel: {diagnostic.model or 'unconfigured'}")
