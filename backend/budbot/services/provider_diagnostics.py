"""One tiny, bounded transport request. No sessions, business tools or raw output."""

import asyncio
from dataclasses import replace

import httpx

from budbot.providers.ai.base import AIMessage, AIMessageRole, AIRequest, GenerationOptions, AIProviderConfig
from budbot.providers.ai.errors import AIError
from budbot.providers.ai.registry import AIProviderRegistry
from budbot.providers.ai.harness_registry import AIHarnessRegistry
from budbot.schemas.provider import ProviderDiagnosticCode as Code

TEST_TIMEOUT_SECONDS = 10
TEST_MAX_OUTPUT_TOKENS = 16


async def diagnose_connection(config: AIProviderConfig, providers: AIProviderRegistry, harnesses: AIHarnessRegistry) -> Code:
    """Use the same trusted transport/harness pair as customer AI, without tools."""
    try:
        config = replace(config, timeout_seconds=min(config.timeout_seconds, TEST_TIMEOUT_SECONDS),
            connect_timeout_seconds=min(config.connect_timeout_seconds, 3),
            max_output_tokens=TEST_MAX_OUTPUT_TOKENS)
        harnesses.validate_pair(config.provider, config.harness)
        request = AIRequest(messages=(AIMessage(AIMessageRole.USER, "Reply OK."),),
            model=config.model, harness=config.harness,
            generation=GenerationOptions(max_output_tokens=TEST_MAX_OUTPUT_TOKENS))
        async with asyncio.timeout(config.timeout_seconds):
            response = await providers.resolve(config.provider).generate(
                request, config, harnesses.resolve(config.harness))
        # Unsolicited tool requests are incompatible; never execute them.
        return Code.INCOMPATIBLE_RESPONSE if response.tool_calls else Code.OK
    except AIError as error:
        if error.code == "AI_PROVIDER_UNAVAILABLE":
            if isinstance(error.__cause__, httpx.RemoteProtocolError):
                return Code.INCOMPATIBLE_RESPONSE
            if isinstance(error.__cause__, httpx.RequestError):
                return Code.UNREACHABLE
        try:
            code = Code(error.code)
            return code if code != Code.OK else Code.PROVIDER_ERROR
        except ValueError:
            return Code.PROVIDER_ERROR
    except TimeoutError:
        return Code.TIMEOUT
    except Exception:
        # Exception text, transport bodies, and chained exceptions never escape.
        return Code.PROVIDER_ERROR
