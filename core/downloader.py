"""
Tinix Facebook Down — Download Orchestrator
Manages the entire download pipeline with threading, pause/stop support.
"""

import re
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
from utils import logger


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

        # State
        self.stats = DownloadStats()
        self._cookies: Dict[str, str] = {}
        self._output_dir: Path = Path(".")
        self._max_threads: int = 1
        self._browser: Optional[BrowserManager] = None

    # --- Public API ---

    def set_callbacks(
        self,
        on_progress: Optional[Callable] = None,
        on_post_complete: Optional[Callable] = None,
        on_all_complete: Optional[Callable] = None,
        on_stats_update: Optional[Callable] = None,
    ) -> None:
        """Set callback functions for GUI updates."""
        self._on_progress = on_progress
        self._on_post_complete = on_post_complete
        self._on_all_complete = on_all_complete
        self._on_stats_update = on_stats_update

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

    def _process_single_post(self, url: str, index: int) -> None:
        """
        Process a single Facebook post URL.
        Fetch → Parse → Download text + media.
        """
        logger.info(f"--- Post {index}/{self.stats.total_posts} ---")
        logger.info(f"URL: {url[:80]}...")

        # Validate
        is_valid, msg = validate_url(url)
        if not is_valid:
            logger.error(f"URL không hợp lệ: {msg}")
            self._update_stats(failed=True)
            return

        # Check stop
        if self._stop_event.is_set():
            return

        try:
            # Extract post ID for folder naming
            post_id = extract_post_id(url)

            # Fetch and parse using browser
            if not self._browser:
                logger.error("Trình duyệt không hoạt động")
                self._update_stats(failed=True)
                return

            post_data = self._browser.fetch_post(url, post_id)

            if not post_data.is_valid:
                logger.error(f"Không thể parse post: {post_data.error}")
                self._update_stats(failed=True)
                return

            # Check stop
            if self._stop_event.is_set():
                return

            # Create output directory for this post
            folder_name = self._make_folder_name(post_data)
            post_dir = self._output_dir / folder_name
            post_dir.mkdir(parents=True, exist_ok=True)

            # Update media count
            with self._lock:
                self.stats.total_media += post_data.media_count

            # Skip caption text file — only download media

            # Download images (skip if post is a video - those are just thumbnails)
            if not post_data.has_video:
                for j, img_url in enumerate(post_data.image_urls):
                    if self._stop_event.is_set():
                        return
                    self._pause_event.wait()

                    img_path = post_dir / f"image_{j+1:03d}.jpg"
                    success = download_image(img_url, img_path, self._cookies)
                    if success:
                        with self._lock:
                            self.stats.downloaded_media += 1
                            if img_path.exists():
                                self.stats.total_bytes += img_path.stat().st_size
                    self._notify_stats()

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
                if post_data.video_url and self._browser:
                    logger.info("Tải video qua browser session...")
                    video_success = self._browser.download_file(
                        post_data.video_url, video_path
                    )

                # Method 2: Direct HTTP download with headers
                if not video_success and post_data.video_url:
                    logger.info("Thử tải video trực tiếp...")
                    video_success = download_video_direct(
                        post_data.video_url, video_path, self._cookies
                    )

                # Method 3: Fallback to yt-dlp
                if not video_success:
                    logger.info("Thử tải video bằng yt-dlp...")
                    original_url = get_original_url(url)
                    video_success = download_video(
                        original_url, post_dir, self._cookies
                    )

                if video_success:
                    with self._lock:
                        self.stats.downloaded_media += 1
                        for vf in post_dir.glob("video_*"):
                            self.stats.total_bytes += vf.stat().st_size
                    self._notify_stats()
                    self._update_stats(failed=False)
                    logger.info(f"✅ Post {index} hoàn thành → {post_dir.name}")
                else:
                    logger.error(f"❌ Post {index} thất bại — không tải được video")
                    self._update_stats(failed=True)
            else:
                self._update_stats(failed=False)
                logger.info(f"✅ Post {index} hoàn thành → {post_dir.name}")

        except Exception as e:
            logger.error(f"Lỗi xử lý post {index}: {str(e)[:200]}")
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

    def reset(self) -> None:
        """Reset the orchestrator to initial state."""
        if self._browser:
            self._browser.stop()
            self._browser = None
        self._running = False
        self._pause_event.set()
        self._stop_event.clear()
        self.stats = DownloadStats()
        self._cookies = {}
        logger.info("🔄 Đã reset")
