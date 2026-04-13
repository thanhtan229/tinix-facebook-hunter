"""
Tinix Facebook Down — Schedule Preview Dialog
Modal dialog showing the generated schedule before confirming to DB.
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
from typing import List, Callable, Optional


_BG = "#0F172A"
_CARD = "#1E293B"
_CARD2 = "#334155"
_BORDER = "#475569"
_TEXT = "#F1F5F9"
_TEXT2 = "#94A3B8"
_ACCENT = "#3B82F6"
_GREEN = "#16A34A"
_RED = "#DC2626"


class SchedulePreviewDialog(ctk.CTkToplevel):
    """
    Modal preview of the generated schedule.
    Shows: Content Name, Target Page, Planned Time, CTA Status.
    On confirm → calls on_confirm callback with the records.
    """

    def __init__(
        self,
        master,
        records: List[dict],
        on_confirm: Callable[[List[dict]], None],
    ):
        super().__init__(master)
        self._records = records
        self._on_confirm = on_confirm
        self._confirmed = False

        self.title("📅 Schedule Preview")
        self.geometry("750x520")
        self.resizable(True, True)
        self.configure(fg_color=_BG)

        # Modal behavior
        self.transient(master)
        self.grab_set()

        self._build_ui()
        self.after(50, self.focus_force)

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(
            header, text="📅 Xem trước lịch đăng",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=_TEXT,
        ).pack(side="left")

        ctk.CTkLabel(
            header, text=f"{len(self._records)} bài viết",
            font=ctk.CTkFont(size=13), text_color=_TEXT2,
        ).pack(side="right")

        # Treeview
        tree_frame = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=12,
                                  border_width=1, border_color=_BORDER)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        inner = ctk.CTkFrame(tree_frame, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=10, pady=10)

        style = ttk.Style()
        style.configure("Preview.Treeview",
            background="#1E293B", foreground="#F1F5F9",
            fieldbackground="#1E293B", borderwidth=0,
            font=("Consolas", 10), rowheight=26,
        )
        style.configure("Preview.Treeview.Heading",
            background="#334155", foreground="#F1F5F9",
            font=("Arial", 10, "bold"), borderwidth=0,
        )
        style.map("Preview.Treeview",
            background=[("selected", "#3B82F6")],
            foreground=[("selected", "#FFFFFF")],
        )

        columns = ("idx", "folder", "page", "time", "cta")
        scrollbar = ttk.Scrollbar(inner, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        self._tree = ttk.Treeview(
            inner, columns=columns, show="headings",
            style="Preview.Treeview", yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=self._tree.yview)

        self._tree.heading("idx", text="#")
        self._tree.heading("folder", text="📁 Content")
        self._tree.heading("page", text="📄 Target Page")
        self._tree.heading("time", text="⏰ Planned Time")
        self._tree.heading("cta", text="💬 CTA")

        self._tree.column("idx", width=40, anchor="center")
        self._tree.column("folder", width=200, minwidth=120)
        self._tree.column("page", width=150, minwidth=100)
        self._tree.column("time", width=160, minwidth=120, anchor="center")
        self._tree.column("cta", width=60, minwidth=40, anchor="center")

        self._tree.tag_configure("odd", background="#1E293B")
        self._tree.tag_configure("even", background="#243044")

        for idx, rec in enumerate(self._records):
            tag = "odd" if idx % 2 == 0 else "even"
            cta_icon = "✅" if rec.get("cta") else "—"
            self._tree.insert("", "end", values=(
                idx + 1,
                rec.get("folder_name", ""),
                rec["page_name"],
                rec["scheduled_time"],
                cta_icon,
            ), tags=(tag,))

        self._tree.pack(fill="both", expand=True)

        # Summary
        summary = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=10,
                               border_width=1, border_color=_BORDER)
        summary.pack(fill="x", padx=16, pady=(0, 8))

        inner_s = ctk.CTkFrame(summary, fg_color="transparent")
        inner_s.pack(fill="x", padx=12, pady=8)

        # Calculate stats
        days = set()
        for r in self._records:
            day = r["scheduled_time"].split(" ")[0] if " " in r["scheduled_time"] else r["scheduled_time"]
            days.add(day)

        ctk.CTkLabel(
            inner_s,
            text=f"📊 {len(self._records)} bài  •  {len(days)} ngày  •  Page: {self._records[0]['page_name'] if self._records else '—'}",
            font=ctk.CTkFont(size=12), text_color=_TEXT2,
        ).pack(side="left")

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkButton(
            btn_frame, text="❌ Hủy", width=100, height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=_CARD2, hover_color="#475569", corner_radius=10,
            text_color=_TEXT,
            command=self.destroy,
        ).pack(side="right")

        ctk.CTkButton(
            btn_frame, text="✅ XÁC NHẬN LỊCH", height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=_GREEN, hover_color="#15803D", corner_radius=10,
            command=self._confirm,
        ).pack(side="right", padx=8)

    def _confirm(self):
        self._confirmed = True
        self._on_confirm(self._records)
        self.destroy()
