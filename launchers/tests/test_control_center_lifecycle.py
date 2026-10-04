from __future__ import annotations

import queue
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from branding_client import BrandingAuthenticationRequired, BrandingClientError
from control_center import BudBotControlCenter, MAX_EVENTS_PER_POLL
from service_controller import BudBotServiceController, BudBotServiceError, LOCAL_WIDGET_URL

BUSINESS_ID = "12345678-1234-5678-1234-567812345678"
PREVIEW_URL = f"http://127.0.0.1:8000/widget/?business_id={BUSINESS_ID}"
BUSINESSES = [{"id": BUSINESS_ID, "display_name": "Demo Business"}]
BRANDING = {
    "business": {"display_name": "Demo Business", "logo_reference": None},
    "assistant": {
        "display_name": "BudBot",
        "greeting": "Hello",
        "avatar_reference": None,
    },
}


def make_center(**attributes):
    center = object.__new__(BudBotControlCenter)
    center.busy = False
    center._close_after_operation = False
    center._window_closed = False
    center._reporting_callback_error = False
    center._poll_after_id = None
    center.events = queue.Queue()
    center.progress = Mock()
    center._set_status = Mock()
    center._refresh_buttons = Mock()
    center.preview_url = None
    center.destroy = Mock()
    center.after_cancel = Mock()
    center.controller = Mock()
    for name, value in attributes.items():
        setattr(center, name, value)
    return center


def make_stateful_center(**attributes):
    center = make_center(
        state="Starting",
        business_id=None,
        message_label=Mock(),
        status_label=Mock(),
        status_dot=Mock(),
        status_circle="circle",
        business_combo=Mock(),
        start_button=Mock(),
        stop_button=Mock(),
        restart_button=Mock(),
        open_button=Mock(),
        save_button=Mock(),
        after=Mock(return_value="poll-next"),
    )
    center._set_status = BudBotControlCenter._set_status.__get__(center)
    center._refresh_buttons = BudBotControlCenter._refresh_buttons.__get__(center)
    center._apply_businesses = Mock()
    center._apply_branding = Mock()
    center._show_page = Mock()
    center._open_preview = Mock()
    for name, value in attributes.items():
        setattr(center, name, value)
    return center


class ControlCenterLifecycleTests(unittest.TestCase):
    def test_close_while_busy_closes_after_completion_and_keeps_services_running(self) -> None:
        message_label = Mock()
        center = make_center(
            busy=True,
            message_label=message_label,
            _poll_after_id="poll-1",
        )

        center._close()

        self.assertTrue(center._close_after_operation)
        center.destroy.assert_not_called()
        center.controller.stop.assert_not_called()
        message_label.configure.assert_called_once()

        center.events.put(("service_done", {"state": "Stopped"}))
        center._poll_events()

        # The poll callback is already running, so it has no pending timer to cancel.
        center.after_cancel.assert_not_called()
        center.destroy.assert_called_once()
        center.controller.stop.assert_not_called()

    def test_close_when_idle_destroys_window_without_stopping_services(self) -> None:
        center = make_center(_poll_after_id="poll-2")
        center._is_dirty = Mock(return_value=False)

        center._close()

        center.after_cancel.assert_called_once_with("poll-2")
        center.destroy.assert_called_once()
        center.controller.stop.assert_not_called()

    def test_close_can_be_cancelled_when_branding_has_unsaved_changes(self) -> None:
        center = make_center()
        center._is_dirty = Mock(return_value=True)
        with patch("control_center.messagebox.askyesno", return_value=False):
            center._close()

        center.destroy.assert_not_called()
        self.assertFalse(center._window_closed)

    def test_unexpected_detection_worker_exception_is_delivered_to_gui_queue(self) -> None:
        center = make_center()
        center.controller.detect_running.side_effect = RuntimeError("probe failed")

        center._detect_worker()

        kind, message = center.events.get_nowait()
        self.assertEqual(kind, "detection_error")
        self.assertIn("probe failed", message)

    def test_unexpected_branding_worker_exception_is_delivered_to_gui_queue(self) -> None:
        center = make_center()
        center.branding_client = Mock()
        center.branding_client.save.side_effect = RuntimeError("save failed")

        center._branding_worker("save", "business-id", {})

        kind, message = center.events.get_nowait()
        self.assertEqual(kind, "branding_error")
        self.assertIn("save failed", message)

    def test_poll_callback_reports_event_handler_errors_and_is_rescheduled(self) -> None:
        center = make_center(busy=True)
        center.events.put(("progress", "Checking Docker…"))
        center.message_label = Mock()
        center.message_label.configure.side_effect = RuntimeError("widget update failed")
        center.after = Mock(return_value="poll-next")

        with patch("control_center.messagebox.showerror") as showerror:
            center._poll_events()

        self.assertTrue(center.busy)  # The service worker is still in flight.
        showerror.assert_called_once()
        self.assertIn("widget update failed", showerror.call_args.args[1])
        center.after.assert_called_once_with(100, center._poll_events)
        self.assertEqual(center._poll_after_id, "poll-next")

    def test_fresh_start_completion_enables_save_stop_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            center = make_stateful_center()
            center.controller.start.return_value = PREVIEW_URL
            center.controller._business_id_from_url.return_value = BUSINESS_ID
            center.controller._valid_uuid.return_value = True
            center.controller.preview_file = Path(folder) / "preview-url.txt"
            center.controller.selected_business_file = Path(folder) / "selected-business.txt"
            center._load_business_data = Mock(return_value=(BUSINESS_ID, BUSINESSES, BRANDING, b"", b""))

            center._service_worker("start")
            center._poll_events()

        self.assertFalse(center.busy)
        self.assertEqual(center.state, "Running")
        center.start_button.set_enabled.assert_called_once_with(False)
        center.stop_button.set_enabled.assert_called_once_with(True)
        center.restart_button.set_enabled.assert_called_once_with(True)
        center.save_button.set_enabled.assert_called_once_with(True)

    def test_fresh_start_failure_clears_busy_and_keeps_recovery_actions_available(self) -> None:
        center = make_stateful_center(busy=True)
        center.controller.start.side_effect = BudBotServiceError("Docker is unavailable")

        center._service_worker("start")
        with patch("control_center.messagebox.showerror"):
            center._poll_events()

        self.assertFalse(center.busy)
        self.assertEqual(center.state, "Error")
        center.start_button.set_enabled.assert_called_once_with(True)
        center.stop_button.set_enabled.assert_called_once_with(True)
        center.restart_button.set_enabled.assert_called_once_with(True)
        center.save_button.set_enabled.assert_called_once_with(False)

    def test_reconnect_completion_enables_save_stop_and_restart(self) -> None:
        center = make_stateful_center(busy=True)
        center.controller.detect_running.return_value = PREVIEW_URL
        center.controller._business_id_from_url.return_value = BUSINESS_ID
        center.branding_client = Mock()
        center.branding_client.list_businesses.return_value = BUSINESSES
        center._load_business_data = Mock(return_value=(BUSINESS_ID, BUSINESSES, BRANDING, b"", b""))

        center._detect_worker()
        center._poll_events()

        self.assertFalse(center.busy)
        self.assertEqual(center.state, "Running")
        center.start_button.set_enabled.assert_called_once_with(False)
        center.stop_button.set_enabled.assert_called_once_with(True)
        center.restart_button.set_enabled.assert_called_once_with(True)
        center.save_button.set_enabled.assert_called_once_with(True)

    def test_reconnect_branding_failure_clears_busy_and_keeps_recovery_actions_available(self) -> None:
        center = make_stateful_center(busy=True)
        center.controller.detect_running.return_value = PREVIEW_URL
        center.controller._business_id_from_url.return_value = BUSINESS_ID
        center.branding_client = Mock()
        center.branding_client.list_businesses.side_effect = BrandingClientError("branding unavailable")

        center._detect_worker()
        with patch("control_center.messagebox.showerror") as showerror:
            center._poll_events()

        self.assertFalse(center.busy)
        self.assertEqual(center.state, "Error")
        showerror.assert_called_once()
        self.assertIn("branding unavailable", showerror.call_args.args[1])
        center.start_button.set_enabled.assert_called_once_with(True)
        center.stop_button.set_enabled.assert_called_once_with(True)
        center.restart_button.set_enabled.assert_called_once_with(True)
        center.save_button.set_enabled.assert_called_once_with(False)

    def test_startup_and_reconnect_use_only_an_authorized_business_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            center = make_center()
            center.branding_client = Mock()
            center.branding_client.list_businesses.return_value = BUSINESSES
            center.branding_client.load.return_value = BRANDING
            center.controller.preview_file = Path(folder) / "preview.txt"
            center.controller.selected_business_file = Path(folder) / "selected.txt"

            center._finish_started_service("start", PREVIEW_URL, "stale-demo-business")
            kind, payload = center.events.get_nowait()
            self.assertEqual(kind, "service_done")
            self.assertEqual(payload["business_id"], BUSINESS_ID)
            self.assertEqual(payload["url"], PREVIEW_URL)
            self.assertEqual(center.controller.preview_file.read_text().strip(), PREVIEW_URL)
            self.assertEqual(
                [call.args[0] for call in center.branding_client.load.call_args_list],
                [BUSINESS_ID],
            )

            center.branding_client.load.reset_mock()
            center._finish_detected_stack(PREVIEW_URL, "stale-demo-business")
            kind, payload = center.events.get_nowait()
            self.assertEqual(kind, "detected")
            self.assertEqual(payload["business_id"], BUSINESS_ID)
            self.assertEqual(payload["url"], PREVIEW_URL)
            center.branding_client.load.assert_called_once_with(BUSINESS_ID)
            self.assertEqual(center.controller.selected_business_file.read_text().strip(), BUSINESS_ID)

    def test_missing_admin_sign_in_unblocks_controls_for_running_services(self) -> None:
        center = make_stateful_center(busy=True, state="Starting")
        with patch("control_center.messagebox.showerror") as showerror:
            center._finish_auth_unavailable(
                {"operation": "service", "action": "start"},
                "Owner sign-in was canceled.",
            )

        self.assertFalse(center.busy)
        self.assertEqual(center.state, "Running")
        center.stop_button.set_enabled.assert_called_once_with(True)
        center.restart_button.set_enabled.assert_called_once_with(True)
        center.save_button.set_enabled.assert_called_once_with(False)
        showerror.assert_called_once()

    def test_detection_runs_even_without_preview_cache(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            center = make_stateful_center(state="Stopped")
            center.controller.preview_file = Path(folder) / "missing-preview.txt"
            center._dispatch_worker = Mock()
            center._detect_existing_stack()
            self.assertTrue(center.busy)
            self.assertEqual(center.state, "Starting")
            center._dispatch_worker.assert_called_once()
            self.assertEqual(center._dispatch_worker.call_args.args[0], center._detect_worker)

    def test_running_detection_needs_no_admin_login_or_seed_for_service_status(self) -> None:
        for cached in (False, True):
            with self.subTest(cached=cached), tempfile.TemporaryDirectory() as folder:
                center = make_stateful_center(busy=True)
                center.controller = BudBotServiceController(Path(folder), cache_dir=Path(folder) / "cache")
                center.controller.create_demo_business = Mock()
                center.controller._run = Mock()
                if cached:
                    center.controller.preview_file.write_text(PREVIEW_URL + "\n")
                center._load_business_data = Mock(side_effect=BrandingAuthenticationRequired("Sign in for branding."))
                center._request_admin_login = Mock(side_effect=lambda pending: center.events.put(("auth_cancelled", pending)))
                response = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
                with patch("service_controller.urlopen", return_value=response), patch("control_center.messagebox.showerror"):
                    center._detect_worker()
                    center._poll_events()
                self.assertEqual(center.state, "Running")
                self.assertFalse(center.busy)
                self.assertIsNone(center.business_id)
                self.assertEqual(center.preview_url, PREVIEW_URL if cached else LOCAL_WIDGET_URL)
                center.stop_button.set_enabled.assert_called_with(True)
                center.restart_button.set_enabled.assert_called_with(True)
                center.open_button.set_enabled.assert_called_with(True)
                center.save_button.set_enabled.assert_called_with(False)
                center.controller.create_demo_business.assert_not_called()
                center.controller._run.assert_not_called()
                if cached:
                    self.assertEqual(center.controller.preview_file.read_text().strip(), PREVIEW_URL)

    def test_cacheless_detection_can_load_an_existing_authorized_business(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            center = make_stateful_center(busy=True)
            center.controller = BudBotServiceController(Path(folder), cache_dir=Path(folder) / "cache")
            center.controller.create_demo_business = Mock()
            center._load_business_data = Mock(return_value=(BUSINESS_ID, BUSINESSES, BRANDING, b"", b""))
            response = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
            with patch("service_controller.urlopen", return_value=response):
                center._detect_worker()
                center._poll_events()
            self.assertEqual(center.state, "Running")
            self.assertEqual(center.preview_url, PREVIEW_URL)
            self.assertEqual(center.controller.preview_file.read_text().strip(), PREVIEW_URL)
            center._load_business_data.assert_called_once_with("")
            center.controller.create_demo_business.assert_not_called()

    def test_stopped_detection_finishes_without_requiring_authentication(self) -> None:
        center = make_stateful_center(busy=True)
        center.controller.detect_running.return_value = None
        center._load_business_data = Mock()
        center._detect_worker()
        center._poll_events()
        self.assertEqual(center.state, "Stopped")
        self.assertFalse(center.busy)
        center._load_business_data.assert_not_called()
        center.start_button.set_enabled.assert_called_once_with(True)
        center.stop_button.set_enabled.assert_called_once_with(False)

    def test_startup_requires_explicit_admin_authentication(self) -> None:
        center = make_center(controller=Mock())
        center._load_business_data = Mock(
            side_effect=BrandingAuthenticationRequired("sign in required")
        )

        center._finish_started_service("start", PREVIEW_URL, BUSINESS_ID)

        kind, pending = center.events.get_nowait()
        self.assertEqual(kind, "auth_required")
        self.assertEqual(pending["operation"], "service")
        self.assertEqual(pending["business_id"], BUSINESS_ID)

    def test_start_completion_handler_exception_is_visible_and_recoverable(self) -> None:
        center = make_stateful_center(busy=True)
        center._apply_branding.side_effect = RuntimeError("Tk branding update failed")
        center.events.put(("service_done", {
            "state": "Running",
            "action": "start",
            "url": PREVIEW_URL,
            "business_id": BUSINESS_ID,
            "businesses": BUSINESSES,
            "branding": BRANDING,
            "logo": b"",
            "avatar": b"",
        }))

        with patch("control_center.messagebox.showerror") as showerror:
            center._poll_events()

        self.assertFalse(center.busy)
        self.assertEqual(center.state, "Error")
        self.assertIn("Tk branding update failed", center.message_label.configure.call_args.kwargs["text"])
        showerror.assert_called_once()
        center.stop_button.set_enabled.assert_called_once_with(True)
        center.restart_button.set_enabled.assert_called_once_with(True)
        center.save_button.set_enabled.assert_called_once_with(False)

    def test_poll_callback_bounds_queue_work_and_reschedules_remaining_events(self) -> None:
        message_label = Mock()
        center = make_center(message_label=message_label, after=Mock(return_value="poll-next"))
        for index in range(MAX_EVENTS_PER_POLL + 1):
            center.events.put(("progress", f"Working {index}"))

        center._poll_events()

        self.assertEqual(message_label.configure.call_count, MAX_EVENTS_PER_POLL)
        self.assertEqual(center.events.qsize(), 1)
        center.after.assert_called_once_with(100, center._poll_events)
        self.assertEqual(center._poll_after_id, "poll-next")

    def test_worker_progress_callback_only_enqueues_for_main_thread(self) -> None:
        center = make_center()
        center.status_label = Mock()
        worker = threading.Thread(target=center._progress_from_worker, args=("Building…",))

        worker.start()
        worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(center.events.get_nowait(), ("progress", "Building…"))
        center.status_label.configure.assert_not_called()

    def test_service_action_is_dispatched_to_a_worker_thread(self) -> None:
        center = make_center(state="Stopped", _service_worker=Mock())
        with patch("control_center.threading.Thread") as thread_factory:
            center._begin_service("start")

        thread_factory.assert_called_once_with(
            target=center._service_worker, args=("start",), daemon=True
        )
        thread_factory.return_value.start.assert_called_once()
        center.controller.start.assert_not_called()

    def test_browser_launch_is_dispatched_to_a_worker_thread(self) -> None:
        url = "http://127.0.0.1:8000/widget/?business_id=demo"
        center = make_center(state="Running", preview_url=url)
        with patch("control_center.threading.Thread") as thread_factory, patch(
            "control_center.webbrowser.open"
        ) as browser_open:
            center.open_budbot()

        thread_factory.assert_called_once_with(
            target=center._browser_worker, args=(url,), daemon=True
        )
        thread_factory.return_value.start.assert_called_once()
        browser_open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
