"""
Tinix Facebook Down — Auto Poster Engine
Playwright automation for posting to Facebook via Meta Business Suite.
Handles metadata branding, upload, scheduling, and anti-detection.
Also provides scan_managed_pages() to discover pages managed by an account.
"""

import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from utils import logger

# ─── Constants ─────────────────────────────────────────────────────────────

CDP_PORT_POSTER = 9226  # Different from scraper port 9224
MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".mp4", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg"}

# Facebook UI strings (English + Vietnamese) that are NEVER a real page name.
# Used to filter false-positives from both mbasic and browser scan strategies.
_FB_UI_NAMES: frozenset = frozenset({
    # ── English ──
    "home", "news feed", "newsfeed", "watch", "marketplace", "gaming",
    "groups", "login", "log in", "log out", "logout", "help", "settings",
    "pages", "bookmarks", "notifications", "friends", "messages",
    "events", "stories", "feeds", "videos", "saved", "people", "ads",
    "business", "privacy", "terms", "about", "create", "composer",
    "manage", "reels", "fundraisers", "jobs", "community", "search",
    "back", "next", "previous", "more", "see all", "see more",
    "memories", "explore", "discover", "your pages", "pages you manage",
    "terms of service", "privacy policy", "cookie policy",
    "community standards", "transparency",
    # ── Vietnamese ──
    "thông báo", "trang chủ", "bảng tin", "xem", "thị trường",
    "chơi game", "nhóm", "đăng nhập", "đăng xuất", "trợ giúp",
    "cài đặt", "trang", "dấu trang", "bạn bè", "tin nhắn",
    "sự kiện", "câu chuyện", "video", "đã lưu", "mọi người",
    "quảng cáo", "doanh nghiệp", "quyền riêng tư", "điều khoản",
    "giới thiệu", "tạo", "trình soạn thảo", "quản lý", "reels",
    "gây quỹ", "việc làm", "cộng đồng", "tìm kiếm", "quay lại",
    "tiếp theo", "trước", "thêm", "xem tất cả", "xem thêm",
    "ký ức", "khám phá", "trang của tôi", "trang bạn quản lý",
    "trang chủ doanh nghiệp", "tin tức",
    "điều khoản & chính sách", "chính sách quyền riêng tư",
    "tiêu chuẩn cộng đồng", "chính sách cookie",
})

# Substring patterns — 'in name_lower' catches variants like "Thông báo 2"
_FB_UI_SUBSTRINGS: tuple = (
    "thông báo", "notification",
    "tin nhắn", "message",
    "cài đặt", "setting",
    "đăng nhập", "log in", "log out", "đăng xuất",
    "trang chủ", "news feed",
    "điều khoản", "chính sách", "terms", "policy", "policies",
    "quyền riêng tư", "privacy",
)

BUSINESS_SUITE_URL = "https://business.facebook.com/latest/home"
CREATE_POST_URL = "https://business.facebook.com/latest/composer"


def _find_chrome() -> Optional[str]:
    """Find Chrome executable."""
    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _random_delay(min_s: float = 1.5, max_s: float = 4.0):
    """Human-like random delay."""
    time.sleep(random.uniform(min_s, max_s))


def _human_type(page, selector: str, text: str, delay_min=30, delay_max=80):
    """Type text with human-like delays between keystrokes."""
    element = page.locator(selector)
    element.click()
    _random_delay(0.3, 0.6)
    for char in text:
        page.keyboard.type(char, delay=random.randint(delay_min, delay_max))
    _random_delay(0.5, 1.0)


# ═══════════════════════════════════════════════════════════════════════════
# METADATA BRANDING
# ═══════════════════════════════════════════════════════════════════════════

def brand_media_to_temp(
    folder_path: str,
    brand_name: str,
    temp_base: Optional[str] = None,
) -> Optional[str]:
    """
    Copy media from folder_path to a temp directory, brand images with EXIF.

    Args:
        folder_path: Source folder with media files.
        brand_name: Name to embed in EXIF metadata.
        temp_base: Base dir for temp folders (default: app_dir/_temp_uploads).

    Returns:
        Path to temp folder with branded files, or None on error.
    """
    source = Path(folder_path)
    if not source.is_dir():
        logger.error(f"Source folder not found: {folder_path}")
        return None

    # Create temp folder
    if not temp_base:
        temp_base = str(Path(__file__).parent.parent / "_temp_uploads")
    os.makedirs(temp_base, exist_ok=True)
    temp_dir = tempfile.mkdtemp(dir=temp_base, prefix="post_")

    try:
        media_files = []
        for f in sorted(source.iterdir()):
            if f.is_file() and f.suffix.lower() in MEDIA_EXTS:
                dst = os.path.join(temp_dir, f.name)
                shutil.copy2(str(f), dst)
                media_files.append(dst)

        if not media_files:
            logger.warning(f"No media files in: {folder_path}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        # Brand images with EXIF
        if brand_name:
            _brand_images(temp_dir, brand_name)

        logger.info(f"  📁 Temp: {len(media_files)} files → {os.path.basename(temp_dir)}")
        return temp_dir

    except Exception as e:
        logger.error(f"brand_media_to_temp error: {str(e)[:200]}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None


def cleanup_temp(temp_dir: str):
    """Delete temp upload folder."""
    try:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass


def _brand_images(temp_dir: str, brand_name: str):
    """Brand all JPEG/JPG images in temp_dir with EXIF metadata."""
    try:
        import piexif
    except ImportError:
        logger.warning("piexif not installed — skipping EXIF branding")
        return

    brand_bytes = brand_name.encode("utf-8")
    comment = b"ASCII\x00\x00\x00" + brand_bytes

    for f in Path(temp_dir).iterdir():
        if f.suffix.lower() not in IMAGE_EXTS:
            continue
        try:
            try:
                exif_dict = piexif.load(str(f))
            except Exception:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = brand_bytes
            exif_dict["0th"][piexif.ImageIFD.Artist] = brand_bytes
            exif_dict["0th"][piexif.ImageIFD.Copyright] = brand_bytes
            exif_dict["Exif"][piexif.ExifIFD.UserComment] = comment

            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, str(f))
        except Exception:
            pass  # Skip corrupted files


# ═══════════════════════════════════════════════════════════════════════════
# AUTO POSTER ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class AutoPoster:
    """
    Playwright-based Facebook Auto Poster via Meta Business Suite.

    Features:
    - Persistent Chrome session (cookies/login)
    - EXIF metadata branding before upload
    - Server-side scheduling
    - Anti-detection with random delays
    - Screenshot on error for debugging
    """

    def __init__(self, account: Optional[Dict] = None, headless: bool = False):
        self._account = account or {}
        self._headless = headless
        self._stop_event = threading.Event()
        self._chrome_process = None
        self._browser = None
        self._context = None
        self._pw_instance = None
        # Meta Business Portfolio ID — loaded from account, resolved during scan
        self._business_id: str = str(account.get("business_id", "") or "")
        # Last error message from post_content / post_now (for error logging)
        self._last_error: str = ""

    # ─── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Launch Chrome and connect Playwright."""
        try:
            from playwright.sync_api import sync_playwright

            chrome_path = _find_chrome()
            if not chrome_path:
                logger.error("Chrome not found!")
                return False

            profile_dir = self._get_profile_dir()
            logger.info(f"🚀 AutoPoster Chrome: {os.path.basename(profile_dir)}")

            chrome_cmd = [
                chrome_path,
                f"--remote-debugging-port={CDP_PORT_POSTER}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-popup-blocking",
                "--disable-blink-features=AutomationControlled",
            ]

            # Always run as a real visible browser — Facebook detects headless
            # via GPU fingerprint and breaks React events / file choosers.
            # Force window position so Chrome doesn't restore a stale off-screen
            # position saved in the profile from a previous session.
            chrome_cmd.append("--window-size=1280,900")
            chrome_cmd.append("--window-position=60,60")

            logger.info("Đang khởi động Chrome...")
            self._chrome_process = subprocess.Popen(
                chrome_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                ),
            )
            time.sleep(4)

            self._pw_instance = sync_playwright().start()
            self._browser = self._pw_instance.chromium.connect_over_cdp(
                f"http://localhost:{CDP_PORT_POSTER}",
                timeout=15000,
            )

            if self._browser.contexts:
                self._context = self._browser.contexts[0]
            else:
                self._context = self._browser.new_context()

            # Login if needed
            if self._account.get("username") and self._account.get("password"):
                self._do_login()
            elif self._account.get("cookie"):
                self._inject_cookies()

            logger.info("✅ AutoPoster ready")
            return True

        except Exception as e:
            logger.error(f"AutoPoster start error: {str(e)[:200]}")
            self.stop()
            return False

    def stop(self):
        """Shutdown browser."""
        self._stop_event.set()
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw_instance:
                self._pw_instance.stop()
        except Exception:
            pass
        try:
            if self._chrome_process:
                self._chrome_process.terminate()
                self._chrome_process.wait(timeout=5)
        except Exception:
            try:
                if self._chrome_process:
                    self._chrome_process.kill()
            except Exception:
                pass
        self._browser = None
        self._context = None
        self._chrome_process = None
        self._pw_instance = None

    def request_stop(self):
        self._stop_event.set()

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    # ─── Posting ───────────────────────────────────────────────────────────

    def _resolve_business_id(self, page) -> str:
        """
        Discover the Meta Business Portfolio ID (business_id / global_scope_id).

        Tries in order:
          1. URL query params after navigating to /latest/home
          2. Numeric path segment in redirected URL
          3. Regex scan of the page HTML source
          4. Other already-open tabs in the browser context
        Result is cached in self._business_id for the session lifetime.
        """
        try:
            # ── Strategy 4 first: check tabs already open (cheapest) ─────────
            try:
                for pg in self._context.pages:
                    if "business.facebook.com" not in pg.url:
                        continue
                    p = parse_qs(urlparse(pg.url).query)
                    bid = (p.get("business_id", [""])[0]
                           or p.get("global_scope_id", [""])[0])
                    if bid:
                        logger.debug(f"[biz_id] from open tab: '{bid}'")
                        return bid
            except Exception:
                pass

            # ── Navigate to Business Suite home ──────────────────────────────
            page.goto("https://business.facebook.com/latest/home",
                      wait_until="domcontentloaded")
            _random_delay(2.5, 4.0)
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
                _random_delay(1.0, 1.5)
            except Exception:
                pass

            url = page.url
            logger.debug(f"[biz_id] redirected URL: {url}")

            # ── Strategy 1: URL query params ─────────────────────────────────
            params = parse_qs(urlparse(url).query)
            bid = (params.get("business_id", [""])[0]
                   or params.get("global_scope_id", [""])[0])
            if bid:
                logger.info(f"[biz_id] from URL param: '{bid}'")
                return bid

            # ── Strategy 2: numeric segment in path ──────────────────────────
            m = re.search(r"business\.facebook\.com/(\d{6,})/", url)
            if m:
                bid = m.group(1)
                logger.info(f"[biz_id] from URL path: '{bid}'")
                return bid

            # ── Strategy 3: regex scan of page HTML ──────────────────────────
            try:
                html = page.content()
                for pattern in [
                    r'"business_id"\s*:\s*"(\d{6,})"',
                    r'"businessId"\s*:\s*"(\d{6,})"',
                    r'"global_scope_id"\s*:\s*"(\d{6,})"',
                    r'business_id=(\d{6,})',
                    r'global_scope_id=(\d{6,})',
                ]:
                    m = re.search(pattern, html)
                    if m:
                        bid = m.group(1)
                        logger.info(f"[biz_id] from HTML source: '{bid}'")
                        return bid
            except Exception:
                pass

            logger.warning("[biz_id] could not resolve business_id — composer URL may be incomplete")
            return ""
        except Exception as e:
            logger.error(f"[biz_id] error: {str(e)[:120]}")
            return ""

    def _navigate_to_composer(
        self, page, page_id: str, page_name: str = "",
        on_status: Optional[Callable] = None,
    ) -> None:
        """
        Switch to the correct page via the Business Suite left-panel asset
        selector, then open the composer.

        Flow (mirrors what the user does manually):
          1. Navigate to Business Suite home.
          2. Click the asset-switcher button (top-left) to open the panel.
          3. Type the page name into the search box to filter assets.
          4. Click the matching page in the result list.
          5. Wait for BS context to switch (URL updates with new asset_id).
          6. Navigate to /latest/composer — opens for the now-selected page.

        Falls back to opening the composer directly (may post to default page)
        if the panel interaction fails.
        """
        if on_status:
            on_status(f"🔄 Chuyển sang page: {page_name}...")
        logger.info(f"[composer] switching to page '{page_name}' (id={page_id})")

        # ── Step 1: navigate to Business Suite home ──────────────────────────
        page.goto(BUSINESS_SUITE_URL, wait_until="domcontentloaded")
        _random_delay(3.0, 4.5)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        _random_delay(1.5, 2.5)

        if "login" in page.url or "checkpoint" in page.url:
            logger.warning("[composer] redirected to login — not authenticated")
            page.goto(CREATE_POST_URL, wait_until="domcontentloaded")
            return

        # ── Step 2: check if we're already on the correct page ───────────────
        # After navigating to BS home, FB redirects to the last-active page.
        # If that page is already the target, skip the switcher entirely.
        pid = str(page_id).strip() if page_id else ""
        already_correct = self._is_correct_bs_page(page, pid, page_name)

        if already_correct:
            logger.info(f"[composer] already on correct page '{page_name}' — skipping switch")
            if on_status:
                on_status(f"✅ Đang ở đúng page: {page_name}")
        else:
            # ── Step 3: switch via left-panel asset selector ─────────────────
            switched = False
            try:
                switched = self._switch_bs_asset(page, page_name)
            except Exception as e:
                logger.warning(f"[composer] asset switch error: {str(e)[:120]}")

            if switched:
                if on_status:
                    on_status(f"✅ Đã chọn page: {page_name}")
                _random_delay(1.5, 2.5)
            else:
                logger.warning(
                    f"[composer] Could not switch to '{page_name}' via left panel"
                )
                if on_status:
                    on_status(f"⚠ Không thể chuyển sang '{page_name}' — tiếp tục với page hiện tại")

        # ── Step 4: open composer (inherits current BS page context) ─────────
        if on_status:
            on_status("🌐 Mở composer...")
        page.goto(CREATE_POST_URL, wait_until="domcontentloaded")

    def _is_correct_bs_page(self, page, page_id: str, page_name: str) -> bool:
        """
        Return True if Business Suite is currently showing the target page.

        Checks (fastest first):
          1. URL contains asset_id=<page_id> or page_id=<page_id>
          2. The top-left switcher button text contains the page name
        """
        try:
            # ── Check 1: numeric page_id in URL ─────────────────────────────
            if page_id and page_id.isdigit() and len(page_id) >= 6:
                if page_id in page.url:
                    logger.debug(f"[is_correct] page_id {page_id} found in URL")
                    return True

            # ── Check 2: switcher button text matches page name ──────────────
            if not page_name:
                return False
            name_lower = page_name.lower().strip()

            switcher_selectors = [
                'div[aria-label*="Chuyển tài sản"]',
                'div[aria-label*="Switch asset"]',
                '[role="combobox"]',
                '[aria-haspopup="listbox"]',
                '[aria-haspopup="dialog"]',
            ]
            for sel in switcher_selectors:
                try:
                    el = page.locator(sel).first
                    if el.count() == 0:
                        continue
                    txt = (el.text_content() or "").strip().lower()
                    if name_lower in txt:
                        logger.debug(f"[is_correct] page name found in switcher btn: '{txt[:60]}'")
                        return True
                except Exception:
                    pass

            # ── Check 3: page name visible anywhere in the left sidebar ──────
            try:
                # The active/selected item in the left panel usually has
                # aria-selected="true" or a highlighted style
                for sel in ['[aria-selected="true"]', '[aria-current="page"]']:
                    for el in page.locator(sel).all():
                        try:
                            txt = (el.text_content() or "").lower()
                            if name_lower in txt:
                                logger.debug(f"[is_correct] aria-selected match: '{txt[:60]}'")
                                return True
                        except Exception:
                            pass
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"[is_correct] error: {str(e)[:80]}")

        return False

    def _switch_bs_asset(self, page, page_name: str) -> bool:
        """
        Switch the active page in Business Suite by clicking the top-left
        asset-switcher dropdown, then clicking the target page directly from
        the list — no typing/search involved.

        Flow:
          1. Click the top-left switcher button to open the dropdown panel.
          2. Wait for the list to appear.
          3. Scan all items in the list, click the one matching page_name.

        Returns True if the page was successfully clicked.
        """
        _name_lower = page_name.lower().strip()

        # ── Step 1: click the switcher button to open the dropdown ───────────
        switcher_selectors = [
            'div[aria-label*="Chuyển tài sản"]',
            'div[aria-label*="Switch asset"]',
            'div[aria-label*="tài sản"]',
            'button[aria-label*="tài sản"]',
            '[role="combobox"]',
            '[aria-haspopup="listbox"]',
            '[aria-haspopup="dialog"]',
        ]
        opened = False
        for sel in switcher_selectors:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible(timeout=1500):
                    btn.click()
                    _random_delay(1.0, 2.0)
                    logger.debug(f"[switch] dropdown opened via: {sel}")
                    opened = True
                    break
            except Exception:
                pass

        if not opened:
            logger.warning("[switch] could not open asset switcher dropdown")
            return False

        # ── Step 2: click the matching page in the dropdown list ─────────────
        # Collect all candidates: role=option, listitem, li, a inside the panel.
        # Try exact text match first, then partial.
        candidate_selectors = [
            '[role="option"]',
            '[role="listitem"]',
            '[role="menuitem"]',
            'li',
        ]

        for exact in (True, False):
            try:
                loc = page.get_by_text(page_name, exact=exact).first
                if loc.count() > 0 and loc.is_visible(timeout=2000):
                    loc.click()
                    logger.info(f"[switch] ✅ {'exact' if exact else 'partial'} text match: '{page_name}'")
                    _random_delay(1.0, 2.0)
                    return True
            except Exception:
                pass

        for sel in candidate_selectors:
            try:
                for item in page.locator(sel).all():
                    try:
                        txt = (item.text_content() or "").strip()
                        if _name_lower in txt.lower() and item.is_visible(timeout=300):
                            item.click()
                            logger.info(f"[switch] ✅ via {sel}: '{txt[:80]}'")
                            _random_delay(1.0, 2.0)
                            return True
                    except Exception:
                        pass
            except Exception:
                pass

        # Nothing found — close the dropdown
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        logger.warning(f"[switch] page '{page_name}' not found in dropdown list")
        return False

    def post_content(
        self,
        folder_path: str,
        caption: str,
        scheduled_time: str,
        page_name: str,
        page_id: str = "",
        brand_name: str = "",
        cta_enabled: bool = False,
        share_to_story: bool = True,
        on_status: Optional[Callable] = None,
    ) -> bool:
        """
        Post a single content item to Facebook via Meta Business Suite.

        Args:
            folder_path: Path to folder with media files.
            caption: Post caption text.
            scheduled_time: "YYYY-MM-DD HH:MM" format.
            page_name: Target page name (for logging).
            page_id: Facebook numeric page ID — used to open the correct page composer.
            brand_name: For EXIF branding.
            cta_enabled: Add "Send Message" CTA button.
            share_to_story: Also share post as a Story (default True).
            on_status: Callback(status_text) for logging.

        Returns:
            True if successfully scheduled.
        """
        if not self._context:
            logger.error("Browser not initialized!")
            return False

        temp_dir = None
        page = None

        try:
            # Step 1: Brand media to temp
            if on_status:
                on_status(f"🏷 Processing metadata: {os.path.basename(folder_path)}")

            temp_dir = brand_media_to_temp(folder_path, brand_name)
            if not temp_dir:
                logger.error("Failed to prepare media files")
                return False

            _random_delay(1.0, 2.0)

            # Route: video folder → Reel Composer; images/text → Post Composer
            from core.content_scanner import folder_has_video
            if folder_has_video(folder_path):
                logger.info(f"🎬 Video detected — using Reel Composer for {os.path.basename(folder_path)}")
                page = self._context.new_page()
                page.set_default_timeout(30000)
                return self._post_reel_content(
                    page, temp_dir, folder_path, caption, scheduled_time,
                    page_id, page_name, cta_enabled, share_to_story, on_status,
                )

            # Step 2: Navigate to composer for the specific page
            if on_status:
                on_status(f"🌐 Opening composer for '{page_name}'...")

            page = self._context.new_page()
            page.set_default_timeout(30000)

            self._navigate_to_composer(page, page_id, page_name, on_status=on_status)
            _random_delay(3.0, 5.0)

            # Wait for composer to load
            page.wait_for_load_state("networkidle", timeout=20000)
            _random_delay(2.0, 3.0)

            if self._stop_event.is_set():
                return False

            # Step 3: Upload media
            if on_status:
                on_status(f"📎 Uploading media files...")

            upload_success = self._upload_media(page, temp_dir)
            if not upload_success:
                self._screenshot_error(page, "upload_failed")
                return False

            _random_delay(2.0, 4.0)

            if self._stop_event.is_set():
                return False

            # Step 4: Enter caption
            if on_status:
                on_status(f"📝 Entering caption...")

            if caption:
                self._enter_caption(page, caption)
                _random_delay(1.5, 3.0)

            # Step 5: CTA button
            if cta_enabled:
                if on_status:
                    on_status(f"💬 Adding CTA button...")
                self._toggle_cta(page)
                _random_delay(1.0, 2.0)

            # Step 5b: Share to Story
            if share_to_story:
                if on_status:
                    on_status("📢 Enabling Share to Story...")
                self._toggle_share_to_story(page)
                self._confirm_share_to_story_dialog(page)
                _random_delay(0.8, 1.5)

            if self._stop_event.is_set():
                return False

            # Step 6: Schedule
            if on_status:
                on_status(f"📅 Setting schedule: {scheduled_time}")

            schedule_success = self._set_schedule(page, scheduled_time)
            if not schedule_success:
                self._screenshot_error(page, "schedule_failed")
                return False

            _random_delay(2.0, 3.0)

            # Step 7: Confirm
            if on_status:
                on_status(f"✅ Confirming schedule...")

            confirm_success = self._click_schedule_button(page)
            if not confirm_success:
                self._screenshot_error(page, "confirm_failed")
                return False

            _random_delay(3.0, 5.0)

            if on_status:
                on_status(f"✅ Scheduled for {scheduled_time}")

            return True

        except Exception as e:
            self._last_error = str(e)[:300]
            logger.error(f"post_content error: {self._last_error}")
            if page:
                self._screenshot_error(page, "exception")
            return False

        finally:
            # Cleanup temp files
            if temp_dir:
                cleanup_temp(temp_dir)
            # Close page
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    def post_now(
        self,
        folder_path: str,
        caption: str,
        page_name: str = "",
        page_id: str = "",
        brand_name: str = "",
        cta_enabled: bool = False,
        share_to_story: bool = True,
        on_status: Optional[Callable] = None,
    ) -> bool:
        """
        Publish a post immediately (no scheduling) to Facebook via Meta Business Suite.

        Args:
            folder_path: Path to folder with media files.
            caption: Post caption text.
            page_name: Target page name (for logging).
            page_id: Facebook numeric page ID — used to open the correct page composer.
            brand_name: For EXIF branding.
            cta_enabled: Add "Send Message" CTA button.
            share_to_story: Also share post as a Story (default True).
            on_status: Callback(status_text) for logging.

        Returns:
            True if successfully published.
        """
        if not self._context:
            logger.error("Browser not initialized!")
            return False

        temp_dir = None
        page = None

        try:
            if on_status:
                on_status(f"🏷 Processing: {os.path.basename(folder_path)}")

            temp_dir = brand_media_to_temp(folder_path, brand_name)
            if not temp_dir:
                logger.error("Failed to prepare media files")
                return False

            _random_delay(1.0, 2.0)

            # Route: video folder → Reel Composer; images/text → Post Composer
            from core.content_scanner import folder_has_video
            if folder_has_video(folder_path):
                logger.info(f"🎬 Video detected — using Reel Composer for {os.path.basename(folder_path)}")
                page = self._context.new_page()
                page.set_default_timeout(30000)
                return self._post_reel_now(
                    page, temp_dir, folder_path, caption,
                    page_id, page_name, cta_enabled, share_to_story, on_status,
                )

            if on_status:
                on_status(f"🌐 Opening composer for '{page_name}'...")

            page = self._context.new_page()
            page.set_default_timeout(30000)
            self._navigate_to_composer(page, page_id, page_name, on_status=on_status)
            _random_delay(3.0, 5.0)
            page.wait_for_load_state("networkidle", timeout=20000)
            _random_delay(2.0, 3.0)

            if self._stop_event.is_set():
                return False

            if on_status:
                on_status("📎 Uploading media...")

            if not self._upload_media(page, temp_dir):
                self._screenshot_error(page, "upload_failed")
                return False

            _random_delay(2.0, 4.0)

            if self._stop_event.is_set():
                return False

            if caption:
                if on_status:
                    on_status("📝 Entering caption...")
                self._enter_caption(page, caption)
                _random_delay(1.5, 3.0)

            if cta_enabled:
                if on_status:
                    on_status("💬 Adding CTA button...")
                self._toggle_cta(page)
                _random_delay(1.0, 2.0)

            if share_to_story:
                if on_status:
                    on_status("📢 Enabling Share to Story...")
                self._toggle_share_to_story(page)
                self._confirm_share_to_story_dialog(page)
                _random_delay(0.8, 1.5)

            if self._stop_event.is_set():
                return False

            if on_status:
                on_status("🚀 Publishing now...")

            if not self._click_publish_now(page):
                self._screenshot_error(page, "publish_failed")
                return False

            _random_delay(3.0, 5.0)

            if on_status:
                on_status(f"✅ Published to {page_name or 'page'}!")

            return True

        except Exception as e:
            self._last_error = str(e)[:300]
            logger.error(f"post_now error: {self._last_error}")
            if page:
                self._screenshot_error(page, "post_now_exception")
            return False

        finally:
            if temp_dir:
                cleanup_temp(temp_dir)
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    def _click_publish_now(self, page) -> bool:
        """Click the Publish Now button (immediate post, no scheduling)."""
        try:
            publish_selectors = [
                'button:has-text("Publish")',
                'button:has-text("Đăng")',
                'button:has-text("Post")',
                '[aria-label="Publish"]',
                '[aria-label*="Đăng bài"]',
                'div[role="button"]:has-text("Publish")',
                'div[role="button"]:has-text("Đăng")',
                'div[role="button"]:has-text("Post")',
            ]
            for selector in publish_selectors:
                try:
                    el = page.locator(selector).first
                    if el.count() > 0 and el.is_visible():
                        el.click()
                        _random_delay(3.0, 5.0)
                        logger.info("  ✅ Publish Now clicked")
                        return True
                except Exception:
                    continue

            logger.error("Publish Now button not found")
            return False
        except Exception as e:
            logger.error(f"Publish Now error: {str(e)[:200]}")
            return False

    # ─── Browser Interactions ──────────────────────────────────────────────

    def _clear_existing_media(self, page) -> None:
        """
        Remove any media already attached to the composer (e.g. draft restored
        by Facebook from a previous session).  Clicks every visible delete/remove
        icon next to existing media items until none remain.
        """
        delete_selectors = [
            '[aria-label="Xóa"]',
            '[aria-label="Xoá"]',
            '[aria-label="Remove"]',
            '[aria-label="Delete"]',
            '[aria-label="Gỡ"]',
            '[aria-label="Close"]',
            '[aria-label="Đóng"]',
            # Link preview remove button
            '[aria-label*="Xóa"][role="button"]',
            '[aria-label*="Remove"][role="button"]',
        ]
        for attempt in range(10):  # max 10 items
            removed = False
            for sel in delete_selectors:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible(timeout=800):
                        btn.click()
                        _random_delay(0.5, 1.0)
                        logger.debug(f"[clear_media] removed item via '{sel}' (attempt {attempt+1})")
                        removed = True
                        break
                except Exception:
                    pass
            if not removed:
                break
        logger.debug("[clear_media] done")

    def _upload_media(self, page, temp_dir: str) -> bool:
        """Upload media files to Meta Business Suite composer.

        Two possible FB layouts:
          A) "Thêm ảnh" click → file chooser opens directly
          B) "Thêm ảnh" click → dropdown → "Tải lên từ máy tính" → file chooser

        Key: use Playwright native .click() (not JS .click()) so React
        synthetic events fire correctly. Always wrap the triggering click
        inside expect_file_chooser so the chooser is not missed.
        """
        try:
            media_files = sorted([
                os.path.join(temp_dir, f)
                for f in os.listdir(temp_dir)
                if Path(f).suffix.lower() in MEDIA_EXTS
            ])
            if not media_files:
                logger.error("No media files to upload")
                return False

            page.evaluate("window.scrollTo(0, 0)")
            _random_delay(0.5, 1.0)

            # Wait longer for composer iframe to fully render (cover/draft may
            # appear 1-3s AFTER the page load event fires).
            _random_delay(2.0, 3.0)

            # Clear any media already in the composer (FB restores drafts from
            # the previous session — cover images, link previews, etc.).
            self._clear_existing_media(page)
            _random_delay(0.5, 1.0)
            # Second pass — some items only appear after first removal animation
            self._clear_existing_media(page)

            # Candidate photo button texts (exact) and sub-option texts
            photo_texts = [
                "Thêm ảnh", "Thêm video", "Ảnh/video",
                "Add Photo", "Add photo", "Photo/video",
            ]
            upload_texts = [
                "Tải lên từ máy tính", "Upload from computer",
                "Tải ảnh lên", "Upload Photos", "Upload photo",
                "Upload", "From computer", "Ảnh từ máy tính",
            ]

            # Debug: screenshot before upload to see what's in composer
            self._screenshot_error(page, "before_upload")

            # Find the photo button locator using Playwright (not JS)
            photo_loc = None
            for txt in photo_texts:
                loc = page.get_by_text(txt, exact=True).first
                try:
                    if loc.count() > 0 and loc.is_visible(timeout=1000):
                        photo_loc = loc
                        logger.debug(f"  Found photo button: '{txt}'")
                        break
                except Exception:
                    continue

            if photo_loc is None:
                logger.error("Upload failed — photo button not found on page")
                return False

            # ── M2: Layout A — click triggers file chooser directly ───────
            # Headless mode needs longer timeout (no GPU rendering)
            try:
                with page.expect_file_chooser(timeout=8000) as fc_info:
                    photo_loc.click()
                fc_info.value.set_files(media_files)
                logger.info(f"  📎 M2 (direct): {len(media_files)} files uploaded")
                _random_delay(2.0, 4.0)
                return True
            except Exception:
                pass  # Layout B — dropdown opened instead

            # ── M3: Layout B — dropdown opened, find sub-option ──────────
            _random_delay(0.8, 1.5)

            sub_loc = None
            for txt in upload_texts:
                loc = page.get_by_text(txt, exact=True).first
                try:
                    if loc.count() > 0 and loc.is_visible(timeout=2000):
                        sub_loc = loc
                        logger.debug(f"  Found sub-option: '{txt}'")
                        break
                except Exception:
                    continue

            if sub_loc is not None:
                try:
                    with page.expect_file_chooser(timeout=10000) as fc_info:
                        sub_loc.click()
                    fc_info.value.set_files(media_files)
                    logger.info(f"  📎 M3 (dropdown): {len(media_files)} files uploaded")
                    _random_delay(2.0, 4.0)
                    return True
                except Exception as e3:
                    logger.debug(f"  M3 chooser failed: {e3}")
            else:
                # Re-click photo button to open dropdown again, then retry sub-options
                logger.debug("  Sub-option not visible, re-opening dropdown...")
                try:
                    photo_loc.click()
                    _random_delay(1.0, 1.5)
                    for txt in upload_texts:
                        loc = page.get_by_text(txt, exact=True).first
                        try:
                            if loc.count() > 0 and loc.is_visible(timeout=2000):
                                with page.expect_file_chooser(timeout=10000) as fc_info:
                                    loc.click()
                                fc_info.value.set_files(media_files)
                                logger.info(f"  📎 M3b: {len(media_files)} files via '{txt}'")
                                _random_delay(2.0, 4.0)
                                return True
                        except Exception:
                            continue
                except Exception:
                    pass

            logger.error("Upload failed — no method succeeded")
            return False

        except Exception as e:
            logger.error(f"Upload error: {str(e)[:200]}")
            return False

    def _enter_caption(self, page, caption: str):
        """Enter caption text into the composer."""
        try:
            # Try multiple selectors for the text area
            caption_selectors = [
                '[aria-label*="Write something"]',
                '[aria-label*="Viết gì đó"]',
                '[aria-label*="What\'s on your mind"]',
                '[role="textbox"]',
                'div[contenteditable="true"]',
            ]

            for selector in caption_selectors:
                try:
                    el = page.locator(selector).first
                    if el.count() > 0 and el.is_visible():
                        el.click()
                        _random_delay(0.5, 1.0)

                        # Type with human-like speed (but batch for long captions)
                        if len(caption) > 200:
                            # Paste for long captions
                            page.keyboard.insert_text(caption)
                        else:
                            # Type character by character for short captions
                            for char in caption:
                                page.keyboard.type(char, delay=random.randint(20, 60))
                                if random.random() < 0.05:
                                    _random_delay(0.2, 0.5)

                        logger.info(f"  📝 Caption: {len(caption)} chars")
                        return
                except Exception:
                    continue

            logger.warning("Could not find caption input")
        except Exception as e:
            logger.error(f"Caption error: {str(e)[:200]}")

    def _toggle_cta(self, page):
        """
        Set 'Gửi tin nhắn' (Send Message) in the 'Nhãn nút' dropdown.

        UI: The composer has a "Nút" section with a "Nhãn nút" dropdown
        defaulting to "Không dùng nút". We must open that dropdown and
        select "Gửi tin nhắn" / "Send Message".

        Flow:
          1. Try native <select> — call select_option() directly.
          2. Find the "Không dùng nút" / "Nhãn nút" dropdown and click it.
          3. Click "Gửi tin nhắn" in the opened list.
        """
        try:
            _random_delay(0.5, 1.0)

            # ── Strategy 1: native <select> ──────────────────────────────────
            select_targets = ["Gửi tin nhắn", "Send Message", "Send message",
                              "Nhận tin nhắn", "Get messages"]
            try:
                for sel_el in page.locator("select").all():
                    try:
                        opts = sel_el.locator("option").all_text_contents()
                        match = next(
                            (o for o in opts
                             if any(t.lower() in o.lower() for t in select_targets)),
                            None,
                        )
                        if match:
                            sel_el.select_option(label=match)
                            _random_delay(0.5, 1.0)
                            logger.info(f"  💬 CTA via <select>: '{match.strip()}'")
                            return
                    except Exception:
                        pass
            except Exception:
                pass

            # ── Strategy 2: click the "Nhãn nút" / "Không dùng nút" dropdown ─
            # Find the dropdown by its current value text or its label
            dropdown_triggers = [
                # Current value shown in the dropdown
                "Không dùng nút",
                "No button",
                "None",
            ]
            label_anchors = [
                # Section labels near the dropdown
                "Nhãn nút",
                "Button label",
                "Nút",
                "Button",
            ]

            dropdown_clicked = False

            # Try clicking by current value text
            for txt in dropdown_triggers:
                try:
                    loc = page.get_by_text(txt, exact=True).first
                    if loc.count() > 0 and loc.is_visible(timeout=1500):
                        loc.click()
                        _random_delay(0.8, 1.5)
                        logger.debug(f"  💬 Opened dropdown via value text: '{txt}'")
                        dropdown_clicked = True
                        break
                except Exception:
                    pass

            # Try finding the label then clicking the adjacent dropdown
            if not dropdown_clicked:
                for lbl_txt in label_anchors:
                    try:
                        lbl = page.get_by_text(lbl_txt, exact=True).first
                        if not (lbl.count() > 0 and lbl.is_visible(timeout=1000)):
                            continue
                        # Walk up ancestors to find the container, then the dropdown
                        for levels in range(1, 5):
                            ancestor = lbl
                            for _ in range(levels):
                                ancestor = ancestor.locator("..")
                            for dd_sel in ["select", '[role="combobox"]',
                                           '[role="listbox"]', '[role="button"]',
                                           '[aria-haspopup]']:
                                try:
                                    dd = ancestor.locator(dd_sel).first
                                    if dd.count() > 0 and dd.is_visible(timeout=500):
                                        dd.click()
                                        _random_delay(0.8, 1.5)
                                        logger.debug(
                                            f"  💬 Opened dropdown via label '{lbl_txt}' → {dd_sel}"
                                        )
                                        dropdown_clicked = True
                                        break
                                except Exception:
                                    pass
                            if dropdown_clicked:
                                break
                        if dropdown_clicked:
                            break
                    except Exception:
                        pass

            if not dropdown_clicked:
                logger.warning("  💬 Could not open 'Nhãn nút' dropdown")
                self._screenshot_error(page, "cta_dropdown_missing")
                return

            # ── Strategy 3: click the target option in the opened list ────────
            for txt in select_targets:
                try:
                    loc = page.get_by_text(txt, exact=True).first
                    if loc.count() > 0 and loc.is_visible(timeout=3000):
                        loc.click()
                        _random_delay(0.5, 1.0)
                        logger.info(f"  💬 CTA selected: '{txt}'")
                        return
                except Exception:
                    pass

            # Partial match across all option-like elements
            for opt_sel in ['[role="option"]', 'li', '[role="menuitem"]']:
                try:
                    for el in page.locator(opt_sel).all():
                        try:
                            txt = (el.text_content() or "").strip()
                            if any(t.lower() in txt.lower() for t in select_targets):
                                if el.is_visible(timeout=300):
                                    el.click()
                                    _random_delay(0.5, 1.0)
                                    logger.info(f"  💬 CTA via option element: '{txt}'")
                                    return
                        except Exception:
                            pass
                except Exception:
                    pass

            logger.warning("  💬 'Gửi tin nhắn' option not found after opening dropdown")
            self._screenshot_error(page, "cta_option_missing")

        except Exception as e:
            logger.error(f"CTA error: {str(e)[:200]}")

    def _set_schedule(self, page, scheduled_time: str) -> bool:
        """
        Enable "Đặt ngày và giờ" toggle then pick date/time on Facebook.

        FB Business Suite layout (Vietnamese):
          [Lên lịch]            [Đặt ngày và giờ  ●]
          [ 📅 12 Tháng 4, 2026 ]  [ 🕐 15:38 ]
          [ Thời điểm hoạt động tích cực ]
        """
        try:
            parts = scheduled_time.strip().split(" ")
            date_str = parts[0]
            time_str = parts[1] if len(parts) > 1 else "08:00"

            year_t, month_t, day_t = (int(x) for x in date_str.split("-"))
            hour_t, min_t = (int(x) for x in time_str.split(":"))

            # ── Step 1: Enable toggle ─────────────────────────────────────────
            toggle_ok = self._enable_schedule_toggle(page)
            _random_delay(1.5, 2.0)
            self._screenshot_error(page, "schedule_after_toggle")
            if not toggle_ok:
                logger.error("  📅 Schedule toggle could not be enabled")
                return False

            # ── Step 2: Set date via calendar ─────────────────────────────────
            ok = self._pick_calendar_date(page, year_t, month_t, day_t)
            if not ok:
                logger.error("  📅 Date picking failed")
                self._screenshot_error(page, "schedule_date_fail")
                return False
            _random_delay(0.8, 1.2)

            # ── Step 3: Set time ──────────────────────────────────────────────
            time_fmt = f"{hour_t:02d}:{min_t:02d}"
            self._fill_time_field(page, time_fmt)
            _random_delay(0.5, 1.0)

            logger.info(f"  📅 Schedule set: {scheduled_time}")
            return True

        except Exception as e:
            logger.error(f"Schedule error: {str(e)[:200]}")
            self._screenshot_error(page, "schedule_exception")
            return False

    def _enable_schedule_toggle(self, page) -> bool:
        """
        Enable the 'Đặt ngày và giờ' switch and verify it turned ON.
        Returns True if the toggle is now enabled (date button appeared).

        Uses JS to find the switch closest to "Đặt ngày và giờ" text and
        simulates a real mouse click via Playwright for React compatibility.
        """
        def _date_button_visible() -> bool:
            """True if a month+year date button is visible (toggle is ON)."""
            return page.evaluate("""() => {
                const monthPat = /Tháng|January|February|March|April|May|June|July|August|September|October|November|December/i;
                const yearPat = /20\\d{2}/;
                const all = document.querySelectorAll('button, [role="button"]');
                for (const el of all) {
                    const txt = (el.textContent || '').trim();
                    if (monthPat.test(txt) && yearPat.test(txt) && txt.length < 50) return true;
                }
                return false;
            }""")

        # Already ON?
        if _date_button_visible():
            logger.info("  📅 Schedule toggle already ON")
            return True

        # ── Strategy 1: JS walk from "Đặt ngày và giờ" text to nearest switch ──
        clicked = page.evaluate("""() => {
            const keywords = ['đặt ngày và giờ', 'set date and time', 'schedule date'];
            // Walk all text nodes to find the label
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                const t = (node.textContent || '').trim().toLowerCase();
                if (keywords.some(k => t.includes(k))) {
                    // Found the label — walk up to find nearest [role="switch"]
                    let el = node.parentElement;
                    for (let i = 0; i < 10; i++) {
                        if (!el) break;
                        const sw = el.querySelector('[role="switch"]');
                        if (sw) {
                            const rect = sw.getBoundingClientRect();
                            return {found: true, x: rect.x + rect.width/2, y: rect.y + rect.height/2,
                                    checked: sw.getAttribute('aria-checked')};
                        }
                        el = el.parentElement;
                    }
                }
            }
            return {found: false};
        }""")

        logger.info(f"  📅 Toggle JS result: {clicked}")

        if clicked and clicked.get("found"):
            if clicked.get("checked") == "true":
                logger.info("  📅 Toggle already aria-checked=true")
                return True
            # Click at the exact coordinates using Playwright mouse
            x, y = clicked["x"], clicked["y"]
            page.mouse.click(x, y)
            _random_delay(1.0, 1.5)
            if _date_button_visible():
                logger.info(f"  📅 Toggle ON (coord click at {x:.0f},{y:.0f})")
                return True
            logger.warning(f"  📅 Coord click at {x:.0f},{y:.0f} — date button not visible yet")

        # ── Strategy 2: Playwright get_by_text + ancestor switch ──
        for label_text in ["Đặt ngày và giờ", "Set date and time"]:
            try:
                label_loc = page.get_by_text(label_text, exact=False).first
                if label_loc.count() == 0 or not label_loc.is_visible(timeout=1500):
                    continue
                # Find switch in same row container (walk up via XPath)
                for depth in range(1, 8):
                    ancestor = label_loc.locator(f"xpath={'/..' * depth}").first
                    if ancestor.count() == 0:
                        break
                    sw = ancestor.locator('[role="switch"]').first
                    if sw.count() > 0 and sw.is_visible(timeout=300):
                        checked = sw.get_attribute("aria-checked")
                        if checked == "true":
                            logger.info(f"  📅 Toggle already ON (depth={depth})")
                            return True
                        sw.scroll_into_view_if_needed()
                        sw.click()
                        _random_delay(1.0, 1.5)
                        if _date_button_visible():
                            logger.info(f"  📅 Toggle ON via Playwright click (depth={depth})")
                            return True
                        break
                if _date_button_visible():
                    return True
            except Exception as e:
                logger.debug(f"  📅 Strategy 2 ({label_text}): {e}")

        # ── Strategy 3: Try every [role="switch"] that is NOT the Ads/Promote toggle ──
        switches = page.locator('[role="switch"]').all()
        logger.info(f"  📅 Total switches on page: {len(switches)}")
        for i, sw in enumerate(switches):
            try:
                if not sw.is_visible(timeout=300):
                    continue
                checked = sw.get_attribute("aria-checked")
                # Get text near this switch to filter out the Ads toggle
                sw_eh = sw.element_handle()
                near = page.evaluate("""(el) => {
                    let node = el;
                    for (let i = 0; i < 4; i++) {
                        node = node.parentElement;
                        if (!node) break;
                        const txt = node.textContent || '';
                        if (txt.trim().length > 0 && txt.length < 300) return txt.toLowerCase();
                    }
                    return '';
                }""", sw_eh) if sw_eh else ""

                is_ads = any(k in near for k in ["quảng bá", "ads ", "promote", "boost"])
                logger.info(f"  📅 Switch[{i}] checked={checked} is_ads={is_ads} near={near[:60]!r}")

                if is_ads:
                    continue  # skip Ads toggle

                if checked == "true":
                    logger.info(f"  📅 Switch[{i}] already ON")
                    return True

                sw.scroll_into_view_if_needed()
                sw.click()
                _random_delay(1.0, 1.5)
                if _date_button_visible():
                    logger.info(f"  📅 Toggle ON via Switch[{i}]")
                    return True
            except Exception as e:
                logger.debug(f"  📅 Switch[{i}] error: {e}")

        logger.error("  📅 Could not enable schedule toggle")
        return False

    def _pick_calendar_date(self, page, year: int, month: int, day: int) -> bool:
        """
        Set the schedule date by clicking the date button then TYPING the date.

        After clicking the date button in Meta Business Suite, the field becomes
        an editable text input — no need to navigate a calendar grid at all.
        We Ctrl+A and type the date in DD/MM/YYYY format, then Tab away.

        ROOT CAUSE NOTE: The Meta Business Suite composer runs inside an <iframe>.
        page.evaluate() only runs on the main frame → sees nothing inside the iframe.
        Playwright locators work cross-frame automatically — use ONLY Playwright APIs.
        """
        VI_MONTHS = {
            1: "Tháng 1", 2: "Tháng 2", 3: "Tháng 3", 4: "Tháng 4",
            5: "Tháng 5", 6: "Tháng 6", 7: "Tháng 7", 8: "Tháng 8",
            9: "Tháng 9", 10: "Tháng 10", 11: "Tháng 11", 12: "Tháng 12",
        }

        # Date string to type (DD/MM/YYYY — Vietnamese locale)
        date_str = f"{day:02d}/{month:02d}/{year}"
        logger.info(f"  📅 Will type date: {date_str}")

        # ── Step 1: Click the date button to make it editable ─────────────────
        # After clicking, the date field turns into a text input that accepts typing.
        # The button displays today's date like "12 Tháng 4, 2026".
        from datetime import date as _date
        today = _date.today()
        cur_vi_mo = VI_MONTHS[today.month]

        date_search_texts = [
            f"{today.day} {cur_vi_mo}",  # "12 Tháng 4"
            cur_vi_mo,                    # "Tháng 4"
            str(today.year),              # "2026"
        ]

        clicked_btn = False
        for search_txt in date_search_texts:
            if clicked_btn:
                break
            try:
                locs = page.get_by_text(search_txt, exact=False).all()
                logger.info(f"  📅 Searching date btn '{search_txt}': {len(locs)} candidates")
                for loc in locs:
                    try:
                        box = loc.bounding_box()
                        if not box or box["width"] < 1 or box["height"] < 1:
                            continue
                        if box["width"] > 350 or box["height"] > 100:
                            continue
                        x = box["x"] + box["width"] / 2
                        y = box["y"] + box["height"] / 2
                        page.mouse.click(x, y)
                        _random_delay(0.5, 0.8)
                        clicked_btn = True
                        logger.info(f"  📅 Clicked date button at ({x:.0f},{y:.0f})")
                        break
                    except Exception as e:
                        logger.debug(f"  📅 Date btn click error: {e}")
            except Exception as e:
                logger.debug(f"  📅 Search '{search_txt}' error: {e}")

        if not clicked_btn:
            # Fallback: Tab from schedule toggle to reach the date input
            try:
                sw = page.locator('[role="switch"][aria-checked="true"]').first
                if sw.is_visible(timeout=1000):
                    sw.focus()
                    page.keyboard.press("Tab")
                    _random_delay(0.3, 0.5)
                    clicked_btn = True
                    logger.info("  📅 Tabbed to date field from toggle")
            except Exception as e:
                logger.debug(f"  📅 Tab fallback error: {e}")

        if not clicked_btn:
            logger.warning("  📅 Could not find/click date button")
            self._screenshot_error(page, "schedule_datebtn_fail")
            return False

        # ── Step 2: Type the date into the focused input ──────────────────────
        # Select all existing text then type the new date character by character
        # so React onChange events fire correctly.
        _random_delay(0.3, 0.5)
        try:
            page.keyboard.press("Control+a")
            _random_delay(0.1, 0.2)
            page.keyboard.type(date_str, delay=80)
            _random_delay(0.3, 0.5)
            page.keyboard.press("Enter")
            _random_delay(0.4, 0.6)
            # Tab once so focus moves to the time input (next field in tab order)
            page.keyboard.press("Tab")
            _random_delay(0.3, 0.5)
            logger.info(f"  📅 Typed date: {date_str}, tabbed to time field")
        except Exception as e:
            logger.warning(f"  📅 Date typing error: {e}")
            self._screenshot_error(page, "schedule_datetype_fail")
            return False

        self._screenshot_error(page, "schedule_date_typed")
        logger.info(f"  📅 Date {date_str} set successfully")
        return True

    # ═══════════════════════════════════════════════════════════════════════
    # REEL / VIDEO POSTING (Facebook Reel Composer)
    # ═══════════════════════════════════════════════════════════════════════

    def _navigate_to_reel_composer(self, page, page_id: str, page_name: str = "",
                                   on_status=None) -> None:
        """Navigate to the Facebook Reel Composer for the target page."""
        biz_id = self._business_id
        if not biz_id:
            biz_id = self._resolve_business_id(page) or ""
        url = (
            f"https://business.facebook.com/latest/reels_composer/"
            f"?asset_id={page_id}&business_id={biz_id}&ref=biz_web_home_create_reel"
        )
        if on_status:
            on_status(f"🎬 Opening Reel Composer for '{page_name}'...")
        logger.info(f"  🎬 Navigating to Reel Composer: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        _random_delay(2.0, 3.5)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        _random_delay(1.5, 2.5)

    def _reel_upload_video(self, page, temp_dir: str, on_status=None) -> bool:
        """Upload video file(s) via the Reel Composer file chooser."""
        video_files = sorted([
            os.path.join(temp_dir, f)
            for f in os.listdir(temp_dir)
            if Path(f).suffix.lower() in {".mp4", ".mov"}
        ])
        if not video_files:
            logger.error("  🎬 No video files found in temp dir")
            return False

        logger.info(f"  🎬 Uploading video: {[os.path.basename(v) for v in video_files]}")
        if on_status:
            on_status("📹 Uploading video...")

        self._screenshot_error(page, "reel_before_upload")

        # Try multiple selectors for the "Thêm video" / "Add video" button
        upload_btn_texts = ["Thêm video", "Add video", "Add Video", "Tải lên", "Upload"]
        upload_btn_selectors = [
            '[aria-label*="Thêm video"]', '[aria-label*="Add video"]',
            'button:has-text("Thêm video")', 'button:has-text("Add video")',
            'input[type="file"]',
        ]

        # Method 1: expect_file_chooser via button text click
        for txt in upload_btn_texts:
            try:
                btn = page.get_by_text(txt, exact=True).first
                if btn.is_visible(timeout=2000):
                    with page.expect_file_chooser(timeout=10000) as fc_info:
                        btn.click()
                    fc_info.value.set_files(video_files)
                    logger.info(f"  🎬 Video set via button text '{txt}'")
                    break
            except Exception as e:
                logger.debug(f"  🎬 btn text '{txt}' failed: {e}")
        else:
            # Method 2: selector-based
            for sel in upload_btn_selectors:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible(timeout=2000):
                        if sel == 'input[type="file"]':
                            el.set_input_files(video_files)
                        else:
                            with page.expect_file_chooser(timeout=10000) as fc_info:
                                el.click()
                            fc_info.value.set_files(video_files)
                        logger.info(f"  🎬 Video set via selector '{sel}'")
                        break
                except Exception as e:
                    logger.debug(f"  🎬 selector '{sel}' failed: {e}")
            else:
                logger.error("  🎬 Could not find upload button")
                self._screenshot_error(page, "reel_upload_btn_fail")
                return False

        # Wait for upload to complete — poll for progress indicator disappearance
        if on_status:
            on_status("⏳ Waiting for video upload to complete...")
        logger.info("  🎬 Waiting for upload completion (max 180s)...")
        deadline = time.time() + 180
        while time.time() < deadline:
            _random_delay(3.0, 4.0)
            # Check for progress bar / spinner
            uploading = False
            for prog_sel in ['[role="progressbar"]', '[aria-label*="Uploading"]',
                             '[aria-label*="Đang tải"]', 'div[class*="progress"]']:
                try:
                    if page.locator(prog_sel).first.is_visible(timeout=500):
                        uploading = True
                        break
                except Exception:
                    pass
            if not uploading:
                logger.info("  🎬 Upload appears complete")
                break
        else:
            logger.warning("  🎬 Upload wait timeout — proceeding anyway")

        _random_delay(2.0, 3.0)
        self._screenshot_error(page, "reel_after_upload")
        return True

    def _reel_enter_caption(self, page, caption: str) -> None:
        """Enter description/caption in the Reel Composer."""
        if not caption:
            return
        caption_selectors = [
            '[aria-label*="Mô tả"]', '[aria-label*="Description"]',
            '[aria-label*="description"]', '[placeholder*="Mô tả"]',
            '[placeholder*="description"]', 'textarea[name*="description"]',
            'div[contenteditable="true"]', '[role="textbox"]',
        ]
        for sel in caption_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=2000):
                    el.click()
                    _random_delay(0.3, 0.5)
                    if len(caption) > 200:
                        page.keyboard.insert_text(caption)
                    else:
                        for ch in caption:
                            page.keyboard.type(ch, delay=random.randint(20, 60))
                            if random.random() < 0.05:
                                _random_delay(0.2, 0.5)
                    logger.info(f"  🎬 Caption entered via '{sel}'")
                    _random_delay(0.5, 1.0)
                    return
            except Exception as e:
                logger.debug(f"  🎬 caption sel '{sel}' failed: {e}")
        logger.warning("  🎬 Could not find caption field")

    def _reel_toggle_cta(self, page) -> None:
        """Add 'Send Message' CTA button in the Reel Composer."""
        cta_btn_texts = ["Thêm nút", "Add button", "Add Button"]
        for txt in cta_btn_texts:
            try:
                btn = page.get_by_text(txt, exact=False).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    _random_delay(0.8, 1.5)
                    break
            except Exception:
                pass

        # Select "Send Message" option
        msg_texts = ["Nhận tin nhắn", "Send Message", "Gửi tin nhắn"]
        for txt in msg_texts:
            try:
                opt = page.get_by_text(txt, exact=False).first
                if opt.is_visible(timeout=2000):
                    opt.click()
                    _random_delay(0.5, 1.0)
                    logger.info("  🎬 CTA 'Send Message' selected")
                    return
            except Exception:
                pass
        logger.warning("  🎬 Could not find CTA Send Message option")

    def _reel_set_thumbnail(self, page, temp_dir: str, folder_path: str) -> None:
        """Select thumbnail: upload image if available, else use suggested thumbnail."""
        image_files = sorted([
            os.path.join(temp_dir, f)
            for f in os.listdir(temp_dir)
            if Path(f).suffix.lower() in {".jpg", ".jpeg", ".png"}
        ])

        self._screenshot_error(page, "reel_before_thumbnail")

        if image_files:
            # Upload custom thumbnail image
            upload_texts = ["Tải hình ảnh lên", "Upload image", "Upload Image",
                            "Choose image", "Chọn hình ảnh"]
            for txt in upload_texts:
                try:
                    btn = page.get_by_text(txt, exact=False).first
                    if btn.is_visible(timeout=2000):
                        with page.expect_file_chooser(timeout=8000) as fc_info:
                            btn.click()
                        fc_info.value.set_files([image_files[0]])
                        logger.info(f"  🎬 Thumbnail uploaded: {os.path.basename(image_files[0])}")
                        _random_delay(1.5, 2.5)
                        self._screenshot_error(page, "reel_thumbnail_uploaded")
                        return
                except Exception as e:
                    logger.debug(f"  🎬 thumbnail upload btn '{txt}' failed: {e}")
            logger.warning("  🎬 Could not upload thumbnail image, falling back to suggestion")

        # No image or upload failed — use suggested thumbnail
        suggest_texts = ["Chọn hình thu nhỏ gợi ý", "Suggested thumbnails",
                         "Choose a thumbnail", "Hình thu nhỏ gợi ý"]
        for txt in suggest_texts:
            try:
                btn = page.get_by_text(txt, exact=False).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    _random_delay(1.0, 2.0)
                    logger.info("  🎬 Opened suggested thumbnails panel")
                    break
            except Exception:
                pass

        # Click the first suggested thumbnail
        _random_delay(1.0, 1.5)
        suggested_selectors = [
            '[aria-label*="hình thu nhỏ"]', '[aria-label*="thumbnail"]',
            'img[class*="thumbnail"]', 'div[class*="thumbnail"] img',
        ]
        for sel in suggested_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=2000):
                    el.click()
                    logger.info(f"  🎬 First suggested thumbnail selected via '{sel}'")
                    _random_delay(0.5, 1.0)
                    self._screenshot_error(page, "reel_thumbnail_suggested")
                    return
            except Exception:
                pass

        # Last resort: click the first image-like element near a thumbnail area
        try:
            imgs = page.locator('img').all()
            for img in imgs[:10]:
                box = img.bounding_box()
                if box and 40 < box["width"] < 200:
                    page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                    logger.info("  🎬 Clicked first candidate thumbnail image")
                    _random_delay(0.5, 1.0)
                    return
        except Exception:
            pass

        logger.warning("  🎬 Could not select thumbnail")

    def _reel_enter_tags(self, page, temp_dir: str, folder_path: str) -> None:
        """Enter tags from key.txt / key.text file if present."""
        tags_content = ""
        for search_dir in [temp_dir, folder_path]:
            for fname in ["key.txt", "key.text", "tags.txt"]:
                try:
                    fpath = os.path.join(search_dir, fname)
                    if os.path.isfile(fpath):
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            tags_content = f.read().strip()
                        if tags_content:
                            logger.info(f"  🎬 Tags loaded from {fpath}: {tags_content[:60]}")
                            break
                except Exception:
                    pass
            if tags_content:
                break

        if not tags_content:
            logger.info("  🎬 No key.txt found — skipping tags")
            return

        tag_selectors = [
            '[aria-label*="Thẻ"]', '[aria-label*="Tag"]', '[aria-label*="tag"]',
            '[placeholder*="Thẻ"]', '[placeholder*="tag"]',
            'input[name*="tag"]', 'div[data-testid*="tag"]',
        ]
        for sel in tag_selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=2000):
                    el.click()
                    _random_delay(0.3, 0.5)
                    page.keyboard.type(tags_content, delay=30)
                    _random_delay(0.3, 0.5)
                    logger.info(f"  🎬 Tags entered via '{sel}'")
                    return
            except Exception as e:
                logger.debug(f"  🎬 tag sel '{sel}' failed: {e}")
        logger.warning("  🎬 Could not find tags field — skipping")

    def _reel_click_next(self, page, step: int = 1) -> bool:
        """Click the 'Tiếp' (Next) button in the Reel Composer."""
        next_texts = ["Tiếp", "Next", "Continue"]
        for txt in next_texts:
            try:
                btn = page.get_by_text(txt, exact=True).first
                if btn.is_visible(timeout=3000):
                    btn.click()
                    logger.info(f"  🎬 Clicked Next (step {step})")
                    _random_delay(1.5, 2.5)
                    return True
            except Exception:
                pass
        # Fallback: find button with Next-like text
        for txt in next_texts:
            try:
                btn = page.locator(f'button:has-text("{txt}")').first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    logger.info(f"  🎬 Clicked Next button (step {step}) via button locator")
                    _random_delay(1.5, 2.5)
                    return True
            except Exception:
                pass
        logger.warning(f"  🎬 Next button not found (step {step})")
        self._screenshot_error(page, f"reel_next_fail_step{step}")
        return False

    def _reel_toggle_share_to_story(self, page, enabled: bool) -> None:
        """Toggle 'Share to Story' switch in the Reel Composer."""
        story_texts = [
            "Chia sẻ lên Tin của bạn", "Share to your Story",
            "Share to Story", "Chia sẻ lên Tin",
        ]
        for txt in story_texts:
            try:
                # Find the switch near this label
                label = page.get_by_text(txt, exact=False).first
                if label.is_visible(timeout=2000):
                    # Look for a sibling/ancestor switch
                    switch = None
                    for sw_sel in ['[role="switch"]', 'input[type="checkbox"]']:
                        try:
                            sw = page.locator(sw_sel).first
                            if sw.is_visible(timeout=1000):
                                switch = sw
                                break
                        except Exception:
                            pass
                    if switch:
                        checked = switch.get_attribute("aria-checked") or ""
                        currently_on = checked.lower() == "true"
                        if enabled and not currently_on:
                            box = switch.bounding_box()
                            if box:
                                page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                                logger.info("  🎬 Share to Story toggled ON")
                        elif not enabled and currently_on:
                            box = switch.bounding_box()
                            if box:
                                page.mouse.click(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                                logger.info("  🎬 Share to Story toggled OFF")
                        else:
                            logger.info(f"  🎬 Share to Story already {'ON' if currently_on else 'OFF'}")
                        _random_delay(0.5, 1.0)
                        return
            except Exception:
                pass
        logger.warning("  🎬 Could not find Share to Story toggle")

    def _reel_click_share(self, page) -> bool:
        """Click the final 'Chia sẻ' / 'Share' button to publish/schedule the reel."""
        share_texts = ["Chia sẻ", "Share", "Publish", "Đăng"]
        for txt in share_texts:
            try:
                btn = page.get_by_text(txt, exact=True).first
                if btn.is_visible(timeout=3000):
                    btn.click()
                    logger.info(f"  🎬 Clicked Share: '{txt}'")
                    _random_delay(3.0, 5.0)
                    return True
            except Exception:
                pass
        for txt in share_texts:
            try:
                btn = page.locator(f'button:has-text("{txt}")').first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    logger.info(f"  🎬 Clicked Share button: '{txt}'")
                    _random_delay(3.0, 5.0)
                    return True
            except Exception:
                pass
        logger.error("  🎬 Share button not found")
        self._screenshot_error(page, "reel_share_fail")
        return False

    def _post_reel_now(
        self,
        page,
        temp_dir: str,
        folder_path: str,
        caption: str,
        page_id: str,
        page_name: str,
        cta_enabled: bool,
        share_to_story: bool,
        on_status=None,
    ) -> bool:
        """Reel Composer flow for immediate post (no scheduling)."""
        try:
            self._navigate_to_reel_composer(page, page_id, page_name, on_status)

            if self._stop_event.is_set():
                return False

            if not self._reel_upload_video(page, temp_dir, on_status):
                return False

            if self._stop_event.is_set():
                return False

            if on_status:
                on_status("📝 Entering reel description...")
            self._reel_enter_caption(page, caption)
            _random_delay(1.0, 2.0)

            if cta_enabled:
                if on_status:
                    on_status("💬 Adding CTA button...")
                self._reel_toggle_cta(page)
                _random_delay(0.8, 1.5)

            if on_status:
                on_status("🖼 Setting thumbnail...")
            self._reel_set_thumbnail(page, temp_dir, folder_path)
            _random_delay(1.0, 2.0)

            if on_status:
                on_status("🏷 Entering tags...")
            self._reel_enter_tags(page, temp_dir, folder_path)
            _random_delay(0.5, 1.0)

            if self._stop_event.is_set():
                return False

            # Click Next (step 1)
            if on_status:
                on_status("➡ Continuing (step 1)...")
            self._reel_click_next(page, step=1)

            # Click Next (step 2)
            if on_status:
                on_status("➡ Continuing (step 2)...")
            self._reel_click_next(page, step=2)

            if share_to_story:
                if on_status:
                    on_status("📢 Enabling Share to Story...")
                self._reel_toggle_share_to_story(page, enabled=True)
                _random_delay(0.5, 1.0)

            if self._stop_event.is_set():
                return False

            if on_status:
                on_status("🚀 Publishing reel...")
            if not self._reel_click_share(page):
                return False

            if on_status:
                on_status(f"✅ Reel published to {page_name}!")
            logger.info(f"  🎬 Reel published to {page_name}")
            return True

        except Exception as e:
            self._last_error = str(e)[:300]
            logger.error(f"_post_reel_now error: {self._last_error}")
            self._screenshot_error(page, "reel_now_exception")
            return False

    def _post_reel_content(
        self,
        page,
        temp_dir: str,
        folder_path: str,
        caption: str,
        scheduled_time: str,
        page_id: str,
        page_name: str,
        cta_enabled: bool,
        share_to_story: bool,
        on_status=None,
    ) -> bool:
        """Reel Composer flow for scheduled post."""
        try:
            self._navigate_to_reel_composer(page, page_id, page_name, on_status)

            if self._stop_event.is_set():
                return False

            if not self._reel_upload_video(page, temp_dir, on_status):
                return False

            if self._stop_event.is_set():
                return False

            if on_status:
                on_status("📝 Entering reel description...")
            self._reel_enter_caption(page, caption)
            _random_delay(1.0, 2.0)

            if cta_enabled:
                if on_status:
                    on_status("💬 Adding CTA button...")
                self._reel_toggle_cta(page)
                _random_delay(0.8, 1.5)

            if on_status:
                on_status("🖼 Setting thumbnail...")
            self._reel_set_thumbnail(page, temp_dir, folder_path)
            _random_delay(1.0, 2.0)

            if on_status:
                on_status("🏷 Entering tags...")
            self._reel_enter_tags(page, temp_dir, folder_path)
            _random_delay(0.5, 1.0)

            if self._stop_event.is_set():
                return False

            # Click Next (step 1)
            if on_status:
                on_status("➡ Continuing (step 1)...")
            self._reel_click_next(page, step=1)

            # Click Next (step 2)
            if on_status:
                on_status("➡ Continuing (step 2)...")
            self._reel_click_next(page, step=2)

            if share_to_story:
                if on_status:
                    on_status("📢 Enabling Share to Story...")
                self._reel_toggle_share_to_story(page, enabled=True)
                _random_delay(0.5, 1.0)

            if self._stop_event.is_set():
                return False

            # Set schedule (reuse existing scheduling UI logic)
            if on_status:
                on_status(f"📅 Setting schedule: {scheduled_time}")
            schedule_ok = self._set_schedule(page, scheduled_time)
            if not schedule_ok:
                self._screenshot_error(page, "reel_schedule_fail")
                logger.warning("  🎬 Schedule set failed — attempting to share anyway")

            _random_delay(1.5, 2.5)

            if on_status:
                on_status("🚀 Confirming reel schedule...")
            if not self._reel_click_share(page):
                return False

            if on_status:
                on_status(f"✅ Reel scheduled for {scheduled_time} on {page_name}!")
            logger.info(f"  🎬 Reel scheduled: {scheduled_time} → {page_name}")
            return True

        except Exception as e:
            self._last_error = str(e)[:300]
            logger.error(f"_post_reel_content error: {self._last_error}")
            self._screenshot_error(page, "reel_content_exception")
            return False

    def _fill_time_field(self, page, time_value: str) -> None:
        """
        Fill the time input (HH:MM) in the FB schedule section.

        FB's time input is a React-controlled input. Using inp.fill() sets the
        DOM value but does NOT fire React synthetic events → value reverts.
        Must use keyboard typing (character-by-character) to trigger onChange.

        The composer is inside an iframe, so Playwright locators work cross-frame.
        """
        filled = False

        def _type_into_input(inp) -> bool:
            """Click the input, select all, then keyboard-type the new value."""
            try:
                inp.scroll_into_view_if_needed()
                inp.click()
                _random_delay(0.1, 0.2)
                inp.press("Control+a")
                _random_delay(0.05, 0.1)
                # Type hour, Tab to minute sub-field, type minute (no Tab after)
                page.keyboard.type(hour_str, delay=80)
                _random_delay(0.1, 0.2)
                page.keyboard.press("Tab")
                _random_delay(0.1, 0.2)
                page.keyboard.type(min_str, delay=80)
                return True
            except Exception as e:
                logger.debug(f"  ⏰ _type_into_input error: {e}")
                return False

        # Parse hour/minute parts
        parts = time_value.split(":")
        hour_str = parts[0].zfill(2)   # "17"
        min_str  = parts[1].zfill(2) if len(parts) > 1 else "00"  # "00"

        # Strategy 0: type directly — _pick_calendar_date already tabbed focus
        # onto the time field. The field has two sub-fields: hour and minute,
        # separated by ":". Type hour digits, then Tab to jump to minute sub-field,
        # then type minute digits.
        try:
            page.keyboard.press("Control+a")
            _random_delay(0.05, 0.1)
            page.keyboard.type(hour_str, delay=80)   # type "17"
            _random_delay(0.15, 0.25)
            page.keyboard.press("Tab")               # jump to minute sub-field
            _random_delay(0.15, 0.25)
            page.keyboard.type(min_str, delay=80)    # type "00"
            _random_delay(0.2, 0.3)
            # Do NOT press Tab here — it would jump to the collaborator field
            logger.info(f"  ⏰ Time typed (hour Tab min): {hour_str}:{min_str}")
            filled = True
        except Exception as e:
            logger.debug(f"  ⏰ Direct type error: {e}")

        # Strategy 1: find by aria-label keywords (only if Strategy 0 failed)
        if not filled:
            for sel in [
                'input[aria-label*="giờ"]',
                'input[aria-label*="Giờ"]',
                'input[aria-label*="time"]',
                'input[aria-label*="Time"]',
                'input[type="time"]',
            ]:
                try:
                    inp = page.locator(sel).first
                    if inp.count() > 0 and inp.is_visible(timeout=800):
                        if _type_into_input(inp):
                            logger.info(f"  ⏰ Time set via '{sel}': {time_value}")
                            filled = True
                            break
                except Exception:
                    pass

        if not filled:
            # Strategy 2: find visible inputs whose current value looks like HH:MM
            try:
                all_inputs = page.locator('input').all()
                logger.info(f"  ⏰ Scanning {len(all_inputs)} inputs for time field...")
                for inp in all_inputs:
                    try:
                        if not inp.is_visible(timeout=300):
                            continue
                        val = inp.input_value() or ""
                        lbl = (inp.get_attribute("aria-label") or "").lower()
                        ph  = (inp.get_attribute("placeholder") or "").lower()
                        is_time = (
                            re.match(r'^\d{1,2}:\d{2}', val.strip()) or
                            "giờ" in lbl or "time" in lbl or "hour" in lbl or
                            "giờ" in ph  or "time" in ph  or "hh" in ph.lower()
                        )
                        logger.debug(f"  ⏰ input val={val!r} lbl={lbl!r} is_time={is_time}")
                        if is_time:
                            if _type_into_input(inp):
                                logger.info(f"  ⏰ Time set via value-scan (val={val!r}): {time_value}")
                                filled = True
                                break
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"  ⏰ input scan error: {e}")

        if not filled:
            # Strategy 3: Tab from current focus — after calendar closes, focus
            # is usually on the date input; one Tab reaches the time input.
            try:
                logger.info("  ⏰ Trying Tab+type approach for time field...")
                page.keyboard.press("Tab")
                _random_delay(0.2, 0.3)
                page.keyboard.press("Control+a")
                _random_delay(0.05, 0.1)
                page.keyboard.type(time_value, delay=50)
                _random_delay(0.1, 0.2)
                page.keyboard.press("Tab")
                logger.info(f"  ⏰ Time typed via Tab approach: {time_value}")
                filled = True
            except Exception as e:
                logger.debug(f"  ⏰ Tab approach error: {e}")

        if not filled:
            logger.warning(f"  ⏰ Could not fill time field: {time_value}")

    def _click_schedule_button(self, page) -> bool:
        """
        Click the final 'Lên lịch' / 'Schedule' confirm button.

        After setting date/time, the bottom action button changes from 'Đăng'
        to 'Lên lịch'. We press Escape first to close any open dropdowns
        (collaborator autocomplete, etc.), then find and click the button.
        """
        try:
            # Close any open dropdown/popup that might be covering the button
            page.keyboard.press("Escape")
            _random_delay(0.5, 0.8)

            confirm_selectors = [
                'button:has-text("Lên lịch")',
                'button:has-text("Schedule")',
                '[aria-label*="Lên lịch bài viết"]',
                '[aria-label*="Schedule post"]',
                'div[role="button"]:has-text("Lên lịch")',
                'div[role="button"]:has-text("Schedule")',
            ]

            for selector in confirm_selectors:
                try:
                    el = page.locator(selector).first
                    if el.count() > 0 and el.is_visible():
                        el.scroll_into_view_if_needed()
                        el.click()
                        _random_delay(3.0, 5.0)
                        logger.info("  ✅ Schedule confirmed")
                        return True
                except Exception:
                    continue

            # Last resort: any visible button whose text is exactly "Lên lịch"
            try:
                for btn in page.locator("button").all():
                    try:
                        txt = (btn.text_content() or "").strip()
                        if txt in ("Lên lịch", "Schedule") and btn.is_visible(timeout=300):
                            btn.click()
                            _random_delay(3.0, 5.0)
                            logger.info(f"  ✅ Schedule confirmed via fallback btn: '{txt}'")
                            return True
                    except Exception:
                        pass
            except Exception:
                pass

            logger.error("Schedule confirm button not found")
            return False

        except Exception as e:
            logger.error(f"Confirm error: {str(e)[:200]}")
            return False

    def _toggle_share_to_story(self, page) -> bool:
        """
        Enable "Chia sẻ lên Tin" / "Share to Stories" in the composer.

        Meta Business Suite shows a toggle or checkbox labelled "Chia sẻ lên Tin"
        (Vietnamese) or "Share to Stories" / "Also share as a story" (English).
        We look for it and ensure it is ON (checked).
        Returns True if the toggle was found (regardless of whether it changed state).
        """
        try:
            _random_delay(0.5, 1.0)

            story_labels = [
                "Chia sẻ lên Tin",
                "Chia sẻ lên tin",
                "Share to Stories",
                "Share to Story",
                "Also share as a story",
                "Also share to story",
                "Chia sẻ dưới dạng Tin",
                "Chia sẻ dưới dạng tin",
            ]

            for txt in story_labels:
                for exact in (True, False):
                    try:
                        loc = page.get_by_text(txt, exact=exact).first
                        if loc.count() > 0 and loc.is_visible(timeout=1500):
                            # Check if already enabled (look for a sibling/parent switch)
                            # Try to find associated checkbox or switch
                            parent = loc.locator("xpath=..").first
                            switch_loc = parent.locator('[role="switch"], input[type="checkbox"]').first
                            if switch_loc.count() > 0:
                                checked = switch_loc.get_attribute("aria-checked") or \
                                          switch_loc.get_attribute("checked") or ""
                                if str(checked).lower() not in ("true", "1"):
                                    switch_loc.click()
                                    _random_delay(0.5, 1.0)
                                    logger.info(f"  📢 Share to Story enabled via switch")
                            else:
                                # Click the text itself — it may be a label for a checkbox
                                loc.click()
                                _random_delay(0.5, 1.0)
                                logger.info(f"  📢 Share to Story clicked: '{txt}'")
                            return True
                    except Exception:
                        pass

            # Fallback: look for any switch whose accessible name mentions "Tin" / "Story"
            try:
                for sw in page.locator('[role="switch"]').all():
                    try:
                        lbl = (sw.get_attribute("aria-label") or "").lower()
                        if any(k in lbl for k in ("tin", "story", "stories")):
                            checked = sw.get_attribute("aria-checked") or ""
                            if str(checked).lower() not in ("true", "1"):
                                sw.click()
                                _random_delay(0.5, 1.0)
                            logger.info(f"  📢 Share to Story via aria-label switch: '{lbl}'")
                            return True
                    except Exception:
                        pass
            except Exception:
                pass

            logger.debug("  📢 'Chia sẻ lên Tin' toggle not found (may not be available)")
            return False

        except Exception as e:
            logger.error(f"Share to Story error: {str(e)[:200]}")
            return False

    def _confirm_share_to_story_dialog(self, page) -> bool:
        """
        After enabling Share to Story, Facebook may show a confirmation dialog:
          "Chia sẻ lên tin trên Facebook"
          [ Chia sẻ tin này ]  [ Luôn chia sẻ tin ]
          [Cancel]  [Confirm]

        We always click "Confirm" / "Xác nhận" to proceed.
        Returns True if dialog was found and confirmed.
        """
        try:
            _random_delay(1.0, 2.0)

            confirm_texts = ["Confirm", "Xác nhận", "OK"]
            for txt in confirm_texts:
                for exact in (True, False):
                    try:
                        loc = page.get_by_text(txt, exact=exact).first
                        if loc.count() > 0 and loc.is_visible(timeout=3000):
                            loc.click()
                            _random_delay(0.8, 1.5)
                            logger.info(f"  📢 Story dialog confirmed: '{txt}'")
                            return True
                    except Exception:
                        pass

            # Fallback: button with role=button
            for sel in [
                'button:has-text("Confirm")',
                'button:has-text("Xác nhận")',
                '[role="button"]:has-text("Confirm")',
                '[role="button"]:has-text("Xác nhận")',
            ]:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible(timeout=2000):
                        el.click()
                        _random_delay(0.8, 1.5)
                        logger.info(f"  📢 Story dialog confirmed via selector: '{sel}'")
                        return True
                except Exception:
                    pass

            return False
        except Exception as e:
            logger.error(f"confirm_share_to_story_dialog error: {str(e)[:200]}")
            return False

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _get_profile_dir(self) -> str:
        base = Path(__file__).parent.parent
        acct_id = self._account.get("id", 0)
        if acct_id:
            name = f"chrome_profile_poster_{acct_id}"
        else:
            name = "chrome_profile_poster"
        d = base / name
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def _do_login(self):
        """Login using FacebookLogin engine."""
        from core.fb_login import FacebookLogin
        tmp = self._context.new_page()
        try:
            login = FacebookLogin(tmp, self._account)
            success = login.ensure_logged_in()
            if not success:
                cookie_str = self._account.get("cookie", "")
                if cookie_str:
                    from core.cookie_handler import parse_cookie_string
                    cookies = parse_cookie_string(cookie_str)
                    self._inject_cookies_raw(cookies)
                else:
                    logger.warning("⚠ Login failed")
        except Exception as e:
            logger.warning(f"Login error: {str(e)[:100]}")
        finally:
            try:
                tmp.close()
            except Exception:
                pass

    def _inject_cookies(self):
        """Inject cookies from account cookie string."""
        cookie_str = self._account.get("cookie", "")
        if cookie_str:
            from core.cookie_handler import parse_cookie_string
            cookies = parse_cookie_string(cookie_str)
            self._inject_cookies_raw(cookies)

    def _inject_cookies_raw(self, cookies: dict):
        """Inject raw cookie dict via CDP."""
        if not self._context:
            return
        tmp = self._context.new_page()
        try:
            cdp = self._context.new_cdp_session(tmp)
            cdp.send("Network.clearBrowserCookies")
            for name, value in cookies.items():
                cdp.send("Network.setCookie", {
                    "name": name, "value": value,
                    "domain": ".facebook.com", "path": "/",
                    "httpOnly": True, "secure": True,
                })
            cdp.detach()
            tmp.goto("https://www.facebook.com/", wait_until="domcontentloaded")
            time.sleep(3)
        except Exception as e:
            logger.error(f"Cookie injection error: {str(e)[:100]}")
        finally:
            try:
                tmp.close()
            except Exception:
                pass

    def _screenshot_error(self, page, label: str):
        """Take screenshot for debugging."""
        try:
            debug_dir = Path(__file__).parent.parent / "debug_screenshots"
            debug_dir.mkdir(exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            path = debug_dir / f"error_{label}_{ts}.png"
            page.screenshot(path=str(path), full_page=False)
            logger.info(f"  📸 Debug screenshot: {path.name}")
        except Exception:
            pass

    def scan_managed_pages(
        self,
        on_status: Optional[Callable] = None,
    ) -> tuple:
        """
        Find pages this account manages and resolve the business_id.

        Returns (pages: List[Dict], business_id: str).
        business_id is also cached in self._business_id.
        """
        if not self._context:
            logger.error("Browser not initialized — call start() first")
            return [], ""

        # Resolve business_id during scan (fine here — no posting happening)
        if not self._business_id:
            if on_status:
                on_status("🔑 Đang lấy Business ID...")
            tmp_page = self._context.new_page()
            try:
                self._business_id = self._resolve_business_id(tmp_page)
            finally:
                try:
                    tmp_page.close()
                except Exception:
                    pass

        if self._business_id:
            logger.info(f"[scan] business_id = {self._business_id}")
        else:
            logger.warning("[scan] business_id not resolved — posting URLs may be incomplete")

        strategies = [
            ("🌐 facebook.com/pages?category=your_pages", self._scan_via_browser),
        ]

        for label, fn in strategies:
            if on_status:
                on_status(f"🔍 {label}...")
            try:
                results = fn(on_status)
            except Exception as e:
                logger.warning(f"Strategy '{label}' error: {str(e)[:200]}")
                results = []

            if results:
                logger.info(f"  ✅ {label}: {len(results)} pages found")
                if on_status:
                    on_status(f"✅ Tìm thấy {len(results)} fanpage")
                return results, self._business_id

            logger.info(f"  ⚠ {label}: 0 pages")

        if on_status:
            on_status("⚠ Không tìm thấy fanpage nào tự động")
        return [], self._business_id

    # ─── Cookie helper ──────────────────────────────────────────────────────

    def _extract_fb_cookies(self) -> Dict[str, str]:
        """Pull all *.facebook.com cookies from the Playwright browser context."""
        result: Dict[str, str] = {}
        if not self._context:
            return result
        try:
            for c in self._context.cookies():
                if "facebook" in c.get("domain", ""):
                    result[c["name"]] = c["value"]
        except Exception as e:
            logger.debug(f"Cookie extraction error: {str(e)[:100]}")
        return result

    # ─── Strategy 1: mbasic (httpx + BeautifulSoup) ─────────────────────────

    def _scan_via_mbasic(self, on_status: Optional[Callable] = None) -> List[Dict]:
        """
        Use the Playwright browser (already authenticated) to navigate to
        mbasic.facebook.com — guarantees auth unlike httpx+cookie approach.
        mbasic returns simple HTML: page cards are <a href="/slug"><strong>Name</strong></a>.
        Saves HTML to debug_screenshots/mbasic_*.html for inspection.
        """
        import re
        from bs4 import BeautifulSoup

        SYSTEM_SLUGS = {
            "home", "watch", "marketplace", "gaming", "groups",
            "login", "help", "settings", "pages", "bookmarks",
            "notifications", "friends", "messages", "events",
            "stories", "feeds", "videos", "saved", "people",
            "ads", "business", "privacy", "terms", "about",
            "legal", "dialog", "ajax", "async", "sharer",
            "photo", "story.php", "post.php", "permalink.php",
            "manage", "create", "composer", "insights", "inbox",
            "published_posts", "policies", "cookiepolicy",
            "communitystandards", "wellbeing", "transparency",
            "profile.php", "photo.php",
        }

        def _is_bad_name(n: str) -> bool:
            nl = n.lower().replace("\xa0", " ")
            if nl in _FB_UI_NAMES:
                return True
            return any(kw in nl for kw in _FB_UI_SUBSTRINGS)

        def _extract_page(raw_href: str):
            """Strip query/fragment, return page_id or None."""
            clean = raw_href.split("?")[0].split("#")[0].rstrip("/")
            pid_m = re.search(r"/pages/[^/]+/(\d{6,})/?$", clean)
            if pid_m:
                return clean, pid_m.group(1)
            slug_m = re.match(r"^/([A-Za-z0-9][A-Za-z0-9._\-]{1,79})$", clean)
            if slug_m and slug_m.group(1).lower() not in SYSTEM_SLUGS:
                return clean, slug_m.group(1)
            return None, None

        MBASIC_URLS = [
            "https://mbasic.facebook.com/pages/manage/",
        ]

        # Playwright uses a desktop Chromium UA which mbasic.facebook.com rejects
        # ("Trình duyệt này không hỗ trợ Facebook"). Override to a mobile UA
        # via route interception so mbasic serves proper mobile HTML.
        MOBILE_UA = (
            "Mozilla/5.0 (Linux; Android 13; SM-S918B) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.6367.82 Mobile Safari/537.36"
        )

        pg = None
        try:
            pg = self._context.new_page()
            pg.set_default_timeout(25000)

            def _ua_route(route):
                try:
                    headers = {**route.request.headers, "user-agent": MOBILE_UA}
                    route.continue_(headers=headers)
                except Exception:
                    try:
                        route.continue_()
                    except Exception:
                        pass

            pg.route("**/*", _ua_route)

            for url in MBASIC_URLS:
                try:
                    if on_status:
                        on_status(f"📡 {url[8:55]}...")
                    pg.goto(url, wait_until="domcontentloaded", timeout=25000)
                    _random_delay(2.0, 3.0)

                    current_url = pg.url
                    logger.debug(f"mbasic navigated to: {current_url[:80]}")

                    if "login" in current_url or "checkpoint" in current_url:
                        logger.warning("mbasic: redirected to login")
                        continue

                    html = pg.content()

                    # Save debug HTML
                    try:
                        debug_dir = Path(__file__).parent.parent / "debug_screenshots"
                        debug_dir.mkdir(exist_ok=True)
                        ts = time.strftime("%Y%m%d_%H%M%S")
                        slug_name = url.split("facebook.com/")[-1].replace("/", "_").strip("_") or "root"
                        (debug_dir / f"mbasic_{slug_name}_{ts}.html").write_text(html, encoding="utf-8")
                        logger.info(f"  💾 mbasic HTML saved (mbasic_{slug_name}_{ts}.html)")
                    except Exception:
                        pass

                    soup = BeautifulSoup(html, "html.parser")
                    title_text = (soup.title.string or "").lower() if soup.title else ""
                    logger.debug(f"mbasic title: {soup.title.string if soup.title else 'N/A'}")

                    if "đăng nhập" in title_text or "log in" in title_text:
                        logger.warning("mbasic: login page returned")
                        continue

                    seen: set = set()
                    batch: List[Dict] = []

                    # Pass 1 — <a><strong>Page Name</strong></a> pattern
                    for a in soup.find_all("a", href=True):
                        strong = a.find("strong")
                        if not strong:
                            continue
                        name = strong.get_text(strip=True)
                        if not name or len(name) < 2 or len(name) > 100:
                            continue
                        if _is_bad_name(name):   # filter BEFORE seen.add
                            continue

                        clean, page_id = _extract_page(a["href"])
                        if not page_id or page_id in seen:
                            continue

                        seen.add(page_id)
                        full_url = f"https://www.facebook.com{clean}" if clean.startswith("/") else clean
                        batch.append({"page_name": name, "page_url": full_url, "page_id": page_id})

                    # Pass 2 — any page-like link (broader, only if pass 1 empty)
                    if not batch:
                        for a in soup.find_all("a", href=True):
                            name = a.get_text(strip=True)
                            if not name or len(name) < 2 or len(name) > 100:
                                continue
                            if _is_bad_name(name):
                                continue

                            clean, page_id = _extract_page(a["href"])
                            if not page_id or page_id in seen:
                                continue

                            seen.add(page_id)
                            full_url = f"https://www.facebook.com{clean}" if clean.startswith("/") else clean
                            batch.append({"page_name": name, "page_url": full_url, "page_id": page_id})

                    if batch:
                        logger.info(f"mbasic: {len(batch)} pages from {url}")
                        return batch

                except Exception as e:
                    logger.debug(f"mbasic URL {url}: {str(e)[:200]}")

            return []

        except Exception as e:
            logger.error(f"_scan_via_mbasic error: {str(e)[:200]}")
            return []
        finally:
            if pg:
                try:
                    pg.close()
                except Exception:
                    pass

    # ─── Strategy 2: Full browser (Playwright) ──────────────────────────────

    def _scan_via_browser(self, on_status: Optional[Callable] = None) -> List[Dict]:
        """
        Navigate to facebook.com/pages/manage using the Playwright browser,
        wait for React to render, then extract page cards from role='main'.

        Key insight: on /pages/manage?category=your_pages, every visible
        page card IS a page you manage — so we look specifically at that
        content section, not the whole DOM.
        """
        import re

        SYSTEM_SLUGS = {
            "home", "watch", "marketplace", "gaming", "groups",
            "login", "help", "settings", "pages", "bookmarks",
            "notifications", "friends", "messages", "events",
            "stories", "feeds", "videos", "saved", "people",
            "ads", "business", "privacy", "terms", "about",
            "create", "composer", "manage",
        }

        pg = None
        try:
            pg = self._context.new_page()
            pg.set_default_timeout(30000)

            # Navigate directly to the managed-pages URL confirmed by the user.
            # facebook.com/pages/ (without param) defaults to the "Khám phá"
            # (Explore) tab which shows random pages — NOT managed pages.
            # ?category=your_pages shows ONLY the pages this account manages.
            TARGET_URL = "https://www.facebook.com/pages/?category=your_pages"

            if on_status:
                on_status("🌐 facebook.com/pages?category=your_pages...")

            pg.goto(TARGET_URL, wait_until="domcontentloaded", timeout=20000)
            try:
                pg.wait_for_selector('[role="main"]', timeout=8000)
            except Exception:
                pass
            _random_delay(2.5, 3.5)

            landed = pg.url
            logger.debug(f"browser: landed at {landed[:80]}")
            if "login" in landed or "checkpoint" in landed:
                logger.warning("browser: redirected to login")
                return []

            # Scroll to load lazy-rendered cards
            if on_status:
                on_status("📜 Đang tải danh sách fanpage...")
            for _ in range(6):
                pg.keyboard.press("End")
                _random_delay(0.8, 1.2)

            if on_status:
                on_status("📄 Phân tích cấu trúc trang...")

            # All cards on ?category=your_pages ARE managed pages.
            # Primary: find "Quản lý trang" buttons and walk up to card container.
            # Fallback: extract all page-like links with headings from role="main".
            raw = pg.evaluate(r"""
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
                    ]);

                    const BAD_NAME = [
                        'thông báo','notification','tin nhắn','message',
                        'cài đặt','setting','đăng nhập','log in',
                        'đăng xuất','log out','quản lý','manage',
                        'điều khoản','chính sách','terms','policy',
                    ];

                    // Texts that identify a "Manage Page" button
                    const MANAGE_TEXTS = [
                        'quản lý trang','manage page','quản lý','manage',
                        'dashboard','bảng điều khiển',
                    ];

                    function isBadName(s) {
                        const sl = s.toLowerCase();
                        return BAD_NAME.some(k => sl.includes(k));
                    }

                    function extractPageId(href) {
                        try {
                            const path = new URL(href).pathname.replace(/\/$/, '');
                            const pidM = /^\/pages\/[^/]+\/(\d{6,})$/.exec(path);
                            if (pidM) return { id: pidM[1], url: href };
                            const slugM = /^\/([A-Za-z0-9][A-Za-z0-9._-]{1,79})$/.exec(path);
                            if (slugM && !SKIP.has(slugM[1].toLowerCase()))
                                return { id: slugM[1], url: href };
                        } catch {}
                        return null;
                    }

                    // Facebook sets aria-label="Ảnh đại diện của <PageName>" on avatar images.
                    // Strip that prefix so we get the clean page name.
                    const AVATAR_PREFIXES = [
                        'ảnh đại diện của ',
                        'profile picture of ',
                        'profile photo of ',
                        'photo of ',
                        'hình ảnh của ',
                    ];
                    function stripAvatarPrefix(s) {
                        const sl = s.toLowerCase();
                        for (const p of AVATAR_PREFIXES) {
                            if (sl.startsWith(p)) return s.slice(p.length).trim();
                        }
                        return s;
                    }

                    function extractName(container) {
                        // Priority: role="heading" → span[dir="auto"] → aria-label (stripped)
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

                    // --- Pass 1: anchor from "Manage" button outward ---
                    const root = document.querySelector('[role="main"]') || document.body;

                    for (const el of root.querySelectorAll('a,div[role="button"],button')) {
                        const elText = el.textContent.trim().toLowerCase();
                        if (!MANAGE_TEXTS.some(t => elText === t)) continue;

                        // Walk up to find a card container that has a page link
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

                    // Pass 2 fallback — safe because the URL is already
                    // ?category=your_pages so ALL visible cards are managed pages.
                    // Runs only if Pass 1 found no "Quản lý trang" buttons
                    // (different locale, layout, or page hasn't rendered them yet).
                    if (out.length === 0) {
                        for (const a of root.querySelectorAll('a[href]')) {
                            const info = extractPageId(a.href);
                            if (!info || seen.has(info.id)) continue;

                            let name = extractName(a);
                            if (!name) {
                                // Try sibling heading in parent
                                const par = a.parentElement;
                                if (par) {
                                    const h = par.querySelector('[role="heading"]');
                                    if (h) name = h.textContent.trim();
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
            """)

            # Build result list
            results: List[Dict] = []
            seen_ids: set = set()

            for item in (raw or []):
                page_id: str = item.get("pageId", "").strip()
                name:    str = item.get("name",   "").strip()
                href:    str = item.get("href",   "").strip()

                if not page_id or not name or not href:
                    continue

                # Strip avatar aria-label prefixes that may slip through from JS
                for _pfx in ("ảnh đại diện của ", "profile picture of ",
                             "profile photo of ", "photo of ", "hình ảnh của "):
                    if name.lower().startswith(_pfx):
                        name = name[len(_pfx):].strip()
                        break

                if not name:
                    continue
                _nl = name.lower().replace("\xa0", " ")
                if _nl in _FB_UI_NAMES:
                    continue
                if any(kw in _nl for kw in _FB_UI_SUBSTRINGS):
                    continue
                if page_id.lower() in SYSTEM_SLUGS or page_id in seen_ids:
                    continue

                seen_ids.add(page_id)

                # Normalise URL: strip tracking params, force facebook.com domain
                clean = href.split("?")[0].split("#")[0].rstrip("/")
                if not clean.startswith("http"):
                    clean = f"https://www.facebook.com{clean}"

                results.append({
                    "page_name":  name,
                    "page_url":   clean,
                    "page_id":    page_id,
                    "avatar_url": item.get("avatar", ""),
                })

            # Debug screenshot if nothing found
            if not results:
                self._screenshot_error(pg, "scan_pages_empty")
                logger.warning("Browser scan: 0 pages — screenshot saved for debug")

            return results

        except Exception as e:
            logger.error(f"_scan_via_browser error: {str(e)[:300]}")
            return []
        finally:
            if pg:
                try:
                    pg.close()
                except Exception:
                    pass
