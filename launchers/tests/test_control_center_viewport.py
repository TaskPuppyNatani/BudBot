from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_center import ScrollableFrame


def make_frame() -> ScrollableFrame:
    frame = object.__new__(ScrollableFrame)
    frame._sync_after_id = None
    frame._syncing = False
    frame._sync_pending = False
    frame._last_window_size = None
    frame._last_scrollregion = None
    frame._scrollbar_visible = False
    frame.after_idle = Mock(return_value="idle-1")
    frame.after_cancel = Mock()
    frame.winfo_exists = Mock(return_value=True)
    frame.canvas = Mock()
    frame.canvas.winfo_width.return_value = 800
    frame.canvas.winfo_height.return_value = 600
    frame.content = Mock()
    frame.content.winfo_reqheight.return_value = 900
    frame.scrollbar = Mock()
    frame.window = 1
    return frame


class ControlCenterViewportTests(unittest.TestCase):
    def test_repeated_canvas_and_content_configures_share_one_idle_callback(self) -> None:
        frame = make_frame()

        for _ in range(5):
            frame._canvas_configured()
            frame._content_configured()

        frame.after_idle.assert_called_once_with(frame._sync_viewport)
        self.assertEqual(frame._sync_after_id, "idle-1")
        frame.canvas.itemconfigure.assert_not_called()

    def test_viewport_sync_avoids_nested_idle_processing_and_stabilizes(self) -> None:
        frame = make_frame()
        scheduled_callbacks = []
        callback_count = [0]
        in_callback = [False]

        def schedule(callback):
            callback_count[0] += 1
            callback_id = f"idle-{callback_count[0]}"

            def guarded_callback():
                if in_callback[0]:
                    raise AssertionError("viewport callback recursively re-entered")
                in_callback[0] = True
                try:
                    callback()
                finally:
                    in_callback[0] = False

            scheduled_callbacks.append(guarded_callback)
            return callback_id

        frame.after_idle = Mock(side_effect=schedule)
        frame.update_idletasks = Mock(side_effect=AssertionError("nested idle processing"))
        frame.canvas.itemconfigure.side_effect = (
            lambda *_args, **_kwargs: frame._canvas_configured()
        )
        frame.canvas.configure.side_effect = lambda **_kwargs: frame._content_configured()
        frame.scrollbar.grid.side_effect = lambda: frame._canvas_configured()

        def drain_scheduled_callbacks() -> int:
            passes = 0
            while scheduled_callbacks:
                if passes >= 5:
                    self.fail("viewport synchronization did not converge after resize")
                callback = scheduled_callbacks.pop(0)
                callback()
                passes += 1
            return passes

        # Initial resize schedules once; Configure events caused by geometry
        # changes during synchronization are coalesced into one later pass.
        frame._canvas_configured()
        self.assertEqual(drain_scheduled_callbacks(), 2)

        self.assertEqual(callback_count[0], 2)
        self.assertEqual(frame._last_window_size, (800, 900))
        self.assertEqual(frame._last_scrollregion, (0, 0, 800, 900))
        frame.scrollbar.grid.assert_called_once_with()
        frame.update_idletasks.assert_not_called()

        frame.canvas.winfo_width.return_value = 640
        frame.canvas.winfo_height.return_value = 480
        for _ in range(5):
            frame._canvas_configured()
            frame._content_configured()
        self.assertEqual(frame.after_idle.call_count, 3)
        self.assertEqual(drain_scheduled_callbacks(), 2)
        self.assertEqual(callback_count[0], 4)
        self.assertEqual(frame._last_window_size, (640, 900))
        self.assertEqual(frame._last_scrollregion, (0, 0, 640, 900))
        self.assertEqual(frame.canvas.itemconfigure.call_count, 2)
        self.assertEqual(frame.canvas.configure.call_count, 2)
        self.assertIsNone(frame._sync_after_id)

        scheduled_before_resize = frame.after_idle.call_count
        frame._canvas_configured()
        frame._content_configured()
        self.assertEqual(frame.after_idle.call_count, scheduled_before_resize + 1)

    def test_reported_1280x860_geometry_converges_with_footer_space_reserved(self) -> None:
        frame = make_frame()
        frame.canvas.winfo_width.return_value = 1062
        frame.canvas.winfo_height.return_value = 551
        frame.content.winfo_reqheight.return_value = 570
        callbacks = []
        callback_count = [0]

        def schedule(callback):
            callback_count[0] += 1
            callbacks.append(callback)
            return f"idle-{callback_count[0]}"

        def show_scrollbar():
            frame.canvas.winfo_width.return_value = 1048
            frame._canvas_configured()

        frame.after_idle = Mock(side_effect=schedule)
        frame.canvas.itemconfigure.side_effect = lambda *_args, **_kwargs: frame._canvas_configured()
        frame.canvas.configure.side_effect = lambda **_kwargs: frame._content_configured()
        frame.scrollbar.grid.side_effect = show_scrollbar
        frame.scrollbar.grid_remove.side_effect = lambda: self.fail(
            "the measured 570 px content must keep the scrollbar visible in a 551 px viewport"
        )

        # The trace measured a 94 px footer and 551 px page viewport inside
        # the 860 px window. The 570 px scrollregion must not claim that extra
        # height from the outer layout and compress the footer.
        footer_logo_request = 88
        footer_logo_vertical_padding = 2 * 3
        footer_height = 94
        page_height = 551
        self.assertGreaterEqual(
            footer_height, footer_logo_request + footer_logo_vertical_padding
        )
        self.assertEqual(860 - 215 - footer_height, page_height)
        self.assertGreater(frame.content.winfo_reqheight(), page_height + 2)

        frame._canvas_configured()
        passes = 0
        while callbacks:
            if passes >= 5:
                self.fail("viewport geometry failed to converge at the reported dimensions")
            callbacks.pop(0)()
            passes += 1

        self.assertEqual(passes, 3)
        self.assertEqual(frame._last_window_size, (1048, 570))
        self.assertEqual(frame._last_scrollregion, (0, 0, 1048, 570))
        self.assertTrue(frame._scrollbar_visible)
        frame.scrollbar.grid.assert_called_once_with()
        frame.scrollbar.grid_remove.assert_not_called()

    def test_destroy_cancels_pending_viewport_sync(self) -> None:
        frame = make_frame()
        frame._sync_after_id = "idle-pending"

        with patch("tkinter.ttk.Frame.destroy") as base_destroy:
            frame.destroy()

        frame.after_cancel.assert_called_once_with("idle-pending")
        self.assertIsNone(frame._sync_after_id)
        base_destroy.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
