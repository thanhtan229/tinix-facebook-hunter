"""
Tinix Facebook Down — Account Manager Dialog
CRUD + Bulk Import + Check Live for Facebook accounts.
Page & Group Management with avatar support (Tab 2).
"""

import threading
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, List, Optional

import customtkinter as ctk

from core.db_storage import (
    get_db_path, get_all_accounts, get_all_proxies,
    add_account, update_account, delete_account,
    save_managed_pages, delete_managed_pages, delete_managed_page,
    get_page_groups, add_page_group, delete_page_group,
    move_pages_to_group, update_page_avatar,
    get_all_managed_pages, save_business_id,
)
from utils import config, logger


# ─── Avatar helpers ───────────────────────────────────────────────────────────

_ASSETS_DIR = Path(__file__).parent.parent / "assets" / "avatars"
_DEFAULT_AVATAR = _ASSETS_DIR / "default.png"
_avatar_cache: dict = {}   # cache_key → PhotoImage (module-level prevents GC)


def _ensure_default_avatar():
    """Create a simple gray circle as the default avatar PNG if missing."""
    _ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if _DEFAULT_AVATAR.exists():
        return
    try:
        from PIL import Image, ImageDraw
        size = 32
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((0, 0, size - 1, size - 1), fill=(100, 116, 139))
        draw.ellipse((10, 5, 22, 17), fill=(226, 232, 240))   # head
        draw.ellipse((5, 18, 27, 36), fill=(226, 232, 240))   # body
        img.save(str(_DEFAULT_AVATAR))
    except Exception:
        pass


def _load_avatar_photo(path: str, size: int = 28):
    """Load an avatar as a circular PhotoImage. Returns None if PIL unavailable."""
    cache_key = f"{path}:{size}"
    if cache_key in _avatar_cache:
        return _avatar_cache[cache_key]
    try:
        from PIL import Image, ImageDraw, ImageTk
        src = path if (path and Path(path).exists()) else str(_DEFAULT_AVATAR)
        if not Path(src).exists():
            return None
        img = Image.open(src).convert("RGBA").resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(img, mask=mask)
        photo = ImageTk.PhotoImage(out)
        _avatar_cache[cache_key] = photo
        return photo
    except Exception:
        return None


def _download_avatar(avatar_url: str, page_id: str) -> str:
    """Download avatar to assets/avatars/{page_id}.png. Returns local path or ''."""
    if not avatar_url:
        return ""
    _ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _ASSETS_DIR / f"{page_id}.png"
    try:
        import io
        import urllib.request
        req = urllib.request.Request(
            avatar_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(data)).convert("RGBA")
            img.save(str(out_path), "PNG")
        except Exception:
            out_path.write_bytes(data)
        return str(out_path)
    except Exception as e:
        logger.debug(f"Avatar download failed for {page_id}: {e}")
        return ""


# ─── parse_account_lines ─────────────────────────────────────────────────────

def parse_account_lines(text: str) -> list:
    """
    Parse bulk account import text. Each line is one account.
    Supported formats:
        COOKIE
        ID|PASSWORD
        ID|PASSWORD|2FA
        ID|PASSWORD|2FA|EMAIL
        ID|PASSWORD|2FA|EMAIL|PASS_MAIL
        ID|PASSWORD|2FA|EMAIL|PASS_MAIL|COOKIE
    """
    results = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) == 1:
            val = parts[0].strip()
            if "=" in val or ";" in val:
                results.append({"cookie": val})
            else:
                results.append({"username": val})
        elif len(parts) == 2:
            results.append({"username": parts[0].strip(), "password": parts[1].strip()})
        elif len(parts) == 3:
            results.append({"username": parts[0].strip(), "password": parts[1].strip(),
                             "secret_2fa": parts[2].strip()})
        elif len(parts) == 4:
            results.append({"username": parts[0].strip(), "password": parts[1].strip(),
                             "secret_2fa": parts[2].strip(), "email": parts[3].strip()})
        elif len(parts) == 5:
            results.append({"username": parts[0].strip(), "password": parts[1].strip(),
                             "secret_2fa": parts[2].strip(), "email": parts[3].strip(),
                             "email_pass": parts[4].strip()})
        elif len(parts) >= 6:
            results.append({"username": parts[0].strip(), "password": parts[1].strip(),
                             "secret_2fa": parts[2].strip(), "email": parts[3].strip(),
                             "email_pass": parts[4].strip(), "cookie": parts[5].strip()})
    return results


# ─── BulkImportDialog ────────────────────────────────────────────────────────

class BulkImportDialog(ctk.CTkToplevel):
    """Dialog for bulk importing accounts."""

    def __init__(self, master, on_import: Callable, **kwargs):
        super().__init__(master, **kwargs)
        self._on_import = on_import
        self.title("📥 Import tài khoản hàng loạt")
        self.geometry("550x420")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.update_idletasks()
        x = master.winfo_x() + (master.winfo_width() - 550) // 2
        y = master.winfo_y() + (master.winfo_height() - 420) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")

        main = ctk.CTkFrame(self, fg_color="#F5F5F7", corner_radius=0)
        main.pack(fill="both", expand=True)

        ctk.CTkLabel(main, text="📥 Import tài khoản hàng loạt",
                      font=ctk.CTkFont(size=16, weight="bold"),
                      text_color="#1E293B").pack(padx=16, pady=(12, 4))
        ctk.CTkLabel(main, text=(
            "Mỗi dòng 1 tài khoản, hỗ trợ các định dạng:\n"
            "• COOKIE\n• ID|PASSWORD\n• ID|PASSWORD|2FA\n"
            "• ID|PASSWORD|2FA|EMAIL\n• ID|PASSWORD|2FA|EMAIL|PASS_MAIL\n"
            "• ID|PASSWORD|2FA|EMAIL|PASS_MAIL|COOKIE"),
            font=ctk.CTkFont(size=11), text_color="#64748B", justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 6))

        self._textbox = ctk.CTkTextbox(
            main, height=180, font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#FFF", text_color="#334155",
            corner_radius=8, border_width=1, border_color="#E2E8F0")
        self._textbox.pack(fill="x", padx=16, pady=(0, 8))

        btn_row = ctk.CTkFrame(main, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 8))
        self._result_label = ctk.CTkLabel(btn_row, text="",
                                           font=ctk.CTkFont(size=11), text_color="#94A3B8")
        self._result_label.pack(side="left")
        ctk.CTkButton(btn_row, text="📥 Import", width=120, height=32,
                       font=ctk.CTkFont(size=12, weight="bold"),
                       fg_color="#16A34A", hover_color="#15803D", corner_radius=8,
                       command=self._do_import).pack(side="right")
        ctk.CTkButton(btn_row, text="📋 Dán", width=70, height=32,
                       font=ctk.CTkFont(size=11), fg_color="#F1F5F9", text_color="#475569",
                       hover_color="#E2E8F0", corner_radius=6,
                       command=self._paste).pack(side="right", padx=(0, 6))

    def _paste(self):
        try:
            text = self.clipboard_get()
            if text:
                self._textbox.delete("1.0", "end")
                self._textbox.insert("1.0", text.strip())
        except Exception:
            pass

    def _do_import(self):
        text = self._textbox.get("1.0", "end").strip()
        if not text:
            self._result_label.configure(text="⚠ Chưa nhập dữ liệu!", text_color="#D97706")
            return
        accounts = parse_account_lines(text)
        if not accounts:
            self._result_label.configure(text="❌ Không parse được!", text_color="#DC2626")
            return
        count = self._on_import(accounts)
        self._result_label.configure(
            text=f"✅ Đã import {count}/{len(accounts)} tài khoản", text_color="#16A34A")


# ─── AccountManagerDialog ────────────────────────────────────────────────────

class AccountManagerDialog(ctk.CTkToplevel):
    """Dual-tab dialog: Account CRUD (Tab 1) + Page & Group Management (Tab 2)."""

    _BG     = "#F5F5F7"
    _CARD   = "#FFFFFF"
    _BORDER = "#E2E8F0"
    _TEXT   = "#1E293B"
    _TEXT2  = "#64748B"
    _ACCENT = "#2563EB"
    _GREEN  = "#16A34A"
    _RED    = "#DC2626"
    _TEAL   = "#0F766E"

    def __init__(self, master, on_change: Optional[Callable] = None, **kwargs):
        super().__init__(master, **kwargs)
        self._on_change = on_change

        # Account tab state
        self._selected_id: Optional[int] = None
        self._accounts: List[dict] = []
        self._proxies: List[dict] = []

        # Pages tab state
        self._groups: List[dict] = []
        self._all_pages: List[dict] = []
        self._selected_group_id: Optional[int] = None
        self._tree_images: List = []
        self._group_btn_refs: List = []

        self.title("👤 Quản lý tài khoản & Fanpage")
        self.geometry("960x740")
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()

        self.update_idletasks()
        x = master.winfo_x() + (master.winfo_width() - 960) // 2
        y = master.winfo_y() + (master.winfo_height() - 740) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

        _ensure_default_avatar()
        self._setup_ui()
        self._refresh_list()
        self.after(200, self._refresh_groups_and_pages)

    def _db(self) -> str:
        return get_db_path(config.get("scraper_db_path", ""))

    # ═══════════════════════════════════════════════════════════════════════
    # MAIN LAYOUT
    # ═══════════════════════════════════════════════════════════════════════

    def _setup_ui(self):
        main = ctk.CTkFrame(self, fg_color=self._BG, corner_radius=0)
        main.pack(fill="both", expand=True)

        ctk.CTkLabel(
            main, text="👤 Quản lý tài khoản & Fanpage",
            font=ctk.CTkFont(size=18, weight="bold"), text_color=self._TEXT,
        ).pack(padx=20, pady=(12, 4))

        tabs = ctk.CTkTabview(
            main, fg_color=self._CARD,
            segmented_button_fg_color="#E2E8F0",
            segmented_button_selected_color=self._ACCENT,
            segmented_button_selected_hover_color="#1D4ED8",
            segmented_button_unselected_color="#F1F5F9",
            segmented_button_unselected_hover_color="#E2E8F0",
            text_color=self._TEXT,
        )
        tabs.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        self._build_account_tab(tabs.add("👤 Tài khoản"))
        self._build_pages_tab(tabs.add("📄 Fanpage & Nhóm"))

        ctk.CTkButton(
            main, text="Đóng", width=80, height=30,
            font=ctk.CTkFont(size=12), fg_color="#F1F5F9",
            text_color="#475569", hover_color="#E2E8F0",
            corner_radius=8, command=self.destroy,
        ).pack(pady=(4, 10))

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 1 — ACCOUNT MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════

    def _build_account_tab(self, parent):
        main = ctk.CTkFrame(parent, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=4, pady=4)

        # ── Account list card ──
        list_card = ctk.CTkFrame(main, fg_color=self._CARD, corner_radius=10,
                                  border_width=1, border_color=self._BORDER)
        list_card.pack(fill="x", pady=(0, 6))

        import tkinter as tk
        _acct_outer = tk.Frame(list_card, bg=self._CARD, height=145)
        _acct_outer.pack(fill="x", padx=4, pady=4)
        _acct_outer.pack_propagate(False)

        _st = ttk.Style()
        try:
            _st.theme_use("clam")
        except Exception:
            pass
        _st.configure("Accounts.Treeview",
                       background=self._CARD, fieldbackground=self._CARD,
                       foreground=self._TEXT, rowheight=30, borderwidth=0,
                       font=("Segoe UI", 10))
        _st.configure("Accounts.Treeview.Heading",
                       background="#F1F5F9", foreground="#334155",
                       font=("Segoe UI", 10, "bold"), relief="flat")
        _st.map("Accounts.Treeview",
                background=[("selected", "#DBEAFE")],
                foreground=[("selected", "#1E40AF")])

        self._acct_tree = ttk.Treeview(
            _acct_outer, columns=("status", "name"),
            show="headings", style="Accounts.Treeview", selectmode="browse")
        self._acct_tree.heading("status", text="Trạng thái", anchor="w")
        self._acct_tree.heading("name",   text="Tài khoản",   anchor="w")
        self._acct_tree.column("status", width=80,  minwidth=60,  stretch=False)
        self._acct_tree.column("name",   width=340, minwidth=150, stretch=True)

        _acct_vsb = ttk.Scrollbar(_acct_outer, orient="vertical",
                                   command=self._acct_tree.yview)
        self._acct_tree.configure(yscrollcommand=_acct_vsb.set)
        _acct_vsb.pack(side="right", fill="y")
        self._acct_tree.pack(side="left", fill="both", expand=True)
        self._acct_tree.bind("<<TreeviewSelect>>", self._on_acct_tree_select)

        btn_row = ctk.CTkFrame(list_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 8))
        for text, color, cmd in [
            ("📥 Import",     "#2563EB", self._open_import),
            ("🔍 Check Live", "#7C3AED", self._check_live),
            ("🗑 Xóa",        "#DC2626", self._delete_account),
        ]:
            ctk.CTkButton(btn_row, text=text, width=95, height=28,
                           font=ctk.CTkFont(size=11), fg_color=color,
                           hover_color="#333", corner_radius=6,
                           command=cmd).pack(side="left", padx=(0, 4))

        # ── Detail form card ──
        form_card = ctk.CTkFrame(main, fg_color=self._CARD, corner_radius=10,
                                  border_width=1, border_color=self._BORDER)
        form_card.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(form_card, text="Chi tiết tài khoản",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      text_color="#334155").pack(anchor="w", padx=14, pady=(10, 4))

        self._entries: dict = {}
        form_inner = ctk.CTkFrame(form_card, fg_color="transparent")
        form_inner.pack(fill="x", padx=14, pady=(0, 6))

        for key, label, is_pass, hint in [
            ("label",      "Tên hiển thị",  False, "VD: Acc Chính"),
            ("username",   "📧 Username",   False, "Email hoặc SĐT"),
            ("password",   "🔒 Password",   True,  "Mật khẩu Facebook"),
            ("secret_2fa", "🔐 2FA Secret", False, "TOTP key (32 ký tự)"),
            ("email",      "📨 Email",      False, "Email khôi phục"),
            ("email_pass", "🔑 Email Pass", True,  "Mật khẩu email"),
            ("cookie",     "🍪 Cookie",     False, "c_user=xxx; xs=xxx; ..."),
        ]:
            row = ctk.CTkFrame(form_inner, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=11),
                          text_color=self._TEXT2, width=130, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(
                row, font=ctk.CTkFont(size=11), height=28,
                fg_color="#F8FAFC", text_color="#334155",
                border_color=self._BORDER, corner_radius=6,
                show="•" if is_pass else "", placeholder_text=hint)
            entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
            self._entries[key] = entry
            if is_pass:
                def _make_toggle(e=entry):
                    def _t():
                        e.configure(show="" if e.cget("show") == "•" else "•")
                    return _t
                ctk.CTkButton(row, text="👁", width=28, height=28,
                               font=ctk.CTkFont(size=12), fg_color="#F1F5F9",
                               text_color="#475569", hover_color="#E2E8F0",
                               corner_radius=6, command=_make_toggle(),
                               ).pack(side="right", padx=(4, 0))

        proxy_row = ctk.CTkFrame(form_inner, fg_color="transparent")
        proxy_row.pack(fill="x", pady=2)
        ctk.CTkLabel(proxy_row, text="🌐 Proxy", font=ctk.CTkFont(size=11),
                      text_color=self._TEXT2, width=130, anchor="w").pack(side="left")
        self._proxy_var = ctk.StringVar(value="Không có proxy")
        self._proxy_combo = ctk.CTkComboBox(
            proxy_row, variable=self._proxy_var, height=28,
            font=ctk.CTkFont(size=11), fg_color="#F8FAFC",
            border_color=self._BORDER, corner_radius=6, values=["Không có proxy"])
        self._proxy_combo.pack(side="left", fill="x", expand=True, padx=(4, 0))

        save_row = ctk.CTkFrame(form_card, fg_color="transparent")
        save_row.pack(fill="x", padx=14, pady=(4, 10))
        ctk.CTkButton(save_row, text="💾 Lưu", width=100, height=32,
                       font=ctk.CTkFont(size=12, weight="bold"),
                       fg_color=self._ACCENT, hover_color="#1D4ED8",
                       corner_radius=8, command=self._save_account).pack(side="right")
        self._status = ctk.CTkLabel(save_row, text="",
                                     font=ctk.CTkFont(size=11), text_color="#94A3B8")
        self._status.pack(side="left")

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 2 — PAGE & GROUP MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════

    def _build_pages_tab(self, parent):
        import tkinter as tk

        # ── Header: account selector + sync button + status ──
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", padx=4, pady=(8, 4))

        ctk.CTkLabel(hdr, text="Sync cho account:",
                      font=ctk.CTkFont(size=11), text_color=self._TEXT2).pack(side="left")
        self._sync_account_var = ctk.StringVar()
        self._sync_account_combo = ctk.CTkComboBox(
            hdr, variable=self._sync_account_var, height=28, width=200,
            font=ctk.CTkFont(size=11), fg_color="#F8FAFC",
            border_color=self._BORDER, corner_radius=6,
            values=["(Chưa có account)"], state="readonly")
        self._sync_account_combo.pack(side="left", padx=(4, 10))

        self._sync_btn = ctk.CTkButton(
            hdr, text="🔄 Sync Fanpage", height=28, width=140,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=self._TEAL, hover_color="#0D9488", corner_radius=6,
            command=self._sync_pages)
        self._sync_btn.pack(side="left")

        self._sync_status = ctk.CTkLabel(
            hdr, text="← Chọn account rồi sync",
            font=ctk.CTkFont(size=10), text_color="#94A3B8")
        self._sync_status.pack(side="left", padx=(10, 0))

        # ── Body: left sidebar + right pane ──
        body = tk.Frame(parent, bg=self._BG)
        body.pack(fill="both", expand=True, padx=4, pady=(4, 4))
        body.columnconfigure(0, minsize=210, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left_card = ctk.CTkFrame(body, fg_color=self._CARD, corner_radius=10,
                                  border_width=1, border_color=self._BORDER)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._build_groups_sidebar(left_card)

        right_card = ctk.CTkFrame(body, fg_color=self._CARD, corner_radius=10,
                                   border_width=1, border_color=self._BORDER)
        right_card.grid(row=0, column=1, sticky="nsew")
        self._build_page_explorer(right_card)

    # ── Groups sidebar ──────────────────────────────────────────────────────

    def _build_groups_sidebar(self, parent):
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkLabel(hdr, text="🗂 Nhóm trang",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      text_color=self._TEXT).pack(side="left")

        act = ctk.CTkFrame(hdr, fg_color="transparent")
        act.pack(side="right")
        ctk.CTkButton(act, text="+", width=26, height=26,
                       font=ctk.CTkFont(size=13, weight="bold"),
                       fg_color=self._GREEN, hover_color="#15803D",
                       corner_radius=5, command=self._add_group).pack(side="left")
        ctk.CTkButton(act, text="✕", width=26, height=26,
                       font=ctk.CTkFont(size=11),
                       fg_color=self._RED, hover_color="#B91C1C",
                       corner_radius=5, command=self._delete_group).pack(side="left", padx=(2, 0))

        ctk.CTkFrame(parent, fg_color=self._BORDER, height=1).pack(fill="x", padx=8)

        self._groups_scroll = ctk.CTkScrollableFrame(
            parent, fg_color="transparent", corner_radius=0)
        self._groups_scroll.pack(fill="both", expand=True, padx=4, pady=4)

    # ── Page explorer ───────────────────────────────────────────────────────

    def _build_page_explorer(self, parent):
        # Search
        search_row = ctk.CTkFrame(parent, fg_color="transparent")
        search_row.pack(fill="x", padx=10, pady=(10, 4))
        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._render_pages())
        ctk.CTkEntry(search_row, textvariable=self._search_var, height=28,
                      placeholder_text="🔍 Tìm kiếm fanpage...",
                      font=ctk.CTkFont(size=11), fg_color="#F8FAFC",
                      border_color=self._BORDER, corner_radius=6,
                      text_color=self._TEXT).pack(fill="x")

        # Treeview
        import tkinter as tk
        tree_outer = tk.Frame(parent, bg=self._BG)
        tree_outer.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Pages.Treeview",
                         background=self._CARD, fieldbackground=self._CARD,
                         foreground=self._TEXT, rowheight=34,
                         font=("Segoe UI", 10))
        style.configure("Pages.Treeview.Heading",
                         background="#F1F5F9", foreground="#334155",
                         font=("Segoe UI", 10, "bold"), relief="flat")
        style.map("Pages.Treeview",
                   background=[("selected", "#DBEAFE")],
                   foreground=[("selected", "#1E40AF")])

        self._tree = ttk.Treeview(
            tree_outer, columns=("account", "group", "synced"),
            show="tree headings", style="Pages.Treeview", selectmode="extended")
        self._tree.heading("#0",      text="  Trang fanpage", anchor="w")
        self._tree.heading("account", text="Tài khoản",       anchor="w")
        self._tree.heading("group",   text="Nhóm",            anchor="w")
        self._tree.heading("synced",  text="Cập nhật",        anchor="w")
        self._tree.column("#0",      width=280, stretch=True, minwidth=180)
        self._tree.column("account", width=150, minwidth=100)
        self._tree.column("group",   width=120, minwidth=80)
        self._tree.column("synced",  width=90,  minwidth=60)

        vsb = ttk.Scrollbar(tree_outer, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Button-3>", self._on_tree_right_click)

    # ═══════════════════════════════════════════════════════════════════════
    # GROUP SIDEBAR LOGIC
    # ═══════════════════════════════════════════════════════════════════════

    def _refresh_groups_and_pages(self):
        self._groups = get_page_groups(self._db())
        self._all_pages = get_all_managed_pages(self._db())
        self._render_groups()
        self._render_pages()
        # Update sync account dropdown to match current account list
        opts = [(a.get("label") or a["username"]) for a in self._accounts]
        if opts:
            self._sync_account_combo.configure(values=opts)
            if self._sync_account_var.get() not in opts:
                self._sync_account_combo.set(opts[0])
        else:
            self._sync_account_combo.configure(values=["(Chưa có account)"])
            self._sync_account_combo.set("(Chưa có account)")

    def _render_groups(self):
        for w in self._groups_scroll.winfo_children():
            w.destroy()
        self._group_btn_refs.clear()

        total = len(self._all_pages)

        def _mk_btn(gid, label, count):
            sel = self._selected_group_id == gid
            b = ctk.CTkButton(
                self._groups_scroll, text=f"  {label}  ({count})",
                anchor="w", height=30,
                fg_color="#DBEAFE" if sel else "transparent",
                text_color=self._ACCENT if sel else self._TEXT,
                hover_color="#EFF6FF", corner_radius=6,
                font=ctk.CTkFont(size=11, weight="bold" if sel else "normal"),
                command=lambda g=gid: self._select_group(g))
            b.pack(fill="x", pady=1)
            self._group_btn_refs.append((gid, b))

        _mk_btn(None, "🌐 Tất cả", total)
        for grp in self._groups:
            icon = "📂" if grp["group_id"] == 1 else "📁"
            _mk_btn(grp["group_id"], f"{icon} {grp['group_name']}", grp["page_count"])

    def _select_group(self, group_id):
        self._selected_group_id = group_id
        self._render_groups()
        self._render_pages()

    def _add_group(self):
        dlg = ctk.CTkInputDialog(title="Thêm nhóm mới", text="Tên nhóm:")
        name = dlg.get_input()
        if name and name.strip():
            gid = add_page_group(self._db(), name.strip())
            if gid > 0:
                self._refresh_groups_and_pages()
            else:
                messagebox.showwarning("Tinix", "Tên nhóm đã tồn tại hoặc không hợp lệ!")

    def _delete_group(self):
        if self._selected_group_id is None or self._selected_group_id == 1:
            messagebox.showinfo("Tinix",
                                "Chọn một nhóm cụ thể để xóa.\n(Không thể xóa nhóm mặc định)")
            return
        grp = next((g for g in self._groups if g["group_id"] == self._selected_group_id), None)
        if not grp:
            return
        if not messagebox.askyesno(
                "Xác nhận",
                f"Xóa nhóm '{grp['group_name']}'?\n"
                f"Các trang trong nhóm sẽ chuyển về 'Chưa phân loại'."):
            return
        if delete_page_group(self._db(), self._selected_group_id):
            self._selected_group_id = None
            self._refresh_groups_and_pages()

    # ═══════════════════════════════════════════════════════════════════════
    # PAGE EXPLORER LOGIC
    # ═══════════════════════════════════════════════════════════════════════

    def _render_pages(self):
        self._tree.delete(*self._tree.get_children())
        self._tree_images.clear()

        pages = self._all_pages
        if self._selected_group_id is not None:
            pages = [p for p in pages if p.get("group_id") == self._selected_group_id]

        q = self._search_var.get().strip().lower() if hasattr(self, "_search_var") else ""
        if q:
            pages = [p for p in pages if q in p["page_name"].lower()]

        for p in pages:
            img = _load_avatar_photo(p.get("avatar_path", ""), size=28)
            if img:
                self._tree_images.append(img)
            synced = (p.get("last_synced") or p.get("scanned_at") or "")[:10]
            self._tree.insert(
                "", "end", iid=f"pg_{p['id']}",
                image=img or "",
                text=f"  {p['page_name']}",
                values=(p.get("account_label", ""), p.get("group_name", ""), synced),
                tags=(str(p["id"]),),
            )

    def _on_tree_right_click(self, event):
        import tkinter as tk
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        if iid not in self._tree.selection():
            self._tree.selection_set(iid)

        menu = tk.Menu(self, tearoff=0, bg="#FFFFFF", fg="#334155",
                        activebackground=self._ACCENT, activeforeground="#FFFFFF",
                        font=("Segoe UI", 10))

        move_menu = tk.Menu(menu, tearoff=0, bg="#FFFFFF", fg="#334155",
                             activebackground=self._ACCENT, activeforeground="#FFFFFF",
                             font=("Segoe UI", 10))
        for grp in self._groups:
            move_menu.add_command(
                label=f"  {grp['group_name']}",
                command=lambda gid=grp["group_id"]: self._move_selected_to_group(gid))

        menu.add_cascade(label="📂 Chuyển nhóm...", menu=move_menu)
        menu.add_command(label="🌐 Mở URL trong trình duyệt",
                          command=lambda: self._open_page_url(iid))
        menu.add_separator()
        menu.add_command(label="🗑 Xóa khỏi hệ thống",
                          command=self._remove_selected_pages,
                          foreground=self._RED)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _get_selected_row_ids(self) -> List[int]:
        ids = []
        for iid in self._tree.selection():
            tags = self._tree.item(iid, "tags")
            if tags:
                try:
                    ids.append(int(tags[0]))
                except (ValueError, IndexError):
                    pass
        return ids

    def _move_selected_to_group(self, group_id: int):
        row_ids = self._get_selected_row_ids()
        if row_ids and move_pages_to_group(self._db(), row_ids, group_id):
            self._refresh_groups_and_pages()

    def _open_page_url(self, iid: str):
        tags = self._tree.item(iid, "tags")
        if not tags:
            return
        try:
            row_id = int(tags[0])
        except (ValueError, IndexError):
            return
        page = next((p for p in self._all_pages if p["id"] == row_id), None)
        if page and page.get("page_url"):
            webbrowser.open(page["page_url"])

    def _remove_selected_pages(self):
        row_ids = self._get_selected_row_ids()
        if not row_ids:
            return
        if not messagebox.askyesno("Xác nhận", f"Xóa {len(row_ids)} trang khỏi hệ thống?"):
            return
        db = self._db()
        for rid in row_ids:
            delete_managed_page(db, rid)
        self._refresh_groups_and_pages()

    # ═══════════════════════════════════════════════════════════════════════
    # SMART SYNC (Playwright + avatar download)
    # ═══════════════════════════════════════════════════════════════════════

    def _sync_pages(self):
        label = self._sync_account_var.get()
        account = next(
            (a for a in self._accounts if (a.get("label") or a["username"]) == label), None)
        if not account:
            self._sync_status.configure(text="⚠ Chọn account trước", text_color="#D97706")
            return

        self._sync_btn.configure(state="disabled", text="⏳ Đang sync...")
        self._sync_status.configure(text="Đang mở Chrome...", text_color="#7C3AED")

        def _do():
            from core.auto_poster import AutoPoster
            poster = AutoPoster(account=account, headless=False)
            pages = []
            business_id = ""
            try:
                if poster.start():
                    def _on_st(msg):
                        self.after(0, self._sync_status.configure,
                                   {"text": msg[:70], "text_color": "#2563EB"})
                    pages, business_id = poster.scan_managed_pages(on_status=_on_st)
            finally:
                poster.stop()
            # Persist business_id so posting can build correct composer URLs
            if business_id:
                db = self._db()
                save_business_id(db, account["id"], business_id)
                logger.info(f"[sync] Saved business_id={business_id} for account {account['id']}")
            self.after(0, lambda: self._show_sync_confirm(pages, account["id"]))

        threading.Thread(target=_do, daemon=True).start()

    def _show_sync_confirm(self, pages: list, account_id: int):
        self._sync_btn.configure(state="normal", text="🔄 Sync Fanpage")
        if not pages:
            self._sync_status.configure(
                text="⚠ Không tìm thấy fanpage nào", text_color="#D97706")
            return

        dlg = ctk.CTkToplevel(self)
        dlg.title(f"Fanpage tìm thấy ({len(pages)})")
        dlg.geometry("380x460")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - 380) // 2
        dlg.geometry(f"+{max(0, x)}+{max(0, self.winfo_rooty() + 60)}")

        ctk.CTkLabel(dlg, text=f"✅ Tìm thấy {len(pages)} fanpage",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      text_color=self._TEXT).pack(padx=12, pady=(12, 2))
        ctk.CTkLabel(dlg, text="Bỏ chọn trang không muốn lưu:",
                      font=ctk.CTkFont(size=11), text_color=self._TEXT2).pack(padx=12, pady=(0, 6))

        list_frame = ctk.CTkScrollableFrame(
            dlg, fg_color="#F1F5F9", corner_radius=8, height=310)
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        check_vars = []
        for p in pages:
            var = ctk.BooleanVar(value=True)
            check_vars.append(var)
            ctk.CTkCheckBox(
                list_frame, text=p["page_name"], variable=var,
                font=ctk.CTkFont(size=11), text_color="#334155",
                fg_color="#2563EB", hover_color="#1D4ED8",
                checkbox_width=16, checkbox_height=16,
            ).pack(anchor="w", fill="x", padx=4, pady=2)

        def _confirm():
            selected = [p for p, v in zip(pages, check_vars) if v.get()]
            if not selected:
                return
            db = self._db()
            delete_managed_pages(db, account_id)
            saved = save_managed_pages(db, account_id, selected)
            self._sync_status.configure(
                text=f"✅ Đã lưu {saved} trang — đang tải avatar...",
                text_color=self._GREEN)
            dlg.destroy()
            threading.Thread(
                target=self._download_avatars_bg, args=(selected, db), daemon=True).start()
            self.after(600, self._refresh_groups_and_pages)

        foot = ctk.CTkFrame(dlg, fg_color="transparent")
        foot.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(foot, text="Huỷ", height=30, width=80,
                       fg_color="#F1F5F9", text_color="#475569", hover_color="#E2E8F0",
                       corner_radius=8, command=dlg.destroy).pack(side="left")
        ctk.CTkButton(foot, text="✓  Lưu & Sync avatar", height=30,
                       font=ctk.CTkFont(size=11, weight="bold"),
                       fg_color="#2563EB", hover_color="#1D4ED8",
                       corner_radius=8, command=_confirm).pack(side="right")

    def _download_avatars_bg(self, pages: list, db_path: str):
        """Background thread: download avatars and update DB."""
        import time as _time
        updated = 0
        for p in pages:
            avatar_url = p.get("avatar_url", "")
            page_id = p.get("page_id", "")
            if avatar_url and page_id:
                local = _download_avatar(avatar_url, page_id)
                if local:
                    update_page_avatar(db_path, page_id, local)
                    # Bust cache
                    _avatar_cache.pop(f"{local}:28", None)
                    updated += 1
            _time.sleep(0.1)
        if updated:
            self.after(0, self._refresh_groups_and_pages)
            self.after(0, self._sync_status.configure,
                       {"text": f"✅ Tải xong {updated} avatar", "text_color": self._GREEN})

    # ═══════════════════════════════════════════════════════════════════════
    # ACCOUNT CRUD LOGIC
    # ═══════════════════════════════════════════════════════════════════════

    def _refresh_list(self):
        self._accounts = get_all_accounts(self._db())
        self._proxies = get_all_proxies(self._db())

        _ch = self._acct_tree.get_children()
        if _ch:
            self._acct_tree.delete(*_ch)

        if not self._accounts:
            self._acct_tree.insert("", "end", iid="__empty",
                                    values=("—", "Chưa có tài khoản — bấm Import để thêm"),
                                    tags=("empty",))
        else:
            for acc in self._accounts:
                icon = "✅" if acc["is_active"] else "⬜"
                proxy_txt = f" · {acc['proxy_label']}" if acc.get("proxy_label") else ""
                display = f"{acc.get('label') or acc['username']} ({acc['username']}){proxy_txt}"
                self._acct_tree.insert("", "end", iid=f"acc_{acc['id']}",
                                        values=(icon, display),
                                        tags=(str(acc["id"]),))

            if self._selected_id:
                iid = f"acc_{self._selected_id}"
                if self._acct_tree.exists(iid):
                    self._acct_tree.selection_set(iid)
                    self._acct_tree.see(iid)

        # Update proxy dropdown — wrapped separately so a CTk render error won't block the list
        try:
            proxy_opts = ["Không có proxy"] + [
                f"[{p['id']}] {p['label'] or p['host']}:{p['port']}" for p in self._proxies]
            self._proxy_combo.configure(values=proxy_opts)
        except Exception:
            pass

    def _on_acct_tree_select(self, _event=None):
        """Handle treeview row selection → fill the detail form."""
        sel = self._acct_tree.selection()
        if not sel:
            return
        iid = sel[0]
        tags = self._acct_tree.item(iid, "tags")
        if not tags or "empty" in tags:
            return
        try:
            acc_id = int(tags[0])
        except (ValueError, IndexError):
            return
        acc = next((a for a in self._accounts if a["id"] == acc_id), None)
        if not acc:
            return
        self._selected_id = acc["id"]
        for key, entry in self._entries.items():
            entry.delete(0, "end")
            val = acc.get(key, "")
            if val:
                entry.insert(0, str(val))
        if acc.get("proxy_id"):
            for p in self._proxies:
                if p["id"] == acc["proxy_id"]:
                    self._proxy_var.set(
                        f"[{p['id']}] {p['label'] or p['host']}:{p['port']}")
                    break
        else:
            self._proxy_var.set("Không có proxy")
        self._status.configure(
            text=f"Đang sửa: {acc.get('label') or acc['username']}",
            text_color=self._ACCENT)

    def _select_account(self, acc: dict):
        """Programmatically select an account in the treeview."""
        self._selected_id = acc["id"]
        iid = f"acc_{acc['id']}"
        if self._acct_tree.exists(iid):
            self._acct_tree.selection_set(iid)
            self._acct_tree.see(iid)

    def _new_account(self):
        self._selected_id = None
        for entry in self._entries.values():
            entry.delete(0, "end")
        self._proxy_var.set("Không có proxy")
        self._status.configure(text="Thêm tài khoản mới", text_color=self._GREEN)
        self._refresh_list()

    def _save_account(self):
        username = self._entries["username"].get().strip()
        cookie = self._entries["cookie"].get().strip()
        if not username and not cookie:
            self._status.configure(text="❌ Cần username hoặc cookie!", text_color=self._RED)
            return
        proxy_id = None
        pv = self._proxy_var.get()
        if pv.startswith("["):
            try:
                proxy_id = int(pv.split("]")[0][1:])
            except (ValueError, IndexError):
                pass
        data = {
            "label":      self._entries["label"].get().strip(),
            "username":   username or f"cookie_{len(self._accounts)+1}",
            "password":   self._entries["password"].get().strip(),
            "secret_2fa": self._entries["secret_2fa"].get().strip(),
            "email":      self._entries["email"].get().strip(),
            "email_pass": self._entries["email_pass"].get().strip(),
            "cookie":     cookie,
            "proxy_id":   proxy_id,
        }
        if self._selected_id:
            ok = update_account(self._db(), self._selected_id, **data)
            msg = "✅ Đã cập nhật!" if ok else "❌ Lỗi"
        else:
            new_id = add_account(self._db(), **data)
            ok = new_id > 0
            if ok:
                self._selected_id = new_id
            msg = "✅ Đã thêm!" if ok else "❌ Lỗi (trùng?)"
        self._status.configure(text=msg, text_color=self._GREEN if ok else self._RED)
        self._refresh_list()
        self._refresh_groups_and_pages()
        if self._on_change:
            self._on_change()

    def _delete_account(self):
        if not self._selected_id:
            self._status.configure(text="⚠ Chọn tài khoản trước", text_color="#D97706")
            return
        if delete_account(self._db(), self._selected_id):
            self._selected_id = None
            for entry in self._entries.values():
                entry.delete(0, "end")
            self._status.configure(text="🗑 Đã xóa", text_color=self._RED)
        self._refresh_list()
        if self._on_change:
            self._on_change()

    def _open_import(self):
        BulkImportDialog(self, on_import=self._do_bulk_import)

    def _do_bulk_import(self, accounts: list) -> int:
        count = 0
        for acc in accounts:
            if not acc.get("username") and not acc.get("cookie"):
                continue
            new_id = add_account(
                self._db(),
                label=acc.get("label", ""),
                username=acc.get("username", f"imported_{count+1}"),
                password=acc.get("password", ""),
                secret_2fa=acc.get("secret_2fa", ""),
                email=acc.get("email", ""),
                email_pass=acc.get("email_pass", ""),
                cookie=acc.get("cookie", ""),
            )
            if new_id > 0:
                count += 1
        self._refresh_list()
        self._status.configure(text=f"📥 Imported {count} tài khoản", text_color=self._GREEN)
        if self._on_change:
            self._on_change()
        return count

    def _check_live(self):
        if not self._accounts:
            self._status.configure(text="⚠ Chưa có tài khoản", text_color="#D97706")
            return
        to_check = (
            [a for a in self._accounts if a["id"] == self._selected_id]
            if self._selected_id else list(self._accounts)
        )
        self._status.configure(
            text=f"🔍 Đang check {len(to_check)} tài khoản...", text_color="#7C3AED")
        threading.Thread(target=self._check_live_thread, args=(to_check,), daemon=True).start()

    def _check_live_thread(self, accounts: list):
        try:
            from core.page_scraper import PageScraper
            import time
            results = []
            for acc in accounts:
                label = acc.get("label") or acc["username"]
                try:
                    scraper = PageScraper(account=acc)
                    if not scraper.start():
                        results.append((label, "❌ Chrome fail"))
                        continue
                    page = scraper._context.new_page()
                    page.goto("https://www.facebook.com/",
                               wait_until="load", timeout=20000)
                    time.sleep(4)
                    state = page.evaluate("""() => ({
                        hasNav: !!document.querySelector('[role="navigation"]'),
                        hasFeed: !!document.querySelector('[role="feed"]'),
                    })""")
                    page.close()
                    scraper.stop()
                    if state.get("hasNav") or state.get("hasFeed"):
                        results.append((label, "✅ Live"))
                        update_account(self._db(), acc["id"], is_active=1)
                    else:
                        results.append((label, "❌ Die"))
                        update_account(self._db(), acc["id"], is_active=0)
                except Exception as e:
                    results.append((label, f"❌ {str(e)[:30]}"))
            summary = " | ".join(f"{n}: {s}" for n, s in results)
            live = sum(1 for _, s in results if "Live" in s)
            self.after(0, self._status.configure, {
                "text": f"🔍 {live}/{len(results)} Live — {summary[:80]}",
                "text_color": self._GREEN if live > 0 else self._RED,
            })
            self.after(0, self._refresh_list)
        except Exception as e:
            self.after(0, self._status.configure, {
                "text": f"❌ Lỗi check: {str(e)[:60]}", "text_color": self._RED})
