"""Portable local Docker Compose controller shared by GUI and CLI launchers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from uuid import UUID

Progress = Callable[[str], None]
DOCKER_COMMAND_TIMEOUT_SECONDS = 30 * 60


class BudBotServiceError(RuntimeError):
    """An actionable, user-facing local-service error."""


class BudBotServiceController:
    def __init__(
        self,
        repository_root: Path | None = None,
        progress: Progress | None = None,
        *,
        cache_dir: Path | None = None,
        operating_system: str | None = None,
    ) -> None:
        self.root = repository_root or Path(__file__).resolve().parents[1]
        self.progress = progress or (lambda _message: None)
        self.operating_system = operating_system or platform.system()
        if cache_dir is not None:
            base = cache_dir
        elif self.operating_system == "Windows":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        else:
            base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        self.cache_dir = base / "BudBot"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.preview_file = self.cache_dir / "preview-url.txt"
        self.selected_business_file = self.cache_dir / "selected-business.txt"
        self.log_file = self.cache_dir / "control-center.log"

    def _compose(self, *arguments: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--project-name",
            "budbot",
            "-f",
            str(self.root / "docker-compose.dev.yml"),
            *arguments,
        ]

    def _run(self, arguments: list[str], failure: str) -> str:
        is_windows = self.operating_system == "Windows"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if is_windows else 0
        startupinfo = None
        if is_windows:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            with self.log_file.open("a", encoding="utf-8") as log:
                log.write("\n$ " + subprocess.list2cmdline(arguments) + "\n")
                log.flush()
                try:
                    result = subprocess.run(
                        arguments,
                        cwd=self.root,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        errors="replace",
                        shell=False,
                        creationflags=creationflags,
                        startupinfo=startupinfo,
                        timeout=DOCKER_COMMAND_TIMEOUT_SECONDS,
                    )
                except subprocess.TimeoutExpired as exc:
                    output = exc.stdout or ""
                    if isinstance(output, bytes):
                        output = output.decode("utf-8", errors="replace")
                    log.write(output)
                    log.flush()
                    guidance = failure or "The Docker command did not finish."
                    raise BudBotServiceError(
                        f"{guidance}\nThe Docker command timed out after "
                        f"{DOCKER_COMMAND_TIMEOUT_SECONDS // 60} minutes. "
                        f"Check Docker, then use Stop or Restart before retrying. "
                        f"Details: {self.log_file}"
                    ) from None
                output = result.stdout or ""
                log.write(output)
                log.flush()
        except OSError as exc:
            raise BudBotServiceError(f"Could not run Docker: {exc}") from None
        if any(word in output.lower() for word in ("building", "pulling", "extracting")):
            self.progress("Building the local containers… first launch may take a few minutes.")
        if result.returncode:
            raise BudBotServiceError(f"{failure}\nDetails: {self.log_file}")
        return output

    def _check_docker(self) -> None:
        if shutil.which("docker") is None:
            platform_hint = (
                "Install Docker Desktop with Docker Compose."
                if os.name == "nt"
                else "Install Docker Engine and the Docker Compose plugin."
            )
            raise BudBotServiceError(f"Docker was not found. {platform_hint}")
        try:
            self._run(["docker", "compose", "version"], "Docker Compose is unavailable.")
        except BudBotServiceError as exc:
            raise BudBotServiceError(
                f"Docker Compose is unavailable. Install or enable Compose V2.\n{exc}"
            ) from None
        try:
            self._run(["docker", "info", "--format", "{{.ServerVersion}}"], "")
        except BudBotServiceError:
            if self.operating_system == "Windows":
                guidance = "Open Docker Desktop and wait until it says Docker is running."
            else:
                guidance = "Start the Docker daemon and make sure your account can access it."
            raise BudBotServiceError(f"Docker is installed, but its daemon is unavailable. {guidance}") from None

    def _prepare_configuration(self) -> None:
        env_path = self.root / ".env"
        if not env_path.exists():
            defaults = self.root / ".env.example"
            if not defaults.is_file():
                raise BudBotServiceError("The local defaults file .env.example is missing.")
            try:
                shutil.copyfile(defaults, env_path)
            except OSError as exc:
                raise BudBotServiceError(f"Could not create local .env: {exc}") from None
        # Never edit or rewrite a user's existing configuration.

    def _wait_ready(self) -> None:
        self.progress("Waiting for PostgreSQL migrations and backend health…")
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            try:
                with urlopen("http://127.0.0.1:8000/ready", timeout=2):
                    pass
                with urlopen("http://127.0.0.1:8000/widget/", timeout=2):
                    pass
                return
            except (OSError, URLError, TimeoutError):
                status = self._run(
                    self._compose("ps", "--format", "json", "backend"),
                    "Could not check the backend startup status.",
                )
                try:
                    containers = json.loads(status) if status.strip() else []
                except json.JSONDecodeError:
                    try:
                        containers = [
                            json.loads(line)
                            for line in status.splitlines()
                            if line.strip()
                        ]
                    except json.JSONDecodeError:
                        containers = []
                if isinstance(containers, dict):
                    containers = [containers]
                failed_states = {"restarting", "exited", "dead"}
                failed = next(
                    (
                        item.get("State", "unknown").lower()
                        for item in containers
                        if item.get("State", "").lower() in failed_states
                    ),
                    None,
                )
                if failed:
                    raise BudBotServiceError(
                        f"The backend container is {failed}. Details: {self.log_file}"
                    )
                self.progress("BudBot is still starting…")
                time.sleep(3)
        raise BudBotServiceError(
            f"BudBot did not become healthy within 15 minutes. Details: {self.log_file}"
        )

    @staticmethod
    def _valid_uuid(value: str) -> bool:
        try:
            UUID(value)
            return True
        except ValueError:
            return False

    @classmethod
    def _business_id_from_url(cls, url: str) -> str:
        """Extract and validate the tenant UUID from a generated preview URL."""

        business_id = parse_qs(urlparse(url).query).get("business_id", [""])[0]
        if not cls._valid_uuid(business_id):
            raise BudBotServiceError("The preview URL did not contain a valid business ID.")
        return business_id

    def start(self) -> str:
        self.progress("Checking Docker and Docker Compose…")
        self._check_docker()
        self.progress("Preparing local settings without overwriting existing configuration…")
        self._prepare_configuration()
        self._run(
            self._compose("config", "--quiet"),
            "The development Compose configuration is invalid. Existing .env was left untouched.",
        )
        self.progress("Building and starting BudBot and PostgreSQL…")
        self._run(
            self._compose("up", "--detach", "--build", "db", "backend"),
            "BudBot could not start. Check Docker or a local port conflict on 8000/5432.",
        )
        self._wait_ready()
        self.progress("Creating or reusing the local demo business and location…")
        business_id = self.create_demo_business()
        url = f"http://127.0.0.1:8000/widget/?business_id={business_id}"
        try:
            with urlopen(url, timeout=4):
                pass
        except (OSError, URLError, TimeoutError):
            raise BudBotServiceError(
                f"The widget preview did not respond. Details: {self.log_file}"
            ) from None
        self.preview_file.write_text(url + "\n", encoding="utf-8")
        self.progress("BudBot is ready.")
        return url

    def create_demo_business(self) -> str:
        self.progress("Creating or reusing the local demo business and location…")
        output = self._run(
            self._compose(
                "exec", "-T", "backend", "python", "-m", "budbot.dev_seed"
            ),
            "The demo could not be initialized. Existing business data was left unchanged.",
        )
        business_id = output.strip().splitlines()[-1] if output.strip() else ""
        if not self._valid_uuid(business_id):
            raise BudBotServiceError(
                f"Demo initialization returned no valid business ID. Details: {self.log_file}"
            )
        return business_id

    def stop(self) -> None:
        self.progress("Stopping BudBot backend and PostgreSQL; keeping all database data…")
        self._check_docker()
        self._run(
            self._compose("stop", "backend", "db"),
            "BudBot services could not be stopped.",
        )
        self.preview_file.unlink(missing_ok=True)

    def restart(self) -> str:
        self.stop()
        return self.start()

    def detect_running(self) -> str | None:
        """Return the saved preview URL only if this tenant/API is reachable."""

        if not self.preview_file.is_file():
            return None
        try:
            url = self.preview_file.read_text(encoding="utf-8").strip()
            business_id = self._business_id_from_url(url)
        except (OSError, BudBotServiceError):
            self.preview_file.unlink(missing_ok=True)
            return None
        try:
            with urlopen("http://127.0.0.1:8000/ready", timeout=1.5):
                pass
            with urlopen("http://127.0.0.1:8000/widget/", timeout=1.5):
                pass
            request = Request(
                f"http://127.0.0.1:8000/api/v1/businesses/{business_id}",
                headers={"X-BudBot-Business-ID": business_id},
            )
            with urlopen(request, timeout=1.5):
                pass
            # Reconstruct a trusted loopback URL; never open arbitrary contents
            # written into the cache file.
            return f"http://127.0.0.1:8000/widget/?business_id={business_id}"
        except (OSError, URLError, TimeoutError):
            self.preview_file.unlink(missing_ok=True)
            return None


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    action = arguments[0] if arguments else "start"
    controller = BudBotServiceController()
    controller.progress = lambda message: print(f"# {message}", flush=True)
    try:
        if action == "start":
            url = controller.start()
            print(f"PREVIEW_URL={url}", flush=True)
            if len(arguments) > 1:
                Path(arguments[1]).write_text(url + "\n", encoding="utf-8")
        elif action == "stop":
            controller.stop()
        elif action == "restart":
            url = controller.restart()
            print(f"PREVIEW_URL={url}", flush=True)
        elif action == "demo":
            print(controller.create_demo_business(), flush=True)
        else:
            print("Usage: service_controller.py [start|stop|restart]", file=sys.stderr)
            return 2
    except BudBotServiceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
