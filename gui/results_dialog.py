"""
Tinix Facebook Down — Scrape Results Dialog
Popup table with pagination showing scraped post data.
"""

import webbrowser
import customtkinter as ctk
from typing import Callable, Dict, List, Optional

from core.page_scraper import ScrapedPost


class ScrapeResultsDialog(ctk.CTkToplevel):
    """Popup showing scraped results in a paginated table."""

    PAGE_SIZE_DEFAULT = 30

    def __init__(
        self,
        master,
        results: Dict[str, List[ScrapedPost]],
        on_download: Optional[Callable] = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self._results = results
        self._on_download = on_download
        self._all_posts = []
        self._current_page = 0
        self._page_size = self.PAGE_SIZE_DEFAULT

        # Flatten
        for page_name, posts in results.items():
            for post in posts:
                self._all_posts.append((page_name, post))

        self._total_pages = max(1, (len(self._all_posts) + self._page_size - 1) // self._page_size)

        self.title(f"📊 Kết quả quét — {len(self._all_posts)} bài viết")
        self.geometry("900x660")
        self.minsize(800, 500)
        self.transient(master)

        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - 900) // 2
        y = (sh - 660) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")

        self._setup_ui()

    def _setup_ui(self):
        main = ctk.CTkFrame(self, fg_color="#F5F5F7", corner_radius=0)
        main.pack(fill="both", expand=True)

        # ===== Header =====
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            header,
            text=f"📊 {len(self._all_posts)} bài viết từ {len(self._results)} page",
            font=ctk.CTkFont(size=16, weight="bold"), text_color="#1E293B",
        ).pack(side="left")

        # Right buttons
        ctk.CTkButton(
            header, text="✕ Đóng", width=70, height=30,
            font=ctk.CTkFont(size=11), fg_color="#F1F5F9",
            text_color="#475569", hover_color="#E2E8F0",
            corner_radius=6, command=self.destroy,
        ).pack(side="right", padx=(4, 0))

        # Download All
        media_posts = [p for _, p in self._all_posts if p.url and p.post_type in ("Ảnh", "Video")]
        if media_posts and self._on_download:
            ctk.CTkButton(
                header,
                text=f"⬇ Tải All ({len(media_posts)})",
                width=140, height=30,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#16A34A", hover_color="#15803D",
                corner_radius=6,
                command=lambda: self._download_all(media_posts),
            ).pack(side="right", padx=(4, 0))

        # ===== Table Header =====
        table_header = ctk.CTkFrame(main, fg_color="#1E293B", corner_radius=8, height=36)
        table_header.pack(fill="x", padx=16, pady=(0, 0))
        table_header.pack_propagate(False)

        columns = [
            ("STT", 44),
            ("Page", 90),
            ("Ngày", 78),
            ("Loại", 48),
            ("Engage", 65),
            ("B.luận", 55),
            ("Xem", 60),
        ]

        for col_name, col_width in columns:
            ctk.CTkLabel(
                table_header, text=col_name, width=col_width,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#FFFFFF", anchor="w",
            ).pack(side="left", padx=3, pady=6)

        # Caption header — expands to fill remaining space
        ctk.CTkLabel(
            table_header, text="Caption",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#FFFFFF", anchor="w",
        ).pack(side="left", padx=3, pady=6, fill="x", expand=True)

        # ===== Table Body =====
        self._table_body = ctk.CTkScrollableFrame(
            main, fg_color="#FFFFFF", corner_radius=0,
        )
        self._table_body.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        # ===== Pagination Footer =====
        footer = ctk.CTkFrame(main, fg_color="transparent", height=40)
        footer.pack(fill="x", padx=16, pady=(4, 10))

        # Left: page size control
        size_frame = ctk.CTkFrame(footer, fg_color="transparent")
        size_frame.pack(side="left")

        ctk.CTkLabel(
            size_frame, text="Hiển thị:", width=55,
            font=ctk.CTkFont(size=11), text_color="#64748B",
        ).pack(side="left")

        self._size_var = ctk.StringVar(value=str(self._page_size))
        size_entry = ctk.CTkEntry(
            size_frame, width=50, height=28, textvariable=self._size_var,
            font=ctk.CTkFont(size=11), fg_color="#F8FAFC",
            text_color="#334155", border_color="#E2E8F0",
            corner_radius=6, justify="center",
        )
        size_entry.pack(side="left", padx=4)
        size_entry.bind("<Return>", lambda e: self._change_page_size())

        ctk.CTkLabel(
            size_frame, text="dòng/trang",
            font=ctk.CTkFont(size=11), text_color="#64748B",
        ).pack(side="left")

        # Center: prev/next
        nav_frame = ctk.CTkFrame(footer, fg_color="transparent")
        nav_frame.pack(side="left", expand=True)

        self._prev_btn = ctk.CTkButton(
            nav_frame, text="◀ Trước", width=90, height=30,
            font=ctk.CTkFont(size=12), fg_color="#2563EB",
            hover_color="#1D4ED8", corner_radius=6,
            command=self._prev_page,
        )
        self._prev_btn.pack(side="left", padx=(0, 8))

        self._page_label = ctk.CTkLabel(
            nav_frame, text="",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#334155",
        )
        self._page_label.pack(side="left", padx=8)

        self._next_btn = ctk.CTkButton(
            nav_frame, text="Sau ▶", width=90, height=30,
            font=ctk.CTkFont(size=12), fg_color="#2563EB",
            hover_color="#1D4ED8", corner_radius=6,
            command=self._next_page,
        )
        self._next_btn.pack(side="left", padx=(8, 0))

        # Render first page
        self._render_page()

    # ===== Pagination =====

    def _recalc_pages(self):
        self._total_pages = max(1, (len(self._all_posts) + self._page_size - 1) // self._page_size)
        if self._current_page >= self._total_pages:
            self._current_page = self._total_pages - 1

    def _change_page_size(self):
        try:
            new_size = int(self._size_var.get().strip())
            if new_size < 1:
                new_size = 1
            if new_size > 500:
                new_size = 500
        except ValueError:
            return
        self._page_size = new_size
        self._current_page = 0
        self._recalc_pages()
        self._render_page()

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._render_page()

    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._render_page()

    def _render_page(self):
        """Render current page of results."""
        # Clear
        for w in self._table_body.winfo_children():
            w.destroy()

        start = self._current_page * self._page_size
        end = min(start + self._page_size, len(self._all_posts))
        page_posts = self._all_posts[start:end]

        # Update nav
        self._page_label.configure(
            text=f"Trang {self._current_page + 1} / {self._total_pages}  ({start+1}–{end} / {len(self._all_posts)})"
        )
        self._prev_btn.configure(state="normal" if self._current_page > 0 else "disabled")
        self._next_btn.configure(state="normal" if self._current_page < self._total_pages - 1 else "disabled")

        # Render rows
        for i, (page_name, post) in enumerate(page_posts):
            global_idx = start + i
            bg = "#F8FAFC" if global_idx % 2 == 0 else "#FFFFFF"
            row = ctk.CTkFrame(self._table_body, fg_color=bg, height=36, corner_radius=0)
            row.pack(fill="x", pady=0)
            row.pack_propagate(False)

            # STT
            ctk.CTkLabel(
                row, text=str(global_idx + 1), width=44,
                font=ctk.CTkFont(size=11), text_color="#64748B", anchor="w",
            ).pack(side="left", padx=3)

            # Page
            short_page = (page_name[:11] + "…") if len(page_name) > 12 else page_name
            ctk.CTkLabel(
                row, text=short_page, width=90,
                font=ctk.CTkFont(size=11), text_color="#334155", anchor="w",
            ).pack(side="left", padx=3)

            # Date
            ctk.CTkLabel(
                row, text=post.date or "—", width=78,
                font=ctk.CTkFont(size=11), text_color="#334155", anchor="w",
            ).pack(side="left", padx=3)

            # Type
            type_colors = {"Ảnh": "#2563EB", "Video": "#DC2626", "Text": "#64748B"}
            ctk.CTkLabel(
                row, text=post.post_type or "Text", width=48,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=type_colors.get(post.post_type, "#64748B"), anchor="w",
            ).pack(side="left", padx=3)

            # Engagement
            ctk.CTkLabel(
                row, text=f"{post.engagement:,}" if post.engagement else "0", width=65,
                font=ctk.CTkFont(size=11), text_color="#334155", anchor="w",
            ).pack(side="left", padx=3)

            # Comments
            ctk.CTkLabel(
                row, text=f"{post.comments:,}" if post.comments else "0", width=55,
                font=ctk.CTkFont(size=11), text_color="#334155", anchor="w",
            ).pack(side="left", padx=3)

            # Views
            ctk.CTkLabel(
                row, text=f"{post.views:,}" if post.views else "—", width=60,
                font=ctk.CTkFont(size=11), text_color="#334155", anchor="w",
            ).pack(side="left", padx=3)

            # Caption (first 8 words) — expands to fill remaining space
            caption_text = post.caption or ""
            words = caption_text.split()
            short_caption = " ".join(words[:8])
            if len(words) > 8:
                short_caption += "…"
            if not short_caption:
                short_caption = "—"
            ctk.CTkLabel(
                row, text=short_caption,
                font=ctk.CTkFont(size=11), text_color="#475569", anchor="w",
            ).pack(side="left", padx=3, fill="x", expand=True)

            # Action buttons — ALWAYS visible at the end
            action_frame = ctk.CTkFrame(row, fg_color="transparent")
            action_frame.pack(side="right", padx=(3, 6))

            post_url = post.url or ""

            if post_url and post.post_type in ("Ảnh", "Video") and self._on_download:
                ctk.CTkButton(
                    action_frame, text="⬇", width=30, height=26,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    fg_color="#16A34A", text_color="#FFF",
                    hover_color="#15803D", corner_radius=5,
                    command=lambda url=post_url: self._on_download([url]),
                ).pack(side="right", padx=(3, 0))

            if post_url:
                ctk.CTkButton(
                    action_frame, text="🔗", width=30, height=26,
                    font=ctk.CTkFont(size=10),
                    fg_color="#2563EB", text_color="#FFF",
                    hover_color="#1D4ED8", corner_radius=5,
                    command=lambda url=post_url: webbrowser.open(url),
                ).pack(side="right", padx=(0, 0))

    def _download_all(self, posts):
        """Download all media posts."""
        urls = [p.url for p in posts if p.url]
        if urls and self._on_download:
            self._on_download(urls)
