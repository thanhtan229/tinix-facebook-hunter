"""Discover public Facebook Pages from Facebook's Page search UI."""

from __future__ import annotations

import re
import time
from typing import Callable, Dict, List, Optional
from urllib.parse import quote_plus, unquote, urlparse, parse_qs

from core.db_storage import normalize_page_url
from core.page_scraper import PageScraper


_FOLLOWER_PATTERN = re.compile(
    r"(?P<number>\d[\d.,\s]*)\s*(?P<suffix>k|m|b|nghìn|ngàn|triệu|tỷ)?"
    r"\s*(?:người\s+theo\s+dõi|followers?|people\s+follow)",
    re.IGNORECASE,
)


def parse_follower_count(value: str) -> int:
    """Convert localized Facebook follower text to a sortable integer."""
    match = _FOLLOWER_PATTERN.search(str(value or ""))
    if not match:
        return 0
    raw = re.sub(r"\s+", "", match.group("number"))
    suffix = (match.group("suffix") or "").lower()
    multiplier = {
        "k": 1_000, "nghìn": 1_000, "ngàn": 1_000,
        "m": 1_000_000, "triệu": 1_000_000,
        "b": 1_000_000_000, "tỷ": 1_000_000_000,
    }.get(suffix, 1)
    try:
        if multiplier > 1:
            # With a suffix, the last comma/dot is a decimal separator.
            normalized = raw.replace(".", "").replace(",", ".")
            if raw.count(".") == 1 and "," not in raw:
                normalized = raw
            return max(0, round(float(normalized) * multiplier))
        return max(0, int(re.sub(r"[.,]", "", raw)))
    except (TypeError, ValueError):
        return 0


def _facebook_target_url(href: str) -> str:
    """Return a canonical Facebook Page candidate URL or an empty string."""
    value = str(href or "").strip()
    if not value:
        return ""
    if value.startswith("/"):
        value = f"https://www.facebook.com{value}"
    try:
        parsed = urlparse(value)
        if parsed.path.rstrip("/") == "/l.php":
            value = unquote(parse_qs(parsed.query).get("u", [""])[0])
            parsed = urlparse(value)
        host = parsed.netloc.lower()
        if host not in {"facebook.com", "www.facebook.com", "m.facebook.com"}:
            return ""
        path = parsed.path.strip("/")
        first = path.split("/", 1)[0].lower() if path else ""
        blocked = {
            "", "search", "groups", "events", "marketplace", "watch", "reel",
            "reels", "stories", "gaming", "help", "login", "share", "photo",
            "notifications", "messages", "friends", "bookmarks", "settings",
        }
        if first in blocked:
            return ""
        if first == "profile.php" and not parse_qs(parsed.query).get("id"):
            return ""
        return normalize_page_url(value)
    except Exception:
        return ""


class PageSearchEngine(PageScraper):
    """Search Page result cards using an authenticated Chrome profile."""

    def search(
        self,
        keyword: str,
        limit: int = 30,
        min_followers: int = 0,
        sort_by: str = "relevance",
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> List[Dict]:
        keyword = str(keyword or "").strip()
        if not keyword:
            raise ValueError("Từ khóa không được để trống")
        limit = max(5, min(int(limit), 100))
        page = self._context.new_page()
        found: Dict[str, Dict] = {}
        seen_candidates = set()
        try:
            page.goto(
                f"https://www.facebook.com/search/pages/?q={quote_plus(keyword)}",
                wait_until="domcontentloaded", timeout=60_000,
            )
            page.wait_for_timeout(2500)
            lowered_url = page.url.lower()
            if "/login" in lowered_url or "/checkpoint" in lowered_url:
                raise RuntimeError("Account Chrome cần đăng nhập lại Facebook")

            stagnant_rounds = 0
            for _round in range(40):
                if self._stop_event.is_set():
                    break
                cards = page.evaluate(_RESULT_CARD_SCRIPT)
                before_candidates = len(seen_candidates)
                for item in cards or []:
                    url = _facebook_target_url(item.get("url", ""))
                    name = str(item.get("name") or "").strip()
                    if not url or not name or len(name) > 300:
                        continue
                    seen_candidates.add(url)
                    followers_text = str(item.get("followers_text") or "").strip()
                    followers = parse_follower_count(followers_text)
                    if followers < max(0, int(min_followers)):
                        continue
                    avatar_url = str(item.get("avatar_url") or "")[:2000]
                    if not avatar_url.startswith("https://"):
                        avatar_url = ""
                    result = {
                        "page_uid": str(item.get("page_uid") or "")[:100],
                        "page_name": name,
                        "page_url": url,
                        "followers_text": followers_text,
                        "follower_count": followers,
                        "category": str(item.get("category") or "")[:200],
                        "avatar_url": avatar_url,
                        "verified": bool(item.get("verified")),
                    }
                    previous = found.get(url)
                    if previous is None or result["follower_count"] > previous["follower_count"]:
                        found[url] = result
                    if len(found) >= limit:
                        break
                if on_progress:
                    on_progress(min(len(found), limit), f"Đã tìm thấy {min(len(found), limit)} Fanpage")
                if len(found) >= limit:
                    break
                stagnant_rounds = stagnant_rounds + 1 if len(seen_candidates) == before_candidates else 0
                if stagnant_rounds >= 4:
                    break
                page.evaluate("window.scrollBy(0, Math.max(window.innerHeight * 0.85, 650))")
                time.sleep(1.25)

            results = list(found.values())[:limit]
            if sort_by == "followers":
                results.sort(key=lambda item: (-item["follower_count"], item["page_name"].lower()))
            elif sort_by == "name":
                results.sort(key=lambda item: item["page_name"].lower())
            return results
        finally:
            try:
                page.close()
            except Exception:
                pass


_RESULT_CARD_SCRIPT = r"""() => {
    const root = document.querySelector('[role="main"]') || document;
    const followerPattern = /[\d.,\s]+\s*(?:K|M|B|nghìn|ngàn|triệu|tỷ)?\s*(?:người theo dõi|followers?|people follow)/i;
    const rows = [];
    for (const anchor of root.querySelectorAll('a[href]')) {
        const rawName = (anchor.innerText || anchor.getAttribute('aria-label') || '').trim();
        const name = rawName.replace(/^(?:Ảnh đại diện của|Profile picture of)\s+/i, '').trim();
        if (!name || name.length < 2 || name.length > 300) continue;
        let box = anchor;
        let text = '';
        for (let depth = 0; depth < 6 && box; depth++, box = box.parentElement) {
            text = (box.innerText || '').trim();
            if (followerPattern.test(text) || (text.length > name.length && box.getAttribute('role') === 'article')) break;
        }
        if (!box) box = anchor.parentElement;
        text = (box && box.innerText || text || '').trim();
        const followerMatch = text.match(followerPattern);
        const lines = text.split('\n').map(v => v.trim()).filter(Boolean);
        const category = lines.find(v => v !== name && v !== rawName && !followerPattern.test(v) && v.length <= 120) || '';
        const img = box && box.querySelector('img[src], image[href], image[xlink\\:href]');
        const href = anchor.href || anchor.getAttribute('href') || '';
        let pageUid = '';
        try {
            const parsed = new URL(href, location.origin);
            pageUid = parsed.searchParams.get('id') || '';
            if (!pageUid) {
                const numeric = parsed.pathname.match(/\/(\d{5,})(?:\/|$)/);
                pageUid = numeric ? numeric[1] : '';
            }
        } catch (_) {}
        rows.push({
            name,
            url: href,
            page_uid: pageUid,
            followers_text: followerMatch ? followerMatch[0].trim() : '',
            category,
            avatar_url: img ? (img.currentSrc || img.src || img.getAttribute('href') || img.getAttribute('xlink:href') || '') : '',
            verified: /verified|đã xác minh/i.test(text) || !!(box && box.querySelector('[aria-label*="Verified"], [aria-label*="xác minh"]')),
        });
    }
    return rows;
}"""
