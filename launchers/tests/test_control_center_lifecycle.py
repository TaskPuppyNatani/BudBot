from __future__ import annotations

import queue
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import BudBotControlCenter, MAX_EVENTS_PER_POLL


def make_center(**attributes):
    center = object.__new__(BudBotControlCenter)
    center.busy = False
    center._close_after_operation = False
    center._window_closed = False
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

    def test_poll_callback_is_rescheduled_even_if_an_event_handler_raises(self) -> None:
        center = make_center(busy=True)
        center.events.put(("progress", "Checking Docker…"))
        center.message_label = Mock()
        center.message_label.configure.side_effect = RuntimeError("widget update failed")
        center.after = Mock(return_value="poll-next")

        with self.assertRaisesRegex(RuntimeError, "widget update failed"):
            center._poll_events()

        center.after.assert_called_once_with(100, center._poll_events)
        self.assertEqual(center._poll_after_id, "poll-next")

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
