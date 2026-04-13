"""
Tinix Facebook Down — Duplicate URL Dialog
Shows when a user enters a URL that already exists in the database.
Options: Skip / Rescan / Open Folder.
"""

import os
import customtkinter as ctk
from typing import Optional


class DuplicateAction:
    SKIP = "skip"
    RESCAN = "rescan"
    OPEN_FOLDER = "open_folder"
    SCAN_NEW = "scan_new"


class DuplicateDialog(ctk.CTkToplevel):
    """
    Modal dialog shown when a duplicate URL is detected.
    Returns one of: 'skip', 'rescan', 'open_folder'.
    """

    def __init__(
        self,
        master,
        page_name: str,
        page_url: str,
        post_count: int,
        last_scraped: str,
        group_name: str = "",
        **kwargs,
    ):
        super().__init__(master, **kwargs)

        self.result: Optional[str] = None
        self._page_url = page_url

        # Window setup
        self.title("⚠ URL đã tồn tại")
        self.geometry("460x360")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.configure(fg_color="#1E293B")

        # Center on parent
        self.update_idletasks()
        px = master.winfo_rootx() + (master.winfo_width() - 460) // 2
        py = master.winfo_rooty() + (master.winfo_height() - 360) // 2
        self.geometry(f"+{max(0, px)}+{max(0, py)}")

        self._build_ui(page_name, page_url, post_count, last_scraped, group_name)

        # Block until closed
        self.protocol("WM_DELETE_WINDOW", self._on_skip)
        self.focus_force()

    def _build_ui(
        self,
        page_name: str,
        page_url: str,
        post_count: int,
        last_scraped: str,
        group_name: str,
    ) -> None:
        """Build the dialog UI."""
        # Icon + Title
        ctk.CTkLabel(
            self,
            text="⚠️  URL này đã được quét trước đó",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#FBBF24",
        ).pack(padx=20, pady=(20, 8))

        # Info card
        info_card = ctk.CTkFrame(
            self, fg_color="#334155", corner_radius=10,
            border_width=1, border_color="#475569",
        )
        info_card.pack(fill="x", padx=20, pady=(0, 16))

        info_text = f"📄  {page_name or 'Không rõ tên'}"
        if group_name:
            info_text += f"  •  📁 {group_name}"
        info_text += f"\n📝  {post_count} bài viết  •  🕐 {last_scraped or 'N/A'}"

        ctk.CTkLabel(
            info_card,
            text=info_text,
            font=ctk.CTkFont(size=13),
            text_color="#E2E8F0",
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=16, pady=12)

        # Question
        ctk.CTkLabel(
            self,
            text="Bạn muốn làm gì?",
            font=ctk.CTkFont(size=14),
            text_color="#CBD5E1",
        ).pack(pady=(0, 12))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))

        # Configure grid for 2x2 buttons
        btn_frame.columnconfigure((0, 1), weight=1)

        # Scan New (primary action — top-left)
        ctk.CTkButton(
            btn_frame,
            text="🆕  Quét bài mới",
            height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#7C3AED", hover_color="#6D28D9",
            corner_radius=10,
            command=self._on_scan_new,
        ).grid(row=0, column=0, padx=(0, 4), pady=(0, 6), sticky="ew")

        # Rescan (top-right)
        ctk.CTkButton(
            btn_frame,
            text="🔄  Quét lại",
            height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2563EB", hover_color="#1D4ED8",
            corner_radius=10,
            command=self._on_rescan,
        ).grid(row=0, column=1, padx=(4, 0), pady=(0, 6), sticky="ew")

        # Skip (bottom-left)
        ctk.CTkButton(
            btn_frame,
            text="⏭  Bỏ qua",
            height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#475569", hover_color="#64748B",
            corner_radius=10,
            command=self._on_skip,
        ).grid(row=1, column=0, padx=(0, 4), sticky="ew")

        # Open Folder (bottom-right)
        ctk.CTkButton(
            btn_frame,
            text="📂  Mở thư mục",
            height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#16A34A", hover_color="#15803D",
            corner_radius=10,
            command=self._on_open_folder,
        ).grid(row=1, column=1, padx=(4, 0), sticky="ew")

    def _on_skip(self) -> None:
        self.result = DuplicateAction.SKIP
        self.destroy()

    def _on_rescan(self) -> None:
        self.result = DuplicateAction.RESCAN
        self.destroy()

    def _on_open_folder(self) -> None:
        self.result = DuplicateAction.OPEN_FOLDER
        self.destroy()

    def _on_scan_new(self) -> None:
        self.result = DuplicateAction.SCAN_NEW
        self.destroy()

    def get_result(self) -> str:
        """Block and wait for user choice. Call from main thread."""
        self.wait_window()
        return self.result or DuplicateAction.SKIP
