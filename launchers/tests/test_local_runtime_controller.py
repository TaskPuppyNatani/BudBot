"""Local IPC tests use temporary sockets and a fake Docker executable only."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_runtime_controller import RuntimeServer, ensure_running, prepare_directory, request_status
from service_controller import BudBotServiceController


def exchange(path, payload):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(str(path))
        connection.sendall(payload)
        return connection.makefile("rb").readline(64)


class LocalRuntimeTests(unittest.TestCase):
    def test_fixed_shutdown_has_no_volume_image_or_arbitrary_command_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = BudBotServiceController(Path(folder), cache_dir=Path(folder) / "cache")
            with patch.object(controller, "_run") as run:
                controller.shutdown()
            self.assertEqual(run.call_args.args[0], ["docker", "compose", "--project-name", "budbot", "-f",
                                                    str(Path(folder) / "docker-compose.dev.yml"), "down"])
            self.assertEqual(run.call_args.kwargs, {"timeout": 120, "record_output": False})

    def test_private_socket_rejects_commands_and_shutdown_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = prepare_directory(Path(folder))
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            path = directory / "control.sock"
            entered, release = threading.Event(), threading.Event()
            action = Mock(side_effect=lambda: (entered.set(), release.wait(3)))
            with RuntimeServer(path, action, delay=0) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(exchange(path, b"status\n"), b"running\n")
                    for command in (b"down -v\n", b"shutdown; echo unsafe\n", b"x" * 33, b'{"action":"shutdown"}\n'):
                        self.assertEqual(exchange(path, command), b"rejected\n")
                    action.assert_not_called()
                    self.assertEqual(exchange(path, b"shutdown\n"), b"accepted\n")
                    self.assertTrue(entered.wait(1))
                    self.assertEqual(exchange(path, b"status\n"), b"stopping\n")
                    self.assertEqual(exchange(path, b"shutdown\n"), b"accepted\n")
                    self.assertEqual(action.call_count, 1)
                finally:
                    release.set()
                    server.shutdown()
                    thread.join(2)

    def test_controller_start_is_detached_and_reuses_an_existing_controller(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("local_runtime_controller.request_status", side_effect=[None, "running"]), \
                 patch("local_runtime_controller.subprocess.Popen") as process:
                self.assertIsNone(ensure_running(root))
            self.assertTrue(process.call_args.kwargs["start_new_session"])
            self.assertTrue(process.call_args.kwargs["close_fds"])
            self.assertNotIn("shell", process.call_args.kwargs)
            with patch("local_runtime_controller.request_status", return_value="running"), \
                 patch("local_runtime_controller.subprocess.Popen") as process:
                self.assertIsNone(ensure_running(root))
                process.assert_not_called()

    def test_symlink_runtime_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "backend").mkdir()
            (root / "outside").mkdir()
            (root / "backend/.budbot-runtime").symlink_to(root / "outside", target_is_directory=True)
            with self.assertRaises(ValueError):
                prepare_directory(root)

    def test_detached_server_process_stops_only_the_fake_project_and_exits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binary = root / "bin"
            binary.mkdir()
            docker = binary / "docker"
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$BUDBOT_TEST_CAPTURE"\n')
            docker.chmod(0o755)
            capture = root / "docker-arguments.txt"
            script = Path(__file__).resolve().parents[1] / "local_runtime_controller.py"
            process = subprocess.Popen([sys.executable, str(script), "serve", str(root)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "PATH": str(binary) + os.pathsep + os.environ.get("PATH", ""),
                     "BUDBOT_TEST_CAPTURE": str(capture), "XDG_CACHE_HOME": str(root / "cache")})
            path = root / "backend/.budbot-runtime/control.sock"
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and request_status(path) != "running":
                    time.sleep(0.02)
                self.assertEqual(request_status(path), "running")
                self.assertEqual(exchange(path, b"shutdown\n"), b"accepted\n")
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertEqual(capture.read_text().splitlines(), ["compose", "--project-name", "budbot", "-f",
                    str(root / "docker-compose.dev.yml"), "down"])
                self.assertFalse(path.exists())
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
