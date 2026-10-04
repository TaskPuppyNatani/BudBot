import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service_controller import (
    DOCKER_COMMAND_TIMEOUT_SECONDS,
    LOCAL_WIDGET_URL,
    BudBotServiceController,
    BudBotServiceError,
)


class ServiceControllerTests(unittest.TestCase):
    def make_controller(self, root: Path, **kwargs) -> BudBotServiceController:
        return BudBotServiceController(
            repository_root=root, cache_dir=root / "cache", **kwargs
        )

    def test_creates_missing_env_once_and_preserves_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".env.example").write_text("DEV_DEFAULT=1\n")
            controller = self.make_controller(root)
            controller._prepare_configuration()
            self.assertEqual((root / ".env").read_text(), "DEV_DEFAULT=1\n")
            (root / ".env").write_text("USER_VALUE=preserve\n")
            controller._prepare_configuration()
            self.assertEqual((root / ".env").read_text(), "USER_VALUE=preserve\n")

    def test_compose_command_is_a_portable_argument_list(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder))
            command = controller._compose("stop", "backend", "db")
            self.assertEqual(command[:4], ["docker", "compose", "--project-name", "budbot"])
            self.assertEqual(command[-3:], ["stop", "backend", "db"])
            self.assertTrue(all(isinstance(part, str) for part in command))

    def test_daemon_error_instructions_match_platform(self) -> None:
        for operating_system, expected in (
            ("Windows", "Open Docker Desktop"),
            ("Linux", "Start the Docker daemon"),
        ):
            with self.subTest(platform=operating_system), tempfile.TemporaryDirectory() as folder:
                controller = self.make_controller(Path(folder), operating_system=operating_system)
                with patch("service_controller.shutil.which", return_value="docker"), patch.object(
                    controller,
                    "_run",
                    side_effect=["Compose v2", BudBotServiceError("daemon unavailable")],
                ):
                    with self.assertRaises(BudBotServiceError) as error:
                        controller._check_docker()
                self.assertIn(expected, str(error.exception))

    def test_process_execution_is_shell_free_and_windows_is_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder), operating_system="Windows")
            startup = SimpleNamespace(dwFlags=0)
            with patch("service_controller.subprocess.STARTUPINFO", return_value=startup, create=True), patch(
                "service_controller.subprocess.STARTF_USESHOWWINDOW", 1, create=True
            ), patch(
                "service_controller.subprocess.CREATE_NO_WINDOW", 0x08000000, create=True
            ), patch(
                "service_controller.subprocess.run",
                return_value=SimpleNamespace(stdout="running\n", returncode=0),
            ) as run:
                output = controller._run(["docker", "info"], "Docker failed")
            self.assertEqual(output, "running\n")
            self.assertFalse(run.call_args.kwargs["shell"])
            self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000000)
            self.assertIs(run.call_args.kwargs["startupinfo"], startup)
            self.assertEqual(run.call_args.kwargs["timeout"], DOCKER_COMMAND_TIMEOUT_SECONDS)
            self.assertEqual(startup.dwFlags, 1)

    def test_docker_command_timeout_is_actionable_and_preserves_output_in_log(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder))
            timeout = subprocess.TimeoutExpired(
                ["docker", "compose", "up"],
                DOCKER_COMMAND_TIMEOUT_SECONDS,
                output=b"still building\n",
            )
            with patch("service_controller.subprocess.run", side_effect=timeout):
                with self.assertRaisesRegex(BudBotServiceError, "timed out after 30 minutes") as error:
                    controller._run(["docker", "compose", "up"], "BudBot could not start.")

            self.assertIn("use Stop or Restart", str(error.exception))
            self.assertIn("still building", controller.log_file.read_text(encoding="utf-8"))

    def test_start_orchestrates_compose_and_persists_preview_url(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder))
            controller._check_docker = Mock()
            controller._prepare_configuration = Mock()
            controller._run = Mock(return_value="")
            controller._wait_ready = Mock()
            business_id = "12345678-1234-5678-1234-567812345678"
            controller.create_demo_business = Mock(return_value=business_id)
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            with patch("service_controller.urlopen", return_value=response):
                url = controller.start()
            self.assertEqual(
                url,
                f"http://127.0.0.1:8000/widget/?business_id={business_id}",
            )
            self.assertEqual(controller._run.call_args_list[0].args[0][-2:], ["config", "--quiet"])
            self.assertEqual(
                controller._run.call_args_list[1].args[0][-5:],
                ["up", "--detach", "--build", "db", "backend"],
            )
            controller._wait_ready.assert_called_once()
            controller.create_demo_business.assert_called_once()
            self.assertEqual(controller.preview_file.read_text().strip(), url)

    def test_stop_keeps_volumes_and_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder))
            controller._check_docker = Mock()
            controller._run = Mock(return_value="")
            controller.preview_file.write_text("http://localhost/demo")
            controller.stop()
            arguments = controller._run.call_args.args[0]
            self.assertEqual(arguments[-3:], ["stop", "backend", "db"])
            self.assertNotIn("down", arguments)
            self.assertNotIn("-v", arguments)
            self.assertFalse(controller.preview_file.exists())

    def test_preview_url_business_id_parser_accepts_uuid_only(self) -> None:
        url = "http://127.0.0.1:8000/widget/?business_id=12345678-1234-5678-1234-567812345678"
        self.assertEqual(
            BudBotServiceController._business_id_from_url(url),
            "12345678-1234-5678-1234-567812345678",
        )
        with self.assertRaises(BudBotServiceError):
            BudBotServiceController._business_id_from_url("https://example.com/?business_id=not-a-uuid")

    def test_detection_ignores_protected_business_401_and_preserves_preview(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder))
            url = "http://127.0.0.1:8000/widget/?business_id=12345678-1234-5678-1234-567812345678"
            controller.preview_file.write_text(url + "\n")
            response = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))

            def probe(request, **kwargs):
                target = request if isinstance(request, str) else request.full_url
                if "/api/v1/businesses/" in target:
                    raise HTTPError(target, 401, "Authentication is required.", {}, None)
                return response

            with patch("service_controller.urlopen", side_effect=probe) as opened:
                self.assertEqual(controller.detect_running(), url)
            self.assertEqual(controller.preview_file.read_text(), url + "\n")
            self.assertEqual([call.args[0] for call in opened.call_args_list],
                ["http://127.0.0.1:8000/ready", "http://127.0.0.1:8000/widget/"])
            self.assertTrue(all(call.kwargs["timeout"] == 1.5 for call in opened.call_args_list))

    def test_running_detection_without_cache_never_seeds_or_runs_compose(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder))
            controller.create_demo_business = Mock()
            controller._run = Mock()
            response = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
            with patch("service_controller.urlopen", return_value=response):
                self.assertEqual(controller.detect_running(), LOCAL_WIDGET_URL)
                # Repeat detection just as closing/reopening Control Center does.
                self.assertEqual(controller.detect_running(), LOCAL_WIDGET_URL)
            controller.create_demo_business.assert_not_called()
            controller._run.assert_not_called()
            self.assertFalse(controller.preview_file.exists())

    def test_detection_recovers_selected_business_without_preview_cache(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder))
            business_id = "12345678-1234-5678-1234-567812345678"
            controller.selected_business_file.write_text(business_id + "\n")
            response = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
            with patch("service_controller.urlopen", return_value=response):
                self.assertEqual(controller.detect_running(), f"{LOCAL_WIDGET_URL}?business_id={business_id}")
            self.assertFalse(controller.preview_file.exists())
            controller.selected_business_file.write_text("not-a-uuid")
            with patch("service_controller.urlopen", return_value=response):
                self.assertEqual(controller.detect_running(), LOCAL_WIDGET_URL)

    def test_unavailable_service_returns_stopped_without_erasing_valid_preview(self) -> None:
        for error in (URLError("connection refused"), HTTPError(LOCAL_WIDGET_URL, 503, "Starting", {}, None)):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as folder:
                controller = self.make_controller(Path(folder))
                saved = f"{LOCAL_WIDGET_URL}?business_id=12345678-1234-5678-1234-567812345678\n"
                controller.preview_file.write_text(saved)
                with patch("service_controller.urlopen", side_effect=error):
                    self.assertIsNone(controller.detect_running())
                self.assertEqual(controller.preview_file.read_text(), saved)

    def test_malformed_or_unsafe_cache_is_discarded_but_not_service_health(self) -> None:
        business_id = "12345678-1234-5678-1234-567812345678"
        unsafe = [
            "not a URL", f"https://example.test/widget/?business_id={business_id}",
            f"http://user:password@127.0.0.1:8000/widget/?business_id={business_id}",
            f"http://127.0.0.1:9000/widget/?business_id={business_id}",
            f"http://127.0.0.1:bad/widget/?business_id={business_id}",
            f"{LOCAL_WIDGET_URL}?business_id=not-a-uuid", f"{LOCAL_WIDGET_URL}?business_id={business_id}#unsafe",
            f"{LOCAL_WIDGET_URL}?business_id={business_id}&business_id={business_id}",
            f"{LOCAL_WIDGET_URL}?business_id={business_id}&extra=data", "x" * 4097,
        ]
        for saved in unsafe:
            with self.subTest(saved=saved[:100]), tempfile.TemporaryDirectory() as folder:
                controller = self.make_controller(Path(folder))
                controller.preview_file.write_text(saved)
                response = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
                with patch("service_controller.urlopen", return_value=response) as opened:
                    self.assertEqual(controller.detect_running(), LOCAL_WIDGET_URL)
                self.assertFalse(controller.preview_file.exists())
                self.assertEqual([call.args[0] for call in opened.call_args_list],
                    ["http://127.0.0.1:8000/ready", LOCAL_WIDGET_URL])

    def test_non_utf8_cache_is_rejected_safely(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder))
            controller.preview_file.write_bytes(b"\xff")
            response = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
            with patch("service_controller.urlopen", return_value=response):
                self.assertEqual(controller.detect_running(), LOCAL_WIDGET_URL)
            self.assertFalse(controller.preview_file.exists())

    def test_widget_probe_failure_preserves_valid_preview(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder))
            saved = f"{LOCAL_WIDGET_URL}?business_id=12345678-1234-5678-1234-567812345678\n"
            controller.preview_file.write_text(saved)
            response = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
            with patch("service_controller.urlopen", side_effect=[response, URLError("transient widget failure")]):
                self.assertIsNone(controller.detect_running())
            self.assertEqual(controller.preview_file.read_text(), saved)

    def test_restart_stops_then_starts_without_replacing_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder))
            calls = []
            controller.stop = Mock(side_effect=lambda: calls.append("stop"))
            controller.start = Mock(side_effect=lambda: (calls.append("start"), LOCAL_WIDGET_URL)[1])
            self.assertEqual(controller.restart(), LOCAL_WIDGET_URL)
            self.assertEqual(calls, ["stop", "start"])

    def test_startup_reports_a_backend_container_that_is_restarting(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            controller = self.make_controller(Path(folder))
            with patch("service_controller.urlopen", side_effect=URLError("offline")), patch.object(
                controller,
                "_run",
                return_value='{"Name":"budbot-backend-1","State":"restarting"}',
            ):
                with self.assertRaisesRegex(BudBotServiceError, "backend container is restarting"):
                    controller._wait_ready()


if __name__ == "__main__":
    unittest.main()
