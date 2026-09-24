"""Native Anthropic Messages API transport."""

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


class AnthropicTransport:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def generate(
        self,
        request: AIRequest,
        config: AIProviderConfig,
        harness: ModelHarness,
    ) -> AIResponse:
        if not config.capabilities.text_generation:
            raise AIError("AI_CAPABILITY_UNSUPPORTED")
        require_tool_capability(request, config)
        if config.provider != "anthropic" or not config.api_key:
            raise AIError("AI_CONFIGURATION_INVALID")
        base_url = config.base_url or "https://api.anthropic.com/v1"
        body = harness.encode_request(request, config)
        payload = await post_json(
            self.client,
            f"{base_url.rstrip('/')}/messages",
            headers={
                "accept": "application/json",
                "x-api-key": config.api_key,
                "anthropic-version": "2023-06-01",
                "x-budbot-request-id": str(request.request_id),
            },
            body=body,
            config=config,
        )
        return harness.decode_response(payload, request, config)
