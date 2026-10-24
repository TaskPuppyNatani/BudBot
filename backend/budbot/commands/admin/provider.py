"""Write-only provider credentials stay outside command inputs and outputs."""

from budbot.commands.admin.common import actions, result, runtime
from budbot.commands.admin.display import diagnostic_message, provider_name, provider_state
from budbot.services.provider_service import ProviderService


async def provider(context, parsed):
    state = runtime(context)
    profile = await ProviderService(context.session, context.tenant, state.settings).read()
    return result(context, parsed,
        f"AI provider: {provider_name(profile.provider)}\nModel: {profile.model or 'Not selected'}\n"
        f"{provider_state(profile.runtime_status)}\nAPI key saved: {'Yes' if profile.credential_configured else 'No'}\n"
        "Open AI Provider to change these settings.")


async def test(context, parsed):
    state = runtime(context)
    diagnostic = await actions(context).test_provider(state.settings, state.providers, state.harnesses)
    return result(context, parsed, f"{diagnostic_message(diagnostic.code)}\nAI provider: {provider_name(diagnostic.provider)}\nModel: {diagnostic.model or 'Not selected'}")
