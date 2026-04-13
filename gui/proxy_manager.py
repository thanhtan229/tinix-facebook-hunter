"""
Tinix Facebook Down — Proxy Manager Dialog
CRUD + Bulk Import + Check Live for proxy servers.
"""

import threading
import customtkinter as ctk
from typing import Callable, Optional

from core.db_storage import (
    get_db_path, get_all_proxies,
    add_proxy, update_proxy, delete_proxy,
)
from utils import config


def parse_proxy_lines(text: str) -> list:
    """
    Parse bulk proxy import text. Each line is one proxy.
    Supported formats:
        USER:PASSWORD@IP:PORT
        IP:PORT:USER:PASSWORD
        IP:PORT (no auth)
    """
    results = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        proxy = {"protocol": "http", "auth_user": "", "auth_pass": ""}

        # Strip protocol prefix
        for proto in ("socks5://", "https://", "http://"):
            if line.lower().startswith(proto):
                proxy["protocol"] = proto.replace("://", "")
                line = line[len(proto):]
                break

        if "@" in line:
            # Format: USER:PASSWORD@IP:PORT
            auth_part, host_part = line.rsplit("@", 1)
            if ":" in auth_part:
                proxy["auth_user"], proxy["auth_pass"] = auth_part.split(":", 1)

            if ":" in host_part:
                parts = host_part.rsplit(":", 1)
                proxy["host"] = parts[0]
                try:
                    proxy["port"] = int(parts[1])
                except ValueError:
                    proxy["port"] = 80
            else:
                proxy["host"] = host_part
                proxy["port"] = 80
        else:
            # Format: IP:PORT:USER:PASSWORD or IP:PORT
            parts = line.split(":")
            if len(parts) == 2:
                proxy["host"] = parts[0]
                try:
                    proxy["port"] = int(parts[1])
                except ValueError:
                    proxy["port"] = 80
            elif len(parts) == 4:
                proxy["host"] = parts[0]
                try:
                    proxy["port"] = int(parts[1])
                except ValueError:
                    proxy["port"] = 80
                proxy["auth_user"] = parts[2]
                proxy["auth_pass"] = parts[3]
            elif len(parts) == 3:
                # Could be IP:PORT:USER (incomplete) - treat as IP:PORT
                proxy["host"] = parts[0]
                try:
                    proxy["port"] = int(parts[1])
                except ValueError:
                    proxy["port"] = 80
            else:
                continue

        if proxy.get("host"):
            results.append(proxy)

    return results


class BulkProxyImportDialog(ctk.CTkToplevel):
    """Dialog for bulk importing proxies."""

    def __init__(self, master, on_import: Callable, **kwargs):
        super().__init__(master, **kwargs)
        self._on_import = on_import

        self.title("📥 Import proxy hàng loạt")
        self.geometry("500x380")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.update_idletasks()
        x = master.winfo_x() + (master.winfo_width() - 500) // 2
        y = master.winfo_y() + (master.winfo_height() - 380) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")

        main = ctk.CTkFrame(self, fg_color="#F5F5F7", corner_radius=0)
        main.pack(fill="both", expand=True)

        ctk.CTkLabel(
            main, text="📥 Import proxy hàng loạt",
            font=ctk.CTkFont(size=16, weight="bold"), text_color="#1E293B",
        ).pack(padx=16, pady=(12, 4))

        ctk.CTkLabel(
            main, text=(
                "Mỗi dòng 1 proxy, hỗ trợ các định dạng:\n"
                "• USER:PASSWORD@IP:PORT\n"
                "• IP:PORT:USER:PASSWORD\n"
                "• IP:PORT (không auth)\n"
                "• http://USER:PASS@IP:PORT\n"
                "• socks5://IP:PORT"
            ),
            font=ctk.CTkFont(size=11), text_color="#64748B",
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 6))

        self._textbox = ctk.CTkTextbox(
            main, height=140,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#FFF", text_color="#334155",
            corner_radius=8, border_width=1, border_color="#E2E8F0",
        )
        self._textbox.pack(fill="x", padx=16, pady=(0, 8))

        btn_row = ctk.CTkFrame(main, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 8))

        self._result_label = ctk.CTkLabel(
            btn_row, text="", font=ctk.CTkFont(size=11), text_color="#94A3B8",
        )
        self._result_label.pack(side="left")

        ctk.CTkButton(
            btn_row, text="📥 Import", width=120, height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#16A34A", hover_color="#15803D", corner_radius=8,
            command=self._do_import,
        ).pack(side="right")

        ctk.CTkButton(
            btn_row, text="📋 Dán", width=70, height=32,
            font=ctk.CTkFont(size=11),
            fg_color="#F1F5F9", text_color="#475569",
            hover_color="#E2E8F0", corner_radius=6,
            command=self._paste,
        ).pack(side="right", padx=(0, 6))

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

        proxies = parse_proxy_lines(text)
        if not proxies:
            self._result_label.configure(text="❌ Không parse được!", text_color="#DC2626")
            return

        count = self._on_import(proxies)
        self._result_label.configure(
            text=f"✅ Đã import {count}/{len(proxies)} proxy",
            text_color="#16A34A",
        )


class ProxyManagerDialog(ctk.CTkToplevel):
    """Dialog for managing proxy servers."""

    def __init__(self, master, on_change: Optional[Callable] = None, **kwargs):
        super().__init__(master, **kwargs)
        self._on_change = on_change
        self._selected_id: Optional[int] = None
        self._proxies = []

        self.title("🌐 Quản lý Proxy")
        self.geometry("540x570")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.update_idletasks()
        x = master.winfo_x() + (master.winfo_width() - 540) // 2
        y = master.winfo_y() + (master.winfo_height() - 570) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")

        self._setup_ui()
        self._refresh_list()

    def _db(self) -> str:
        return get_db_path(config.get("scraper_db_path", ""))

    def _setup_ui(self):
        main = ctk.CTkFrame(self, fg_color="#F5F5F7", corner_radius=0)
        main.pack(fill="both", expand=True)

        ctk.CTkLabel(
            main, text="🌐 Quản lý Proxy",
            font=ctk.CTkFont(size=18, weight="bold"), text_color="#1E293B",
        ).pack(padx=20, pady=(14, 8))

        # ===== Proxy List =====
        list_card = ctk.CTkFrame(main, fg_color="#FFF", corner_radius=10,
                                  border_width=1, border_color="#E2E8F0")
        list_card.pack(fill="x", padx=16, pady=(0, 6))

        self._list_frame = ctk.CTkScrollableFrame(
            list_card, height=120, fg_color="#FFF", corner_radius=0,
        )
        self._list_frame.pack(fill="x", padx=4, pady=4)

        btn_row = ctk.CTkFrame(list_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 8))

        buttons = [
            ("🆕 Mới", "#16A34A", self._new_proxy),
            ("📥 Import", "#2563EB", self._open_import),
            ("🔍 Check Live", "#7C3AED", self._check_live),
            ("🗑 Xóa", "#DC2626", self._delete_proxy),
        ]
        for text, color, cmd in buttons:
            ctk.CTkButton(
                btn_row, text=text, width=95, height=28,
                font=ctk.CTkFont(size=11), fg_color=color,
                hover_color="#333", corner_radius=6, command=cmd,
            ).pack(side="left", padx=(0, 4))

        # ===== Detail Form =====
        form_card = ctk.CTkFrame(main, fg_color="#FFF", corner_radius=10,
                                  border_width=1, border_color="#E2E8F0")
        form_card.pack(fill="x", padx=16, pady=(0, 6))

        ctk.CTkLabel(
            form_card, text="Chi tiết Proxy",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#334155",
        ).pack(anchor="w", padx=14, pady=(10, 4))

        form_inner = ctk.CTkFrame(form_card, fg_color="transparent")
        form_inner.pack(fill="x", padx=14, pady=(0, 10))

        self._entries = {}
        for key, label, placeholder in [
            ("label", "Tên proxy", "VD: US Proxy 1"),
            ("host", "Host/IP", "1.2.3.4"),
            ("auth_user", "Auth User", "Để trống nếu không cần"),
            ("auth_pass", "Auth Pass", "Để trống nếu không cần"),
        ]:
            row = ctk.CTkFrame(form_inner, fg_color="transparent")
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(
                row, text=label, font=ctk.CTkFont(size=11),
                text_color="#64748B", width=100, anchor="w",
            ).pack(side="left")

            entry = ctk.CTkEntry(
                row, font=ctk.CTkFont(size=11), height=28,
                fg_color="#F8FAFC", text_color="#334155",
                border_color="#E2E8F0", corner_radius=6,
                placeholder_text=placeholder,
                show="•" if "pass" in key.lower() else "",
            )
            entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
            self._entries[key] = entry

        # Protocol + Port
        proto_row = ctk.CTkFrame(form_inner, fg_color="transparent")
        proto_row.pack(fill="x", pady=2)

        ctk.CTkLabel(
            proto_row, text="Protocol", font=ctk.CTkFont(size=11),
            text_color="#64748B", width=100, anchor="w",
        ).pack(side="left")

        self._proto_var = ctk.StringVar(value="http")
        ctk.CTkOptionMenu(
            proto_row, variable=self._proto_var,
            values=["http", "https", "socks5"], width=100, height=28,
            font=ctk.CTkFont(size=11), fg_color="#F8FAFC",
            button_color="#CBD5E1", text_color="#334155", corner_radius=6,
        ).pack(side="left", padx=(4, 8))

        ctk.CTkLabel(
            proto_row, text="Port", font=ctk.CTkFont(size=11),
            text_color="#64748B", width=40, anchor="w",
        ).pack(side="left")

        self._port_entry = ctk.CTkEntry(
            proto_row, font=ctk.CTkFont(size=11), height=28, width=80,
            fg_color="#F8FAFC", text_color="#334155",
            border_color="#E2E8F0", corner_radius=6,
            placeholder_text="8080",
        )
        self._port_entry.pack(side="left", padx=(4, 0))

        # Save
        save_row = ctk.CTkFrame(form_card, fg_color="transparent")
        save_row.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkButton(
            save_row, text="💾 Lưu", width=100, height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563EB", hover_color="#1D4ED8", corner_radius=8,
            command=self._save_proxy,
        ).pack(side="right")

        self._status = ctk.CTkLabel(
            save_row, text="", font=ctk.CTkFont(size=11), text_color="#94A3B8",
        )
        self._status.pack(side="left")

        ctk.CTkButton(
            main, text="Đóng", width=80, height=32,
            font=ctk.CTkFont(size=12), fg_color="#F1F5F9",
            text_color="#475569", hover_color="#E2E8F0",
            corner_radius=8, command=self.destroy,
        ).pack(pady=(4, 12))

    # === List ===

    def _refresh_list(self):
        self._proxies = get_all_proxies(self._db())

        for w in self._list_frame.winfo_children():
            w.destroy()

        if not self._proxies:
            ctk.CTkLabel(
                self._list_frame, text="Chưa có proxy — bấm Import để thêm",
                font=ctk.CTkFont(size=12), text_color="#94A3B8",
            ).pack(pady=20)
            return

        for p in self._proxies:
            row = ctk.CTkFrame(self._list_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)

            status = "✅" if p["is_active"] else "⬜"
            auth = f" ({p['auth_user']})" if p["auth_user"] else ""
            display = f"{status} {p['label'] or 'Proxy'} · {p['protocol']}://{p['host']}:{p['port']}{auth}"
            is_sel = self._selected_id == p["id"]

            btn = ctk.CTkButton(
                row, text=display, anchor="w", height=26,
                font=ctk.CTkFont(size=11),
                fg_color="#DBEAFE" if is_sel else "transparent",
                text_color="#1E293B", hover_color="#EFF6FF", corner_radius=4,
                command=lambda pr=p: self._select_proxy(pr),
            )
            btn.pack(fill="x")

    # === CRUD ===

    def _select_proxy(self, proxy: dict):
        self._selected_id = proxy["id"]
        for key in ("label", "host", "auth_user", "auth_pass"):
            self._entries[key].delete(0, "end")
            if proxy.get(key):
                self._entries[key].insert(0, str(proxy[key]))
        self._proto_var.set(proxy.get("protocol", "http"))
        self._port_entry.delete(0, "end")
        self._port_entry.insert(0, str(proxy.get("port", 80)))
        self._status.configure(text=f"Đang sửa: {proxy['label'] or proxy['host']}", text_color="#2563EB")
        self._refresh_list()

    def _new_proxy(self):
        self._selected_id = None
        for entry in self._entries.values():
            entry.delete(0, "end")
        self._port_entry.delete(0, "end")
        self._proto_var.set("http")
        self._status.configure(text="Thêm proxy mới", text_color="#16A34A")
        self._refresh_list()

    def _save_proxy(self):
        host = self._entries["host"].get().strip()
        if not host:
            self._status.configure(text="❌ Host không được trống!", text_color="#DC2626")
            return
        try:
            port = int(self._port_entry.get().strip() or "80")
        except ValueError:
            self._status.configure(text="❌ Port phải là số!", text_color="#DC2626")
            return

        data = {
            "label": self._entries["label"].get().strip(),
            "protocol": self._proto_var.get(),
            "host": host,
            "port": port,
            "auth_user": self._entries["auth_user"].get().strip(),
            "auth_pass": self._entries["auth_pass"].get().strip(),
        }

        if self._selected_id:
            ok = update_proxy(self._db(), self._selected_id, **data)
            msg = "✅ Đã cập nhật!" if ok else "❌ Lỗi"
        else:
            new_id = add_proxy(self._db(), **data)
            ok = new_id > 0
            if ok:
                self._selected_id = new_id
            msg = "✅ Đã thêm!" if ok else "❌ Lỗi"

        self._status.configure(text=msg, text_color="#16A34A" if ok else "#DC2626")
        self._refresh_list()
        if self._on_change:
            self._on_change()

    def _delete_proxy(self):
        if not self._selected_id:
            self._status.configure(text="⚠ Chọn proxy trước", text_color="#D97706")
            return
        ok = delete_proxy(self._db(), self._selected_id)
        if ok:
            self._selected_id = None
            for entry in self._entries.values():
                entry.delete(0, "end")
            self._port_entry.delete(0, "end")
            self._status.configure(text="🗑 Đã xóa", text_color="#DC2626")
        self._refresh_list()
        if self._on_change:
            self._on_change()

    # === Bulk Import ===

    def _open_import(self):
        BulkProxyImportDialog(self, on_import=self._do_bulk_import)

    def _do_bulk_import(self, proxies: list) -> int:
        count = 0
        for p in proxies:
            new_id = add_proxy(
                self._db(),
                label=p.get("label", ""),
                protocol=p.get("protocol", "http"),
                host=p["host"],
                port=p.get("port", 80),
                auth_user=p.get("auth_user", ""),
                auth_pass=p.get("auth_pass", ""),
            )
            if new_id > 0:
                count += 1
        self._refresh_list()
        self._status.configure(text=f"📥 Imported {count} proxy", text_color="#16A34A")
        if self._on_change:
            self._on_change()
        return count

    # === Check Live ===

    def _check_live(self):
        """Check if selected (or all) proxies are reachable."""
        if not self._proxies:
            self._status.configure(text="⚠ Chưa có proxy", text_color="#D97706")
            return

        proxies_to_check = []
        if self._selected_id:
            for p in self._proxies:
                if p["id"] == self._selected_id:
                    proxies_to_check = [p]
                    break
        else:
            proxies_to_check = list(self._proxies)

        self._status.configure(
            text=f"🔍 Đang check {len(proxies_to_check)} proxy...",
            text_color="#7C3AED",
        )

        thread = threading.Thread(
            target=self._check_live_thread,
            args=(proxies_to_check,),
            daemon=True,
        )
        thread.start()

    def _check_live_thread(self, proxies: list):
        """Background thread to check proxy connectivity."""
        import socket

        results = []
        for p in proxies:
            label = p.get("label") or f"{p['host']}:{p['port']}"
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((p["host"], p["port"]))
                sock.close()

                if result == 0:
                    results.append((label, "✅ Live"))
                    update_proxy(self._db(), p["id"], is_active=1)
                else:
                    results.append((label, "❌ Die"))
                    update_proxy(self._db(), p["id"], is_active=0)
            except Exception as e:
                results.append((label, f"❌ {str(e)[:20]}"))
                update_proxy(self._db(), p["id"], is_active=0)

        live_count = sum(1 for _, s in results if "Live" in s)
        summary = " | ".join(f"{n}: {s}" for n, s in results)
        self.after(0, self._status.configure,
                   {"text": f"🔍 {live_count}/{len(results)} Live — {summary[:80]}",
                    "text_color": "#16A34A" if live_count > 0 else "#DC2626"})
        self.after(0, self._refresh_list)
