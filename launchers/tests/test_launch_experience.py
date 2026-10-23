"""Deterministic Admin launch, optional AI diagnostics, and menu integration."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_ai_probe
import service_controller
from service_controller import BudBotServiceController, BudBotServiceError, LOCAL_ADMIN_URL


class LaunchExperienceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.env = self.root / ".env"
        self.env.write_text("PRIVATE_TEST_VALUE=synthetic-secret\n")
        self.controller = BudBotServiceController(self.root, cache_dir=self.root / "cache")

    def prepare_launch(self, running=False):
        self.controller._check_docker = Mock()
        self.controller._run = Mock(return_value="")
        self.controller._probe_ready = Mock(return_value=running)
        self.controller._wait_ready = Mock()
        self.controller.create_demo_business = Mock()
        self.controller._prepare_configuration = Mock()

    def test_fresh_launch_starts_existing_compose_waits_and_preserves_configuration(self):
        self.prepare_launch()
        before = self.env.read_bytes()
        self.assertEqual(self.controller.launch(), LOCAL_ADMIN_URL)
        calls = self.controller._run.call_args_list
        self.assertEqual(calls[0].args[0][-2:], ["config", "--quiet"])
        self.assertEqual(calls[1].args[0][-5:], ["up", "--detach", "--build", "db", "backend"])
        self.assertTrue(all(call.kwargs["record_output"] is False for call in calls))
        self.controller._wait_ready.assert_called_once_with(LOCAL_ADMIN_URL, record_output=False)
        self.controller._prepare_configuration.assert_not_called()
        self.controller.create_demo_business.assert_not_called()
        self.assertEqual(self.env.read_bytes(), before)

    def test_already_running_reuses_stack_without_build_or_seed(self):
        self.prepare_launch(running=True)
        self.assertEqual(self.controller.launch(), LOCAL_ADMIN_URL)
        self.assertEqual(self.controller._run.call_count, 1)  # config --quiet only
        self.controller._wait_ready.assert_not_called()
        self.controller.create_demo_business.assert_not_called()

    def test_missing_configuration_is_actionable_and_is_not_generated(self):
        self.prepare_launch()
        self.env.unlink()
        with self.assertRaisesRegex(BudBotServiceError, "copy .env.example to .env"):
            self.controller.launch()
        self.assertFalse(self.env.exists())
        self.controller._run.assert_not_called()
        self.controller._prepare_configuration.assert_not_called()

    def test_docker_missing_prevents_startup(self):
        with patch("service_controller.shutil.which", return_value=None), patch.object(self.controller, "_run") as run:
            with self.assertRaisesRegex(BudBotServiceError, "Docker was not found"):
                self.controller.launch()
        run.assert_not_called()

    def test_readiness_requires_database_and_admin_shell(self):
        response = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
        with patch("service_controller.urlopen", return_value=response) as opened:
            self.controller._wait_ready(LOCAL_ADMIN_URL)
        self.assertEqual([call.args[0] for call in opened.call_args_list],
                         ["http://127.0.0.1:8000/ready", LOCAL_ADMIN_URL])
        with patch("service_controller.urlopen", side_effect=[response, URLError("not ready")]):
            self.assertFalse(self.controller._probe_ready(LOCAL_ADMIN_URL))

    def test_readiness_polls_then_succeeds_and_bounds_status_commands(self):
        with patch.object(self.controller, "_probe_ready", side_effect=[False, True]), \
             patch.object(self.controller, "_run", return_value='{"State":"running"}') as run, \
             patch("service_controller.time.sleep"):
            self.controller._wait_ready(LOCAL_ADMIN_URL, record_output=False)
        self.assertEqual(run.call_args.kwargs["timeout"], 10)
        self.assertFalse(run.call_args.kwargs["record_output"])
        self.assertIn("--all", run.call_args.args[0])

    def test_readiness_timeout_is_bounded_and_actionable(self):
        with patch.object(self.controller, "_probe_ready", return_value=False), \
             patch.object(self.controller, "_run", return_value='{"State":"running"}'), \
             patch("service_controller.time.monotonic", side_effect=[0, 0, 901]), \
             patch("service_controller.time.sleep"):
            with self.assertRaisesRegex(BudBotServiceError, "within 15 minutes") as error:
                self.controller._wait_ready(LOCAL_ADMIN_URL)
        self.assertIn("logs backend db", str(error.exception))

    def test_launch_subprocess_failures_do_not_log_or_display_docker_output(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout):
                result = SimpleNamespace(stdout="synthetic-secret", returncode=1)
                error = subprocess.TimeoutExpired(["docker"], 10, output=b"synthetic-secret")
                with patch("service_controller.subprocess.run", side_effect=error if timeout else None,
                           return_value=result):
                    with self.assertRaises(BudBotServiceError) as caught:
                        self.controller._run(["docker", "compose", "up"], "Check Docker and port conflicts.",
                                             timeout=10, record_output=False)
                self.assertNotIn("synthetic-secret", str(caught.exception))
                self.assertNotIn("synthetic-secret", self.controller.log_file.read_text())

    def run_main(self, controller, action="launch", opened=True):
        output = io.StringIO()
        with patch("service_controller.BudBotServiceController", return_value=controller), \
             patch("service_controller.webbrowser.open", return_value=opened) as browser, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = service_controller.main([action])
        return code, output.getvalue(), browser

    def test_browser_opens_only_after_successful_readiness_and_ai_is_optional(self):
        controller = Mock()
        events = []
        controller.launch.side_effect = lambda: (events.append("ready"), LOCAL_ADMIN_URL)[1]
        controller.local_ai_warning.return_value = "Compatible AI is unavailable; BudBot is running."
        output = io.StringIO()
        with patch("service_controller.BudBotServiceController", return_value=controller), \
             patch("service_controller.webbrowser.open", side_effect=lambda *a, **kw: events.append("browser") or True) as browser, \
             contextlib.redirect_stdout(output):
            self.assertEqual(service_controller.main(["launch"]), 0)
        self.assertEqual(events, ["ready", "browser"])
        browser.assert_called_once_with(LOCAL_ADMIN_URL, new=2)
        self.assertIn("WARNING:", output.getvalue())
        self.assertNotIn("synthetic-secret", output.getvalue())

    def test_startup_failure_or_cancellation_never_opens_browser_or_stops_services(self):
        for error, expected in [(BudBotServiceError("Check Docker."), 1), (KeyboardInterrupt(), 130)]:
            with self.subTest(error=type(error).__name__):
                controller = Mock()
                controller.launch.side_effect = error
                code, output, browser = self.run_main(controller)
                self.assertEqual(code, expected)
                browser.assert_not_called()
                controller.local_ai_warning.assert_not_called()
                controller.stop.assert_not_called()
                self.assertNotIn("Traceback", output)

    def test_browser_block_reports_url_and_desktop_error_window_handles_eof(self):
        controller = Mock()
        controller.launch.return_value = LOCAL_ADMIN_URL
        controller.local_ai_warning.return_value = None
        with patch("service_controller.sys.stdin.isatty", return_value=True), \
             patch("builtins.input", side_effect=EOFError) as prompt:
            code, output, _ = self.run_main(controller, "launch-desktop", opened=False)
        self.assertEqual(code, 0)
        self.assertIn(f"Open {LOCAL_ADMIN_URL} manually", output)
        prompt.assert_called_once()

    def test_optional_probe_uses_backend_network_and_never_echoes_unexpected_output(self):
        for status, warning in [("reachable", False), ("not-configured", False),
                                ("unavailable", True), ("not-approved", True), ("synthetic-secret", True)]:
            with self.subTest(status=status), patch.object(self.controller, "_run", return_value=status) as run:
                result = self.controller.local_ai_warning()
                self.assertEqual(bool(result), warning)
                self.assertNotIn("synthetic-secret", result or "")
                args = run.call_args.args[0]
                self.assertEqual(args[6:12], ["exec", "-T", "backend", "python", "-c", args[-1]])
                self.assertEqual(run.call_args.kwargs, {"timeout": 10, "record_output": False})
        with patch.object(self.controller, "_run", side_effect=BudBotServiceError("unavailable")):
            self.assertIn("could not be checked", self.controller.local_ai_warning())

    def test_menu_installer_uses_user_local_location_and_current_checkout(self):
        root = self.root / 'checkout with spaces % and "quotes"'
        (root / "launchers").mkdir(parents=True)
        (root / "launchers/service_controller.py").touch()
        data = self.root / "user-data"
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(data)}):
            entry = service_controller.install_desktop(root)
        self.assertEqual(entry, data / "applications/budbot.desktop")
        contents = entry.read_text()
        self.assertIn("Name=BudBot\n", contents)
        self.assertIn("Terminal=true", contents)
        self.assertIn("launch-desktop", contents)
        self.assertIn("spaces %%", contents)
        self.assertIn('\\\\"quotes\\\\"', contents)
        self.assertNotIn("sh -c", contents)
        self.assertIn(f"Path={root}", contents)

    def test_shell_entry_reuses_controller_from_any_directory(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        python = fake_bin / "python3"
        python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        python.chmod(0o755)
        script = Path(__file__).resolve().parents[2] / "scripts/start_budbot.sh"
        for args, action in [([], "launch"), (["--install-desktop"], "install-desktop"), (["preview.txt"], "start")]:
            with self.subTest(args=args):
                result = subprocess.run([str(script), *args], cwd=self.root, text=True, capture_output=True,
                                        env={**os.environ, "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", "")})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines()[1], action)


class LocalAIProbeTests(unittest.TestCase):
    endpoint = "http://host.docker.internal:1234/v1"

    def test_probe_contacts_only_allowlisted_destinations_and_uses_no_inference(self):
        connection = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
        with patch("local_ai_probe.socket.create_connection", return_value=connection) as connect:
            self.assertEqual(local_ai_probe.probe_endpoints([], ()), "not-configured")
            self.assertEqual(local_ai_probe.probe_endpoints([self.endpoint], ()), "not-approved")
            connect.assert_not_called()
            self.assertEqual(local_ai_probe.probe_endpoints([self.endpoint], (self.endpoint,)), "reachable")
        connect.assert_called_once_with(("host.docker.internal", 1234), timeout=1)

    def test_unreachable_endpoint_and_diagnostic_errors_are_safe(self):
        with patch("local_ai_probe.socket.create_connection", side_effect=OSError("synthetic-secret")):
            self.assertEqual(local_ai_probe.probe_endpoints([self.endpoint], (self.endpoint,)), "unavailable")
        output = io.StringIO()
        with patch("local_ai_probe.configured_endpoints", new=AsyncMock(side_effect=RuntimeError("synthetic-secret"))), \
             contextlib.redirect_stdout(output):
            local_ai_probe.main()
        self.assertEqual(output.getvalue(), "unknown\n")


if __name__ == "__main__":
    unittest.main()
