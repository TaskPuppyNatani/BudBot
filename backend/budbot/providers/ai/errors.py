"""Safe, provider-neutral AI failures."""

from budbot.core.exceptions import DomainError


_ERRORS: dict[str, tuple[str, int]] = {
    "AI_DISABLED": ("AI chat is not enabled.", 503),
    "AI_CONFIGURATION_INVALID": ("AI chat is not configured correctly.", 503),
    "AI_PROVIDER_UNKNOWN": ("The configured AI provider is not supported.", 503),
    "AI_PROVIDER_UNAVAILABLE": ("The AI provider is temporarily unavailable.", 503),
    "AI_PROVIDER_TIMEOUT": ("The AI provider did not respond in time.", 504),
    "AI_PROVIDER_AUTH_FAILED": ("The AI provider rejected its configured credentials.", 503),
    "AI_PROVIDER_BAD_RESPONSE": ("The AI provider returned an invalid response.", 502),
    "AI_MODEL_UNAVAILABLE": ("The configured AI model is unavailable.", 503),
    "AI_HARNESS_UNSUPPORTED": ("The configured model behavior is not supported.", 503),
    "AI_CAPABILITY_UNSUPPORTED": ("The configured model cannot perform this request.", 503),
    "AI_TOOL_CALL_INVALID": ("The AI provider returned an invalid tool request.", 502),
    "AI_TOOL_NOT_AVAILABLE": ("That BudBot capability is unavailable in this session.", 403),
    "AI_TOOL_LIMIT_EXCEEDED": ("The AI request exceeded its tool-call limit.", 502),
}


class AIError(DomainError):
    """Expected AI/provider failure with a fixed customer-safe description."""

    def __init__(self, code: str) -> None:
        detail, status_code = _ERRORS.get(
            code, ("The AI request could not be completed.", 502)
        )
        super().__init__(detail, code=code, status_code=status_code)
