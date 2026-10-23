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
import webbrowser
from collections.abc import Callable
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
from uuid import UUID

Progress = Callable[[str], None]
DOCKER_COMMAND_TIMEOUT_SECONDS = 30 * 60
LOCAL_WIDGET_URL = "http://127.0.0.1:8000/widget/"
LOCAL_ADMIN_URL = "http://localhost:8000/admin/"
READY_TIMEOUT_SECONDS = 900


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

    def _run(
        self, arguments: list[str], failure: str, *,
        timeout: float = DOCKER_COMMAND_TIMEOUT_SECONDS,
        record_output: bool = True,
    ) -> str:
        is_windows = self.operating_system == "Windows"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if is_windows else 0
        startupinfo = None
        if is_windows:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            with self.log_file.open("a", encoding="utf-8") as log:
                log.write("\n$ " + (subprocess.list2cmdline(arguments) if record_output
                          else "Docker command (output suppressed by launcher)") + "\n")
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
                        timeout=timeout,
                    )
                except subprocess.TimeoutExpired as exc:
                    output = exc.stdout or ""
                    if isinstance(output, bytes):
                        output = output.decode("utf-8", errors="replace")
                    if record_output:
                        log.write(output)
                    log.flush()
                    guidance = failure or "The Docker command did not finish."
                    duration = f"{timeout / 60:g} minutes" if timeout >= 60 else f"{timeout:g} seconds"
                    raise BudBotServiceError(
                        f"{guidance}\nThe Docker command timed out after {duration}. "
                        f"Check Docker, then use Stop or Restart before retrying. "
                        f"Details: {self.log_file}"
                    ) from None
                output = result.stdout or ""
                if record_output:
                    log.write(output)
                log.flush()
        except OSError as exc:
            if not record_output:
                raise BudBotServiceError("Could not run Docker. Check its installation and daemon access.") from None
            raise BudBotServiceError(f"Could not run Docker: {exc}") from None
        if any(word in output.lower() for word in ("building", "pulling", "extracting")):
            self.progress("Building the local containers… first launch may take a few minutes.")
        if result.returncode:
            raise BudBotServiceError(f"{failure}\nDetails: {self.log_file}")
        return output

    def _check_docker(self, *, record_output: bool = True) -> None:
        if shutil.which("docker") is None:
            platform_hint = (
                "Install Docker Desktop with Docker Compose."
                if os.name == "nt"
                else "Install Docker Engine and the Docker Compose plugin."
            )
            raise BudBotServiceError(f"Docker was not found. {platform_hint}")
        try:
            self._run(["docker", "compose", "version"], "Docker Compose is unavailable.",
                      timeout=10, record_output=record_output)
        except BudBotServiceError as exc:
            raise BudBotServiceError(
                f"Docker Compose is unavailable. Install or enable Compose V2.\n{exc}"
            ) from None
        try:
            self._run(["docker", "info", "--format", "{{.ServerVersion}}"], "",
                      timeout=10, record_output=record_output)
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

    @staticmethod
    def _probe_ready(asset_url: str, *, timeout: float = 2) -> bool:
        try:
            with urlopen("http://127.0.0.1:8000/ready", timeout=timeout):
                pass
            with urlopen(asset_url, timeout=timeout):
                pass
            return True
        except (OSError, URLError, TimeoutError):
            return False

    def _wait_ready(
        self, asset_url: str = LOCAL_WIDGET_URL, *,
        timeout_seconds: float = READY_TIMEOUT_SECONDS, record_output: bool = True,
    ) -> None:
        self.progress("Waiting for PostgreSQL migrations and backend health…")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._probe_ready(asset_url):
                return
            else:
                status = self._run(
                    self._compose("ps", "--all", "--format", "json", "backend"),
                    "Could not check the backend startup status.",
                    timeout=10, record_output=record_output,
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
                        str(item.get("State", "unknown")).lower()
                        for item in containers
                        if isinstance(item, dict) and str(item.get("State", "")).lower() in failed_states
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
            f"BudBot did not become healthy within {timeout_seconds / 60:g} minutes. "
            f"Check Docker and backend startup/migrations with "
            f"docker compose -f docker-compose.dev.yml --project-name budbot logs backend db. "
            f"Existing data is preserved. Details: {self.log_file}"
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

    def _start_services(self, *, admin: bool = False) -> None:
        """Share Compose startup between Control Center and the Admin launcher."""
        self.progress("Checking Docker and Docker Compose…")
        if admin:
            self._check_docker(record_output=False)
            if not (self.root / ".env").is_file():
                raise BudBotServiceError(
                    "Local .env is missing. From the repository, copy .env.example to .env "
                    "and configure it privately, then launch again. No configuration was created."
                )
        else:
            self._check_docker()
        self.progress("Preparing local settings without overwriting existing configuration…")
        if not admin:
            self._prepare_configuration()
        self._run(
            self._compose("config", "--quiet"),
            "The development Compose configuration is invalid. Check Compose files and .env syntax privately. "
            "Existing .env was left untouched.",
            timeout=30, record_output=not admin,
        )
        if admin and self._probe_ready(LOCAL_ADMIN_URL, timeout=1.5):
            self.progress("BudBot is already running; reusing the healthy stack.")
            return
        self.progress("Building and starting BudBot and PostgreSQL… first launch may take several minutes.")
        self._run(
            self._compose("up", "--detach", "--build", "db", "backend"),
            "BudBot could not start. Check Docker or a local port conflict on 8000/5432. "
            "For service/migration details, inspect locally: "
            "docker compose -f docker-compose.dev.yml --project-name budbot logs backend db.",
            record_output=not admin,
        )
        if admin:
            self._wait_ready(LOCAL_ADMIN_URL, record_output=False)
        else:
            self._wait_ready()

    def launch(self) -> str:
        """Start/reuse services for browser administration without seeding data."""
        self._start_services(admin=True)
        self.progress("BudBot is ready.")
        return LOCAL_ADMIN_URL

    def local_ai_warning(self) -> str | None:
        """Read-only, credential-free network diagnostic from the backend container."""
        self.progress("Checking optional compatible AI connectivity from the backend…")
        try:
            probe = Path(__file__).with_name("local_ai_probe.py").read_text(encoding="utf-8")
            status = self._run(
                self._compose("exec", "-T", "backend", "python", "-c", probe),
                "Optional AI connectivity could not be checked.",
                timeout=10, record_output=False,
            ).strip()
        except (BudBotServiceError, OSError):
            status = "unknown"
        if status in {"reachable", "not-configured"}:
            return None
        if status == "unavailable":
            return ("BudBot is running, but a configured compatible AI endpoint is unreachable "
                    "from the backend. Start the configured local server (such as LM Studio), "
                    "or check its address, bind/firewall settings and Docker host reachability. "
                    "Review Admin → AI Provider. LM Studio is optional and was not started.")
        if status == "not-approved":
            return ("BudBot is running, but a configured compatible AI endpoint is no longer "
                    "deployment-approved. Ask the operator to review the exact endpoint allowlist.")
        return ("BudBot is running. Optional AI connectivity could not be checked; "
                "review Admin → AI Provider. This does not prevent opening the dashboard.")

    def start(self) -> str:
        self._start_services()
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

    def _cached_preview_url(self) -> str | None:
        """Treat preview metadata as a local customer selector, not identity."""
        try:
            with self.preview_file.open(encoding="utf-8") as saved:
                contents = saved.read(4097)
            url = contents.strip()
            parsed = urlparse(url)
            query = parse_qs(parsed.query, keep_blank_values=True)
            if (
                len(contents) > 4096
                or parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.port != 8000
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path != "/widget/"
                or parsed.params
                or parsed.fragment
                or set(query) != {"business_id"}
                or len(query["business_id"]) != 1
            ):
                raise ValueError("Unsafe or malformed cached preview URL")
            business_id = self._business_id_from_url(url)
            return f"{LOCAL_WIDGET_URL}?business_id={UUID(business_id)}"
        except OSError:
            # Missing/unreadable metadata is not evidence of stopped services.
            return None
        except (UnicodeError, ValueError, BudBotServiceError):
            try:
                self.preview_file.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def detect_running(self) -> str | None:
        """Check local service readiness independently of owner authentication."""

        url = self._cached_preview_url()
        if url is None:
            try:
                selected = self.selected_business_file.read_text(encoding="utf-8").strip()
                if self._valid_uuid(selected):
                    url = f"{LOCAL_WIDGET_URL}?business_id={UUID(selected)}"
            except (OSError, UnicodeError):
                pass
        try:
            with urlopen("http://127.0.0.1:8000/ready", timeout=1.5):
                pass
            with urlopen(LOCAL_WIDGET_URL, timeout=1.5):
                pass
            # No data creation or protected business reads. Without a saved
            # selection the public shell is enough to report Running; explicit
            # branding sign-in can later select an authorized existing business.
            return url or LOCAL_WIDGET_URL
        except (OSError, URLError, TimeoutError):
            # Readiness/network failure does not invalidate saved business data.
            return None


def install_desktop(repository_root: Path | None = None) -> Path:
    """Install a checkout-specific Linux menu entry without root or shell commands."""
    if not sys.platform.startswith("linux"):
        raise BudBotServiceError("The application-menu installer supports Linux only.")
    root = (repository_root or Path(__file__).resolve().parents[1]).resolve()
    script = root / "launchers" / "service_controller.py"
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    values = (str(root), str(script), sys.executable, str(data_home))
    if not data_home.is_absolute() or any(any(ord(c) < 32 for c in value) for value in values):
        raise BudBotServiceError("The checkout and XDG_DATA_HOME must use absolute paths without control characters.")
    if not script.is_file():
        raise BudBotServiceError("The shared BudBot service controller is missing from this checkout.")

    def quote_exec(value: str) -> str:
        # Escape both the desktop-entry string layer and the Exec argument layer.
        escaped = "".join("\\" + c if c in '\\"`$' else c for c in value.replace("%", "%%"))
        return '"' + escaped.replace("\\", "\\\\") + '"'

    destination = data_home / "applications" / "budbot.desktop"
    destination.parent.mkdir(parents=True, exist_ok=True)
    working_directory = str(root).replace("\\", "\\\\")
    destination.write_text(
        "[Desktop Entry]\nVersion=1.0\nType=Application\nName=BudBot\n"
        "Comment=Start BudBot locally and open the Admin dashboard\n"
        f"Exec={quote_exec(sys.executable)} {quote_exec(str(script))} launch-desktop\n"
        f"Path={working_directory}\n"
        "Icon=applications-internet\nTerminal=true\nStartupNotify=false\n"
        "Categories=Development;WebDevelopment;\n",
        encoding="utf-8",
    )
    destination.chmod(0o644)
    return destination


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    action = arguments[0] if arguments else "start"
    desktop = action == "launch-desktop"
    needs_attention = False
    exit_code = 0
    try:
        if action == "install-desktop":
            print(f"Installed BudBot application-menu entry: {install_desktop()}")
            return 0
        controller = BudBotServiceController()
        controller.progress = lambda message: print(f"# {message}", flush=True)
        if action in {"launch", "launch-desktop"}:
            url = controller.launch()
            print(f"Admin: {url}", flush=True)
            try:
                opened = webbrowser.open(url, new=2)
            except Exception:
                opened = False
            if not opened:
                print(f"WARNING: The browser could not open automatically. Open {url} manually.", flush=True)
                needs_attention = True
            warning = controller.local_ai_warning()
            if warning:
                print(f"WARNING: {warning}", flush=True)
                needs_attention = True
        elif action == "start":
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
            print("Usage: service_controller.py [launch|install-desktop|start|stop|restart|demo]", file=sys.stderr)
            return 2
    except BudBotServiceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        exit_code = 1
    except KeyboardInterrupt:
        print("\nCancelled. Detached Docker services may still be running or starting. "
              "Rerun scripts/start_budbot.sh to reconnect, or scripts/stop_budbot.sh to stop safely.",
              file=sys.stderr, flush=True)
        return 130
    except Exception:
        print("ERROR: The launcher could not complete. Check Docker access and local file permissions, "
              "then retry scripts/start_budbot.sh. Existing services and data were left in place.",
              file=sys.stderr, flush=True)
        exit_code = 1
    if desktop and (exit_code or needs_attention) and sys.stdin.isatty():
        try:
            input("Press Enter to close this launcher window…")
        except (EOFError, KeyboardInterrupt):
            pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
