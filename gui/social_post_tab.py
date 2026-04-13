"""
Tinix Facebook Down — Photo Post Tab (Library + Scheduling + Execution)
Smart Library with photo content import, search, scheduling engine, preview, and auto-posting.
"""

import os
import sqlite3
import threading
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

import customtkinter as ctk
import json

from core.db_storage import (
    get_db_path, save_content_pool, get_all_content_pool,
    delete_content_pool, get_all_accounts,
    bulk_insert_schedule, check_duplicate_schedule,
    reset_pending_schedule, get_managed_pages, save_managed_pages,
    update_content_caption,
    get_managed_page_groups, update_managed_page_group,
    update_history_status_with_error, get_schedule_history_filtered,
)
from core.content_scanner import scan_main_folder, count_media_in_folder
from core.auto_poster import AutoPoster
from gui.schedule_preview import SchedulePreviewDialog
from utils import config, logger


# ─── Dark Theme Constants ──────────────────────────────────────────────────

_BG = "#0F172A"
_CARD = "#1E293B"
_CARD2 = "#334155"
_BORDER = "#475569"
_TEXT = "#F1F5F9"
_TEXT2 = "#94A3B8"
_ACCENT = "#3B82F6"
_GREEN = "#16A34A"
_RED = "#DC2626"
_YELLOW = "#F59E0B"
_PURPLE = "#7C3AED"


class SocialPostTab(ctk.CTkFrame):
    """Photo Post - Smart Library + Scheduling + Execution Engine."""

    TAB_TITLE = "Photo Post"
    TAB_SUBTITLE = "Photo Library & Scheduler"
    SHOW_PLATFORM_SELECTOR = False
    PLATFORM_OPTIONS: List[str] = []

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=_BG, corner_radius=0, **kwargs)
        self._all_items: List[dict] = []
        self._poster: Optional[AutoPoster] = None
        self._posting_thread: Optional[threading.Thread] = None
        self._slot_active_vars: List[ctk.BooleanVar] = []
        self._slot_time_vars: List[ctk.StringVar] = []
        self._slot_entry_widgets: List[ctk.CTkEntry] = []
        # Pagination
        self._page_size_var = ctk.StringVar(value="50")
        self._current_page: int = 0          # 0-indexed
        self._filtered_items: List[dict] = []
        # Page dropdown — list of {name, var, group_name, db_id}
        self._page_check_data: List[dict] = []
        self._setup_ui()

    # ═══════════════════════════════════════════════════════════════════════
    # MAIN LAYOUT
    # ═══════════════════════════════════════════════════════════════════════

    def _setup_ui(self):
        # ── Title ──
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.pack(fill="x", padx=16, pady=(10, 4))

        ctk.CTkLabel(
            title_frame, text=self.TAB_TITLE,
            font=ctk.CTkFont(size=18, weight="bold"), text_color=_TEXT,
        ).pack(side="left")

        ctk.CTkLabel(
            title_frame, text=self.TAB_SUBTITLE,
            font=ctk.CTkFont(size=12), text_color=_TEXT2,
        ).pack(side="left", padx=10, pady=(4, 0))

        # ── Three-column layout: Left (Library) | Mid (Scheduler) | Right (Actions) ──
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        main_container.columnconfigure(0, weight=3)
        main_container.columnconfigure(1, weight=2)
        main_container.columnconfigure(2, weight=0)
        main_container.rowconfigure(0, weight=1)

        # LEFT: Library
        left = ctk.CTkFrame(main_container, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        self._build_import_panel(left)
        self._build_search_bar(left)
        self._build_treeview(left)

        # MIDDLE: Scheduling settings panel
        mid = ctk.CTkFrame(main_container, fg_color=_CARD, corner_radius=12,
                           border_width=1, border_color=_BORDER)
        mid.grid(row=0, column=1, sticky="nsew", padx=(4, 4))

        self._build_scheduler_panel(mid)

        # RIGHT: Action buttons panel
        right = ctk.CTkFrame(main_container, fg_color=_CARD, corner_radius=12,
                             border_width=1, border_color=_BORDER, width=160)
        right.grid(row=0, column=2, sticky="nsew", padx=(0, 0))
        right.pack_propagate(False)

        self._build_action_panel(right)

        # ── Console Log ──
        log_card = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=10,
                                border_width=1, border_color=_BORDER)
        log_card.pack(fill="x", padx=16, pady=(0, 4))

        log_hdr = ctk.CTkFrame(log_card, fg_color="transparent")
        log_hdr.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(log_hdr, text="📋 Console Log",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=_TEXT2).pack(side="left")
        ctk.CTkButton(log_hdr, text="🗑 Xóa", width=52, height=20,
                      font=ctk.CTkFont(size=10), fg_color=_CARD2,
                      hover_color=_BORDER, text_color=_TEXT2, corner_radius=4,
                      command=self._clear_console).pack(side="right")

        from tkinter import Text, Scrollbar
        log_outer = ctk.CTkFrame(log_card, fg_color="transparent")
        log_outer.pack(fill="x", padx=6, pady=(0, 6))

        self._console = Text(
            log_outer, height=5, bg="#0B1220", fg="#94A3B8",
            font=("Consolas", 9), relief="flat", bd=0,
            wrap="word", state="disabled",
            selectbackground="#334155", insertbackground="#94A3B8",
        )
        _log_sb = Scrollbar(log_outer, orient="vertical",
                            command=self._console.yview)
        self._console.configure(yscrollcommand=_log_sb.set)
        _log_sb.pack(side="right", fill="y")
        self._console.pack(side="left", fill="x", expand=True)

        # Tag colors for different log levels
        self._console.tag_configure("INFO",  foreground="#94A3B8")
        self._console.tag_configure("OK",    foreground="#16A34A")
        self._console.tag_configure("WARN",  foreground="#F59E0B")
        self._console.tag_configure("ERROR", foreground="#DC2626")
        self._console.tag_configure("TIME",  foreground="#475569")

        # ── Status Bar ──
        bottom = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=10, height=38)
        bottom.pack(fill="x", padx=16, pady=(0, 8))
        bottom.pack_propagate(False)

        self._status_label = ctk.CTkLabel(
            bottom, text="Sẵn sàng", font=ctk.CTkFont(size=11),
            text_color=_TEXT2,
        )
        self._status_label.pack(side="left", padx=12)

        self._progress = ctk.CTkProgressBar(
            bottom, height=7, corner_radius=4,
            fg_color=_CARD2, progress_color=_ACCENT,
        )
        self._progress.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=12)
        self._progress.set(0)

        # Load data
        self._refresh_treeview()

    # ═══════════════════════════════════════════════════════════════════════
    # LEFT PANEL: Import Controls
    # ═══════════════════════════════════════════════════════════════════════

    def _build_import_panel(self, parent):
        card = ctk.CTkFrame(parent, fg_color=_CARD, corner_radius=10,
                            border_width=1, border_color=_BORDER)
        card.pack(fill="x", pady=(0, 4))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=8)

        # Row 1: Single folder picker (contains subfolders + Excel)
        r1 = ctk.CTkFrame(inner, fg_color="transparent")
        r1.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(r1, text="📂", font=ctk.CTkFont(size=12), text_color=_TEXT2).pack(side="left")

        ctk.CTkLabel(
            r1, text="Content Folder:",
            font=ctk.CTkFont(size=10, weight="bold"), text_color=_TEXT2,
        ).pack(side="left", padx=(2, 4))

        self._folder_var = ctk.StringVar()
        ctk.CTkEntry(
            r1, textvariable=self._folder_var, height=28,
            font=ctk.CTkFont(size=10), fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, corner_radius=5, state="disabled",
        ).pack(side="left", fill="x", expand=True, padx=4)

        ctk.CTkButton(
            r1, text="Chọn", width=55, height=28,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=_ACCENT, hover_color="#2563EB",
            corner_radius=5, command=self._pick_folder,
        ).pack(side="left")

        # Row 2: Buttons
        r2 = ctk.CTkFrame(inner, fg_color="transparent")
        r2.pack(fill="x")

        self._import_btn = ctk.CTkButton(
            r2, text="🚀 Import", height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=_GREEN, hover_color="#15803D", corner_radius=8,
            command=self._on_import,
        )
        self._import_btn.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            r2, text="📂", width=32, height=32,
            font=ctk.CTkFont(size=12), fg_color=_CARD2, hover_color="#475569",
            corner_radius=8, text_color=_TEXT, command=self._on_open_content_folder,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            r2, text="☑ All", width=52, height=32,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=_CARD2, hover_color="#475569", corner_radius=8,
            text_color=_TEXT, command=self._on_select_all,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            r2, text="🗑 Xóa", width=60, height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=_RED, hover_color="#B91C1C", corner_radius=8,
            text_color="#FFF", command=self._on_delete_selected,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            r2, text="➕ Folder", width=72, height=32,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=_CARD2, hover_color="#475569", corner_radius=8,
            text_color=_TEXT, command=self._on_add_folders,
        ).pack(side="left")

        self._stats_label = ctk.CTkLabel(
            r2, text="", font=ctk.CTkFont(size=11), text_color=_TEXT2,
        )
        self._stats_label.pack(side="right")

    # ═══════════════════════════════════════════════════════════════════════
    # LEFT PANEL: Search Bar
    # ═══════════════════════════════════════════════════════════════════════

    def _build_search_bar(self, parent):
        card = ctk.CTkFrame(parent, fg_color=_CARD, corner_radius=8,
                            border_width=1, border_color=_BORDER)
        card.pack(fill="x", pady=(0, 4))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=6)

        ctk.CTkLabel(inner, text="🔍", font=ctk.CTkFont(size=12), text_color=_TEXT2).pack(side="left")

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", self._on_search_changed)

        ctk.CTkEntry(
            inner, textvariable=self._search_var, height=28,
            font=ctk.CTkFont(size=11), fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, corner_radius=5,
            placeholder_text="Tìm folder hoặc caption...",
            placeholder_text_color="#64748B",
        ).pack(side="left", padx=6, fill="x", expand=True)

        ctk.CTkButton(
            inner, text="✕", width=28, height=28,
            font=ctk.CTkFont(size=11), fg_color=_CARD2, hover_color="#475569",
            corner_radius=5, text_color=_TEXT2,
            command=lambda: self._search_var.set(""),
        ).pack(side="left")

    # ═══════════════════════════════════════════════════════════════════════
    # LEFT PANEL: Treeview
    # ═══════════════════════════════════════════════════════════════════════

    def _build_treeview(self, parent):
        card = ctk.CTkFrame(parent, fg_color=_CARD, corner_radius=10,
                            border_width=1, border_color=_BORDER)
        card.pack(fill="both", expand=True, pady=(0, 0))

        # Dark mode style
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.Treeview",
            background="#1E293B", foreground="#F1F5F9",
            fieldbackground="#1E293B", borderwidth=0,
            font=("Consolas", 10), rowheight=26,
        )
        style.configure("Dark.Treeview.Heading",
            background="#334155", foreground="#F1F5F9",
            font=("Arial", 10, "bold"), borderwidth=0,
        )
        style.map("Dark.Treeview",
            background=[("selected", "#3B82F6")],
            foreground=[("selected", "#FFFFFF")],
        )
        style.map("Dark.Treeview.Heading",
            background=[("active", "#475569")],
        )

        columns = ("id", "folder", "caption", "media", "status")
        tree_frame = ctk.CTkFrame(card, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=8, pady=8)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        self._tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            style="Dark.Treeview", selectmode="extended",
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=self._tree.yview)

        self._tree.heading("id", text="#")
        self._tree.heading("folder", text="📁 Folder")
        self._tree.heading("caption", text="📝 Caption")
        self._tree.heading("media", text="🖼 Media")
        self._tree.heading("status", text="📊 Status")

        self._tree.column("id", width=35, minwidth=30, anchor="center")
        self._tree.column("folder", width=140, minwidth=80)
        self._tree.column("caption", width=200, minwidth=100)
        self._tree.column("media", width=90, minwidth=60, anchor="center")
        self._tree.column("status", width=150, minwidth=80)

        self._tree.pack(fill="both", expand=True)
        self._tree.tag_configure("odd", background="#1E293B")
        self._tree.tag_configure("even", background="#243044")
        self._tree.bind("<Double-1>", self._on_tree_double_click)

        # ── Pagination bar ──
        pg_bar = ctk.CTkFrame(card, fg_color="transparent")
        pg_bar.pack(fill="x", padx=8, pady=(2, 6))

        self._pg_prev_btn = ctk.CTkButton(
            pg_bar, text="◀", width=28, height=24,
            font=ctk.CTkFont(size=11), fg_color=_CARD2, hover_color=_BORDER,
            text_color=_TEXT, corner_radius=5, command=self._pg_prev,
        )
        self._pg_prev_btn.pack(side="left")

        self._pg_label = ctk.CTkLabel(
            pg_bar, text="1 / 1", width=60,
            font=ctk.CTkFont(size=10), text_color=_TEXT2,
        )
        self._pg_label.pack(side="left", padx=4)

        self._pg_next_btn = ctk.CTkButton(
            pg_bar, text="▶", width=28, height=24,
            font=ctk.CTkFont(size=11), fg_color=_CARD2, hover_color=_BORDER,
            text_color=_TEXT, corner_radius=5, command=self._pg_next,
        )
        self._pg_next_btn.pack(side="left")

        # Rows-per-page selector
        ctk.CTkLabel(
            pg_bar, text="Dòng/trang:", font=ctk.CTkFont(size=10), text_color=_TEXT2,
        ).pack(side="left", padx=(12, 2))

        ctk.CTkOptionMenu(
            pg_bar, variable=self._page_size_var,
            values=["20", "50", "100", "200", "Tất cả"],
            width=80, height=24, font=ctk.CTkFont(size=10),
            fg_color=_CARD2, button_color=_BORDER, button_hover_color="#475569",
            text_color=_TEXT, dropdown_fg_color=_CARD2, dropdown_text_color=_TEXT,
            command=self._on_page_size_changed,
        ).pack(side="left")

    # ═══════════════════════════════════════════════════════════════════════
    # RIGHT PANEL: Scheduling Engine
    # ═══════════════════════════════════════════════════════════════════════

    def _build_scheduler_panel(self, parent):
        # Scrollable inner
        inner = ctk.CTkScrollableFrame(parent, fg_color="transparent", scrollbar_button_color=_CARD2)
        inner.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # ── Account ──
        self._section_label(inner, "👤 Account")
        self._account_combo = ctk.CTkComboBox(
            inner, height=32,
            font=ctk.CTkFont(size=11),
            fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, button_color=_ACCENT,
            dropdown_fg_color=_CARD2, dropdown_text_color=_TEXT,
            dropdown_hover_color=_ACCENT,
            corner_radius=6, state="readonly",
            command=self._on_account_changed,
        )
        self._account_combo.pack(fill="x", pady=(0, 8))

        # ── Target Pages (multi-select, filtered by account) ──
        pages_hdr = ctk.CTkFrame(inner, fg_color="transparent")
        pages_hdr.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(
            pages_hdr, text="📄 Fanpages quản lý",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=_TEXT2,
        ).pack(side="left")
        ctk.CTkButton(
            pages_hdr, text="🔄", height=22, width=30,
            font=ctk.CTkFont(size=11),
            fg_color=_CARD2, hover_color="#475569", corner_radius=5,
            text_color=_TEXT2, border_width=1, border_color=_BORDER,
            command=self._reload_page_listbox,
        ).pack(side="right")

        # Dropdown button — shows selected count, opens checkbox popup
        self._page_dropdown_btn = ctk.CTkButton(
            inner, text="── Chưa có fanpage ──", height=32,
            font=ctk.CTkFont(size=10), fg_color=_CARD2, hover_color="#475569",
            corner_radius=6, text_color=_TEXT2, border_width=1, border_color=_BORDER,
            anchor="w", command=self._open_page_dropdown,
        )
        self._page_dropdown_btn.pack(fill="x", pady=(0, 8))

        self._load_accounts_and_pages()
        # ── Platform selection (checkboxes) ──
        self._platform_vars = {}
        platforms = self.PLATFORM_OPTIONS if self.SHOW_PLATFORM_SELECTOR else []
        platform_frame = ctk.CTkFrame(inner, fg_color=_CARD2, corner_radius=6)
        platform_frame.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(platform_frame, text="📱 Nền tảng", font=ctk.CTkFont(size=11, weight="bold"), text_color=_TEXT2).pack(side="left", padx=4)
        for name in platforms:
            var = ctk.BooleanVar(value=False)
            self._platform_vars[name] = var
            ctk.CTkCheckBox(platform_frame, text=name, variable=var, fg_color=_CARD2, text_color=_TEXT2).pack(side="left", padx=2)
        if not self.SHOW_PLATFORM_SELECTOR:
            platform_frame.pack_forget()

        # ── Start / End Date (range picker) ──
        self._section_label(inner, "📆 Schedule Range")

        # Row: [Start entry]  [arrow]  [End entry]  [📅 button]
        date_row = ctk.CTkFrame(inner, fg_color="transparent")
        date_row.pack(fill="x", pady=(0, 8))
        date_row.columnconfigure(0, weight=1)
        date_row.columnconfigure(2, weight=1)

        # Start (no label)
        self._date_var = ctk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        ctk.CTkEntry(
            date_row, textvariable=self._date_var, height=30,
            font=ctk.CTkFont(size=11), fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, corner_radius=5, placeholder_text="YYYY-MM-DD",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 2))

        # Arrow separator
        ctk.CTkLabel(
            date_row, text="→", font=ctk.CTkFont(size=13), text_color=_TEXT2,
        ).grid(row=0, column=1, padx=2)

        # End (no label)
        self._end_date_var = ctk.StringVar(value="")
        ctk.CTkEntry(
            date_row, textvariable=self._end_date_var, height=30,
            font=ctk.CTkFont(size=11), fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, corner_radius=5, placeholder_text="YYYY-MM-DD",
        ).grid(row=0, column=2, sticky="ew", padx=(2, 2))

        # Calendar picker button
        ctk.CTkButton(
            date_row, text="📅", width=32, height=30,
            font=ctk.CTkFont(size=13), fg_color=_ACCENT, hover_color="#2563EB",
            corner_radius=6, text_color="#FFF",
            command=self._show_range_picker,
        ).grid(row=0, column=3, padx=(4, 0))

        # ── Time Slots ──
        slots_header = ctk.CTkFrame(inner, fg_color="transparent")
        slots_header.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(
            slots_header, text="⏰ Time Slots",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=_TEXT2,
        ).pack(side="left")
        ctk.CTkLabel(
            slots_header, text="(posts/day = active slots)",
            font=ctk.CTkFont(size=9), text_color="#64748B",
        ).pack(side="left", padx=(6, 0), pady=(2, 0))
        ctk.CTkButton(
            slots_header, text="+", width=24, height=22,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=_ACCENT, hover_color="#2563EB", corner_radius=6,
            command=self._add_time_slot,
        ).pack(side="right")

        self._slots_frame = ctk.CTkFrame(inner, fg_color="transparent")
        self._slots_frame.pack(fill="x", pady=(0, 8))
        self._slots_frame.columnconfigure(0, weight=1)
        self._slots_frame.columnconfigure(1, weight=1)

        # 2 default slots, all inactive
        for default_t in ["08:00", "20:00"]:
            self._add_time_slot(default_t, active=False)

        # ── CTA Toggle ──
        self._cta_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(
            inner, text="💬 Add Send Message Button",
            font=ctk.CTkFont(size=11), text_color=_TEXT2,
            variable=self._cta_var, onvalue=True, offvalue=False,
            fg_color=_CARD2, progress_color=_GREEN,
            button_color=_TEXT, button_hover_color="#CBD5E1",
        ).pack(anchor="w", pady=(4, 4))

        # ── Share to Story Toggle ──
        self._share_story_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            inner, text="📢 Chia sẻ lên Tin (Story)",
            font=ctk.CTkFont(size=11), text_color=_TEXT2,
            variable=self._share_story_var, onvalue=True, offvalue=False,
            fg_color=_CARD2, progress_color=_GREEN,
            button_color=_TEXT, button_hover_color="#CBD5E1",
        ).pack(anchor="w", pady=(0, 8))

        # ── Brand Name ──
        self._section_label(inner, "🏷 Brand Name (EXIF)")
        self._brand_var = ctk.StringVar(value="")
        ctk.CTkEntry(
            inner, textvariable=self._brand_var, height=30,
            font=ctk.CTkFont(size=11),
            fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, corner_radius=6,
            placeholder_text="Tên fanpage cho metadata...",
            placeholder_text_color="#64748B",
        ).pack(fill="x", pady=(0, 8))

        self._headless_var = ctk.BooleanVar(value=False)  # always visible browser

        # ── Separator ──
        ctk.CTkFrame(inner, fg_color=_BORDER, height=1).pack(fill="x", pady=(0, 8))

        self._scheduling_mode_var = ctk.StringVar(value="FB")

    def _build_action_panel(self, parent):
        """Right-most panel: action buttons stacked vertically."""
        pad = {"padx": 10, "pady": (4, 0), "fill": "x"}

        ctk.CTkFrame(parent, fg_color="transparent", height=10).pack()

        self._post_now_btn = ctk.CTkButton(
            parent, text="⚡ ĐĂNG NGAY", height=38,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#EA580C", hover_color="#C2410C", corner_radius=10,
            command=self._on_post_now,
        )
        self._post_now_btn.pack(**pad)

        ctk.CTkFrame(parent, fg_color=_BORDER, height=1).pack(fill="x", padx=10, pady=(10, 6))

        ctk.CTkButton(
            parent, text="📅 XEM LỊCH", height=32,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=_YELLOW, hover_color="#D97706", corner_radius=8,
            text_color="#000",
            command=self._open_calendar_dialog,
        ).pack(**pad)

        ctk.CTkButton(
            parent, text="📋 PLANNING", height=36,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=_PURPLE, hover_color="#6D28D9", corner_radius=10,
            command=self._on_generate_schedule,
        ).pack(**pad)

        self._execute_btn = ctk.CTkButton(
            parent, text="▶ EXECUTE PLAN", height=38,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#059669", hover_color="#047857", corner_radius=10,
            command=self._on_execute,
        )
        self._execute_btn.pack(**pad)

        self._stop_btn = ctk.CTkButton(
            parent, text="⏹ STOP", height=34,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=_RED, hover_color="#B91C1C", corner_radius=8,
            state="disabled",
            command=self._on_stop_execute,
        )
        self._stop_btn.pack(**pad)

    def _section_label(self, parent, text: str):
        ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(size=11, weight="bold"), text_color=_TEXT2,
        ).pack(anchor="w", pady=(4, 2))

    # ═══════════════════════════════════════════════════════════════════════
    # LIBRARY ACTIONS (same as Phase 1)
    # ═══════════════════════════════════════════════════════════════════════

    def _pick_folder(self):
        folder = filedialog.askdirectory(title="Chọn Content Folder (chứa subfolders + Excel)")
        if folder:
            self._folder_var.set(os.path.normpath(os.path.abspath(folder)))

    def _find_excel_in_folder(self, folder: str) -> str:
        """Auto-detect first .xlsx/.xls file in folder."""
        for f in sorted(os.listdir(folder)):
            if f.lower().endswith((".xlsx", ".xls")) and not f.startswith("~"):
                return os.path.join(folder, f)
        return ""

    def _on_import(self):
        main_folder = self._folder_var.get().strip()
        if not main_folder or not os.path.isdir(main_folder):
            messagebox.showwarning("Tinix", "Vui lòng chọn Content Folder hợp lệ!")
            return

        # Auto-detect Excel in folder
        excel_path = self._find_excel_in_folder(main_folder)
        if excel_path:
            logger.info(f"📄 Auto-detected Excel: {os.path.basename(excel_path)}")
        else:
            logger.warning("⚠ Không tìm thấy file Excel trong folder")

        self._import_btn.configure(state="disabled", text="⏳ Importing...")
        self._progress.set(0)
        self._set_status("Đang quét thư mục...", _YELLOW)

        threading.Thread(
            target=self._import_thread,
            args=(main_folder, excel_path),
            daemon=True,
        ).start()

    def _on_download_template(self):
        """Generate and save a sample Excel template."""
        filepath = filedialog.asksaveasfilename(
            title="Lưu Excel Template",
            defaultextension=".xlsx",
            initialfile="Social_Post_Template.xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not filepath:
            return

        try:
            import pandas as pd
            df = pd.DataFrame({
                "Folder_Name": [
                    "Bo_anh_so_sinh_01",
                    "Chup_ky_yeu_02",
                    "Album_cuoi_03",
                ],
                "Caption": [
                    "Chào mừng thiên thần nhỏ đến với studio! 👶✨ Liên hệ đặt lịch ngay.",
                    "Kỷ yếu lớp 12A1 - Những khoảnh khắc đáng nhớ 📸🎓",
                    "Trọn gói album cưới ngoại cảnh. Inbox để nhận báo giá 💍",
                ],
            })

            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Template")
                ws = writer.sheets["Template"]
                ws.column_dimensions["A"].width = 30
                ws.column_dimensions["B"].width = 70

            messagebox.showinfo(
                "Tinix",
                "✅ Template saved!\n\n"
                "Điền Folder_Name (khớp tên subfolder) và Caption,\n"
                "rồi dùng nút Import để nạp nội dung.",
            )
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể tạo template:\n{str(e)[:200]}")

    def _import_thread(self, main_folder: str, excel_path: str):
        try:
            def on_progress(current, total, folder_name):
                if total > 0:
                    self.after(0, self._progress.set, current / total)
                    self.after(0, self._set_status,
                              f"[{current}/{total}] {folder_name}", _ACCENT)

            items = scan_main_folder(main_folder, excel_path, on_progress)
            if not items:
                self.after(0, self._import_done, 0, "Không tìm thấy folder nào!")
                return

            db_path = get_db_path(config.get("scraper_db_path", ""))
            saved = save_content_pool(db_path, items)
            self.after(0, self._progress.set, 1.0)
            self.after(0, self._import_done, saved,
                       f"✅ Imported {saved} folders")
        except Exception as e:
            self.after(0, self._import_done, 0, f"❌ {str(e)[:200]}")

    def _import_done(self, count: int, message: str):
        self._import_btn.configure(state="normal", text="🚀 Import")
        self._set_status(message, _GREEN if count > 0 else _RED)
        if count > 0:
            self._refresh_treeview()
        else:
            self._progress.set(0)

    def _on_delete_selected(self):
        selected = self._tree.selection()
        if not selected:
            messagebox.showinfo("Tinix", "Chọn ít nhất 1 mục!")
            return

        ids = self._get_selected_content_ids()
        if not ids:
            return

        if not messagebox.askyesno("Xác nhận", f"Xóa {len(ids)} mục?"):
            return

        db_path = get_db_path(config.get("scraper_db_path", ""))
        deleted = delete_content_pool(db_path, ids)
        self._set_status(f"Đã xóa {deleted} mục", _GREEN)
        self._refresh_treeview()

    def _on_open_content_folder(self):
        """Open the selected content folder in Windows Explorer."""
        import subprocess
        path = self._folder_var.get().strip()
        if path and os.path.isdir(path):
            subprocess.Popen(["explorer", os.path.normpath(path)])
        else:
            messagebox.showwarning("Tinix", "Chưa chọn Content Folder!")

    def _on_add_folders(self):
        """Dialog: create N empty subfolders inside the content folder, auto-named."""
        main_folder = self._folder_var.get().strip()
        if not main_folder or not os.path.isdir(main_folder):
            messagebox.showwarning("Tinix", "Chọn Content Folder trước!")
            return

        # Detect last folder name and its prefix/number pattern
        import re
        existing = sorted([
            d for d in os.listdir(main_folder)
            if os.path.isdir(os.path.join(main_folder, d))
        ])

        last_num = 0
        prefix = "Folder_"
        if existing:
            last = existing[-1]
            m = re.match(r'^(.*?)(\d+)$', last)
            if m:
                prefix = m.group(1)
                last_num = int(m.group(2))
                zero_pad = len(m.group(2))
            else:
                prefix = last + "_"
                zero_pad = 4
        else:
            zero_pad = 4

        # Dialog
        dlg = ctk.CTkToplevel(self)
        dlg.title("Tạo thư mục trống")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(fg_color=_CARD)
        dlg.update_idletasks()
        w, h = 360, 200
        px = self.winfo_rootx() + self.winfo_width() // 2 - w // 2
        py = self.winfo_rooty() + self.winfo_height() // 2 - h // 2
        dlg.geometry(f"{w}x{h}+{px}+{py}")

        next_name = f"{prefix}{str(last_num + 1).zfill(zero_pad)}"
        ctk.CTkLabel(
            dlg, text=f"Thư mục tiếp theo: {next_name}",
            font=ctk.CTkFont(size=11), text_color=_TEXT2,
        ).pack(anchor="w", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            dlg, text="Số lượng thư mục cần tạo:",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=_TEXT,
        ).pack(anchor="w", padx=16)

        count_var = ctk.StringVar(value="1")
        ctk.CTkEntry(
            dlg, textvariable=count_var, height=32, width=100,
            font=ctk.CTkFont(size=13), fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, justify="center",
        ).pack(padx=16, pady=6)

        status_lbl = ctk.CTkLabel(dlg, text="", font=ctk.CTkFont(size=10), text_color=_TEXT2)
        status_lbl.pack()

        def _create():
            try:
                n = int(count_var.get())
                if n < 1 or n > 999:
                    raise ValueError
            except ValueError:
                status_lbl.configure(text="⚠ Nhập số từ 1–999", text_color=_YELLOW)
                return

            created = []
            num = last_num
            for _ in range(n):
                num += 1
                name = f"{prefix}{str(num).zfill(zero_pad)}"
                path = os.path.join(main_folder, name)
                try:
                    os.makedirs(path, exist_ok=True)
                    created.append(name)
                except Exception as e:
                    status_lbl.configure(
                        text=f"❌ Lỗi tạo {name}: {str(e)[:60]}", text_color=_RED)
                    return

            self._set_status(f"✅ Đã tạo {len(created)} thư mục", _GREEN)
            dlg.destroy()

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(
            btn_row, text="✓ Tạo", width=90, height=32,
            fg_color=_ACCENT, hover_color="#2563EB",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#FFF",
            command=_create,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            btn_row, text="Hủy", width=70, height=32,
            fg_color=_CARD2, hover_color=_BORDER, text_color=_TEXT,
            command=dlg.destroy,
        ).pack(side="right")

    # ═══════════════════════════════════════════════════════════════════════
    # SCHEDULING
    # ═══════════════════════════════════════════════════════════════════════

    def _load_accounts_and_pages(self):
        """Populate account combo and page listbox."""
        db_path = get_db_path(config.get("scraper_db_path", ""))
        accounts = get_all_accounts(db_path)

        acct_options = []
        self._accounts_data: List[dict] = accounts
        for a in accounts:
            label = a.get("label") or a.get("username", "")
            if label:
                acct_options.append(label)

        if acct_options:
            self._account_combo.configure(values=acct_options)
            self._account_combo.set(acct_options[0])
        else:
            self._account_combo.configure(values=["(Chưa có account)"])
            self._account_combo.set("(Chưa có account)")

        self._reload_page_listbox()

    def _reload_page_listbox(self):
        """Refresh dropdown page list from managed_pages for the selected account."""
        db_path = get_db_path(config.get("scraper_db_path", ""))
        account_id = self._get_selected_account_id()

        self._page_check_data.clear()

        if account_id is not None:
            pages = get_managed_pages(db_path, account_id)
            for p in pages:
                self._page_check_data.append({
                    "name": p["page_name"],
                    "var": ctk.BooleanVar(value=False),
                    "group_name": p.get("group_name", ""),
                    "db_id": p["id"],
                    "page_id": p.get("page_id", ""),
                })

        self._update_page_dropdown_label()

    def _update_page_dropdown_label(self):
        """Update the dropdown button text to reflect current selection."""
        total = len(self._page_check_data)
        if total == 0:
            self._page_dropdown_btn.configure(
                text="── Nhấn 'Quét fanpage' để tải ──", text_color=_TEXT2)
            return
        checked = sum(1 for d in self._page_check_data if d["var"].get())
        if checked == 0:
            label = f"Chọn fanpage... ({total} trang)"
        elif checked == total:
            label = f"✓ Tất cả ({total} trang)"
        else:
            label = f"✓ {checked}/{total} trang được chọn"
        self._page_dropdown_btn.configure(text=label, text_color=_TEXT)

    def _open_page_dropdown(self):
        """Open a borderless dropdown popup with checkboxes and group filters."""
        import tkinter as tk

        total = len(self._page_check_data)
        if total == 0:
            messagebox.showinfo("Tinix", "Chưa có fanpage.\nNhấn 'Quét fanpage' để tải danh sách.")
            return

        # Destroy existing popup if any
        if hasattr(self, "_page_popup") and self._page_popup and self._page_popup.winfo_exists():
            self._page_popup.destroy()
            return

        # Collect distinct groups
        db_path = get_db_path(config.get("scraper_db_path", ""))
        account_id = self._get_selected_account_id()
        groups = get_managed_page_groups(db_path, account_id) if account_id is not None else []

        btn = self._page_dropdown_btn
        btn.update_idletasks()
        bx = btn.winfo_rootx()
        by = btn.winfo_rooty() + btn.winfo_height() + 2
        bw = btn.winfo_width()
        popup_w = max(bw, 280)
        # Height: header + group bar (if groups) + pages list
        group_bar_h = 34 if groups else 0
        row_h = 30
        list_h = min(row_h * total, 300)
        popup_h = 54 + group_bar_h + list_h  # header + group bar + list

        popup = tk.Toplevel(self)
        self._page_popup = popup
        popup.overrideredirect(True)
        popup.geometry(f"{popup_w}x{popup_h}+{bx}+{by}")
        popup.configure(bg=_CARD2)
        popup.lift()
        popup.focus_set()

        def _on_check():
            all_var.set(all(d["var"].get() for d in self._page_check_data))
            self._update_page_dropdown_label()

        # ── Header: "Tất cả" checkbox ──
        hdr_frame = tk.Frame(popup, bg=_CARD2)
        hdr_frame.pack(fill="x", padx=6, pady=(6, 2))

        all_var = ctk.BooleanVar(value=all(d["var"].get() for d in self._page_check_data))

        def _toggle_all():
            val = all_var.get()
            for d in self._page_check_data:
                d["var"].set(val)
            self._update_page_dropdown_label()

        ctk.CTkCheckBox(
            hdr_frame, text="✓ Tất cả", variable=all_var,
            font=ctk.CTkFont(size=11, weight="bold"), text_color=_TEXT,
            fg_color=_ACCENT, hover_color="#2563EB", bg_color=_CARD2,
            command=_toggle_all,
        ).pack(side="left")

        # ── Group filter bar (only when groups exist) ──
        if groups:
            tk.Frame(popup, bg=_BORDER, height=1).pack(fill="x", padx=6, pady=(2, 0))

            grp_frame = tk.Frame(popup, bg="#1E293B")
            grp_frame.pack(fill="x", padx=0)

            grp_lbl = tk.Label(grp_frame, text="Nhóm:", bg="#1E293B", fg=_TEXT2,
                               font=("Segoe UI", 9))
            grp_lbl.pack(side="left", padx=(6, 4))

            def _select_group(gname):
                """Tick all pages whose group_name == gname (deselect others)."""
                for d in self._page_check_data:
                    d["var"].set(d["group_name"] == gname)
                all_var.set(all(d["var"].get() for d in self._page_check_data))
                self._update_page_dropdown_label()

            for g in groups:
                g_name = g  # capture
                tk.Button(
                    grp_frame, text=g_name, relief="flat",
                    bg=_CARD2, fg=_TEXT, activebackground=_ACCENT, activeforeground="#fff",
                    font=("Segoe UI", 9), padx=6, pady=2, cursor="hand2",
                    command=lambda n=g_name: _select_group(n),
                ).pack(side="left", padx=2, pady=4)

        tk.Frame(popup, bg=_BORDER, height=1).pack(fill="x", padx=6, pady=(2, 0))

        # ── Scrollable checkbox list ──
        canvas = tk.Canvas(popup, bg=_CARD2, highlightthickness=0)
        vsb = ttk.Scrollbar(popup, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=4, pady=(2, 4))

        inner = tk.Frame(canvas, bg=_CARD2)
        canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_win, width=canvas.winfo_width())

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_win, width=e.width))

        def _make_assign_group_menu(widget, entry_data):
            """Right-click context menu: assign group to this page."""
            menu = tk.Menu(popup, tearoff=0, bg=_CARD2, fg=_TEXT,
                           activebackground=_ACCENT, activeforeground="#fff",
                           font=("Segoe UI", 10))

            def _do_assign():
                dlg = ctk.CTkInputDialog(
                    title="Gán nhóm",
                    text=f"Nhóm cho '{entry_data['name']}':\n(để trống để xoá nhóm)",
                )
                val = dlg.get_input()
                if val is None:
                    return  # cancelled
                new_group = val.strip()
                db_p = get_db_path(config.get("scraper_db_path", ""))
                update_managed_page_group(db_p, [entry_data["db_id"]], new_group)
                entry_data["group_name"] = new_group
                # Refresh label on checkbox
                display = f"[{new_group}] {entry_data['name']}" if new_group else entry_data["name"]
                lbl_var.set(display)

            menu.add_command(
                label=f"Gán nhóm cho '{entry_data['name']}'",
                command=_do_assign,
            )
            if entry_data["group_name"]:
                menu.add_command(
                    label="Xoá nhóm",
                    command=lambda: (
                        update_managed_page_group(
                            get_db_path(config.get("scraper_db_path", "")),
                            [entry_data["db_id"]], ""),
                        entry_data.update({"group_name": ""}),
                        lbl_var.set(entry_data["name"]),
                    ),
                )

            def _show(event):
                try:
                    menu.tk_popup(event.x_root, event.y_root)
                finally:
                    menu.grab_release()

            widget.bind("<Button-3>", _show)
            return menu

        for entry in self._page_check_data:
            grp = entry["group_name"]
            lbl_var = tk.StringVar(value=f"[{grp}] {entry['name']}" if grp else entry["name"])

            row_frame = tk.Frame(inner, bg=_CARD2)
            row_frame.pack(fill="x", padx=2, pady=1)

            cb = ctk.CTkCheckBox(
                row_frame, textvariable=lbl_var, variable=entry["var"],
                font=ctk.CTkFont(size=11), text_color=_TEXT,
                fg_color=_ACCENT, hover_color="#2563EB", bg_color=_CARD2,
                command=_on_check,
            )
            cb.pack(anchor="w", padx=4, pady=1)

            # Store lbl_var on entry so right-click handler can update it
            entry["_lbl_var"] = lbl_var
            _make_assign_group_menu(row_frame, entry)
            _make_assign_group_menu(cb, entry)

        # Mousewheel scroll
        def _on_wheel(e):
            canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)

        # Close when clicking outside
        def _on_focus_out(e):
            if popup.winfo_exists():
                try:
                    wx, wy = popup.winfo_rootx(), popup.winfo_rooty()
                    ww, wh = popup.winfo_width(), popup.winfo_height()
                    mx, my = popup.winfo_pointerx(), popup.winfo_pointery()
                    if not (wx <= mx <= wx + ww and wy <= my <= wy + wh):
                        canvas.unbind_all("<MouseWheel>")
                        popup.destroy()
                except Exception:
                    pass

        popup.bind("<FocusOut>", _on_focus_out)

    def _get_selected_account_id(self) -> Optional[int]:
        """Return the DB id of the currently selected account, or None."""
        label = self._account_combo.get()
        if hasattr(self, "_accounts_data"):
            for a in self._accounts_data:
                if (a.get("label") or a.get("username", "")) == label:
                    return a["id"]
        return None

    def _on_account_changed(self, _choice: str):
        """Account selection changed — refresh page list."""
        self._reload_page_listbox()

    def _on_add_page_manual(self):
        """Dialog to manually add a page for the selected account."""
        account_id = self._get_selected_account_id()
        if account_id is None:
            messagebox.showwarning("Tinix", "Chọn account trước!")
            return

        dlg = ctk.CTkToplevel(self)
        dlg.title("Thêm fanpage thủ công")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(fg_color=_CARD)
        dlg.update_idletasks()
        px = self.winfo_rootx() + self.winfo_width() // 2 - 155
        py = self.winfo_rooty() + self.winfo_height() // 2 - 90
        dlg.geometry(f"310x210+{px}+{py}")

        ctk.CTkLabel(
            dlg, text="Tên fanpage:", font=ctk.CTkFont(size=11), text_color=_TEXT2,
        ).pack(anchor="w", padx=12, pady=(12, 2))
        name_var = ctk.StringVar()
        ctk.CTkEntry(
            dlg, textvariable=name_var, height=32,
            font=ctk.CTkFont(size=11), fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, corner_radius=6,
            placeholder_text="Tên hiển thị của fanpage...",
        ).pack(fill="x", padx=12)

        ctk.CTkLabel(
            dlg, text="URL hoặc username:", font=ctk.CTkFont(size=11), text_color=_TEXT2,
        ).pack(anchor="w", padx=12, pady=(8, 2))
        url_var = ctk.StringVar()
        ctk.CTkEntry(
            dlg, textvariable=url_var, height=32,
            font=ctk.CTkFont(size=11), fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, corner_radius=6,
            placeholder_text="https://facebook.com/... hoặc username",
        ).pack(fill="x", padx=12)

        def _save():
            name = name_var.get().strip()
            url  = url_var.get().strip()
            if not name:
                messagebox.showwarning("Tinix", "Nhập tên fanpage!")
                return

            # Normalise URL
            if url and not url.startswith("http"):
                url = f"https://www.facebook.com/{url.lstrip('/')}"
            elif not url:
                url = f"https://www.facebook.com/{name.replace(' ', '')}"

            import re
            slug_m = re.search(r"facebook\.com/([^/?#]+)", url)
            page_id = slug_m.group(1) if slug_m else name.lower().replace(" ", "_")

            db_path = get_db_path(config.get("scraper_db_path", ""))
            save_managed_pages(db_path, account_id, [{
                "page_name": name, "page_url": url, "page_id": page_id,
            }])
            self._reload_page_listbox()
            self._set_status(f"✅ Đã thêm: {name}", _GREEN)
            dlg.destroy()

        foot = ctk.CTkFrame(dlg, fg_color="transparent")
        foot.pack(fill="x", padx=12, pady=(10, 10))
        ctk.CTkButton(
            foot, text="Huỷ", height=30, fg_color=_CARD2, hover_color=_BORDER,
            corner_radius=8, text_color=_TEXT2, command=dlg.destroy,
        ).pack(side="left")
        ctk.CTkButton(
            foot, text="✓  Lưu", height=30,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=_GREEN, hover_color="#15803D", corner_radius=8,
            command=_save,
        ).pack(side="right")
        dlg.bind("<Return>", lambda e: _save())

    def _get_active_time_slots(self) -> List[str]:
        """Return sorted list of times for active slots only."""
        slots = []
        for active_var, time_var in zip(self._slot_active_vars, self._slot_time_vars):
            if not active_var.get():
                continue
            t = time_var.get().strip()
            if t and ":" in t:
                parts = t.split(":")
                try:
                    h, m = int(parts[0]), int(parts[1])
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        slots.append(f"{h:02d}:{m:02d}")
                except ValueError:
                    pass
        return sorted(slots)

    def _get_selected_pages(self) -> List[str]:
        """Return list of page names that are checked in the dropdown."""
        return [d["name"] for d in self._page_check_data if d["var"].get()]

    def _get_selected_page_data(self) -> List[dict]:
        """Return list of {name, page_id} dicts for checked pages."""
        return [
            {"name": d["name"], "page_id": d.get("page_id", "")}
            for d in self._page_check_data if d["var"].get()
        ]

    def _add_time_slot(self, default_t: str = "08:00", active: bool = False):
        """Add a new time slot cell to the 2-column grid in _slots_frame."""
        i = len(self._slot_active_vars)
        active_var = ctk.BooleanVar(value=active)
        time_var = ctk.StringVar(value=default_t)

        grid_row = i // 2
        grid_col = i % 2

        cell = ctk.CTkFrame(self._slots_frame, fg_color="transparent")
        cell.grid(row=grid_row, column=grid_col, sticky="ew",
                  padx=(0, 4) if grid_col == 0 else (4, 0), pady=2)

        chk = ctk.CTkCheckBox(
            cell, text="", variable=active_var,
            width=20, checkbox_width=15, checkbox_height=15,
            fg_color=_ACCENT, hover_color="#2563EB",
            border_color=_BORDER,
            command=lambda idx=i: self._on_slot_toggle(idx),
        )
        chk.pack(side="left", padx=(0, 2))

        entry = ctk.CTkEntry(
            cell, textvariable=time_var, width=62, height=26,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=_CARD2, text_color=_TEXT if active else "#64748B",
            border_color=_ACCENT if active else _BORDER,
            corner_radius=5, justify="center",
            placeholder_text="HH:MM",
        )
        entry.pack(side="left", padx=(2, 0))

        # Up/down arrows to adjust hour ±1
        arrows = ctk.CTkFrame(cell, fg_color="transparent")
        arrows.pack(side="left", padx=(2, 0))
        ctk.CTkButton(
            arrows, text="▲", width=20, height=12,
            font=ctk.CTkFont(size=8), fg_color=_CARD2, hover_color=_BORDER,
            text_color=_TEXT2, corner_radius=3,
            command=lambda idx=i: self._adjust_slot_hour(idx, +1),
        ).pack()
        ctk.CTkButton(
            arrows, text="▼", width=20, height=12,
            font=ctk.CTkFont(size=8), fg_color=_CARD2, hover_color=_BORDER,
            text_color=_TEXT2, corner_radius=3,
            command=lambda idx=i: self._adjust_slot_hour(idx, -1),
        ).pack()

        self._slot_active_vars.append(active_var)
        self._slot_time_vars.append(time_var)
        self._slot_entry_widgets.append(entry)

    def _adjust_slot_hour(self, idx: int, delta: int):
        """Increase or decrease the hour of a slot by delta (+1 or -1)."""
        if idx >= len(self._slot_time_vars):
            return
        time_var = self._slot_time_vars[idx]
        t = time_var.get().strip()
        try:
            h, m = map(int, t.split(":"))
        except Exception:
            h, m = 8, 0
        h = (h + delta) % 24
        time_var.set(f"{h:02d}:{m:02d}")

    def _on_slot_toggle(self, idx: int):
        """Update entry styling when a slot is toggled active/inactive."""
        if idx >= len(self._slot_entry_widgets):
            return
        active = self._slot_active_vars[idx].get()
        entry = self._slot_entry_widgets[idx]
        entry.configure(
            text_color=_TEXT if active else "#64748B",
            border_color=_ACCENT if active else _BORDER,
        )

    def _on_select_all(self):
        """Select all rows in the content treeview."""
        children = self._tree.get_children()
        if children:
            self._tree.selection_set(children)

    def _on_generate_schedule(self):
        """Generate schedule from selected content + params, show preview."""
        # Get selected content IDs
        content_ids = self._get_selected_content_ids()
        if not content_ids:
            messagebox.showwarning("Tinix", "Chọn ít nhất 1 nội dung từ Library!")
            return

        # Get selected pages
        page_names = self._get_selected_pages()
        if not page_names:
            messagebox.showwarning("Tinix", "Chọn ít nhất 1 Target Page!")
            return

        # Get account
        acct_label = self._account_combo.get()
        account_id = ""
        if hasattr(self, "_accounts_data"):
            for a in self._accounts_data:
                lbl = a.get("label") or a.get("username", "")
                if lbl == acct_label:
                    account_id = str(a.get("id", ""))
                    break

        # Parse start date
        try:
            start_date = datetime.strptime(self._date_var.get().strip(), "%Y-%m-%d")
        except ValueError:
            messagebox.showwarning("Tinix", "Start Date không hợp lệ! (YYYY-MM-DD)")
            return

        # Parse optional end date
        end_date = None
        end_raw = self._end_date_var.get().strip()
        if end_raw:
            try:
                end_date = datetime.strptime(end_raw, "%Y-%m-%d")
                if end_date < start_date:
                    messagebox.showwarning("Tinix", "End Date phải sau Start Date!")
                    return
            except ValueError:
                messagebox.showwarning("Tinix", "End Date không hợp lệ! (YYYY-MM-DD)")
                return

        # Get active time slots (posts per day = active slot count)
        time_slots = self._get_active_time_slots()
        if not time_slots:
            messagebox.showwarning("Tinix", "Cần ít nhất 1 time slot active!")
            return

        cta_enabled = self._cta_var.get()
        posts_per_day = len(time_slots)

        # Build content_id → folder_name map
        cid_to_name = {item["content_id"]: item["folder_name"] for item in self._all_items}

        db_path = get_db_path(config.get("scraper_db_path", ""))
        records = []

        # Generate schedule for each selected page independently
        for page_name in page_names:
            day_offset = 0
            slot_idx = 0
            day_count = 0

            for cid in content_ids:
                current_date = start_date + timedelta(days=day_offset)

                # Stop if beyond end_date
                if end_date and current_date > end_date:
                    break

                current_time = time_slots[slot_idx % posts_per_day]
                scheduled = f"{current_date.strftime('%Y-%m-%d')} {current_time}"

                if check_duplicate_schedule(db_path, cid, page_name, scheduled):
                    logger.info(f"⚠ Duplicate skipped: {cid_to_name.get(cid, cid)} @ {page_name} @ {scheduled}")
                else:
                    mode = self._scheduling_mode_var.get()
                    scheduling_method = "Web" if mode == "Lên lịch Web" else "App"
                    # Gather selected platforms as JSON array
                    selected_platforms = [name for name, var in self._platform_vars.items() if var.get()]
                    records.append({
                        "content_id": cid,
                        "account_id": account_id,
                        "page_name": page_name,
                        "scheduled_time": scheduled,
                        "folder_name": cid_to_name.get(cid, f"ID_{cid}"),
                        "cta": cta_enabled,
                        "status": "Pending",
                        "scheduling_method": scheduling_method,
                        "platforms": json.dumps(selected_platforms),
                    })

                # Advance slot / day
                slot_idx += 1
                day_count += 1
                if day_count >= posts_per_day:
                    day_offset += 1
                    slot_idx = 0
                    day_count = 0

        if not records:
            messagebox.showinfo("Tinix", "Tất cả đã được lên lịch rồi (duplicates)!")
            return

        # Show preview
        SchedulePreviewDialog(
            self.winfo_toplevel(),
            records,
            on_confirm=self._confirm_schedule,
        )

    def _confirm_schedule(self, records: List[dict]):
        """Called when user confirms the schedule preview."""
        db_path = get_db_path(config.get("scraper_db_path", ""))

        # Run in background thread for UI responsiveness
        def do_insert():
            inserted = bulk_insert_schedule(db_path, records)
            self.after(0, self._schedule_done, inserted)

        threading.Thread(target=do_insert, daemon=True).start()
        self._set_status("Đang lưu lịch...", _YELLOW)

    def _schedule_done(self, count: int):
        self._set_status(f"✅ Đã lên lịch {count} bài viết", _GREEN)
        self._refresh_treeview()

    def _on_schedule_now(self):
        """
        Schedule selected content directly on Facebook via browser.
        Generates time slots from current UI params, then calls post_content()
        for each item — opening the composer, filling schedule date/time, and
        clicking 'Lên lịch'. No need for Generate → Execute two-step flow.
        """
        content_ids = self._get_selected_content_ids()
        if not content_ids:
            messagebox.showwarning("Tinix", "Chọn ít nhất 1 nội dung từ Library!")
            return

        page_data = self._get_selected_page_data()
        if not page_data:
            messagebox.showwarning("Tinix", "Chọn ít nhất 1 Target Page!")
            return

        # Parse start date
        try:
            start_date = datetime.strptime(self._date_var.get().strip(), "%Y-%m-%d")
        except ValueError:
            messagebox.showwarning("Tinix", "Start Date không hợp lệ! (YYYY-MM-DD)")
            return

        # Parse optional end date
        end_date = None
        end_raw = self._end_date_var.get().strip()
        if end_raw:
            try:
                end_date = datetime.strptime(end_raw, "%Y-%m-%d")
                if end_date < start_date:
                    messagebox.showwarning("Tinix", "End Date phải sau Start Date!")
                    return
            except ValueError:
                messagebox.showwarning("Tinix", "End Date không hợp lệ! (YYYY-MM-DD)")
                return

        time_slots = self._get_active_time_slots()
        if not time_slots:
            messagebox.showwarning("Tinix", "Cần ít nhất 1 time slot active!")
            return

        posts_per_day = len(time_slots)
        cta_enabled = self._cta_var.get()
        share_to_story = self._share_story_var.get()
        brand_name = self._brand_var.get().strip()

        # Build flat list of (content_item, page, scheduled_time) tuples
        db_path = get_db_path(config.get("scraper_db_path", ""))
        all_items_map = {i["content_id"]: i for i in self._all_items}

        jobs = []  # list of dicts: folder_path, caption, page_name, page_id, scheduled_time
        for pg in page_data:
            day_offset = 0
            slot_idx = 0
            day_count = 0
            for cid in content_ids:
                current_date = start_date + timedelta(days=day_offset)
                if end_date and current_date > end_date:
                    break
                current_time = time_slots[slot_idx % posts_per_day]
                scheduled = f"{current_date.strftime('%Y-%m-%d')} {current_time}"
                item = all_items_map.get(cid)
                if item:
                    jobs.append({
                        "folder_path":    item["folder_path"],
                        "caption":        item.get("caption", ""),
                        "folder_name":    item["folder_name"],
                        "page_name":      pg["name"],
                        "page_id":        pg.get("page_id", ""),
                        "scheduled_time": scheduled,
                    })
                slot_idx += 1
                day_count += 1
                if day_count >= posts_per_day:
                    day_offset += 1
                    slot_idx = 0
                    day_count = 0

        if not jobs:
            messagebox.showinfo("Tinix", "Không có bài nào để lên lịch!")
            return

        # ── Validate scheduled times (Facebook rule: +20min to +29days) ──
        now = datetime.now()
        min_dt = now + timedelta(minutes=20)
        max_dt = now + timedelta(days=29)
        invalid_jobs = []
        for j in jobs:
            try:
                st = datetime.strptime(j["scheduled_time"], "%Y-%m-%d %H:%M")
                if st < min_dt or st > max_dt:
                    invalid_jobs.append(j)
            except ValueError:
                invalid_jobs.append(j)

        if invalid_jobs:
            lines = "\n".join(
                f"  • {j['folder_name']} ({j['page_name']}): {j['scheduled_time']}"
                for j in invalid_jobs[:10]
            )
            if len(invalid_jobs) > 10:
                lines += f"\n  ... và {len(invalid_jobs) - 10} bài khác"
            messagebox.showwarning(
                "Lịch đăng không hợp lệ",
                f"Facebook yêu cầu lịch đăng từ 20 phút đến 29 ngày kể từ hiện tại.\n\n"
                f"Các bài sau không hợp lệ:\n{lines}\n\n"
                f"Vui lòng điều chỉnh ngày/giờ đăng rồi thử lại.",
            )
            return

        # Get account
        acct_label = self._account_combo.get()
        account = {}
        if hasattr(self, "_accounts_data"):
            for a in self._accounts_data:
                if (a.get("label") or a.get("username", "")) == acct_label:
                    account = a
                    break
        if not account:
            accounts = get_all_accounts(db_path)
            account = accounts[0] if accounts else {}

        pages_str = ", ".join(pg["name"] for pg in page_data)
        first_t = jobs[0]["scheduled_time"]
        last_t  = jobs[-1]["scheduled_time"]
        logger.info(f"Scheduling {len(jobs)} posts for {pages_str} from {first_t} to {last_t}")

        self._post_now_btn.configure(state="disabled", text="⏳ Đang lên lịch...")
        self._stop_btn.configure(state="normal")
        self._progress.set(0)

        self._posting_thread = threading.Thread(
            target=self._schedule_now_thread,
            args=(jobs, account, brand_name, cta_enabled, share_to_story),
            daemon=True,
        )
        self._posting_thread.start()

    def _schedule_now_thread(
        self,
        jobs: list,
        account: dict,
        brand_name: str,
        cta_enabled: bool,
        share_to_story: bool,
    ):
        """Background thread: schedule each job directly on Facebook."""
        import time as _time
        import random

        total = len(jobs)
        success_count = 0
        fail_count = 0

        self.after(0, self._set_status, "🚀 Starting browser...", _YELLOW)
        self._poster = AutoPoster(account=account, headless=False)

        if not self._poster.start():
            self.after(0, self._schedule_now_done, 0, 0, total, "❌ Browser start failed")
            return

        try:
            for idx, job in enumerate(jobs):
                if self._poster.is_stopped():
                    self.after(0, self._set_status, "⏹ Stopped by user", _YELLOW)
                    break

                self.after(0, self._progress.set, idx / total)
                folder_name = job["folder_name"]
                self.after(0, self._set_status,
                           f"[{idx+1}/{total}] 🗓 {folder_name} → {job['page_name']} @ {job['scheduled_time']}",
                           _ACCENT)

                def on_status(msg, _i=idx):
                    self.after(0, self._set_status, f"[{_i+1}/{total}] {msg}", _ACCENT)
                    logger.info(msg)

                ok = self._poster.post_content(
                    folder_path=job["folder_path"],
                    caption=job["caption"],
                    scheduled_time=job["scheduled_time"],
                    page_name=job["page_name"],
                    page_id=job["page_id"],
                    brand_name=brand_name,
                    cta_enabled=cta_enabled,
                    share_to_story=share_to_story,
                    on_status=on_status,
                )

                if ok:
                    success_count += 1
                    logger.info(f"✅ [{idx+1}/{total}] {folder_name} → Scheduled @ {job['scheduled_time']}")
                else:
                    fail_count += 1
                    logger.error(f"❌ [{idx+1}/{total}] {folder_name} → Failed")

                if idx < total - 1 and not self._poster.is_stopped():
                    wait = random.uniform(5.0, 12.0)
                    self.after(0, self._set_status,
                               f"⏳ Waiting {wait:.0f}s before next post...", _TEXT2)
                    _time.sleep(wait)

        except Exception as e:
            logger.error(f"Schedule Now thread error: {str(e)[:300]}")
        finally:
            if self._poster:
                self._poster.stop()
                self._poster = None

        self.after(0, self._progress.set, 1.0)
        self.after(0, self._schedule_now_done, success_count, fail_count, total, "")

    def _schedule_now_done(self, success: int, failed: int, total: int, error_msg: str):
        self._post_now_btn.configure(state="normal", text="⚡  ĐĂNG NGAY")
        self._stop_btn.configure(state="disabled")
        if error_msg:
            self._set_status(error_msg, _RED)
        else:
            self._set_status(
                f"🗓 Lên lịch xong: {success} thành công, {failed} thất bại (/{total})",
                _GREEN if failed == 0 else _YELLOW,
            )

    def _open_calendar_dialog(self):
        """Open the Smart Calendar dialog."""
        from gui.calendar_dialog import CalendarDialog
        page_data = self._get_selected_page_data()
        CalendarDialog(
            self.winfo_toplevel(),
            page_data=page_data,
            on_execute=self._execute_records_from_calendar,
        )

    def _execute_records_from_calendar(self, records: List[dict]):
        """Execute specific records (from calendar retry/reschedule)."""
        if not records:
            return

        # Validate Facebook scheduling rule: +20min to +29days from now
        now = datetime.now()
        min_dt = now + timedelta(minutes=20)
        max_dt = now + timedelta(days=29)
        invalid = []
        for r in records:
            try:
                st = datetime.strptime(r["scheduled_time"], "%Y-%m-%d %H:%M")
                if st < min_dt or st > max_dt:
                    invalid.append(r)
            except ValueError:
                invalid.append(r)
        if invalid:
            lines = "\n".join(
                f"  • {r['folder_name']} ({r['page_name']}): {r['scheduled_time']}"
                for r in invalid[:10]
            )
            if len(invalid) > 10:
                lines += f"\n  ... và {len(invalid) - 10} bài khác"
            messagebox.showwarning(
                "Lịch đăng không hợp lệ",
                f"Facebook yêu cầu lịch đăng từ 20 phút đến 29 ngày kể từ hiện tại.\n\n"
                f"Các bài sau không hợp lệ:\n{lines}\n\n"
                f"Vui lòng mở XEM LỊCH để sửa ngày/giờ rồi thử lại.",
            )
            return

        acct_label = self._account_combo.get()
        account = {}
        if hasattr(self, "_accounts_data"):
            for a in self._accounts_data:
                if (a.get("label") or a.get("username", "")) == acct_label:
                    account = a
                    break
        if not account:
            db_path = get_db_path(config.get("scraper_db_path", ""))
            accounts = get_all_accounts(db_path)
            account = accounts[0] if accounts else {}

        page_id_map = {d["name"]: d["page_id"] for d in self._get_selected_page_data()}

        self._execute_btn.configure(state="disabled", text="⏳ Executing...")
        self._stop_btn.configure(state="normal")
        self._progress.set(0)

        self._posting_thread = threading.Thread(
            target=self._execute_thread,
            args=(records, account, self._brand_var.get().strip(),
                  False, self._cta_var.get(), page_id_map,
                  self._share_story_var.get()),
            daemon=True,
        )
        self._posting_thread.start()

    def _on_reset_schedule(self):
        """Reset pending posts for selected pages (or all if none selected)."""
        page_names = self._get_selected_pages()

        if page_names:
            target = ", ".join(page_names)
        else:
            target = "tất cả"

        if not messagebox.askyesno(
            "Reset Schedule",
            f"Xóa tất cả bài Pending cho '{target}'?",
        ):
            return

        db_path = get_db_path(config.get("scraper_db_path", ""))
        total_deleted = 0
        if page_names:
            for pg in page_names:
                total_deleted += reset_pending_schedule(db_path, pg)
        else:
            total_deleted = reset_pending_schedule(db_path, "")

        self._set_status(f"Đã xóa {total_deleted} bài Pending", _GREEN)
        self._refresh_treeview()

    # ═══════════════════════════════════════════════════════════════════════
    # EXECUTION ENGINE (Phase 3)
    # ═══════════════════════════════════════════════════════════════════════

    def _on_execute(self):
        """Start executing all pending posts for the selected pages."""
        page_data = self._get_selected_page_data()
        if not page_data:
            messagebox.showwarning("Tinix", "Chọn ít nhất 1 Target Page!")
            return

        # Gather pending records across all selected pages
        page_id_map = {d["name"]: d["page_id"] for d in page_data}
        pending = []
        for pg in page_data:
            pending.extend(self._get_pending_records(pg["name"]))
        pending.sort(key=lambda r: r["scheduled_time"])

        if not pending:
            messagebox.showinfo("Tinix", "Không có bài Pending cho các page đã chọn!")
            return

        # ── Validate scheduled times (Facebook rule: +20min to +29days) ──
        now = datetime.now()
        min_dt = now + timedelta(minutes=20)
        max_dt = now + timedelta(days=29)
        invalid = []
        for r in pending:
            try:
                st = datetime.strptime(r["scheduled_time"], "%Y-%m-%d %H:%M")
                if st < min_dt or st > max_dt:
                    invalid.append(r)
            except ValueError:
                invalid.append(r)
        if invalid:
            lines = "\n".join(
                f"  • {r['folder_name']} ({r['page_name']}): {r['scheduled_time']}"
                for r in invalid[:10]
            )
            if len(invalid) > 10:
                lines += f"\n  ... và {len(invalid) - 10} bài khác"
            messagebox.showwarning(
                "Lịch đăng không hợp lệ",
                f"Facebook yêu cầu lịch đăng từ 20 phút đến 29 ngày kể từ hiện tại.\n\n"
                f"Các bài sau không hợp lệ:\n{lines}\n\n"
                f"Vui lòng mở XEM LỊCH để sửa ngày/giờ rồi thử lại.",
            )
            return

        # Get selected account
        acct_label = self._account_combo.get()
        account = {}
        if hasattr(self, "_accounts_data"):
            for a in self._accounts_data:
                lbl = a.get("label") or a.get("username", "")
                if lbl == acct_label:
                    account = a
                    break
        if not account:
            db_path = get_db_path(config.get("scraper_db_path", ""))
            accounts = get_all_accounts(db_path)
            account = accounts[0] if accounts else {}

        brand_name = self._brand_var.get().strip()
        headless = self._headless_var.get()
        cta_enabled = self._cta_var.get()
        share_to_story = self._share_story_var.get()

        # UI state
        self._execute_btn.configure(state="disabled", text="⏳ Executing...")
        self._stop_btn.configure(state="normal")
        self._progress.set(0)

        self._posting_thread = threading.Thread(
            target=self._execute_thread,
            args=(pending, account, brand_name, headless, cta_enabled, page_id_map, share_to_story),
            daemon=True,
        )
        self._posting_thread.start()

    def _execute_thread(
        self,
        pending: List[dict],
        account: dict,
        brand_name: str,
        headless: bool,
        cta_enabled: bool,
        page_id_map: dict = None,
        share_to_story: bool = True,
    ):
        """Background thread: execute all pending posts."""
        db_path = get_db_path(config.get("scraper_db_path", ""))
        total = len(pending)
        success_count = 0
        fail_count = 0
        _page_id_map = page_id_map or {}

        # Start browser
        self.after(0, self._set_status, "🚀 Starting browser...", _YELLOW)
        self._poster = AutoPoster(account=account, headless=headless)

        if not self._poster.start():
            self.after(0, self._execute_done, 0, 0, total, "❌ Browser start failed")
            return

        try:
            for idx, record in enumerate(pending):
                if self._poster.is_stopped():
                    self.after(0, self._set_status, "⏹ Stopped by user", _YELLOW)
                    break

                # Progress
                frac = (idx) / total
                self.after(0, self._progress.set, frac)

                folder_name = record.get("folder_name", "")
                self.after(0, self._set_status,
                           f"[{idx+1}/{total}] {folder_name}", _ACCENT)

                def on_status(msg, _idx=idx):
                    self.after(0, self._set_status, f"[{_idx+1}/{total}] {msg}", _ACCENT)
                    logger.info(msg)

                page_id = _page_id_map.get(record["page_name"], "")

                # Execute single post
                ok = self._poster.post_content(
                    folder_path=record["folder_path"],
                    caption=record["caption"],
                    scheduled_time=record["scheduled_time"],
                    page_name=record["page_name"],
                    page_id=page_id,
                    brand_name=brand_name,
                    cta_enabled=cta_enabled,
                    share_to_story=share_to_story,
                    on_status=on_status,
                )

                # Update DB status + log error if any
                new_status = "Scheduled" if ok else "Failed"
                error_msg_log = "" if ok else (
                    getattr(self._poster, "_last_error", "") or "Unknown error"
                )
                update_history_status_with_error(
                    db_path, record["history_id"], new_status, error_msg_log
                )

                if ok:
                    success_count += 1
                    logger.info(f"✅ [{idx+1}/{total}] {folder_name} → Scheduled")
                else:
                    fail_count += 1
                    logger.error(f"❌ [{idx+1}/{total}] {folder_name} → Failed")

                # Anti-detection: random delay between posts
                if idx < total - 1 and not self._poster.is_stopped():
                    import random
                    wait = random.uniform(5.0, 12.0)
                    self.after(0, self._set_status,
                              f"⏳ Waiting {wait:.0f}s before next post...", _TEXT2)
                    import time
                    time.sleep(wait)

        except Exception as e:
            logger.error(f"Execute error: {str(e)[:300]}")
        finally:
            # Stop browser
            if self._poster:
                self._poster.stop()
                self._poster = None

        self.after(0, self._progress.set, 1.0)
        self.after(0, self._execute_done, success_count, fail_count, total, "")

    def _execute_done(self, success: int, failed: int, total: int, error_msg: str):
        """Called on main thread after execution completes."""
        self._execute_btn.configure(state="normal", text="▶️  EXECUTE PENDING")
        self._stop_btn.configure(state="disabled")

        if error_msg:
            self._set_status(error_msg, _RED)
        else:
            self._set_status(
                f"✅ Done: {success} scheduled, {failed} failed (of {total})",
                _GREEN if failed == 0 else _YELLOW,
            )

        self._refresh_treeview()

    def _on_stop_execute(self):
        """Stop the execution loop."""
        if self._poster:
            self._poster.request_stop()
            self._set_status("⏹ Stopping after current post...", _YELLOW)
            self._stop_btn.configure(state="disabled")

    # ═══════════════════════════════════════════════════════════════════════
    # POST NOW (immediate, no scheduling)
    # ═══════════════════════════════════════════════════════════════════════

    def _on_post_now(self):
        """Post now: if any time slots are active → schedule on FB; else post immediately."""
        if self._get_active_time_slots():
            self._on_schedule_now()
            return
        content_ids = self._get_selected_content_ids()
        if not content_ids:
            messagebox.showwarning("Tinix", "Chọn ít nhất 1 nội dung từ Library!")
            return

        page_data = self._get_selected_page_data()
        if not page_data:
            messagebox.showwarning("Tinix", "Chọn ít nhất 1 Target Page!")
            return

        db_path = get_db_path(config.get("scraper_db_path", ""))
        all_items = get_all_content_pool(db_path)
        items_to_post = [i for i in all_items if i["content_id"] in content_ids]
        if not items_to_post:
            messagebox.showwarning("Tinix", "Không tìm thấy nội dung đã chọn!")
            return

        # Get account
        acct_label = self._account_combo.get()
        account = {}
        if hasattr(self, "_accounts_data"):
            for a in self._accounts_data:
                if (a.get("label") or a.get("username", "")) == acct_label:
                    account = a
                    break
        if not account:
            all_accts = get_all_accounts(db_path)
            account = all_accts[0] if all_accts else {}

        self._post_now_btn.configure(state="disabled", text="⏳ Đang đăng...")
        self._stop_btn.configure(state="normal")
        self._progress.set(0)

        self._posting_thread = threading.Thread(
            target=self._post_now_thread,
            args=(
                items_to_post, page_data, account,
                self._brand_var.get().strip(),
                self._headless_var.get(),
                self._cta_var.get(),
                self._share_story_var.get(),
            ),
            daemon=True,
        )
        self._posting_thread.start()

    def _post_now_thread(
        self,
        items: list,
        pages: List[dict],
        account: dict,
        brand_name: str,
        headless: bool,
        cta_enabled: bool,
        share_to_story: bool = True,
    ):
        """Background thread: post items immediately to all selected pages."""
        import random
        import time as _time

        total = len(items) * len(pages)
        success_count = 0
        fail_count = 0
        idx = 0

        self.after(0, self._set_status, "🚀 Starting browser...", _YELLOW)
        self._poster = AutoPoster(account=account, headless=headless)

        if not self._poster.start():
            self.after(0, self._post_now_done, 0, 0, total, "❌ Browser start failed")
            return

        try:
            stopped = False
            for item in items:
                if stopped:
                    break
                for pg in pages:
                    page_name = pg["name"]
                    page_id = pg.get("page_id", "")
                    if self._poster.is_stopped():
                        self.after(0, self._set_status, "⏹ Stopped by user", _YELLOW)
                        stopped = True
                        break

                    self.after(0, self._progress.set, idx / total)
                    folder_name = item.get("folder_name", "")
                    self.after(0, self._set_status,
                               f"[{idx+1}/{total}] {folder_name} → {page_name}", _ACCENT)

                    def on_status(msg, _i=idx):
                        self.after(0, self._set_status,
                                   f"[{_i+1}/{total}] {msg}", _ACCENT)
                        logger.info(msg)

                    ok = self._poster.post_now(
                        folder_path=item["folder_path"],
                        caption=item.get("caption", ""),
                        page_name=page_name,
                        page_id=page_id,
                        brand_name=brand_name,
                        cta_enabled=cta_enabled,
                        share_to_story=share_to_story,
                        on_status=on_status,
                    )

                    if ok:
                        success_count += 1
                        logger.info(f"✅ [{idx+1}/{total}] {folder_name} → {page_name}")
                    else:
                        fail_count += 1
                        logger.error(f"❌ [{idx+1}/{total}] {folder_name} → {page_name}")

                    idx += 1

                    if idx < total and not self._poster.is_stopped():
                        wait = random.uniform(5.0, 12.0)
                        self.after(0, self._set_status,
                                   f"⏳ Chờ {wait:.0f}s trước bài tiếp...", _TEXT2)
                        _time.sleep(wait)

        except Exception as e:
            logger.error(f"Post Now thread error: {str(e)[:300]}")
        finally:
            if self._poster:
                self._poster.stop()
                self._poster = None

        self.after(0, self._progress.set, 1.0)
        self.after(0, self._post_now_done, success_count, fail_count, total, "")

    def _post_now_done(self, success: int, failed: int, total: int, error_msg: str):
        self._post_now_btn.configure(state="normal", text="⚡  ĐĂNG NGAY")
        self._stop_btn.configure(state="disabled")
        if error_msg:
            self._set_status(error_msg, _RED)
        else:
            self._set_status(
                f"⚡ Đăng xong: {success} thành công, {failed} thất bại (/{total})",
                _GREEN if failed == 0 else _YELLOW,
            )

    def _get_pending_records(self, page_name: str) -> List[dict]:
        """Get all Pending post_history records for a page with content info."""
        try:
            db_path = get_db_path(config.get("scraper_db_path", ""))
            conn = sqlite3.connect(db_path)
            rows = conn.execute("""
                SELECT h.history_id, h.content_id, h.page_name, h.scheduled_time,
                       c.folder_name, c.folder_path, c.caption
                FROM post_history h
                JOIN content_pool c ON h.content_id = c.content_id
                WHERE h.status = 'Pending' AND h.page_name = ?
                ORDER BY h.scheduled_time
            """, (page_name,)).fetchall()
            conn.close()
            return [
                {
                    "history_id": r[0], "content_id": r[1],
                    "page_name": r[2], "scheduled_time": r[3],
                    "folder_name": r[4], "folder_path": r[5],
                    "caption": r[6],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"get_pending error: {str(e)[:200]}")
            return []

    @staticmethod
    def _update_history_status(db_path: str, history_id: int, status: str):
        """Update a single post_history record status."""
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                "UPDATE post_history SET status = ? WHERE history_id = ?",
                (status, history_id),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Status update error: {str(e)[:100]}")

    # ═══════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def _get_selected_content_ids(self) -> List[int]:
        """Extract content_ids from selected treeview items."""
        ids = []
        for item_id in self._tree.selection():
            tags = self._tree.item(item_id, "tags")
            for t in tags:
                if t.startswith("cid_"):
                    try:
                        ids.append(int(t[4:]))
                    except ValueError:
                        pass
        return ids

    def _on_search_changed(self, *_args):
        self._populate_treeview(self._all_items)

    def _filter_items(self, items: List[dict]) -> List[dict]:
        query = self._search_var.get().strip().lower()
        if not query:
            return items
        return [
            it for it in items
            if query in it["folder_name"].lower()
            or query in it["caption"].lower()
        ]

    def _refresh_treeview(self):
        db_path = get_db_path(config.get("scraper_db_path", ""))
        self._all_items = get_all_content_pool(db_path)
        self._populate_treeview(self._all_items)

    def _populate_treeview(self, items: List[dict]):
        self._filtered_items = self._filter_items(items)
        self._current_page = 0
        self._render_page()

    def _render_page(self):
        """Render the current page of _filtered_items into the treeview."""
        for child in self._tree.get_children():
            self._tree.delete(child)

        filtered = self._filtered_items
        total_rows = len(filtered)

        # Compute page slice
        size_str = self._page_size_var.get()
        if size_str == "Tất cả":
            page_size = total_rows or 1
        else:
            page_size = int(size_str)

        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        self._current_page = max(0, min(self._current_page, total_pages - 1))

        start = self._current_page * page_size
        end = min(start + page_size, total_rows)
        page_items = filtered[start:end]

        for idx, item in enumerate(page_items):
            caption_snip = (
                item["caption"][:50] + "..." if len(item["caption"]) > 50
                else item["caption"]
            )
            img_c, vid_c = count_media_in_folder(item["folder_path"])
            parts = []
            if img_c > 0:
                parts.append(f"{img_c} img")
            if vid_c > 0:
                parts.append(f"{vid_c} vid")
            media_str = ", ".join(parts) if parts else "⚠ empty"

            row_tag = "odd" if idx % 2 == 0 else "even"
            cid_tag = f"cid_{item['content_id']}"

            self._tree.insert("", "end", values=(
                start + idx + 1,
                item["folder_name"],
                caption_snip,
                media_str,
                item["post_status"],
            ), tags=(cid_tag, row_tag))

        # Update pagination controls
        self._pg_label.configure(text=f"{self._current_page + 1} / {total_pages}")
        self._pg_prev_btn.configure(state="normal" if self._current_page > 0 else "disabled")
        self._pg_next_btn.configure(state="normal" if self._current_page < total_pages - 1 else "disabled")

        total = len(self._all_items)
        text = f"📦 {total_rows}/{total}" if total_rows < total else f"📦 {total}"
        self._stats_label.configure(text=text)

    def _pg_prev(self):
        self._current_page -= 1
        self._render_page()

    def _pg_next(self):
        self._current_page += 1
        self._render_page()

    def _on_page_size_changed(self, _value=None):
        self._current_page = 0
        self._render_page()

    def _log(self, text: str, level: str = "INFO"):
        """Append a timestamped line to the console widget (thread-safe via after)."""
        def _do():
            ts = datetime.now().strftime("%H:%M:%S")
            tag = level if level in ("OK", "WARN", "ERROR", "INFO") else "INFO"
            try:
                self._console.configure(state="normal")
                self._console.insert("end", f"[{ts}] ", "TIME")
                self._console.insert("end", f"{text}\n", tag)
                self._console.see("end")
                self._console.configure(state="disabled")
            except Exception:
                pass
        self.after(0, _do)

    def _clear_console(self):
        try:
            self._console.configure(state="normal")
            self._console.delete("1.0", "end")
            self._console.configure(state="disabled")
        except Exception:
            pass

    def _set_status(self, text: str, color: str = _TEXT2):
        self._status_label.configure(text=text, text_color=color)
        # Mirror to console with appropriate level
        if color == _GREEN or "✅" in text:
            level = "OK"
        elif color == _RED or "❌" in text:
            level = "ERROR"
        elif color == _YELLOW or "⚠" in text or "⏳" in text:
            level = "WARN"
        else:
            level = "INFO"
        self._log(text, level)

    # ═══════════════════════════════════════════════════════════════════════
    # CAPTION INLINE EDIT (double-click)
    # ═══════════════════════════════════════════════════════════════════════

    def _on_tree_double_click(self, event):
        """Open caption editor when user double-clicks the Caption column."""
        region = self._tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self._tree.identify_column(event.x)
        # Column indices: #1=id, #2=folder, #3=caption, #4=media, #5=status
        if col != "#3":
            return
        item_id = self._tree.identify_row(event.y)
        if not item_id:
            return

        # Get content_id from tag
        content_id = None
        for tag in self._tree.item(item_id, "tags"):
            if tag.startswith("cid_"):
                content_id = int(tag[4:])
                break
        if content_id is None:
            return

        # Find full caption from _all_items (treeview shows truncated)
        item_data = next((it for it in self._all_items if it["content_id"] == content_id), None)
        if not item_data:
            return

        self._show_caption_editor(content_id, item_data["folder_name"],
                                  item_data["folder_path"], item_data["caption"])

    def _show_caption_editor(self, content_id: int, folder_name: str,
                             folder_path: str, current_caption: str):
        """Modal dialog to edit caption, then save to DB + Excel."""
        dlg = ctk.CTkToplevel(self)
        dlg.title(f"Sửa caption — {folder_name}")
        dlg.resizable(True, False)
        dlg.grab_set()
        dlg.configure(fg_color=_CARD)
        dlg.update_idletasks()
        w, h = 540, 280
        px = self.winfo_rootx() + self.winfo_width() // 2 - w // 2
        py = self.winfo_rooty() + self.winfo_height() // 2 - h // 2
        dlg.geometry(f"{w}x{h}+{px}+{py}")

        ctk.CTkLabel(
            dlg, text=f"📁 {folder_name}",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=_TEXT,
        ).pack(anchor="w", padx=16, pady=(14, 2))

        ctk.CTkLabel(
            dlg, text="Chỉnh sửa caption (Ctrl+Enter để lưu):",
            font=ctk.CTkFont(size=11), text_color=_TEXT2,
        ).pack(anchor="w", padx=16)

        txt = ctk.CTkTextbox(
            dlg, height=120, font=ctk.CTkFont(size=11),
            fg_color=_CARD2, text_color=_TEXT, border_color=_BORDER, border_width=1,
        )
        txt.pack(fill="x", padx=16, pady=(6, 0))
        txt.insert("1.0", current_caption)
        txt.focus_set()

        status_lbl = ctk.CTkLabel(dlg, text="", font=ctk.CTkFont(size=10), text_color=_TEXT2)
        status_lbl.pack(anchor="w", padx=16, pady=(4, 0))

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(8, 14))

        def _save():
            new_caption = txt.get("1.0", "end").rstrip("\n")
            if new_caption == current_caption:
                dlg.destroy()
                return

            db_path = get_db_path(config.get("scraper_db_path", ""))
            ok_db = update_content_caption(db_path, content_id, new_caption)

            ok_excel = False
            if folder_path and os.path.isdir(folder_path):
                ok_excel = self._update_excel_caption(folder_path, folder_name, new_caption)

            if ok_db:
                self._refresh_treeview()
                msg = "✅ Đã lưu DB"
                msg += " + Excel" if ok_excel else " (không tìm thấy file Excel)"
                self._set_status(msg, _GREEN)
                dlg.destroy()
            else:
                status_lbl.configure(text="❌ Lưu DB thất bại", text_color=_RED)

        ctk.CTkButton(
            btn_row, text="✓ Lưu", width=100, height=32,
            fg_color=_ACCENT, hover_color="#2563EB",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#FFFFFF",
            command=_save,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            btn_row, text="Hủy", width=80, height=32,
            fg_color=_CARD2, hover_color=_BORDER, text_color=_TEXT,
            command=dlg.destroy,
        ).pack(side="right")

        def _open_folder():
            path = folder_path if folder_path and os.path.isdir(folder_path) else ""
            if not path:
                status_lbl.configure(text="⚠ Thư mục không tồn tại", text_color=_YELLOW)
                return
            import subprocess
            subprocess.Popen(["explorer", os.path.normpath(path)])

        ctk.CTkButton(
            btn_row, text="📂 Mở thư mục", width=110, height=32,
            fg_color=_CARD2, hover_color=_BORDER, text_color=_TEXT,
            command=_open_folder,
        ).pack(side="left")

        # Ctrl+Enter shortcut
        txt.bind("<Control-Return>", lambda _e: _save())

    def _update_excel_caption(self, folder_path: str, folder_name: str,
                               new_caption: str) -> bool:
        """
        Find the Excel file in folder_path (or its parent), update the row
        matching folder_name, save back. Returns True if updated successfully.
        """
        import glob
        # Search in the folder itself and one level up (main_folder)
        search_dirs = [folder_path, str(os.path.dirname(folder_path))]
        excel_file = None
        for d in search_dirs:
            hits = glob.glob(os.path.join(d, "*.xlsx")) + glob.glob(os.path.join(d, "*.xls"))
            if hits:
                excel_file = hits[0]
                break

        if not excel_file:
            logger.warning(f"update_excel_caption: no Excel found near {folder_path}")
            return False

        try:
            import openpyxl
            wb = openpyxl.load_workbook(excel_file)
            ws = wb.active

            # Detect header row and column indices
            folder_col_idx = None
            caption_col_idx = None
            header_row = 1
            for cell in ws[header_row]:
                if cell.value is None:
                    continue
                v = str(cell.value).lower().strip()
                if v in ("folder_name", "folder", "tên thư mục", "ten thu muc", "name"):
                    folder_col_idx = cell.column
                elif v in ("caption", "nội dung", "noi dung", "content", "mô tả", "mo ta"):
                    caption_col_idx = cell.column

            # Fallback: use first two columns
            if folder_col_idx is None:
                folder_col_idx = 1
            if caption_col_idx is None and ws.max_column >= 2:
                caption_col_idx = 2

            if caption_col_idx is None:
                logger.warning("update_excel_caption: cannot find caption column")
                return False

            # Find the matching row and update
            updated = False
            for row in ws.iter_rows(min_row=header_row + 1):
                cell_folder = row[folder_col_idx - 1]
                if cell_folder.value and str(cell_folder.value).strip() == folder_name:
                    row[caption_col_idx - 1].value = new_caption
                    updated = True
                    break

            if updated:
                wb.save(excel_file)
                logger.info(f"Excel updated: {os.path.basename(excel_file)} [{folder_name}]")
            else:
                logger.warning(f"update_excel_caption: folder '{folder_name}' not found in Excel")
            return updated

        except Exception as e:
            logger.error(f"update_excel_caption error: {str(e)[:200]}")
            return False

    # ═══════════════════════════════════════════════════════════════════════
    # DATE & TIME PICKERS
    # ═══════════════════════════════════════════════════════════════════════

    def _show_range_picker(self):
        """
        Single calendar dialog that selects both Start Date and End Date.
        Step 1: click a day → sets Start Date (highlighted blue).
        Step 2: click another day → sets End Date, highlights range, closes.
        Footer buttons: [Hôm nay] [Xóa End] [✓ Xác nhận]
        """
        import calendar as _cal

        # Parse existing values
        def _parse(s: str) -> Optional[datetime]:
            try:
                return datetime.strptime(s.strip(), "%Y-%m-%d")
            except ValueError:
                return None

        sel = {
            "start": _parse(self._date_var.get()) or datetime.now(),
            "end": _parse(self._end_date_var.get()),
            "step": 1,          # 1 = choosing start, 2 = choosing end
        }

        nav = {"year": sel["start"].year, "month": sel["start"].month}

        # ── Dialog ──────────────────────────────────────────────────────
        dlg = ctk.CTkToplevel(self)
        dlg.title("📅 Chọn khoảng thời gian")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.configure(fg_color=_CARD)
        dlg.update_idletasks()
        px = self.winfo_rootx() + self.winfo_width() // 2 - 160
        py = self.winfo_rooty() + self.winfo_height() // 2 - 145
        dlg.geometry(f"322x330+{px}+{py}")

        # ── Header (nav) ────────────────────────────────────────────────
        hdr = ctk.CTkFrame(dlg, fg_color="transparent")
        hdr.pack(fill="x", padx=8, pady=(8, 2))

        month_lbl = ctk.CTkLabel(
            hdr, text="", width=200,
            font=ctk.CTkFont(size=13, weight="bold"), text_color=_TEXT,
        )

        def _prev():
            if nav["month"] == 1:
                nav["year"] -= 1; nav["month"] = 12
            else:
                nav["month"] -= 1
            _render()

        def _next():
            if nav["month"] == 12:
                nav["year"] += 1; nav["month"] = 1
            else:
                nav["month"] += 1
            _render()

        ctk.CTkButton(hdr, text="◀", width=30, height=28,
            font=ctk.CTkFont(size=13), fg_color=_CARD2, hover_color=_BORDER,
            corner_radius=5, text_color=_TEXT, command=_prev,
        ).pack(side="left")
        month_lbl.pack(side="left", expand=True)
        ctk.CTkButton(hdr, text="▶", width=30, height=28,
            font=ctk.CTkFont(size=13), fg_color=_CARD2, hover_color=_BORDER,
            corner_radius=5, text_color=_TEXT, command=_next,
        ).pack(side="right")

        # ── Step hint label ─────────────────────────────────────────────
        hint_lbl = ctk.CTkLabel(
            dlg, text="",
            font=ctk.CTkFont(size=10), text_color=_ACCENT,
        )
        hint_lbl.pack(pady=(0, 2))

        # ── Day grid ────────────────────────────────────────────────────
        grid_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        grid_frame.pack(fill="both", expand=True, padx=8)

        DAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
        for c, d in enumerate(DAYS):
            ctk.CTkLabel(
                grid_frame, text=d, width=38, height=22,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=_ACCENT if d == "CN" else _TEXT2,
            ).grid(row=0, column=c, padx=1, pady=(0, 1))

        day_buttons: List = []

        def _date_of(day, y, m) -> datetime:
            return datetime(y, m, day)

        def _in_range(d: datetime) -> bool:
            if sel["start"] and sel["end"]:
                lo, hi = sorted([sel["start"], sel["end"]])
                return lo <= d <= hi
            return False

        def _render():
            for b in day_buttons:
                b.destroy()
            day_buttons.clear()

            y, m = nav["year"], nav["month"]
            month_lbl.configure(text=f"{y}/{m:02d}")

            hint_lbl.configure(
                text="① Nhấp chọn Start Date" if sel["step"] == 1
                     else "② Nhấp chọn End Date  (hoặc nhấn Xác nhận để bỏ qua)"
            )

            first_wd, num_days = _cal.monthrange(y, m)

            for day in range(1, num_days + 1):
                cell_idx = first_wd + day - 1
                r, c = divmod(cell_idx, 7)
                r += 1

                d_obj = _date_of(day, y, m)
                is_start = sel["start"] and d_obj.date() == sel["start"].date()
                is_end   = sel["end"]   and d_obj.date() == sel["end"].date()
                in_rng   = _in_range(d_obj)
                is_today = d_obj.date() == datetime.now().date()

                if is_start or is_end:
                    bg, tc = _ACCENT, "#FFFFFF"
                elif in_rng:
                    bg, tc = "#1D4ED8", "#FFFFFF"  # mid-range (darker blue)
                elif is_today:
                    bg, tc = _GREEN, "#FFFFFF"
                else:
                    bg, tc = _CARD2, _TEXT

                btn = ctk.CTkButton(
                    grid_frame, text=str(day), width=38, height=28,
                    font=ctk.CTkFont(size=11), corner_radius=4,
                    fg_color=bg, hover_color="#2563EB", text_color=tc,
                    command=lambda _d=day, _y=y, _m=m: _click(_d, _y, _m),
                )
                btn.grid(row=r, column=c, padx=1, pady=1)
                day_buttons.append(btn)

        def _click(day, y, m):
            clicked = _date_of(day, y, m)
            if sel["step"] == 1:
                sel["start"] = clicked
                sel["end"] = None
                sel["step"] = 2
                _render()
            else:
                # Ensure end >= start
                if clicked < sel["start"]:
                    sel["start"], sel["end"] = clicked, sel["start"]
                else:
                    sel["end"] = clicked
                _confirm()

        def _confirm():
            self._date_var.set(sel["start"].strftime("%Y-%m-%d") if sel["start"] else "")
            self._end_date_var.set(sel["end"].strftime("%Y-%m-%d") if sel["end"] else "")
            dlg.destroy()

        def _today():
            sel["start"] = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            if sel["step"] == 2:
                sel["end"] = None
            sel["step"] = 2
            nav["year"]  = sel["start"].year
            nav["month"] = sel["start"].month
            _render()

        def _clear_end():
            sel["end"] = None
            sel["step"] = 2
            _render()

        _render()

        # ── Footer buttons ───────────────────────────────────────────────
        foot = ctk.CTkFrame(dlg, fg_color="transparent")
        foot.pack(fill="x", padx=8, pady=(4, 8))

        ctk.CTkButton(
            foot, text="Hôm nay", height=28, width=80,
            font=ctk.CTkFont(size=10), fg_color=_CARD2, hover_color=_BORDER,
            corner_radius=6, text_color=_TEXT2, command=_today,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            foot, text="Xóa End", height=28, width=80,
            font=ctk.CTkFont(size=10), fg_color=_CARD2, hover_color=_BORDER,
            corner_radius=6, text_color=_TEXT2, command=_clear_end,
        ).pack(side="left")

        ctk.CTkButton(
            foot, text="✓  Xác nhận", height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=_ACCENT, hover_color="#2563EB", corner_radius=6,
            command=_confirm,
        ).pack(side="right")

        dlg.bind("<Return>", lambda e: _confirm())
