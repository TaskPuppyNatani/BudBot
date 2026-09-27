from __future__ import annotations

import ctypes
import sys
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import control_center
from control_center import calculate_window_geometry, create_page_host, detect_work_area, responsive_layout


class ControlCenterLayoutTests(unittest.TestCase):
    def test_page_host_expands_in_parent_without_propagating_scroll_content_size(self) -> None:
        parent = object()
        pages = Mock()
        with patch.object(control_center.ttk, "Frame", return_value=pages):
            self.assertIs(create_page_host(parent), pages)

        self.assertEqual(
            pages.mock_calls,
            [call.pack(fill="both", expand=True), call.pack_propagate(False)],
        )

    def test_screenshot_sized_work_area_uses_comfortable_default_and_centers(self) -> None:
        geometry = calculate_window_geometry(
            1397, 882, work_area=(0, 0, 1397, 882)
        )
        self.assertEqual((geometry["width"], geometry["height"]), (1280, 860))
        self.assertEqual((geometry["x"], geometry["y"]), (58, 11))
        self.assertEqual((geometry["min_width"], geometry["min_height"]), (1180, 780))

    def test_panel_reduced_work_area_clamps_size_and_centers_inside_available_area(self) -> None:
        geometry = calculate_window_geometry(
            1600, 1000, work_area=(20, 30, 1360, 800)
        )
        self.assertEqual((geometry["width"], geometry["height"]), (1280, 800))
        self.assertEqual((geometry["x"], geometry["y"]), (60, 30))
        self.assertEqual((geometry["min_width"], geometry["min_height"]), (1180, 780))

    def test_minimum_comfortable_work_area_fits_without_forcing_maximization(self) -> None:
        geometry = calculate_window_geometry(
            1180, 780, work_area=(0, 0, 1180, 780)
        )
        self.assertEqual((geometry["width"], geometry["height"]), (1180, 780))
        self.assertEqual((geometry["min_width"], geometry["min_height"]), (1180, 780))

    def test_small_laptop_area_never_exceeds_desktop_or_forces_larger_minimum(self) -> None:
        geometry = calculate_window_geometry(
            1024, 700, work_area=(0, 0, 1024, 700)
        )
        self.assertEqual((geometry["width"], geometry["height"]), (1024, 700))
        self.assertLess(geometry["min_width"], geometry["width"])
        self.assertLess(geometry["min_height"], geometry["height"])
        self.assertGreaterEqual(geometry["min_width"], 560)
        self.assertGreaterEqual(geometry["min_height"], 420)

    def test_dpi_scaling_expands_target_until_work_area_requires_clamping(self) -> None:
        geometry = calculate_window_geometry(
            2560, 1600, ui_scale=1.5, work_area=(0, 0, 2560, 1600)
        )
        self.assertEqual((geometry["width"], geometry["height"]), (1920, 1290))
        self.assertEqual((geometry["min_width"], geometry["min_height"]), (1770, 1170))
        self.assertEqual((geometry["x"], geometry["y"]), (320, 155))

    def test_cards_stack_only_when_available_width_crosses_responsive_breakpoint(self) -> None:
        self.assertEqual(responsive_layout(962, breakpoint=900), "columns")
        self.assertEqual(responsive_layout(899, breakpoint=900), "stacked")
        self.assertEqual(responsive_layout(1349, breakpoint=900, ui_scale=1.5), "stacked")
        self.assertEqual(responsive_layout(1350, breakpoint=900, ui_scale=1.25), "columns")

    def test_windows_work_area_is_converted_to_tk_screen_coordinates(self) -> None:
        class User32:
            @staticmethod
            def SystemParametersInfoW(_action, _parameter, rectangle_pointer, _flags):
                rectangle = ctypes.cast(
                    rectangle_pointer,
                    ctypes.POINTER(ctypes.c_long * 4),
                ).contents
                rectangle[:] = (100, 80, 1700, 980)
                return 1

            @staticmethod
            def GetSystemMetrics(metric):
                return 1920 if metric == 0 else 1080

        root = SimpleNamespace(winfo_screenwidth=lambda: 960, winfo_screenheight=lambda: 540)
        with patch.object(control_center.ctypes, "windll", SimpleNamespace(user32=User32()), create=True):
            self.assertEqual(
                detect_work_area(root, platform_name="win32"),
                (50, 40, 800, 450),
            )

    def test_linux_work_area_uses_desktop_panel_bounds_when_xprop_is_available(self) -> None:
        root = SimpleNamespace(winfo_screenwidth=lambda: 1920, winfo_screenheight=lambda: 1080)
        output = subprocess.CompletedProcess(
            ["xprop", "-root", "_NET_WORKAREA"],
            0,
            stdout="_NET_WORKAREA(CARDINAL) = 0, 28, 1920, 1020\n",
            stderr="",
        )
        with patch.object(control_center.shutil, "which", return_value="/usr/bin/xprop"), patch(
            "control_center.subprocess.run", return_value=output
        ):
            self.assertEqual(
                detect_work_area(root, platform_name="linux"),
                (0, 28, 1920, 1020),
            )


if __name__ == "__main__":
    unittest.main()
