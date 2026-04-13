"""
Tinix Facebook Down — Smart Calendar Dialog
Displays post_history in a list view with edit/delete support.
"""

from datetime import datetime, timedelta
from typing import Callable, List, Optional

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, ttk

from core.db_storage import (
    get_db_path,
    get_schedule_history_filtered,
    retry_failed_posts,
    update_history_scheduled_time,
    delete_history_records,
)
from utils import config

# ── Theme ──────────────────────────────────────────────────────────────────
_BG     = "#0F172A"
_CARD   = "#1E293B"
_CARD2  = "#334155"
_BORDER = "#475569"
_TEXT   = "#F1F5F9"
_TEXT2  = "#94A3B8"
_ACCENT = "#3B82F6"
_GREEN  = "#16A34A"
_RED    = "#DC2626"
_YELLOW = "#F59E0B"
_PURPLE = "#7C3AED"

STATUS_COLOR = {
    "Pending":   _YELLOW,
    "Scheduled": _ACCENT,
    "Success":   _GREEN,
    "Failed":    _RED,
}
STATUS_ICON = {
    "Pending":   "🕒",
    "Scheduled": "📅",
    "Success":   "✅",
    "Failed":    "❌",
}


class CalendarDialog(ctk.CTkToplevel):
    """Smart Calendar showing scheduled posts."""

    def __init__(
        self,
        master,
        page_data: Optional[List[dict]] = None,
        on_execute: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self._page_data = page_data or []
        self._on_execute = on_execute
        self._records: List[dict] = []

        self.title("📅 Smart Calendar")
        self.geometry("1100x700")
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()

        self.update_idletasks()
        x = master.winfo_x() + (master.winfo_width() - 1100) // 2
        y = master.winfo_y() + (master.winfo_height() - 700) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")

        self._setup_ui()
        self._load_data()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.configure(fg_color=_BG)

        # ── Title bar ──
        hdr = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=0, height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(
            hdr, text="📅 Smart Calendar",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=_TEXT,
        ).pack(side="left", padx=16)
        ctk.CTkButton(
            hdr, text="✕", width=36, height=32,
            font=ctk.CTkFont(size=13), fg_color="transparent",
            text_color=_TEXT2, hover_color=_CARD2, corner_radius=6,
            command=self.destroy,
        ).pack(side="right", padx=8)

        # ── Filter bar ──
        fbar = ctk.CTkFrame(self, fg_color=_CARD2, corner_radius=0, height=44)
        fbar.pack(fill="x")
        fbar.pack_propagate(False)

        ctk.CTkLabel(fbar, text="Từ:", font=ctk.CTkFont(size=11),
                     text_color=_TEXT2).pack(side="left", padx=(12, 4))
        self._from_var = ctk.StringVar(value=datetime.now().strftime("%Y-%m-01"))
        ctk.CTkEntry(fbar, textvariable=self._from_var, width=100, height=28,
                     font=ctk.CTkFont(size=11), fg_color=_CARD, text_color=_TEXT,
                     border_color=_BORDER, corner_radius=6).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(fbar, text="Đến:", font=ctk.CTkFont(size=11),
                     text_color=_TEXT2).pack(side="left", padx=(0, 4))
        now = datetime.now()
        last_day = (now.replace(month=now.month % 12 + 1, day=1) - timedelta(days=1)).day \
            if now.month < 12 else 31
        self._to_var = ctk.StringVar(value=now.strftime(f"%Y-%m-{last_day}"))
        ctk.CTkEntry(fbar, textvariable=self._to_var, width=100, height=28,
                     font=ctk.CTkFont(size=11), fg_color=_CARD, text_color=_TEXT,
                     border_color=_BORDER, corner_radius=6).pack(side="left", padx=(0, 8))

        ctk.CTkLabel(fbar, text="Trạng thái:", font=ctk.CTkFont(size=11),
                     text_color=_TEXT2).pack(side="left", padx=(0, 4))
        self._status_filter_var = ctk.StringVar(value="Tất cả")
        ctk.CTkOptionMenu(
            fbar, values=["Tất cả", "Pending", "Scheduled", "Success", "Failed"],
            variable=self._status_filter_var,
            width=110, height=28, font=ctk.CTkFont(size=11),
            fg_color=_CARD, button_color=_CARD2,
            button_hover_color=_BORDER, text_color=_TEXT, corner_radius=6,
            command=lambda _: self._load_data(),
        ).pack(side="left", padx=(0, 12))

        ctk.CTkButton(fbar, text="🔍 Lọc", width=72, height=28,
                      font=ctk.CTkFont(size=11, weight="bold"),
                      fg_color=_ACCENT, hover_color="#2563EB", corner_radius=6,
                      command=self._load_data).pack(side="left")

        ctk.CTkLabel(fbar, text="Trang:", font=ctk.CTkFont(size=11),
                     text_color=_TEXT2).pack(side="left", padx=(16, 4))
        page_names = ["Tất cả"] + [p["name"] for p in self._page_data]
        self._page_filter_var = ctk.StringVar(value="Tất cả")
        ctk.CTkOptionMenu(
            fbar, values=page_names, variable=self._page_filter_var,
            width=140, height=28, font=ctk.CTkFont(size=11),
            fg_color=_CARD, button_color=_CARD2,
            button_hover_color=_BORDER, text_color=_TEXT, corner_radius=6,
            command=lambda _: self._load_data(),
        ).pack(side="left")

        # ── Treeview ──
        tree_frame = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=10,
                                  border_width=1, border_color=_BORDER)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(8, 0))

        cols = ("scheduled_time", "page_name", "folder_name", "caption", "status", "error_log")
        col_labels = ("Thời gian lên lịch", "Trang", "Nội dung", "Caption", "Trạng thái", "Lỗi")
        col_widths = (150, 160, 160, 220, 100, 200)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Cal.Treeview",
                        background=_CARD, foreground=_TEXT,
                        fieldbackground=_CARD, borderwidth=0,
                        font=("Segoe UI", 10), rowheight=26)
        style.configure("Cal.Treeview.Heading",
                        background=_CARD2, foreground=_TEXT2,
                        font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.map("Cal.Treeview", background=[("selected", _ACCENT)])

        tv_outer = tk.Frame(tree_frame, bg=_CARD)
        tv_outer.pack(fill="both", expand=True, padx=6, pady=6)

        vsb = ttk.Scrollbar(tv_outer, orient="vertical")
        vsb.pack(side="right", fill="y")
        hsb = ttk.Scrollbar(tv_outer, orient="horizontal")
        hsb.pack(side="bottom", fill="x")

        self._tree = ttk.Treeview(
            tv_outer, columns=cols, show="headings",
            style="Cal.Treeview",
            yscrollcommand=vsb.set, xscrollcommand=hsb.set,
            selectmode="extended",
        )
        vsb.config(command=self._tree.yview)
        hsb.config(command=self._tree.xview)
        self._tree.pack(fill="both", expand=True)

        for col, lbl, w in zip(cols, col_labels, col_widths):
            self._tree.heading(col, text=lbl, command=lambda c=col: self._sort_by(c))
            self._tree.column(col, width=w, minwidth=60, anchor="w")

        self._tree.tag_configure("Pending",   foreground=_YELLOW)
        self._tree.tag_configure("Scheduled", foreground=_ACCENT)
        self._tree.tag_configure("Success",   foreground=_GREEN)
        self._tree.tag_configure("Failed",    foreground=_RED)
        self._tree.tag_configure("odd",       background="#16203A")
        self._tree.tag_configure("even",      background=_CARD)

        self._tree.bind("<Button-3>", self._on_right_click)
        self._tree.bind("<Double-1>", self._on_double_click)

        # ── Bottom bar ──
        bot = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=0, height=48)
        bot.pack(fill="x", pady=(4, 0))
        bot.pack_propagate(False)

        self._count_label = ctk.CTkLabel(bot, text="", font=ctk.CTkFont(size=11), text_color=_TEXT2)
        self._count_label.pack(side="left", padx=12)

        ctk.CTkButton(bot, text="Đóng", width=72, height=32,
                      font=ctk.CTkFont(size=11),
                      fg_color=_CARD2, hover_color=_BORDER, text_color=_TEXT,
                      corner_radius=8, command=self.destroy).pack(side="right", padx=(4, 12))

        ctk.CTkButton(bot, text="▶ Execute Selected", width=140, height=32,
                      font=ctk.CTkFont(size=11, weight="bold"),
                      fg_color=_GREEN, hover_color="#15803D", corner_radius=8,
                      command=self._on_execute_selected).pack(side="right", padx=4)

        ctk.CTkButton(bot, text="🗑 Xóa", width=80, height=32,
                      font=ctk.CTkFont(size=11, weight="bold"),
                      fg_color=_RED, hover_color="#B91C1C", corner_radius=8,
                      command=self._on_delete_selected).pack(side="right", padx=4)

        ctk.CTkButton(bot, text="✏ Sửa giờ", width=90, height=32,
                      font=ctk.CTkFont(size=11, weight="bold"),
                      fg_color=_PURPLE, hover_color="#6D28D9", corner_radius=8,
                      command=self._on_edit_time_selected).pack(side="right", padx=4)

        ctk.CTkButton(bot, text="🔁 Retry Failed", width=120, height=32,
                      font=ctk.CTkFont(size=11, weight="bold"),
                      fg_color=_YELLOW, hover_color="#D97706", text_color="#000",
                      corner_radius=8, command=self._on_retry_selected).pack(side="right", padx=4)

    # ── Data ───────────────────────────────────────────────────────────────

    def _load_data(self):
        db_path = get_db_path(config.get("scraper_db_path", ""))
        page_name = self._page_filter_var.get()
        status = self._status_filter_var.get()
        records = get_schedule_history_filtered(
            db_path,
            page_name=page_name if page_name != "Tất cả" else "",
            date_from=self._from_var.get().strip(),
            date_to=self._to_var.get().strip(),
            status=status if status != "Tất cả" else "",
        )
        # Sort by scheduled_time ascending (earliest first)
        records.sort(key=lambda r: r.get("scheduled_time", ""))
        self._records = records
        self._populate_tree(records)

    def _populate_tree(self, records: List[dict]):
        for child in self._tree.get_children():
            self._tree.delete(child)

        for idx, r in enumerate(records):
            icon = STATUS_ICON.get(r["status"], "")
            err = r["error_log"][:60] + ("..." if len(r["error_log"]) > 60 else "") \
                if r["error_log"] else ""
            caption = r.get("caption", "")
            caption_short = caption[:60] + ("..." if len(caption) > 60 else "") if caption else ""
            row_tag = "odd" if idx % 2 == 0 else "even"
            self._tree.insert(
                "", "end",
                iid=str(r["history_id"]),
                values=(
                    r["scheduled_time"],
                    r["page_name"],
                    r["folder_name"],
                    caption_short,
                    f"{icon} {r['status']}",
                    err,
                ),
                tags=(r["status"], row_tag),
            )

        total = len(records)
        counts = {}
        for r in records:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        parts = [f"📊 Tổng: {total}"]
        for st, cnt in counts.items():
            parts.append(f"{STATUS_ICON.get(st,'')} {st}: {cnt}")
        self._count_label.configure(text="  |  ".join(parts))

    def _sort_by(self, col: str):
        items = [(self._tree.set(k, col), k) for k in self._tree.get_children("")]
        items.sort()
        for idx, (_, k) in enumerate(items):
            self._tree.move(k, "", idx)

    # ── Context menu ───────────────────────────────────────────────────────

    def _on_right_click(self, event):
        item = self._tree.identify_row(event.y)
        if not item:
            return
        self._tree.selection_set(item)
        menu = tk.Menu(self, tearoff=0, bg=_CARD2, fg=_TEXT,
                       activebackground=_ACCENT, activeforeground="#fff",
                       font=("Segoe UI", 10))
        menu.add_command(label="✏ Sửa giờ đăng", command=self._on_edit_time_selected)
        menu.add_command(label="🗑 Xóa", command=self._on_delete_selected)
        menu.add_separator()
        menu.add_command(label="🔁 Retry (đặt lại Pending)", command=self._on_retry_selected)
        menu.add_command(label="▶ Execute ngay", command=self._on_execute_selected)
        menu.tk_popup(event.x_root, event.y_root)

    def _on_double_click(self, event):
        """Double-click: edit scheduled time."""
        item = self._tree.identify_row(event.y)
        if not item:
            return
        self._on_edit_time_selected()

    # ── Helpers ────────────────────────────────────────────────────────────

    def _get_selected_history_ids(self) -> List[int]:
        try:
            return [int(iid) for iid in self._tree.selection()]
        except Exception:
            return []

    # ── Actions ────────────────────────────────────────────────────────────

    def _on_edit_time_selected(self):
        """Open a small dialog to edit the scheduled time of selected record(s)."""
        ids = self._get_selected_history_ids()
        if not ids:
            messagebox.showwarning("Tinix", "Chọn ít nhất 1 bài để sửa!", parent=self)
            return

        # Show current time if single selection
        current = ""
        if len(ids) == 1:
            rec = next((r for r in self._records if r["history_id"] == ids[0]), None)
            if rec:
                current = rec["scheduled_time"]

        dlg = ctk.CTkToplevel(self)
        dlg.title("Sửa giờ đăng")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(fg_color=_BG)
        # Center on the calendar dialog
        self.update_idletasks()
        w, h = 340, 140
        cx = self.winfo_x() + (self.winfo_width() - w) // 2
        cy = self.winfo_y() + (self.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{max(0, cx)}+{max(0, cy)}")

        ctk.CTkLabel(dlg, text="Thời gian mới (YYYY-MM-DD HH:MM):",
                     font=ctk.CTkFont(size=11), text_color=_TEXT2).pack(pady=(16, 4))
        time_var = ctk.StringVar(value=current)
        entry = ctk.CTkEntry(dlg, textvariable=time_var, width=200, height=32,
                             font=ctk.CTkFont(size=12), fg_color=_CARD2, text_color=_TEXT,
                             border_color=_BORDER, corner_radius=6, justify="center")
        entry.pack()
        entry.focus()

        def _save():
            new_time = time_var.get().strip()
            try:
                datetime.strptime(new_time, "%Y-%m-%d %H:%M")
            except ValueError:
                messagebox.showwarning("Tinix", "Định dạng không hợp lệ!\nDùng: YYYY-MM-DD HH:MM", parent=dlg)
                return
            db_path = get_db_path(config.get("scraper_db_path", ""))
            updated = 0
            for hid in ids:
                if update_history_scheduled_time(db_path, hid, new_time):
                    updated += 1
            dlg.destroy()
            self._load_data()

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(pady=12)
        ctk.CTkButton(btn_row, text="Huỷ", width=80, height=30,
                      fg_color=_CARD2, hover_color=_BORDER, text_color=_TEXT2,
                      corner_radius=8, command=dlg.destroy).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="✓ Lưu", width=80, height=30,
                      font=ctk.CTkFont(size=11, weight="bold"),
                      fg_color=_ACCENT, hover_color="#2563EB", corner_radius=8,
                      command=_save).pack(side="left", padx=4)
        dlg.bind("<Return>", lambda e: _save())

    def _on_delete_selected(self):
        ids = self._get_selected_history_ids()
        if not ids:
            messagebox.showwarning("Tinix", "Chọn ít nhất 1 bài để xóa!", parent=self)
            return
        if not messagebox.askyesno("Xóa", f"Xóa {len(ids)} bài đã chọn?", parent=self):
            return
        db_path = get_db_path(config.get("scraper_db_path", ""))
        delete_history_records(db_path, ids)
        self._load_data()

    def _on_retry_selected(self):
        ids = self._get_selected_history_ids()
        if not ids:
            ids = [r["history_id"] for r in self._records if r["status"] == "Failed"]
        if not ids:
            messagebox.showinfo("Tinix", "Không có bài Failed nào!", parent=self)
            return
        db_path = get_db_path(config.get("scraper_db_path", ""))
        retry_failed_posts(db_path, ids)
        self._load_data()

    def _on_execute_selected(self):
        if not self._on_execute:
            messagebox.showwarning("Tinix", "Execute handler không được đăng ký!", parent=self)
            return
        ids = self._get_selected_history_ids()
        if not ids:
            messagebox.showwarning("Tinix", "Chọn ít nhất 1 bài để thực thi!", parent=self)
            return
        selected = [r for r in self._records if r["history_id"] in ids and r["status"] == "Pending"]
        if not selected:
            messagebox.showinfo("Tinix", "Chỉ bài Pending mới có thể thực thi!", parent=self)
            return
        self.destroy()
        self._on_execute(selected)
