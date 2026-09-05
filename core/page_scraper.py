"""
Tinix Facebook Down — Page Scraper (v4 - Network Interception)
Scrapes Facebook Page posts by intercepting GraphQL API responses.
Uses Playwright Chrome + response listener to capture all post data
from AJAX calls triggered by scrolling.
"""

import json
import random
import re
import time
import threading
import subprocess
import sys
import os
import urllib.request
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from utils import logger
from utils.chrome_profiles import scraper_profile_dir


@dataclass
class ScrapedPost:
    """A single scraped post from a Facebook Page."""
    date: str = ""
    post_id: str = ""
    post_type: str = "Text"  # Ảnh / Video / Text
    engagement: int = 0
    comments: int = 0
    shares: int = 0
    view_count: int = 0
    caption: str = ""
    page_name: str = ""
    url: str = ""
    media_preview_url: str = ""
    media_count: int = 0


CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

CDP_PORT_BASE = 9400  # Keep in sync with Account Manager's dedicated Chrome ports.

GENERIC_FACEBOOK_PAGE_NAMES = {
    "chi tiết", "details", "xem thêm", "see more", "bài viết", "post",
    "ảnh", "photos", "video", "videos", "reels", "trang", "page",
    "facebook", "thông báo", "notifications", "đoạn chat", "chats",
    "thông tin liên hệ", "contact info", "giới thiệu", "about",
}


def is_valid_facebook_page_name(value: object) -> bool:
    """Reject navigation/dialog labels that Facebook sometimes exposes as the page title."""
    name = re.sub(r"\s+", " ", str(value or "")).strip()
    return 1 < len(name) <= 300 and name.casefold() not in GENERIC_FACEBOOK_PAGE_NAMES


def _find_chrome() -> Optional[str]:
    for path in CHROME_PATHS:
        expanded = os.path.expandvars(path)
        if os.path.exists(expanded):
            return expanded
    return None


def _get_profile_dir() -> Path:
    return scraper_profile_dir()


def _parse_fb_number(s: str) -> int:
    """Parse Facebook-style numbers: '1,234', '1.2K', '2N', '1M'."""
    if not s:
        return 0
    s = s.strip().upper().replace(",", "").replace(".", "")
    mul = 1
    if s.endswith("K") or s.endswith("N"):
        mul = 1000
        s = s[:-1]
    elif s.endswith("M"):
        mul = 1000000
        s = s[:-1]
    try:
        return int(float(s) * mul)
    except (ValueError, TypeError):
        return 0


def _parse_abbreviated_number(s: str) -> int:
    """Parse abbreviated numbers from FB JSON: '1,234', '1.2K', '3.5M', '1K'."""
    if not s:
        return 0
    s = s.strip().upper().replace(",", "")
    mul = 1
    if s.endswith("K"):
        mul = 1000
        s = s[:-1]
    elif s.endswith("M"):
        mul = 1000000
        s = s[:-1]
    try:
        return int(float(s) * mul)
    except (ValueError, TypeError):
        return 0


def _parse_metric_number(value) -> int:
    """Parse localized compact metrics such as 1,2K, 2.5M or 12 nghìn."""
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value or "").strip().lower()
    match = re.search(
        r"([\d.,]+)\s*(k|m|b|n|nghìn|ngàn|triệu|tỷ)?", text, re.IGNORECASE
    )
    if not match:
        return 0
    number = match.group(1)
    suffix = (match.group(2) or "").lower()
    multiplier = {
        "k": 1_000, "n": 1_000, "nghìn": 1_000, "ngàn": 1_000,
        "m": 1_000_000, "triệu": 1_000_000,
        "b": 1_000_000_000, "tỷ": 1_000_000_000,
    }.get(suffix, 1)
    try:
        if multiplier > 1:
            normalized = number.replace(".", "").replace(",", ".")
            if number.count(".") == 1 and "," not in number:
                normalized = number
            return max(0, round(float(normalized) * multiplier))
        return max(0, int(re.sub(r"[.,]", "", number)))
    except (TypeError, ValueError):
        return 0


def _safe_str(s: str) -> str:
    """Remove surrogate characters that cause encoding errors."""
    if not s:
        return ""
    # Remove lone surrogates
    return s.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _decode_unicode_escapes(s: str) -> str:
    """Decode JSON unicode escape sequences safely."""
    if not s:
        return ""
    s = s.replace(r"\n", "\n").replace(r"\r", "").replace(r'\"', '"')
    s = s.replace(r"\u0026", "&").replace(r"\u003C", "<").replace(r"\u003E", ">")
    # Decode remaining \\uXXXX
    try:
        s = re.sub(
            r"\\u([0-9a-fA-F]{4})",
            lambda m: chr(int(m.group(1), 16)),
            s,
        )
    except Exception:
        pass
    return _safe_str(s)


class _PostCollector:
    """
    Collects post data from intercepted GraphQL responses.
    Parses Facebook's NDJSON format (newline-delimited JSON) and
    recursively traverses the JSON to find story/post nodes.
    """

    def __init__(self):
        self._posts: Dict[str, dict] = {}  # post_id -> data
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        return len(self._posts)

    def get_posts(self) -> List[dict]:
        with self._lock:
            return list(self._posts.values())

    def process_response_body(self, body: str) -> int:
        """Parse a GraphQL response body (NDJSON) and extract posts."""
        new_count = 0

        # Split by newlines — each line is a separate JSON object
        for line in body.split("\n"):
            line = line.strip()
            if len(line) < 200:
                continue
            if '"post_id"' not in line and '"creation_time"' not in line:
                continue

            try:
                data = json.loads(line)
                added = self._extract_from_json(data)
                if added > 0 and self.count <= 5:
                    logger.debug(f"[JSON-PATH] +{added} bài (tổng: {self.count})")
                new_count += added
            except (json.JSONDecodeError, ValueError):
                # Try to extract JSON from embedded <script> tags (SSR HTML)
                # Facebook SSR uses <script type="application/json" data-sjs>...</script>
                script_added = 0
                if '<script' in line and '"post_id"' in line:
                    # Find data-sjs script boundaries and parse each
                    for m in re.finditer(r'<script[^>]*data-sjs[^>]*>',  line):
                        start = m.end()
                        end = line.find('</script>', start)
                        if end == -1:
                            continue
                        chunk = line[start:end].strip()
                        if '"post_id"' not in chunk:
                            continue
                        try:
                            script_data = json.loads(chunk)
                            script_added += self._extract_from_json(script_data)
                        except (json.JSONDecodeError, ValueError):
                            pass
                    if script_added > 0 and self.count <= 5:
                        logger.debug(f"[SCRIPT-JSON] +{script_added} bài (tổng: {self.count})")
                    new_count += script_added

                # Final fallback: regex text extraction
                if script_added == 0:
                    added = self._extract_from_text(line)
                    if added > 0 and self.count <= 5:
                        logger.debug(f"[TEXT-PATH] +{added} bài (tổng: {self.count})")
                    new_count += added

        return new_count

    def _extract_from_json(self, data: dict) -> int:
        """Extract posts from a parsed JSON object via recursive traversal."""
        new_count = 0
        story_nodes = []

        # Find all nodes that have a comet_sections structure (= a post/story)
        self._find_story_nodes(data, story_nodes)

        for node in story_nodes:
            post = self._parse_story_node(node)
            if post and post["post_id"]:
                pid = post["post_id"]
                with self._lock:
                    if pid not in self._posts:
                        self._posts[pid] = post
                        new_count += 1
                    else:
                        # Post already exists (e.g. from SSR with empty engagement).
                        # Update with better data if the new version has non-zero values.
                        existing = self._posts[pid]
                        # Merge engagement data (take higher values)
                        if post.get("engagement", 0) > existing.get("engagement", 0):
                            existing["engagement"] = post["engagement"]
                        if post.get("comments", 0) > existing.get("comments", 0):
                            existing["comments"] = post["comments"]
                        if post.get("shares", 0) > existing.get("shares", 0):
                            existing["shares"] = post["shares"]
                        if post.get("view_count", 0) > existing.get("view_count", 0):
                            existing["view_count"] = post["view_count"]
                        # Merge empty text fields
                        if post.get("date") and not existing.get("date"):
                            existing["date"] = post["date"]
                        if post.get("caption") and not existing.get("caption"):
                            existing["caption"] = post["caption"]
                        if post.get("url") and (not existing.get("url") or existing["url"] == f"https://www.facebook.com/{pid}"):
                            existing["url"] = post["url"]
                        if post.get("media_preview_url") and not existing.get("media_preview_url"):
                            existing["media_preview_url"] = post["media_preview_url"]
                        if post.get("media_count", 0) > existing.get("media_count", 0):
                            existing["media_count"] = post["media_count"]
                        # Update post_type if previously Text
                        if existing.get("post_type") == "Text" and post.get("post_type") in ("Ảnh", "Video"):
                            existing["post_type"] = post["post_type"]

        return new_count

    def _find_story_nodes(self, obj, results: list) -> None:
        """Recursively find JSON nodes that represent posts (have comet_sections)."""
        if not isinstance(obj, dict):
            if isinstance(obj, list):
                for item in obj:
                    self._find_story_nodes(item, results)
            return

        # A story/post node has "comet_sections" containing content + feedback
        if "comet_sections" in obj and isinstance(obj["comet_sections"], dict):
            cs = obj["comet_sections"]
            # Confirm it's a real post (has content or feedback sections)
            has_content = "content" in cs or "feedback" in cs
            # Avoid nested sub-stories (e.g. shared posts within posts)
            has_post_id = "post_id" in obj
            if has_content and has_post_id:
                results.append(obj)
                return  # Don't recurse further into this node

        # Recurse into child dicts/lists
        for v in obj.values():
            if isinstance(v, (dict, list)):
                self._find_story_nodes(v, results)

    def _parse_story_node(self, node: dict) -> Optional[dict]:
        """Extract all post fields from a story node with comet_sections."""
        cs = node.get("comet_sections", {})
        post_id = str(node.get("post_id", ""))

        if not post_id:
            return None

        # --- Date ---
        date_str = ""
        creation_time = self._deep_find(cs, "creation_time")
        if creation_time and isinstance(creation_time, (int, float)):
            try:
                dt = datetime.fromtimestamp(int(creation_time))
                date_str = dt.strftime("%d/%m/%Y")
            except (ValueError, OSError):
                pass

        # --- Caption ---
        caption = ""
        # Path: comet_sections.content.story.message.text
        content = cs.get("content", {})
        if isinstance(content, dict):
            story = content.get("story", {})
            if isinstance(story, dict):
                msg = story.get("message", {})
                if isinstance(msg, dict) and "text" in msg:
                    caption = _safe_str(str(msg["text"]))
        # Fallback: deep search for message.text
        if not caption:
            msg_text = self._deep_find(cs.get("content", {}), "message")
            if isinstance(msg_text, dict) and "text" in msg_text:
                caption = _safe_str(str(msg_text["text"]))

        if caption and len(caption) > 500:
            caption = caption[:500] + "..."

        # --- Engagement (reactions, comments, shares) ---
        engagement = 0
        comments = 0
        shares = 0

        # Path: comet_sections.feedback.story.story_ufi_container.story.feedback_context
        feedback = cs.get("feedback", {})
        feedback_str = json.dumps(feedback, default=str)

        # Debug: log feedback keys for first few posts
        if len(self._posts) < 3:
            fb_keys = list(feedback.keys()) if isinstance(feedback, dict) else []
            # Extract context around key patterns
            _snippets = []
            for pattern_name, pattern in [
                ("reaction_count", r'"reaction_count"[^}]{0,80}'),
                ("total_comment", r'"total_comment_count"[^,}]{0,40}'),
                ("comment_count", r'"comment_count"[^}]{0,80}'),
                ("share_count", r'"share_count"[^}]{0,80}'),
                ("reshare_count", r'"reshare_count"[^}]{0,80}'),
                ("i18n_reaction", r'"i18n_reaction_count"[^,}]{0,60}'),
                ("i18n_comment", r'"i18n_comment_count"[^,}]{0,60}'),
                ("i18n_share", r'"i18n_share_count"[^,}]{0,60}'),
            ]:
                m = re.search(pattern, feedback_str)
                if m:
                    _snippets.append(f"{pattern_name}={m.group(0)[:80]}")

            logger.debug(
                f"[DEBUG] Post {post_id}: feedback_len={len(feedback_str)}, "
                f"fb_keys={fb_keys[:4]}"
            )
            if _snippets:
                for s in _snippets:
                    logger.debug(f"[DEBUG]   → {s}")
            else:
                logger.debug(f"[DEBUG]   → No engagement patterns found in feedback!")
                # Show first 500 chars of feedback for manual inspection
                logger.debug(f"[DEBUG]   → feedback_preview: {feedback_str[:500]}")

        # Reactions
        react_match = re.search(r'"reaction_count":\s*\{"count":\s*(\d+)', feedback_str)
        if react_match:
            engagement = int(react_match.group(1))

        # Comments — try several patterns (Facebook varies the field names)
        cmt_match = re.search(r'"total_comment_count":\s*(\d+)', feedback_str)
        if cmt_match:
            comments = int(cmt_match.group(1))
        if comments == 0:
            cmt_match2 = re.search(r'"comment_count":\s*\{"total_count":\s*(\d+)', feedback_str)
            if cmt_match2:
                comments = int(cmt_match2.group(1))
        if comments == 0:
            # Fallback: "comments":{"total_count":N}
            cmt_match3 = re.search(r'"comments":\s*\{"total_count":\s*(\d+)', feedback_str)
            if cmt_match3:
                comments = int(cmt_match3.group(1))
        if comments == 0:
            # Fallback: i18n text like "123 bình luận" or "123 comments"
            cmt_match4 = re.search(r'"i18n_comment_count":\s*"([\d,.KkMm]+)', feedback_str)
            if cmt_match4:
                comments = _parse_abbreviated_number(cmt_match4.group(1))
        if comments == 0:
            # Fallback: top_level_comment_count
            cmt_match5 = re.search(r'"top_level_comment_count":\s*(\d+)', feedback_str)
            if cmt_match5:
                comments = int(cmt_match5.group(1))
        if comments == 0:
            # Deep-find in the parsed feedback dict
            for key in ("total_comment_count", "comment_count"):
                val = self._deep_find(feedback, key)
                if isinstance(val, int) and val > 0:
                    comments = val
                    break
                elif isinstance(val, dict):
                    tc = val.get("total_count")
                    if isinstance(tc, int) and tc > 0:
                        comments = tc
                        break

        # Shares — try several patterns
        share_match = re.search(r'"share_count":\s*\{"count":\s*(\d+)', feedback_str)
        if share_match:
            shares = int(share_match.group(1))
        if shares == 0:
            share_match2 = re.search(r'"reshare_count":\s*\{"count":\s*(\d+)', feedback_str)
            if share_match2:
                shares = int(share_match2.group(1))
        if shares == 0:
            share_match3 = re.search(r'"share_count":\s*(\d+)', feedback_str)
            if share_match3:
                shares = int(share_match3.group(1))
        if shares == 0:
            # Fallback: i18n share count text
            share_match4 = re.search(r'"i18n_share_count":\s*"([\d,.KkMm]+)', feedback_str)
            if share_match4:
                shares = _parse_abbreviated_number(share_match4.group(1))
        if shares == 0:
            # Deep-find in parsed feedback dict
            for key in ("share_count", "reshare_count"):
                val = self._deep_find(feedback, key)
                if isinstance(val, int) and val > 0:
                    shares = val
                    break
                elif isinstance(val, dict):
                    c = val.get("count")
                    if isinstance(c, int) and c > 0:
                        shares = c
                        break

        # Also search the FULL node (not just feedback) for engagement fallback
        if comments == 0 or shares == 0:
            node_str = json.dumps(node, default=str)
            if comments == 0:
                cm = re.search(r'"total_comment_count":\s*(\d+)', node_str)
                if cm:
                    comments = int(cm.group(1))
            if comments == 0:
                cm2 = re.search(r'"comment_count":\s*\{"total_count":\s*(\d+)', node_str)
                if cm2:
                    comments = int(cm2.group(1))
            if shares == 0:
                sm = re.search(r'"share_count":\s*\{"count":\s*(\d+)', node_str)
                if sm:
                    shares = int(sm.group(1))

        # --- Post type ---
        post_type = self._detect_post_type(node)
        media_preview_url, media_count = self._extract_media_metadata(node)

        # --- Video/Reels views ---
        view_count = self._extract_view_count(node)

        # --- URL ---
        url = f"https://www.facebook.com/{post_id}"
        node_str_for_url = json.dumps(node, default=str)
        url_match = re.search(
            r'"url":\s*"(https?://www\.facebook\.com/[^"]*(?:posts|videos|permalink|pfbid|reel)[^"]*)"',
            node_str_for_url,
        )
        if url_match:
            url = url_match.group(1).replace("\\/", "/")

        # Only return if we have meaningful data
        if not date_str and not caption and not engagement and not view_count:
            return None

        # Debug: log final values for first few posts
        if len(self._posts) < 5:
            logger.debug(
                f"[DEBUG] Post {post_id} FINAL: date={date_str}, engagement={engagement}, "
                f"comments={comments}, shares={shares}, views={view_count}, type={post_type}"
            )

        return {
            "post_id": post_id,
            "date": date_str,
            "post_type": post_type,
            "engagement": engagement,
            "comments": comments,
            "shares": shares,
            "view_count": view_count,
            "caption": caption,
            "url": url,
            "media_preview_url": media_preview_url,
            "media_count": media_count,
        }

    def _deep_find(self, obj, key: str):
        """Recursively find the first occurrence of a key in a nested dict."""
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                result = self._deep_find(v, key)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = self._deep_find(item, key)
                if result is not None:
                    return result
        return None

    @staticmethod
    def _valid_preview_url(value: object) -> str:
        """Allow only Facebook CDN image URLs suitable for an <img> preview."""
        url = str(value or "").replace("\\/", "/").strip()
        try:
            parsed = urllib.parse.urlsplit(url)
        except ValueError:
            return ""
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (host == "fbcdn.net" or host.endswith(".fbcdn.net")):
            return ""
        return url

    def _extract_media_metadata(self, node: dict) -> tuple[str, int]:
        """Extract one safe preview image and a conservative attachment count."""
        media: list[tuple[str, str]] = []
        seen_media: set[str] = set()

        def best_image(value: object, allow_any_fbcdn: bool) -> str:
            candidates: list[tuple[int, str]] = []

            def collect(obj: object, path: tuple[str, ...] = ()) -> None:
                if isinstance(obj, dict):
                    width = int(obj.get("width", 0) or 0) if str(obj.get("width", "")).isdigit() else 0
                    height = int(obj.get("height", 0) or 0) if str(obj.get("height", "")).isdigit() else 0
                    path_text = ".".join(path).lower()
                    for key, child in obj.items():
                        child_path = (*path, str(key))
                        if key in {"uri", "url", "src"} and isinstance(child, str):
                            preview = self._valid_preview_url(child)
                            looks_like_image = (
                                any(token in path_text for token in (
                                    "image", "thumbnail", "photo", "poster", "preview", "cover"
                                ))
                                or re.search(r"\.(?:jpe?g|png|webp|gif)(?:\?|$)", preview, re.IGNORECASE)
                            )
                            excluded = any(token in path_text for token in (
                                "actor", "author", "avatar", "profile_picture", "profile_pic",
                                "badge", "emoji", "icon", "logo", "sprite", "sticker",
                            ))
                            if preview and not excluded and (allow_any_fbcdn or looks_like_image):
                                # Prefer an actual preview/thumbnail around 640px instead of a
                                # full-resolution attachment. No file is downloaded here.
                                longest_side = max(width, height)
                                if 240 <= longest_side <= 960:
                                    size_score = 400_000_000 - abs(longest_side - 640) * 100_000
                                elif longest_side > 0:
                                    size_score = max(1, 100_000_000 - abs(longest_side - 640) * 10_000)
                                else:
                                    size_score = 10_000_000
                                score = size_score
                                if "preferred_thumbnail" in path_text or "thumbnail" in path_text or "poster" in path_text:
                                    score += 3_000_000_000
                                elif "preview" in path_text or "image" in path_text or "photo" in path_text:
                                    score += 1_000_000_000
                                candidates.append((score, preview))
                        elif isinstance(child, (dict, list)):
                            collect(child, child_path)
                elif isinstance(obj, list):
                    for index, child in enumerate(obj):
                        collect(child, (*path, str(index)))

            collect(value)
            return max(candidates, default=(0, ""), key=lambda item: item[0])[1]

        def visit(obj: object) -> None:
            if isinstance(obj, dict):
                typename = str(obj.get("__typename", ""))
                if typename in {"Photo", "Video"}:
                    preview = best_image(obj, allow_any_fbcdn=typename == "Photo")
                    identity = str(obj.get("id") or obj.get("video_id") or preview)
                    if identity and identity not in seen_media:
                        seen_media.add(identity)
                        media.append((preview, typename))
                    return
                for child in obj.values():
                    if isinstance(child, (dict, list)):
                        visit(child)
            elif isinstance(obj, list):
                for child in obj:
                    visit(child)

        content = node.get("comet_sections", {}).get("content", {})
        visit(content)
        preview = next((url for url, _kind in media if url), "")
        if not preview:
            preview = best_image(content, allow_any_fbcdn=False)
        count = len(media) if media else (1 if preview else 0)
        return preview, count

    def _extract_view_count(self, obj) -> int:
        """Find the strongest explicit video/Reels view or play count in GraphQL data."""
        keys = {
            "view_count", "video_view_count", "video_views", "video_play_count",
            "play_count", "plays_count", "total_video_views", "view_count_text",
            "video_view_count_text", "play_count_text",
        }
        candidates = []

        def visit(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if str(key).lower() in keys:
                        if isinstance(child, dict):
                            for inner_key in ("count", "value", "text", "total_count"):
                                if inner_key in child:
                                    candidates.append(_parse_metric_number(child[inner_key]))
                        else:
                            candidates.append(_parse_metric_number(child))
                    if isinstance(child, (dict, list)):
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(obj)
        return max(candidates or [0])

    def _detect_post_type(self, node: dict) -> str:
        """Detect post type (Video/Ảnh/Text) via JSON traversal of media attachments."""
        has_video = False
        has_photo = False

        # 1. Check __typename in the entire node tree
        def check_types(obj):
            nonlocal has_video, has_photo
            if isinstance(obj, dict):
                tn = obj.get("__typename", "")
                if tn == "Video":
                    has_video = True
                    return
                elif tn == "Photo":
                    has_photo = True
                # Check for video-specific keys
                if "video_id" in obj or "playable_url" in obj:
                    has_video = True
                    return
                if "photo_image" in obj:
                    has_photo = True
                # Recurse but skip very deep nesting for performance
                for k, v in obj.items():
                    if has_video:
                        return  # Video takes priority, stop early
                    if isinstance(v, (dict, list)):
                        check_types(v)
            elif isinstance(obj, list):
                for item in obj:
                    if has_video:
                        return
                    check_types(item)

        # Only check content and feedback sections (not the entire node for perf)
        cs = node.get("comet_sections", {})
        check_types(cs.get("content", {}))
        if not has_video:
            check_types(cs.get("feedback", {}))

        # 3. If still nothing found, check for scontent image URLs in attachments
        if not has_video and not has_photo:
            content = cs.get("content", {})
            content_str = json.dumps(content, default=str)
            if "scontent" in content_str and ("photo" in content_str.lower() or ".jpg" in content_str or ".png" in content_str):
                has_photo = True

        return "Video" if has_video else ("Ảnh" if has_photo else "Text")

    def _extract_from_text(self, text: str) -> int:
        """Fallback: extract posts from raw text using regex (for SSR HTML source)."""
        new_count = 0
        post_ids = set(re.findall(r'"post_id":\s*"(\d+)"', text))

        if post_ids and self.count < 5:
            logger.debug(f"[TEXT-EXTRACT] Found {len(post_ids)} post_ids: {list(post_ids)[:5]}")

        for pid in post_ids:

            pos = text.find(f'"post_id":"{pid}"')
            if pos == -1:
                # Also try with space after colon
                pos = text.find(f'"post_id": "{pid}"')
            if pos == -1:
                continue

            # Moderate window for SSR data
            start = max(0, pos - 15000)
            end = min(len(text), pos + 35000)
            block = text[start:end]

            date_str = ""
            t_match = re.search(r'"creation_time":\s*(\d{10})', block)
            if t_match:
                try:
                    dt = datetime.fromtimestamp(int(t_match.group(1)))
                    date_str = dt.strftime("%d/%m/%Y")
                except (ValueError, OSError):
                    pass

            caption = ""
            msg_match = re.search(
                r'"message":\s*\{"text":\s*"((?:[^"\\]|\\.){3,})"', block
            )
            if msg_match:
                caption = _decode_unicode_escapes(msg_match.group(1))
                if len(caption) > 500:
                    caption = caption[:500] + "..."

            has_video = '"__typename":"Video"' in block or '"video_id"' in block
            has_photo = '"__typename":"Photo"' in block
            post_type = "Video" if has_video else ("Ảnh" if has_photo else "Text")

            media_preview_url = ""
            preview_match = re.search(
                r'"(?:uri|url)":\s*"(https:\\/\\/[^" ]*?fbcdn\.net[^" ]*)"',
                block,
                re.IGNORECASE,
            )
            if preview_match:
                candidate = _decode_unicode_escapes(preview_match.group(1)).replace("\\/", "/")
                if re.search(r"\.(?:jpe?g|png|webp|gif)(?:\?|$)", candidate, re.IGNORECASE):
                    media_preview_url = self._valid_preview_url(candidate)

            engagement = 0
            react_m = re.search(r'"reaction_count":\s*\{"count":\s*(\d+)', block)
            if react_m:
                engagement = int(react_m.group(1))

            comments = 0
            cmt_m = re.search(r'"comment_count":\s*\{"total_count":\s*(\d+)', block)
            if cmt_m:
                comments = int(cmt_m.group(1))
            if comments == 0:
                cmt_m2 = re.search(r'"total_comment_count":\s*(\d+)', block)
                if cmt_m2:
                    comments = int(cmt_m2.group(1))
            if comments == 0:
                cmt_m3 = re.search(r'"comments":\s*\{"total_count":\s*(\d+)', block)
                if cmt_m3:
                    comments = int(cmt_m3.group(1))

            shares = 0
            share_m = re.search(r'"share_count":\s*\{"count":\s*(\d+)', block)
            if share_m:
                shares = int(share_m.group(1))
            if shares == 0:
                share_m2 = re.search(r'"reshare_count":\s*\{"count":\s*(\d+)', block)
                if share_m2:
                    shares = int(share_m2.group(1))
            if shares == 0:
                share_m3 = re.search(r'"share_count":\s*(\d+)', block)
                if share_m3:
                    shares = int(share_m3.group(1))

            view_count = 0
            for view_pattern in (
                r'"(?:video_)?view_count":\s*(\d+)',
                r'"(?:video_)?play_count":\s*(\d+)',
                r'"(?:video_)?view_count(?:_text)?":\s*"([\d.,]+\s*(?:K|M|B|N|nghìn|triệu|tỷ)?)',
                r'([\d.,]+\s*(?:K|M|B|N|nghìn|triệu|tỷ)?)\s*(?:lượt xem|views?|plays?)',
            ):
                view_match = re.search(view_pattern, block, re.IGNORECASE)
                if view_match:
                    view_count = max(view_count, _parse_metric_number(view_match.group(1)))

            # Debug: show extracted values for first posts
            if self.count < 5:
                logger.debug(
                    f"[TEXT-POST] pid={pid}: date={date_str}, "
                    f"engage={engagement}, cmt={comments}, shares={shares}, views={view_count}, "
                    f"type={post_type}, caption_len={len(caption)}"
                )

            if not date_str and not caption and not engagement and not view_count:
                continue

            with self._lock:
                if pid not in self._posts:
                    self._posts[pid] = {
                        "post_id": pid,
                        "date": date_str,
                        "post_type": post_type,
                        "engagement": engagement,
                        "comments": comments,
                        "shares": shares,
                        "view_count": view_count,
                        "caption": _safe_str(caption),
                        "url": f"https://www.facebook.com/{pid}",
                        "media_preview_url": media_preview_url,
                        "media_count": 1 if media_preview_url else 0,
                    }
                    new_count += 1
                else:
                    # Merge better engagement values
                    existing = self._posts[pid]
                    if engagement > existing.get("engagement", 0):
                        existing["engagement"] = engagement
                    if comments > existing.get("comments", 0):
                        existing["comments"] = comments
                    if shares > existing.get("shares", 0):
                        existing["shares"] = shares
                    if view_count > existing.get("view_count", 0):
                        existing["view_count"] = view_count
                    if date_str and not existing.get("date"):
                        existing["date"] = date_str
                    if caption and not existing.get("caption"):
                        existing["caption"] = _safe_str(caption)
                    if existing.get("post_type") == "Text" and post_type in ("Ảnh", "Video"):
                        existing["post_type"] = post_type
                    if media_preview_url and not existing.get("media_preview_url"):
                        existing["media_preview_url"] = media_preview_url
                    if media_preview_url and existing.get("media_count", 0) < 1:
                        existing["media_count"] = 1

        return new_count


class PageScraper:
    """
    Scrapes posts from Facebook Pages using Chrome + Playwright.
    Intercepts GraphQL API responses to capture post data directly.
    Supports dedicated Chrome profiles per account.
    """

    def __init__(self, account: Optional[Dict] = None, cookies: Optional[Dict[str, str]] = None,
                 cdp_port: Optional[int] = None):
        """
        Args:
            account: dict from db_storage.get_all_accounts() with credentials
                     and a dedicated profile_dir.
            cookies: legacy cookie dict (fallback if no account)
            cdp_port: Chrome DevTools Protocol port (unique per instance).
                      Defaults to CDP_PORT_BASE + account_id.
        """
        self._account = account or {}
        self._cookies = cookies or {}
        # Calculate unique CDP port per account
        if cdp_port is not None:
            self._cdp_port = cdp_port
        else:
            acct_id = self._account.get("id", 0) or 0
            self._cdp_port = CDP_PORT_BASE + (int(acct_id) % 400)
        self._stop_event = threading.Event()
        self._chrome_process = None
        self._browser = None
        self._context = None
        self._pw_instance = None
        self._reused_browser = False
        self.last_follower_count = 0  # populated after scrape_page
        self.last_observed_post_ids: List[str] = []
        self.last_scan_stop_reason = ""
        self.last_scan_complete = False
        self.last_archive_boundary_found = False

    def _get_profile_dir(self) -> str:
        """Get per-account Chrome profile directory."""
        custom_profile = self._account.get("profile_dir", "")
        if custom_profile:
            profile_dir = Path(custom_profile)
            profile_dir.mkdir(parents=True, exist_ok=True)
            return str(profile_dir)
        acct_id = self._account.get("id", 0)
        return str(scraper_profile_dir(acct_id or None))

    def start(self) -> bool:
        """Launch Chrome and connect Playwright."""
        try:
            from playwright.sync_api import sync_playwright

            chrome_path = _find_chrome()
            if not chrome_path:
                logger.error("Không tìm thấy Chrome.")
                return False

            profile_dir = self._get_profile_dir()
            acct_label = self._account.get("label") or self._account.get("username") or "default"
            logger.info(f"🚀 Chrome profile: {acct_label}")

            self._reused_browser = self._cdp_is_ready()
            if self._reused_browser:
                logger.info(f"Kết nối Chrome đang mở (port {self._cdp_port})...")
            else:
                chrome_cmd = [
                    chrome_path,
                    f"--remote-debugging-port={self._cdp_port}",
                    f"--user-data-dir={profile_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-popup-blocking",
                    "--disable-gpu",
                    "--window-size=1280,900",
                    "--disable-blink-features=AutomationControlled",
                ]

                logger.info(f"Đang khởi động Chrome (port {self._cdp_port})...")
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
                f"http://127.0.0.1:{self._cdp_port}",
                timeout=15000,
            )

            if self._browser.contexts:
                self._context = self._browser.contexts[0]
            else:
                self._context = self._browser.new_context()

            # Login using FacebookLogin engine
            if self._account.get("username") and self._account.get("password"):
                self._do_account_login()
            elif self._cookies:
                # Legacy: cookie injection
                self._inject_cookies_cdp()

            logger.info("Chrome đã sẵn sàng")
            return True

        except Exception as e:
            logger.error(f"Lỗi khởi động Chrome: {str(e)[:200]}")
            self.stop()
            return False

    def _cdp_is_ready(self) -> bool:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self._cdp_port}/json/version", timeout=1.5
            ) as response:
                return response.status == 200
        except Exception:
            return False

    def _do_account_login(self) -> None:
        """Login using FacebookLogin engine."""
        from core.fb_login import FacebookLogin

        tmp_page = self._context.new_page()
        try:
            login = FacebookLogin(tmp_page, self._account)
            success = login.ensure_logged_in()
            if not success:
                # Fallback to cookie if available
                cookie_str = self._account.get("cookie", "")
                if cookie_str:
                    logger.info("🔄 Thử fallback bằng cookie...")
                    from core.cookie_handler import parse_cookie_string
                    self._cookies = parse_cookie_string(cookie_str)
                    tmp_page.close()
                    self._inject_cookies_cdp()
                    return
                logger.warning("⚠ Đăng nhập thất bại — quét ở chế độ công khai")
        except Exception as e:
            logger.warning(f"Login error: {str(e)[:100]}")
        finally:
            try:
                tmp_page.close()
            except Exception:
                pass

    def stop(self):
        """Shutdown browser."""
        self._stop_event.set()
        try:
            if self._browser and not self._reused_browser:
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
        self._reused_browser = False

    def _inject_cookies_cdp(self) -> None:
        """Inject cookies via CDP for reliable authentication in Chrome.
        
        Steps:
        1. Clear ALL existing facebook.com cookies (avoid conflicts)
        2. Set fresh cookies via CDP Network.setCookie  
        3. Navigate to facebook.com to verify login
        """
        if not self._context:
            return

        # Open a temporary page to inject cookies
        tmp_page = self._context.new_page()

        try:
            # Get CDP session
            cdp = tmp_page.context.new_cdp_session(tmp_page)

            # Step 1: Clear ALL existing Facebook cookies
            try:
                # Get all existing cookies for facebook.com
                result = cdp.send("Network.getCookies", {
                    "urls": ["https://www.facebook.com", "https://m.facebook.com"]
                })
                existing = result.get("cookies", [])
                if existing:
                    logger.info(f"Xóa {len(existing)} cookies cũ...")
                    for c in existing:
                        try:
                            cdp.send("Network.deleteCookies", {
                                "name": c["name"],
                                "domain": c.get("domain", ".facebook.com"),
                                "path": c.get("path", "/"),
                            })
                        except Exception:
                            pass
            except Exception:
                pass

            # Step 2: Set fresh cookies via CDP
            for name, value in self._cookies.items():
                try:
                    cdp.send("Network.setCookie", {
                        "name": name,
                        "value": value,
                        "domain": ".facebook.com",
                        "path": "/",
                        "url": "https://www.facebook.com/",
                        "secure": True,
                        "httpOnly": name in ("c_user", "xs", "datr", "fr"),
                    })
                except Exception:
                    pass

            # Also add via Playwright context
            pw_cookies = [
                {
                    "name": k,
                    "value": v,
                    "domain": ".facebook.com",
                    "path": "/",
                    "secure": True,
                }
                for k, v in self._cookies.items()
            ]
            self._context.add_cookies(pw_cookies)

            # Step 3: Navigate to facebook to verify login
            tmp_page.goto("https://www.facebook.com/", wait_until="load", timeout=20000)
            time.sleep(4)

            # Check login state
            login_ok = "/login" not in tmp_page.url
            check = tmp_page.evaluate("""() => {
                const nav = document.querySelector('[role="navigation"]');
                const feed = document.querySelector('[role="feed"]');
                const loginForm = document.querySelector('#login_form, form[action*="login"]');
                const bodyText = document.body.innerText.slice(0, 200);
                return {
                    hasNav: !!nav,
                    hasFeed: !!feed,
                    loginForm: !!loginForm,
                    bodyStart: bodyText,
                };
            }""")

            if check.get("hasNav") or check.get("hasFeed"):
                logger.info("✅ Đã đăng nhập Facebook thành công")
            elif "Tiếp tục" in check.get("bodyStart", "") or "Continue" in check.get("bodyStart", ""):
                # Facebook's "Continue as..." confirmation page
                logger.info("🔄 Đang xác nhận đăng nhập...")
                try:
                    # Click the continue button using DOM search (most reliable)
                    clicked = tmp_page.evaluate("""() => {
                        const spans = document.querySelectorAll('span');
                        for (const s of spans) {
                            const text = s.textContent.trim();
                            if (text === 'Tiếp tục' || text === 'Continue') {
                                const btn = s.closest('[role="button"]') || s.parentElement;
                                if (btn) { btn.click(); return true; }
                            }
                        }
                        return false;
                    }""")
                    
                    if clicked:
                        time.sleep(5)
                        # Check result after click
                        post_click = tmp_page.evaluate("""() => ({
                            hasNav: !!document.querySelector('[role="navigation"]'),
                            hasFeed: !!document.querySelector('[role="feed"]'),
                            hasPasswordInput: !!document.querySelector('input[type="password"]'),
                            bodyText: document.body.innerText.slice(0, 100),
                        })""")
                        
                        if post_click.get("hasNav") or post_click.get("hasFeed"):
                            logger.info("✅ Đã đăng nhập Facebook thành công")
                        elif post_click.get("hasPasswordInput") or "mật khẩu" in post_click.get("bodyText", "").lower():
                            logger.warning("⚠ COOKIES ĐÃ HẾT HẠN!")
                            logger.warning("📋 Bấm nút Tài khoản ở thanh trên cùng để cập nhật cookies mới")
                            logger.warning("Tiếp tục quét ở chế độ công khai (giới hạn dữ liệu)...")
                        else:
                            logger.info("✅ Đã xác nhận đăng nhập")
                    else:
                        logger.warning("⚠ Cookies cần xác nhận lại — quét trong chế độ công khai")
                except Exception:
                    logger.warning("⚠ Không thể xác nhận đăng nhập tự động")
            elif check.get("loginForm"):
                logger.warning("⚠ Cookies không hợp lệ hoặc đã hết hạn!")
                logger.warning("📋 Bấm nút Tài khoản ở thanh trên cùng để cập nhật cookies mới")
            else:
                logger.info("✅ Facebook đã nhận cookies")

            cdp.detach()

        except Exception as e:
            logger.warning(f"Cookie injection: {str(e)[:100]}")
        finally:
            try:
                tmp_page.close()
            except Exception:
                pass

    def request_stop(self):
        self._stop_event.set()

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    def scrape_page(
        self,
        page_url: str,
        max_posts: int = 50,
        on_progress: Optional[Callable] = None,
        known_post_ids: Optional[set] = None,
        stop_post_ids: Optional[set] = None,
        archive_after_post_ids: Optional[set] = None,
        delay_profile: Optional[dict] = None,
    ) -> List[ScrapedPost]:
        """Scrape up to max_posts from a Facebook Page.
        
        Args:
            known_post_ids: IDs filtered from the returned results.
            stop_post_ids: Previous cursor markers used as the incremental boundary.
        """
        if not self._context:
            logger.error("Chrome chưa khởi tạo")
            return []

        self._stop_event.clear()
        self.last_observed_post_ids = []
        self.last_scan_stop_reason = ""
        self.last_scan_complete = False
        self.last_archive_boundary_found = False
        url = self._normalize_page_url(page_url)
        logger.info(f"Đang tải: {url}")
        if known_post_ids:
            logger.info(f"🆕 Chế độ Quét bài mới — bỏ qua {len(known_post_ids)} bài đã quét")

        collector = _PostCollector()
        page = None

        try:
            page = self._context.new_page()
            page.set_viewport_size({"width": 1280, "height": 900})

            # Set up response interception for ALL responses with post data
            def on_response(response):
                try:
                    resp_url = response.url
                    # Skip static resources
                    if any(ext in resp_url for ext in [".js", ".css", ".png", ".jpg", ".gif", ".woff", ".svg"]):
                        return
                    body = response.text()
                    if '"post_id"' not in body and '"creation_time"' not in body:
                        return
                    new = collector.process_response_body(body)
                    if new > 0:
                        logger.debug(
                            f"Response: +{new} bài (tổng: {collector.count})"
                        )
                except Exception:
                    pass

            page.on("response", on_response)

            # Navigate
            page.goto(url, wait_until="load", timeout=30000)
            time.sleep(5)

            # Check for login redirect
            if "/login" in page.url:
                logger.error("Cookies hết hạn — bị redirect tới login")
                return []

            # Check if 'Tiếp tục' confirmation page appears on target
            body_text = page.evaluate("() => document.body.innerText.slice(0, 200)")
            if "Tiếp tục" in body_text and "Dùng trang cá nhân khác" in body_text:
                logger.warning("⚠ Cookies hết hạn — trang yêu cầu đăng nhập lại")
                logger.warning("Vui lòng bấm nút Tài khoản ở thanh trên cùng để cập nhật cookies mới")

            # Extract page name
            page_name = self._extract_page_name(page)
            logger.info(f"Page: {page_name}")

            # Extract follower count
            self.last_follower_count = self._extract_follower_count(page)
            if self.last_follower_count > 0:
                logger.info(f"👥 Followers: {self.last_follower_count:,}")

            # Also parse the initial page source (SSR data)
            try:
                html = page.evaluate("() => document.documentElement.outerHTML")
                initial = collector.process_response_body(html)
                if initial > 0:
                    logger.info(f"Dữ liệu ban đầu: {initial} bài")
            except Exception:
                pass

            boundary_ids = stop_post_ids if stop_post_ids is not None else known_post_ids
            if archive_after_post_ids is not None:
                self.last_scan_stop_reason = self._scroll_for_archive_posts(
                    page, collector, max_posts, on_progress,
                    known_post_ids or set(), archive_after_post_ids, delay_profile,
                )
            else:
                initial_ids = {str(item.get("post_id") or "") for item in collector.get_posts()}
                if boundary_ids and initial_ids.intersection(boundary_ids):
                    self.last_scan_stop_reason = "boundary"
                    logger.info("🆕 Đã gặp mốc quét trước trong dữ liệu ban đầu")
                else:
                    self.last_scan_stop_reason = self._scroll_for_posts(
                        page, collector, max_posts, on_progress, boundary_ids, delay_profile
                    )

            self.last_observed_post_ids = [
                str(item.get("post_id") or "")
                for item in collector.get_posts()
                if str(item.get("post_id") or "")
            ]
            self.last_scan_complete = self.last_scan_stop_reason in {"boundary", "exhausted"}

            # Scroll back to top so DOM enrichment can see the newest posts
            try:
                page.evaluate("() => window.scrollTo(0, 0)")
                time.sleep(2)
            except Exception:
                pass

            # Enrich engagement + dates from DOM (may not be in JSON)
            self._enrich_engagement_from_dom(page, collector)

            # Build final results
            posts = self._build_results(
                collector, page_name, max_posts, known_post_ids,
                archive_after_post_ids=archive_after_post_ids,
            )
            if archive_after_post_ids is not None:
                self.last_observed_post_ids = [post.post_id for post in posts if post.post_id]
                self.last_scan_complete = self.last_archive_boundary_found and self.last_scan_stop_reason in {"limit", "exhausted"}

            logger.info(
                f"Hoàn thành: {len(posts)} bài viết từ '{page_name}'"
            )
            return posts

        except Exception as e:
            self.last_scan_stop_reason = "error"
            logger.error(f"Lỗi quét page: {str(e)[:200]}")
            return []
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    def _scroll_for_posts(
        self,
        page,
        collector: _PostCollector,
        max_posts: int,
        on_progress: Optional[Callable],
        known_post_ids: Optional[set] = None,
        delay_profile: Optional[dict] = None,
    ) -> str:
        """Scroll the page to trigger GraphQL data loading.
        
        Facebook uses either window scroll OR a #scrollview div container.
        We detect which one is active and scroll that.
        
        If known_post_ids is set (scan-new mode), stops when enough known
        posts are encountered consecutively.
        """
        no_new_count = 0
        prev_count = collector.count
        max_scrolls = max(max_posts * 3, 50)
        last_pause_bucket = 0

        for i in range(max_scrolls):
            if self._stop_event.is_set():
                logger.info("⏹ Đã dừng quét")
                return "stopped"

            if collector.count >= max_posts:
                logger.info(f"Đã đạt {max_posts} bài")
                return "limit"

            # Scroll both window AND #scrollview container
            page.evaluate("""() => {
                // Scroll window (works on some page layouts)
                window.scrollBy(0, 1200);
                
                // Scroll #scrollview container (Facebook's inner scroll)
                const sv = document.getElementById('scrollview');
                if (sv) {
                    sv.scrollTop += 1200;
                    sv.dispatchEvent(new Event('scroll', {bubbles: true}));
                }
            }""")
            time.sleep(2.0)

            current = collector.count
            if current > prev_count:
                new = current - prev_count
                no_new_count = 0
                logger.info(
                    f"Scroll #{i + 1}: +{new} bài (tổng: {current})"
                )
                if on_progress:
                    on_progress(min(current, max_posts), f"{current}/{max_posts}")
                self._enrich_previews_from_dom(page, collector)

                # Stop as soon as one stable marker from the previous successful scan appears.
                if known_post_ids:
                    new_posts = collector.get_posts()
                    recent_ids = [p["post_id"] for p in new_posts[prev_count:]]
                    overlap = [pid for pid in recent_ids if pid in known_post_ids]
                    if overlap:
                        logger.info("🆕 Đã gặp mốc quét trước — dừng quét bài mới")
                        return "boundary"

                last_pause_bucket = self._maybe_rest_after_batch(
                    current, max_posts, last_pause_bucket, delay_profile, on_progress
                )

                prev_count = current
            else:
                no_new_count += 1

            # Stop if no new posts after many scrolls
            if no_new_count >= 12:
                logger.info("Không còn bài mới")
                return "exhausted"
        return "exhausted"

    @staticmethod
    def _archive_candidates(raw: List[dict], known_ids: set, boundary_ids: set) -> tuple[bool, List[dict]]:
        """Return unknown posts occurring after the oldest matched archive marker."""
        if not boundary_ids:
            return True, [item for item in raw if str(item.get("post_id") or "") not in known_ids]
        matched = [
            index for index, item in enumerate(raw)
            if str(item.get("post_id") or "") in boundary_ids
        ]
        if not matched:
            return False, []
        edge = max(matched)
        return True, [
            item for item in raw[edge + 1:]
            if str(item.get("post_id") or "") and str(item.get("post_id") or "") not in known_ids
        ]

    def _scroll_for_archive_posts(
        self, page, collector: _PostCollector, max_posts: int,
        on_progress: Optional[Callable], known_ids: set, boundary_ids: set,
        delay_profile: Optional[dict],
    ) -> str:
        """Seek the oldest saved boundary, then collect the next historical batch."""
        no_new_count = 0
        previous_total = collector.count
        last_pause_bucket = 0
        max_scrolls = max(min((len(known_ids) + max_posts) * 3, 6000), 100)

        for index in range(max_scrolls):
            if self._stop_event.is_set():
                return "stopped"
            boundary_found, candidates = self._archive_candidates(
                collector.get_posts(), known_ids, boundary_ids
            )
            self.last_archive_boundary_found = boundary_found
            if boundary_found and len(candidates) >= max_posts:
                logger.info(f"Đã lấy đủ {max_posts} bài cũ sau mốc lưu")
                return "limit"

            page.evaluate("""() => {
                window.scrollBy(0, 1200);
                const sv = document.getElementById('scrollview');
                if (sv) { sv.scrollTop += 1200; sv.dispatchEvent(new Event('scroll', {bubbles: true})); }
            }""")
            time.sleep(2.0)
            current_total = collector.count
            if current_total > previous_total:
                no_new_count = 0
                previous_total = current_total
                boundary_found, candidates = self._archive_candidates(
                    collector.get_posts(), known_ids, boundary_ids
                )
                self.last_archive_boundary_found = boundary_found
                self._enrich_previews_from_dom(page, collector)
                if on_progress:
                    message = f"Đã gặp mốc · {len(candidates)}/{max_posts}" if boundary_found else "Đang tìm mốc bài cũ nhất…"
                    on_progress(min(len(candidates), max_posts), message)
                if boundary_found:
                    last_pause_bucket = self._maybe_rest_after_batch(
                        len(candidates), max_posts, last_pause_bucket, delay_profile, on_progress
                    )
            else:
                no_new_count += 1
            if no_new_count >= 12:
                return "exhausted"
        return "exhausted"

    def _maybe_rest_after_batch(
        self, count: int, target: int, previous_bucket: int,
        profile: Optional[dict], on_progress: Optional[Callable],
    ) -> int:
        if not profile or count >= target:
            return previous_bucket
        batch_size = max(1, int(profile.get("batch_size", 100)))
        bucket = count // batch_size
        if bucket <= previous_bucket:
            return previous_bucket
        long_every = max(batch_size, int(profile.get("long_break_every", 500)))
        is_long = count > 0 and count % long_every < batch_size
        low, high = (
            (profile.get("long_delay_min", 90), profile.get("long_delay_max", 180))
            if is_long else (profile.get("delay_min", 20), profile.get("delay_max", 40))
        )
        seconds = random.uniform(max(0, float(low)), max(float(low), float(high)))
        logger.info(f"⏳ Nghỉ {seconds:.0f} giây sau {count} bài")
        if on_progress:
            on_progress(count, f"Đang nghỉ {seconds:.0f} giây sau {count} bài")
        deadline = time.time() + seconds
        while time.time() < deadline and not self._stop_event.is_set():
            time.sleep(min(0.5, deadline - time.time()))
        return bucket

    def _enrich_previews_from_dom(self, page, collector: _PostCollector) -> int:
        """Merge already-rendered post thumbnails without fetching full-size media."""
        try:
            previews = page.evaluate("""() => {
                const results = [];
                const extractPostId = href => {
                    const match = String(href || '').match(/(?:posts|videos|permalink)\/?(\d{10,})|(pfbid[A-Za-z0-9]+)|facebook\.com\/(\d{15,})/);
                    return match ? (match[1] || match[2] || match[3] || '') : '';
                };
                for (const article of document.querySelectorAll('[role="article"]')) {
                    let postId = '';
                    for (const link of article.querySelectorAll('a[href]')) {
                        postId = extractPostId(link.href);
                        if (postId) break;
                    }
                    if (!postId) continue;
                    let best = null;
                    for (const element of article.querySelectorAll('video[poster], img[src], img[srcset]')) {
                        const url = element.tagName === 'VIDEO'
                            ? (element.poster || '') : (element.currentSrc || element.src || '');
                        if (!/^https:\/\/[^/]*fbcdn\.net\//i.test(url)) continue;
                        const description = `${element.alt || ''} ${element.getAttribute('aria-label') || ''}`.toLowerCase();
                        if (/(avatar|ảnh đại diện|profile picture|emoji|icon|logo|sticker)/i.test(description)) continue;
                        const width = Number(element.naturalWidth || element.videoWidth || element.clientWidth || 0);
                        const height = Number(element.naturalHeight || element.videoHeight || element.clientHeight || 0);
                        if ((width && width < 160) || (height && height < 90)) continue;
                        const score = (element.tagName === 'VIDEO' ? 1000000000 : 0) + Math.max(1, width * height);
                        if (!best || score > best.score) best = {url, score};
                    }
                    if (best) results.push({postId, url: best.url});
                }
                return results;
            }""")
            merged = 0
            with collector._lock:
                for item in previews or []:
                    post_id = str(item.get("postId") or "")
                    preview = collector._valid_preview_url(item.get("url"))
                    post = collector._posts.get(post_id)
                    if post and preview and not post.get("media_preview_url"):
                        post["media_preview_url"] = preview
                        post["media_count"] = max(1, int(post.get("media_count", 0) or 0))
                        merged += 1
            if merged:
                logger.debug(f"[DOM] Bổ sung thumbnail cho {merged} bài đang hiển thị")
            return merged
        except Exception as exc:
            logger.debug(f"DOM preview enrichment skipped: {str(exc)[:120]}")
            return 0

    def _enrich_engagement_from_dom(self, page, collector: _PostCollector) -> None:
        """Enrich posts with engagement data AND dates from visible DOM.
        
        Facebook often renders engagement text ('45 bình luận') and relative
        dates ('14 giờ', '29 tháng 1') in the DOM but NOT in GraphQL JSON.
        This scans the rendered page to fill in missing data.
        """
        try:
            logger.debug("[DOM] Starting DOM enrichment scan...")
            engagement_data = page.evaluate("""() => {
                const results = [];
                const processedPostIds = new Set();
                
                // Helper: parse a number string with K/M/N suffix
                function parseNum(s) {
                    if (!s) return 0;
                    let n = s.toUpperCase().trim().replace('N', 'K');
                    let mul = 1;
                    if (n.endsWith('K')) { mul = 1000; n = n.slice(0, -1); }
                    else if (n.endsWith('M')) { mul = 1000000; n = n.slice(0, -1); }
                    else if (n.endsWith('B')) { mul = 1000000000; n = n.slice(0, -1); }
                    if (mul > 1) n = n.replace(',', '.');
                    else n = n.replace(/[.,]/g, '');
                    return Math.round(parseFloat(n) * mul) || 0;
                }
                
                // Helper: parse Vietnamese relative date to dd/mm/yyyy
                function parseDate(text) {
                    const now = new Date();
                    
                    // "X phút" → today
                    if (/\d+\s*phút/.test(text)) {
                        return now.toLocaleDateString('en-GB'); // dd/mm/yyyy
                    }
                    // "X giờ" → today
                    if (/\d+\s*giờ/.test(text)) {
                        return now.toLocaleDateString('en-GB');
                    }
                    // "Hôm qua" → yesterday
                    if (/hôm qua/i.test(text)) {
                        const d = new Date(now);
                        d.setDate(d.getDate() - 1);
                        return d.toLocaleDateString('en-GB');
                    }
                    // "Hôm nay" → today
                    if (/hôm nay/i.test(text)) {
                        return now.toLocaleDateString('en-GB');
                    }
                    // "X ngày" → X days ago
                    const daysMatch = text.match(/(\d+)\s*ngày/);
                    if (daysMatch) {
                        const d = new Date(now);
                        d.setDate(d.getDate() - parseInt(daysMatch[1]));
                        return d.toLocaleDateString('en-GB');
                    }
                    // "DD tháng MM" or "DD tháng MM, YYYY"
                    const vnDateMatch = text.match(/(\d{1,2})\s*tháng\s*(\d{1,2})(?:,?\s*(\d{4}))?/);
                    if (vnDateMatch) {
                        const day = vnDateMatch[1].padStart(2, '0');
                        const month = vnDateMatch[2].padStart(2, '0');
                        const year = vnDateMatch[3] || now.getFullYear().toString();
                        return `${day}/${month}/${year}`;
                    }
                    // "Tháng MM DD, YYYY" (another format)
                    const vnDateMatch2 = text.match(/tháng\s*(\d{1,2})\s*(\d{1,2}),?\s*(\d{4})/i);
                    if (vnDateMatch2) {
                        const month = vnDateMatch2[1].padStart(2, '0');
                        const day = vnDateMatch2[2].padStart(2, '0');
                        const year = vnDateMatch2[3];
                        return `${day}/${month}/${year}`;
                    }
                    return '';
                }
                
                // Helper: extract post ID from a link href
                function extractPostId(href) {
                    const m1 = href.match(/(?:posts|videos|permalink)\/?(\d{10,})/);
                    if (m1) return m1[1];
                    const m2 = href.match(/(pfbid[A-Za-z0-9]+)/);
                    if (m2) return m2[1];
                    const m3 = href.match(/facebook\.com\/(\d{15,})/);
                    if (m3) return m3[1];
                    return '';
                }
                
                // Scan all article elements (each = one post on the page)
                const articles = document.querySelectorAll('[role="article"]');
                for (const article of articles) {
                    const text = article.innerText || '';
                    
                    // Find post ID from ALL links in the article
                    // Use link.href (resolved absolute URL) not getAttribute('href')
                    // because Facebook often uses relative URLs like /122129141792999978
                    const links = article.querySelectorAll('a[href]');
                    let postId = '';
                    for (const link of links) {
                        const h = link.href || '';  // resolved absolute URL
                        postId = extractPostId(h);
                        if (postId) break;
                    }
                    if (!postId || processedPostIds.has(postId)) continue;
                    processedPostIds.add(postId);
                    
                    // Extract date from time-related text
                    // Facebook shows dates near the page name, e.g. "14 giờ", "29 tháng 1"
                    let dateStr = '';
                    const timeElements = article.querySelectorAll('a[href] span, abbr, [data-utime], span[id]');
                    for (const el of timeElements) {
                        const t = (el.innerText || el.getAttribute('title') || '').trim();
                        if (t && (/(\d+\s*(giờ|phút|ngày))|(tháng\s*\d)|(hôm\s*(qua|nay))/i.test(t))) {
                            dateStr = parseDate(t);
                            if (dateStr) break;
                        }
                    }
                    // Also try link text that looks like a date
                    if (!dateStr) {
                        for (const link of links) {
                            const t = (link.innerText || '').trim();
                            if (t && /(\d+\s*(giờ|phút|ngày))|(tháng\s*\d)|(hôm\s*(qua|nay))/i.test(t)) {
                                dateStr = parseDate(t);
                                if (dateStr) break;
                            }
                        }
                    }
                    
                    // Extract engagement
                    let comments = 0, shares = 0, reactions = 0, views = 0;
                    
                    const cmtM = text.match(/([\d,.]+[KkMmNn]?)\s*(?:bình luận|comments?)/i);
                    if (cmtM) comments = parseNum(cmtM[1]);
                    
                    const shareM = text.match(/([\d,.]+[KkMmNn]?)\s*(?:lượt chia sẻ|chia sẻ|shares?)/i);
                    if (shareM) shares = parseNum(shareM[1]);
                    
                    const reactM = text.match(/([\d,.]+[KkMmNn]?)\s*(?:lượt thích|likes?|reactions?)/i);
                    if (reactM) reactions = parseNum(reactM[1]);

                    const viewM = text.match(/([\d,.]+[KkMmBbNn]?)\s*(?:lượt xem|views?|plays?)/i);
                    if (viewM) views = parseNum(viewM[1]);

                    // Reuse an already-rendered thumbnail. Reading currentSrc/poster
                    // does not open the post or download the full-size attachment.
                    let mediaPreviewUrl = '';
                    let bestPreviewScore = -1;
                    const mediaNodes = [
                        ...article.querySelectorAll('video[poster]'),
                        ...article.querySelectorAll('img[src], img[srcset]')
                    ];
                    for (const mediaNode of mediaNodes) {
                        const candidate = mediaNode.tagName === 'VIDEO'
                            ? (mediaNode.poster || '')
                            : (mediaNode.currentSrc || mediaNode.src || '');
                        if (!candidate || !/^https:\/\/[^/]*fbcdn\.net\//i.test(candidate)) continue;
                        const description = `${mediaNode.alt || ''} ${mediaNode.getAttribute('aria-label') || ''}`.toLowerCase();
                        if (/(avatar|ảnh đại diện|profile picture|emoji|icon|logo|sticker)/i.test(description)) continue;
                        const width = Number(mediaNode.naturalWidth || mediaNode.videoWidth || mediaNode.clientWidth || 0);
                        const height = Number(mediaNode.naturalHeight || mediaNode.videoHeight || mediaNode.clientHeight || 0);
                        if ((width && width < 160) || (height && height < 90)) continue;
                        const score = (mediaNode.tagName === 'VIDEO' ? 1000000000 : 0) + Math.max(1, width * height);
                        if (score > bestPreviewScore) {
                            bestPreviewScore = score;
                            mediaPreviewUrl = candidate;
                        }
                    }
                    
                    if (comments > 0 || shares > 0 || reactions > 0 || views > 0 || dateStr || mediaPreviewUrl) {
                        results.push({
                            postId: postId,
                            comments: comments,
                            shares: shares,
                            reactions: reactions,
                            views: views,
                            date: dateStr,
                            mediaPreviewUrl: mediaPreviewUrl,
                        });
                    }
                }
                
                return results;
            }""")

            if not engagement_data:
                logger.debug("[DOM] No articles found or no engagement data extracted")
                return

            logger.debug(f"[DOM] Found {len(engagement_data)} article(s) with data")

            # Merge DOM data into collector's posts
            enriched = 0
            with collector._lock:
                for item in engagement_data:
                    pid = item.get("postId", "")
                    if not pid:
                        continue

                    # Try exact match first
                    post = collector._posts.get(pid)

                    # If not found by exact ID, try to match by URL substring
                    if not post:
                        for existing_pid, existing_post in collector._posts.items():
                            post_url = existing_post.get("url", "")
                            if pid in post_url or existing_pid in pid:
                                post = existing_post
                                break

                    if not post:
                        continue

                    changed = False
                    if item.get("comments", 0) > 0 and post.get("comments", 0) == 0:
                        post["comments"] = item["comments"]
                        changed = True
                    if item.get("shares", 0) > 0 and post.get("shares", 0) == 0:
                        post["shares"] = item["shares"]
                        changed = True
                    if item.get("reactions", 0) > 0 and post.get("engagement", 0) == 0:
                        post["engagement"] = item["reactions"]
                        changed = True
                    if item.get("views", 0) > post.get("view_count", 0):
                        post["view_count"] = item["views"]
                        changed = True
                    if item.get("date") and not post.get("date"):
                        post["date"] = item["date"]
                        changed = True
                    dom_preview = self._valid_preview_url(item.get("mediaPreviewUrl"))
                    if dom_preview and not post.get("media_preview_url"):
                        post["media_preview_url"] = dom_preview
                        post["media_count"] = max(1, int(post.get("media_count", 0) or 0))
                        changed = True
                    if changed:
                        enriched += 1
                        if enriched <= 3:
                            logger.debug(
                                f"[DOM] Enriched {pid[:20]}: "
                                f"date={item.get('date','')}, "
                                f"react={item.get('reactions',0)}, "
                                f"cmt={item.get('comments',0)}, "
                                f"shares={item.get('shares',0)}, "
                                f"views={item.get('views',0)}"
                            )

            if enriched > 0:
                logger.info(f"📊 DOM enrichment: bổ sung dữ liệu cho {enriched} bài viết")

        except Exception as e:
            logger.warning(f"⚠ DOM enrichment error: {str(e)[:200]}")

    def _build_results(
        self,
        collector: _PostCollector,
        page_name: str,
        max_posts: int,
        known_post_ids: Optional[set] = None,
        archive_after_post_ids: Optional[set] = None,
    ) -> List[ScrapedPost]:
        """Convert collected data to ScrapedPost list, sorted by date.
        
        If known_post_ids is provided, filters out already-known posts.
        """
        raw = collector.get_posts()
        if archive_after_post_ids is not None:
            boundary_found, raw = self._archive_candidates(
                raw, known_post_ids or set(), archive_after_post_ids
            )
            self.last_archive_boundary_found = boundary_found

        posts = []
        skipped = 0
        for item in raw:
            # In scan-new mode, skip already-known posts
            if known_post_ids and item.get("post_id", "") in known_post_ids:
                skipped += 1
                continue

            post = ScrapedPost(
                date=item.get("date", ""),
                post_id=item.get("post_id", ""),
                post_type=item.get("post_type", "Text"),
                engagement=item.get("engagement", 0),
                comments=item.get("comments", 0),
                shares=item.get("shares", 0),
                view_count=item.get("view_count", 0),
                caption=item.get("caption", ""),
                url=item.get("url", ""),
                media_preview_url=item.get("media_preview_url", ""),
                media_count=item.get("media_count", 0),
                page_name=page_name,
            )
            posts.append(post)

        if known_post_ids and skipped > 0:
            logger.info(f"🆕 Bỏ qua {skipped} bài đã quét, giữ {len(posts)} bài mới")

        # Sort by date (newest first), parsing dd/mm/yyyy
        # Posts without date are typically the newest (from SSR initial load)
        # so they sort to the top.
        def date_sort_key(p):
            try:
                return datetime.strptime(p.date, "%d/%m/%Y")
            except (ValueError, TypeError):
                return datetime.max

        posts.sort(key=date_sort_key, reverse=True)
        return posts[:max_posts]

    def _normalize_page_url(self, url: str) -> str:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(url)
        path = parsed.path.strip("/")

        # Handle profile.php?id=XXXXX format
        if path == "profile.php":
            qs = parse_qs(parsed.query)
            pid = qs.get("id", [None])[0]
            if pid:
                return f"https://www.facebook.com/profile.php?id={pid}"
            return url

        for suffix in [
            "posts",
            "photos",
            "videos",
            "about",
            "reviews",
            "events",
        ]:
            if path.endswith(suffix):
                path = path[: path.rfind(suffix)].strip("/")

        first_segment = path.split("/")[0] if path else ""
        if not first_segment:
            return url

        return f"https://www.facebook.com/{first_segment}"

    def _extract_page_name(self, page) -> str:
        """Extract page name from the page, avoiding FB UI elements.
        
        Strategy:
        1. Try og:title meta tag
        2. Try document.title (cleaned)
        3. Try the profile/page name from specific DOM selectors
        4. Fallback: h1/h2 with comprehensive skip list
        5. Last resort: extract from URL
        """
        try:
            name = page.evaluate(
                """() => {
                const genericLabels = new Set([
                    'chi tiết', 'details', 'xem thêm', 'see more', 'bài viết', 'post',
                    'ảnh', 'photos', 'video', 'videos', 'reels', 'trang', 'page',
                    'facebook', 'thông báo', 'notifications', 'đoạn chat', 'chats',
                    'thông tin liên hệ', 'contact info', 'giới thiệu', 'about'
                ]);
                const validName = value => {
                    const name = String(value || '').replace(/\s+/g, ' ').trim();
                    return name.length > 1 && name.length <= 300 && !genericLabels.has(name.toLocaleLowerCase('vi'));
                };
                // 1. Best: og:title meta tag
                let og = document.querySelector('meta[property="og:title"]');
                if (og && og.content) {
                    let t = og.content.trim();
                    if (validName(t)) return t;
                }

                // 2. Title tag (cleaned)
                let title = document.title || '';
                title = title.replace(/\\s*[|(].*$/, '')
                             .replace(/\\s*-\\s*Facebook.*$/i, '')
                             .replace(/Facebook$/, '')
                             .trim();
                if (validName(title)) return title;

                // 3. Try specific Facebook page name selectors
                // Profile/Page name is usually in a prominent h1 inside main content
                let mainContent = document.querySelector('[role="main"]');
                if (mainContent) {
                    let mainH1 = mainContent.querySelector('h1');
                    if (mainH1) {
                        let t = mainH1.innerText.trim();
                        if (validName(t)) return t;
                    }
                }

                // 4. Try aria-label of profile image
                let profileImg = document.querySelector('image[style*="border-radius"]');
                if (profileImg) {
                    let label = profileImg.getAttribute('aria-label') || '';
                    let alt = profileImg.closest('svg')?.getAttribute('aria-label') || '';
                    let t = (label || alt).trim();
                    if (validName(t)) return t;
                }

                // 5. Fallback: h1 but skip known FB UI labels
                const skipLabels = [
                    // Vietnamese UI
                    'Thông báo', 'Đoạn chat', 'Trang chủ', 'Watch', 'Marketplace',
                    'Đăng nhập', 'Tạo tài khoản', 'Bạn bè', 'Nhóm', 'Video',
                    'Reels', 'Kỷ niệm', 'Đã lưu', 'Quảng cáo', 'Sự kiện',
                    'Trang', 'Chơi game', 'Tin', 'Cửa hàng',
                    // English UI
                    'Facebook', 'Notifications', 'Messenger', 'Log in', 'Sign Up',
                    'Home', 'Friends', 'Groups', 'Gaming', 'Bookmarks',
                    'Memories', 'Saved', 'Events', 'Pages', 'News Feed',
                    'Chats',
                ];
                let allH1 = document.querySelectorAll('h1');
                for (let h of allH1) {
                    let t = h.innerText.trim();
                    if (validName(t) && !skipLabels.includes(t)) return t;
                }

                // 6. Try h2 inside main content only
                if (mainContent) {
                    let h2 = mainContent.querySelector('h2');
                    if (h2) {
                        let t = h2.innerText.trim();
                        if (validName(t) && !skipLabels.includes(t)) return t;
                    }
                }

                return '';
            }"""
            )
            if is_valid_facebook_page_name(name):
                return name
        except Exception:
            pass

        # Try extracting page name from GraphQL data in page source
        try:
            name_from_json = page.evaluate(
                """() => {
                // Search for page name in embedded JSON data
                let scripts = document.querySelectorAll('script[type="application/json"]');
                for (let s of scripts) {
                    try {
                        let text = s.textContent;
                        // Look for "name":"PageName" near "__typename":"Page"
                        let pageMatch = text.match(/"__typename":\s*"(?:Page|User)"[^}]*"name":\s*"([^"]{2,})"/)
                                     || text.match(/"name":\s*"([^"]{2,})"[^}]*"__typename":\s*"(?:Page|User)"/)
                                     || text.match(/"page_name":\s*"([^"]{2,})"/);
                        if (pageMatch) return pageMatch[1];
                    } catch(e) {}
                }
                return '';
            }"""
            )
            if is_valid_facebook_page_name(name_from_json):
                return name_from_json
        except Exception:
            pass

        # Last resort: extract from URL
        try:
            url = page.url
            import re
            match = re.search(r'facebook\.com/([^/?&#]+)', url)
            if match:
                slug = match.group(1)
                if slug not in ('pages', 'profile.php', 'groups', 'watch', 'login'):
                    return slug.replace('.', ' ').title()
        except Exception:
            pass

        return "Unknown Page"

    def _extract_follower_count(self, page) -> int:
        """Extract follower count from the Facebook page DOM."""
        try:
            count = page.evaluate("""() => {
                // Search for follower text in page content
                const body = document.body.innerText || '';

                // Vietnamese: "1.234 người theo dõi" or "1,234 người theo dõi"
                // English: "1,234 followers" or "1.2K followers"
                const patterns = [
                    /([\d.,]+(?:\s*[KkMm])?)\s*người theo dõi/i,
                    /([\d.,]+(?:\s*[KkMm])?)\s*follower/i,
                    /([\d.,]+(?:\s*[KkMm])?)\s*people follow/i,
                ];

                for (const pat of patterns) {
                    const match = body.match(pat);
                    if (match) {
                        let numStr = match[1].trim();

                        // Handle K/M suffixes
                        let multiplier = 1;
                        if (/[Kk]$/.test(numStr)) {
                            multiplier = 1000;
                            numStr = numStr.replace(/[Kk]$/, '');
                        } else if (/[Mm]$/.test(numStr)) {
                            multiplier = 1000000;
                            numStr = numStr.replace(/[Mm]$/, '');
                        }

                        // Parse: "1.234" (dot as thousands) or "1,234"
                        // If multiplier > 1, dot is decimal: "1.2K" = 1200
                        if (multiplier > 1) {
                            numStr = numStr.replace(/,/g, '.');
                            return Math.round(parseFloat(numStr) * multiplier);
                        }

                        // Otherwise remove thousands separators
                        numStr = numStr.replace(/[.,]/g, '');
                        const num = parseInt(numStr, 10);
                        if (!isNaN(num) && num > 0) return num;
                    }
                }

                // Try structured data from meta tags
                const metaDesc = document.querySelector('meta[name="description"]');
                if (metaDesc) {
                    const content = metaDesc.content || '';
                    for (const pat of patterns) {
                        const match = content.match(pat);
                        if (match) {
                            let numStr = match[1].trim().replace(/[.,]/g, '');
                            const num = parseInt(numStr, 10);
                            if (!isNaN(num) && num > 0) return num;
                        }
                    }
                }

                return 0;
            }""")
            return int(count) if count else 0
        except Exception:
            return 0
