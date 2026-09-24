"""Generic async OpenAI-compatible Chat Completions transport."""

from __future__ import annotations

import httpx

from budbot.providers.ai.base import (
    AIProviderConfig,
    AIRequest,
    AIResponse,
    ModelHarness,
    require_tool_capability,
)
from budbot.providers.ai.errors import AIError
from budbot.providers.ai.http import post_json


class OpenAICompatibleTransport:
    """Shared transport for configured compatible services and hosted OpenAI."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        default_base_url: str | None = None,
        require_api_key: bool = False,
    ) -> None:
        self.client = client
        self.default_base_url = default_base_url
        self.require_api_key = require_api_key

    async def generate(
        self,
        request: AIRequest,
        config: AIProviderConfig,
        harness: ModelHarness,
    ) -> AIResponse:
        if not config.capabilities.text_generation:
            raise AIError("AI_CAPABILITY_UNSUPPORTED")
        require_tool_capability(request, config)
        if config.provider not in {"openai_compatible", "openai"}:
            raise AIError("AI_PROVIDER_UNKNOWN")
        if self.require_api_key and not config.api_key:
            raise AIError("AI_CONFIGURATION_INVALID")
        base_url = config.base_url or self.default_base_url
        if not base_url:
            raise AIError("AI_CONFIGURATION_INVALID")
        headers = {"accept": "application/json"}
        if config.api_key:
            headers["authorization"] = f"Bearer {config.api_key}"
        headers["x-budbot-request-id"] = str(request.request_id)
        body = harness.encode_request(request, config)
        payload = await post_json(
            self.client,
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            body=body,
            config=config,
        )
        return harness.decode_response(payload, request, config)
