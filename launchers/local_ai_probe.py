"""Read-only launcher diagnostic, executed inside the existing backend container.

Only endpoint metadata is queried. No credential table or decryption is used,
and stdout contains one fixed status, never endpoint values or exception text.
TCP reachability does not verify model capabilities, credentials or inference.
"""

from __future__ import annotations

import asyncio
import socket
import time
from urllib.parse import urlsplit


def probe_endpoints(endpoints: list[str], allowed: tuple[str, ...]) -> str:
    if not endpoints:
        return "not-configured"
    deadline = time.monotonic() + 5
    for endpoint in endpoints:
        if endpoint not in allowed:
            return "not-approved"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "unknown"
        try:
            parsed = urlsplit(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return "unavailable"
            with socket.create_connection(
                (parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)),
                timeout=min(1, remaining),
            ):
                pass
        except (OSError, ValueError):
            return "unavailable"
    return "reachable"


async def configured_endpoints() -> tuple[list[str], tuple[str, ...]]:
    # Imports belong here because this script runs in the backend environment;
    # the host launcher itself remains Python-standard-library only.
    from sqlalchemy import select
    from budbot.core.config import get_settings
    from budbot.database.session import Database
    from budbot.models.provider import BusinessAIProfile

    settings = get_settings()
    if not settings.ai_tenant_enabled:
        return [], ()
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            endpoints = list(await session.scalars(
                select(BusinessAIProfile.base_url)
                .where(BusinessAIProfile.enabled.is_(True),
                       BusinessAIProfile.provider == "openai_compatible")
                .distinct()
            ))
        return endpoints, settings.ai_compatible_endpoints
    finally:
        await database.dispose()


def main() -> None:
    try:
        endpoints, allowed = asyncio.run(configured_endpoints())
        status = probe_endpoints(endpoints, allowed)
    except Exception:
        status = "unknown"
    print(status)


if __name__ == "__main__":
    main()
