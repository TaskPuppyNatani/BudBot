"""Fixed, bounded IPC to the optional local-development host controller."""

import asyncio
from pathlib import Path

from budbot.core.exceptions import DomainError

SOCKET_PATH = Path(__file__).resolve().parents[2] / ".budbot-runtime" / "control.sock"


class LocalRuntimeService:
    async def _request(self, command: bytes) -> str:
        writer = None
        try:
            async with asyncio.timeout(2):
                reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH), limit=64)
                writer.write(command)
                await writer.drain()
                return (await reader.readline()).decode("ascii").strip()
        except (OSError, TimeoutError, UnicodeError, ValueError):
            return "unavailable"
        finally:
            if writer is not None:
                writer.close()

    async def status(self) -> dict[str, object]:
        state = await self._request(b"status\n")
        available = state in {"running", "stopping", "error"}
        return {"available": available, "state": state if available else "unavailable"}

    async def shutdown(self) -> None:
        if await self._request(b"shutdown\n") != "accepted":
            raise DomainError(
                "Local shutdown is unavailable. Relaunch BudBot with scripts/start_budbot.sh or use the existing Stop command.",
                code="LOCAL_RUNTIME_UNAVAILABLE", status_code=503,
            )
