"""
Tinix Facebook Down — Control Panel
Action buttons: Run, Pause, Stop, Reset, Settings, History.
"""

import customtkinter as ctk
from typing import Callable, Optional


class ControlPanel(ctk.CTkFrame):
    """
    Control panel with action buttons.
    Manages button states based on download status.
    """

    def __init__(
        self,
        master,
        on_run: Optional[Callable] = None,
        on_pause: Optional[Callable] = None,
        on_stop: Optional[Callable] = None,
        on_reset: Optional[Callable] = None,
        on_settings: Optional[Callable] = None,
        on_history: Optional[Callable] = None,
        on_open_folder: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(
            master,
            fg_color="#FFFFFF",
            corner_radius=12,
            border_width=1,
            border_color="#E2E8F0",
            **kwargs,
        )

        self._on_run = on_run
        self._on_pause = on_pause
        self._on_stop = on_stop
        self._on_reset = on_reset
        self._on_settings = on_settings
        self._on_history = on_history
        self._on_open_folder = on_open_folder
        self._is_paused = False

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the control panel UI."""
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=10)

        # Left side: main action buttons
        left = ctk.CTkFrame(inner, fg_color="transparent")
        left.pack(side="left")

        # Run button
        self._run_btn = ctk.CTkButton(
            left,
            text="▶  Bắt đầu",
            width=130,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            corner_radius=10,
            command=self._handle_run,
        )
        self._run_btn.pack(side="left", padx=(0, 8))

        # Pause button
        self._pause_btn = ctk.CTkButton(
            left,
            text="⏸  Tạm dừng",
            width=120,
            height=40,
            font=ctk.CTkFont(size=13),
            fg_color="#F59E0B",
            hover_color="#D97706",
            corner_radius=10,
            command=self._handle_pause,
            state="disabled",
        )
        self._pause_btn.pack(side="left", padx=(0, 8))

        # Stop button
        self._stop_btn = ctk.CTkButton(
            left,
            text="⏹  Dừng",
            width=100,
            height=40,
            font=ctk.CTkFont(size=13),
            fg_color="#DC2626",
            hover_color="#B91C1C",
            corner_radius=10,
            command=self._handle_stop,
            state="disabled",
        )
        self._stop_btn.pack(side="left", padx=(0, 8))

        # Reset button
        self._reset_btn = ctk.CTkButton(
            left,
            text="🔄  Reset",
            width=100,
            height=40,
            font=ctk.CTkFont(size=13),
            fg_color="#F1F5F9",
            text_color="#475569",
            hover_color="#E2E8F0",
            corner_radius=10,
            command=self._handle_reset,
        )
        self._reset_btn.pack(side="left")

        # Right side: utility buttons
        right = ctk.CTkFrame(inner, fg_color="transparent")
        right.pack(side="right")

        # Open folder button
        self._folder_btn = ctk.CTkButton(
            right,
            text="📂 Mở thư mục",
            width=110,
            height=40,
            font=ctk.CTkFont(size=13),
            fg_color="#F1F5F9",
            text_color="#475569",
            hover_color="#E2E8F0",
            corner_radius=10,
            command=self._handle_open_folder,
        )
        self._folder_btn.pack(side="right")

    # --- State Management ---

    def set_running(self) -> None:
        """Set buttons to 'running' state."""
        self._run_btn.configure(state="disabled", fg_color="#93C5FD")
        self._pause_btn.configure(state="normal")
        self._stop_btn.configure(state="normal")
        self._reset_btn.configure(state="disabled")
        self._is_paused = False

    def set_paused(self) -> None:
        """Set buttons to 'paused' state."""
        self._pause_btn.configure(text="▶  Tiếp tục", fg_color="#16A34A", hover_color="#15803D")
        self._is_paused = True

    def set_resumed(self) -> None:
        """Set buttons back from paused state."""
        self._pause_btn.configure(text="⏸  Tạm dừng", fg_color="#F59E0B", hover_color="#D97706")
        self._is_paused = False

    def set_idle(self) -> None:
        """Set buttons to 'idle' (not running) state."""
        self._run_btn.configure(state="normal", fg_color="#2563EB")
        self._pause_btn.configure(
            state="disabled",
            text="⏸  Tạm dừng",
            fg_color="#F59E0B",
        )
        self._stop_btn.configure(state="disabled")
        self._reset_btn.configure(state="normal")
        self._is_paused = False

    # --- Handlers ---

    def _handle_run(self) -> None:
        if self._on_run:
            self._on_run()

    def _handle_pause(self) -> None:
        if self._on_pause:
            self._on_pause(not self._is_paused)

    def _handle_stop(self) -> None:
        if self._on_stop:
            self._on_stop()

    def _handle_reset(self) -> None:
        if self._on_reset:
            self._on_reset()

    def _handle_settings(self) -> None:
        if self._on_settings:
            self._on_settings()

    def _handle_history(self) -> None:
        if self._on_history:
            self._on_history()

    def _handle_open_folder(self) -> None:
        if self._on_open_folder:
            self._on_open_folder()
