"""Private Unix-socket controller for one predefined local BudBot shutdown.

The development source bind mount makes this socket visible to the backend.
No network listener, Docker socket mount, token, or browser-supplied command is
used. The socket/directory are accessible only to the launching OS user (and
the development container's existing filesystem authority).
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time


def runtime_directory(root: Path) -> Path:
    return root / "backend" / ".budbot-runtime"


def prepare_directory(root: Path) -> Path:
    directory = runtime_directory(root)
    if directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()):
        raise ValueError("Invalid runtime directory")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_uid != os.getuid():
        raise ValueError("Runtime directory has a different owner")
    directory.chmod(0o700)
    return directory


def request_status(path: Path) -> str | None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.25)
            connection.connect(str(path))
            connection.sendall(b"status\n")
            return connection.makefile("rb").readline(32).decode("ascii").strip()
    except (OSError, UnicodeError):
        return None


def ensure_running(root: Path) -> str | None:
    """Detach one controller; failure is an optional-capability warning only."""
    if os.name != "posix" or not hasattr(socket, "AF_UNIX"):
        return "Local web shutdown is unavailable on this platform; use the existing Stop command or Control Center."
    try:
        directory = prepare_directory(root)
        path = directory / "control.sock"
        status = request_status(path)
        if status in {"running", "error"}:
            return None
        if status == "stopping":
            return "A local shutdown is still in progress. Wait for it to finish, then launch BudBot again."
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "serve", str(root.resolve())],
            cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if request_status(path) in {"running", "error"}:
                return None
            if process.poll() is not None:
                break
            time.sleep(0.05)
    except (OSError, ValueError):
        pass
    return "BudBot is running, but local web shutdown is unavailable. Use scripts/stop_budbot.sh or Control Center."


class RuntimeServer(socketserver.UnixStreamServer):
    def __init__(self, path: Path, shutdown_action, *, delay: float = 1):
        self.state = "running"
        self.state_lock = threading.Lock()
        self.shutdown_action = shutdown_action
        self.delay = delay
        super().__init__(str(path), RuntimeHandler)
        path.chmod(0o600)

    def begin_shutdown(self) -> None:
        with self.state_lock:
            if self.state in {"stopping", "stopped"}:
                return
            self.state = "stopping"
        threading.Thread(target=self._stop, daemon=True).start()

    def _stop(self) -> None:
        # Acknowledge before Docker stops the backend handling the HTTP request.
        time.sleep(self.delay)
        try:
            self.shutdown_action()
        except Exception:
            self.state = "error"
            return
        self.state = "stopped"
        self.shutdown()

    def handle_error(self, request, client_address):
        # Never emit exception text or peer/process information.
        pass


class RuntimeHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(1)
        command = self.rfile.readline(33)
        if command == b"status\n":
            response = self.server.state.encode("ascii") + b"\n"
        elif command == b"shutdown\n":
            response = b"accepted\n"
        else:
            response = b"rejected\n"
        self.wfile.write(response)
        self.wfile.flush()
        if command == b"shutdown\n":
            self.server.begin_shutdown()


def serve(root: Path) -> None:
    import fcntl
    from service_controller import BudBotServiceController

    directory = prepare_directory(root)
    descriptor = os.open(directory / "controller.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # Another launch already owns the controller.
        path = directory / "control.sock"
        if path.exists() or path.is_symlink():
            if not stat.S_ISSOCK(path.lstat().st_mode):
                raise ValueError("Unexpected runtime file")
            path.unlink()  # Stale socket; the exclusive lock proves no owner.
        controller = BudBotServiceController(repository_root=root)
        try:
            with RuntimeServer(path, controller.shutdown) as server:
                server.serve_forever(poll_interval=0.1)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "serve":
        raise SystemExit(2)
    try:
        serve(Path(sys.argv[2]).resolve())
    except Exception:
        raise SystemExit(1) from None
