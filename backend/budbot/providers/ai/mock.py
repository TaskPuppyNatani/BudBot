"""Scriptable normalized transport used for deterministic testing."""

from collections import deque
from collections.abc import Iterable

from budbot.providers.ai.base import AIProviderConfig, AIRequest, AIResponse, ModelHarness
from budbot.providers.ai.errors import AIError


class MockAIProvider:
    def __init__(self, responses: Iterable[AIResponse] = ()) -> None:
        self._responses = deque(responses)
        self.requests: list[AIRequest] = []

    async def generate(
        self,
        request: AIRequest,
        config: AIProviderConfig,
        harness: ModelHarness,
    ) -> AIResponse:
        self.requests.append(request)
        if not self._responses:
            raise AIError("AI_PROVIDER_UNAVAILABLE")
        response = self._responses.popleft()
        return AIResponse(
            content=response.content,
            finish_reason=response.finish_reason,
            tool_calls=response.tool_calls,
            provider=config.provider,
            model=config.model,
            harness=config.harness,
            usage=response.usage,
            request_id=request.request_id,
        )
