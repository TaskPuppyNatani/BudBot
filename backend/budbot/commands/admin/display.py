"""Fixed owner-facing labels, independent of stored/API diagnostic codes."""

from budbot.schemas.provider import ProviderDiagnosticCode as Code

PROVIDER_NAMES = {
    "openrouter": "OpenRouter", "openai_compatible": "LM Studio / OpenAI-compatible",
    "openai": "OpenAI", "anthropic": "Anthropic",
}
PROVIDER_STATES = {
    "ready": "Settings complete; run /test to check the connection",
    "disabled": "AI is turned off", "incomplete": "Setup needs attention",
}
DIAGNOSTIC_LABELS = {
    Code.OK: "Connected",
    Code.DISABLED: "AI is turned off.",
    Code.CONFIGURATION_INVALID: "AI setup needs attention.",
    Code.CREDENTIAL_MISSING: "No API key is saved.",
    Code.ENDPOINT_DENIED: "This AI server is not approved for this installation.",
    Code.UNREACHABLE: "Could not reach the AI provider.",
    Code.TIMEOUT: "The AI provider took too long to reply.",
    Code.AUTH_FAILED: "The AI provider rejected the saved API key.",
    Code.MODEL_UNAVAILABLE: "The configured AI model could not be found.",
    Code.INCOMPATIBLE_RESPONSE: "The AI provider sent a reply BudBot could not use.",
    Code.PROVIDER_UNAVAILABLE: "The AI provider is busy or temporarily unavailable.",
    Code.PROVIDER_ERROR: "The connection could not be checked.",
}
DIAGNOSTIC_GUIDANCE = {
    Code.OK: "The AI provider replied to a short test request.",
    Code.DISABLED: "Turn it on in AI Provider, then try /test again.",
    Code.CONFIGURATION_INVALID: "Review AI Provider settings. If the saved key cannot be read, ask the person who set up BudBot for help.",
    Code.CREDENTIAL_MISSING: "Add the key in AI Provider, then try /test again.",
    Code.ENDPOINT_DENIED: "Ask the person who set up BudBot to approve this server.",
    Code.UNREACHABLE: "Check that the server is running, then try /test again.",
    Code.TIMEOUT: "Check the server and loaded model, then try again.",
    Code.AUTH_FAILED: "Update the key in AI Provider, then try again.",
    Code.MODEL_UNAVAILABLE: "Check the model name in AI Provider, then try /test again.",
    Code.INCOMPATIBLE_RESPONSE: "Check the selected model and server settings in AI Provider.",
    Code.PROVIDER_UNAVAILABLE: "Wait a moment and try again.",
    Code.PROVIDER_ERROR: "Reload settings and try /test again.",
}


def provider_name(value):
    return PROVIDER_NAMES.get(value, "Not set up")


def provider_state(value):
    return PROVIDER_STATES.get(value, "Setup needs attention")


def diagnostic_label(value):
    return DIAGNOSTIC_LABELS.get(value, DIAGNOSTIC_LABELS[Code.PROVIDER_ERROR])


def diagnostic_message(value):
    return diagnostic_label(value) + "\n" + DIAGNOSTIC_GUIDANCE.get(value, DIAGNOSTIC_GUIDANCE[Code.PROVIDER_ERROR])
