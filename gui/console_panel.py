"""
Tinix Facebook Down — Console Panel
Real-time log display with color-coded messages.
"""

import customtkinter as ctk
from typing import Callable, Optional


class ConsolePanel(ctk.CTkFrame):
    """
    Scrollable log console with color-coded messages.
    Supports INFO (green), WARNING (yellow), ERROR (red) levels.
    """

    # Color scheme for log levels
    COLORS = {
        "INFO": "#16A34A",      # Green
        "WARNING": "#D97706",   # Amber
        "ERROR": "#DC2626",     # Red
        "DEBUG": "#64748B",     # Gray
    }

    LEVEL_ICONS = {
        "INFO": "✅",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "DEBUG": "🔍",
    }

    def __init__(
        self,
        master,
        on_open_diagnostics: Optional[Callable[[], None]] = None,
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

        self._on_open_diagnostics = on_open_diagnostics
        self._setup_ui()
        self._line_count = 0
        self._max_lines = 500

    def _setup_ui(self) -> None:
        """Build the console UI."""
        # Header
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=16, pady=(12, 0))

        ctk.CTkLabel(
            header_frame,
            text="📋 Console Log",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#1E293B",
        ).pack(side="left")

        # Clear button
        ctk.CTkButton(
            header_frame,
            text="Xóa Log",
            width=80,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color="#F1F5F9",
            text_color="#64748B",
            hover_color="#E2E8F0",
            corner_radius=6,
            command=self.clear,
        ).pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            header_frame,
            text="Copy Log",
            width=80,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color="#F1F5F9",
            text_color="#64748B",
            hover_color="#E2E8F0",
            corner_radius=6,
            command=self._copy_log,
        ).pack(side="right")

        ctk.CTkButton(
            header_frame,
            text="Diagnostics",
            width=96,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color="#F1F5F9",
            text_color="#64748B",
            hover_color="#E2E8F0",
            corner_radius=6,
            command=self._open_diagnostics,
        ).pack(side="right", padx=(0, 4))

        # Log text area
        self._textbox = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#F8FAFC",
            text_color="#334155",
            corner_radius=8,
            border_width=1,
            border_color="#E2E8F0",
            state="disabled",
            wrap="word",
        )
        self._textbox.pack(fill="both", expand=True, padx=12, pady=12)

        # Configure text tags for colors
        self._textbox.tag_config("INFO", foreground=self.COLORS["INFO"])
        self._textbox.tag_config("WARNING", foreground=self.COLORS["WARNING"])
        self._textbox.tag_config("ERROR", foreground=self.COLORS["ERROR"])
        self._textbox.tag_config("DEBUG", foreground=self.COLORS["DEBUG"])

    def append_log(self, level: str, message: str) -> None:
        """
        Append a log message to the console.
        Thread-safe: should be called via root.after() from background threads.

        Args:
            level: Log level (INFO, WARNING, ERROR, DEBUG).
            message: The log message text.
        """
        self._textbox.configure(state="normal")

        # Auto-trim old lines if exceeding max
        self._line_count += 1
        if self._line_count > self._max_lines:
            self._textbox.delete("1.0", "2.0")
            self._line_count -= 1

        # Insert message with color tag
        tag = level if level in self.COLORS else "INFO"
        self._textbox.insert("end", message + "\n", tag)

        # Auto-scroll to bottom
        self._textbox.see("end")
        self._textbox.configure(state="disabled")

    def clear(self) -> None:
        """Clear all log messages."""
        self._textbox.configure(state="normal")
        self._textbox.delete("1.0", "end")
        self._textbox.configure(state="disabled")
        self._line_count = 0

    def _copy_log(self) -> None:
        """Copy all log text to clipboard."""
        self._textbox.configure(state="normal")
        text = self._textbox.get("1.0", "end").strip()
        self._textbox.configure(state="disabled")

        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _open_diagnostics(self) -> None:
        """Open diagnostics reports from the host app."""
        if self._on_open_diagnostics:
            self._on_open_diagnostics()

    def get_log_text(self) -> str:
        """Get all log text as a string."""
        self._textbox.configure(state="normal")
        text = self._textbox.get("1.0", "end").strip()
        self._textbox.configure(state="disabled")
        return text
