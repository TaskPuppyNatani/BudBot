"""Bounded async JSON request helper shared by HTTP provider transports."""

from __future__ import annotations

import json
from collections.abc import Mapping

import httpx

from budbot.providers.ai.base import AIProviderConfig
from budbot.providers.ai.errors import AIError


MAX_PROVIDER_RESPONSE_BYTES = 1_048_576


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: Mapping[str, str],
    body: Mapping[str, object],
    config: AIProviderConfig,
) -> Mapping[str, object]:
    """Send one request, bound response size, and hide all upstream diagnostics."""

    timeout = httpx.Timeout(
        timeout=config.timeout_seconds,
        connect=min(config.connect_timeout_seconds, config.timeout_seconds),
    )
    try:
        async with client.stream(
            "POST", url, headers=dict(headers), json=dict(body), timeout=timeout
        ) as response:
            if response.status_code in {401, 403}:
                raise AIError("AI_PROVIDER_AUTH_FAILED")
            if response.status_code == 404:
                raise AIError("AI_MODEL_UNAVAILABLE")
            if response.status_code == 429 or response.status_code >= 500:
                raise AIError("AI_PROVIDER_UNAVAILABLE")
            if response.status_code < 200 or response.status_code >= 300:
                raise AIError("AI_PROVIDER_BAD_RESPONSE")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_PROVIDER_RESPONSE_BYTES:
                    raise AIError("AI_PROVIDER_BAD_RESPONSE")
                chunks.append(chunk)
    except AIError:
        raise
    except httpx.TimeoutException as exc:
        raise AIError("AI_PROVIDER_TIMEOUT") from exc
    except httpx.RequestError as exc:
        raise AIError("AI_PROVIDER_UNAVAILABLE") from exc

    try:
        payload = json.loads(b"".join(chunks))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise AIError("AI_PROVIDER_BAD_RESPONSE") from exc
    if not isinstance(payload, Mapping) or not all(
        isinstance(key, str) for key in payload
    ):
        raise AIError("AI_PROVIDER_BAD_RESPONSE")
    return payload
