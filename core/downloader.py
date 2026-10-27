"""
Tinix Facebook Down — Download Orchestrator
Manages the entire download pipeline with threading, pause/stop support.
"""

import re
import queue
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from core.url_handler import (
    get_original_url,
    extract_post_id,
    is_story_permalink_for_id,
    is_video_url_for_story_id,
    normalize_video_post_url,
    parse_urls,
    validate_url,
)
from core.cookie_handler import parse_cookie_string, validate_cookies
from core.facebook_parser import BrowserManager, PostData
from core.account_preflight import (
    account_label,
    check_facebook_account,
    resolve_download_profile,
)
from core.media_downloader import (
    save_text_content,
    download_image,
    download_video,
    download_video_direct,
    get_last_download_error,
    _get_extension_from_url,
)
from core.db_storage import (
    get_db_path,
    get_post_by_id,
    get_post_by_row_id,
    post_file_key,
    mark_post_row_downloaded,
    mark_post_row_download_status,
    mark_posts_download_status,
    register_downloaded_post_for_page,
    resolve_download_target,
)
from utils.chrome_profiles import chrome_profile_dir
from utils import config
from utils import logger


MEDIA_FILE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".webm", ".avi", ".mkv"}


def _canonical_post_url(page_url: str, post_id: str) -> str:
    """Build a valid post permalink from a saved Page or profile URL."""
    clean_page_url = str(page_url or "").strip()
    clean_post_id = str(post_id or "").strip()
    parsed = urlparse(clean_page_url)
    if parsed.path.rstrip("/") == "/profile.php":
        profile_id = parse_qs(parsed.query).get("id", [""])[0]
        if profile_id:
            return (
                "https://www.facebook.com/permalink.php?"
                f"story_fbid={clean_post_id}&id={profile_id}"
            )
    return f"{clean_page_url.rstrip('/')}/posts/{clean_post_id}"


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
    finished_time: float = 0.0

    @property
    def progress_fraction(self) -> float:
        if self.total_posts == 0:
            return 0.0
        return self.completed_posts / self.total_posts

    @property
    def elapsed_seconds(self) -> float:
        if self.start_time == 0:
            return 0
        return max(0.0, (self.finished_time or time.time()) - self.start_time)

    @property
    def eta_seconds(self) -> float:
        """Estimated time remaining in seconds."""
        if self.completed_posts == 0 or self.total_posts == 0:
            return 0
        elapsed = self.elapsed_seconds
        avg_per_post = elapsed / self.completed_posts
        remaining = self.total_posts - self.completed_posts
        return avg_per_post * remaining


@dataclass
class DownloadTask:
    """One queue item. Attempts are finalised only after retry is exhausted."""
    index: int
    url: str
    attempts: int = 0
    tried_account_ids: List[int] = field(default_factory=list)
    last_error: str = ""
    last_error_code: str = ""
    thumbnail_only: bool = False
    source_post_row_id: int = 0


@dataclass
class DownloadSafetySettings:
    """Pacing values read once at the beginning of a download run."""
    delay_min: float = 2.0
    delay_max: float = 5.0
    batch_size: int = 25
    batch_rest_min: float = 30.0
    batch_rest_max: float = 90.0


@dataclass
class AccountPacingState:
    """Worker-local account health and pacing state."""
    processed_posts: int = 0
    consecutive_errors: int = 0
    rate_limit_count: int = 0
    next_ready_at: float = 0.0
    cooldown_until: float = 0.0
    wait_code: str = ""
    wait_message: str = ""


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
        self._on_account_status: Optional[Callable] = None
        self._on_download_item: Optional[Callable] = None
        self._on_idle: Optional[Callable] = None

        # State
        self.stats = DownloadStats()
        self._cookies: Dict[str, str] = {}
        self._output_dir: Path = Path(".")
        self._max_threads: int = 1
        self._browser: Optional[BrowserManager] = None
        self._browsers: List[BrowserManager] = []
        self.account_statuses: Dict[int, Dict[str, Any]] = {}
        self._retrying_posts: int = 0
        self._attempt_local = threading.local()
        self._cookie_mode = False
        self._safety = DownloadSafetySettings()
        self._rate_limit_events: List[tuple[float, int]] = []
        self._safety_pause_reason = ""
        self._worker_account_ids: set[int] = set()

    # --- Public API ---

    def set_callbacks(
        self,
        on_progress: Optional[Callable] = None,
        on_post_complete: Optional[Callable] = None,
        on_all_complete: Optional[Callable] = None,
        on_stats_update: Optional[Callable] = None,
        on_existing_post: Optional[Callable] = None,
        on_post_failed: Optional[Callable] = None,
        on_account_status: Optional[Callable] = None,
        on_download_item: Optional[Callable] = None,
        on_idle: Optional[Callable] = None,
    ) -> None:
        """Set callback functions for GUI updates."""
        self._on_progress = on_progress
        self._on_post_complete = on_post_complete
        self._on_all_complete = on_all_complete
        self._on_stats_update = on_stats_update
        self._on_existing_post = on_existing_post
        self._on_post_failed = on_post_failed
        self._on_account_status = on_account_status
        self._on_download_item = on_download_item
        self._on_idle = on_idle

    def _notify_idle(self) -> None:
        """Notify only after every browser and worker for the run has stopped."""
        if not self._on_idle:
            return
        try:
            self._on_idle()
        except Exception as exc:
            logger.warning(f"Lỗi callback on_idle: {str(exc)[:200]}")

    def start(
        self,
        urls_text: str,
        cookie_string: str,
        output_dir: str,
        max_threads: int = 1,
        source_post_row_ids: Optional[List[int]] = None,
    ) -> bool:
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
            return False

        # Parse & validate input
        urls = parse_urls(urls_text)
        if not urls:
            logger.error("Không tìm thấy URL Facebook nào hợp lệ!")
            if self._on_all_complete:
                self._on_all_complete(False, "Không tìm thấy URL hợp lệ")
            self._notify_idle()
            return False
        row_ids = [int(value or 0) for value in (source_post_row_ids or [])]
        if row_ids and len(row_ids) != len(urls):
            logger.error("Số ID bài nguồn không khớp với số URL")
            return False
        if not row_ids:
            row_ids = [0] * len(urls)

        # Clear counters before a validation callback can complete this run.
        # Without this reset a bad cookie could inherit the previous run's totals.
        self.stats = DownloadStats(total_posts=len(urls), start_time=time.time())

        # Validate cookies
        cookies = parse_cookie_string(cookie_string)
        is_valid, msg = validate_cookies(cookies)
        if not is_valid:
            logger.error(f"Cookies không hợp lệ: {msg}")
            if self._on_all_complete:
                self._on_all_complete(False, f"Cookies lỗi: {msg}")
            self._notify_idle()
            return False

        logger.info(f"Cookies hợp lệ: {msg}")
        logger.info(f"Tìm thấy {len(urls)} URL hợp lệ")
        logger.info(f"Thư mục lưu: {output_dir}")
        logger.info(f"Số luồng tải: {max_threads}")

        # Initialize state
        self._cookies = cookies
        self._output_dir = Path(output_dir)
        self._configure_safety_settings()
        self._cookie_mode = True
        requested_threads = max(1, int(max_threads or 1))
        # Multiple isolated browser profiles sharing one Facebook cookie make
        # simultaneous requests from one account, which is checkpoint-prone.
        self._max_threads = 1
        if requested_threads > 1:
            logger.warning(
                f"Cookie dùng chung: yêu cầu {requested_threads} luồng, giới hạn còn 1 luồng để bảo vệ account."
            )
        self._retrying_posts = 0
        self.account_statuses = {}
        self._worker_account_ids = set()
        self._rate_limit_events = []
        self._safety_pause_reason = ""
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Reset events
        self._pause_event.set()
        self._stop_event.clear()
        self._running = True
        self._mark_urls_download_status(urls, "downloading", source_post_row_ids=row_ids)

        # Start in background
        thread = threading.Thread(
            target=self._run_pipeline,
            args=(urls, row_ids),
            daemon=True,
        )
        thread.start()
        return True

    def start_with_accounts(
        self,
        urls_text: str,
        accounts: List[dict],
        output_dir: str,
        max_threads: int = 1,
        source_post_row_ids: Optional[List[int]] = None,
    ) -> bool:
        """Preflight every active account, then use at most ``max_threads`` healthy workers."""
        if self._running:
            logger.warning("Download đang chạy rồi!")
            return False

        urls = parse_urls(urls_text)
        if not urls:
            logger.error("Không tìm thấy URL Facebook nào hợp lệ!")
            if self._on_all_complete:
                self._on_all_complete(False, "Không tìm thấy URL hợp lệ")
            self._notify_idle()
            return False
        row_ids = [int(value or 0) for value in (source_post_row_ids or [])]
        if row_ids and len(row_ids) != len(urls):
            logger.error("Số ID bài nguồn không khớp với số URL")
            return False
        if not row_ids:
            row_ids = [0] * len(urls)

        # Same early reset as cookie mode: preflight failures must not report
        # stale totals from an earlier download.
        self.stats = DownloadStats(total_posts=len(urls), start_time=time.time())

        live_accounts = [a for a in accounts if a.get("is_active")]
        if not live_accounts:
            logger.error("Chưa có account Facebook Live để tải đa luồng.")
            if self._on_all_complete:
                self._on_all_complete(False, "Chưa có account Facebook Live")
            self._notify_idle()
            return False

        self._configure_safety_settings()
        self._cookie_mode = False
        worker_count = max(1, min(int(max_threads or 1), len(live_accounts), len(urls)))
        logger.info(f"Tìm thấy {len(urls)} URL hợp lệ")
        logger.info(f"Thư mục lưu: {output_dir}")
        logger.info(f"Số luồng tải: {worker_count} | Account Live: {len(live_accounts)}")

        self._output_dir = Path(output_dir)
        self._max_threads = worker_count
        self._retrying_posts = 0
        self.account_statuses = {}
        self._worker_account_ids = set()
        self._rate_limit_events = []
        self._safety_pause_reason = ""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._pause_event.set()
        self._stop_event.clear()
        self._running = True
        self._mark_urls_download_status(urls, "downloading", source_post_row_ids=row_ids)

        thread = threading.Thread(
            target=self._run_multi_account_pipeline,
            args=(urls, live_accounts, row_ids),
            daemon=True,
        )
        thread.start()
        return True

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
        if self._safety_pause_reason:
            logger.info("Người dùng tiếp tục tác vụ sau safety pause.")
            self._safety_pause_reason = ""
        self._pause_event.set()
        logger.info("▶ Đã tiếp tục")

    def stop(self) -> None:
        """Request that workers stop after their current browser operation."""
        if not self._running:
            return
        self._stop_event.set()
        self._pause_event.set()  # Unblock if paused
        # Every Sync Playwright instance is owned by its worker thread.  Calling
        # BrowserManager.stop() here would close it from the web-request thread
        # and trigger greenlet/thread-affinity failures.  Each worker observes
        # _stop_event and closes its own browser in its finally block.
        logger.info("⏹ Đang dừng sau thao tác trình duyệt hiện tại...")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._running and not self._pause_event.is_set()

    @property
    def safety_pause_reason(self) -> str:
        return self._safety_pause_reason

    def _configure_safety_settings(self) -> None:
        """Read validated download pacing values once for this run."""
        def number(key: str, fallback: float, minimum: float, maximum: float) -> float:
            try:
                return min(maximum, max(minimum, float(config.get(key, fallback))))
            except (TypeError, ValueError):
                return fallback

        delay_min = number("download_delay_min", 2.0, 0.1, 60.0)
        delay_max = number("download_delay_max", 5.0, delay_min, 60.0)
        batch_rest_min = number("download_batch_rest_min", 30.0, 0.0, 900.0)
        batch_rest_max = number("download_batch_rest_max", 90.0, batch_rest_min, 900.0)
        try:
            batch_size = min(500, max(1, int(config.get("download_batch_size", 25))))
        except (TypeError, ValueError):
            batch_size = 25
        self._safety = DownloadSafetySettings(
            delay_min=delay_min,
            delay_max=delay_max,
            batch_size=batch_size,
            batch_rest_min=batch_rest_min,
            batch_rest_max=batch_rest_max,
        )

    def _wait_for_account_slot(
        self,
        pacing: AccountPacingState,
        account_id: int,
        label: str,
    ) -> bool:
        """Wait for a per-account rest or cooldown without blocking Stop."""
        while not self._stop_event.is_set():
            self._pause_event.wait(timeout=0.25)
            if not self._pause_event.is_set():
                continue
            remaining = pacing.next_ready_at - time.monotonic()
            if remaining <= 0:
                if pacing.wait_code:
                    pacing.wait_code = ""
                    pacing.wait_message = ""
                    if account_id:
                        self._emit_account_status(
                            account_id, label, "working", "READY", "Đang nhận bài từ hàng đợi chung.",
                            pacing=pacing,
                        )
                return True

            state = "cooldown" if pacing.cooldown_until > time.monotonic() else "resting"
            if state == "cooldown":
                message = f"Facebook đang giới hạn; còn khoảng {max(1, round(remaining))} giây cooldown."
            else:
                message = f"Nghỉ an toàn giữa các bài; còn khoảng {max(1, round(remaining))} giây."
            if account_id:
                self._emit_account_status(account_id, label, state, pacing.wait_code or "PACING", message, pacing=pacing)
            time.sleep(min(0.5, remaining))
        return False

    def _schedule_account_pacing(
        self,
        pacing: AccountPacingState,
        account_id: int,
        label: str,
        *,
        failed: bool,
    ) -> None:
        """Schedule a short human-scale pause before this account's next post."""
        pacing.processed_posts += 1
        pacing.consecutive_errors = pacing.consecutive_errors + 1 if failed else 0
        if self._stop_event.is_set():
            return

        if pacing.processed_posts % self._safety.batch_size == 0:
            seconds = random.uniform(self._safety.batch_rest_min, self._safety.batch_rest_max)
            pacing.wait_code = "BATCH_REST"
            pacing.wait_message = f"Nghỉ {seconds:.0f} giây sau {pacing.processed_posts} bài."
        else:
            seconds = random.uniform(self._safety.delay_min, self._safety.delay_max)
            pacing.wait_code = "PACING"
            pacing.wait_message = f"Nghỉ {seconds:.1f} giây trước bài tiếp theo."

        pacing.next_ready_at = max(pacing.next_ready_at, time.monotonic() + seconds)
        logger.info(f"[Account #{account_id} · {label}] {pacing.wait_message}")
        if account_id:
            self._emit_account_status(account_id, label, "resting", pacing.wait_code, pacing.wait_message, pacing=pacing)

    def _apply_rate_limit(
        self,
        pacing: AccountPacingState,
        account_id: int,
        label: str,
        message: str,
    ) -> None:
        """Back off one account progressively after a server-side limit."""
        pacing.rate_limit_count += 1
        steps = (60.0, 180.0, 600.0)
        base_seconds = steps[min(pacing.rate_limit_count - 1, len(steps) - 1)]
        seconds = base_seconds + random.uniform(0.0, min(15.0, base_seconds * 0.1))
        pacing.cooldown_until = time.monotonic() + seconds
        pacing.next_ready_at = max(pacing.next_ready_at, pacing.cooldown_until)
        pacing.wait_code = "RATE_LIMITED"
        pacing.wait_message = f"{message} Cooldown {seconds:.0f} giây."
        logger.warning(f"[Account #{account_id} · {label}] {pacing.wait_message}")
        self._emit_account_status(account_id, label, "cooldown", "RATE_LIMITED", pacing.wait_message, pacing=pacing)

        now = time.monotonic()
        with self._lock:
            self._rate_limit_events = [event for event in self._rate_limit_events if now - event[0] <= 300]
            self._rate_limit_events.append((now, account_id))
            must_pause = len({event[1] for event in self._rate_limit_events}) >= 2
        if must_pause:
            self._pause_for_safety("Hai account bị Facebook giới hạn trong 5 phút; tác vụ đã tự động tạm dừng.")

    def _pause_for_safety(self, reason: str) -> None:
        """Pause remaining workers rather than spreading a suspected restriction."""
        if not self._running:
            return
        with self._lock:
            already_paused = bool(self._safety_pause_reason)
            self._safety_pause_reason = reason
        self._pause_event.clear()
        if not already_paused:
            logger.warning(f"🛡️ SAFETY PAUSE: {reason}")

    # --- Internal Pipeline ---

    def _run_pipeline(self, urls: List[str], row_ids: Optional[List[int]] = None) -> None:
        """Main download pipeline (runs in background thread)."""
        try:
            logger.info("=" * 50)
            logger.info("🚀 Bắt đầu tải...")
            logger.info("=" * 50)

            if self._max_threads > 1:
                self._run_parallel(urls, row_ids or [0] * len(urls))
            else:
                # Sync Playwright must be started and used in this same pipeline thread.
                self._browser = BrowserManager()
                if not self._browser.start(self._cookies):
                    logger.error("Không thể khởi động trình duyệt!")
                    self._notify_download_complete()
                    return
                self._run_sequential(urls, row_ids or [0] * len(urls))

            # Final summary
            if self._stop_event.is_set():
                logger.info("⏹ Download đã bị dừng bởi người dùng")
            else:
                logger.info("=" * 50)
                if self.stats.success_posts == self.stats.total_posts:
                    logger.info("✅ HOÀN THÀNH!")
                elif self.stats.success_posts > 0:
                    logger.warning("⚠️ HOÀN THÀNH MỘT PHẦN!")
                else:
                    logger.error("❌ TẢI THẤT BẠI!")
                logger.info(
                    f"   Thành công: {self.stats.success_posts}/{self.stats.total_posts} posts"
                )
                if self.stats.failed_posts > 0:
                    logger.warning(f"   Thất bại: {self.stats.failed_posts} posts")
                elapsed = self.stats.elapsed_seconds
                logger.info(f"   Thời gian: {int(elapsed//60)} phút {int(elapsed%60)} giây")
                logger.info("=" * 50)

            self._notify_download_complete()

        except Exception as e:
            logger.error(f"Pipeline error: {str(e)[:300]}")
            self._notify_download_complete()
        finally:
            self._mark_urls_download_status(
                urls,
                "failed",
                "Tác vụ tải kết thúc trước khi xử lý bài này",
                only_if_status="downloading",
                source_post_row_ids=row_ids,
            )
            # Always stop the browser
            if self._browser:
                self._browser.stop()
                self._browser = None
            self._running = False
            self._notify_idle()

    def _run_multi_account_pipeline(self, urls: List[str], accounts: List[dict], row_ids: Optional[List[int]] = None) -> None:
        """Preflight accounts, then let healthy workers consume one shared queue."""
        browsers: List[BrowserManager] = []
        self._browsers = browsers
        task_queue: queue.Queue[Optional[DownloadTask]] = queue.Queue()
        active_account_ids: set[int] = set()
        active_accounts_lock = threading.Lock()
        startup_results: queue.Queue[bool] = queue.Queue()
        startup_gate = threading.Event()
        accept_tasks = threading.Event()
        threads: List[threading.Thread] = []
        try:
            logger.info("=" * 50)
            logger.info("🚀 Preflight account trước khi bắt đầu tải...")
            logger.info("=" * 50)

            ready_accounts: List[dict] = []
            self.account_statuses = {}
            # A task should not wait for every active profile before it can
            # start. Check enough healthy workers plus one warm fallback; when
            # early profiles fail, continue down the list until that target is
            # reached or there are no accounts left.
            ready_target = min(len(accounts), self._max_threads + 1)
            for account in accounts:
                account_id = int(account.get("id") or 0)
                label = account_label(account)
                self._emit_account_status(account_id, label, "checking", "PREFLIGHT", "Đang kiểm tra Chrome và phiên Facebook.")
                logger.info(f"[Account #{account_id} · {label}] PREFLIGHT: đang kiểm tra phiên Facebook...")
                result = check_facebook_account(account)
                if result.ready:
                    ready_accounts.append(account)
                    self._emit_account_status(account_id, label, "ready", result.code, result.message)
                    logger.info(f"[Account #{account_id} · {label}] PREFLIGHT READY: {result.message}")
                else:
                    self._emit_account_status(account_id, label, "unavailable", result.code, result.message)
                    logger.warning(f"[Account #{account_id} · {label}] PREFLIGHT FAILED [{result.code}]: {result.message}")
                if len(ready_accounts) >= ready_target:
                    break

            if not ready_accounts:
                error = "Không có account nào qua preflight; hãy đăng nhập/cập nhật cookie rồi thử lại."
                for index, url in enumerate(urls, start=1):
                    row_id = (row_ids or [0] * len(urls))[index - 1]
                    task = DownloadTask(index=index, url=url, source_post_row_id=row_id, last_error=error, last_error_code="NO_READY_ACCOUNT")
                    self._finalize_task_failure(task)
                self._log_download_summary()
                self._notify_download_complete()
                return

            selected_accounts = ready_accounts[:self._max_threads]
            self._worker_account_ids = {
                int(account.get("id") or 0) for account in selected_accounts if int(account.get("id") or 0)
            }
            if len(ready_accounts) > len(selected_accounts):
                logger.info(f"Có {len(ready_accounts) - len(selected_accounts)} account dự phòng đã qua preflight.")

            def has_other_active_account(task: DownloadTask, current_account_id: int) -> bool:
                with active_accounts_lock:
                    return any(
                        account_id != current_account_id and account_id not in task.tried_account_ids
                        for account_id in active_account_ids
                    )

            def worker(account: dict) -> None:
                account_id = int(account.get("id") or 0)
                label = account_label(account)
                profile_dir = resolve_download_profile(account)
                port = 9700 + (account_id % 200)
                cookies = parse_cookie_string(str(account.get("cookie") or ""))
                browser: Optional[BrowserManager] = None
                started = False
                startup_reported = False
                pacing = AccountPacingState()
                try:
                    # Playwright Sync API instances may only be created, used and
                    # stopped in one thread.  Do all three within this worker.
                    browser = BrowserManager(profile_dir=profile_dir, cdp_port=port, headless=True)
                    logger.info(f"[Account #{account_id} · {label}] mở Chrome worker | profile={profile_dir}")
                    started = browser.start(cookies, require_authenticated=True)
                    if not started:
                        code = browser.last_start_error_code or "BROWSER_START_FAILED"
                        message = browser.last_start_error_message or "Không thể mở Chrome worker."
                        self._emit_account_status(account_id, label, "unavailable", code, message)
                        logger.error(f"[Account #{account_id} · {label}] WORKER FAILED [{code}]: {message}")
                    else:
                        with self._lock:
                            browsers.append(browser)
                        with active_accounts_lock:
                            active_account_ids.add(account_id)
                        self._emit_account_status(
                            account_id, label, "working", "READY", "Đang nhận bài từ hàng đợi chung.",
                            pacing=pacing,
                        )

                    startup_results.put(started)
                    startup_reported = True
                    # Do not consume a post until all selected workers have
                    # reported their own Playwright startup outcome.  Otherwise
                    # an early worker could exhaust the queue before a healthy
                    # fallback account finishes starting.
                    startup_gate.wait()
                    if not accept_tasks.is_set() or not started or not browser:
                        return

                    max_attempts = min(2, len(selected_accounts))

                    while True:
                        if not self._stop_event.is_set():
                            self._pause_event.wait()
                            if not self._stop_event.is_set() and not self._wait_for_account_slot(pacing, account_id, label):
                                continue
                        task = task_queue.get()
                        try:
                            if task is None:
                                return
                            if self._stop_event.is_set():
                                continue

                            # Prefer a different account for a retry when one exists.
                            if account_id in task.tried_account_ids and has_other_active_account(task, account_id):
                                task_queue.put(task)
                                time.sleep(0.05)
                                continue

                            success, error = self._run_post_attempt(
                                task.url, task.index, browser, cookies, label, account_id, task.attempts + 1,
                                task.source_post_row_id,
                            )
                            if success:
                                self._schedule_account_pacing(pacing, account_id, label, failed=False)
                                self._update_stats(failed=False)
                                self._emit_download_item(task, account_id, label, "success", "DOWNLOADED", "Đã tải thành công.")
                                continue

                            task.attempts += 1
                            task.tried_account_ids.append(account_id)
                            task.last_error = error or "Tải bài viết không thành công."
                            task.last_error_code = self._classify_download_error(task.last_error)
                            task.thumbnail_only = "thumbnail" in task.last_error.lower() or "thiếu video" in task.last_error.lower()

                            account_failure = task.last_error_code in {"ACCOUNT_AUTH_EXPIRED", "ACCOUNT_CHECKPOINT", "BROWSER_UNAVAILABLE"}
                            if account_failure:
                                if task.last_error_code == "ACCOUNT_CHECKPOINT":
                                    self._pause_for_safety(
                                        f"Facebook yêu cầu xác nhận Account #{account_id}; hãy kiểm tra account trước khi tiếp tục."
                                    )
                                with active_accounts_lock:
                                    active_account_ids.discard(account_id)
                                    has_fallback = bool(active_account_ids)
                                self._emit_account_status(
                                    account_id, label, "unavailable", task.last_error_code, task.last_error,
                                    pacing=pacing,
                                )
                                logger.warning(f"[Account #{account_id} · {label}] bị loại giữa tác vụ [{task.last_error_code}]: {task.last_error}")
                                if has_fallback:
                                    self._retry_task(task, account_id, label)
                                    task_queue.put(task)
                                else:
                                    self._finalize_task_failure(task)
                                    self._finalize_queued_tasks(task_queue, "Không còn account nào sẵn sàng để tiếp tục tải.", "NO_READY_ACCOUNT")
                                return

                            if task.last_error_code == "RATE_LIMITED":
                                self._apply_rate_limit(pacing, account_id, label, task.last_error)
                                if task.attempts < max_attempts:
                                    self._retry_task(task, account_id, label, message="sẽ thử lại sau cooldown an toàn")
                                    task_queue.put(task)
                                else:
                                    self._finalize_task_failure(task)
                                continue

                            self._schedule_account_pacing(pacing, account_id, label, failed=True)
                            retryable = task.last_error_code not in {"POST_INVALID_URL", "POST_UNAVAILABLE"}
                            if retryable and task.attempts < max_attempts and has_other_active_account(task, account_id):
                                self._retry_task(task, account_id, label)
                                task_queue.put(task)
                            else:
                                self._finalize_task_failure(task)
                        finally:
                            task_queue.task_done()
                except Exception as exc:
                    message = f"Lỗi khởi động Chrome worker: {str(exc)[:200]}"
                    self._emit_account_status(account_id, label, "unavailable", "BROWSER_START_FAILED", message)
                    logger.error(f"[Account #{account_id} · {label}] WORKER FAILED [BROWSER_START_FAILED]: {message}")
                finally:
                    if not startup_reported:
                        startup_results.put(False)
                    with active_accounts_lock:
                        active_account_ids.discard(account_id)
                    if browser:
                        with self._lock:
                            if browser in browsers:
                                browsers.remove(browser)
                        try:
                            browser.stop()
                        except Exception as exc:
                            logger.warning(f"Không thể đóng Chrome worker #{account_id}: {str(exc)[:120]}")

            threads = [threading.Thread(target=worker, args=(account,), daemon=True) for account in selected_accounts]
            for thread in threads:
                thread.start()

            ready_worker_count = 0
            for _ in selected_accounts:
                try:
                    ready_worker_count += int(startup_results.get(timeout=60))
                except queue.Empty:
                    logger.error("Chrome worker không phản hồi kết quả khởi động trong 60 giây.")

            if not ready_worker_count:
                error = "Các account qua preflight không thể khởi động worker tải."
                for index, url in enumerate(urls, start=1):
                    row_id = (row_ids or [0] * len(urls))[index - 1]
                    task = DownloadTask(index=index, url=url, source_post_row_id=row_id, last_error=error, last_error_code="NO_RUNNING_WORKER")
                    self._finalize_task_failure(task)
                startup_gate.set()
                for thread in threads:
                    thread.join()
                self._log_download_summary()
                self._notify_download_complete()
                return

            logger.info(
                f"✅ Worker Chrome sẵn sàng: {ready_worker_count}/{len(selected_accounts)}. "
                f"Đưa {len(urls)} bài vào hàng đợi chung."
            )
            for index, url in enumerate(urls, start=1):
                row_id = (row_ids or [0] * len(urls))[index - 1]
                task_queue.put(DownloadTask(index=index, url=url, source_post_row_id=row_id))
            accept_tasks.set()
            startup_gate.set()
            task_queue.join()
            for _ in range(ready_worker_count):
                task_queue.put(None)
            for thread in threads:
                thread.join()

            if self._stop_event.is_set():
                logger.info("⏹ Download đã bị dừng bởi người dùng")
            else:
                self._log_download_summary()
            self._notify_download_complete()
        except Exception as e:
            logger.error(f"Multi-account pipeline error: {str(e)[:300]}")
            if self._on_all_complete:
                self._on_all_complete(False, str(e))
        finally:
            startup_gate.set()
            self._mark_urls_download_status(
                urls,
                "failed",
                "Tác vụ tải kết thúc trước khi xử lý bài này",
                only_if_status="downloading",
                source_post_row_ids=row_ids,
            )
            self._browsers = []
            self._running = False
            self._notify_idle()

    def _run_post_attempt(
        self, url: str, index: int, browser: BrowserManager, cookies: Dict[str, str],
        label: str, account_id: int, attempt: int, source_post_row_id: int = 0,
    ) -> tuple[bool, str]:
        """Run a post without prematurely counting a retry as a final failure."""
        self._attempt_local.context = {"defer_stats": True, "failed": None, "error": "", "account_id": account_id, "attempt": attempt, "source_post_row_id": source_post_row_id}
        try:
            kwargs = {"browser": browser, "cookies": cookies, "account_label": f"#{account_id} · {label}"}
            if source_post_row_id:
                kwargs["source_post_row_id"] = source_post_row_id
            self._process_single_post(url, index, **kwargs)
            context = self._attempt_local.context
            return context.get("failed") is False, str(context.get("error") or "")
        finally:
            self._attempt_local.context = None

    @staticmethod
    def _error_with_code(message: str, code: str = "") -> str:
        """Keep a machine-readable failure code in the existing error string."""
        cleaned_message = str(message or "Tải bài viết không thành công.").strip()
        cleaned_code = str(code or "").strip().upper()
        if not cleaned_code or cleaned_message.startswith(f"[{cleaned_code}]"):
            return cleaned_message
        return f"[{cleaned_code}] {cleaned_message}"

    def _latest_media_error(self, fallback: str, browser: Optional[BrowserManager] = None) -> str:
        """Expose the worker-local HTTP/yt-dlp result to the retry policy."""
        code, message = get_last_download_error()
        if not code and browser is not None:
            code = getattr(browser, "last_request_error_code", "")
            message = getattr(browser, "last_request_error_message", "")
        return self._error_with_code(message or fallback, code)

    @staticmethod
    def _classify_download_error(error: str) -> str:
        raw_text = str(error or "")
        text = raw_text.lower()
        known_codes = (
            "ACCOUNT_CHECKPOINT", "ACCOUNT_AUTH_EXPIRED", "BROWSER_UNAVAILABLE",
            "RATE_LIMITED", "POST_INVALID_URL", "POST_UNAVAILABLE", "POST_PARSE_FAILED",
            "MEDIA_ACCESS_DENIED", "MEDIA_URL_EXPIRED", "MEDIA_HTTP_ERROR",
            "NETWORK_TIMEOUT", "DOWNLOADER_UNAVAILABLE", "DOWNLOAD_FAILED",
        )
        upper_text = raw_text.upper()
        for code in known_codes:
            if f"[{code}]" in upper_text:
                return code
        if "cookie" in text and ("hết hạn" in text or "login" in text):
            return "ACCOUNT_AUTH_EXPIRED"
        if "checkpoint" in text or "xác nhận lại" in text or "xác nhận danh tính" in text:
            return "ACCOUNT_CHECKPOINT"
        if any(marker in text for marker in (
            "try again later", "temporarily blocked", "too many requests", "rate limit",
            "vui lòng thử lại sau", "đang thực hiện quá nhanh", "tạm thời bị chặn", "http 429",
        )):
            return "RATE_LIMITED"
        if "trình duyệt không hoạt động" in text or "không mở được chrome" in text:
            return "BROWSER_UNAVAILABLE"
        if "url không hợp lệ" in text:
            return "POST_INVALID_URL"
        if "không còn khả dụng" in text or "đã thay đổi quyền xem" in text or "content isn't available" in text:
            return "POST_UNAVAILABLE"
        if "không thể parse" in text:
            return "POST_PARSE_FAILED"
        if "thumbnail" in text or "thiếu video" in text or "video stream" in text:
            return "MEDIA_ACCESS_DENIED"
        if "thời gian chờ" in text or "timeout" in text:
            return "NETWORK_TIMEOUT"
        return "DOWNLOAD_FAILED"

    def _retry_task(self, task: DownloadTask, account_id: int, label: str, message: str = "") -> None:
        self._retrying_posts += 1
        message = message or f"Lần {task.attempts + 1}: chuyển sang account khác sau lỗi {task.last_error_code}."
        logger.warning(f"[Post {task.index} · Account #{account_id} · Attempt {task.attempts}] RETRY: {message}")
        self._emit_download_item(task, account_id, label, "retrying", task.last_error_code, message)
        self._mark_post_download_status(task.url, "downloading", "", task.source_post_row_id)

    def _finalize_task_failure(self, task: DownloadTask) -> None:
        status = "thumbnail_only" if task.thumbnail_only else "failed"
        self._mark_post_download_status(task.url, status, task.last_error, task.source_post_row_id)
        self._update_stats(failed=True)
        self._emit_download_item(task, task.tried_account_ids[-1] if task.tried_account_ids else 0, "", "failed", task.last_error_code, task.last_error)

    def _finalize_queued_tasks(self, task_queue: queue.Queue, error: str, code: str) -> None:
        while True:
            try:
                task = task_queue.get_nowait()
            except queue.Empty:
                return
            if task is not None:
                task.last_error = error
                task.last_error_code = code
                self._finalize_task_failure(task)
            task_queue.task_done()

    def _emit_account_status(
        self,
        account_id: int,
        label: str,
        state: str,
        code: str,
        message: str,
        *,
        pacing: Optional[AccountPacingState] = None,
    ) -> None:
        payload = {"account_id": account_id, "label": label, "state": state, "code": code, "message": message}
        if pacing is not None:
            payload.update({
                "processed_posts": pacing.processed_posts,
                "consecutive_errors": pacing.consecutive_errors,
                "rate_limit_count": pacing.rate_limit_count,
                "cooldown_seconds": max(0, round(pacing.cooldown_until - time.monotonic())),
            })
        with self._lock:
            self.account_statuses[account_id] = payload
        if self._on_account_status:
            self._on_account_status(payload)

    def _emit_download_item(self, task: DownloadTask, account_id: int, label: str, state: str, code: str, message: str) -> None:
        if self._on_download_item:
            self._on_download_item({
                "index": task.index, "url": task.url, "account_id": account_id, "account_label": label,
                "attempt": task.attempts, "state": state, "code": code, "message": message,
            })

    def _log_download_summary(self) -> None:
        logger.info("=" * 50)
        if self.stats.success_posts == self.stats.total_posts:
            logger.info("✅ HOÀN THÀNH!")
        elif self.stats.success_posts > 0:
            logger.warning("⚠️ HOÀN THÀNH MỘT PHẦN!")
        else:
            logger.error("❌ TẢI THẤT BẠI!")
        logger.info(f"   Thành công: {self.stats.success_posts}/{self.stats.total_posts} posts")
        if self.stats.failed_posts > 0:
            logger.warning(f"   Thất bại: {self.stats.failed_posts} posts")
        logger.info("=" * 50)

    def _notify_download_complete(self) -> None:
        self._finish_run_state()
        if not self._on_all_complete:
            return
        all_success = self.stats.total_posts > 0 and self.stats.success_posts == self.stats.total_posts
        summary = f"{self.stats.success_posts}/{self.stats.total_posts} bài thành công; {self.stats.failed_posts} bài thất bại"
        try:
            self._on_all_complete(all_success, summary)
        except Exception as cb_err:
            logger.warning(f"Lỗi callback on_all_complete: {cb_err}")

    def _finish_run_state(self) -> None:
        """Freeze elapsed time and publish a terminal state for active workers."""
        with self._lock:
            if not self.stats.finished_time:
                self.stats.finished_time = time.time()
            worker_ids = set(self._worker_account_ids)
            current = {
                account_id: dict(payload)
                for account_id, payload in self.account_statuses.items()
                if account_id in worker_ids
            }

        if self._stop_event.is_set():
            state, code, message = "stopped", "STOPPED", "Đã dừng theo yêu cầu người dùng."
        elif self.stats.failed_posts and not self.stats.success_posts:
            state, code, message = "failed", "RUN_FAILED", "Tác vụ kết thúc nhưng không có bài tải thành công."
        elif self.stats.failed_posts:
            state, code, message = "completed", "PARTIAL", "Đã kết thúc; một số bài không tải được."
        else:
            state, code, message = "completed", "COMPLETED", "Đã hoàn thành tác vụ tải."

        for account_id, payload in current.items():
            if payload.get("state") == "unavailable":
                continue
            label = str(payload.get("label") or f"Account #{account_id}")
            self._emit_account_status(account_id, label, state, code, message)

    def _run_sequential(self, urls: List[str], row_ids: Optional[List[int]] = None) -> None:
        """Process shared-cookie URLs one by one with the same safe pacing."""
        pacing = AccountPacingState()
        for i, url in enumerate(urls):
            if self._stop_event.is_set():
                break

            # Check pause
            self._pause_event.wait()

            if self._stop_event.is_set():
                break

            if not self._wait_for_account_slot(pacing, 0, "Cookie phiên"):
                break

            row_id = (row_ids or [0] * len(urls))[i]
            if row_id:
                self._process_single_post(url, i + 1, source_post_row_id=row_id)
            else:
                self._process_single_post(url, i + 1)
            if not self._stop_event.is_set():
                # Cookie mode has one account only; pace every completed attempt
                # even when the post itself was unavailable or its media failed.
                self._schedule_account_pacing(pacing, 0, "Cookie phiên", failed=False)

    def _run_parallel(self, urls: List[str], row_ids: Optional[List[int]] = None) -> None:
        """Process URL chunks with one thread-owned Playwright browser per worker."""
        worker_count = max(1, min(self._max_threads, len(urls)))
        chunks: List[List[tuple[int, str, int]]] = [[] for _ in range(worker_count)]
        for index, url in enumerate(urls, start=1):
            row_id = (row_ids or [0] * len(urls))[index - 1]
            chunks[(index - 1) % worker_count].append((index, url, row_id))

        def worker(worker_index: int, items: List[tuple[int, str, int]]) -> None:
            browser = BrowserManager(
                profile_dir=str(chrome_profile_dir(f"download_cookie_{worker_index}")),
                cdp_port=9300 + worker_index,
                headless=True,
            )
            with self._lock:
                self._browsers.append(browser)
            try:
                if not browser.start(self._cookies):
                    logger.error(f"Không thể khởi động trình duyệt tải #{worker_index}!")
                    for index, url, row_id in items:
                        self._attempt_local.source_post_row_id = row_id
                        self._notify_post_failed(url, index, "Không thể khởi động trình duyệt")
                        self._update_stats(failed=True)
                    return
                for index, url, row_id in items:
                    if self._stop_event.is_set():
                        break
                    self._pause_event.wait()
                    if self._stop_event.is_set():
                        break
                    kwargs = {
                        "browser": browser, "cookies": self._cookies,
                        "account_label": f"Luồng {worker_index}",
                    }
                    if row_id:
                        kwargs["source_post_row_id"] = row_id
                    self._process_single_post(url, index, **kwargs)
            finally:
                browser.stop()
                with self._lock:
                    if browser in self._browsers:
                        self._browsers.remove(browser)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            self._executor = executor
            futures: List[Future] = [
                executor.submit(worker, worker_index, items)
                for worker_index, items in enumerate(chunks, start=1)
            ]
            for future in futures:
                try:
                    future.result(timeout=600)
                except Exception as e:
                    logger.error(f"Thread error: {str(e)[:200]}")
            self._executor = None

    def _process_single_post(
        self,
        url: str,
        index: int,
        browser: Optional[BrowserManager] = None,
        cookies: Optional[Dict[str, str]] = None,
        account_label: str = "",
        source_post_row_id: int = 0,
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
        context = getattr(self._attempt_local, "context", None)
        if isinstance(context, dict):
            source_post_row_id = int(source_post_row_id or context.get("source_post_row_id") or 0)
        self._attempt_local.source_post_row_id = source_post_row_id

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
            self._mark_post_download_status(url, "downloading", source_post_row_id=source_post_row_id)

            # Look up metadata from local database
            video_url = normalize_video_post_url(url)
            db_path = get_db_path(config.get("scraper_db_path", ""))
            db_post = get_post_by_row_id(db_path, source_post_row_id) if source_post_row_id else None
            if not db_post:
                db_post = get_post_by_id(db_path, post_id, video_url or url)
            source_post_id = str((db_post or {}).get("post_id") or post_id or "").strip()
            if video_url and db_post and (
                not (
                    db_post.get("video_url_verified")
                    or is_video_url_for_story_id(video_url, source_post_id)
                )
                or normalize_video_post_url(str(db_post.get("url") or "")) != video_url
            ):
                logger.warning("URL video không có xác nhận từ attachment của bài nguồn; dùng permalink nguồn")
                video_url = ""

            # Resolve best URL
            active_url = video_url or url
            is_bare_numeric = bool(re.match(r"^https?://(?:www\.|m\.|web\.)?facebook\.com/(\d{10,})/?(?:\?.*)?$", url.strip()))
            if db_post and source_post_id:
                canonical_page_url = (
                    _canonical_post_url(str(db_post["page_url"]), source_post_id)
                    if db_post.get("page_url") else f"https://www.facebook.com/{source_post_id}"
                )
                if not video_url and (
                    is_bare_numeric or not is_story_permalink_for_id(url, source_post_id)
                ):
                    active_url = canonical_page_url
                    logger.info(f"Dùng link bài viết đã xác minh từ Fanpage: {active_url}")
            elif is_bare_numeric:
                if db_post and db_post.get("page_url"):
                    active_url = _canonical_post_url(str(db_post["page_url"]), post_id)
                    logger.info(f"Chuyển đổi URL bare post {url} → {active_url}")
                elif post_id.isdigit():
                    active_url = f"https://www.facebook.com/{post_id}"
                    logger.info(f"URL dạng số, dùng link direct post: {active_url}")

            # Fetch and parse using browser
            if not active_browser:
                error_msg = "Trình duyệt không hoạt động"
                logger.error(error_msg)
                self._notify_post_failed(url, index, error_msg)
                self._update_stats(failed=True)
                return

            active_post_id = extract_post_id(active_url) or post_id
            post_data = active_browser.fetch_post(active_url, active_post_id)

            # Fallback if first attempt failed
            if not post_data.is_valid and active_post_id.isdigit() and len(active_post_id) >= 10:
                direct_url = f"https://www.facebook.com/{active_post_id}"
                if active_url != direct_url:
                    logger.info(f"Thử fallback sang direct post URL: {direct_url}")
                    direct_data = active_browser.fetch_post(direct_url, active_post_id)
                    if direct_data.is_valid:
                        post_data = direct_data
                        active_url = direct_url

            # Enrich text and metadata from db_post if browser missed it
            if db_post:
                db_caption = (db_post.get("caption") or "").strip()
                if db_caption:
                    if not post_data.text or len(db_caption) > len(post_data.text) or BrowserManager._is_ui_text(post_data.text):
                        post_data.text = db_caption
                        logger.info(f"Sử dụng caption từ database ({len(post_data.text)} ký tự)")
                if db_post.get("post_type") == "Video":
                    post_data.has_video = True
                if post_data.error and (post_data.text or post_data.has_video or db_post.get("media_preview_url")):
                    post_data.error = None

            # The watch URL uses the attachment ID for parsing. Keep the source
            # story ID for flat filenames, status updates, and exact DB matching.
            if source_post_id:
                post_data.post_id = source_post_id

            stored_post_type = str((db_post or {}).get("post_type") or "").strip()
            has_explicit_video_url = any(
                marker in active_url.lower() for marker in ("/watch/", "/reel/", "/videos/")
            )
            if (
                stored_post_type == "Ảnh"
                and post_data.image_urls
                and not has_explicit_video_url
                and post_data.has_video
            ):
                # The scanner already classified this source post as an image.
                # Ignore an unscoped parser video signal so its images are not
                # skipped and then reported as a failed video download.
                logger.warning("Bỏ qua tín hiệu video không khớp với post ảnh đã quét")
                post_data.has_video = False
                post_data.video_url = ""

            is_video_post = bool(
                post_data.has_video
                or stored_post_type == "Video"
                or has_explicit_video_url
            )
            if is_video_post:
                post_data.has_video = True

            expected_media_count = post_data.media_count
            if stored_post_type == "Ảnh":
                try:
                    expected_media_count = max(expected_media_count, int((db_post or {}).get("media_count") or 0))
                except (TypeError, ValueError):
                    pass

            if not post_data.is_valid and not (db_post and (db_post.get("caption") or db_post.get("media_preview_url"))):
                error_msg = self._error_with_code(
                    f"Không thể parse post: {post_data.error or 'Không tìm thấy nội dung/media'}",
                    post_data.error_code,
                )
                logger.error(error_msg)
                self._notify_post_failed(url, index, error_msg)
                self._update_stats(failed=True)
                return

            # Check stop
            if self._stop_event.is_set():
                return

            # Create output files for this post directly in self._output_dir (flat storage)
            post_id = self._make_folder_name(post_data)
            existing_action = self._handle_existing_post(
                post_id, url, is_video_post=is_video_post, expected_media_count=expected_media_count,
            )
            if existing_action in {"cancel", "open_folder"}:
                if self._post_has_media(post_id, is_video_post=is_video_post):
                    logger.info(f"Post {index} đã được tải trước đó → {post_id}")
                    self._mark_post_downloaded(post_data, self._output_dir, url, post_id=post_id)
                    self._update_stats(failed=False)
                else:
                    logger.warning(f"Post {index} đã có file nhưng chưa đủ media, bỏ qua theo yêu cầu")
                    self._notify_post_failed(url, index, "Bỏ qua bản tải cũ chưa hoàn thiện")
                    self._update_stats(failed=True)
                return

            # Update media count
            with self._lock:
                self.stats.total_media += expected_media_count

            if post_data.text and post_data.text.strip():
                caption_path = self._output_dir / f"{post_id}.txt"
                save_text_content(post_data.text.strip(), caption_path)

            if post_data.media_count <= 0:
                # An image post whose DOM did not render its gallery is not a
                # video. Preserve the known preview when available, but keep
                # the retryable error accurate instead of invoking yt-dlp or
                # labeling the post as a missing video.
                if stored_post_type == "Ảnh":
                    preview_url = (db_post or {}).get("media_preview_url") or ""
                    if preview_url:
                        logger.info("Không thấy gallery ảnh trong DOM; đang lưu ảnh preview...")
                        preview_ext = _get_extension_from_url(preview_url) or ".jpeg"
                        preview_path = self._output_dir / f"{post_id}_1{preview_ext}"
                        if download_image(preview_url, preview_path, active_cookies):
                            with self._lock:
                                self.stats.downloaded_media += 1
                                self.stats.total_media += 1
                            error_msg = "Không trích xuất được gallery ảnh đầy đủ; chỉ lưu ảnh preview để có thể tải lại."
                            self._mark_post_downloaded(
                                post_data, self._output_dir, url,
                                status="failed", error=error_msg, post_id=post_id,
                            )
                            self._notify_post_failed(url, index, error_msg)
                            self._update_stats(failed=True)
                            logger.warning(f"⚠️ Post {index} chỉ lưu ảnh preview, chưa đủ gallery → {post_id}")
                            return

                logger.warning(
                    "Không thấy media trong DOM; thử nhận diện và tải video trực tiếp bằng yt-dlp..."
                )
                video_success = download_video(
                    get_original_url(active_url), self._output_dir, active_cookies, post_id=post_id
                )
                if video_success and self._post_has_media(post_id, is_video_post=True):
                    with self._lock:
                        downloaded = self._get_post_media_files(post_id, is_video_post=True)
                        self.stats.downloaded_media += len(downloaded)
                        self.stats.total_media += len(downloaded)
                        self.stats.total_bytes += sum(p.stat().st_size for p in downloaded)
                    self._mark_post_downloaded(post_data, self._output_dir, url, post_id=post_id)
                    self._update_stats(failed=False)
                    logger.info(f"✅ Post {index} hoàn thành bằng yt-dlp → {post_id}")
                    return

                # If yt-dlp failed, check if we have preview image in db_post
                preview_url = (db_post.get("media_preview_url") if db_post else "")
                if preview_url:
                    logger.info("Đang tải ảnh preview/thumbnail...")
                    thumb_ext = _get_extension_from_url(preview_url) or ".jpeg"
                    thumb_path = self._output_dir / f"{post_id}_1{thumb_ext}"
                    if download_image(preview_url, thumb_path, active_cookies):
                        with self._lock:
                            self.stats.downloaded_media += 1
                            self.stats.total_media += 1
                        self._mark_post_downloaded(
                            post_data, self._output_dir, url,
                            status="thumbnail_only",
                            error="Chỉ tải được ảnh thumbnail, chưa tải được file video stream",
                            post_id=post_id,
                        )
                        self._notify_post_failed(url, index, "Chỉ tải được thumbnail/caption, không tải được video")
                        self._update_stats(failed=True)
                        logger.warning(f"⚠️ Post {index} chỉ lưu caption & thumbnail (thiếu video) → {post_id}")
                        return

                error_msg = self._latest_media_error(
                    "Không tìm thấy ảnh/video và yt-dlp không tải được video",
                    active_browser,
                )
                self._cleanup_failed_post(post_id)
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

                    ext = _get_extension_from_url(img_url) or ".jpeg"
                    img_path = self._output_dir / f"{post_id}_{j+1}{ext}"
                    if img_path.is_file() and img_path.stat().st_size > 0:
                        image_success_count += 1
                        continue
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

                expected_image_count = expected_media_count if stored_post_type == "Ảnh" else len(post_data.image_urls)
                if post_data.image_urls and image_success_count == 0:
                    error_msg = self._latest_media_error(
                        f"Thiếu media local: tìm thấy 0/{expected_image_count} file",
                        active_browser,
                    )
                    logger.error(f"❌ Post {index} thất bại — {error_msg}")
                    self._cleanup_failed_post(post_id)
                    self._notify_post_failed(url, index, error_msg)
                    self._update_stats(failed=True)
                    return
                if image_success_count < expected_image_count:
                    error_msg = f"Thiếu media local: tìm thấy {image_success_count}/{expected_image_count} file"
                    self._mark_post_downloaded(
                        post_data, self._output_dir, url, status="failed", error=error_msg, post_id=post_id,
                    )
                    self._notify_post_failed(url, index, error_msg)
                    self._update_stats(failed=True)
                    logger.warning(f"⚠️ Post {index}: {error_msg}")
                    return
                if image_failed_count:
                    logger.warning(f"Post {index}: tải được {image_success_count}/{expected_image_count} ảnh")

            # Download video
            if post_data.has_video:
                if self._stop_event.is_set():
                    return
                self._pause_event.wait()

                video_success = False
                video_path = self._output_dir / f"{post_id}.mp4"

                if post_data.video_url:
                    logger.info(f"Video URL found ({len(post_data.video_url)} chars)")
                else:
                    logger.warning("Không tìm thấy video URL từ page source")

                # Method 1: Browser download (uses authenticated session)
                if post_data.video_url and active_browser and hasattr(active_browser, "download_file"):
                    logger.info("Tải video qua browser session...")
                    try:
                        video_success = active_browser.download_file(
                            post_data.video_url, video_path
                        )
                    except Exception as e:
                        logger.warning(f"Tải video qua browser session lỗi: {e}")

                # Method 2: Direct HTTP download with headers
                if not video_success and post_data.video_url:
                    logger.info("Thử tải video trực tiếp...")
                    video_success = download_video_direct(
                        post_data.video_url, video_path, active_cookies
                    )

                # Method 3: Fallback to yt-dlp
                if not video_success:
                    logger.info("Thử tải video bằng yt-dlp...")
                    original_url = get_original_url(active_url)
                    video_success = download_video(
                        original_url, self._output_dir, active_cookies, post_id=post_id
                    )

                if video_success:
                    try:
                        video_success = any(
                            video_file.stat().st_size > 0
                            for video_file in self._get_post_media_files(post_id, is_video_post=True)
                        )
                    except OSError:
                        video_success = False
                    if not video_success:
                        logger.warning("Downloader báo thành công nhưng chưa có file video hợp lệ.")

                if video_success:
                    with self._lock:
                        self.stats.downloaded_media += 1
                        vfiles = self._get_post_media_files(post_id, is_video_post=True)
                        for vf in vfiles:
                            self.stats.total_bytes += vf.stat().st_size
                    self._notify_stats()
                    self._mark_post_downloaded(post_data, self._output_dir, url, post_id=post_id)
                    self._update_stats(failed=False)
                    logger.info(f"✅ Post {index} hoàn thành → {post_id}")
                else:
                    # Video stream failed, try to preserve preview/thumbnail & caption
                    preview_url = (db_post.get("media_preview_url") if db_post else "") or (post_data.image_urls[0] if post_data.image_urls else "")
                    has_thumb = False
                    if preview_url:
                        logger.info("Không tải được video stream, đang lưu ảnh preview/thumbnail...")
                        thumb_ext = _get_extension_from_url(preview_url) or ".jpeg"
                        thumb_path = self._output_dir / f"{post_id}_1{thumb_ext}"
                        if download_image(preview_url, thumb_path, active_cookies):
                            has_thumb = True
                            with self._lock:
                                self.stats.downloaded_media += 1
                                if thumb_path.exists():
                                    self.stats.total_bytes += thumb_path.stat().st_size
                            self._notify_stats()

                    has_caption = (self._output_dir / f"{post_id}.txt").exists()
                    if has_thumb:
                        saved_items = "caption và thumbnail" if has_caption else "thumbnail"
                        logger.warning(
                            f"⚠️ Post {index}: Không thể tải trực tiếp video stream (yêu cầu đăng nhập), "
                            f"đã bảo toàn {saved_items} → {post_id}"
                        )
                        self._mark_post_downloaded(
                            post_data, self._output_dir, url,
                            status="thumbnail_only",
                            error="Chỉ tải được ảnh thumbnail, chưa tải được file video stream",
                            post_id=post_id,
                        )
                        self._notify_post_failed(url, index, "Chỉ tải được thumbnail/caption, không tải được video stream")
                        self._update_stats(failed=True)
                    else:
                        error_msg = self._latest_media_error(
                            "Không tải được video sau khi thử browser session, direct HTTP và yt-dlp",
                            active_browser,
                        )
                        self._cleanup_failed_post(post_id)
                        logger.error(f"❌ Post {index} thất bại — {error_msg}")
                        self._notify_post_failed(url, index, error_msg)
                        self._update_stats(failed=True)
            else:
                self._mark_post_downloaded(post_data, self._output_dir, url, post_id=post_id, source_post_row_id=source_post_row_id)
                self._update_stats(failed=False)
                logger.info(f"✅ Post {index} hoàn thành → {post_id}")

        except Exception as e:
            error_msg = f"Lỗi xử lý post: {str(e)[:200]}"
            logger.error(f"Lỗi xử lý post {index}: {str(e)[:200]}")
            self._notify_post_failed(url, index, error_msg)
            self._update_stats(failed=True)

    def _make_folder_name(self, post_data: PostData) -> str:
        """
        Create base identifier using the post's numeric ID.
        Example: 836851975657298
        """
        if post_data.post_id:
            if re.fullmatch(r"pfbid[A-Za-z0-9_-]{8,100}", post_data.post_id, re.IGNORECASE):
                return post_data.post_id
            numeric_id = re.sub(r'\D', '', post_data.post_id)
            if numeric_id:
                return numeric_id
            return post_data.post_id[:30]
        return "post_unknown"

    def _mark_post_downloaded(
        self, post_data: PostData, post_dir: Path, url: str, status: str = "downloaded", error: str = "", post_id: str = "",
        source_post_row_id: int = 0,
    ) -> None:
        """Mark or save a download only under its verified Facebook source page."""
        candidates = {
            str(post_id or "").strip(),
            str(getattr(post_data, "post_id", "") or "").strip(),
            str(extract_post_id(url) or "").strip(),
        }
        if post_dir and post_dir.name and post_dir != self._output_dir:
            candidates.add(str(post_dir.name).strip())
        candidates |= {
            re.sub(r"\D", "", c) for c in list(candidates)
            if c and not c.lower().startswith("pfbid")
        }
        post_ids = [c for c in candidates if c and c != "unknown"]
        if not post_ids:
            return
        try:
            db_path = get_db_path(config.get("scraper_db_path", ""))
            source_post_row_id = int(source_post_row_id or getattr(self._attempt_local, "source_post_row_id", 0) or 0)
            if source_post_row_id:
                updated = mark_post_row_downloaded(
                    db_path, source_post_row_id, str(post_dir), status=status, error=error
                )
                if updated:
                    logger.info(f"Đã cập nhật trạng thái '{status}' cho đúng dòng Post Spy #{source_post_row_id}.")
                return
            target = resolve_download_target(
                db_path,
                post_ids,
                url=normalize_video_post_url(url) or url,
                page_url=getattr(post_data, "author_url", ""),
                page_name=getattr(post_data, "author", ""),
                caption=str(getattr(post_data, "text", "") or ""),
            )
            if target and target.get("row_id"):
                updated = int(mark_post_row_downloaded(
                    db_path, int(target["row_id"]), str(post_dir), status=status, error=error
                ))
                if status == "downloaded":
                    logger.info(f"Đã đánh dấu {updated} bài là Đã tải trong Post Spy.")
                else:
                    logger.info(f"Đã cập nhật {updated} bài trạng thái '{status}' ({error}) trong Post Spy.")
            elif target and target.get("page_url"):
                created = register_downloaded_post_for_page(
                    db_path,
                    post_id or self._make_folder_name(post_data),
                    normalize_video_post_url(url) or url,
                    post_data.text,
                    page_name=target.get("page_name", ""),
                    page_url=target["page_url"],
                    post_type="Video" if post_data.has_video else "Ảnh" if post_data.image_urls else "Text",
                    media_count=post_data.media_count,
                    folder_path=str(post_dir),
                    status=status,
                    error=error,
                )
                if created:
                    logger.info("Đã thêm bài tải vào page nguồn đã xác minh.")
            else:
                logger.warning("Không ghi Post Spy: chưa xác minh được page nguồn của bài tải.")
        except Exception as e:
            logger.error(f"Không cập nhật trạng thái đã tải: {str(e)[:200]}")

    @staticmethod
    def _post_id_candidates(url: str) -> List[str]:
        """Build stable database identifiers from a Facebook post URL."""
        candidates = {str(extract_post_id(url) or "").strip()}
        candidates |= {
            re.sub(r"\D", "", value) for value in list(candidates)
            if value and not value.lower().startswith("pfbid")
        }
        return [value for value in candidates if value and value != "unknown"]

    def _mark_post_download_status(self, url: str, status: str, error: str = "", source_post_row_id: int = 0) -> None:
        try:
            db_path = get_db_path(config.get("scraper_db_path", ""))
            source_post_row_id = int(source_post_row_id or getattr(self._attempt_local, "source_post_row_id", 0) or 0)
            if source_post_row_id:
                mark_post_row_download_status(db_path, source_post_row_id, status, error=error)
                return
            db_post = get_post_by_id(db_path, extract_post_id(url), normalize_video_post_url(url) or url)
            if db_post and db_post.get("post_id"):
                post_ids = self._post_id_candidates(str(db_post["post_id"]))
            else:
                post_ids = self._post_id_candidates(url)
            if not post_ids:
                return
            mark_posts_download_status(db_path, post_ids, status, error=error)
        except Exception as exc:
            logger.error(f"Không cập nhật trạng thái tải: {str(exc)[:200]}")

    def _mark_urls_download_status(
        self,
        urls: List[str],
        status: str,
        error: str = "",
        *,
        only_if_status: str = "",
        source_post_row_ids: Optional[List[int]] = None,
    ) -> None:
        """Persist the state of every queued URL before worker threads start."""
        try:
            db_path = get_db_path(config.get("scraper_db_path", ""))
            if source_post_row_ids and len(source_post_row_ids) == len(urls):
                for row_id in source_post_row_ids:
                    if row_id:
                        mark_post_row_download_status(
                            db_path, int(row_id), status, error=error, only_if_status=only_if_status,
                        )
                fallback = [url for url, row_id in zip(urls, source_post_row_ids, strict=True) if not row_id]
                if not fallback:
                    return
                urls = fallback
            post_ids: List[str] = []
            for url in urls:
                db_post = get_post_by_id(db_path, extract_post_id(url), normalize_video_post_url(url) or url)
                if db_post and db_post.get("post_id"):
                    post_ids.extend(self._post_id_candidates(str(db_post["post_id"])))
                else:
                    post_ids.extend(self._post_id_candidates(url))
            post_ids = list(dict.fromkeys(post_ids))
            if not post_ids:
                return
            mark_posts_download_status(
                db_path,
                post_ids,
                status,
                error=error,
                only_if_status=only_if_status,
            )
        except Exception as exc:
            logger.error(f"Không cập nhật trạng thái hàng đợi tải: {str(exc)[:200]}")

    def _get_post_media_files(self, post_id: str, is_video_post: bool = False) -> List[Path]:
        """Find media files belonging to post_id in flat storage."""
        clean_pid = post_file_key(post_id)
        if not clean_pid or not self._output_dir.exists():
            return []
        video_exts = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v"}
        results = []
        try:
            for p in self._output_dir.iterdir():
                if not p.is_file():
                    continue
                name_match = (
                    p.stem == clean_pid
                    or p.name.startswith(f"{clean_pid}_")
                    or p.name.startswith(f"{clean_pid}.")
                )
                if name_match:
                    ext = p.suffix.lower()
                    if is_video_post and ext in video_exts:
                        results.append(p)
                    elif not is_video_post and ext in MEDIA_FILE_EXTS:
                        results.append(p)
        except Exception:
            pass
        return results

    def _post_has_media(self, post_id: str, is_video_post: bool = False) -> bool:
        return bool(self._get_post_media_files(post_id, is_video_post=is_video_post))

    def _post_dir_has_media(self, post_dir: Path, is_video_post: bool = False) -> bool:
        return self._post_has_media(post_dir.name if isinstance(post_dir, Path) else str(post_dir), is_video_post=is_video_post)

    def _handle_existing_post(
        self, post_target: Any, url: str = "", is_video_post: bool = False, expected_media_count: int = 0,
    ) -> str:
        """Ask the GUI what to do when a post already contains media."""
        if isinstance(post_target, Path):
            post_id = post_target.name
        else:
            post_id = str(post_target or "")

        existing_media = self._get_post_media_files(post_id, is_video_post=is_video_post)
        if not existing_media:
            return "download"
        if expected_media_count > 0 and len(existing_media) < expected_media_count:
            logger.info(
                f"Post {post_id} có {len(existing_media)}/{expected_media_count} media; tiếp tục tải phần còn thiếu."
            )
            return "download"

        logger.warning(f"Bài viết đã được tải trước đó: {post_id}")
        action = "cancel"
        if self._on_existing_post:
            try:
                action = self._on_existing_post(str(self._output_dir), post_id, url) or "cancel"
            except Exception as e:
                logger.error(f"Existing-post prompt failed: {str(e)[:200]}")
                action = "cancel"

        action = str(action or "cancel").lower()
        if action == "redownload":
            self._clear_existing_post(post_id)
            return "download"
        if action == "open_folder":
            return "open_folder"
        return "cancel"

    def _clear_existing_post(self, post_id: str) -> None:
        """Remove existing downloaded files for a post before redownloading."""
        clean_pid = post_file_key(post_id)
        if not clean_pid or not self._output_dir.exists():
            return
        try:
            for p in list(self._output_dir.iterdir()):
                if p.is_file() and (
                    p.stem == clean_pid
                    or p.name.startswith(f"{clean_pid}_")
                    or p.name.startswith(f"{clean_pid}.")
                ):
                    p.unlink(missing_ok=True)
            logger.info(f"Đã xóa bản tải cũ để tải lại: {clean_pid}")
        except Exception as e:
            logger.error(f"Không xóa được bản tải cũ: {str(e)[:200]}")

    def _clear_existing_post_dir(self, post_dir: Path) -> None:
        self._clear_existing_post(post_dir.name if isinstance(post_dir, Path) else str(post_dir))

    def _cleanup_failed_post(self, post_id: str) -> None:
        """Remove partial files (like caption or incomplete media) if post download failed."""
        if self._post_has_media(post_id):
            return
        clean_pid = post_file_key(post_id)
        if not clean_pid or not self._output_dir.exists():
            return
        try:
            for p in list(self._output_dir.iterdir()):
                if p.is_file() and (
                    p.stem == clean_pid
                    or p.name.startswith(f"{clean_pid}_")
                    or p.name.startswith(f"{clean_pid}.")
                ):
                    p.unlink(missing_ok=True)
            logger.info(f"Đã dọn file tải chưa hoàn tất cho bài viết: {clean_pid}")
        except Exception as exc:
            logger.warning(f"Không dọn được file tải chưa hoàn tất: {str(exc)[:200]}")

    def _cleanup_failed_post_dir(self, post_dir: Path) -> None:
        self._cleanup_failed_post(post_dir.name if isinstance(post_dir, Path) else str(post_dir))

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
        attempt_context = getattr(self._attempt_local, "context", None)
        if attempt_context and attempt_context.get("defer_stats"):
            attempt_context["failed"] = bool(failed)
            return
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
        attempt_context = getattr(self._attempt_local, "context", None)
        if attempt_context and attempt_context.get("defer_stats"):
            attempt_context["failed"] = True
            attempt_context["error"] = error
        else:
            self._mark_post_download_status(url, "failed", error)
        if not self._on_post_failed:
            return
        try:
            self._on_post_failed({
                "url": url,
                "index": index,
                "error": error,
                "account_id": (attempt_context or {}).get("account_id", 0),
                "attempt": (attempt_context or {}).get("attempt", 1),
                "retrying": bool(attempt_context and attempt_context.get("defer_stats")),
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
        self._notify_idle()
        self._pause_event.set()
        self._stop_event.clear()
        self.stats = DownloadStats()
        self._cookies = {}
        logger.info("🔄 Đã reset")
