#!/usr/bin/env python3
"""Cross-platform dark Control Center for BudBot local development."""

from __future__ import annotations

import base64
import ctypes
import math
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
import webbrowser

from branding_client import (
    BrandingClientError,
    LocalBrandingClient,
    encode_image_file,
)
from service_controller import BudBotServiceController, BudBotServiceError

COLORS = {
    "background": "#11131b",
    "sidebar": "#171925",
    "surface": "#1c2030",
    "surface2": "#23283a",
    "border": "#30364b",
    "text": "#e5ffe9",
    "green_text": "#b5ffc1",
    "muted": "#aec4b3",
    "green": "#54f575",
    "green_dark": "#123323",
    "amber": "#ffd36e",
    "red": "#ff6483",
    "red_dark": "#381d2b",
    "purple": "#8b38ff",
    "purple_dark": "#351764",
    "purple_hover": "#a45cff",
    "cyan": "#17d9ee",
    "cyan_dark": "#123440",
}
STATE_COLORS = {
    "Starting": COLORS["amber"],
    "Running": COLORS["green"],
    "Stopping": COLORS["amber"],
    "Stopped": COLORS["muted"],
    "Error": COLORS["red"],
}
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".webp")
DEFAULT_WINDOW_SIZE = (1280, 860)
MIN_COMFORTABLE_SIZE = (1180, 780)
MAX_EVENTS_PER_POLL = 100


def calculate_window_geometry(
    screen_width: int,
    screen_height: int,
    *,
    ui_scale: float = 1.0,
    work_area: tuple[int, int, int, int] | None = None,
) -> dict[str, int]:
    """Choose a centered, DPI-aware initial size that fits the desktop work area."""
    scale = min(2.0, max(0.75, float(ui_scale)))
    if work_area is None:
        area_x, area_y, area_width, area_height = 0, 0, screen_width, screen_height
    else:
        area_x, area_y, area_width, area_height = work_area
    area_width = max(1, min(int(area_width), int(screen_width)))
    area_height = max(1, min(int(area_height), int(screen_height)))
    area_x = min(max(0, int(area_x)), max(0, screen_width - area_width))
    area_y = min(max(0, int(area_y)), max(0, screen_height - area_height))

    target_width, target_height = (round(value * scale) for value in DEFAULT_WINDOW_SIZE)
    minimum_width, minimum_height = (round(value * scale) for value in MIN_COMFORTABLE_SIZE)
    width = min(target_width, area_width)
    height = min(target_height, area_height)
    fit_ratio = min(1.0, area_width / minimum_width, area_height / minimum_height)
    if fit_ratio < 1.0:
        # Keep a useful resize range on small displays; content below this
        # comfortable target remains reachable through the page scroll areas.
        minimum_width = round(minimum_width * fit_ratio * 0.9)
        minimum_height = round(minimum_height * fit_ratio * 0.9)
    return {
        "width": width,
        "height": height,
        "min_width": min(width, max(round(560 * scale), minimum_width)),
        "min_height": min(height, max(round(420 * scale), minimum_height)),
        "x": area_x + (area_width - width) // 2,
        "y": area_y + (area_height - height) // 2,
    }


def responsive_layout(width: int, *, breakpoint: int, ui_scale: float = 1.0) -> str:
    """Return a two-column layout when it fits, otherwise stack the panels."""
    return "stacked" if width < round(breakpoint * min(2.0, max(0.75, ui_scale))) else "columns"


def create_page_host(parent: tk.Misc) -> ttk.Frame:
    """Keep scroll content from changing the outer page/footer allocation."""
    pages = ttk.Frame(parent)
    pages.pack(fill="both", expand=True)
    pages.pack_propagate(False)
    return pages


def detect_work_area(root: tk.Misc, *, platform_name: str | None = None) -> tuple[int, int, int, int]:
    """Find a desktop work area where supported, with a safe cross-platform fallback."""
    screen_width = int(root.winfo_screenwidth())
    screen_height = int(root.winfo_screenheight())
    platform_name = platform_name or sys.platform
    if os.name == "nt" or platform_name.startswith("win"):
        try:
            class Rect(ctypes.Structure):
                _fields_ = [(name, ctypes.c_long) for name in ("left", "top", "right", "bottom")]

            rect = Rect()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                native_width = ctypes.windll.user32.GetSystemMetrics(0)
                native_height = ctypes.windll.user32.GetSystemMetrics(1)
                scale_x = screen_width / native_width if native_width else 1.0
                scale_y = screen_height / native_height if native_height else 1.0
                x = round(rect.left * scale_x)
                y = round(rect.top * scale_y)
                width = round((rect.right - rect.left) * scale_x)
                height = round((rect.bottom - rect.top) * scale_y)
                if width > 0 and height > 0:
                    return x, y, min(width, screen_width), min(height, screen_height)
        except (AttributeError, OSError, TypeError, ValueError):
            pass
    elif platform_name.startswith("linux") and shutil.which("xprop"):
        try:
            result = subprocess.run(
                ["xprop", "-root", "_NET_WORKAREA"],
                capture_output=True,
                text=True,
                timeout=0.5,
                check=False,
            )
            match = re.search(r"=\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)", result.stdout)
            if result.returncode == 0 and match:
                x, y, width, height = (int(value) for value in match.groups())
                if width > 0 and height > 0:
                    x = max(0, min(x, screen_width - 1))
                    y = max(0, min(y, screen_height - 1))
                    return x, y, min(width, screen_width - x), min(height, screen_height - y)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

    # Reserve room for desktop panels/taskbars when native work-area APIs are
    # unavailable. On Windows the native API above supplies the exact bounds.
    scale = 1.0
    try:
        scale = min(2.0, max(0.75, float(root.winfo_fpixels("1i")) / 96.0))
    except (tk.TclError, TypeError, ValueError):
        pass
    horizontal_margin = min(round(16 * scale), max(0, (screen_width - 1) // 2))
    top_margin = min(round(8 * scale), max(0, screen_height - 1))
    bottom_margin = min(round(48 * scale), max(0, screen_height - top_margin - 1))
    return (
        horizontal_margin,
        top_margin,
        max(1, screen_width - horizontal_margin * 2),
        max(1, screen_height - top_margin - bottom_margin),
    )


class ScrollableFrame(ttk.Frame):
    """A width-responsive page viewport whose content can scroll vertically."""

    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=COLORS["background"], highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.content = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self._sync_after_id: str | None = None
        self._syncing = False
        self._sync_pending = False
        self._last_window_size: tuple[int, int] | None = None
        self._last_scrollregion: tuple[int, int, int, int] | None = None
        self._scrollbar_visible = False
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.scrollbar.grid_remove()
        self.canvas.bind("<Configure>", self._canvas_configured)
        self.content.bind("<Configure>", self._content_configured)

    def _canvas_configured(self, event=None) -> None:
        self._schedule_viewport_sync()

    def _content_configured(self, _event=None) -> None:
        self._schedule_viewport_sync()

    def _schedule_viewport_sync(self) -> None:
        if self._syncing:
            self._sync_pending = True
        elif self._sync_after_id is None:
            try:
                self._sync_after_id = self.after_idle(self._sync_viewport)
            except tk.TclError:
                self._sync_after_id = None

    def _sync_viewport(self) -> None:
        self._sync_after_id = None
        if self._syncing:
            self._sync_pending = True
            return
        self._syncing = True
        try:
            if not self.winfo_exists():
                return
            canvas_width = max(1, self.canvas.winfo_width())
            canvas_height = max(1, self.canvas.winfo_height())
            content_height = max(1, self.content.winfo_reqheight())
            window_height = max(canvas_height, content_height)
            window_size = (canvas_width, window_height)
            scrollregion = (0, 0, canvas_width, window_height)
            if window_size != self._last_window_size:
                self.canvas.itemconfigure(
                    self.window, width=canvas_width, height=window_height
                )
                self._last_window_size = window_size
            if scrollregion != self._last_scrollregion:
                self.canvas.configure(scrollregion=scrollregion)
                self._last_scrollregion = scrollregion
            needs_scrollbar = content_height > canvas_height + 2
            if needs_scrollbar != self._scrollbar_visible:
                if needs_scrollbar:
                    self.scrollbar.grid()
                else:
                    self.scrollbar.grid_remove()
                self._scrollbar_visible = needs_scrollbar
        except tk.TclError:
            return
        finally:
            self._syncing = False
            if self._sync_pending:
                self._sync_pending = False
                self._schedule_viewport_sync()

    def destroy(self) -> None:
        pending = self._sync_after_id
        self._sync_after_id = None
        if pending is not None:
            try:
                self.after_cancel(pending)
            except tk.TclError:
                pass
        super().destroy()


class RoundedButton(tk.Canvas):
    """Keyboard accessible rounded button with a restrained neon accent."""

    def __init__(self, master: tk.Misc, *, text: str, command, background: str, **kwargs) -> None:
        button_height = kwargs.pop("height", 54)
        super().__init__(
            master,
            height=button_height,
            background=COLORS["background"],
            highlightthickness=0,
            borderwidth=0,
            takefocus=True,
            **kwargs,
        )
        self.label = text
        self.command = command
        self.fill = background
        self.button_height = button_height
        self.enabled = True
        self.hovered = False
        self.focused = False
        self.bind("<Configure>", self._draw)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self.bind("<Button-1>", self._click)
        self.bind("<Return>", self._click)
        self.bind("<space>", self._click)
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def _enter(self, _event=None) -> None:
        self.hovered = True
        self._draw()

    def _leave(self, _event=None) -> None:
        self.hovered = False
        self._draw()

    def _focus_in(self, _event=None) -> None:
        self.focused = True
        self._draw()

    def _focus_out(self, _event=None) -> None:
        self.focused = False
        self._draw()

    def _click(self, _event=None) -> str:
        if self.enabled:
            self.command()
        return "break"

    def _draw(self, _event=None) -> None:
        self.delete("all")
        width, height = max(self.winfo_width(), 96), max(self.winfo_height(), self.button_height)
        radius = min(13, (height - 4) / 2)
        points = []
        for cx, cy, start in (
            (width - radius - 2, radius + 2, -90),
            (width - radius - 2, height - radius - 2, 0),
            (radius + 2, height - radius - 2, 90),
            (radius + 2, radius + 2, 180),
        ):
            for step in range(5):
                angle = math.radians(start + step * 90 / 4)
                points.extend((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        fill = self.fill
        foreground = COLORS["text"]
        if not self.enabled:
            fill, foreground = COLORS["surface2"], COLORS["muted"]
        elif self.hovered:
            fill = COLORS["purple_hover"] if self.fill == COLORS["purple"] else self.fill
        self.create_polygon(
            points,
            smooth=True,
            splinesteps=12,
            fill=fill,
            outline=(COLORS["purple_hover"] if self.focused else COLORS["border"])
            if self.focused or self.fill == COLORS["surface2"] else "",
            width=2 if self.focused else 1,
        )
        self.create_text(
            width / 2,
            height / 2,
            text=self.label,
            fill=foreground,
            font=("Sans", 10, "bold"),
            width=max(1, width - 28),
            justify="center",
        )


class BudBotControlCenter(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("BudBot Control Center")
        self.update_idletasks()
        try:
            self.ui_scale = min(2.0, max(0.75, float(self.winfo_fpixels("1i")) / 96.0))
        except (tk.TclError, TypeError, ValueError):
            self.ui_scale = 1.0
        self.work_area = detect_work_area(self)
        geometry = calculate_window_geometry(
            self.winfo_screenwidth(),
            self.winfo_screenheight(),
            ui_scale=self.ui_scale,
            work_area=self.work_area,
        )
        self.geometry(
            f"{geometry['width']}x{geometry['height']}+{geometry['x']}+{geometry['y']}"
        )
        self.minsize(geometry["min_width"], geometry["min_height"])
        self.configure(bg=COLORS["background"])
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.controller = BudBotServiceController(progress=self._progress_from_worker)
        self.branding_client = LocalBrandingClient()
        self.busy = False
        self._close_after_operation = False
        self._window_closed = False
        self._poll_after_id: str | None = None
        self.state = "Stopped"
        self.preview_url: str | None = None
        self.business_id: str | None = None
        self.businesses: list[dict[str, str]] = []
        self.business_by_label: dict[str, dict[str, str]] = {}
        self.saved: dict[str, object] = {}
        self.logo_file: Path | None = None
        self.avatar_file: Path | None = None
        self.remove_logo = False
        self.remove_avatar = False
        self.logo_preview_data = b""
        self.avatar_preview_data = b""
        self.assistant_avatar_configured = False
        self.logo_photo: tk.PhotoImage | None = None
        self.avatar_photo: tk.PhotoImage | None = None
        self.form_logo_photo: tk.PhotoImage | None = None
        self.company_photo: tk.PhotoImage | None = None
        self.page = "Dashboard"
        self.active_scroll: ScrollableFrame | None = None
        self._wrap_refresh_id: str | None = None

        self.name_var = tk.StringVar()
        self.assistant_var = tk.StringVar()
        self.greeting_var = tk.StringVar()
        self.color_var = tk.StringVar()
        self.business_var = tk.StringVar()
        self.name_var.trace_add("write", self._refresh_brand_preview)
        self.assistant_var.trace_add("write", self._refresh_brand_preview)
        self.greeting_var.trace_add("write", self._refresh_brand_preview)
        self.color_var.trace_add("write", self._refresh_brand_preview)

        self._configure_styles()
        self._build_ui()
        self._set_status("Stopped", "Ready when you are. Start BudBot to launch the local preview.")
        self._refresh_buttons()
        self._show_page("Dashboard")
        self._detect_existing_stack()
        self._poll_after_id = self.after(100, self._poll_events)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["background"])
        style.configure("Sidebar.TFrame", background=COLORS["sidebar"])
        style.configure("Card.TFrame", background=COLORS["surface"], relief="flat")
        style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"])
        style.configure("Card.TLabel", background=COLORS["surface"], foreground=COLORS["text"])
        style.configure("Title.TLabel", font=("Sans", 21, "bold"), foreground=COLORS["green_text"])
        style.configure("CardTitle.TLabel", background=COLORS["surface"], font=("Sans", 21, "bold"), foreground=COLORS["green_text"])
        style.configure("Section.TLabel", background=COLORS["surface"], font=("Sans", 14, "bold"), foreground=COLORS["green_text"])
        style.configure("Muted.TLabel", font=("Sans", 10), foreground=COLORS["muted"])
        style.configure(
            "FooterBrand.TLabel",
            background=COLORS["background"],
            foreground=COLORS["green_text"],
            font=("Sans", 10, "bold"),
            padding=(round(7 * self.ui_scale), round(3 * self.ui_scale)),
        )
        style.configure("Green.TLabel", foreground=COLORS["green_text"])
        style.configure("CardMuted.TLabel", background=COLORS["surface"], font=("Sans", 10), foreground=COLORS["muted"])
        style.configure("CardGreen.TLabel", background=COLORS["surface"], foreground=COLORS["green_text"])
        style.configure("State.TLabel", background=COLORS["surface"], font=("Sans", 11, "bold"))
        style.configure(
            "TEntry",
            fieldbackground=COLORS["surface2"],
            foreground=COLORS["text"],
            insertcolor=COLORS["green"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
        )
        style.configure("TCombobox", fieldbackground=COLORS["surface2"], foreground=COLORS["text"])
        style.map("TCombobox", fieldbackground=[("readonly", COLORS["surface2"])], foreground=[("readonly", COLORS["text"])])
        style.configure("TButton", background=COLORS["surface2"], foreground=COLORS["text"], padding=(10, 7), focuscolor=COLORS["purple_hover"])
        style.map("TButton", background=[("active", COLORS["purple_dark"])])
        style.configure("Horizontal.TProgressbar", troughcolor=COLORS["surface2"], background=COLORS["purple"], bordercolor=COLORS["surface"])
        style.configure("Vertical.TScrollbar", background=COLORS["surface2"], troughcolor=COLORS["background"], arrowcolor=COLORS["muted"], bordercolor=COLORS["background"])
        style.map("Vertical.TScrollbar", background=[("active", COLORS["purple_dark"])])

    def _build_ui(self) -> None:
        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)
        sidebar_width = round(174 * self.ui_scale)
        self.sidebar = ttk.Frame(
            shell,
            style="Sidebar.TFrame",
            padding=tuple(round(value * self.ui_scale) for value in (16, 22, 12, 14)),
            width=sidebar_width,
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        ttk.Label(self.sidebar, text="◉  BudBot", font=("Sans", 18, "bold"), background=COLORS["sidebar"], foreground=COLORS["green_text"]).pack(anchor="w", pady=(0, 3))
        ttk.Label(self.sidebar, text="CONTROL CENTER", font=("Sans", 8, "bold"), background=COLORS["sidebar"], foreground=COLORS["muted"]).pack(anchor="w", pady=(0, round(25 * self.ui_scale)))
        self.nav_buttons: dict[str, ttk.Button] = {}
        for label in ("Dashboard", "Branding"):
            button = ttk.Button(self.sidebar, text=f"   {label}", command=lambda item=label: self._show_page(item))
            button.pack(fill="x", pady=4)
            self.nav_buttons[label] = button
        ttk.Label(self.sidebar, text="LOCAL PREVIEW ONLY", wraplength=max(90, sidebar_width - 35), justify="left", font=("Sans", 9), background=COLORS["sidebar"], foreground=COLORS["muted"]).pack(side="bottom", anchor="w", pady=(12, 8))

        self.main = ttk.Frame(
            shell,
            padding=tuple(round(value * self.ui_scale) for value in (22, 18, 22, 10)),
        )
        self.main.pack(side="left", fill="both", expand=True)
        header = ttk.Frame(self.main)
        header.pack(fill="x", pady=(0, round(12 * self.ui_scale)))
        self.page_title = ttk.Label(header, text="Dashboard", style="Title.TLabel")
        self.page_title.pack(side="left")
        status_chip = ttk.Frame(header, style="Card.TFrame", padding=(round(10 * self.ui_scale), round(6 * self.ui_scale)))
        status_chip.pack(side="right")
        self.status_dot = tk.Canvas(status_chip, width=14, height=14, bg=COLORS["surface"], highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 8))
        self.status_circle = self.status_dot.create_oval(2, 2, 12, 12, fill=COLORS["muted"], outline="")
        self.status_label = ttk.Label(status_chip, text="Stopped", style="State.TLabel")
        self.status_label.pack(side="left")
        self.progress = ttk.Progressbar(self.main, mode="indeterminate", length=280)
        self.progress.pack(fill="x", pady=(0, round(6 * self.ui_scale)))
        self.message_label = ttk.Label(self.main, text="", style="Muted.TLabel", wraplength=880)
        self.message_label.pack(anchor="w", fill="x", pady=(0, round(8 * self.ui_scale)))

        self.action_bar = ttk.Frame(self.main)
        self.action_bar.pack(fill="x", pady=(0, round(10 * self.ui_scale)))
        for column in range(4):
            self.action_bar.columnconfigure(column, weight=1, uniform="service-actions")
        self.start_button = RoundedButton(self.action_bar, text="▶  Start BudBot", command=self.start_budbot, background=COLORS["green_dark"], height=60)
        self.stop_button = RoundedButton(self.action_bar, text="■  Stop BudBot", command=self.stop_budbot, background=COLORS["red_dark"], height=60)
        self.restart_button = RoundedButton(self.action_bar, text="⟳  Restart BudBot", command=self.restart_budbot, background=COLORS["purple_dark"], height=60)
        self.open_button = RoundedButton(self.action_bar, text="↗  Open BudBot", command=self.open_budbot, background=COLORS["cyan_dark"], height=60)
        for column, button in enumerate((self.start_button, self.stop_button, self.restart_button, self.open_button)):
            gap = round(5 * self.ui_scale)
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else gap, 0 if column == 3 else gap))

        self.pages = create_page_host(self.main)
        self.pages.grid_rowconfigure(0, weight=1)
        self.pages.grid_columnconfigure(0, weight=1)
        self.dashboard_page = ScrollableFrame(self.pages)
        self.branding_page = ScrollableFrame(self.pages)
        self._build_dashboard()
        self._build_branding()

        self.footer = ttk.Frame(self.main)
        self.footer.pack(fill="x", pady=(round(7 * self.ui_scale), 0))
        self.footer_left = ttk.Label(self.footer, text="Local development preview · AI chat requires a configured provider", style="Muted.TLabel", wraplength=760)
        self.footer_left.pack(side="left", fill="x", expand=True)
        logo_path = Path(__file__).resolve().parents[1] / "frontend" / "widget" / "assets" / "taskpuppy-kreations.png"
        try:
            self.company_photo = tk.PhotoImage(file=str(logo_path))
            logo_size = min(112, max(68, round(84 * self.ui_scale)))
            factor = max(1, math.ceil(max(self.company_photo.width() / logo_size, self.company_photo.height() / logo_size)))
            self.company_photo = self.company_photo.subsample(factor, factor)
        except (tk.TclError, OSError):
            self.company_photo = None
        if self.company_photo:
            ttk.Label(self.footer, image=self.company_photo, background=COLORS["background"]).pack(
                side="right",
                padx=(round(10 * self.ui_scale), round(4 * self.ui_scale)),
                pady=(round(3 * self.ui_scale), round(3 * self.ui_scale)),
            )
        ttk.Label(
            self.footer,
            text="Powered by TaskPuppy Kreations",
            style="FooterBrand.TLabel",
        ).pack(side="right", padx=(round(4 * self.ui_scale), 0))
        self.main.bind("<Configure>", self._schedule_wrap_refresh)
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_linux_mousewheel)
        self.bind_all("<Button-5>", self._on_linux_mousewheel)
        self.after_idle(self._refresh_wrap_lengths)

    def _card(self, parent: tk.Misc, padding: int = 15) -> ttk.Frame:
        return ttk.Frame(parent, style="Card.TFrame", padding=padding)

    def _build_dashboard(self) -> None:
        page = self.dashboard_page.content
        page.pack(fill="both", expand=True)
        picker_row = ttk.Frame(page)
        picker_row.pack(fill="x", pady=(0, round(10 * self.ui_scale)))
        ttk.Label(picker_row, text="Business", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self.business_combo = ttk.Combobox(picker_row, textvariable=self.business_var, state="readonly", width=40)
        self.business_combo.pack(side="left", fill="x", expand=True)
        self.business_combo.bind("<<ComboboxSelected>>", self._business_selected)

        hero = self._card(page, padding=round(18 * self.ui_scale))
        hero.pack(fill="x", pady=(0, round(12 * self.ui_scale)))
        hero.grid_columnconfigure(1, weight=1)
        self.hero_logo = tk.Label(hero, text="Your logo here", width=17, height=6, bg=COLORS["surface2"], fg=COLORS["muted"], font=("Sans", 11, "bold"), relief="flat")
        self.hero_logo.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 18))
        self.hero_name = ttk.Label(hero, text="Your Business Name", style="CardTitle.TLabel")
        self.hero_name.grid(row=0, column=1, sticky="sw")
        self.hero_assistant = ttk.Label(hero, text="Assistant: BudBot", style="CardGreen.TLabel", font=("Sans", 12, "bold"))
        self.hero_assistant.grid(row=1, column=1, sticky="nw", pady=(4, 0))
        self.hero_logo_button = ttk.Button(hero, text="Choose Business Logo…", command=lambda: self._show_page("Branding"))
        self.hero_logo_button.grid(row=0, column=2, rowspan=2, sticky="e", padx=(14, 0))

        lower = ttk.Frame(page)
        lower.pack(fill="both", expand=True)
        self.dashboard_lower = lower
        brand_card = self._card(lower, padding=16)
        self.dashboard_brand_card = brand_card
        ttk.Label(brand_card, text="Branding", style="Section.TLabel").pack(anchor="w")
        self.dashboard_brand_description = ttk.Label(brand_card, text="Make the customer widget feel like your business.", style="CardMuted.TLabel", wraplength=360)
        self.dashboard_brand_description.pack(anchor="w", pady=(4, 10))
        self.dashboard_brand_summary = ttk.Label(brand_card, text="Choose a business to view its saved branding.", style="CardGreen.TLabel", wraplength=360)
        self.dashboard_brand_summary.pack(anchor="w", pady=(0, 12))
        ttk.Button(brand_card, text="Edit Branding", command=lambda: self._show_page("Branding")).pack(anchor="w")

        widget_card = self._card(lower, padding=16)
        self.dashboard_widget_card = widget_card
        ttk.Label(widget_card, text="Widget Preview", style="Section.TLabel").pack(anchor="w")
        ttk.Label(widget_card, text="Customer-facing preview", style="CardMuted.TLabel").pack(anchor="w", pady=(4, 9))
        preview = ttk.Frame(widget_card, style="Card.TFrame", padding=10)
        preview.pack(fill="both", expand=True)
        preview_header = ttk.Frame(preview, style="Card.TFrame")
        preview_header.pack(fill="x")
        self.preview_business_logo = tk.Label(preview_header, text="◉", width=4, height=2, bg=COLORS["surface2"], fg=COLORS["green"], font=("Sans", 15, "bold"))
        self.preview_business_logo.pack(side="left", padx=(0, 8))
        names = ttk.Frame(preview_header, style="Card.TFrame")
        names.pack(side="left", fill="x", expand=True)
        self.preview_business_name = ttk.Label(names, text="Your Business Name", style="Card.TLabel", font=("Sans", 10, "bold"))
        self.preview_business_name.pack(anchor="w")
        ttk.Label(names, text="Ask us anything", style="CardMuted.TLabel").pack(anchor="w")
        self.preview_assistant = ttk.Label(preview, text="Hi there! How can I help you today?", style="Card.TLabel", wraplength=300, padding=10)
        self.preview_assistant.pack(anchor="w", pady=(12, 8))
        ttk.Label(preview, text="Get Information     View Services     Contact Us", style="CardGreen.TLabel", wraplength=350).pack(anchor="w")
        self.dashboard_widget_description = ttk.Label(widget_card, text="Open BudBot to interact with the live local widget.", style="CardMuted.TLabel", wraplength=380)
        self.dashboard_widget_description.pack(anchor="w", pady=(10, 0))
        self.dashboard_lower.bind("<Configure>", self._layout_dashboard_cards)
        self.after_idle(self._layout_dashboard_cards)

    def _build_branding(self) -> None:
        page = self.branding_page.content
        page.pack(fill="both", expand=True)
        top = ttk.Frame(page)
        top.pack(fill="x", pady=(0, round(10 * self.ui_scale)))
        ttk.Label(top, text="Branding", style="Title.TLabel").pack(side="left")
        self.branding_intro = ttk.Label(
            top,
            text="The business logo is the default chat avatar; an optional assistant avatar overrides it.",
            style="Muted.TLabel",
            wraplength=700,
            justify="left",
        )
        self.branding_intro.pack(side="left", fill="x", expand=True, padx=(14, 0))
        body = ttk.Frame(page)
        body.pack(fill="both", expand=True)
        self.branding_body = body
        form = self._card(body, padding=round(18 * self.ui_scale))
        self.branding_form = form
        preview = self._card(body, padding=round(16 * self.ui_scale))
        self.branding_preview_card = preview

        ttk.Label(form, text="Customer Brand", style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Label(form, text="Business Logo", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        logo_value = ttk.Frame(form, style="Card.TFrame")
        logo_value.grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        logo_holder = tk.Frame(logo_value, width=92, height=72, bg=COLORS["surface2"], highlightthickness=1, highlightbackground=COLORS["border"])
        logo_holder.pack(side="left", padx=(0, 9))
        logo_holder.pack_propagate(False)
        self.branding_logo_image = tk.Label(logo_holder, text="Your logo here", width=10, height=3, bg=COLORS["surface2"], fg=COLORS["muted"], font=("Sans", 8), wraplength=78)
        self.branding_logo_image.pack(expand=True)
        self.logo_status = ttk.Label(logo_value, text="Your logo here", style="CardMuted.TLabel", wraplength=210, justify="left")
        self.logo_status.pack(side="left", fill="x", expand=True)
        logo_actions = ttk.Frame(form, style="Card.TFrame")
        logo_actions.grid(row=1, column=2, sticky="e")
        ttk.Button(logo_actions, text="Choose…", command=self._choose_logo).pack(side="left", padx=(0, 5))
        ttk.Button(logo_actions, text="Remove", command=self._remove_business_logo).pack(side="left")

        ttk.Label(form, text="Business Name", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=7)
        self.name_entry = ttk.Entry(form, textvariable=self.name_var)
        self.name_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        ttk.Label(form, text="Assistant Name", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=7)
        self.assistant_entry = ttk.Entry(form, textvariable=self.assistant_var)
        self.assistant_entry.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        ttk.Label(form, text="Greeting", style="Card.TLabel").grid(row=4, column=0, sticky="nw", pady=7)
        self.greeting_entry = ttk.Entry(form, textvariable=self.greeting_var)
        self.greeting_entry.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        ttk.Label(form, text="Primary Brand Color", style="Card.TLabel").grid(row=5, column=0, sticky="w", pady=7)
        color_field = ttk.Frame(form, style="Card.TFrame")
        color_field.grid(row=5, column=1, sticky="ew", padx=(8, 6))
        color_field.columnconfigure(0, weight=1)
        self.color_entry = ttk.Entry(color_field, textvariable=self.color_var, width=12)
        self.color_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.color_swatch = tk.Label(color_field, width=3, height=1, bg=COLORS["green"], relief="solid", bd=1, highlightthickness=1, highlightbackground=COLORS["border"])
        self.color_swatch.grid(row=0, column=1, sticky="e")
        ttk.Button(form, text="●  Choose Color…", command=self._choose_color).grid(row=5, column=2, sticky="e")

        ttk.Label(form, text="Assistant Avatar", style="Card.TLabel").grid(row=6, column=0, sticky="w", pady=7)
        self.avatar_status = ttk.Label(form, text="Optional · uses business logo by default", style="CardMuted.TLabel", wraplength=195)
        self.avatar_status.grid(row=6, column=1, sticky="w", padx=8)
        avatar_actions = ttk.Frame(form, style="Card.TFrame")
        avatar_actions.grid(row=6, column=2, sticky="e")
        ttk.Button(avatar_actions, text="Choose…", command=self._choose_avatar).pack(side="left", padx=(0, 5))
        ttk.Button(avatar_actions, text="Remove", command=self._remove_assistant_avatar).pack(side="left")
        form.columnconfigure(1, weight=1)
        form.rowconfigure(7, weight=1)

        action_row = ttk.Frame(form, style="Card.TFrame")
        action_row.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(round(16 * self.ui_scale), 0))
        self.save_button = RoundedButton(action_row, text="▣  Save Branding", command=self._save_branding, background=COLORS["green_dark"])
        self.save_button.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(action_row, text="Restore Defaults", command=self._restore_defaults).pack(side="left", padx=5)
        ttk.Button(action_row, text="Open Widget", command=self.open_budbot).pack(side="left", padx=(5, 0))

        ttk.Label(preview, text="Widget Preview", style="Section.TLabel").pack(anchor="w")
        self.brand_preview_description = ttk.Label(preview, text="Updates as you edit. Save to apply it to customers.", style="CardMuted.TLabel", wraplength=300, justify="left")
        self.brand_preview_description.pack(anchor="w", fill="x", pady=(3, 12))
        self.brand_preview = ttk.Frame(preview, style="Card.TFrame", padding=12)
        self.brand_preview.pack(fill="both", expand=True)
        self.brand_preview.configure(relief="solid")
        self.brand_preview_header = ttk.Frame(self.brand_preview, style="Card.TFrame")
        self.brand_preview_header.pack(fill="x")
        self.brand_preview_logo = tk.Label(self.brand_preview_header, text="Your logo here", width=15, height=4, bg=COLORS["surface2"], fg=COLORS["muted"], font=("Sans", 9))
        self.brand_preview_logo.pack(side="left", padx=(0, 10))
        header_text = ttk.Frame(self.brand_preview_header, style="Card.TFrame")
        header_text.pack(side="left", fill="x", expand=True)
        self.brand_preview_name = ttk.Label(header_text, text="Your Business Name", style="Card.TLabel", font=("Sans", 10, "bold"), wraplength=160)
        self.brand_preview_name.pack(anchor="w")
        ttk.Label(header_text, text="Ask us anything!", style="CardMuted.TLabel").pack(anchor="w")
        self.brand_preview_avatar = tk.Label(self.brand_preview, text="◉", width=4, height=2, bg=COLORS["surface2"], fg=COLORS["green"], font=("Sans", 13, "bold"))
        self.brand_preview_avatar.pack(anchor="w", pady=(15, 5))
        self.brand_preview_greeting = ttk.Label(self.brand_preview, text="Hi there! How can I help?", style="Card.TLabel", wraplength=280, padding=10)
        self.brand_preview_greeting.pack(anchor="w")
        self.branding_upload_description = ttk.Label(preview, text="Image uploads are decoded and validated by BudBot. Supported: PNG, JPG, WebP, up to 4 MB.", style="CardMuted.TLabel", wraplength=300, justify="left")
        self.branding_upload_description.pack(anchor="w", fill="x", pady=(14, 0))
        self.branding_local_description = ttk.Label(preview, text="Branding edits are available only from this local development Control Center.", style="CardMuted.TLabel", wraplength=300, justify="left")
        self.branding_local_description.pack(anchor="w", fill="x", pady=(8, 0))
        self.branding_body.bind("<Configure>", self._layout_branding_cards)
        self.after_idle(self._layout_branding_cards)

    def _layout_dashboard_cards(self, event=None) -> None:
        width = int(event.width) if event is not None else self.dashboard_lower.winfo_width()
        if width <= 1:
            return
        stacked = responsive_layout(width, breakpoint=860, ui_scale=self.ui_scale) == "stacked"
        if getattr(self, "_dashboard_stacked", None) == stacked:
            return
        self._dashboard_stacked = stacked
        self.dashboard_brand_card.grid_forget()
        self.dashboard_widget_card.grid_forget()
        if stacked:
            self.dashboard_lower.columnconfigure(0, weight=1, uniform="")
            self.dashboard_lower.columnconfigure(1, weight=0, uniform="")
            self.dashboard_lower.rowconfigure(0, weight=1)
            self.dashboard_lower.rowconfigure(1, weight=1)
            self.dashboard_brand_card.grid(row=0, column=0, sticky="nsew", pady=(0, round(10 * self.ui_scale)))
            self.dashboard_widget_card.grid(row=1, column=0, sticky="nsew")
        else:
            self.dashboard_lower.rowconfigure(0, weight=1)
            self.dashboard_lower.rowconfigure(1, weight=0)
            self.dashboard_lower.columnconfigure(0, weight=2, uniform="dashboard-cards")
            self.dashboard_lower.columnconfigure(1, weight=3, uniform="dashboard-cards")
            self.dashboard_brand_card.grid(row=0, column=0, sticky="nsew", padx=(0, round(6 * self.ui_scale)))
            self.dashboard_widget_card.grid(row=0, column=1, sticky="nsew", padx=(round(6 * self.ui_scale), 0))

    def _layout_branding_cards(self, event=None) -> None:
        width = int(event.width) if event is not None else self.branding_body.winfo_width()
        if width <= 1:
            return
        stacked = responsive_layout(width, breakpoint=900, ui_scale=self.ui_scale) == "stacked"
        if getattr(self, "_branding_stacked", None) == stacked:
            return
        self._branding_stacked = stacked
        self.branding_form.grid_forget()
        self.branding_preview_card.grid_forget()
        if stacked:
            self.branding_body.columnconfigure(0, weight=1, uniform="")
            self.branding_body.columnconfigure(1, weight=0, uniform="")
            self.branding_body.rowconfigure(0, weight=1)
            self.branding_body.rowconfigure(1, weight=1)
            self.branding_form.grid(row=0, column=0, sticky="nsew")
            self.branding_preview_card.grid(row=1, column=0, sticky="nsew", pady=(round(10 * self.ui_scale), 0))
        else:
            self.branding_body.rowconfigure(0, weight=1)
            self.branding_body.rowconfigure(1, weight=0)
            self.branding_body.columnconfigure(0, weight=2, uniform="branding-cards")
            self.branding_body.columnconfigure(1, weight=1, uniform="branding-cards")
            self.branding_form.grid(row=0, column=0, sticky="nsew", padx=(0, round(7 * self.ui_scale)))
            self.branding_preview_card.grid(row=0, column=1, sticky="nsew", padx=(round(7 * self.ui_scale), 0))
        self.after_idle(self._refresh_wrap_lengths)

    def _schedule_wrap_refresh(self, _event=None) -> None:
        if self._wrap_refresh_id is None:
            self._wrap_refresh_id = self.after_idle(self._refresh_wrap_lengths)

    def _refresh_wrap_lengths(self) -> None:
        self._wrap_refresh_id = None
        scale = self.ui_scale
        main_width = max(1, self.main.winfo_width())
        self.message_label.configure(wraplength=max(round(220 * scale), main_width - round(4 * scale)))
        footer_width = max(1, self.footer.winfo_width())
        self.footer_left.configure(wraplength=max(round(170 * scale), footer_width - round(260 * scale)))
        dashboard_brand_width = max(160, self.dashboard_brand_card.winfo_width() - round(36 * scale))
        self.dashboard_brand_description.configure(wraplength=dashboard_brand_width)
        self.dashboard_brand_summary.configure(wraplength=dashboard_brand_width)
        dashboard_widget_width = max(180, self.dashboard_widget_card.winfo_width() - round(36 * scale))
        self.dashboard_widget_description.configure(wraplength=dashboard_widget_width)
        self.preview_assistant.configure(wraplength=max(140, dashboard_widget_width - round(24 * scale)))
        hero_width = max(180, self.hero_logo.master.winfo_width() - round(350 * scale))
        self.hero_name.configure(wraplength=hero_width)
        self.hero_assistant.configure(wraplength=hero_width)
        brand_body_width = max(240, self.branding_body.winfo_width())
        self.branding_intro.configure(wraplength=max(round(180 * scale), brand_body_width - round(130 * scale)))
        preview_width = max(200, self.branding_preview_card.winfo_width() - round(34 * scale))
        self.brand_preview_description.configure(wraplength=preview_width)
        self.branding_upload_description.configure(wraplength=preview_width)
        self.branding_local_description.configure(wraplength=preview_width)
        self.brand_preview_greeting.configure(wraplength=max(140, preview_width - round(20 * scale)))
        self.brand_preview_name.configure(wraplength=max(110, preview_width - round(112 * scale)))
        logo_text_width = max(100, min(round(350 * scale), self.branding_form.winfo_width() - round(440 * scale)))
        self.logo_status.configure(wraplength=logo_text_width)
        self.avatar_status.configure(wraplength=max(120, self.branding_form.winfo_width() - round(345 * scale)))

    def _pointer_is_inside(self, ancestor: tk.Misc, event) -> bool:
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except tk.TclError:
            return False
        while widget is not None:
            if widget == ancestor:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _on_mousewheel(self, event) -> str | None:
        if self.active_scroll and self._pointer_is_inside(self.active_scroll, event):
            delta = int(getattr(event, "delta", 0))
            units = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
            self.active_scroll.canvas.yview_scroll(units, "units")
            return "break"
        return None

    def _on_linux_mousewheel(self, event) -> str | None:
        if self.active_scroll and self._pointer_is_inside(self.active_scroll, event):
            self.active_scroll.canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
            return "break"
        return None

    def _show_page(self, page: str) -> None:
        self.page = page
        self.page_title.configure(text=page)
        for frame in (self.dashboard_page, self.branding_page):
            frame.pack_forget()
        selected = self.dashboard_page if page == "Dashboard" else self.branding_page
        selected.pack(fill="both", expand=True)
        self.active_scroll = selected
        selected._schedule_viewport_sync()
        self.after_idle(self._refresh_wrap_lengths)

    def _set_status(self, state: str, message: str) -> None:
        self.state = state
        self.status_label.configure(text=state, foreground=STATE_COLORS[state])
        self.status_dot.itemconfigure(self.status_circle, fill=STATE_COLORS[state])
        self.message_label.configure(text=message)

    def _refresh_buttons(self) -> None:
        ready = self.state == "Running" and bool(self.business_id)
        self.start_button.set_enabled(not self.busy and self.state not in {"Running", "Starting", "Stopping"})
        self.stop_button.set_enabled(not self.busy and self.state in {"Running", "Error"})
        self.restart_button.set_enabled(not self.busy and self.state in {"Running", "Error"})
        self.open_button.set_enabled(not self.busy and ready and bool(self.preview_url))
        self.save_button.set_enabled(not self.busy and ready)
        if self.business_id:
            self.business_combo.configure(state="readonly" if not self.busy else "disabled")
        else:
            self.business_combo.configure(state="disabled")

    def _begin_service(self, action: str) -> None:
        if self.busy:
            return
        self.busy = True
        if action == "stop":
            self._set_status("Stopping", "Stopping BudBot services. Database data and configuration are kept.")
        else:
            self._set_status("Starting", "Checking Docker and preparing the local demo…")
        self.progress.start(12)
        self._refresh_buttons()
        threading.Thread(target=self._service_worker, args=(action,), daemon=True).start()

    def start_budbot(self) -> None:
        self._begin_service("start")

    def stop_budbot(self) -> None:
        if messagebox.askyesno("Stop BudBot", "Stop BudBot and PostgreSQL? Database data and uploaded logos will be kept.", parent=self):
            self._begin_service("stop")

    def restart_budbot(self) -> None:
        self._begin_service("restart")

    def open_budbot(self) -> None:
        if not self.preview_url or self.state != "Running":
            messagebox.showinfo("BudBot is not running", "Start BudBot before opening the widget preview.", parent=self)
            return
        self._open_preview(self.preview_url)

    def _open_preview(self, url: str) -> None:
        threading.Thread(target=self._browser_worker, args=(url,), daemon=True).start()

    def _browser_worker(self, url: str) -> None:
        try:
            opened = webbrowser.open(url, new=2)
            error = None
        except Exception as exc:
            opened = False
            error = str(exc)
        self.events.put(("browser_result", {"url": url, "opened": bool(opened), "error": error}))

    def _progress_from_worker(self, message: str) -> None:
        self.events.put(("progress", message))

    def _load_business_data(self, business_id: str) -> tuple[list[dict[str, str]], dict[str, dict[str, object]], bytes, bytes]:
        businesses = self.branding_client.list_businesses()
        branding = self.branding_client.load(business_id)
        business = branding["business"]
        assistant = branding["assistant"]
        logo = self.branding_client.load_asset_preview(business.get("logo_reference"), business_id) if business.get("logo_reference") else b""
        avatar = self.branding_client.load_asset_preview(assistant.get("avatar_reference"), business_id) if assistant.get("avatar_reference") else b""
        return businesses, branding, logo, avatar

    def _service_worker(self, action: str) -> None:
        try:
            if action == "stop":
                self.controller.stop()
                self.events.put(("service_done", {"state": "Stopped", "action": action}))
                return
            url = self.controller.restart() if action == "restart" else self.controller.start()
            demo_id = self.controller._business_id_from_url(url)
            saved_selection = self.controller.selected_business_file
            business_id = saved_selection.read_text(encoding="utf-8").strip() if saved_selection.exists() else demo_id
            if not self.controller._valid_uuid(business_id):
                business_id = demo_id
            businesses, branding, logo, avatar = self._load_business_data(business_id)
            available_ids = {item["id"] for item in businesses}
            if business_id not in available_ids:
                business_id = demo_id
                businesses, branding, logo, avatar = self._load_business_data(business_id)
            preview = f"http://127.0.0.1:8000/widget/?business_id={business_id}"
            self.controller.preview_file.write_text(preview + "\n", encoding="utf-8")
            saved_selection.parent.mkdir(parents=True, exist_ok=True)
            saved_selection.write_text(business_id + "\n", encoding="utf-8")
            self.events.put(("service_done", {"state": "Running", "action": action, "url": preview, "business_id": business_id, "businesses": businesses, "branding": branding, "logo": logo, "avatar": avatar}))
        except (BudBotServiceError, BrandingClientError, OSError, ValueError) as exc:
            self.events.put(("service_done", {"state": "Error", "action": action, "message": f"BudBot operation failed: {exc}"}))
        except Exception as exc:
            self.events.put(("service_done", {"state": "Error", "action": action, "message": f"BudBot could not complete the operation: {exc}"}))

    def _detect_existing_stack(self) -> None:
        if not self.controller.preview_file.is_file():
            return
        self.busy = True
        self._set_status("Starting", "Checking whether the local BudBot service is already running…")
        self.progress.start(12)
        self._refresh_buttons()
        threading.Thread(target=self._detect_worker, daemon=True).start()

    def _detect_worker(self) -> None:
        try:
            url = self.controller.detect_running()
            if not url:
                self.events.put(("detected", None))
                return
            business_id = self.controller._business_id_from_url(url)
            businesses = self.branding_client.list_businesses()
            if business_id not in {item["id"] for item in businesses}:
                if not businesses:
                    raise BrandingClientError("No active business is available for preview.")
                business_id = businesses[0]["id"]
                url = f"http://127.0.0.1:8000/widget/?business_id={business_id}"
                self.controller.preview_file.write_text(url + "\n", encoding="utf-8")
                self.controller.selected_business_file.write_text(business_id + "\n", encoding="utf-8")
            businesses, branding, logo, avatar = self._load_business_data(business_id)
            self.events.put(("detected", {"url": url, "business_id": business_id, "businesses": businesses, "branding": branding, "logo": logo, "avatar": avatar}))
        except (BudBotServiceError, BrandingClientError, OSError, ValueError):
            self.events.put(("detected", None))
        except Exception as exc:
            self.events.put(("detection_error", f"Could not check the BudBot service: {exc}"))

    def _business_selected(self, _event=None) -> None:
        choice = self.business_by_label.get(self.business_var.get())
        if not choice or choice["id"] == self.business_id:
            return
        if self._is_dirty() and not messagebox.askyesno("Discard unsaved branding?", "Switch businesses and discard your unsaved edits?", parent=self):
            self._select_combo_business(self.business_id)
            return
        self._load_selected_business(choice["id"])

    def _load_selected_business(self, business_id: str) -> None:
        if self.busy:
            return
        self.busy = True
        # Clear the previous tenant's visible identity while the new selection
        # loads, so a failed request cannot leave stale branding under the new name.
        self.saved = {}
        self.logo_file = self.avatar_file = None
        self.remove_logo = self.remove_avatar = False
        self.preview_url = None
        self._set_image(self.hero_logo, b"", "Your logo here", "hero")
        self._set_image(self.branding_logo_image, b"", "Your logo here", "form")
        self._set_image(self.preview_business_logo, b"", "◉", "dashboard")
        self._set_image(self.brand_preview_logo, b"", "Your logo here", "brand")
        self._set_image(self.brand_preview_avatar, b"", "◉", "avatar")
        self.hero_name.configure(text="Loading business branding…")
        self.hero_assistant.configure(text="Assistant: loading…")
        self.preview_business_name.configure(text="Loading business branding…")
        self.preview_assistant.configure(text="Loading greeting…")
        self.logo_status.configure(text="Your logo here")
        self.avatar_status.configure(text="Optional · no avatar configured")
        self._refresh_buttons()
        self.message_label.configure(text="Loading this business's saved branding…")
        self.progress.start(12)
        threading.Thread(target=self._branding_worker, args=("load", business_id, None), daemon=True).start()

    def _branding_worker(self, action: str, business_id: str, changes: dict[str, object] | None) -> None:
        try:
            if action == "save":
                branding = self.branding_client.save(business_id, changes or {})
                logo_ref = branding["business"].get("logo_reference")
                avatar_ref = branding["assistant"].get("avatar_reference")
                logo = self.branding_client.load_asset_preview(logo_ref, business_id) if logo_ref else b""
                avatar = self.branding_client.load_asset_preview(avatar_ref, business_id) if avatar_ref else b""
                self.events.put(("branding_saved", {"branding": branding, "logo": logo, "avatar": avatar}))
            else:
                businesses, branding, logo, avatar = self._load_business_data(business_id)
                self.events.put(("business_loaded", {"business_id": business_id, "businesses": businesses, "branding": branding, "logo": logo, "avatar": avatar}))
        except (BrandingClientError, OSError, ValueError) as exc:
            self.events.put(("branding_error", str(exc)))
        except Exception as exc:
            self.events.put(("branding_error", f"Could not complete the branding operation: {exc}"))

    def _apply_businesses(self, businesses: list[dict[str, str]]) -> None:
        self.businesses = businesses
        self.business_by_label = {}
        labels = []
        for business in businesses:
            label = f"{business['display_name']}  ·  {business['id'][:8]}"
            labels.append(label)
            self.business_by_label[label] = business
        self.business_combo.configure(values=labels)
        self._select_combo_business(self.business_id)

    def _select_combo_business(self, business_id: str | None) -> None:
        if not business_id:
            return
        for label, business in self.business_by_label.items():
            if business["id"] == business_id:
                self.business_var.set(label)
                return

    def _apply_branding(self, business_id: str, branding: dict[str, dict[str, object]], logo: bytes, avatar: bytes) -> None:
        self.business_id = business_id
        self.saved = branding
        business, assistant = branding["business"], branding["assistant"]
        self.logo_file = self.avatar_file = None
        self.remove_logo = self.remove_avatar = False
        self.logo_preview_data = logo
        self.avatar_preview_data = avatar
        self.assistant_avatar_configured = bool(assistant.get("avatar_reference"))
        self.name_var.set(str(business.get("display_name") or ""))
        self.assistant_var.set(str(assistant.get("display_name") or ""))
        self.greeting_var.set(str(assistant.get("greeting") or ""))
        self.color_var.set(str(business.get("primary_brand_color") or ""))
        self._set_image(self.hero_logo, logo, "Your logo here", "hero")
        self._set_image(self.branding_logo_image, logo, "Your logo here", "form")
        self._set_image(self.preview_business_logo, logo, "◉", "dashboard")
        self._set_image(self.brand_preview_logo, logo, "Your logo here", "brand")
        self._refresh_assistant_avatar_preview()
        self.logo_status.configure(text="Saved business logo" if logo else "Your logo here")
        self.avatar_status.configure(
            text="Saved assistant avatar" if self.assistant_avatar_configured
            else "Optional · uses business logo by default" if logo
            else "Optional · letter fallback"
        )
        self.hero_name.configure(text=self.name_var.get() or "Your Business Name")
        self.hero_assistant.configure(text=f"Assistant: {self.assistant_var.get() or 'BudBot'}")
        self.dashboard_brand_summary.configure(text=f"{self.name_var.get()} · {self.assistant_var.get()} · {self.color_var.get() or 'default color'}")
        self._select_combo_business(business_id)
        self._refresh_brand_preview()
        self._refresh_buttons()

    def _refresh_assistant_avatar_preview(self) -> None:
        if self.avatar_file:
            self._set_preview_from_file(
                self.brand_preview_avatar, self.avatar_file, "◉", "avatar"
            )
        elif self.remove_avatar or not self.assistant_avatar_configured:
            if self.logo_file and not self.remove_logo:
                self._set_preview_from_file(
                    self.brand_preview_avatar, self.logo_file, "◉", "avatar"
                )
            else:
                self._set_image(
                    self.brand_preview_avatar,
                    b"" if self.remove_logo else self.logo_preview_data,
                    "◉",
                    "avatar",
                )
        else:
            self._set_image(
                self.brand_preview_avatar, self.avatar_preview_data, "◉", "avatar"
            )

    def _set_image(self, widget: tk.Label, payload: bytes, fallback: str, kind: str) -> None:
        photo = None
        if payload:
            try:
                photo = tk.PhotoImage(data=base64.b64encode(payload).decode("ascii"))
                max_width, max_height = {
                    "hero": (180, 130),
                    "form": (82, 60),
                    "brand": (96, 64),
                }.get(kind, (96, 64))
                factor = max(1, math.ceil(max(photo.width() / max_width, photo.height() / max_height)))
                if factor > 1:
                    photo = photo.subsample(factor, factor)
            except tk.TclError:
                photo = None
        if kind == "hero":
            self.logo_photo = photo
        elif kind == "form":
            self.form_logo_photo = photo
        elif kind == "dashboard":
            self.dashboard_logo_photo = photo
        elif kind == "brand":
            self.brand_logo_photo = photo
        elif kind == "avatar":
            self.avatar_photo = photo
        if photo:
            widget.configure(image=photo, text="", width=0, height=0, bg=COLORS["surface2"])
        else:
            width, height = (17, 5) if kind == "hero" else (10, 3) if kind == "form" else (13, 3)
            widget.configure(image="", text=fallback, width=width, height=height, bg=COLORS["surface2"])

    def _refresh_brand_preview(self, *_args) -> None:
        if not hasattr(self, "brand_preview_name"):
            return
        name = self.name_var.get().strip() or "Your Business Name"
        assistant = self.assistant_var.get().strip() or "BudBot"
        greeting = self.greeting_var.get().strip() or f"Hi, I’m {assistant}. How can I help?"
        color = self.color_var.get().strip()
        if color and (len(color) != 7 or not color.startswith("#")):
            color = ""
        try:
            if color:
                self.winfo_rgb(color)
        except tk.TclError:
            color = ""
        self.brand_preview_name.configure(text=name)
        self.brand_preview_greeting.configure(text=greeting)
        self.brand_preview.configure(highlightbackground=color or COLORS["green"], highlightcolor=color or COLORS["green"], highlightthickness=1)
        if hasattr(self, "color_swatch"):
            self.color_swatch.configure(bg=color or COLORS["surface2"])
        self.preview_business_name.configure(text=name)
        self.preview_assistant.configure(text=greeting)
        self.hero_name.configure(text=name)
        self.hero_assistant.configure(text=f"Assistant: {assistant}")
        if hasattr(self, "dashboard_brand_summary"):
            self.dashboard_brand_summary.configure(text=f"{name} · {assistant} · {color or 'default color'}")

    def _choose_logo(self) -> None:
        self._choose_image("business")

    def _choose_avatar(self) -> None:
        self._choose_image("assistant")

    def _choose_image(self, kind: str) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Choose " + ("Business Logo" if kind == "business" else "Assistant Avatar"),
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")],
        )
        if not path:
            return
        selected = Path(path)
        try:
            encoded_image = encode_image_file(selected)
        except BrandingClientError as exc:
            messagebox.showerror("Invalid image", str(exc), parent=self)
            return
        if kind == "business":
            self.logo_file, self.remove_logo = selected, False
            self.logo_preview_data = base64.b64decode(
                encoded_image["content_base64"], validate=True
            )
            self.logo_status.configure(text=selected.name)
            self._set_preview_from_file(self.branding_logo_image, selected, "Your logo here", "form")
            self._set_preview_from_file(self.brand_preview_logo, selected, "Your logo here", "brand")
            self._set_preview_from_file(self.hero_logo, selected, "Your logo here", "hero")
            self._set_preview_from_file(self.preview_business_logo, selected, "◉", "dashboard")
            self._refresh_assistant_avatar_preview()
        else:
            self.avatar_file, self.remove_avatar = selected, False
            self.assistant_avatar_configured = True
            self.avatar_status.configure(text=selected.name)
            self._set_preview_from_file(self.brand_preview_avatar, selected, "◉", "avatar")

    def _set_preview_from_file(self, widget: tk.Label, path: Path, fallback: str, kind: str) -> None:
        try:
            payload = path.read_bytes()
        except OSError:
            widget.configure(text=fallback, image="")
            return
        self._set_image(widget, payload, fallback, kind)

    def _remove_business_logo(self) -> None:
        self.logo_file, self.remove_logo = None, True
        self.logo_preview_data = b""
        self.logo_status.configure(text="Will be removed when saved")
        self._set_image(self.hero_logo, b"", "Your logo here", "hero")
        self._set_image(self.branding_logo_image, b"", "Your logo here", "form")
        self._set_image(self.brand_preview_logo, b"", "Your logo here", "brand")
        self._set_image(self.preview_business_logo, b"", "◉", "dashboard")
        self._refresh_assistant_avatar_preview()

    def _remove_assistant_avatar(self) -> None:
        self.avatar_file, self.remove_avatar = None, True
        self.assistant_avatar_configured = False
        self.avatar_status.configure(text="Will be removed when saved")
        self._refresh_assistant_avatar_preview()

    def _choose_color(self) -> None:
        _rgb, color = colorchooser.askcolor(color=self.color_var.get() or COLORS["green"], parent=self)
        if color:
            self.color_var.set(color.upper())

    def _is_dirty(self) -> bool:
        if not self.saved:
            return False
        business, assistant = self.saved["business"], self.saved["assistant"]
        return bool(
            self.name_var.get().strip() != business.get("display_name")
            or self.assistant_var.get().strip() != assistant.get("display_name")
            or self.greeting_var.get().strip() != assistant.get("greeting")
            or (self.color_var.get().strip() or None) != business.get("primary_brand_color")
            or self.logo_file
            or self.avatar_file
            or self.remove_logo
            or self.remove_avatar
        )

    def _save_branding(self) -> None:
        if self.busy or not self.business_id:
            return
        if not self.name_var.get().strip() or not self.assistant_var.get().strip() or not self.greeting_var.get().strip():
            messagebox.showerror("Missing information", "Business name, assistant name, and greeting are required.", parent=self)
            return
        color = self.color_var.get().strip()
        if color:
            try:
                if len(color) != 7 or not color.startswith("#"):
                    raise ValueError
                self.winfo_rgb(color)
            except (tk.TclError, ValueError):
                messagebox.showerror("Invalid brand color", "Choose a color in #RRGGBB format.", parent=self)
                return
        changes: dict[str, object] = {
            "display_name": self.name_var.get().strip(),
            "assistant_display_name": self.assistant_var.get().strip(),
            "greeting": self.greeting_var.get().strip(),
            "primary_brand_color": color or None,
        }
        try:
            if self.logo_file:
                changes["business_logo"] = encode_image_file(self.logo_file)
            elif self.remove_logo:
                changes["remove_business_logo"] = True
            if self.avatar_file:
                changes["assistant_avatar"] = encode_image_file(self.avatar_file)
            elif self.remove_avatar:
                changes["remove_assistant_avatar"] = True
        except BrandingClientError as exc:
            messagebox.showerror("Invalid image", str(exc), parent=self)
            return
        self._begin_branding_action("Saving branding settings and validating images…")
        threading.Thread(target=self._branding_worker, args=("save", self.business_id, changes), daemon=True).start()

    def _restore_defaults(self) -> None:
        if not self.business_id or self.busy:
            return
        if not messagebox.askyesno(
            "Restore default branding?",
            "Clear this business's logo, assistant avatar, and custom brand color? Business name, assistant name, and greeting will be preserved.",
            parent=self,
        ):
            return
        changes: dict[str, object] = {
            "primary_brand_color": None,
            "remove_business_logo": True,
            "remove_assistant_avatar": True,
        }
        self._begin_branding_action("Restoring the default logo and color settings…")
        threading.Thread(target=self._branding_worker, args=("save", self.business_id, changes), daemon=True).start()

    def _begin_branding_action(self, message: str) -> None:
        self.busy = True
        self.message_label.configure(text=message)
        self.progress.start(12)
        self._refresh_buttons()

    def _poll_events(self) -> None:
        self._poll_after_id = None
        try:
            processed = 0
            while processed < MAX_EVENTS_PER_POLL:
                kind, payload = self.events.get_nowait()
                processed += 1
                if kind == "progress":
                    message = str(payload)
                    self.message_label.configure(text=message)
                    if message.lower().startswith(("checking docker", "preparing local", "building", "waiting", "creating")):
                        self.status_label.configure(text="Starting", foreground=STATE_COLORS["Starting"])
                        self.status_dot.itemconfigure(self.status_circle, fill=STATE_COLORS["Starting"])
                    elif message.lower().startswith("stopping"):
                        self.status_label.configure(text="Stopping", foreground=STATE_COLORS["Stopping"])
                        self.status_dot.itemconfigure(self.status_circle, fill=STATE_COLORS["Stopping"])
                elif kind == "detected":
                    self.busy = False
                    self.progress.stop()
                    if payload:
                        data = payload
                        self.preview_url = data["url"]
                        self.business_id = data["business_id"]
                        self._apply_businesses(data["businesses"])
                        self._apply_branding(data["business_id"], data["branding"], data["logo"], data["avatar"])
                        self._set_status("Running", "BudBot is running. Select a business and open its live widget preview.")
                    else:
                        self.preview_url = None
                        self._set_status("Stopped", "BudBot is not running.")
                    self._refresh_buttons()
                elif kind == "detection_error":
                    self.busy = False
                    self.progress.stop()
                    self.preview_url = None
                    self._set_status("Error", str(payload))
                    self._refresh_buttons()
                    if not self._close_after_operation:
                        messagebox.showerror("BudBot status error", str(payload), parent=self)
                elif kind == "service_done":
                    self.busy = False
                    self.progress.stop()
                    data = payload
                    if data["state"] == "Running":
                        self.preview_url = data["url"]
                        self.business_id = data["business_id"]
                        if not self._close_after_operation:
                            self._apply_businesses(data["businesses"])
                            self._apply_branding(data["business_id"], data["branding"], data["logo"], data["avatar"])
                            self._set_status("Running", "BudBot is online and ready. Your customer widget has opened.")
                            self._show_page("Dashboard")
                            self._open_preview(self.preview_url)
                    elif data["state"] == "Stopped":
                        self.preview_url = None
                        self._set_status("Stopped", "BudBot stopped safely. Database and uploaded assets were kept.")
                    else:
                        self._set_status("Error", str(data.get("message", "BudBot could not start.")))
                        if not self._close_after_operation:
                            messagebox.showerror("BudBot error", str(data.get("message", "BudBot could not start.")), parent=self)
                    self._refresh_buttons()
                elif kind == "business_loaded":
                    self.busy = False
                    self.progress.stop()
                    data = payload
                    self.business_id = data["business_id"]
                    self._apply_businesses(data["businesses"])
                    self._apply_branding(data["business_id"], data["branding"], data["logo"], data["avatar"])
                    self.preview_url = f"http://127.0.0.1:8000/widget/?business_id={self.business_id}"
                    self.controller.selected_business_file.write_text(self.business_id + "\n", encoding="utf-8")
                    self.controller.preview_file.write_text(self.preview_url + "\n", encoding="utf-8")
                    self.message_label.configure(text="Business branding loaded.")
                    self._refresh_buttons()
                elif kind == "branding_saved":
                    self.busy = False
                    self.progress.stop()
                    data = payload
                    self._apply_branding(self.business_id or "", data["branding"], data["logo"], data["avatar"])
                    self.message_label.configure(text="Branding saved for this business.")
                    self._refresh_buttons()
                elif kind == "branding_error":
                    self.busy = False
                    self.progress.stop()
                    self.message_label.configure(text="Branding could not be saved.")
                    if not self._close_after_operation:
                        messagebox.showerror("Branding error", str(payload), parent=self)
                    self._refresh_buttons()
                elif kind == "browser_result":
                    if not payload["opened"] and not self._window_closed:
                        detail = payload.get("error") or "The browser did not accept the request."
                        messagebox.showerror(
                            "Open BudBot",
                            f"Could not open the browser. Open this address manually:\n{payload['url']}\n\n{detail}",
                            parent=self,
                        )
        except queue.Empty:
            pass
        finally:
            if self._close_after_operation and not self.busy:
                self._destroy_window()
            elif not self._window_closed:
                try:
                    self._poll_after_id = self.after(100, self._poll_events)
                except tk.TclError:
                    self._window_closed = True

    def _close(self) -> None:
        if self.busy:
            self._close_after_operation = True
            self.message_label.configure(
                text="Close requested. The current operation will finish, then this window will close. BudBot services and saved data will be kept."
            )
            return
        if self._is_dirty() and not messagebox.askyesno(
            "Discard unsaved changes?",
            "Close without saving your branding edits?",
            parent=self,
        ):
            return
        self._destroy_window()

    def _destroy_window(self) -> None:
        if self._window_closed:
            return
        self._window_closed = True
        poll_after_id = self._poll_after_id
        self._poll_after_id = None
        if poll_after_id is not None:
            try:
                self.after_cancel(poll_after_id)
            except tk.TclError:
                pass
        self.destroy()


if __name__ == "__main__":
    BudBotControlCenter().mainloop()
