"""
Tinix Facebook Down — Missed Post Recovery Dialog (V15.0)
Shown at startup when there are App-mode posts that were missed.
"""

import threading
from datetime import datetime, timedelta
from typing import Callable, List, Optional

import customtkinter as ctk
from tkinter import messagebox

from core.db_storage import get_db_path, get_missed_app_posts, duplicate_history_record
from utils import config

_BG    = "#0F172A"
_CARD  = "#1E293B"
_CARD2 = "#334155"
_BORDER = "#475569"
_TEXT  = "#F1F5F9"
_TEXT2 = "#94A3B8"
_ACCENT = "#3B82F6"
_GREEN = "#16A34A"
_RED   = "#DC2626"
_YELLOW = "#F59E0B"


class MissedPostDialog(ctk.CTkToplevel):
    """
    Startup recovery notification for missed App-mode scheduled posts.

    Options:
    - "Đăng bù ngay": Execute all missed posts immediately (3-5 min delay between)
    - "Dời lịch": Reschedule each missed post to now+offset
    - "Bỏ qua": Dismiss without action
    """

    def __init__(
        self,
        master,
        missed: List[dict],
        on_execute_now: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self._missed = missed
        self._on_execute_now = on_execute_now

        self.title("⚠ Phát hiện bài chưa đăng")
        w, h = 540, 400
        self.geometry(f"{w}x{h}")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = master.winfo_x() + (master.winfo_width() - w) // 2
        y = master.winfo_y() + (master.winfo_height() - h) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")

        self._setup_ui()

    def _setup_ui(self):
        self.configure(fg_color=_BG)

        # Header
        hdr = ctk.CTkFrame(self, fg_color=_RED, corner_radius=0, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr, text=f"⚠  Phát hiện {len(self._missed)} bài chưa được đăng!",
            font=ctk.CTkFont(size=14, weight="bold"), text_color="#FFF",
        ).pack(side="left", padx=16)

        # Subtitle
        ctk.CTkLabel(
            self,
            text="Các bài sau đã qua thời gian lên lịch nhưng chưa được đăng\n"
                 "(ứng dụng có thể đã bị đóng khi đến giờ đăng).",
            font=ctk.CTkFont(size=12),
            text_color=_TEXT2,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(12, 4))

        # List of missed posts
        list_frame = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=10,
                                  border_width=1, border_color=_BORDER)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        from tkinter import Text, Scrollbar
        outer = ctk.CTkFrame(list_frame, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=6, pady=6)
        vsb = Scrollbar(outer, orient="vertical")
        vsb.pack(side="right", fill="y")
        txt = Text(
            outer, height=8,
            bg=_CARD, fg=_TEXT2,
            font=("Consolas", 9), relief="flat", bd=0,
            wrap="word", state="normal",
            yscrollcommand=vsb.set,
        )
        vsb.config(command=txt.yview)
        txt.pack(side="left", fill="both", expand=True)

        for r in self._missed:
            try:
                sched = datetime.strptime(r["scheduled_time"], "%Y-%m-%d %H:%M")
                delta = datetime.now() - sched
                ago = f"{int(delta.total_seconds()//3600)}h {int((delta.total_seconds()%3600)//60)}m trước"
            except Exception:
                ago = r["scheduled_time"]
            txt.insert("end", f"• [{r['page_name']}] {r['folder_name']} — {ago}\n")
        txt.configure(state="disabled")

        # Delay note
        ctk.CTkLabel(
            self,
            text="💡 'Đăng bù ngay' sẽ đăng lần lượt, chờ 3-5 phút giữa mỗi bài.",
            font=ctk.CTkFont(size=10),
            text_color="#64748B",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkButton(
            btn_row, text="Bỏ qua", width=90, height=36,
            font=ctk.CTkFont(size=12),
            fg_color=_CARD2, hover_color=_BORDER, text_color=_TEXT2,
            corner_radius=8, command=self.destroy,
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="📆 Dời lịch (+7 ngày)", width=180, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=_ACCENT, hover_color="#2563EB", corner_radius=8,
            command=self._on_reschedule,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            btn_row, text="⚡ Đăng bù ngay", width=150, height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=_GREEN, hover_color="#15803D", corner_radius=8,
            command=self._on_post_now,
        ).pack(side="right")

    # ── Actions ────────────────────────────────────────────────────────────

    def _on_reschedule(self):
        """Clone each missed record to scheduled_time + 7 days, status=Pending."""
        db_path = get_db_path(config.get("scraper_db_path", ""))
        cloned = 0
        for r in self._missed:
            try:
                orig = datetime.strptime(r["scheduled_time"], "%Y-%m-%d %H:%M")
            except ValueError:
                orig = datetime.now()
            new_time = (orig + timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
            new_id = duplicate_history_record(db_path, r["history_id"], new_time)
            if new_id > 0:
                cloned += 1
        self.destroy()
        messagebox.showinfo(
            "Tinix",
            f"✅ Đã dời lịch {cloned} bài sang +7 ngày.\n"
            "Dùng 'Execute Pending' khi đến giờ.",
        )

    def _on_post_now(self):
        """Pass missed records to the execute handler (with 3-5 min delays)."""
        if not self._on_execute_now:
            messagebox.showwarning("Tinix", "Execute handler không khả dụng!")
            self.destroy()
            return
        if not messagebox.askyesno(
            "Đăng bù",
            f"Bắt đầu đăng bù {len(self._missed)} bài?\n"
            "Sẽ chờ 3-5 phút giữa mỗi bài.",
            parent=self,
        ):
            return
        records = list(self._missed)
        self.destroy()
        self._on_execute_now(records)
