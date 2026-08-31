"""
Tinix Facebook Down — Download Orchestrator
Manages the entire download pipeline with threading, pause/stop support.
"""

import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.url_handler import (
    get_original_url,
    extract_post_id,
    parse_urls,
    validate_url,
)
from core.cookie_handler import parse_cookie_string, validate_cookies
from core.facebook_parser import BrowserManager, PostData
from core.media_downloader import save_text_content, download_image, download_video, download_video_direct
from core.db_storage import get_db_path, mark_posts_downloaded
from utils.chrome_profiles import download_profile_dir
from utils import config
from utils import logger


MEDIA_FILE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".webm", ".avi", ".mkv"}


@dataclass
class DownloadStats:
    """Statistics for the current download session."""
    total_posts: int = 0
    completed_posts: int = 0
    success_posts: int = 0
    failed_posts: int = 0
    total_media: int = 0
    downloaded_media: int = 0
    total_bytes: int = 0
    start_time: float = 0.0

    @property
    def progress_fraction(self) -> float:
        if self.total_posts == 0:
            return 0.0
        return self.completed_posts / self.total_posts

    @property
    def elapsed_seconds(self) -> float:
        if self.start_time == 0:
            return 0
        return time.time() - self.start_time

    @property
    def eta_seconds(self) -> float:
        """Estimated time remaining in seconds."""
        if self.completed_posts == 0 or self.total_posts == 0:
            return 0
        elapsed = self.elapsed_seconds
        avg_per_post = elapsed / self.completed_posts
        remaining = self.total_posts - self.completed_posts
        return avg_per_post * remaining


class DownloadOrchestrator:
    """
    Manages the complete download pipeline.

    Features:
    - Multi-threaded downloading via ThreadPoolExecutor
    - Pause/Resume support
    - Stop support
    - Progress callbacks for GUI updates
    - Comprehensive error handling
    """

    def __init__(self):
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._executor: Optional[ThreadPoolExecutor] = None

        # Callbacks
        self._on_progress: Optional[Callable] = None
        self._on_post_complete: Optional[Callable] = None
        self._on_all_complete: Optional[Callable] = None
        self._on_stats_update: Optional[Callable] = None
        self._on_existing_post: Optional[Callable] = None
        self._on_post_failed: Optional[Callable] = None

        # State
        self.stats = DownloadStats()
        self._cookies: Dict[str, str] = {}
        self._output_dir: Path = Path(".")
        self._max_threads: int = 1
        self._browser: Optional[BrowserManager] = None
        self._browsers: List[BrowserManager] = []

    # --- Public API ---

    def set_callbacks(
        self,
        on_progress: Optional[Callable] = None,
        on_post_complete: Optional[Callable] = None,
        on_all_complete: Optional[Callable] = None,
        on_stats_update: Optional[Callable] = None,
        on_existing_post: Optional[Callable] = None,
        on_post_failed: Optional[Callable] = None,
    ) -> None:
        """Set callback functions for GUI updates."""
        self._on_progress = on_progress
        self._on_post_complete = on_post_complete
        self._on_all_complete = on_all_complete
        self._on_stats_update = on_stats_update
        self._on_existing_post = on_existing_post
        self._on_post_failed = on_post_failed

    def start(
        self,
        urls_text: str,
        cookie_string: str,
        output_dir: str,
        max_threads: int = 1,
    ) -> None:
        """
        Start the download process in a background thread.

        Args:
            urls_text: Multi-line text with Facebook URLs.
            cookie_string: Cookie string for authentication.
            output_dir: Base output directory.
            max_threads: Maximum concurrent downloads.
        """
        if self._running:
            logger.warning("Download đang chạy rồi!")
            return

        # Parse & validate input
        urls = parse_urls(urls_text)
        if not urls:
            logger.error("Không tìm thấy URL Facebook nào hợp lệ!")
            if self._on_all_complete:
                self._on_all_complete(False, "Không tìm thấy URL hợp lệ")
            return

        # Validate cookies
        cookies = parse_cookie_string(cookie_string)
        is_valid, msg = validate_cookies(cookies)
        if not is_valid:
            logger.error(f"Cookies không hợp lệ: {msg}")
            if self._on_all_complete:
                self._on_all_complete(False, f"Cookies lỗi: {msg}")
            return

        logger.info(f"Cookies hợp lệ: {msg}")
        logger.info(f"Tìm thấy {len(urls)} URL hợp lệ")
        logger.info(f"Thư mục lưu: {output_dir}")
        logger.info(f"Số luồng tải: {max_threads}")

        # Initialize state
        self._cookies = cookies
        self._output_dir = Path(output_dir)
        self._max_threads = max_threads
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self.stats = DownloadStats(
            total_posts=len(urls),
            start_time=time.time(),
        )

        # Reset events
        self._pause_event.set()
        self._stop_event.clear()
        self._running = True

        # Start in background
        thread = threading.Thread(
            target=self._run_pipeline,
            args=(urls,),
            daemon=True,
        )
        thread.start()

    def start_with_accounts(
        self,
        urls_text: str,
        accounts: List[dict],
        output_dir: str,
        max_threads: int = 1,
    ) -> None:
        """Start downloading with one Chrome profile per selected Facebook account."""
        if self._running:
            logger.warning("Download đang chạy rồi!")
            return

        urls = parse_urls(urls_text)
        if not urls:
            logger.error("Không tìm thấy URL Facebook nào hợp lệ!")
            if self._on_all_complete:
                self._on_all_complete(False, "Không tìm thấy URL hợp lệ")
            return

        live_accounts = [a for a in accounts if a.get("is_active")]
        if not live_accounts:
            logger.error("Chưa có account Facebook Live để tải đa luồng.")
            if self._on_all_complete:
                self._on_all_complete(False, "Chưa có account Facebook Live")
            return

        worker_count = max(1, min(int(max_threads or 1), len(live_accounts), len(urls)))
        selected_accounts = live_accounts[:worker_count]
        logger.info(f"Tìm thấy {len(urls)} URL hợp lệ")
        logger.info(f"Thư mục lưu: {output_dir}")
        logger.info(f"Số luồng tải: {worker_count} | Account Live: {len(live_accounts)}")

        self._output_dir = Path(output_dir)
        self._max_threads = worker_count
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self.stats = DownloadStats(total_posts=len(urls), start_time=time.time())
        self._pause_event.set()
        self._stop_event.clear()
        self._running = True

        thread = threading.Thread(
            target=self._run_multi_account_pipeline,
            args=(urls, selected_accounts),
            daemon=True,
        )
        thread.start()

    def pause(self) -> None:
        """Pause the download (waits between posts)."""
        if not self._running:
            return
        self._pause_event.clear()
        logger.info("⏸ Đã tạm dừng")

    def resume(self) -> None:
        """Resume a paused download."""
        if not self._running:
            return
        self._pause_event.set()
        logger.info("▶ Đã tiếp tục")

    def stop(self) -> None:
        """Stop the download completely."""
        if not self._running:
            return
        self._stop_event.set()
        self._pause_event.set()  # Unblock if paused
        for browser in list(getattr(self, "_browsers", []) or []):
            try:
                browser.stop()
            except Exception:
                pass
        logger.info("⏹ Đang dừng...")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._running and not self._pause_event.is_set()

    # --- Internal Pipeline ---

    def _run_pipeline(self, urls: List[str]) -> None:
        """Main download pipeline (runs in background thread)."""
        try:
            logger.info("=" * 50)
            logger.info("🚀 Bắt đầu tải...")
            logger.info("=" * 50)

            # Start browser
            self._browser = BrowserManager()
            if not self._browser.start(self._cookies):
                logger.error("Không thể khởi động trình duyệt!")
                if self._on_all_complete:
                    self._on_all_complete(False, "Lỗi trình duyệt")
                return

            if self._max_threads > 1:
                self._run_parallel(urls)
            else:
                self._run_sequential(urls)

            # Final summary
            if self._stop_event.is_set():
                logger.info("⏹ Download đã bị dừng bởi người dùng")
            else:
                logger.info("=" * 50)
                logger.info("✅ HOÀN THÀNH!")
                logger.info(
                    f"   Thành công: {self.stats.success_posts}/{self.stats.total_posts} posts"
                )
                if self.stats.failed_posts > 0:
                    logger.warning(f"   Thất bại: {self.stats.failed_posts} posts")
                elapsed = self.stats.elapsed_seconds
                logger.info(f"   Thời gian: {int(elapsed//60)} phút {int(elapsed%60)} giây")
                logger.info("=" * 50)

            if self._on_all_complete:
                has_success = self.stats.success_posts > 0
                self._on_all_complete(has_success, "Hoàn thành")

        except Exception as e:
            logger.error(f"Pipeline error: {str(e)[:300]}")
            if self._on_all_complete:
                self._on_all_complete(False, str(e))
        finally:
            # Always stop the browser
            if self._browser:
                self._browser.stop()
                self._browser = None
            self._running = False

    def _run_multi_account_pipeline(self, urls: List[str], accounts: List[dict]) -> None:
        """Download with multiple browser profiles, one per live account."""
        browsers: List[BrowserManager] = []
        self._browsers = browsers
        try:
            logger.info("=" * 50)
            logger.info("🚀 Bắt đầu tải đa luồng bằng nhiều account...")
            logger.info("=" * 50)

            chunks = [[] for _ in accounts]
            for idx, url in enumerate(urls):
                chunks[idx % len(accounts)].append((idx + 1, url))

            def worker(account: dict, items: List[tuple]) -> None:
                if not items:
                    return
                account_id = int(account.get("id") or 0)
                label = account.get("label") or account.get("username") or f"Account {account_id}"
                profile_dir = account.get("profile_dir") or account.get("download_profile_dir") or ""
                if not profile_dir:
                    profile_dir = str(download_profile_dir(account_id))
                port = 9700 + (account_id % 200)
                cookies = parse_cookie_string(account.get("cookie", ""))
                browser = BrowserManager(profile_dir=profile_dir, cdp_port=port, headless=True)
                browsers.append(browser)
                logger.info(f"Mở Chrome tải media: {label} | profile={profile_dir} | {len(items)} link")
                if not browser.start(cookies):
                    logger.error(f"Không mở được Chrome cho {label}")
                    for _index, _url in items:
                        self._update_stats(failed=True)
                    return
                try:
                    for index, url in items:
                        if self._stop_event.is_set():
                            break
                        self._pause_event.wait()
                        if self._stop_event.is_set():
                            break
                        self._process_single_post(url, index, browser=browser, cookies=cookies, account_label=label)
                finally:
                    browser.stop()

            threads = [
                threading.Thread(target=worker, args=(account, items), daemon=True)
                for account, items in zip(accounts, chunks)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            if self._stop_event.is_set():
                logger.info("⏹ Download đã bị dừng bởi người dùng")
            else:
                logger.info("=" * 50)
                logger.info("✅ HOÀN THÀNH!")
                logger.info(f"   Thành công: {self.stats.success_posts}/{self.stats.total_posts} posts")
                if self.stats.failed_posts > 0:
                    logger.warning(f"   Thất bại: {self.stats.failed_posts} posts")
                logger.info("=" * 50)

            if self._on_all_complete:
                self._on_all_complete(self.stats.success_posts > 0, "Hoàn thành")
        except Exception as e:
            logger.error(f"Multi-account pipeline error: {str(e)[:300]}")
            if self._on_all_complete:
                self._on_all_complete(False, str(e))
        finally:
            for browser in browsers:
                try:
                    browser.stop()
                except Exception:
                    pass
            self._browsers = []
            self._running = False

    def _run_sequential(self, urls: List[str]) -> None:
        """Process URLs one by one."""
        for i, url in enumerate(urls):
            if self._stop_event.is_set():
                break

            # Check pause
            self._pause_event.wait()

            if self._stop_event.is_set():
                break

            self._process_single_post(url, i + 1)

    def _run_parallel(self, urls: List[str]) -> None:
        """Process URLs with thread pool."""
        with ThreadPoolExecutor(max_workers=self._max_threads) as executor:
            self._executor = executor
            futures: List[Future] = []

            for i, url in enumerate(urls):
                if self._stop_event.is_set():
                    break
                future = executor.submit(self._process_single_post, url, i + 1)
                futures.append(future)

            # Wait for all futures
            for future in futures:
                if self._stop_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    future.result(timeout=600)
                except Exception as e:
                    logger.error(f"Thread error: {str(e)[:100]}")

            self._executor = None

    def _process_single_post(
        self,
        url: str,
        index: int,
        browser: Optional[BrowserManager] = None,
        cookies: Optional[Dict[str, str]] = None,
        account_label: str = "",
    ) -> None:
        """
        Process a single Facebook post URL.
        Fetch → Parse → Download text + media.
        """
        prefix = f"[{account_label}] " if account_label else ""
        logger.info(f"--- {prefix}Post {index}/{self.stats.total_posts} ---")
        logger.info(f"URL: {url[:80]}...")
        active_browser = browser or self._browser
        active_cookies = cookies if cookies is not None else self._cookies

        # Validate
        is_valid, msg = validate_url(url)
        if not is_valid:
            error_msg = f"URL không hợp lệ: {msg}"
            logger.error(error_msg)
            self._notify_post_failed(url, index, error_msg)
            self._update_stats(failed=True)
            return

        # Check stop
        if self._stop_event.is_set():
            return

        try:
            # Extract post ID for folder naming
            post_id = extract_post_id(url)

            # Fetch and parse using browser
            if not active_browser:
                error_msg = "Trình duyệt không hoạt động"
                logger.error(error_msg)
                self._notify_post_failed(url, index, error_msg)
                self._update_stats(failed=True)
                return

            post_data = active_browser.fetch_post(url, post_id)

            if not post_data.is_valid:
                error_msg = f"Không thể parse post: {post_data.error or 'Không tìm thấy nội dung/media'}"
                logger.error(error_msg)
                self._notify_post_failed(url, index, error_msg)
                self._update_stats(failed=True)
                return

            # Check stop
            if self._stop_event.is_set():
                return

            # Create output directory for this post
            folder_name = self._make_folder_name(post_data)
            post_dir = self._output_dir / folder_name
            existing_action = self._handle_existing_post(post_dir, folder_name, url)
            if existing_action in {"cancel", "open_folder"}:
                logger.info(f"Post {index} đã được tải trước đó → {post_dir.name}")
                self._mark_post_downloaded(post_data, post_dir, url)
                self._update_stats(failed=False)
                return
            post_dir.mkdir(parents=True, exist_ok=True)

            # Update media count
            with self._lock:
                self.stats.total_media += post_data.media_count

            if post_data.text and post_data.text.strip():
                save_text_content(post_data.text.strip(), post_dir / "caption.txt")

            if post_data.media_count <= 0:
                error_msg = "Không tìm thấy ảnh/video để tải trong bài viết"
                logger.error(f"❌ Post {index} thất bại — {error_msg}")
                self._notify_post_failed(url, index, error_msg)
                self._update_stats(failed=True)
                return

            # Download images (skip if post is a video - those are just thumbnails)
            if not post_data.has_video:
                image_success_count = 0
                image_failed_count = 0
                for j, img_url in enumerate(post_data.image_urls):
                    if self._stop_event.is_set():
                        return
                    self._pause_event.wait()

                    img_path = post_dir / f"image_{j+1:03d}.jpg"
                    success = download_image(img_url, img_path, active_cookies)
                    if success:
                        image_success_count += 1
                        with self._lock:
                            self.stats.downloaded_media += 1
                            if img_path.exists():
                                self.stats.total_bytes += img_path.stat().st_size
                    else:
                        image_failed_count += 1
                    self._notify_stats()

                if post_data.image_urls and image_success_count == 0:
                    error_msg = f"Tải ảnh thất bại ({image_failed_count}/{len(post_data.image_urls)} ảnh)"
                    logger.error(f"❌ Post {index} thất bại — {error_msg}")
                    self._notify_post_failed(url, index, error_msg)
                    self._update_stats(failed=True)
                    return
                if image_failed_count:
                    logger.warning(
                        f"Post {index}: tải được {image_success_count}/{len(post_data.image_urls)} ảnh, "
                        f"{image_failed_count} ảnh lỗi"
                    )

            # Download video
            if post_data.has_video:
                if self._stop_event.is_set():
                    return
                self._pause_event.wait()

                video_success = False
                video_path = post_dir / "video_001.mp4"

                if post_data.video_url:
                    logger.info(f"Video URL found ({len(post_data.video_url)} chars)")
                else:
                    logger.warning("Không tìm thấy video URL từ page source")

                # Method 1: Browser download (uses authenticated session)
                if post_data.video_url and active_browser:
                    logger.info("Tải video qua browser session...")
                    video_success = active_browser.download_file(
                        post_data.video_url, video_path
                    )

                # Method 2: Direct HTTP download with headers
                if not video_success and post_data.video_url:
                    logger.info("Thử tải video trực tiếp...")
                    video_success = download_video_direct(
                        post_data.video_url, video_path, active_cookies
                    )

                # Method 3: Fallback to yt-dlp
                if not video_success:
                    logger.info("Thử tải video bằng yt-dlp...")
                    original_url = get_original_url(url)
                    video_success = download_video(
                        original_url, post_dir, active_cookies
                    )

                if video_success:
                    with self._lock:
                        self.stats.downloaded_media += 1
                        for vf in post_dir.glob("video_*"):
                            self.stats.total_bytes += vf.stat().st_size
                    self._notify_stats()
                    self._mark_post_downloaded(post_data, post_dir, url)
                    self._update_stats(failed=False)
                    logger.info(f"✅ Post {index} hoàn thành → {post_dir.name}")
                else:
                    error_msg = "Không tải được video sau khi thử browser session, direct HTTP và yt-dlp"
                    logger.error(f"❌ Post {index} thất bại — {error_msg}")
                    self._notify_post_failed(url, index, error_msg)
                    self._update_stats(failed=True)
            else:
                self._mark_post_downloaded(post_data, post_dir, url)
                self._update_stats(failed=False)
                logger.info(f"✅ Post {index} hoàn thành → {post_dir.name}")

        except Exception as e:
            error_msg = f"Lỗi xử lý post: {str(e)[:200]}"
            logger.error(f"Lỗi xử lý post {index}: {str(e)[:200]}")
            self._notify_post_failed(url, index, error_msg)
            self._update_stats(failed=True)

    def _make_folder_name(self, post_data: PostData) -> str:
        """
        Create folder name using the post's numeric ID.
        Example: 836851975657298
        """
        if post_data.post_id:
            # Extract only digits from post_id
            numeric_id = re.sub(r'\D', '', post_data.post_id)
            if numeric_id:
                return numeric_id
            return post_data.post_id[:30]
        return "post_unknown"

    def _mark_post_downloaded(self, post_data: PostData, post_dir: Path, url: str) -> None:
        """Mark the matching scraped post row as downloaded for Post Spy filters."""
        candidates = {
            str(post_dir.name or "").strip(),
            str(getattr(post_data, "post_id", "") or "").strip(),
            str(extract_post_id(url) or "").strip(),
        }
        candidates |= {re.sub(r"\D", "", c) for c in list(candidates) if c}
        post_ids = [c for c in candidates if c and c != "unknown"]
        if not post_ids:
            return
        try:
            db_path = get_db_path(config.get("scraper_db_path", ""))
            updated = mark_posts_downloaded(db_path, post_ids, str(post_dir))
            if updated:
                logger.info(f"Đã đánh dấu {updated} bài là Đã tải trong Post Spy.")
        except Exception as e:
            logger.error(f"Không cập nhật trạng thái đã tải: {str(e)[:200]}")

    def _handle_existing_post(self, post_dir: Path, folder_name: str, url: str) -> str:
        """Ask the GUI what to do when a post folder already contains media."""
        if not self._post_dir_has_media(post_dir):
            return "download"

        logger.warning(f"Bài viết đã được tải trước đó: {post_dir}")
        action = "cancel"
        if self._on_existing_post:
            try:
                action = self._on_existing_post(str(post_dir), folder_name, url) or "cancel"
            except Exception as e:
                logger.error(f"Existing-post prompt failed: {str(e)[:200]}")
                action = "cancel"

        action = str(action or "cancel").lower()
        if action == "redownload":
            self._clear_existing_post_dir(post_dir)
            return "download"
        if action == "open_folder":
            return "open_folder"
        return "cancel"

    @staticmethod
    def _post_dir_has_media(post_dir: Path) -> bool:
        if not post_dir.exists() or not post_dir.is_dir():
            return False
        try:
            return any(
                p.is_file() and p.suffix.lower() in MEDIA_FILE_EXTS
                for p in post_dir.iterdir()
            )
        except Exception:
            return False

    def _clear_existing_post_dir(self, post_dir: Path) -> None:
        """Remove an existing downloaded-post folder before redownloading."""
        try:
            resolved_output = self._output_dir.resolve()
            resolved_post = post_dir.resolve()
            if resolved_post == resolved_output or resolved_output not in resolved_post.parents:
                logger.error(f"Refuse to clear unsafe path: {resolved_post}")
                return
            shutil.rmtree(resolved_post)
            logger.info(f"Đã xóa bản tải cũ để tải lại: {resolved_post.name}")
        except Exception as e:
            logger.error(f"Không xóa được bản tải cũ: {str(e)[:200]}")

    @staticmethod
    def _parse_date(timestamp: str) -> str:
        """
        Parse Facebook timestamp to dd-mm-yyyy format.
        Handles various formats like:
        - '12 tháng 8, 2024'
        - 'August 12, 2024'
        - '12/08/2024'
        """
        if not timestamp:
            return ""

        import re as _re
        from datetime import datetime

        # Vietnamese month mapping
        vn_months = {
            "tháng 1": 1, "tháng 2": 2, "tháng 3": 3, "tháng 4": 4,
            "tháng 5": 5, "tháng 6": 6, "tháng 7": 7, "tháng 8": 8,
            "tháng 9": 9, "tháng 10": 10, "tháng 11": 11, "tháng 12": 12,
        }

        # Try Vietnamese format: "12 tháng 8, 2024" or "Ngày 12 tháng 8, 2024"
        vn_match = _re.search(r'(\d{1,2})\s+tháng\s+(\d{1,2}),?\s+(\d{4})', timestamp)
        if vn_match:
            day = int(vn_match.group(1))
            month = int(vn_match.group(2))
            year = int(vn_match.group(3))
            return f"{day:02d}-{month:02d}-{year}"

        # Try English format: "August 12, 2024"
        en_months = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
        }
        for month_name, month_num in en_months.items():
            en_match = _re.search(
                rf'{month_name}\s+(\d{{1,2}}),?\s+(\d{{4}})',
                timestamp, _re.IGNORECASE,
            )
            if en_match:
                day = int(en_match.group(1))
                year = int(en_match.group(2))
                return f"{day:02d}-{month_num:02d}-{year}"

        # Try dd/mm/yyyy or mm/dd/yyyy
        date_match = _re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', timestamp)
        if date_match:
            a, b, year = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
            # Assume dd/mm/yyyy (Vietnamese locale)
            return f"{a:02d}-{b:02d}-{year}"

        # Try to extract any year
        year_match = _re.search(r'(\d{4})', timestamp)
        if year_match:
            return year_match.group(1)

        return ""

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Remove or replace characters not safe for filenames."""
        # Replace problematic characters
        name = re.sub(r'[<>:"/\\|?*]', '_', name)
        name = re.sub(r'\s+', '_', name)
        name = name.strip('._')
        return name or "unknown"

    @staticmethod
    def _format_text_file(post_data: PostData) -> str:
        """Format the text content file — raw content only."""
        return post_data.text

    def _update_stats(self, failed: bool = False) -> None:
        """Update download statistics."""
        with self._lock:
            self.stats.completed_posts += 1
            if failed:
                self.stats.failed_posts += 1
            else:
                self.stats.success_posts += 1
        self._notify_stats()

    def _notify_stats(self) -> None:
        """Send stats update to GUI."""
        if self._on_stats_update:
            self._on_stats_update(self.stats)

    def _notify_post_failed(self, url: str, index: int, error: str) -> None:
        """Send per-link failure details to GUI."""
        if not self._on_post_failed:
            return
        try:
            self._on_post_failed({
                "url": url,
                "index": index,
                "error": error,
            })
        except Exception as exc:
            logger.error(f"Post-failed callback error: {str(exc)[:200]}")

    def reset(self) -> None:
        """Reset the orchestrator to initial state."""
        if self._browser:
            self._browser.stop()
            self._browser = None
        for browser in list(getattr(self, "_browsers", []) or []):
            try:
                browser.stop()
            except Exception:
                pass
        self._browsers = []
        self._running = False
        self._pause_event.set()
        self._stop_event.clear()
        self.stats = DownloadStats()
        self._cookies = {}
        logger.info("🔄 Đã reset")
