"""
Tinix Facebook Down — Facebook Post Parser
Uses Playwright with a separate Chrome profile + CDP to fetch Facebook posts.
This bypasses all Facebook bot detection since it uses a real browser.
"""

import os
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from utils import logger
from utils.chrome_profiles import browser_profile_dir

# Suppress warnings
import warnings
warnings.filterwarnings("ignore")

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

CDP_PORT = 9223  # Different from default 9222 to avoid conflicts


@dataclass
class PostData:
    """Parsed Facebook post data."""
    post_id: str = ""
    author: str = ""
    timestamp: str = ""
    text: str = ""
    image_urls: List[str] = field(default_factory=list)
    has_video: bool = False
    video_url: str = ""
    original_url: str = ""
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None and (self.text or self.image_urls or self.has_video)

    @property
    def media_count(self) -> int:
        count = len(self.image_urls)
        if self.has_video:
            count += 1
        return count


def _find_chrome() -> Optional[str]:
    """Find Chrome executable path."""
    for path in CHROME_PATHS:
        expanded = os.path.expandvars(path)
        if os.path.exists(expanded):
            return expanded
    return None


def _get_profile_dir() -> Path:
    """Get a separate Chrome profile directory for the tool."""
    return browser_profile_dir()


class BrowserManager:
    """
    Manages a Chrome browser instance with Playwright CDP connection.
    Uses a separate profile so user's Chrome stays untouched.
    """

    def __init__(self, profile_dir: Optional[str] = None, cdp_port: Optional[int] = None, headless: bool = True):
        self._chrome_process = None
        self._browser = None
        self._context = None
        self._playwright = None
        self._pw_instance = None
        self._profile_dir = Path(profile_dir) if profile_dir else None
        self._cdp_port = cdp_port or CDP_PORT
        self._headless = headless

    def start(self, cookies: Dict[str, str]) -> bool:
        """Launch Chrome with remote debugging and connect Playwright."""
        try:
            from playwright.sync_api import sync_playwright

            chrome_path = _find_chrome()
            if not chrome_path:
                logger.error("Không tìm thấy Chrome. Vui lòng cài đặt Google Chrome.")
                return False

            profile_dir = self._profile_dir or _get_profile_dir()
            profile_dir.mkdir(parents=True, exist_ok=True)

            # Launch Chrome with remote debugging
            import subprocess
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
            if self._headless:
                chrome_cmd.append("--headless=new")

            logger.info("Đang khởi động trình duyệt...")
            self._chrome_process = subprocess.Popen(
                chrome_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            time.sleep(3)  # Wait for Chrome to start

            # Connect Playwright via CDP
            self._pw_instance = sync_playwright().start()
            self._browser = self._pw_instance.chromium.connect_over_cdp(
                f"http://localhost:{self._cdp_port}",
                timeout=15000,
            )

            # Get the default context
            if self._browser.contexts:
                self._context = self._browser.contexts[0]
            else:
                self._context = self._browser.new_context()

            # Inject cookies
            pw_cookies = []
            for name, value in cookies.items():
                pw_cookies.append({
                    "name": name,
                    "value": value,
                    "domain": ".facebook.com",
                    "path": "/",
                    "secure": True,
                })
            if pw_cookies:
                self._context.add_cookies(pw_cookies)

            logger.info("Trình duyệt đã sẵn sàng")
            return True

        except Exception as e:
            logger.error(f"Lỗi khởi động trình duyệt: {str(e)[:200]}")
            self.stop()
            return False

    def download_file(self, url: str, save_path) -> bool:
        """
        Download a file using the browser's authenticated session.
        This uses the browser's cookies/session, bypassing CDN 403 errors.
        """
        if not self._context:
            return False

        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        page = None
        try:
            page = self._context.new_page()

            # Use route to intercept and save response
            response = page.request.get(url, headers={
                "Referer": "https://www.facebook.com/",
                "Origin": "https://www.facebook.com",
            })

            if response.ok:
                body = response.body()
                with open(save_path, "wb") as f:
                    f.write(body)

                file_size = save_path.stat().st_size
                if file_size > 10000:
                    from core.media_downloader import _format_size
                    logger.info(f"Đã tải video (browser): {save_path.name} ({_format_size(file_size)})")
                    return True
                else:
                    logger.warning(f"File quá nhỏ ({file_size} bytes)")
                    save_path.unlink(missing_ok=True)
                    return False
            else:
                logger.error(f"Browser download failed: HTTP {response.status}")
                return False

        except Exception as e:
            logger.error(f"Browser download error: {str(e)[:150]}")
            return False
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    def fetch_post(self, url: str, post_id: str = "") -> PostData:
        """Fetch and parse a single Facebook post."""
        post_data = PostData(post_id=post_id, original_url=url)

        if not self._context:
            post_data.error = "Trình duyệt chưa được khởi động"
            return post_data

        page = None
        try:
            page = self._context.new_page()
            logger.info(f"Đang tải: {url[:80]}...")

            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Smart wait: wait for key elements instead of fixed 5s
            try:
                page.wait_for_selector(
                    'video, [role="article"], [role="dialog"], [role="main"], img[src*="scontent"]',
                    timeout=5000,
                )
            except Exception:
                pass  # Timeout is OK, proceed with what we have

            title = page.title()
            current_url = page.url

            # Check for error page
            error_el = page.query_selector('text="Lỗi không xác định"')
            if error_el:
                logger.info("Trang báo lỗi, đang thử lại...")
                page.reload(wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector('[role="article"], [role="main"], video', timeout=5000)
                except Exception:
                    pass

                error_el = page.query_selector('text="Lỗi không xác định"')
                if error_el:
                    post_data.error = "Facebook hiển thị lỗi. Cookies có thể đã hết hạn."
                    logger.error(post_data.error)
                    return post_data

            # Check for login page
            if "/login" in current_url:
                post_data.error = "Cookies không hợp lệ, bị chuyển hướng tới trang đăng nhập."
                logger.error(post_data.error)
                return post_data

            # Click "Xem thêm" / "See more" to expand truncated text
            self._click_see_more(page)
            page_html = ""
            try:
                page_html = page.evaluate("() => document.documentElement.innerHTML")
            except Exception:
                page_html = ""

            # Find the main post container
            article = self._find_main_article(page)
            if not article:
                logger.warning("Không tìm thấy bài viết chính trên trang")
                try:
                    debug_dir = _get_profile_dir().parent / "debug_html"
                    debug_dir.mkdir(exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    page.screenshot(path=str(debug_dir / f"debug_{post_id}_{ts}.png"))
                    logger.info("Debug screenshot saved to debug_html/")
                except Exception:
                    pass
                post_data.error = "Không tìm thấy bài viết. Trang có thể bị lỗi."
                return post_data

            logger.debug("Đã tìm thấy article container")

            # Parse post content
            post_data.author = self._extract_author(article)
            post_data.timestamp = self._extract_timestamp(article)

            # Extract video ID from URL first (needed for text + video extraction)
            video_id = ""
            try:
                from urllib.parse import urlparse as _urlparse, parse_qs as _parse_qs
                _parsed = _urlparse(current_url)
                _qs = _parse_qs(_parsed.query)
                if 'v' in _qs:
                    video_id = _qs['v'][0]
                elif '/watch/' in current_url or '/videos/' in current_url:
                    import re as _re
                    _vid_match = _re.search(r'/(\d{10,})(?:/|$|\?)', current_url)
                    if _vid_match:
                        video_id = _vid_match.group(1)
                if not video_id:
                    video_id = post_id
            except Exception:
                video_id = post_id

            post_data.text = self._extract_text(article, page, video_id)
            json_caption = self._extract_caption_from_story_json(page_html, post_id, video_id)
            if json_caption and (not post_data.text or len(json_caption) > len(post_data.text)):
                post_data.text = json_caption
                logger.info(f"Caption from Facebook JSON ({len(json_caption)} chars)")
            post_data.image_urls = self._extract_images(article)

            # Video detection — extracts URL from page source JS data
            video_info = self._detect_video(article, page, video_id)
            post_data.has_video = video_info["has_video"]
            post_data.video_url = video_info["video_url"]



            # Summary
            parts = []
            if post_data.text:
                parts.append(f"text ({len(post_data.text)} chars)")
            if post_data.image_urls:
                parts.append(f"{len(post_data.image_urls)} ảnh")
            if post_data.has_video:
                parts.append(f"video{'(URL OK)' if post_data.video_url else '(no URL)'}")

            if parts:
                logger.info(f"Đã parse: {', '.join(parts)}")
            else:

                post_data.error = "Không tìm thấy nội dung nào trong bài viết."
                logger.warning(post_data.error)

        except Exception as e:
            post_data.error = f"Lỗi: {str(e)[:200]}"
            logger.error(post_data.error)
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

        return post_data

    def _extract_caption_from_story_json(self, html: str, post_id: str = "", video_id: str = "") -> str:
        """Extract caption from Facebook SSR/GraphQL JSON near the post/video id."""
        if not html:
            return ""

        anchors = []
        for value in {str(post_id or "").strip(), str(video_id or "").strip()}:
            if not value:
                continue
            for pattern in (
                f'"post_id":"{value}"',
                f'"post_id": "{value}"',
                f'"video_id":"{value}"',
                f'"video_id": "{value}"',
            ):
                start = 0
                while True:
                    pos = html.find(pattern, start)
                    if pos < 0:
                        break
                    anchors.append(pos)
                    start = pos + 1

        blocks = []
        if anchors:
            for pos in anchors:
                blocks.append(html[max(0, pos - 15000): min(len(html), pos + 35000)])
        else:
            blocks.append(html)

        best = ""
        for block in blocks:
            for match in re.finditer(r'"message":\s*\{"text":\s*"((?:[^"\\]|\\.){3,})"', block):
                caption = self._decode_fb_json_text(match.group(1))
                if self._looks_like_caption(caption) and len(caption) > len(best):
                    best = caption

        return best.strip()

    @staticmethod
    def _decode_fb_json_text(raw: str) -> str:
        try:
            text = json.loads(f'"{raw}"')
        except Exception:
            try:
                text = raw.encode("utf-8").decode("unicode_escape")
            except Exception:
                text = raw
        return (
            text.replace("\\/", "/")
            .replace("\\n", "\n")
            .replace("\\u0026", "&")
            .replace("\\u003C", "<")
            .replace("\\u003E", ">")
            .strip()
        )

    @staticmethod
    def _looks_like_caption(text: str) -> bool:
        text = (text or "").strip()
        if len(text) < 3:
            return False
        lowered = text.lower()
        ui_phrases = (
            "like", "comment", "share", "see more", "write a comment",
            "thích", "bình luận", "chia sẻ", "xem thêm", "viết bình luận",
        )
        if len(text) < 60 and any(phrase == lowered or lowered.startswith(phrase) for phrase in ui_phrases):
            return False
        if re.fullmatch(r"[\d,.\s]+", text):
            return False
        return True

    def _click_see_more(self, page) -> None:
        """Click 'Xem thêm' / 'See more' buttons to expand truncated text."""
        try:
            see_more_selectors = [
                'div[role="button"]:has-text("Xem thêm")',
                'div[role="button"]:has-text("See more")',
                'span:has-text("Xem thêm")',
                'span:has-text("See more")',
            ]
            for sel in see_more_selectors:
                try:
                    btn = page.query_selector(sel)
                    if btn:
                        btn.click()
                        page.wait_for_timeout(500)
                        logger.debug("Clicked 'Xem thêm' to expand text")
                        break
                except Exception:
                    continue
        except Exception:
            pass

    def _find_main_article(self, page):
        """
        Find the main post container on a permalink page.
        Facebook uses different layouts:
        - Dialog/modal (role="dialog") for photo post permalinks
        - Article (role="article") for feed posts
        - Video watch page: video on left, post info on right
        - Main content area as fallback
        """
        # Wait for page to render
        try:
            page.wait_for_selector(
                '[role="dialog"], [role="article"], [role="main"], video',
                timeout=8000,
            )
        except Exception:
            pass

        # Strategy 1: Post dialog modal (photo post permalinks)
        dialog = page.query_selector('[role="dialog"]')
        if dialog:
            inner_text = dialog.inner_text()
            if len(inner_text) > 50:
                logger.debug("Found post in dialog modal")
                return dialog

        # Strategy 2: Video page (check BEFORE articles)
        # On video permalink pages, articles are just comments — caption is outside
        video_el = page.query_selector("video")
        if video_el:
            logger.debug("Detected video page layout — using role=main")
            main = page.query_selector('[role="main"]')
            if main:
                return main

        # Strategy 3: Article containers (feed posts, non-video)
        articles = page.query_selector_all('[role="article"]')
        if articles:
            logger.debug(f"Found {len(articles)} article(s)")
            return articles[0]

        # Strategy 4: Main content area (general fallback)
        main = page.query_selector('[role="main"]')
        if main:
            logger.debug("Using role=main as container")
            return main

        return None

    def _extract_author(self, article) -> str:
        """Extract post author from the article container."""
        try:
            selectors = [
                'h2 a strong span',
                'h2 a span',
                'h3 a strong span',
                'h3 a strong',
                'h4 a strong',
            ]
            for sel in selectors:
                el = article.query_selector(sel)
                if el:
                    text = el.inner_text().strip()
                    if text and len(text) > 1:
                        return text
        except Exception:
            pass
        return "Unknown"

    def _extract_timestamp(self, article) -> str:
        """Extract post timestamp from the article container."""
        try:
            # Timestamp links usually have aria-label with the date
            links = article.query_selector_all('a[aria-label]')
            for link in links:
                aria = link.get_attribute("aria-label") or ""
                # Timestamps typically contain numbers (dates/times)
                if aria and any(c.isdigit() for c in aria):
                    # Filter out non-time labels like "Like" buttons
                    if len(aria) > 5 and not any(kw in aria.lower() for kw in ["thích", "like", "share", "chia sẻ"]):
                        return aria

            # Fallback: look for spans with time-like text
            spans = article.query_selector_all('span[id]')
            for span in spans:
                text = span.inner_text().strip()
                if text and any(c.isdigit() for c in text) and len(text) < 50:
                    return text
        except Exception:
            pass
        return ""

    def _extract_text(self, article, page=None, video_id: str = "") -> str:
        """Extract the main post text content from the article container."""
        try:
            # Strategy 0: Watch page — video description panel
            # On /watch/?v= pages, the caption is in a specific area near the first video
            try:
                watch_text = article.evaluate("""(el) => {
                    // Check if this is a watch page by looking for watch_feed
                    let watchFeed = el.querySelector('#watch_feed') || 
                                    document.querySelector('#watch_feed');
                    if (!watchFeed) return '';
                    
                    // The first video's description area: find all div[dir="auto"]
                    // near the FIRST video section only
                    let allDivs = watchFeed.querySelectorAll('div[dir="auto"]');
                    
                    function isUI(t) {
                        if (t.length > 50) return false;
                        let l = t.trim().toLowerCase();
                        let skip = ['thích','bình luận','chia sẻ','like','comment','share',
                                    'xem thêm','see more','gửi','send','video',
                                    'hãy là người đầu tiên','be the first',
                                    'lượt xem','views','reels','watch',
                                    'người đăng','public','bạn bè','friends'];
                        for (let s of skip) {
                            if (l === s || l.startsWith(s) || l.endsWith(s)) return true;
                        }
                        // Skip "2K lượt xem" style texts
                        if (/^\d[\d,.\s]*[KMkm]?\s*(lượt xem|views)/i.test(l)) return true;
                        return false;
                    }
                    
                    for (let div of allDivs) {
                        let text = div.innerText.trim();
                        if (text.length < 10) continue;
                        if (isUI(text)) continue;
                        
                        // Skip numbers-only
                        if (/^[\d,.\s]+$/.test(text)) continue;
                        
                        // Skip profile headings
                        if (div.querySelector && div.querySelector('h2, h3, h4')) continue;
                        let p = div;
                        let isHeading = false;
                        for (let i = 0; i < 5; i++) {
                            if (!p) break;
                            if (p.tagName === 'H2' || p.tagName === 'H3') { isHeading = true; break; }
                            p = p.parentElement;
                        }
                        if (isHeading) continue;
                        
                        // Found caption
                        return text;
                    }
                    return '';
                }""")
                if watch_text and len(watch_text) > 10:
                    return watch_text
            except Exception:
                pass

            # Strategy 0.5: JSON extraction from page source (for video posts)
            # Most reliable for video permalink pages where DOM caption is tricky
            if page and video_id and video_id.isdigit():
                try:
                    json_text = page.evaluate(r"""(videoId) => {
                        let html = document.documentElement.innerHTML;
                        
                        // Find all "message":{"text":"..."} patterns with positions
                        let re = /"message":\s*\{"text":"((?:[^"\\]|\\.)*)"/g;
                        let matches = [];
                        let m;
                        while ((m = re.exec(html)) !== null) {
                            if (m[1].length > 5) {
                                matches.push({text: m[1], pos: m.index});
                            }
                        }
                        
                        if (matches.length === 0) return '';
                        
                        // Find the video_id reference closest to message texts
                        let vidStr = '"video_id":"' + videoId + '"';
                        let vidRefs = [];
                        let searchStart = 0;
                        while (true) {
                            let idx = html.indexOf(vidStr, searchStart);
                            if (idx === -1) break;
                            vidRefs.push(idx);
                            searchStart = idx + 1;
                        }
                        
                        if (vidRefs.length > 0) {
                            // Find the message closest to any video_id ref
                            let bestMatch = null;
                            let bestDist = Infinity;
                            for (let msg of matches) {
                                for (let ref of vidRefs) {
                                    let dist = Math.abs(msg.pos - ref);
                                    if (dist < bestDist && dist < 100000) {
                                        bestDist = dist;
                                        bestMatch = msg;
                                    }
                                }
                            }
                            if (bestMatch) {
                                return bestMatch.text
                                    .replace(/\\n/g, '\n')
                                    .replace(/\\u0026/g, '&')
                                    .replace(/\\u003C/g, '<')
                                    .replace(/\\u003E/g, '>')
                                    .replace(/\\"/g, '"')
                                    .replace(/\\u00e0/g, 'à')
                                    .replace(/\\u([0-9a-fA-F]{4})/g, (m, c) => String.fromCharCode(parseInt(c, 16)));
                            }
                        }
                        
                        // Fallback: return first message if only one
                        if (matches.length === 1) {
                            return matches[0].text
                                .replace(/\\n/g, '\n')
                                .replace(/\\u([0-9a-fA-F]{4})/g, (m, c) => String.fromCharCode(parseInt(c, 16)));
                        }
                        
                        return '';
                    }""", video_id)
                    if json_text and len(json_text) > 5:
                        logger.info(f"Caption from JSON ({len(json_text)} chars)")
                        return json_text
                except Exception as e:
                    logger.debug(f"JSON text extraction error: {e}")

            # Strategy 1: data-ad-comet-preview="message" (most reliable)
            msg_el = article.query_selector('div[data-ad-comet-preview="message"]')
            if msg_el:
                text = msg_el.inner_text().strip()
                if text:
                    return text

            # Strategy 2: data-ad-preview="message"
            msg_el = article.query_selector('div[data-ad-preview="message"]')
            if msg_el:
                text = msg_el.inner_text().strip()
                if text:
                    return text

            # Strategy 3: Find the post caption by locating text near author heading
            post_text = article.evaluate("""(el) => {
                let divs = el.querySelectorAll('div[dir="auto"]');
                
                function isUI(t) {
                    if (t.length > 50) return false;
                    let l = t.trim().toLowerCase();
                    let skip = ['thích','bình luận','chia sẻ','like','comment','share',
                                'xem thêm','see more','gửi','send','trả lời','reply',
                                'haha','wow','phẫn nộ','viết bình luận','write a comment',
                                'xem tất cả','all comments','xem thêm bình luận',
                                'người đăng:','public','bạn bè','friends',
                                'lượt xem','views','video','reels','watch'];
                    for (let s of skip) {
                        if (l === s || l.startsWith(s)) return true;
                    }
                    if (/^\d[\d,.\s]*[KMkm]?\s*(lượt xem|views)/i.test(l)) return true;
                    return false;
                }
                
                function isProfileName(div) {
                    let p = div;
                    for (let i = 0; i < 5; i++) {
                        if (!p) break;
                        if (p.getAttribute && p.getAttribute('data-ad-rendering-role') === 'profile_name') return true;
                        if (p.tagName === 'H2' || p.tagName === 'H3' || p.tagName === 'H4') return true;
                        p = p.parentElement;
                    }
                    if (div.querySelector && div.querySelector('h2, h3, h4')) return true;
                    let text = div.innerText.trim().toLowerCase();
                    if (text.startsWith('người đăng')) return true;
                    return false;
                }
                
                for (let div of divs) {
                    let text = div.innerText.trim();
                    if (text.length < 3) continue;
                    if (isUI(text)) continue;
                    if (isProfileName(div)) continue;
                    if (text.length < 20 && !text.includes(' ') && !text.includes('\\n')) continue;
                    if (/^\d+$/.test(text)) continue;
                    return text;
                }
                
                return '';
            }""")

            if post_text:
                return post_text

            # Strategy 4: Extract from page source JSON data (generic fallback)
            try:
                page_obj = page if page else article
                page_text = page_obj.evaluate(r"""(el) => {
                    let html = document.documentElement.innerHTML;
                    let match = html.match(/"message":\s*\{"text":"((?:[^"\\]|\\.)*)"/);
                    if (match && match[1] && match[1].length > 3) {
                        return match[1]
                            .replace(/\\n/g, '\n')
                            .replace(/\\u0026/g, '&')
                            .replace(/\\u003C/g, '<')
                            .replace(/\\u003E/g, '>')
                            .replace(/\\"/g, '"')
                            .replace(/\\u([0-9a-fA-F]{4})/g, (m, c) => String.fromCharCode(parseInt(c, 16)));
                    }
                    return '';
                }""")
                if page_text:
                    return page_text
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"Error extracting text: {e}")
        return ""

    def _extract_images(self, article) -> List[str]:
        """
        Extract full-resolution image URLs.
        Strategy: find all substantial images in the article,
        check their parent <a> links for photo page URLs,
        navigate to each photo page to get the full-res image.
        """
        image_urls = []
        seen_hrefs = set()

        try:
            # Find all photo page URLs from the article
            # Strategy: collect hrefs from all <a> tags that link to photo pages
            photo_hrefs = article.evaluate("""(el) => {
                let hrefs = [];
                let seen = new Set();
                
                // Find all links that look like photo links
                let links = el.querySelectorAll('a[href]');
                for (let a of links) {
                    let href = a.getAttribute('href') || '';
                    
                    // Check if this link goes to a photo page
                    let isPhoto = href.includes('/photo') || 
                                  href.includes('fbid=') ||
                                  href.includes('/photos/');
                    
                    if (!isPhoto) continue;
                    
                    // Check if the link contains a substantial image (not icons/avatars)
                    let imgs = a.querySelectorAll('img[src*="scontent"]');
                    let hasSubstantialImg = false;
                    for (let img of imgs) {
                        if (img.naturalWidth > 100 && img.naturalHeight > 100) {
                            hasSubstantialImg = true;
                            break;
                        }
                    }
                    
                    // Also check if the link itself is near a substantial image
                    if (!hasSubstantialImg) {
                        // Parent might be an image container
                        let parentImgs = a.parentElement ? 
                            a.parentElement.querySelectorAll('img[src*="scontent"]') : [];
                        for (let img of parentImgs) {
                            if (img.naturalWidth > 100 && img.naturalHeight > 100) {
                                hasSubstantialImg = true;
                                break;
                            }
                        }
                    }
                    
                    if (!hasSubstantialImg && !href.includes('fbid=')) continue;
                    
                    // Normalize href
                    let fullHref = href;
                    if (href.startsWith('/')) {
                        fullHref = 'https://www.facebook.com' + href;
                    }
                    
                    // Deduplicate by fbid if present, otherwise by base path
                    let fbidMatch = fullHref.match(/fbid=(\d+)/);
                    let dedupKey = fbidMatch ? fbidMatch[1] : fullHref.split('?')[0];
                    
                    if (!seen.has(dedupKey)) {
                        seen.add(dedupKey);
                        hrefs.push(fullHref);
                    }
                }
                
                return hrefs;
            }""")

            if not photo_hrefs:
                logger.debug("No photo links found, using fallback")
                return self._extract_images_fallback(article)

            logger.info(f"Tìm thấy {len(photo_hrefs)} ảnh, đang lấy full-res...")

            for i, href in enumerate(photo_hrefs):
                try:
                    full_url = self._get_fullres_from_photo_page(href, i + 1)
                    if full_url:
                        image_urls.append(full_url)
                except Exception as e:
                    logger.debug(f"Error photo {i+1}: {e}")

            if not image_urls:
                logger.debug("Photo page approach failed, using fallback")
                return self._extract_images_fallback(article)

        except Exception as e:
            logger.debug(f"Error extracting images: {e}")
            return self._extract_images_fallback(article)

        return image_urls

    def _get_fullres_from_photo_page(self, photo_url: str, index: int) -> Optional[str]:
        """
        Navigate to a photo page and extract the full-resolution image URL.
        Facebook photo pages render the image at full resolution.
        """
        if not self._context:
            return None

        page = None
        try:
            page = self._context.new_page()
            page.goto(photo_url, wait_until="domcontentloaded", timeout=15000)
            # Smart wait: wait for photo image to load instead of fixed 3s
            try:
                page.wait_for_selector(
                    'img[data-visualcompletion="media-vc-image"], img[src*="scontent"]',
                    timeout=3000,
                )
            except Exception:
                pass

            # Find the largest image on the photo page
            best_url = page.evaluate("""() => {
                let best = '';
                let bestArea = 0;
                
                // Strategy 1: img with data-visualcompletion="media-vc-image" (FB photo viewer)
                let imgs = document.querySelectorAll('img[data-visualcompletion="media-vc-image"]');
                for (let img of imgs) {
                    let area = img.naturalWidth * img.naturalHeight;
                    if (img.src && img.src.includes('scontent') && area > bestArea) {
                        bestArea = area;
                        best = img.src;
                    }
                }
                
                // Strategy 2: largest scontent image overall
                if (!best) {
                    imgs = document.querySelectorAll('img[src*="scontent"]');
                    for (let img of imgs) {
                        let area = img.naturalWidth * img.naturalHeight;
                        if (area > bestArea && img.naturalWidth > 200) {
                            bestArea = area;
                            best = img.src;
                        }
                    }
                }
                
                return JSON.stringify({url: best, w: Math.sqrt(bestArea) | 0});
            }""")

            import json
            result = json.loads(best_url)
            url = result.get("url", "")

            if url:
                logger.debug(f"Ảnh {index}: full-res OK")
                return url
            else:
                logger.debug(f"Ảnh {index}: không tìm thấy full-res trên photo page")
                return None

        except Exception as e:
            logger.debug(f"Error navigating to photo page {index}: {e}")
            return None
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass

    def _extract_images_fallback(self, article) -> List[str]:
        """Fallback: extract image URLs directly from img tags (thumbnails)."""
        image_urls = []
        seen = set()

        try:
            imgs = article.query_selector_all("img")
            for img in imgs:
                src = img.get_attribute("src") or ""
                if not src or "scontent" not in src or "fbcdn" not in src:
                    continue

                try:
                    natural_w = img.evaluate("el => el.naturalWidth")
                    natural_h = img.evaluate("el => el.naturalHeight")
                except Exception:
                    natural_w = 0
                    natural_h = 0

                if natural_w > 0 and natural_w < 150:
                    continue
                if natural_h > 0 and natural_h < 150:
                    continue

                skip_patterns = [
                    "emoji", "p50x50", "p100x100", "p60x60",
                    "p75x75", "s40x40", "s50x50", "s32x32",
                ]
                if any(pat in src.lower() for pat in skip_patterns):
                    continue

                base_url = src.split("?")[0]
                if base_url not in seen:
                    seen.add(base_url)
                    image_urls.append(src)
        except Exception:
            pass

        return image_urls

    def _detect_video(self, article, page, video_id: str = "") -> dict:
        """
        Detect if the post contains a video and extract its download URL.
        Uses video_id to find the correct video on pages with multiple videos.
        """
        result = {"has_video": False, "video_url": ""}
        try:
            # Check for video element within the post article
            video = article.query_selector("video")
            if video:
                result["has_video"] = True

            # Check for video-related divs
            video_div = article.query_selector('div[data-video-id]')
            if video_div:
                result["has_video"] = True

            # If not found in article, check page level for watch/video pages
            # Only when we have a numeric video_id (confirming it's a video URL)
            if not result["has_video"] and video_id and video_id.isdigit():
                page_video = page.query_selector("video")
                if page_video:
                    # Double-check: verify video_id exists in page source
                    try:
                        has_vid_ref = page.evaluate(
                            """(vid) => document.documentElement.innerHTML.includes('"video_id":"' + vid + '"')""",
                            video_id
                        )
                        if has_vid_ref:
                            result["has_video"] = True
                            logger.info(f"Video detected at page level (video_id={video_id})")
                    except Exception:
                        result["has_video"] = True  # fallback: trust the video element

            # Facebook often lazy-loads the player, so the post can be a video even
            # when no <video> element has been rendered yet. Look for video delivery
            # data close to this post/video id before giving up.
            if not result["has_video"]:
                try:
                    result["has_video"] = bool(page.evaluate(r"""(videoId) => {
                        const html = document.documentElement.innerHTML;
                        const signals = [
                            'videoDeliveryLegacyFields', 'videoDeliveryResponseFragment',
                            'dash_manifest', 'playable_url', 'browser_native_hd_url',
                            'video_redirect', 'video_id'
                        ];
                        if (!videoId) return signals.some(signal => html.includes(signal));
                        const anchors = [
                            `"video_id":"${videoId}"`, `"video_id": "${videoId}"`,
                            `"post_id":"${videoId}"`, `"post_id": "${videoId}"`,
                            `/${videoId}`
                        ];
                        for (const anchor of anchors) {
                            let pos = html.indexOf(anchor);
                            while (pos >= 0) {
                                const nearby = html.slice(Math.max(0, pos - 120000), pos + 120000);
                                if (signals.some(signal => nearby.includes(signal))) return true;
                                pos = html.indexOf(anchor, pos + anchor.length);
                            }
                        }
                        return false;
                    }""", video_id))
                    if result["has_video"]:
                        logger.info(f"Video detected from page data (video_id={video_id or 'unknown'})")
                except Exception as exc:
                    logger.debug(f"Video page-data detection error: {exc}")

            # Only extract a scoped mp4 URL after confirming video indicators.
            if not result["has_video"]:
                return result

            # Extract video URL from page source
            # Use video_id to scope the search to the correct video
            try:
                video_url = page.evaluate(r"""(videoId) => {
                    let html = document.documentElement.innerHTML;
                    
                    // Find all quoted strings containing scontent...mp4
                    // URLs in innerHTML appear as: "https:\/\/scontent...mp4?..."
                    let allUrls = [];
                    
                    // Match quoted URLs: path up to 1500 chars + query up to 2000 chars
                    let re = /\"(https?:[^\"]{10,1500}\.mp4\?[^\"]{10,2000})\"/g;
                    let match;
                    
                    while ((match = re.exec(html)) !== null) {
                        let raw = match[1];
                        // Must contain scontent or fbcdn
                        if (!raw.includes('scontent') && !raw.includes('fbcdn')) continue;
                        
                        // Clean URL: unescape JSON/HTML entities
                        let url = raw
                            .replace(/\\\//g, '/')
                            .replace(/\\u0025/g, '%')
                            .replace(/&amp;/g, '&')
                            .replace(/\\u0026/g, '&');
                        
                        if (url.length > 2000) continue;
                        if (!url.startsWith('http')) continue;
                        
                        let bitrateMatch = url.match(/bitrate=(\d+)/);
                        let bitrate = bitrateMatch ? parseInt(bitrateMatch[1]) : 0;
                        allUrls.push({url: url, bitrate: bitrate, pos: match.index});
                    }
                    
                    if (allUrls.length === 0) return '';
                    
                    // If we have a video ID, find URLs near that video's reference
                    if (videoId && videoId.length > 5) {
                        // Find ALL occurrences of video_id in the HTML
                        let searchStr = '"video_id":"' + videoId + '"';
                        let vidRefs = [];
                        let searchStart = 0;
                        while (true) {
                            let idx = html.indexOf(searchStr, searchStart);
                            if (idx === -1) break;
                            vidRefs.push(idx);
                            searchStart = idx + 1;
                        }
                        
                        // Also check injected_video_id
                        searchStr = '"injected_video_id":"' + videoId + '"';
                        searchStart = 0;
                        while (true) {
                            let idx = html.indexOf(searchStr, searchStart);
                            if (idx === -1) break;
                            vidRefs.push(idx);
                            searchStart = idx + 1;
                        }
                        
                        if (vidRefs.length > 0) {
                            // Collect ALL unique URLs near ANY video_id ref
                            let seenUrls = new Set();
                            let candidateUrls = [];
                            for (let ref of vidRefs) {
                                let nearby = allUrls.filter(u => 
                                    Math.abs(u.pos - ref) < 50000
                                );
                                for (let u of nearby) {
                                    if (!seenUrls.has(u.url)) {
                                        seenUrls.add(u.url);
                                        candidateUrls.push(u);
                                    }
                                }
                            }
                            
                            if (candidateUrls.length > 0) {
                                // Prefer URLs with explicit bitrate (progressive downloads)
                                // over DASH segments (bitrate=0)
                                let withBitrate = candidateUrls.filter(u => u.bitrate > 0);
                                if (withBitrate.length > 0) {
                                    // Pick highest bitrate for best quality
                                    withBitrate.sort((a, b) => b.bitrate - a.bitrate);
                                    return withBitrate[0].url;
                                }
                                // Fall back to first candidate URL
                                return candidateUrls[0].url;
                            }
                        }
                    }
                    
                    // Fallback: pick URL with highest bitrate globally
                    let withBitrate = allUrls.filter(u => u.bitrate > 0);
                    if (withBitrate.length > 0) {
                        withBitrate.sort((a, b) => b.bitrate - a.bitrate);
                        return withBitrate[0].url;
                    }
                    
                    // Last resort: first URL
                    return allUrls[0].url;
                }""", video_id)
                
                if video_url:
                    result["has_video"] = True
                    result["video_url"] = video_url
                    logger.info(f"Video URL extracted ({len(video_url)} chars)")
                    return result
            except Exception as e:
                logger.info(f"Error extracting video URL: {e}")

        except Exception:
            pass
        return result

    @staticmethod
    def _is_ui_text(text: str) -> bool:
        """Check if text is UI/navigation text rather than post content."""
        ui_patterns = [
            "Thích", "Bình luận", "Chia sẻ", "Gửi",
            "Like", "Comment", "Share", "Send",
            "Viết bình luận", "Write a comment",
            "Xem thêm", "See more",
            "Tất cả bình luận", "All comments",
            "phản hồi", "reply",
            "Haha", "Wow", "Buồn", "Phẫn nộ",
            "Trả lời", "Reply",
        ]
        text_lower = text.strip().lower()
        if len(text) < 30:
            for pattern in ui_patterns:
                if text_lower == pattern.lower():
                    return True
        return False

    def stop(self) -> None:
        """Shut down browser and Chrome process."""
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

    def is_running(self) -> bool:
        """Check if browser is still running."""
        return self._chrome_process is not None and self._chrome_process.poll() is None
