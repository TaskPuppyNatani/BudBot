"""First-party OpenAI cloud configuration over the shared compatible transport."""

import httpx

from budbot.providers.ai.openai_compatible import OpenAICompatibleTransport


class OpenAITransport(OpenAICompatibleTransport):
    def __init__(self, client: httpx.AsyncClient) -> None:
        super().__init__(
            client,
            default_base_url="https://api.openai.com/v1",
            require_api_key=True,
        )
