"""
Tinix Facebook Down — Video Post Tab
Inherits all scheduling/execution logic from SocialPostTab,
overrides treeview columns (Tiêu Đề | Nội Dung | Từ Khóa | Media | Status)
and Excel template/import to handle the 5-column video format.
"""

from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk

from core.content_scanner import scan_main_folder, count_media_in_folder, load_post_excel
from core.db_storage import get_db_path, save_content_pool
from gui.social_post_tab import (
    SocialPostTab,
    _CARD, _CARD2, _BORDER, _TEXT, _TEXT2, _GREEN, _RED,
)
from utils import config

_ACCENT_VIDEO = "#7C3AED"   # Purple accent for video tab


class VideoPostTab(SocialPostTab):
    """Video Post tab — same scheduling/execution engine as SocialPostTab,
    but with a 7-column treeview (# | Folder | Tiêu Đề | Nội Dung | Từ Khóa | Media | Status)
    and a 5-column Excel import (Số thứ tự, Folder Name, Tiêu Đề, Nội Dung, Từ Khóa).
    """

    _ACCENT = _ACCENT_VIDEO

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        try:
            self._progress.configure(progress_color=_ACCENT_VIDEO)
        except Exception:
            pass

    # ── Override: 7-column treeview ───────────────────────────────────────────

    def _build_treeview(self, parent):
        """Replace the base 5-column treeview with a 7-column video treeview."""
        card = ctk.CTkFrame(parent, fg_color=_CARD, corner_radius=10,
                            border_width=1, border_color=_BORDER)
        card.pack(fill="both", expand=True, pady=(0, 0))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("VideoPost.Treeview",
            background="#1E293B", foreground="#F1F5F9",
            fieldbackground="#1E293B", borderwidth=0,
            font=("Consolas", 10), rowheight=26,
        )
        style.configure("VideoPost.Treeview.Heading",
            background="#334155", foreground="#F1F5F9",
            font=("Arial", 10, "bold"), borderwidth=0,
        )
        style.map("VideoPost.Treeview",
            background=[("selected", _ACCENT_VIDEO)],
            foreground=[("selected", "#FFFFFF")],
        )
        style.map("VideoPost.Treeview.Heading",
            background=[("active", "#475569")],
        )

        columns = ("id", "folder", "title", "content", "keywords", "media", "status")
        tree_frame = ctk.CTkFrame(card, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True, padx=8, pady=8)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        self._tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            style="VideoPost.Treeview", selectmode="extended",
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=self._tree.yview)

        self._tree.heading("id",       text="#")
        self._tree.heading("folder",   text="📁 Folder")
        self._tree.heading("title",    text="📌 Tiêu Đề")
        self._tree.heading("content",  text="📝 Nội Dung")
        self._tree.heading("keywords", text="🔑 Từ Khóa")
        self._tree.heading("media",    text="🎬 Media")
        self._tree.heading("status",   text="📊 Status")

        self._tree.column("id",       width=35,  minwidth=30,  anchor="center")
        self._tree.column("folder",   width=110, minwidth=70)
        self._tree.column("title",    width=130, minwidth=80)
        self._tree.column("content",  width=160, minwidth=100)
        self._tree.column("keywords", width=110, minwidth=70)
        self._tree.column("media",    width=75,  minwidth=55, anchor="center")
        self._tree.column("status",   width=130, minwidth=80)

        self._tree.pack(fill="both", expand=True)
        self._tree.tag_configure("odd",  background="#1E293B")
        self._tree.tag_configure("even", background="#243044")
        self._tree.bind("<Double-1>", self._on_tree_double_click)

        # ── Pagination bar (same widget names as base class) ──
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

    # ── Override: render rows using title/content/keywords ────────────────────

    def _render_page(self):
        """Render the current page with 7-column video layout."""
        for child in self._tree.get_children():
            self._tree.delete(child)

        filtered = self._filtered_items
        total_rows = len(filtered)

        size_str = self._page_size_var.get()
        page_size = total_rows or 1 if size_str == "Tất cả" else int(size_str)

        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        self._current_page = max(0, min(self._current_page, total_pages - 1))

        start = self._current_page * page_size
        end = min(start + page_size, total_rows)
        page_items = filtered[start:end]

        for idx, item in enumerate(page_items):
            title = item.get("title", "")
            title_snip = (title[:36] + "…") if len(title) > 36 else title

            content = item.get("caption", "")
            content_snip = (content[:46] + "…") if len(content) > 46 else content

            keywords = item.get("keywords", "")
            kw_snip = (keywords[:36] + "…") if len(keywords) > 36 else keywords

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
                title_snip,
                content_snip,
                kw_snip,
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

    # ── Override: filter also searches title/keywords ─────────────────────────

    def _filter_items(self, items):
        q = self._search_var.get().strip().lower() if hasattr(self, "_search_var") else ""
        if not q:
            return items
        result = []
        for it in items:
            haystack = " ".join([
                it.get("folder_name", ""),
                it.get("title", ""),
                it.get("caption", ""),
                it.get("keywords", ""),
            ]).lower()
            if q in haystack:
                result.append(it)
        return result

    # ── Override: template Excel 5 cột cho video ─────────────────────────────

    def _on_download_template(self):
        filepath = filedialog.asksaveasfilename(
            title="Lưu Video Post Template",
            defaultextension=".xlsx",
            initialfile="Video_Post_Template.xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not filepath:
            return

        try:
            import pandas as pd
            df = pd.DataFrame({
                "Số thứ tự": [1, 2, 3],
                "Folder Name": [
                    "Video_Gioi_Thieu_01",
                    "Video_San_Pham_02",
                    "Video_Review_03",
                ],
                "Tiêu Đề": [
                    "Video giới thiệu thương hiệu",
                    "Giới thiệu sản phẩm mới",
                    "Review chi tiết sản phẩm",
                ],
                "Nội Dung": [
                    "Chào mừng bạn đến với kênh của chúng tôi! Hãy theo dõi để không bỏ lỡ video mới 🎬",
                    "Sản phẩm mới đã ra mắt! Đặt hàng ngay hôm nay để nhận ưu đãi đặc biệt 🛍️",
                    "Đánh giá chi tiết về chất lượng, tính năng và trải nghiệm sử dụng thực tế 👍",
                ],
                "Từ Khóa": [
                    "giới thiệu; thương hiệu; video",
                    "sản phẩm mới; mua sắm; ưu đãi",
                    "review; đánh giá; chất lượng",
                ],
            })

            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="Template")
                ws = writer.sheets["Template"]
                ws.column_dimensions["A"].width = 12
                ws.column_dimensions["B"].width = 30
                ws.column_dimensions["C"].width = 35
                ws.column_dimensions["D"].width = 55
                ws.column_dimensions["E"].width = 35

            messagebox.showinfo(
                "Tinix",
                "✅ Template saved!\n\n"
                "Điền Folder Name (khớp tên subfolder), Tiêu Đề, Nội Dung, Từ Khóa,\n"
                "rồi dùng nút Import để nạp nội dung video.",
            )
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể tạo template:\n{str(e)[:200]}")

    # ── Override: import merges folder scan + Excel 5 cột ────────────────────

    def _import_thread(self, main_folder: str, excel_path: str):
        try:
            # 1. Scan subfolders
            folder_items = scan_main_folder(main_folder)
            if not folder_items:
                self.after(0, self._import_done, 0, "Không tìm thấy folder nào!")
                return

            # 2. Load Excel (5-column video format)
            excel_map = {}
            if excel_path:
                try:
                    rows = load_post_excel(excel_path)
                    for row in rows:
                        fn = str(row.get("Folder Name", "")).strip()
                        if fn:
                            excel_map[fn] = row
                except Exception as e:
                    self.after(0, self._set_status,
                               f"⚠ Excel lỗi: {str(e)[:80]}", "#F59E0B")

            # 3. Merge folder data with Excel metadata
            total = len(folder_items)
            merged = []
            for i, item in enumerate(folder_items):
                fn = item["folder_name"]
                ex = excel_map.get(fn, {})

                # Nội Dung → caption (primary post content)
                caption = str(ex.get("Nội Dung", "")).strip()
                if not caption:
                    caption = item.get("caption", "")  # fallback: .txt file in folder

                merged.append({
                    "folder_name": fn,
                    "folder_path": item["folder_path"],
                    "caption": caption,
                    "title": str(ex.get("Tiêu Đề", "")).strip(),
                    "keywords": str(ex.get("Từ Khóa", "")).strip(),
                })

                # Update progress
                if total > 0:
                    self.after(0, self._progress.set, (i + 1) / total)
                    self.after(0, self._set_status,
                               f"[{i + 1}/{total}] {fn}", _ACCENT_VIDEO)

            # 4. Save to DB
            db_path = get_db_path(config.get("scraper_db_path", ""))
            saved = save_content_pool(db_path, merged)
            self.after(0, self._progress.set, 1.0)
            self.after(0, self._import_done, saved, f"✅ Imported {saved} folders")

        except Exception as e:
            self.after(0, self._import_done, 0, f"❌ {str(e)[:200]}")

    # ── Override: double-click opens editor on columns 3, 4, or 5 ────────────

    def _on_tree_double_click(self, event):
        """Open video content editor on double-click of Tiêu Đề/Nội Dung/Từ Khóa columns."""
        region = self._tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self._tree.identify_column(event.x)
        # #3=title, #4=content, #5=keywords
        if col not in ("#3", "#4", "#5"):
            return
        item_id = self._tree.identify_row(event.y)
        if not item_id:
            return

        content_id = None
        for tag in self._tree.item(item_id, "tags"):
            if tag.startswith("cid_"):
                content_id = int(tag[4:])
                break
        if content_id is None:
            return

        item_data = next((it for it in self._all_items if it["content_id"] == content_id), None)
        if not item_data:
            return

        self._show_video_editor(content_id, item_data)

    def _show_video_editor(self, content_id: int, item_data: dict):
        """Modal dialog to edit Tiêu Đề, Nội Dung, Từ Khóa for a video item."""
        folder_name = item_data["folder_name"]
        dlg = ctk.CTkToplevel(self)
        dlg.title(f"Sửa nội dung video — {folder_name}")
        dlg.resizable(True, True)
        dlg.grab_set()
        dlg.configure(fg_color=_CARD)
        w, h = 580, 400
        px = self.winfo_rootx() + self.winfo_width() // 2 - w // 2
        py = self.winfo_rooty() + self.winfo_height() // 2 - h // 2
        dlg.geometry(f"{w}x{h}+{px}+{py}")

        ctk.CTkLabel(
            dlg, text=f"📁 {folder_name}",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=_TEXT,
        ).pack(anchor="w", padx=16, pady=(14, 6))

        # Tiêu Đề
        ctk.CTkLabel(dlg, text="📌 Tiêu Đề:", font=ctk.CTkFont(size=11),
                     text_color=_TEXT2).pack(anchor="w", padx=16)
        title_entry = ctk.CTkEntry(
            dlg, font=ctk.CTkFont(size=11), height=32,
            fg_color=_CARD2, text_color=_TEXT, border_color=_BORDER, border_width=1,
        )
        title_entry.pack(fill="x", padx=16, pady=(2, 8))
        title_entry.insert(0, item_data.get("title", ""))

        # Nội Dung
        ctk.CTkLabel(dlg, text="📝 Nội Dung:", font=ctk.CTkFont(size=11),
                     text_color=_TEXT2).pack(anchor="w", padx=16)
        content_txt = ctk.CTkTextbox(
            dlg, height=100, font=ctk.CTkFont(size=11),
            fg_color=_CARD2, text_color=_TEXT, border_color=_BORDER, border_width=1,
        )
        content_txt.pack(fill="x", padx=16, pady=(2, 8))
        content_txt.insert("1.0", item_data.get("caption", ""))

        # Từ Khóa
        ctk.CTkLabel(dlg, text="🔑 Từ Khóa:", font=ctk.CTkFont(size=11),
                     text_color=_TEXT2).pack(anchor="w", padx=16)
        keywords_entry = ctk.CTkEntry(
            dlg, font=ctk.CTkFont(size=11), height=32,
            fg_color=_CARD2, text_color=_TEXT, border_color=_BORDER, border_width=1,
        )
        keywords_entry.pack(fill="x", padx=16, pady=(2, 8))
        keywords_entry.insert(0, item_data.get("keywords", ""))

        status_lbl = ctk.CTkLabel(dlg, text="", font=ctk.CTkFont(size=10), text_color=_TEXT2)
        status_lbl.pack(anchor="w", padx=16)

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(6, 14))

        def _save():
            new_title    = title_entry.get().strip()
            new_caption  = content_txt.get("1.0", "end").rstrip("\n")
            new_keywords = keywords_entry.get().strip()

            db_path = get_db_path(config.get("scraper_db_path", ""))
            ok = False
            try:
                import sqlite3
                conn = sqlite3.connect(db_path)
                conn.execute(
                    "UPDATE content_pool SET caption=?, title=?, keywords=? WHERE content_id=?",
                    (new_caption, new_title, new_keywords, content_id),
                )
                conn.commit()
                conn.close()
                ok = True
            except Exception as e:
                status_lbl.configure(text=f"❌ {str(e)[:80]}", text_color=_RED)

            if ok:
                self._refresh_treeview()
                self._set_status("✅ Đã lưu Tiêu Đề / Nội Dung / Từ Khóa", _GREEN)
                dlg.destroy()

        ctk.CTkButton(
            btn_row, text="✓ Lưu", width=100, height=32,
            fg_color=_ACCENT_VIDEO, hover_color="#6D28D9",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#FFFFFF",
            command=_save,
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            btn_row, text="Hủy", width=80, height=32,
            fg_color=_CARD2, hover_color=_BORDER, text_color=_TEXT,
            font=ctk.CTkFont(size=12),
            command=dlg.destroy,
        ).pack(side="right")
