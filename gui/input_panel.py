"""
Tinix Facebook Down — Input Panel
URL input and output directory selection.
"""

import customtkinter as ctk
from tkinter import filedialog
from typing import Optional

from utils import config


class InputPanel(ctk.CTkFrame):
    """
    Input panel containing:
    - Multi-line URL input
    - Output directory selection
    """

    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            fg_color="#FFFFFF",
            corner_radius=12,
            border_width=1,
            border_color="#E2E8F0",
            **kwargs,
        )

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the input panel UI."""
        # ===== URL Input Section =====
        url_frame = ctk.CTkFrame(self, fg_color="transparent")
        url_frame.pack(fill="x", padx=16, pady=(12, 0))

        url_header = ctk.CTkFrame(url_frame, fg_color="transparent")
        url_header.pack(fill="x")

        ctk.CTkLabel(
            url_header,
            text="🔗 Facebook URLs",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#1E293B",
        ).pack(side="left")

        ctk.CTkButton(
            url_header,
            text="Dán từ Clipboard",
            width=120,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color="#EFF6FF",
            text_color="#2563EB",
            hover_color="#DBEAFE",
            corner_radius=6,
            command=self._paste_urls,
        ).pack(side="right")

        ctk.CTkLabel(
            url_frame,
            text="Nhập link bài viết Facebook, mỗi link một dòng",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8",
        ).pack(anchor="w", pady=(2, 4))

        self._url_textbox = ctk.CTkTextbox(
            url_frame,
            height=55,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#F8FAFC",
            text_color="#334155",
            corner_radius=8,
            border_width=1,
            border_color="#E2E8F0",
        )
        self._url_textbox.pack(fill="x")

        # ===== Output Directory Section =====
        dir_frame = ctk.CTkFrame(self, fg_color="transparent")
        dir_frame.pack(fill="x", padx=16, pady=(10, 12))

        ctk.CTkLabel(
            dir_frame,
            text="📁 Thư mục lưu",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#1E293B",
        ).pack(anchor="w")

        dir_row = ctk.CTkFrame(dir_frame, fg_color="transparent")
        dir_row.pack(fill="x", pady=(4, 0))

        self._dir_entry = ctk.CTkEntry(
            dir_row,
            font=ctk.CTkFont(size=12),
            fg_color="#F8FAFC",
            text_color="#334155",
            border_color="#E2E8F0",
            corner_radius=8,
            height=36,
        )
        self._dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Set default output dir
        default_dir = config.get("output_dir", str(config.DEFAULTS["output_dir"]))
        self._dir_entry.insert(0, default_dir)

        ctk.CTkButton(
            dir_row,
            text="Chọn...",
            width=80,
            height=36,
            font=ctk.CTkFont(size=12),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            corner_radius=8,
            command=self._browse_directory,
        ).pack(side="right")

    # --- Public API ---

    def get_urls(self) -> str:
        """Get the URL text content."""
        return self._url_textbox.get("1.0", "end").strip()

    def get_output_dir(self) -> str:
        """Get the output directory path."""
        return self._dir_entry.get().strip()

    def set_urls(self, text: str) -> None:
        """Set URL textbox content."""
        self._url_textbox.delete("1.0", "end")
        self._url_textbox.insert("1.0", text)

    def clear(self) -> None:
        """Clear all inputs."""
        self._url_textbox.delete("1.0", "end")

    def set_state(self, state: str) -> None:
        """Enable or disable inputs. state: 'normal' or 'disabled'"""
        self._url_textbox.configure(state=state)
        self._dir_entry.configure(state=state)

    # --- Private Methods ---

    def _paste_urls(self) -> None:
        """Paste clipboard content into URL textbox."""
        try:
            text = self.clipboard_get()
            if text:
                self._url_textbox.insert("end", text)
        except Exception:
            pass

    def _browse_directory(self) -> None:
        """Open a directory chooser dialog."""
        current = self._dir_entry.get().strip()
        directory = filedialog.askdirectory(
            title="Chọn thư mục lưu",
            initialdir=current if current else None,
        )
        if directory:
            self._dir_entry.delete(0, "end")
            self._dir_entry.insert(0, directory)
