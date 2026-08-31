"""
Tinix Facebook Down — Ghost Engine
Stealth HTTP client for scraping mbasic.facebook.com.

Triết lý: "Tàng hình" trước Meta Anti-Bot.
- Sử dụng mbasic.facebook.com (HTML thuần, không JS)  
- httpx thay vì browser → không có Chromium fingerprint  
- Random Mobile User-Agent cho mỗi session
- Persistent cookies per Via
- Human-like delays (gaussian distribution)
"""

import json
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from utils import logger

# ── Mobile User-Agent Pool ──────────────────────────────────────────
# Real-world mobile UAs to blend in with normal traffic.
# Each session picks one randomly and sticks with it (consistency).
MOBILE_USER_AGENTS = [
    # iPhone Safari
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.3 Mobile/15E148 Safari/604.1",
    # Android Chrome
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.119 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.40 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.178 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.105 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; RMX3630) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36",
    # Samsung Internet
    "Mozilla/5.0 (Linux; Android 13; SAMSUNG SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SAMSUNG SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/24.0 Chrome/117.0.0.0 Mobile Safari/537.36",
    # iPad Safari
    "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 16_7_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
]

# ── Mobile Viewports ────────────────────────────────────────────────
MOBILE_VIEWPORTS = [
    (390, 844),   # iPhone 14
    (393, 852),   # iPhone 15
    (414, 896),   # iPhone 11/XR
    (360, 800),   # Samsung Galaxy S21
    (412, 915),   # Pixel 7
    (384, 854),   # Samsung Galaxy A54
]

# ── Session directory ───────────────────────────────────────────────
def _get_sessions_dir() -> Path:
    """Get the ghost sessions storage directory."""
    import sys
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    sessions_dir = base / "ghost_sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


@dataclass
class ViaConfig:
    """A single Facebook account session."""
    via_id: str                      # Unique ID for this via (hash of cookie)
    cookies: Dict[str, str]          # Parsed Facebook cookies
    user_agent: str = ""             # Assigned User-Agent for this session
    viewport: Tuple[int, int] = (390, 844)
    posts_scraped: int = 0           # Counter for rotation
    is_active: bool = True           # False if blocked/checkpoint
    error_count: int = 0             # Consecutive errors

    def __post_init__(self):
        if not self.user_agent:
            self.user_agent = random.choice(MOBILE_USER_AGENTS)
            self.viewport = random.choice(MOBILE_VIEWPORTS)


def parse_via_list(text: str) -> List[ViaConfig]:
    """
    Parse one Facebook cookie string per line.
    
    Returns list of ViaConfig objects.
    """
    vias = []
    for line_num, line in enumerate(text.strip().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        cookie_str = line

        # Parse cookies: "c_user=xxx; xs=yyy; ..."
        cookies = {}
        for pair in cookie_str.split(";"):
            pair = pair.strip()
            if "=" in pair:
                key, val = pair.split("=", 1)
                cookies[key.strip()] = val.strip()

        # Validate essential cookies
        if "c_user" not in cookies:
            logger.warning(f"Dòng {line_num}: thiếu cookie 'c_user', bỏ qua")
            continue

        # Create unique ID from c_user
        via_id = cookies.get("c_user", f"via_{line_num}")

        vias.append(ViaConfig(
            via_id=via_id,
            cookies=cookies,
        ))

    return vias


class GhostSession:
    """
    A stealthy HTTP session for one Via.
    
    Handles:
    - Cookie persistence (saves/loads from disk)
    - Mobile User-Agent fingerprinting
    - Human-like random delays
    """

    def __init__(self, via: ViaConfig):
        self.via = via
        self._client: Optional[httpx.Client] = None
        self._session_dir = _get_sessions_dir() / via.via_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._request_count = 0

    def start(self) -> bool:
        """Initialize the HTTP client with stealth settings."""
        try:
            # Load persistent cookies if available
            saved_cookies = self._load_cookies()
            if saved_cookies:
                self.via.cookies.update(saved_cookies)
                logger.debug(f"Via {self.via.via_id}: loaded {len(saved_cookies)} saved cookies")

            # Build headers that mimic a real mobile browser
            headers = {
                "User-Agent": self.via.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }

            self._client = httpx.Client(
                cookies=self.via.cookies,
                headers=headers,
                timeout=30.0,
                follow_redirects=True,
                http2=False,  # mbasic doesn't need HTTP/2
            )

            logger.info(f"👻 Via {self.via.via_id}: session ready"
                        f" | UA: ...{self.via.user_agent[-30:]}")
            return True

        except Exception as e:
            logger.error(f"Via {self.via.via_id}: session start failed: {e}")
            return False

    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """
        Fetch a page with human-like behavior.
        Returns parsed BeautifulSoup or None on failure.
        """
        if not self._client:
            return None

        try:
            # Human-like delay between requests (gaussian, mean=3.5s, std=1.5s)
            if self._request_count > 0:
                delay = max(1.5, random.gauss(3.5, 1.5))
                delay = min(delay, 8.0)  # Cap at 8s
                logger.debug(f"⏳ Delay: {delay:.1f}s")
                time.sleep(delay)

            self._request_count += 1

            # Set referer to look like normal navigation
            self._client.headers["Referer"] = "https://mbasic.facebook.com/"

            response = self._client.get(url)

            # Check for login redirect (cookies expired)
            if "/login" in str(response.url) or response.status_code == 302:
                logger.warning(f"Via {self.via.via_id}: bị chuyển hướng đăng nhập → cookies hết hạn")
                self.via.is_active = False
                return None

            if response.status_code != 200:
                logger.warning(f"Via {self.via.via_id}: HTTP {response.status_code}")
                self.via.error_count += 1
                return None

            # Check for checkpoint/block
            page_text = response.text
            if "checkpoint" in page_text.lower() or "security check" in page_text.lower():
                logger.warning(f"⚠️ Via {self.via.via_id}: bị checkpoint/security check")
                self.via.is_active = False
                return None

            # Parse HTML
            soup = BeautifulSoup(page_text, "lxml")

            # Save updated cookies
            self._save_cookies()

            # Reset error count on success
            self.via.error_count = 0
            self.via.posts_scraped += 1

            return soup

        except httpx.TimeoutException:
            logger.warning(f"Via {self.via.via_id}: timeout")
            self.via.error_count += 1
            return None
        except Exception as e:
            logger.error(f"Via {self.via.via_id}: fetch error: {str(e)[:100]}")
            self.via.error_count += 1
            return None

    def stop(self):
        """Close the HTTP client and save cookies."""
        if self._client:
            try:
                self._save_cookies()
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _save_cookies(self):
        """Persist cookies to disk for session reuse."""
        try:
            if self._client and self._client.cookies:
                cookie_dict = dict(self._client.cookies)
                cookie_dict.update(self.via.cookies)  # Merge with original
                cookie_path = self._session_dir / "cookies.json"
                with open(cookie_path, "w") as f:
                    json.dump(cookie_dict, f, indent=2)
        except Exception:
            pass

    def _load_cookies(self) -> Dict[str, str]:
        """Load saved cookies from disk."""
        try:
            cookie_path = self._session_dir / "cookies.json"
            if cookie_path.exists():
                with open(cookie_path) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}


class GhostEngine:
    """
    Manages multiple Via sessions with automatic rotation.
    
    Rotation logic:
    - Each Via handles 20-30 posts before rotating
    - If a Via gets blocked/checkpoint → skip to next
    - If all Vias are exhausted → stop
    """

    POSTS_PER_VIA = 25  # Rotate after this many posts per via

    def __init__(self, vias: List[ViaConfig]):
        self._vias = vias
        self._sessions: Dict[str, GhostSession] = {}
        self._current_index = 0
        self._active_session: Optional[GhostSession] = None

    @property
    def current_via(self) -> Optional[ViaConfig]:
        if self._active_session:
            return self._active_session.via
        return None

    @property
    def active_via_count(self) -> int:
        return sum(1 for v in self._vias if v.is_active)

    def start(self) -> bool:
        """Initialize the first via session."""
        if not self._vias:
            logger.error("Không có Via nào được cung cấp!")
            return False

        logger.info(f"👻 Ghost Engine: {len(self._vias)} via(s) loaded")
        return self._activate_next_via()

    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """
        Fetch a page using the current active session.
        Auto-rotates via if needed (post limit or errors).
        """
        if not self._active_session:
            if not self._activate_next_via():
                return None

        # Check if current via needs rotation
        via = self._active_session.via
        if via.posts_scraped >= self.POSTS_PER_VIA or via.error_count >= 3:
            reason = "post limit" if via.posts_scraped >= self.POSTS_PER_VIA else "errors"
            logger.info(f"🔄 Rotating via (reason: {reason})")
            self._active_session.stop()
            if not self._activate_next_via():
                return None

        result = self._active_session.fetch_page(url)

        # If fetch failed and via is dead, try next
        if result is None and not self._active_session.via.is_active:
            logger.info(f"🔄 Via {via.via_id} bị block, chuyển via...")
            self._active_session.stop()
            if self._activate_next_via():
                result = self._active_session.fetch_page(url)

        return result

    def stop(self):
        """Stop all sessions."""
        for session in self._sessions.values():
            session.stop()
        self._sessions.clear()
        self._active_session = None
        logger.info("👻 Ghost Engine stopped")

    def _activate_next_via(self) -> bool:
        """Find and activate the next available via."""
        start_index = self._current_index
        attempts = 0

        while attempts < len(self._vias):
            via = self._vias[self._current_index % len(self._vias)]
            self._current_index = (self._current_index + 1) % len(self._vias)
            attempts += 1

            if not via.is_active:
                continue

            # Reset post counter for rotation
            via.posts_scraped = 0
            via.error_count = 0

            # Create or reuse session
            if via.via_id not in self._sessions:
                session = GhostSession(via)
                if not session.start():
                    via.is_active = False
                    continue
                self._sessions[via.via_id] = session

            self._active_session = self._sessions[via.via_id]
            logger.info(f"👻 Active via: {via.via_id} | Posts remaining: {self.POSTS_PER_VIA}")
            return True

        logger.error("❌ Tất cả Via đều đã bị block hoặc hết hạn!")
        return False
