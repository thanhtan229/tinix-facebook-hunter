"""
Tinix Facebook Down — History Dialog
Shows download history and allows opening folders or clearing history.
"""

import os
import subprocess
import sys

import customtkinter as ctk
from typing import Optional

from utils.history import load_history, clear_history, HistoryEntry


class HistoryDialog(ctk.CTkToplevel):
    """
    Modal dialog showing past download sessions.
    - Table of past sessions
    - Open folder button
    - Clear history button
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.title("Lịch sử tải")
        self.geometry("600x450")
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = master.winfo_x() + (master.winfo_width() - 600) // 2
        y = master.winfo_y() + (master.winfo_height() - 450) // 2
        self.geometry(f"+{x}+{y}")

        self._setup_ui()
        self._load_data()

    def _setup_ui(self) -> None:
        """Build the history dialog UI."""
        main = ctk.CTkFrame(self, fg_color="#F5F5F7", corner_radius=0)
        main.pack(fill="both", expand=True)

        # Header
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 12))

        ctk.CTkLabel(
            header,
            text="📋 Lịch sử tải",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#1E293B",
        ).pack(side="left")

        ctk.CTkButton(
            header,
            text="Xóa tất cả",
            width=100,
            height=32,
            font=ctk.CTkFont(size=12),
            fg_color="#FEE2E2",
            text_color="#DC2626",
            hover_color="#FECACA",
            corner_radius=8,
            command=self._clear_history,
        ).pack(side="right")

        # Scrollable list
        self._scroll_frame = ctk.CTkScrollableFrame(
            main,
            fg_color="#F5F5F7",
            corner_radius=0,
        )
        self._scroll_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

    def _load_data(self) -> None:
        """Load and display history entries."""
        # Clear existing
        for widget in self._scroll_frame.winfo_children():
            widget.destroy()

        history = load_history()

        if not history:
            ctk.CTkLabel(
                self._scroll_frame,
                text="Chưa có lịch sử tải nào",
                font=ctk.CTkFont(size=14),
                text_color="#94A3B8",
            ).pack(pady=40)
            return

        for entry in history:
            self._create_entry_card(entry)

    def _create_entry_card(self, entry: HistoryEntry) -> None:
        """Create a card for a single history entry."""
        card = ctk.CTkFrame(
            self._scroll_frame,
            fg_color="#FFFFFF",
            corner_radius=10,
            border_width=1,
            border_color="#E2E8F0",
        )
        card.pack(fill="x", pady=(0, 8))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)

        # Left: info
        left = ctk.CTkFrame(inner, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)

        # Date and status
        date_frame = ctk.CTkFrame(left, fg_color="transparent")
        date_frame.pack(fill="x")

        ctk.CTkLabel(
            date_frame,
            text=f"📅 {entry.date}",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#1E293B",
        ).pack(side="left")

        # Success/fail badge
        if entry.failed > 0:
            badge_text = f"⚠ {entry.success}/{entry.total_posts}"
            badge_color = "#FEF3C7"
            badge_text_color = "#D97706"
        else:
            badge_text = f"✅ {entry.success}/{entry.total_posts}"
            badge_color = "#DCFCE7"
            badge_text_color = "#16A34A"

        ctk.CTkLabel(
            date_frame,
            text=badge_text,
            font=ctk.CTkFont(size=11),
            text_color=badge_text_color,
            fg_color=badge_color,
            corner_radius=4,
            padx=6,
            pady=2,
        ).pack(side="left", padx=8)

        # URL preview
        url_preview = entry.urls[0][:60] + "..." if entry.urls else "No URLs"
        if len(entry.urls) > 1:
            url_preview += f" (+{len(entry.urls) - 1} more)"

        ctk.CTkLabel(
            left,
            text=url_preview,
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8",
        ).pack(anchor="w", pady=(2, 0))

        # Right: open folder button
        if entry.output_dir:
            ctk.CTkButton(
                inner,
                text="📂",
                width=36,
                height=36,
                font=ctk.CTkFont(size=16),
                fg_color="#F1F5F9",
                text_color="#475569",
                hover_color="#E2E8F0",
                corner_radius=8,
                command=lambda d=entry.output_dir: self._open_folder(d),
            ).pack(side="right")

    def _open_folder(self, path: str) -> None:
        """Open a folder in the file explorer."""
        try:
            if os.path.exists(path):
                if sys.platform == "win32":
                    os.startfile(path)
                elif sys.platform == "darwin":
                    subprocess.run(["open", path])
                else:
                    subprocess.run(["xdg-open", path])
            else:
                # Folder doesn't exist anymore
                pass
        except Exception:
            pass

    def _clear_history(self) -> None:
        """Clear all history."""
        clear_history()
        self._load_data()
