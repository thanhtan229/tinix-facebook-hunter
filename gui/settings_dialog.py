"""
Tinix Facebook Down — Settings Dialog
Configuration dialog for app settings + Cookie management.
"""

import customtkinter as ctk
from tkinter import filedialog
from typing import Callable, Optional

from utils import config
from core.db_storage import get_db_path, get_all_accounts, get_all_proxies


class SettingsDialog(ctk.CTkToplevel):
    """
    Modal settings dialog with:
    - Cookie input + validation
    - Max threads (1-10)
    - Default output directory
    - Auto-open folder after download
    """

    def __init__(self, master, on_save: Optional[Callable] = None, **kwargs):
        super().__init__(master, **kwargs)

        self._on_save = on_save

        # Window setup
        self.title("⚙ Cài đặt")
        self.geometry("500x600")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = master.winfo_x() + (master.winfo_width() - 500) // 2
        y = master.winfo_y() + (master.winfo_height() - 600) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")

        self._setup_ui()
        self._load_current_settings()

    def _setup_ui(self) -> None:
        """Build the settings dialog UI."""
        # Main container
        main = ctk.CTkFrame(self, fg_color="#F5F5F7", corner_radius=0)
        main.pack(fill="both", expand=True)

        # Title
        ctk.CTkLabel(
            main,
            text="⚙ Cài đặt",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#1E293B",
        ).pack(padx=20, pady=(16, 12))

        # ===== Account & Proxy Management Card =====
        acct_card = ctk.CTkFrame(
            main,
            fg_color="#FFFFFF",
            corner_radius=12,
            border_width=1,
            border_color="#E2E8F0",
        )
        acct_card.pack(fill="x", padx=20, pady=(0, 12))

        ctk.CTkLabel(
            acct_card,
            text="🔐 Tài khoản & Proxy",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#1E293B",
        ).pack(anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            acct_card,
            text="Quản lý tài khoản Facebook (đăng nhập tự động) và proxy",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        btn_row_acct = ctk.CTkFrame(acct_card, fg_color="transparent")
        btn_row_acct.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkButton(
            btn_row_acct,
            text="👤 Quản lý tài khoản",
            width=180,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            corner_radius=8,
            command=self._open_account_manager,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row_acct,
            text="🌐 Quản lý Proxy",
            width=160,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#7C3AED",
            hover_color="#6D28D9",
            corner_radius=8,
            command=self._open_proxy_manager,
        ).pack(side="left")

        self._acct_status = ctk.CTkLabel(
            acct_card,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#16A34A",
        )
        self._acct_status.pack(anchor="w", padx=16, pady=(0, 8))
        self._update_account_status()

        # ===== Settings Card =====
        card = ctk.CTkFrame(
            main,
            fg_color="#FFFFFF",
            corner_radius=12,
            border_width=1,
            border_color="#E2E8F0",
        )
        card.pack(fill="x", padx=20, pady=(0, 12))

        # --- Max Threads ---
        row1 = ctk.CTkFrame(card, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(
            row1,
            text="Số luồng tải song song:",
            font=ctk.CTkFont(size=13),
            text_color="#334155",
        ).pack(side="left")

        self._threads_var = ctk.StringVar(value="1")
        self._threads_menu = ctk.CTkOptionMenu(
            row1,
            values=[str(i) for i in range(1, 11)],
            variable=self._threads_var,
            width=80,
            height=32,
            font=ctk.CTkFont(size=12),
            fg_color="#F1F5F9",
            button_color="#CBD5E1",
            button_hover_color="#94A3B8",
            text_color="#334155",
            corner_radius=8,
        )
        self._threads_menu.pack(side="right")

        # Separator
        ctk.CTkFrame(card, fg_color="#E2E8F0", height=1).pack(fill="x", padx=16)

        # --- Default Output Dir ---
        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=8)

        ctk.CTkLabel(
            row2,
            text="Thư mục mặc định:",
            font=ctk.CTkFont(size=13),
            text_color="#334155",
        ).pack(anchor="w")

        dir_row = ctk.CTkFrame(row2, fg_color="transparent")
        dir_row.pack(fill="x", pady=(4, 0))

        self._dir_entry = ctk.CTkEntry(
            dir_row,
            font=ctk.CTkFont(size=12),
            fg_color="#F8FAFC",
            text_color="#334155",
            border_color="#E2E8F0",
            corner_radius=8,
            height=32,
        )
        self._dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        ctk.CTkButton(
            dir_row,
            text="📁",
            width=36,
            height=32,
            font=ctk.CTkFont(size=14),
            fg_color="#F1F5F9",
            text_color="#475569",
            hover_color="#E2E8F0",
            corner_radius=8,
            command=self._browse_dir,
        ).pack(side="right")

        # Separator
        ctk.CTkFrame(card, fg_color="#E2E8F0", height=1).pack(fill="x", padx=16)

        # --- Auto-open folder ---
        row3 = ctk.CTkFrame(card, fg_color="transparent")
        row3.pack(fill="x", padx=16, pady=(8, 12))

        self._auto_open_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            row3,
            text="Tự động mở thư mục sau khi tải xong",
            font=ctk.CTkFont(size=13),
            text_color="#334155",
            variable=self._auto_open_var,
            corner_radius=6,
            border_width=2,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
        ).pack(anchor="w")

        # --- Buttons ---
        btn_frame = ctk.CTkFrame(main, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 16))

        ctk.CTkButton(
            btn_frame,
            text="Lưu tất cả",
            width=110,
            height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            corner_radius=8,
            command=self._save,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame,
            text="Đóng",
            width=80,
            height=36,
            font=ctk.CTkFont(size=13),
            fg_color="#F1F5F9",
            text_color="#475569",
            hover_color="#E2E8F0",
            corner_radius=8,
            command=self.destroy,
        ).pack(side="right")

    def _load_current_settings(self) -> None:
        """Load current settings into the form."""
        cfg = config.load_config()
        self._threads_var.set(str(cfg.get("max_threads", 1)))
        self._dir_entry.insert(0, cfg.get("output_dir", config.DEFAULTS["output_dir"]))
        self._auto_open_var.set(cfg.get("auto_open_folder", False))

    def _update_account_status(self) -> None:
        """Update the account/proxy status label."""
        try:
            db = get_db_path(config.get("scraper_db_path", ""))
            accounts = get_all_accounts(db)
            proxies = get_all_proxies(db)
            active = sum(1 for a in accounts if a["is_active"])
            self._acct_status.configure(
                text=f"📊 {len(accounts)} tài khoản ({active} active) · {len(proxies)} proxy",
                text_color="#16A34A" if accounts else "#94A3B8",
            )
        except Exception:
            self._acct_status.configure(text="", text_color="#94A3B8")

    def _open_account_manager(self) -> None:
        """Open the Account Manager dialog."""
        from gui.account_manager import AccountManagerDialog
        AccountManagerDialog(self, on_change=self._update_account_status)

    def _open_proxy_manager(self) -> None:
        """Open the Proxy Manager dialog."""
        from gui.proxy_manager import ProxyManagerDialog
        ProxyManagerDialog(self, on_change=self._update_account_status)

    def _browse_dir(self) -> None:
        """Open directory chooser."""
        current = self._dir_entry.get().strip()
        directory = filedialog.askdirectory(
            title="Chọn thư mục mặc định",
            initialdir=current if current else None,
        )
        if directory:
            self._dir_entry.delete(0, "end")
            self._dir_entry.insert(0, directory)

    def _save(self) -> None:
        """Save all settings and close."""
        cfg = config.load_config()
        cfg["max_threads"] = int(self._threads_var.get())
        cfg["output_dir"] = self._dir_entry.get().strip()
        cfg["auto_open_folder"] = self._auto_open_var.get()
        config.save_config(cfg)

        if self._on_save:
            self._on_save(cfg)

        self.destroy()
