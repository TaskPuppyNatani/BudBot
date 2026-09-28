import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from urllib.error import URLError
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service_controller import (
    DOCKER_COMMAND_TIMEOUT_SECONDS,
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
