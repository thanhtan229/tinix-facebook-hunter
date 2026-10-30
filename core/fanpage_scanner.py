"""
Standalone Facebook fanpage scanner for account-manager testing.

This module intentionally does not depend on AutoPoster. It reuses an
existing Chrome profile/debug port when possible, launches Chrome only if
needed, then navigates directly to the single Facebook pages URL
facebook.com/pages/?category=your_pages and extracts managed pages from
the rendered page cards.
"""

import os
import random
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

from utils import logger


TARGET_URL = "https://www.facebook.com/pages/?category=your_pages"


def _find_chrome_path() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return "chrome"


def _wait_for_debug_port(port: int, timeout_s: float = 18.0) -> bool:
    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.6)
    return False


def _random_delay(min_s: float = 1.0, max_s: float = 2.0):
    time.sleep(random.uniform(min_s, max_s))


class FanpageScanner:
    """Small standalone scanner that works on an account Chrome profile."""

    def __init__(
        self,
        profile_dir: str,
        cdp_port: int,
        user_agent: str = "",
        on_status: Optional[Callable[[str], None]] = None,
    ):
        self.profile_dir = str(profile_dir or "").strip()
        self.cdp_port = int(cdp_port or 0)
        self.user_agent = str(user_agent or "").strip()
        self.on_status = on_status
        self._pw = None
        self._browser = None
        self._context = None
        self._started_chrome = False

    def _status(self, msg: str):
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass

    def start(self) -> bool:
        if not self.profile_dir:
            raise RuntimeError("Missing profile_dir")
        if not self.cdp_port:
            raise RuntimeError("Missing cdp_port")

        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        if not _wait_for_debug_port(self.cdp_port, timeout_s=1.0):
            chrome_cmd = [
                _find_chrome_path(),
                f"--user-data-dir={self.profile_dir}",
                f"--remote-debugging-port={self.cdp_port}",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
                "--new-window",
                "--window-size=1280,900",
                TARGET_URL,
            ]
            if self.user_agent:
                chrome_cmd.append(f"--user-agent={self.user_agent}")
            subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._started_chrome = True
            self._status("Đang mở Chrome profile...")
            if not _wait_for_debug_port(self.cdp_port, timeout_s=12.0):
                raise RuntimeError("Không kết nối được Chrome profile")

        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(
            f"http://127.0.0.1:{self.cdp_port}", timeout=12000
        )
        self._context = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        return True

    def stop(self):
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._context = None
        self._pw = None

    def _pick_scan_page(self):
        if not self._context:
            raise RuntimeError("Scanner not started")

        pages = list(self._context.pages)
        for page in reversed(pages):
            try:
                url = page.url or ""
            except Exception:
                continue
            if "facebook.com" in url:
                try:
                    page.bring_to_front()
                except Exception:
                    pass
                return page

        for page in reversed(pages):
            try:
                url = page.url or ""
            except Exception:
                continue
            if url in ("", "about:blank") or url.startswith("chrome://new-tab"):
                try:
                    page.bring_to_front()
                except Exception:
                    pass
                return page

        page = self._context.new_page()
        try:
            page.bring_to_front()
        except Exception:
            pass
        return page

    def scan(self) -> List[Dict]:
        page = self._pick_scan_page()
        page.set_default_timeout(30000)
        self._status("Đang vào trang fanpage duy nhất...")
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=25000)
        try:
            page.wait_for_selector('[role="main"]', timeout=10000)
        except Exception:
            pass
        _random_delay(2.0, 3.0)

        landed = page.url or ""
        logger.info(f"[scan-page] landed at {landed[:120]}")
        if "login" in landed or "checkpoint" in landed:
            raise RuntimeError("Facebook đã chuyển về trang login/checkpoint")

        self._status("Đang tải danh sách fanpage từ URL duy nhất...")
        for _ in range(6):
            page.keyboard.press("End")
            _random_delay(0.7, 1.1)

        self._status("Đang phân tích danh sách fanpage từ URL duy nhất...")
        raw = page.evaluate(
            r"""
            () => {
                const out = [];
                const seen = new Set();

                const SKIP = new Set([
                    'home','watch','marketplace','gaming','groups','login',
                    'help','settings','pages','bookmarks','notifications',
                    'friends','messages','events','stories','feeds','videos',
                    'saved','people','ads','business','privacy','terms',
                    'about','create','composer','manage','reels','fundraisers',
                    'policies','communitystandards','wellbeing',
                    'profile.php','photo.php',
                ]);

                const BAD_NAME = [
                    'thÃ´ng bÃ¡o','notification','tin nháº¯n','message',
                    'cÃ i Ä‘áº·t','setting','Ä‘Äƒng nháº­p','log in',
                    'Ä‘Äƒng xuáº¥t','log out','quáº£n lÃ½','manage',
                    'Ä‘iá»u khoáº£n','chÃ­nh sÃ¡ch','terms','policy',
                ];

                const MANAGE_TEXTS = [
                    'quáº£n lÃ½ trang','manage page','quáº£n lÃ½','manage',
                    'dashboard','báº£ng Ä‘iá»u khiá»ƒn',
                ];

                function isBadName(s) {
                    const sl = (s || '').toLowerCase();
                    return BAD_NAME.some(k => sl.includes(k));
                }

                function extractPageId(href) {
                    try {
                        const u = new URL(href);
                        const path = u.pathname.replace(/\/$/, '');
                        if (path === '/profile.php') {
                            const id = u.searchParams.get('id');
                            if (id && /^\d{6,}$/.test(id)) return { id, url: href };
                            return null;
                        }
                        const pidM = /^\/pages\/[^/]+\/(\d{6,})$/.exec(path);
                        if (pidM) return { id: pidM[1], url: href };
                        const slugM = /^\/([A-Za-z0-9][A-Za-z0-9._-]{1,79})$/.exec(path);
                        if (slugM && !SKIP.has(slugM[1].toLowerCase()))
                            return { id: slugM[1], url: href };
                    } catch {}
                    return null;
                }

                const AVATAR_PREFIXES = [
                    'áº£nh Ä‘áº¡i diá»‡n cá»§a ',
                    'profile picture of ',
                    'profile photo of ',
                    'photo of ',
                    'hÃ¬nh áº£nh cá»§a ',
                ];
                function stripAvatarPrefix(s) {
                    const input = (s || '').trim();
                    const sl = input.toLowerCase();
                    for (const p of AVATAR_PREFIXES) {
                        if (sl.startsWith(p)) return input.slice(p.length).trim();
                    }
                    return input;
                }

                function extractName(container) {
                    const h = container.querySelector('[role="heading"]');
                    if (h) {
                        const t = stripAvatarPrefix(h.textContent.trim());
                        if (t.length > 1 && !isBadName(t)) return t;
                    }
                    for (const sp of container.querySelectorAll('span[dir="auto"],span[dir="ltr"]')) {
                        const t = stripAvatarPrefix(sp.textContent.trim());
                        if (t.length >= 2 && t.length <= 100 && !isBadName(t)) return t;
                    }
                    const al = (container.getAttribute && container.getAttribute('aria-label') || '').trim();
                    if (al.length >= 2) {
                        const t = stripAvatarPrefix(al);
                        if (!isBadName(t)) return t;
                    }
                    return '';
                }

                function extractAvatar(container) {
                    if (!container) return '';
                    for (const img of container.querySelectorAll('img[src]')) {
                        const src = img.src || '';
                        if (src.includes('fbcdn.net') || src.includes('fbsbx.com')) {
                            return src;
                        }
                    }
                    return '';
                }

                const root = document.querySelector('[role="main"]') || document.body;

                for (const el of root.querySelectorAll('a,div[role="button"],button')) {
                    const elText = (el.textContent || '').trim().toLowerCase();
                    if (!MANAGE_TEXTS.some(t => elText === t)) continue;

                    let container = el.parentElement;
                    let found = false;
                    for (let i = 0; i < 12 && container; i++) {
                        for (const a of container.querySelectorAll('a[href]')) {
                            const info = extractPageId(a.href);
                            if (!info || seen.has(info.id)) continue;

                            const name = extractName(container);
                            if (!name || isBadName(name)) continue;

                            const avatar = extractAvatar(container);
                            seen.add(info.id);
                            out.push({ pageId: info.id, name, href: info.url, avatar });
                            found = true;
                            break;
                        }
                        if (found) break;
                        container = container.parentElement;
                    }
                }

                if (out.length === 0) {
                    for (const a of root.querySelectorAll('a[href]')) {
                        const info = extractPageId(a.href);
                        if (!info || seen.has(info.id)) continue;

                        let name = extractName(a);
                        if (!name) {
                            const par = a.parentElement;
                            if (par) {
                                const h = par.querySelector('[role="heading"]');
                                if (h) name = (h.textContent || '').trim();
                            }
                        }
                        if (!name || isBadName(name)) continue;

                        const avatarEl = a.closest('div[class]') || a.parentElement;
                        const avatar = extractAvatar(avatarEl);
                        seen.add(info.id);
                        out.push({ pageId: info.id, name, href: info.url, avatar });
                    }
                }

                return out;
            }
            """
        )

        results: List[Dict] = []
        seen = set()
        for item in raw or []:
            page_id = str(item.get("pageId") or "").strip()
            page_name = str(item.get("name") or "").strip()
            page_url = str(item.get("href") or "").strip()
            if not page_id or not page_name:
                continue
            key = page_id.lower()
            if key in seen:
                continue
            seen.add(key)
            if page_url.startswith("/"):
                page_url = f"https://www.facebook.com{page_url}"
            results.append(
                {
                    "page_id": page_id,
                    "page_name": page_name,
                    "page_url": page_url or f"https://www.facebook.com/{page_id}",
                    "avatar_url": str(item.get("avatar") or "").strip(),
                }
            )

        self._status(f"Tìm thấy {len(results)} fanpage")
        return results
