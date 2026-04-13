"""
Tinix Facebook Down — Data Operations Center
Full-featured dashboard with multi-filter export + bulk delete.

Left Panel:  Advanced Multi-Filter → Export to Excel (pandas + openpyxl)
Right Panel: Bulk Delete by post_id with disk cleanup
"""

import os
import threading
from datetime import datetime
from tkinter import messagebox
from typing import Optional, Callable

import customtkinter as ctk

from core.db_storage import (
    get_db_path, get_all_pages, get_all_groups,
    query_posts_filtered, bulk_delete_posts,
)
from utils import config, logger
from gui.social_post_tab import SocialPostTab
from gui.video_post_tab import VideoPostTab


# ─── Constants ───────────────────────────────────────────────────────────────

_BG = "#0F172A"          # Main dark bg
_CARD = "#1E293B"        # Card bg
_CARD2 = "#334155"       # Input bg
_BORDER = "#475569"      # Border
_TEXT = "#F1F5F9"        # Primary text
_TEXT2 = "#94A3B8"       # Secondary text
_ACCENT = "#3B82F6"      # Blue accent
_GREEN = "#16A34A"       # Success
_RED = "#DC2626"         # Danger
_YELLOW = "#F59E0B"      # Warning


class DashboardTab(ctk.CTkFrame):
    """Data Operations Center — replaces old Dashboard."""

    def __init__(self, master, on_send_to_download: Optional[Callable] = None, **kwargs):
        super().__init__(master, fg_color=_BG, corner_radius=0, **kwargs)
        self._on_send_to_download = on_send_to_download
        self._export_path: str = ""
        self._setup_ui()

    # ═══════════════════════════════════════════════════════════════════════
    # LAYOUT
    # ═══════════════════════════════════════════════════════════════════════

    def _setup_ui(self):
        # Title
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(
            title_frame, text="🖥 Data Operations Center",
            font=ctk.CTkFont(size=18, weight="bold"), text_color=_TEXT,
        ).pack(side="left")

        ctk.CTkLabel(
            title_frame, text="Export & Maintenance",
            font=ctk.CTkFont(size=12), text_color=_TEXT2,
        ).pack(side="left", padx=10, pady=(4, 0))
        # ── Tabview for Image & Video posts ──
        tabview = ctk.CTkTabview(self, width=0, height=0)
        tabview.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        tabview.add("Image")
        tabview.add("Video")
        # Instantiate tabs
        self.image_tab = SocialPostTab(tabview.tab("Image"))
        self.video_tab = VideoPostTab(tabview.tab("Video"))

        def _on_tab_change(event=None):
            cur = tabview.get()
            if cur == "Video":
                tabview.configure(segmented_button_selected_color="#7C3AED")
            else:
                tabview.configure(segmented_button_selected_color="#3B82F6")
        tabview._segmented_button.configure(command=_on_tab_change)

        # Main split: Left (filters) | Right (bulk delete)
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        # Left panel — 65% width
        left = ctk.CTkFrame(main, fg_color=_CARD, corner_radius=12, border_width=1, border_color=_BORDER)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        # Right panel — 35% width
        right = ctk.CTkFrame(main, fg_color=_CARD, corner_radius=12, border_width=1, border_color=_BORDER, width=320)
        right.pack(side="right", fill="both", padx=(6, 0))
        right.pack_propagate(False)

        self._build_filter_panel(left)
        self._build_delete_panel(right)

        # Bottom: Progress bar + status
        bottom = ctk.CTkFrame(self, fg_color=_CARD, corner_radius=10, height=50)
        bottom.pack(fill="x", padx=16, pady=(0, 10))
        bottom.pack_propagate(False)

        self._status_label = ctk.CTkLabel(
            bottom, text="Sẵn sàng", font=ctk.CTkFont(size=12),
            text_color=_TEXT2,
        )
        self._status_label.pack(side="left", padx=12)

        self._progress = ctk.CTkProgressBar(
            bottom, height=8, corner_radius=4,
            fg_color=_CARD2, progress_color=_ACCENT,
        )
        self._progress.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=16)
        self._progress.set(0)

        # Post-export action buttons (hidden initially)
        self._action_frame = ctk.CTkFrame(bottom, fg_color="transparent")

        self._open_file_btn = ctk.CTkButton(
            self._action_frame, text="📄 Mở File", width=90, height=30,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=_GREEN, hover_color="#15803D", corner_radius=6,
            command=self._open_export_file,
        )
        self._open_file_btn.pack(side="left", padx=(0, 4))

        self._open_folder_btn = ctk.CTkButton(
            self._action_frame, text="📂 Mở Folder", width=100, height=30,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=_ACCENT, hover_color="#2563EB", corner_radius=6,
            command=self._open_export_folder,
        )
        self._open_folder_btn.pack(side="left")

    # ═══════════════════════════════════════════════════════════════════════
    # LEFT PANEL — Advanced Multi-Filter
    # ═══════════════════════════════════════════════════════════════════════

    def _build_filter_panel(self, parent):
        # Section title
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            header, text="🔍 Advanced Multi-Filter",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=_TEXT,
        ).pack(side="left")

        # ── Filter grid ──
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 8))

        # Load data for dropdowns
        db_path = get_db_path(config.get("scraper_db_path", ""))
        pages = get_all_pages(db_path)
        groups = get_all_groups(db_path)
        page_names = ["Tất cả"] + [p["page_name"] for p in pages]
        group_names = ["Tất cả"] + groups

        # Row 1: Page + Group
        r1 = ctk.CTkFrame(grid, fg_color="transparent")
        r1.pack(fill="x", pady=3)

        self._f_page = self._filter_combo(r1, "📄 Page", page_names, width=200)
        self._f_group = self._filter_combo(r1, "📁 Group", group_names, width=160)

        # Row 2: Content Type + Time Range
        r2 = ctk.CTkFrame(grid, fg_color="transparent")
        r2.pack(fill="x", pady=3)

        self._f_type = self._filter_combo(r2, "📌 Loại", ["Tất cả", "Ảnh", "Video", "Text"], width=110)
        self._f_date_from = self._filter_entry(r2, "📅 Từ", placeholder="dd/mm/yyyy", width=100)
        self._f_date_to = self._filter_entry(r2, "→ Đến", placeholder="dd/mm/yyyy", width=100)

        # Row 3: Min Engage + Min Views + Keyword
        r3 = ctk.CTkFrame(grid, fg_color="transparent")
        r3.pack(fill="x", pady=3)

        self._f_engage = self._filter_entry(r3, "❤ Min Engage", placeholder="0", width=80)
        self._f_views = self._filter_entry(r3, "👁 Min Views", placeholder="0", width=80)
        self._f_keyword = self._filter_entry(r3, "🔎 Keyword", placeholder="tìm trong caption...", width=160)

        # Row 4: Download Status
        r4 = ctk.CTkFrame(grid, fg_color="transparent")
        r4.pack(fill="x", pady=3)

        self._f_dl_status = self._filter_combo(r4, "⬇ Download", ["Tất cả", "Đã tải", "Chưa tải"], width=120)

        # ── Action buttons ──
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(fill="x", padx=14, pady=(4, 12))

        self._export_btn = ctk.CTkButton(
            btn_frame, text="📊  EXPORT TO EXCEL", height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=_GREEN, hover_color="#15803D", corner_radius=10,
            command=self._on_export,
        )
        self._export_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            btn_frame, text="🔄 Reset", width=90, height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=_CARD2, hover_color="#475569", corner_radius=10,
            text_color=_TEXT,
            command=self._reset_filters,
        ).pack(side="right")

        # ── Stats label ──
        self._filter_stats = ctk.CTkLabel(
            parent, text="",
            font=ctk.CTkFont(size=12), text_color=_TEXT2,
        )
        self._filter_stats.pack(padx=14, pady=(0, 10), anchor="w")

    # ═══════════════════════════════════════════════════════════════════════
    # RIGHT PANEL — Bulk Maintenance
    # ═══════════════════════════════════════════════════════════════════════

    def _build_delete_panel(self, parent):
        # Title
        ctk.CTkLabel(
            parent, text="🗑 Bulk Maintenance",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=_TEXT,
        ).pack(padx=14, pady=(12, 4), anchor="w")

        ctk.CTkLabel(
            parent, text="Dán danh sách post_id để xóa vĩnh viễn\n(mỗi ID trên 1 dòng hoặc copy từ Excel)",
            font=ctk.CTkFont(size=11), text_color=_TEXT2,
            justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        # Post ID textbox
        self._del_textbox = ctk.CTkTextbox(
            parent, height=300,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, border_width=1, corner_radius=8,
        )
        self._del_textbox.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        # ID count label
        self._del_count = ctk.CTkLabel(
            parent, text="0 IDs",
            font=ctk.CTkFont(size=11), text_color=_TEXT2,
        )
        self._del_count.pack(padx=14, anchor="w")

        # Update count on key release
        self._del_textbox.bind("<KeyRelease>", self._update_id_count)

        # Delete button
        self._del_btn = ctk.CTkButton(
            parent, text="🗑  PERMANENT DELETE", height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=_RED, hover_color="#B91C1C", corner_radius=10,
            text_color="#FFFFFF",
            command=self._on_delete,
        )
        self._del_btn.pack(fill="x", padx=14, pady=(8, 14))

    # ═══════════════════════════════════════════════════════════════════════
    # FILTER WIDGET BUILDERS
    # ═══════════════════════════════════════════════════════════════════════

    def _filter_combo(self, parent, label: str, values: list, width: int = 140) -> ctk.CTkComboBox:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(
            frame, text=label,
            font=ctk.CTkFont(size=11, weight="bold"), text_color=_TEXT2,
        ).pack(anchor="w")

        combo = ctk.CTkComboBox(
            frame, width=width, height=30,
            font=ctk.CTkFont(size=11),
            values=values,
            fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, corner_radius=6,
            button_color="#475569", button_hover_color="#64748B",
            dropdown_fg_color=_CARD, dropdown_text_color=_TEXT,
            dropdown_hover_color=_ACCENT,
        )
        combo.pack()
        combo.set(values[0] if values else "")
        return combo

    def _filter_entry(self, parent, label: str, placeholder: str = "", width: int = 100) -> ctk.CTkEntry:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(
            frame, text=label,
            font=ctk.CTkFont(size=11, weight="bold"), text_color=_TEXT2,
        ).pack(anchor="w")

        entry = ctk.CTkEntry(
            frame, width=width, height=30,
            font=ctk.CTkFont(size=11),
            fg_color=_CARD2, text_color=_TEXT,
            border_color=_BORDER, corner_radius=6,
            placeholder_text=placeholder, placeholder_text_color="#64748B",
        )
        entry.pack()
        return entry

    # ═══════════════════════════════════════════════════════════════════════
    # FILTER LOGIC
    # ═══════════════════════════════════════════════════════════════════════

    def _collect_filters(self) -> dict:
        """Read all filter widgets and return kwargs for query_posts_filtered."""
        page = self._f_page.get()
        group = self._f_group.get()
        ptype = self._f_type.get()
        date_from = self._f_date_from.get().strip()
        date_to = self._f_date_to.get().strip()

        try:
            min_eng = int(self._f_engage.get().strip())
        except (ValueError, TypeError):
            min_eng = 0
        try:
            min_views = int(self._f_views.get().strip())
        except (ValueError, TypeError):
            min_views = 0

        keyword = self._f_keyword.get().strip()

        dl_raw = self._f_dl_status.get()
        dl_map = {"Tất cả": "", "Đã tải": "downloaded", "Chưa tải": "not_downloaded"}
        dl_status = dl_map.get(dl_raw, "")

        return {
            "page_name": "" if page == "Tất cả" else page,
            "group_name": "" if group == "Tất cả" else group,
            "post_type": "" if ptype == "Tất cả" else ptype,
            "date_from": date_from,
            "date_to": date_to,
            "min_engagement": min_eng,
            "min_views": min_views,
            "keyword": keyword,
            "download_status": dl_status,
        }

    def _build_filter_context(self, filters: dict) -> str:
        """Build a short context string for file naming."""
        parts = []
        if filters["page_name"]:
            parts.append(filters["page_name"][:15])
        if filters["group_name"]:
            parts.append(f"G-{filters['group_name'][:10]}")
        if filters["post_type"]:
            parts.append(filters["post_type"])
        if filters["keyword"]:
            parts.append(f"kw-{filters['keyword'][:10]}")
        if not parts:
            parts.append("All")
        # Sanitize for filename
        ctx = "_".join(parts)
        return "".join(c if c.isalnum() or c in "_-" else "_" for c in ctx)

    def _reset_filters(self):
        """Reset all filter widgets to default."""
        self._f_page.set("Tất cả")
        self._f_group.set("Tất cả")
        self._f_type.set("Tất cả")
        self._f_date_from.delete(0, "end")
        self._f_date_to.delete(0, "end")
        self._f_engage.delete(0, "end")
        self._f_views.delete(0, "end")
        self._f_keyword.delete(0, "end")
        self._f_dl_status.set("Tất cả")
        self._filter_stats.configure(text="")
        self._set_status("Đã reset bộ lọc", _TEXT2)

    # ═══════════════════════════════════════════════════════════════════════
    # EXPORT (Background Thread)
    # ═══════════════════════════════════════════════════════════════════════

    def _on_export(self):
        """Start export in background thread."""
        self._export_btn.configure(state="disabled", text="⏳ Đang export...")
        self._action_frame.pack_forget()
        self._progress.set(0)
        self._set_status("Đang truy vấn database...", _YELLOW)

        filters = self._collect_filters()
        thread = threading.Thread(target=self._export_thread, args=(filters,), daemon=True)
        thread.start()

    def _export_thread(self, filters: dict):
        """Run export in background."""
        try:
            import pandas as pd
            from openpyxl.styles import Font, PatternFill, Alignment
            from openpyxl.utils import get_column_letter

            db_path = get_db_path(config.get("scraper_db_path", ""))
            self.after(0, self._progress.set, 0.1)

            # Query
            rows = query_posts_filtered(db_path, **filters)
            count = len(rows)
            self.after(0, self._set_status, f"Tìm thấy {count:,} bài viết, đang xuất Excel...", _ACCENT)
            self.after(0, self._progress.set, 0.3)

            if count == 0:
                self.after(0, self._export_done, False, "Không tìm thấy bài viết nào phù hợp với bộ lọc.")
                return

            # Build DataFrame — full schema, post_id as Column A
            df = pd.DataFrame(rows)
            # Reorder: post_id first, then rest
            col_order = ["post_id"]
            for c in df.columns:
                if c != "post_id":
                    col_order.append(c)
            df = df[col_order]

            self.after(0, self._progress.set, 0.5)

            # File path
            ctx = self._build_filter_context(filters)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"Report_{ctx}_{ts}.xlsx"
            output_dir = config.get("output_dir", ".")
            os.makedirs(output_dir, exist_ok=True)
            filepath = os.path.join(output_dir, filename)

            # Write with pandas + openpyxl
            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Posts")
                ws = writer.sheets["Posts"]

                # Styling
                header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
                header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")

                for col_idx in range(1, len(df.columns) + 1):
                    cell = ws.cell(row=1, column=col_idx)
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = Alignment(horizontal="center", vertical="center")

                    # Auto-fit width
                    col_letter = get_column_letter(col_idx)
                    col_name = df.columns[col_idx - 1]
                    max_len = max(len(str(col_name)), 8)

                    # Sample first 50 rows for width estimation
                    for row_val in df.iloc[:50, col_idx - 1]:
                        val_len = len(str(row_val)) if row_val else 0
                        max_len = max(max_len, min(val_len, 60))

                    ws.column_dimensions[col_letter].width = max_len + 3

                # Freeze top row
                ws.freeze_panes = "A2"

                # Auto-filter
                ws.auto_filter.ref = f"A1:{get_column_letter(len(df.columns))}{len(df) + 1}"

            self.after(0, self._progress.set, 1.0)
            self._export_path = filepath
            self.after(0, self._export_done, True,
                       f"✅ Đã xuất {count:,} bài → {filename}")

        except PermissionError:
            self.after(0, self._export_done, False,
                       "❌ Không thể ghi file — file Excel đang được mở!")
        except Exception as e:
            self.after(0, self._export_done, False, f"❌ Lỗi: {str(e)[:200]}")

    def _export_done(self, success: bool, message: str):
        """Called on main thread when export finishes."""
        self._export_btn.configure(state="normal", text="📊  EXPORT TO EXCEL")

        if success:
            self._set_status(message, _GREEN)
            self._filter_stats.configure(text=message)
            # Show action buttons
            self._action_frame.pack(side="right", padx=12)
            # Auto-open file
            if self._export_path and os.path.exists(self._export_path):
                os.startfile(self._export_path)
        else:
            self._set_status(message, _RED)
            self._filter_stats.configure(text=message)
            self._progress.set(0)

    def _open_export_file(self):
        if self._export_path and os.path.exists(self._export_path):
            os.startfile(self._export_path)

    def _open_export_folder(self):
        if self._export_path and os.path.exists(self._export_path):
            folder = os.path.dirname(self._export_path)
            os.startfile(folder)

    # ═══════════════════════════════════════════════════════════════════════
    # BULK DELETE (Background Thread)
    # ═══════════════════════════════════════════════════════════════════════

    def _parse_post_ids(self) -> list:
        """Parse post_ids from textbox (one per line, skip blanks)."""
        raw = self._del_textbox.get("1.0", "end").strip()
        if not raw:
            return []
        ids = []
        for line in raw.splitlines():
            pid = line.strip()
            if pid:
                ids.append(pid)
        return list(dict.fromkeys(ids))  # dedupe, preserve order

    def _update_id_count(self, event=None):
        ids = self._parse_post_ids()
        self._del_count.configure(text=f"{len(ids)} IDs")

    def _on_delete(self):
        """Start bulk deletion after confirmation."""
        ids = self._parse_post_ids()
        if not ids:
            messagebox.showwarning("Tinix", "Vui lòng nhập ít nhất 1 post_id!")
            return

        confirmed = messagebox.askyesno(
            "⚠ Xác nhận xóa vĩnh viễn",
            f"Bạn có chắc muốn XÓA VĨNH VIỄN {len(ids)} bài viết và media đi kèm?\n\n"
            f"Hành động này KHÔNG THỂ hoàn tác!",
            icon="warning",
        )
        if not confirmed:
            return

        self._del_btn.configure(state="disabled", text="⏳ Đang xóa...")
        self._progress.set(0)
        self._set_status(f"Đang xóa {len(ids)} bài viết...", _YELLOW)

        thread = threading.Thread(target=self._delete_thread, args=(ids,), daemon=True)
        thread.start()

    def _delete_thread(self, post_ids: list):
        """Run deletion in background."""
        try:
            db_path = get_db_path(config.get("scraper_db_path", ""))
            total = len(post_ids)

            self.after(0, self._progress.set, 0.2)

            # Step 1: Delete from DB and get media paths
            result = bulk_delete_posts(db_path, post_ids)
            deleted = result["deleted"]
            media_paths = result["paths"]

            self.after(0, self._progress.set, 0.5)

            # Step 2: Delete physical media files
            files_deleted = 0
            files_failed = 0
            for i, path in enumerate(media_paths):
                try:
                    if os.path.exists(path):
                        if os.path.isdir(path):
                            import shutil
                            shutil.rmtree(path, ignore_errors=True)
                        else:
                            os.remove(path)
                        files_deleted += 1
                except (PermissionError, FileNotFoundError):
                    files_failed += 1
                except Exception:
                    files_failed += 1

                # Update progress
                if media_paths:
                    frac = 0.5 + 0.5 * (i + 1) / len(media_paths)
                    self.after(0, self._progress.set, frac)

            self.after(0, self._progress.set, 1.0)

            msg = (
                f"✅ Đã xóa {deleted}/{total} bài viết từ database.\n"
                f"   📁 Files xóa: {files_deleted}"
            )
            if files_failed:
                msg += f" | ⚠ Thất bại: {files_failed}"

            self.after(0, self._delete_done, True, msg)

        except Exception as e:
            self.after(0, self._delete_done, False, f"❌ Lỗi: {str(e)[:200]}")

    def _delete_done(self, success: bool, message: str):
        """Called on main thread when deletion finishes."""
        self._del_btn.configure(state="normal", text="🗑  PERMANENT DELETE")

        if success:
            self._set_status(message.split("\n")[0], _GREEN)
            self._del_textbox.delete("1.0", "end")
            self._del_count.configure(text="0 IDs")
        else:
            self._set_status(message, _RED)

        logger.info(message)

    # ═══════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════════════

    def _set_status(self, text: str, color: str = _TEXT2):
        self._status_label.configure(text=text, text_color=color)
