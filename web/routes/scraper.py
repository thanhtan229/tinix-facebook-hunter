import threading
import time
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, HTTPException
from pydantic import Field, HttpUrl, model_validator
from typing import List, Literal, Optional
from core.page_scraper import PageScraper, is_valid_facebook_page_name
from core.page_search import PageSearchEngine
from core.account_preflight import check_facebook_account
from core.profile_lease import (
    ProfileLeaseConflict,
    acquire_profile_leases,
    profile_lease_owner,
    release_profile_leases,
)
from core.db_storage import (
    create_task_run,
    create_favorite_page_group,
    delete_favorite_page,
    delete_favorite_pages,
    delete_favorite_page_group,
    finish_favorite_scan,
    finish_favorite_archive_scan,
    finish_task_run,
    get_all_accounts,
    get_favorite_page,
    get_favorite_page_groups,
    get_favorite_pages,
    get_db_path,
    find_page_by_url,
    get_page_post_ids,
    get_page_archive_cursor,
    mark_favorite_scan_started,
    reset_favorite_cursor,
    reset_favorite_cursors,
    save_favorite_page,
    save_account_preflight_result,
    save_posts,
    update_favorite_group_members,
    update_favorite_page_group,
)
from utils import config, logger
from web.ws_manager import log_to_web, progress_to_web
from web.models import ApiRequest

router = APIRouter(prefix="/api/scrape", tags=["Scraper"])

_scraper_thread: Optional[threading.Thread] = None
_active_scraper: Optional[PageScraper] = None
_active_favorite_scrapers: dict[str, PageScraper] = {}
_favorite_worker_stop_events: dict[str, threading.Event] = {}
_active_task_run_id = 0
_active_profile_lease_owner = ""
_active_profile_lease_keys: set[str] = set()
_scrape_lock = threading.RLock()
_stop_requested = threading.Event()
_scrape_status = {
    "is_running": False,
    "current_page": "",
    "posts_found": 0,
    "start_time": 0,
    "elapsed": 0,
    "queue_total": 0,
    "queue_completed": 0,
    "queue_successful": 0,
    "queue_failed": 0,
    "current_favorite_id": 0,
    "new_posts": 0,
    "task_type": "",
    "keyword": "",
    "error": "",
    "search_results": [],
    "workers": {},
}


def scrape_is_running() -> bool:
    with _scrape_lock:
        return bool(_scrape_status["is_running"])


def _finish_scrape_task_run(status: str, saved_posts: int = 0, error: str = "") -> None:
    """Persist a compact, credential-free summary when a scan coordinator ends."""
    global _active_task_run_id
    if not _active_task_run_id:
        return
    with _scrape_lock:
        completed = int(_scrape_status.get("queue_completed", 0))
        successful = int(_scrape_status.get("queue_successful", 0))
        failed = int(_scrape_status.get("queue_failed", 0))
    finish_task_run(
        get_db_path(config.get("scraper_db_path", "")),
        _active_task_run_id,
        status,
        completed_items=completed,
        successful_items=successful,
        failed_items=failed,
        error_message=error or ("" if status == "completed" else f"Đã lưu {saved_posts} bài"),
    )
    _active_task_run_id = 0


def _record_scrape_page_result(success: Optional[bool]) -> None:
    """Count a processed Page once; worker state is not a Page-level outcome."""
    with _scrape_lock:
        _scrape_status["queue_completed"] += 1
        if success is True:
            _scrape_status["queue_successful"] += 1
        elif success is False:
            _scrape_status["queue_failed"] += 1


def _release_scrape_profile_leases() -> None:
    global _active_profile_lease_owner, _active_profile_lease_keys
    if _active_profile_lease_keys:
        release_profile_leases(_active_profile_lease_owner, _active_profile_lease_keys)
        _active_profile_lease_owner = ""
        _active_profile_lease_keys = set()


def _preflight_scrape_queues(db_path: str, queues: List[dict]) -> None:
    """Check assigned accounts before a scan uses their Chrome profile."""
    for queue in queues:
        if _stop_requested.is_set() or queue.get("account_error"):
            continue
        account = queue.get("account")
        if not account:
            continue
        worker_id = queue["worker_id"]
        _update_favorite_worker(worker_id, status="Đang kiểm tra", error="")
        result = check_facebook_account(account)
        checked_at = save_account_preflight_result(
            db_path,
            int(account.get("id") or 0),
            code=result.code,
            message=result.message,
        )
        if result.ready:
            _update_favorite_worker(worker_id, status="Đang chờ", error="")
            log_to_web(f"[{queue['account_label']}] Preflight sẵn sàng ({checked_at or 'chưa lưu'}).", "OK")
            continue
        queue["account_error"] = result.message
        _update_favorite_worker(worker_id, status="Không sẵn sàng", error=result.message)
        log_to_web(f"[{queue['account_label']}] Preflight thất bại: {result.message}", "WARNING")


def _resolve_scraped_page_name(
    db_path: str, page_url: str, scraped_name: str = "", preferred_name: str = "",
) -> str:
    """Choose a durable Page name and reject transient Facebook UI labels."""
    registered = find_page_by_url(db_path, page_url) or {}
    candidates = (preferred_name, registered.get("page_name", ""), scraped_name)
    for candidate in candidates:
        if is_valid_facebook_page_name(candidate):
            return str(candidate).strip()
    # A URL is a safer fallback than a generic UI label such as "Thông tin liên hệ".
    return str(page_url or "Facebook Page").strip()

class ScrapeStartRequest(ApiRequest):
    page_url: Optional[HttpUrl] = None
    page_urls: List[HttpUrl] = Field(default_factory=list, max_length=100)
    limit: Optional[int] = Field(default=50, ge=1, le=10_000)
    mode: Literal["All"] = "All"
    delay_mode: Literal["fast", "balanced", "cautious"] = "balanced"
    account_mode: Literal["auto", "default", "specific"] = "auto"
    account_id: Optional[int] = Field(default=None, gt=0)
    max_concurrency: int = Field(default=2, ge=1, le=8)
    download_media: Optional[bool] = True

    @model_validator(mode="after")
    def validate_batch(self):
        if not self.page_url and not self.page_urls:
            raise ValueError("Hãy nhập ít nhất một URL Fanpage")
        if self.account_mode == "specific" and not self.account_id:
            raise ValueError("Hãy chọn Account Chrome cần dùng")
        if self.account_mode != "specific" and self.account_id is not None:
            raise ValueError("account_id chỉ dùng với account_mode=specific")
        return self


class FavoriteSaveRequest(ApiRequest):
    page_url: HttpUrl
    page_name: Optional[str] = Field(default="", max_length=300)
    account_id: Optional[int] = Field(default=None, gt=0)
    scan_limit: int = Field(default=100, ge=5, le=2000)
    page_uid: Optional[str] = Field(default="", max_length=100)
    follower_count: int = Field(default=0, ge=0)
    category: Optional[str] = Field(default="", max_length=200)
    avatar_url: Optional[HttpUrl] = None
    verified: bool = False
    group_ids: List[int] = Field(default_factory=list, max_length=50)


class FavoriteActionRequest(ApiRequest):
    favorite_id: int = Field(gt=0)


class FavoriteBatchActionRequest(ApiRequest):
    favorite_ids: List[int] = Field(min_length=1, max_length=500)


class FavoriteGroupCreateRequest(ApiRequest):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#0f766e", pattern=r"^#[0-9a-fA-F]{6}$")


class FavoriteGroupUpdateRequest(FavoriteGroupCreateRequest):
    group_id: int = Field(gt=0)


class FavoriteGroupActionRequest(ApiRequest):
    group_id: int = Field(gt=0)


class FavoriteGroupMembersRequest(FavoriteGroupActionRequest):
    favorite_ids: List[int] = Field(min_length=1, max_length=500)
    action: Literal["add", "remove"] = "add"


class FavoriteWorkerStopRequest(ApiRequest):
    worker_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")


class FavoriteScanRequest(ApiRequest):
    favorite_ids: List[int] = Field(default_factory=list, max_length=500)
    account_mode: Literal["auto", "assigned", "default", "specific"] = "auto"
    account_id: Optional[int] = Field(default=None, gt=0)
    max_concurrency: int = Field(default=2, ge=1, le=8)
    scan_limit: int = Field(default=100, ge=5, le=2000)
    download_media: bool = True
    scan_direction: Literal["new", "older"] = "new"
    delay_mode: Literal["fast", "balanced", "cautious"] = "balanced"

    @model_validator(mode="after")
    def validate_account_choice(self):
        if self.account_mode == "specific" and not self.account_id:
            raise ValueError("Hãy chọn Account Chrome cần dùng")
        if self.account_mode != "specific" and self.account_id is not None:
            raise ValueError("account_id chỉ dùng với account_mode=specific")
        return self


class PageSearchRequest(ApiRequest):
    keyword: str = Field(min_length=1, max_length=100)
    account_mode: Literal["auto", "default", "specific"] = "auto"
    account_id: Optional[int] = Field(default=None, gt=0)
    limit: int = Field(default=30, ge=5, le=100)
    min_followers: int = Field(default=0, ge=0, le=2_000_000_000)
    sort_by: str = Field(default="relevance", pattern="^(relevance|followers|name)$")

    @model_validator(mode="after")
    def validate_search_account(self):
        if self.account_mode == "specific" and not self.account_id:
            raise ValueError("Hãy chọn Account Chrome cần dùng")
        if self.account_mode != "specific" and self.account_id is not None:
            raise ValueError("account_id chỉ dùng với account_mode=specific")
        return self


DELAY_PROFILES = {
    "fast": {
        "batch_size": 100, "delay_min": 8, "delay_max": 15,
        "long_break_every": 500, "long_delay_min": 45, "long_delay_max": 90,
    },
    "balanced": {
        "batch_size": 100, "delay_min": 20, "delay_max": 40,
        "long_break_every": 500, "long_delay_min": 90, "long_delay_max": 180,
    },
    "cautious": {
        "batch_size": 50, "delay_min": 20, "delay_max": 40,
        "long_break_every": 250, "long_delay_min": 90, "long_delay_max": 180,
    },
}


def _run_page_search(
    keyword: str, limit: int, min_followers: int, sort_by: str, account: Optional[dict]
) -> None:
    """Run discovery in the same exclusive browser-task lane as page scraping."""
    global _active_scraper, _scrape_status
    scraper = PageSearchEngine(account=account)
    final_status = "completed"
    results: List[dict] = []
    error_message = ""
    try:
        with _scrape_lock:
            _active_scraper = scraper
        if account:
            preflight = check_facebook_account(account)
            checked_at = save_account_preflight_result(
                get_db_path(config.get("scraper_db_path", "")),
                int(account.get("id") or 0), code=preflight.code, message=preflight.message,
            )
            if not preflight.ready:
                raise RuntimeError(preflight.message)
            log_to_web(f"[{_account_label(account)}] Preflight sẵn sàng ({checked_at or 'chưa lưu'}).", "OK")
        log_to_web(f"Tìm Fanpage với từ khóa: {keyword}", "INFO")
        if not scraper.start():
            raise RuntimeError("Không thể khởi động Chrome")

        def _on_progress(count: int, message: str = "") -> None:
            with _scrape_lock:
                _scrape_status["posts_found"] = count
            progress_to_web("page_search", count, limit, message or f"{count}/{limit}", "searching")

        results = scraper.search(
            keyword=keyword, limit=limit, min_followers=min_followers,
            sort_by=sort_by, on_progress=_on_progress,
        )
        with _scrape_lock:
            _scrape_status["search_results"] = results
            _scrape_status["posts_found"] = len(results)
        if _stop_requested.is_set():
            final_status = "stopped"
            log_to_web(f"Đã dừng tìm kiếm; giữ lại {len(results)} kết quả.", "WARNING")
        else:
            log_to_web(f"✅ Đã tìm thấy {len(results)} Fanpage.", "OK")
    except Exception as exc:
        message = str(exc)[:500]
        error_message = message
        final_status = "stopped" if _stop_requested.is_set() else "failed"
        if not _stop_requested.is_set():
            logger.exception("Lỗi tìm kiếm Fanpage", exc)
            log_to_web(f"Lỗi tìm Fanpage: {message}", "ERROR")
        with _scrape_lock:
            _scrape_status["error"] = "Đã dừng" if _stop_requested.is_set() else message
    finally:
        try:
            scraper.stop()
        except Exception:
            pass
        with _scrape_lock:
            _scrape_status["is_running"] = False
            _active_scraper = None
            _scrape_status["queue_completed"] = len(results)
            _scrape_status["queue_successful"] = len(results)
            _scrape_status["queue_failed"] = 0 if final_status != "failed" else 1
        progress_to_web("page_search", 100, 100, "", final_status)
        _finish_scrape_task_run(final_status, error=error_message)
        _release_scrape_profile_leases()


def _downloadable_post_urls(posts: List[object]) -> List[str]:
    """Return unique post URLs keyed by the stable ID persisted in Post Spy."""
    urls: List[str] = []
    seen: set[str] = set()
    for post in posts:
        post_id = str(getattr(post, "post_id", "") or "").strip()
        # Scanner video links often use ``watch/?v=<video_id>`` while the
        # database is keyed by the post ID.  A direct numeric URL lets the
        # downloader resolve that same DB row and update its status correctly.
        url = (
            f"https://www.facebook.com/{post_id}"
            if post_id.isdigit()
            else str(getattr(post, "url", "") or "").strip()
        )
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _start_auto_download(urls: List[str], accounts: Optional[List[dict]] = None) -> bool:
    """Hand one deduplicated scrape result batch to the downloader account pool."""
    unique_urls = list(dict.fromkeys(str(url).strip() for url in urls if str(url).strip()))
    if not unique_urls:
        return False
    try:
        from web.routes.downloader import enqueue_auto_download
        # A scan-owned pool must stay exclusive to this batch.  Adding every
        # configured account here would lease unrelated profiles and prevent a
        # following scan from creating its own FIFO download batch.
        active_accounts = [
            account for account in (accounts or []) if account and account.get("is_active", 1)
        ]
        if not active_accounts:
            db_p = get_db_path(config.get("scraper_db_path", ""))
            active_accounts = [
                account for account in get_all_accounts(db_p) if account.get("is_active", 1)
            ]
        unique_accounts: dict[object, dict] = {}
        for account in active_accounts:
            key = account.get("id") or account.get("profile_dir") or account.get("username")
            unique_accounts[key] = account
        active_accounts = list(unique_accounts.values())
        account_ids = [int(account.get("id") or 0) for account in active_accounts]
        if enqueue_auto_download(unique_urls, account_ids):
            log_to_web(f"⬇ Auto Download đã nhận {len(unique_urls)} bài vừa quét.", "OK")
            return True
        log_to_web("Auto Download không thể khởi động; hãy kiểm tra Account hoặc cookie tải.", "WARNING")
        return False
    except Exception as exc:
        logger.exception("Không thể khởi động Auto Download", exc)
        log_to_web(f"Auto Download lỗi: {str(exc)[:160]}", "WARNING")
        return False


def _run_scrape_worker(
    page_url: str, limit: int, mode: str, account: Optional[dict],
    download_media: bool, delay_mode: str = "balanced",
):
    global _active_scraper, _scrape_status

    db_p = get_db_path(config.get("scraper_db_path", ""))
    auto_download_urls: List[str] = []
    final_status = "completed"
    log_to_web(f"Khởi động trình duyệt quét Page: {page_url} (tối đa {limit} bài)...", "INFO")

    try:
        scraper = PageScraper(account=account)
        with _scrape_lock:
            _active_scraper = scraper

        if not scraper.start():
            final_status = "failed"
            log_to_web("Không thể khởi động Chrome cho tác vụ quét Page.", "ERROR")
            return

        def _on_progress(count: int, msg: str = ""):
            with _scrape_lock:
                _scrape_status["posts_found"] = count
            progress_to_web("scraper", count, limit, f"{count}/{limit}", "scraping")
            if msg:
                log_to_web(msg, "INFO")

        known_ids = set(get_page_post_ids(db_p, page_url)) if mode in {"New Posts", "Older Posts"} else set()
        archive_cursor = set(get_page_archive_cursor(db_p, page_url)) if mode == "Older Posts" else None
        if mode == "Older Posts" and not known_ids:
            archive_cursor = set()
            log_to_web("Page chưa có dữ liệu cũ; bắt đầu lấy lô lịch sử đầu tiên.", "INFO")

        posts = scraper.scrape_page(
            page_url=page_url,
            max_posts=limit,
            on_progress=_on_progress,
            known_post_ids=known_ids if mode in {"New Posts", "Older Posts"} else None,
            stop_post_ids=known_ids if mode == "New Posts" else None,
            archive_after_post_ids=archive_cursor,
            delay_profile=DELAY_PROFILES[delay_mode],
        )

        if posts:
            page_name = _resolve_scraped_page_name(
                db_p, page_url, posts[0].page_name if posts else "",
            )
            for post in posts:
                post.page_name = page_name
            saved_count = save_posts(
                db_path=db_p,
                page_name=page_name,
                page_url=page_url,
                posts=posts,
                follower_count=getattr(scraper, "last_follower_count", 0)
            )
            if download_media and not _stop_requested.is_set():
                auto_download_urls = _downloadable_post_urls(posts)
            scan_label = "bài cũ" if mode == "Older Posts" else "bài viết"
            log_to_web(f"✅ Đã quét xong {len(posts)} {scan_label}! Đã lưu {saved_count} bài vào cơ sở dữ liệu.", "OK")
        else:
            final_status = "stopped" if _stop_requested.is_set() else "partial"
            log_to_web("Không tìm thấy bài viết nào hoặc quá trình bị hủy.", "WARNING")

    except Exception as e:
        final_status = "failed"
        logger.exception("Lỗi trong tác vụ quét Page", e)
        log_to_web(f"Lỗi khi quét: {str(e)}", "ERROR")
    finally:
        try:
            if _active_scraper:
                _active_scraper.stop()
        except Exception as exc:
            logger.warning(f"Không thể đóng scraper sạch sẽ: {str(exc)[:100]}")
        with _scrape_lock:
            _scrape_status["is_running"] = False
            _active_scraper = None
        progress_to_web("scraper", 100, 100, "", final_status)
        if auto_download_urls and not _stop_requested.is_set():
            _start_auto_download(auto_download_urls, [account] if account else [])


def _account_label(account: Optional[dict]) -> str:
    if not account:
        return "Profile mặc định"
    return account.get("label") or account.get("username") or f"Account #{account.get('id')}"


def _build_quick_queues(
    page_urls: List[str], accounts: List[dict], account_mode: str,
    account_id: Optional[int], max_concurrency: int,
) -> List[dict]:
    """Distribute transient Page URLs so one Account owns at most one worker."""
    active_accounts = [item for item in accounts if item.get("is_active", 1)]
    if account_mode == "auto":
        available_accounts = [item for item in active_accounts if not profile_lease_owner(item)]
        if available_accounts:
            active_accounts = available_accounts
    if account_mode == "specific":
        selected = next((item for item in active_accounts if item.get("id") == account_id), None)
        return [{"worker_id": f"account-{account_id}", "account": selected,
                 "account_label": _account_label(selected), "page_urls": list(page_urls)}]
    if account_mode == "default" or not active_accounts:
        return [{"worker_id": "default", "account": None,
                 "account_label": "Profile mặc định", "page_urls": list(page_urls)}]

    usable = active_accounts[:max(1, min(max_concurrency, len(active_accounts), len(page_urls)))]
    queues = [{"worker_id": f"account-{item['id']}", "account": item,
               "account_label": _account_label(item), "page_urls": []} for item in usable]
    for index, page_url in enumerate(page_urls):
        queues[index % len(queues)]["page_urls"].append(page_url)
    return [queue for queue in queues if queue["page_urls"]]


def _run_quick_worker(queue: dict) -> int:
    """Run one sequential quick-scan queue for one Account/profile."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    worker_id = queue["worker_id"]
    account = queue.get("account")
    stop_event = _favorite_worker_stop_events[worker_id]
    total_saved = 0
    worker_failed = False
    if queue.get("account_error"):
        _update_favorite_worker(worker_id, status="Không sẵn sàng", error=queue["account_error"])
        log_to_web(f"[{queue['account_label']}] Bỏ qua hàng đợi: {queue['account_error']}", "WARNING")
        for _ in queue.get("page_urls", []):
            _record_scrape_page_result(False)
        _update_favorite_worker(
            worker_id,
            queue_completed=len(queue.get("page_urls", [])),
            posts_found=0,
        )
        return 0
    _update_favorite_worker(worker_id, status="Đang chạy")

    for position, page_url in enumerate(queue["page_urls"], start=1):
        if _stop_requested.is_set() or stop_event.is_set():
            break
        _update_favorite_worker(
            worker_id, current_page=page_url, posts_found=0, status="Đang quét",
        )
        with _scrape_lock:
            _scrape_status["current_page"] = page_url
        log_to_web(
            f"🔍 [{queue['account_label']}] {position}/{len(queue['page_urls'])} · {page_url}", "INFO"
        )
        scraper = PageScraper(account=account)
        page_outcome: Optional[bool] = None
        with _scrape_lock:
            _active_favorite_scrapers[worker_id] = scraper
        try:
            if not scraper.start():
                raise RuntimeError("Không thể khởi động Chrome")

            limit = int(queue["scan_limit"])
            mode = queue["mode"]

            def _on_progress(count: int, msg: str = "", _limit: int = limit):
                _update_favorite_worker(worker_id, posts_found=count)
                with _scrape_lock:
                    _scrape_status["posts_found"] = sum(
                        int(item.get("posts_found", 0))
                        for item in _scrape_status.get("workers", {}).values()
                    )
                progress_to_web(
                    "scraper", count, _limit,
                    f"{queue['account_label']} · {msg or count}", "scraping",
                )

            known_ids = set(get_page_post_ids(db_p, page_url)) if mode in {"New Posts", "Older Posts"} else set()
            archive_cursor = set(get_page_archive_cursor(db_p, page_url)) if mode == "Older Posts" else None
            posts = scraper.scrape_page(
                page_url=page_url, max_posts=limit, on_progress=_on_progress,
                known_post_ids=known_ids if mode in {"New Posts", "Older Posts"} else None,
                stop_post_ids=known_ids if mode == "New Posts" else None,
                archive_after_post_ids=archive_cursor,
                delay_profile=queue["delay_profile"],
            )
            saved_count = 0
            if posts:
                page_name = _resolve_scraped_page_name(db_p, page_url, posts[0].page_name)
                for post in posts:
                    post.page_name = page_name
                saved_count = save_posts(
                    db_path=db_p, page_name=page_name, page_url=page_url, posts=posts,
                    follower_count=getattr(scraper, "last_follower_count", 0),
                )
                if queue.get("download_media"):
                    queue["download_urls"].extend(_downloadable_post_urls(posts))
                log_to_web(f"✅ {page_name}: đã lưu {saved_count} bài.", "OK")
            else:
                log_to_web(f"Không tìm thấy bài viết tại {page_url}.", "WARNING")
            total_saved += saved_count
            page_outcome = not (_stop_requested.is_set() or stop_event.is_set())
            with _scrape_lock:
                _scrape_status["new_posts"] += saved_count
        except Exception as exc:
            worker_failed = True
            page_outcome = False
            _update_favorite_worker(worker_id, error=str(exc)[:200])
            log_to_web(f"Lỗi quét {page_url}: {str(exc)[:180]}", "ERROR")
        finally:
            try:
                scraper.stop()
            except Exception:
                pass
            with _scrape_lock:
                _active_favorite_scrapers.pop(worker_id, None)
            _record_scrape_page_result(page_outcome)
            _update_favorite_worker(worker_id, queue_completed=position, new_posts=total_saved)

    stopped = _stop_requested.is_set() or stop_event.is_set()
    _update_favorite_worker(
        worker_id, status="Đã dừng" if stopped else ("Lỗi" if worker_failed else "Hoàn tất"),
        current_page="", posts_found=0,
    )
    return total_saved


def _run_quick_parallel(queues: List[dict], max_concurrency: int, download_media: bool) -> None:
    total_saved = 0
    worker_failed = False
    try:
        if any(queue.get("requires_preflight") for queue in queues):
            db_p = get_db_path(config.get("scraper_db_path", ""))
            _preflight_scrape_queues(db_p, queues)
        with ThreadPoolExecutor(
            max_workers=max(1, min(max_concurrency, len(queues))),
            thread_name_prefix="quick-scan",
        ) as pool:
            futures = [pool.submit(_run_quick_worker, queue) for queue in queues]
            for future in as_completed(futures):
                try:
                    total_saved += int(future.result() or 0)
                except Exception as exc:
                    worker_failed = True
                    logger.exception("Lỗi hàng đợi quét nhanh", exc)
    finally:
        with _scrape_lock:
            worker_failed = worker_failed or any(
                worker.get("status") in {"Lỗi", "Không sẵn sàng"}
                for worker in _scrape_status.get("workers", {}).values()
            ) or _scrape_status["queue_completed"] > _scrape_status["queue_successful"]
            _scrape_status["is_running"] = False
            _active_favorite_scrapers.clear()
            _favorite_worker_stop_events.clear()
        final_status = "stopped" if _stop_requested.is_set() else ("partial" if worker_failed else "completed")
        progress_to_web("scraper", 100, 100, "", final_status)
        log_to_web(
            f"Hoàn tất quét nhanh nhiều Page: đã lưu {total_saved} bài.",
            "WARNING" if final_status != "completed" else "OK",
        )
        _finish_scrape_task_run(final_status, total_saved)
        _release_scrape_profile_leases()
        if download_media and not _stop_requested.is_set():
            urls = [url for queue in queues for url in queue.get("download_urls", [])]
            used_accounts = [queue.get("account") for queue in queues if queue.get("account")]
            _start_auto_download(urls, used_accounts)


def _build_favorite_queues(
    favorites: List[dict], accounts: List[dict], account_mode: str,
    account_id: Optional[int], max_concurrency: int,
) -> List[dict]:
    """Group pages into fair per-account queues; a profile never has two workers."""
    active_accounts = [item for item in accounts if item.get("is_active", 1)]
    if account_mode == "auto":
        available_accounts = [item for item in active_accounts if not profile_lease_owner(item)]
        if available_accounts:
            active_accounts = available_accounts
    account_by_id = {int(item["id"]): item for item in accounts}
    queues: dict[str, dict] = {}

    def ensure(worker_id: str, account: Optional[dict], error: str = "") -> dict:
        if worker_id not in queues:
            queues[worker_id] = {
                "worker_id": worker_id,
                "account": account,
                "account_label": _account_label(account),
                "favorite_ids": [],
                "account_error": error,
            }
        return queues[worker_id]

    if account_mode == "auto":
        usable = active_accounts[:max(1, min(max_concurrency, len(active_accounts)))]
        if not usable:
            return []
        for index, favorite in enumerate(favorites):
            account = usable[index % len(usable)]
            ensure(f"account-{account['id']}", account)["favorite_ids"].append(int(favorite["id"]))
    elif account_mode == "assigned":
        for favorite in favorites:
            assigned_id = favorite.get("account_id")
            if not assigned_id:
                queue = ensure("default", None)
            else:
                account = account_by_id.get(int(assigned_id))
                error = ""
                if account is None:
                    error = "Không tìm thấy Account Chrome đã gán"
                elif not account.get("is_active", 1):
                    error = "Account Chrome đã gán đang bị tắt"
                queue = ensure(f"account-{assigned_id}", account, error)
            queue["favorite_ids"].append(int(favorite["id"]))
    elif account_mode == "specific":
        account = account_by_id.get(int(account_id or 0))
        ensure(f"account-{account_id}", account)["favorite_ids"] = [int(item["id"]) for item in favorites]
    else:
        ensure("default", None)["favorite_ids"] = [int(item["id"]) for item in favorites]
    return list(queues.values())


def _update_favorite_worker(worker_id: str, **values) -> None:
    with _scrape_lock:
        worker = _scrape_status.get("workers", {}).get(worker_id)
        if worker is not None:
            worker.update(values)


def _run_favorite_worker(queue: dict) -> int:
    """Run one sequential Page queue for exactly one Account/profile."""
    global _active_favorite_scrapers
    db_p = get_db_path(config.get("scraper_db_path", ""))
    worker_id = queue["worker_id"]
    account = queue.get("account")
    favorite_ids = queue["favorite_ids"]
    stop_event = _favorite_worker_stop_events[worker_id]
    total_new = 0
    worker_failed = bool(queue.get("account_error"))
    _update_favorite_worker(worker_id, status="Đang chạy")

    for position, favorite_id in enumerate(favorite_ids, start=1):
        if _stop_requested.is_set() or stop_event.is_set():
            break
        favorite = get_favorite_page(db_p, favorite_id)
        if not favorite:
            continue
        page_label = favorite.get("page_name") or favorite["page_url"]
        _update_favorite_worker(
            worker_id, current_page=page_label, current_favorite_id=favorite_id,
            posts_found=0, status="Đang quét",
        )
        with _scrape_lock:
            _scrape_status["current_page"] = favorite["page_url"]
            _scrape_status["current_favorite_id"] = favorite_id
        mark_favorite_scan_started(db_p, favorite_id)

        if queue.get("account_error"):
            finish_favorite_scan(
                db_p, favorite_id, status="Lỗi", new_posts=0,
                error=queue["account_error"],
            )
            _update_favorite_worker(worker_id, error=queue["account_error"])
            _record_scrape_page_result(False)
            _update_favorite_worker(worker_id, queue_completed=position)
            continue

        log_to_web(
            f"⭐ [{queue['account_label']}] {position}/{len(favorite_ids)} · {page_label}", "INFO"
        )
        scraper = PageScraper(account=account)
        page_outcome: Optional[bool] = None
        with _scrape_lock:
            _active_favorite_scrapers[worker_id] = scraper
        try:
            if not scraper.start():
                worker_failed = True
                page_outcome = False
                finish_favorite_scan(
                    db_p, favorite_id, status="Lỗi", new_posts=0,
                    error="Không thể khởi động Chrome",
                )
                _update_favorite_worker(worker_id, error="Không thể khởi động Chrome")
                continue

            scan_limit = int(queue.get("scan_limit") or favorite["scan_limit"])
            scan_direction = queue.get("scan_direction", "new")

            def _on_progress(count: int, msg: str = "", _limit: int = scan_limit):
                _update_favorite_worker(worker_id, posts_found=count)
                with _scrape_lock:
                    _scrape_status["posts_found"] = sum(
                        int(item.get("posts_found", 0))
                        for item in _scrape_status.get("workers", {}).values()
                    )
                progress_to_web(
                    "scraper", count, _limit,
                    f"{queue['account_label']} · {msg or count}", "scraping",
                )

            known_ids = set(get_page_post_ids(db_p, favorite["page_url"]))
            cursor_ids = set(favorite.get("cursor_post_ids") or [])
            archive_cursor_ids = set(favorite.get("archive_cursor_post_ids") or [])
            if scan_direction == "older" and not archive_cursor_ids:
                archive_cursor_ids = set(get_page_archive_cursor(db_p, favorite["page_url"]))
            posts = scraper.scrape_page(
                page_url=favorite["page_url"], max_posts=scan_limit,
                on_progress=_on_progress, known_post_ids=known_ids,
                stop_post_ids=cursor_ids if scan_direction == "new" else None,
                archive_after_post_ids=archive_cursor_ids if scan_direction == "older" else None,
                delay_profile=queue.get("delay_profile"),
            )
            # A saved/registered name wins over a transient Facebook dialog label.
            favorite_name = favorite.get("page_name") or ""
            page_name = _resolve_scraped_page_name(
                db_p, favorite["page_url"],
                posts[0].page_name if posts else page_label,
                favorite_name,
            )
            for post in posts:
                post.page_name = page_name
            saved_count = save_posts(
                db_path=db_p, page_name=page_name, page_url=favorite["page_url"],
                posts=posts, follower_count=getattr(scraper, "last_follower_count", 0),
            ) if posts else 0
            total_new += saved_count
            observed_ids = list(dict.fromkeys(scraper.last_observed_post_ids))
            follower_count = int(getattr(scraper, "last_follower_count", 0) or 0)
            reason = scraper.last_scan_stop_reason
            complete = not cursor_ids or scraper.last_scan_complete
            stopped = _stop_requested.is_set() or stop_event.is_set() or reason == "stopped"
            if queue.get("download_media") and saved_count and not stopped:
                queue.setdefault("download_urls", []).extend(_downloadable_post_urls(posts))
            # A stopped or cursor-limited scan has no terminal Page result.
            page_outcome = True if complete and not stopped else None

            if scan_direction == "older":
                archive_ids = [post.post_id for post in posts if post.post_id]
                if stopped:
                    finish_favorite_archive_scan(
                        db_p, favorite_id, status="Đã dừng quét bài cũ", saved_posts=saved_count,
                        error="Người dùng dừng hàng đợi; mốc lịch sử được giữ nguyên", page_name=page_name,
                    )
                elif scraper.last_scan_complete and archive_ids:
                    finish_favorite_archive_scan(
                        db_p, favorite_id, status="Đã quét thêm bài cũ", saved_posts=saved_count,
                        cursor_post_ids=archive_ids, successful=True, page_name=page_name,
                    )
                    log_to_web(f"✅ [{queue['account_label']}] {page_name}: thêm {saved_count} bài cũ", "OK")
                elif scraper.last_scan_complete:
                    finish_favorite_archive_scan(
                        db_p, favorite_id, status="Đã đến cuối lịch sử", saved_posts=0,
                        error="Không còn bài cũ hơn mốc hiện tại", page_name=page_name,
                    )
                else:
                    error = "Không tìm thấy mốc bài cũ; mốc lịch sử được giữ nguyên"
                    finish_favorite_archive_scan(
                        db_p, favorite_id, status="Chưa hoàn tất bài cũ", saved_posts=saved_count,
                        error=error, page_name=page_name,
                    )
            elif stopped:
                finish_favorite_scan(
                    db_p, favorite_id, status="Đã dừng", new_posts=saved_count,
                    error="Người dùng dừng hàng đợi", page_name=page_name,
                    follower_count=follower_count,
                )
            elif complete and observed_ids:
                finish_favorite_scan(
                    db_p, favorite_id, status="Thành công", new_posts=saved_count,
                    page_name=page_name, cursor_post_ids=observed_ids[:20],
                    successful=True, follower_count=follower_count,
                )
                log_to_web(f"✅ [{queue['account_label']}] {page_name}: {saved_count} bài mới", "OK")
            elif complete:
                finish_favorite_scan(
                    db_p, favorite_id, status="Không có dữ liệu", new_posts=0,
                    error="Không lấy được mốc bài viết", page_name=page_name,
                    follower_count=follower_count,
                )
            else:
                detail = (
                    "Đã đạt giới hạn trước khi gặp mốc cũ; mốc quét được giữ nguyên"
                    if reason == "limit" else "Lần quét chưa hoàn tất; mốc quét được giữ nguyên"
                )
                finish_favorite_scan(
                    db_p, favorite_id, status="Chưa hoàn tất", new_posts=saved_count,
                    error=detail, page_name=page_name, follower_count=follower_count,
                )
        except Exception as exc:
            worker_failed = True
            page_outcome = False
            logger.exception("Lỗi quét Fanpage yêu thích", exc)
            finish_favorite_scan(
                db_p, favorite_id, status="Lỗi", new_posts=0, error=str(exc)[:500],
            )
            _update_favorite_worker(worker_id, error=str(exc)[:200])
        finally:
            try:
                scraper.stop()
            except Exception:
                pass
            with _scrape_lock:
                _active_favorite_scrapers.pop(worker_id, None)
                _scrape_status["new_posts"] += total_new - int(
                    _scrape_status["workers"][worker_id].get("new_posts", 0)
                )
            _update_favorite_worker(
                worker_id, queue_completed=position, new_posts=total_new,
                current_favorite_id=0,
            )
            _record_scrape_page_result(page_outcome)

    stopped = _stop_requested.is_set() or stop_event.is_set()
    final_status = "Đã dừng" if stopped else ("Lỗi" if worker_failed else "Hoàn tất")
    _update_favorite_worker(
        worker_id, status=final_status,
        current_page="", current_favorite_id=0, posts_found=0,
    )
    return total_new


def _run_favorite_parallel(
    queues: List[dict], max_concurrency: int, download_media: bool = False
) -> None:
    """Coordinate independent per-account queues with a bounded worker pool."""
    global _active_favorite_scrapers
    total_new = 0
    worker_failed = False
    try:
        if any(queue.get("requires_preflight") for queue in queues):
            db_p = get_db_path(config.get("scraper_db_path", ""))
            _preflight_scrape_queues(db_p, queues)
        worker_limit = max(1, min(max_concurrency, len(queues)))
        with ThreadPoolExecutor(max_workers=worker_limit, thread_name_prefix="favorite-scan") as pool:
            futures = [pool.submit(_run_favorite_worker, queue) for queue in queues]
            for future in as_completed(futures):
                try:
                    total_new += int(future.result() or 0)
                except Exception as exc:
                    worker_failed = True
                    logger.exception("Lỗi hàng đợi Account", exc)
    finally:
        with _scrape_lock:
            worker_failed = worker_failed or any(
                worker.get("status") in {"Lỗi", "Không sẵn sàng"}
                for worker in _scrape_status.get("workers", {}).values()
            ) or _scrape_status["queue_completed"] > _scrape_status["queue_successful"]
            _scrape_status["is_running"] = False
            _scrape_status["current_favorite_id"] = 0
            _active_favorite_scrapers.clear()
            _favorite_worker_stop_events.clear()
        final_status = "stopped" if _stop_requested.is_set() else ("partial" if worker_failed else "completed")
        progress_to_web("scraper", 100, 100, "", final_status)
        level = "WARNING" if final_status != "completed" else "OK"
        log_to_web(f"Hoàn tất các hàng đợi yêu thích: {total_new} bài mới.", level)
        _finish_scrape_task_run(final_status, total_new)
        _release_scrape_profile_leases()
        if download_media and not _stop_requested.is_set():
            urls = [url for queue in queues for url in queue.get("download_urls", [])]
            accounts = [queue.get("account") for queue in queues if queue.get("account")]
            _start_auto_download(urls, accounts)


def _run_favorite_queue(
    favorite_ids: List[int], account_mode: str = "assigned", account_id: Optional[int] = None
) -> None:
    """Compatibility wrapper used by sequential callers and tests."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    favorites = [item for item in (get_favorite_page(db_p, value) for value in favorite_ids) if item]
    queues = _build_favorite_queues(
        favorites, get_all_accounts(db_p), account_mode, account_id, 1
    )
    with _scrape_lock:
        _scrape_status["workers"] = {
            queue["worker_id"]: {
                "worker_id": queue["worker_id"], "account_label": queue["account_label"],
                "queue_total": len(queue["favorite_ids"]), "queue_completed": 0,
                "current_page": "", "current_favorite_id": 0, "posts_found": 0,
                "new_posts": 0, "status": "Đang chờ", "error": "",
            } for queue in queues
        }
        for queue in queues:
            _favorite_worker_stop_events[queue["worker_id"]] = threading.Event()
    _run_favorite_parallel(queues, 1)

@router.post("/start")
def start_scrape(req: ScrapeStartRequest):
    """Start one or many Page scans using bounded per-account queues."""
    global _active_task_run_id, _scraper_thread, _active_profile_lease_owner, _active_profile_lease_keys
    page_urls = list(dict.fromkeys(
        [str(value) for value in req.page_urls]
        + ([str(req.page_url)] if req.page_url else [])
    ))
    limit = req.limit or 50
    if not page_urls:
        raise HTTPException(status_code=422, detail="URL Fanpage không được để trống")
    if not 1 <= limit <= 2000:
        raise HTTPException(status_code=422, detail="Giới hạn bài viết phải nằm trong khoảng 1-2000")

    db_p = get_db_path(config.get("scraper_db_path", ""))
    accounts = get_all_accounts(db_p)
    if req.account_mode == "specific":
        account = next((item for item in accounts if item.get("id") == req.account_id), None)
        if account is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy Account Chrome đã chọn")
        if not account.get("is_active", 1):
            raise HTTPException(status_code=422, detail="Account Chrome đang bị tắt")
    queues = _build_quick_queues(
        page_urls, accounts, req.account_mode, req.account_id, req.max_concurrency
    )
    worker_count = min(req.max_concurrency, len(queues))
    for queue in queues:
        queue.update({
            "mode": req.mode or "All", "scan_limit": limit,
            "delay_profile": DELAY_PROFILES[req.delay_mode],
            "download_media": bool(req.download_media), "download_urls": [],
            "requires_preflight": True,
        })

    with _scrape_lock:
        if _scrape_status["is_running"]:
            raise HTTPException(status_code=400, detail="Tác vụ quét Page đang chạy rồi!")
        _active_profile_lease_owner = f"scrape-{uuid4().hex[:8]}"
        try:
            _active_profile_lease_keys = acquire_profile_leases(
                _active_profile_lease_owner, [queue.get("account") for queue in queues]
            )
        except ProfileLeaseConflict as exc:
            _active_profile_lease_owner = ""
            _active_profile_lease_keys = set()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _active_task_run_id = create_task_run(
            db_p,
            "scrape_quick",
            total_items=len(page_urls),
            summary={
                "workers": worker_count,
                "scan_limit": limit,
                "download_media": bool(req.download_media),
                "account_mode": req.account_mode,
            },
        )
        _scrape_status.update({
            "is_running": True,
            "current_page": "",
            "posts_found": 0,
            "start_time": time.time(),
            "queue_total": len(page_urls),
            "queue_completed": 0,
            "queue_successful": 0,
            "queue_failed": 0,
            "current_favorite_id": 0,
            "new_posts": 0,
            "task_type": "quick_batch",
            "keyword": "",
            "error": "",
            "search_results": [],
            "workers": {
                queue["worker_id"]: {
                    "worker_id": queue["worker_id"], "account_label": queue["account_label"],
                    "queue_total": len(queue["page_urls"]), "queue_completed": 0,
                    "current_page": "", "posts_found": 0, "new_posts": 0,
                    "status": "Đang chờ", "error": "",
                } for queue in queues
            },
        })
        _stop_requested.clear()
        for queue in queues:
            _favorite_worker_stop_events[queue["worker_id"]] = threading.Event()

    _scraper_thread = threading.Thread(
        target=_run_quick_parallel,
        args=(queues, worker_count, bool(req.download_media)), daemon=True,
    )
    _scraper_thread.start()
    return {
        "status": "success", "message": "Đã bắt đầu tác vụ quét Page",
        "queued": len(page_urls), "workers": worker_count,
    }

@router.post("/stop")
def stop_scrape():
    """Stop active page scraper."""
    global _active_scraper, _active_favorite_scrapers
    with _scrape_lock:
        scraper = _active_scraper
        favorite_scrapers = list(_active_favorite_scrapers.values())
        favorite_events = list(_favorite_worker_stop_events.values())
        is_running = _scrape_status["is_running"]
    _stop_requested.set()
    for event in favorite_events:
        event.set()
    for favorite_scraper in favorite_scrapers:
        try:
            favorite_scraper.stop()
        except Exception:
            pass
    if favorite_events:
        log_to_web("Đã gửi lệnh dừng tất cả hàng đợi Account.", "WARNING")
        return {"status": "success", "message": "Đã dừng tất cả hàng đợi Account"}
    if scraper:
        scraper.stop()
        log_to_web("Đã gửi lệnh dừng quét Page.", "WARNING")
        return {"status": "success", "message": "Đã dừng quét"}
    if is_running:
        return {"status": "success", "message": "Tác vụ đang khởi động; lệnh dừng sẽ khả dụng sau ít giây"}
    return {"status": "success", "message": "Không có tác vụ nào đang chạy"}


def shutdown_scraper(timeout_seconds: float = 5.0) -> None:
    """Request worker-owned browsers to stop during application shutdown."""
    stop_scrape()
    thread = _scraper_thread
    if thread and thread is not threading.current_thread() and thread.is_alive():
        thread.join(timeout=max(0.0, float(timeout_seconds)))
    if thread and thread.is_alive():
        log_to_web("Quét Page chưa dừng kịp khi đóng app; tác vụ sẽ được đánh dấu gián đoạn.", "WARNING")

@router.get("/status")
def get_scrape_status():
    """Get active scrape status."""
    with _scrape_lock:
        snapshot = dict(_scrape_status)
        workers = [dict(item) for item in _scrape_status.get("workers", {}).values()]
    elapsed = 0
    if snapshot["is_running"] and snapshot["start_time"] > 0:
        elapsed = round(time.time() - snapshot["start_time"], 1)
    return {
        "status": "success",
        "data": {
            "is_running": snapshot["is_running"],
            "current_page": snapshot["current_page"],
            "posts_found": snapshot["posts_found"],
            "elapsed_seconds": elapsed,
            "queue_total": snapshot["queue_total"],
            "queue_completed": snapshot["queue_completed"],
            "current_favorite_id": snapshot["current_favorite_id"],
            "new_posts": snapshot["new_posts"],
            "task_type": snapshot["task_type"],
            "keyword": snapshot["keyword"],
            "error": snapshot["error"],
            "results_found": len(snapshot["search_results"]),
            "workers": workers,
        }
    }


@router.get("/favorites")
def list_favorite_pages():
    db_p = get_db_path(config.get("scraper_db_path", ""))
    return {"status": "success", "data": get_favorite_pages(db_p)}


@router.get("/favorites/groups")
def list_favorite_groups():
    db_p = get_db_path(config.get("scraper_db_path", ""))
    return {"status": "success", "data": get_favorite_page_groups(db_p)}


@router.post("/favorites/groups/create")
def create_favorite_group_endpoint(req: FavoriteGroupCreateRequest):
    db_p = get_db_path(config.get("scraper_db_path", ""))
    try:
        group_id = create_favorite_page_group(db_p, req.name, req.color)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "success", "id": group_id}


@router.post("/favorites/groups/update")
def update_favorite_group_endpoint(req: FavoriteGroupUpdateRequest):
    db_p = get_db_path(config.get("scraper_db_path", ""))
    try:
        updated = update_favorite_page_group(db_p, req.group_id, req.name, req.color)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhóm Fanpage")
    return {"status": "success"}


@router.post("/favorites/groups/delete")
def delete_favorite_group_endpoint(req: FavoriteGroupActionRequest):
    if scrape_is_running():
        raise HTTPException(status_code=409, detail="Hãy dừng tác vụ quét trước")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if not delete_favorite_page_group(db_p, req.group_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy nhóm Fanpage")
    return {"status": "success"}


@router.post("/favorites/groups/members")
def update_favorite_group_members_endpoint(req: FavoriteGroupMembersRequest):
    if scrape_is_running():
        raise HTTPException(status_code=409, detail="Hãy dừng tác vụ quét trước")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    try:
        changed = update_favorite_group_members(
            db_p, req.group_id, req.favorite_ids, req.action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "success", "changed": changed}


@router.post("/favorites/save")
def save_favorite_page_endpoint(req: FavoriteSaveRequest):
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if req.account_id and not any(
        account.get("id") == req.account_id for account in get_all_accounts(db_p)
    ):
        raise HTTPException(status_code=404, detail="Không tìm thấy account Chrome")
    valid_group_ids = {item["id"] for item in get_favorite_page_groups(db_p)}
    invalid_group_ids = [value for value in dict.fromkeys(req.group_ids) if value not in valid_group_ids]
    if invalid_group_ids:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy nhóm Fanpage #{invalid_group_ids[0]}")
    favorite_id = save_favorite_page(
        db_p, str(req.page_url), req.page_name or "", req.account_id, req.scan_limit,
        page_uid=req.page_uid or "", follower_count=req.follower_count,
        category=req.category or "", avatar_url=str(req.avatar_url or ""),
        verified=req.verified,
    )
    for group_id in dict.fromkeys(req.group_ids):
        try:
            update_favorite_group_members(db_p, int(group_id), [favorite_id], "add")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "success", "id": favorite_id}


@router.post("/favorites/delete")
def delete_favorite_page_endpoint(req: FavoriteActionRequest):
    if scrape_is_running():
        raise HTTPException(status_code=409, detail="Hãy dừng tác vụ quét trước")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if not delete_favorite_page(db_p, req.favorite_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy Fanpage yêu thích")
    return {"status": "success"}


@router.post("/favorites/batch-delete")
def batch_delete_favorite_pages_endpoint(req: FavoriteBatchActionRequest):
    if scrape_is_running():
        raise HTTPException(status_code=409, detail="Hãy dừng tác vụ quét trước")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    count = delete_favorite_pages(db_p, req.favorite_ids)
    return {"status": "success", "count": count}


@router.post("/favorites/reset-cursor")
def reset_favorite_cursor_endpoint(req: FavoriteActionRequest):
    if scrape_is_running():
        raise HTTPException(status_code=409, detail="Hãy dừng tác vụ quét trước")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if not reset_favorite_cursor(db_p, req.favorite_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy Fanpage yêu thích")
    return {"status": "success"}


@router.post("/favorites/batch-reset-cursor")
def batch_reset_favorite_cursor_endpoint(req: FavoriteBatchActionRequest):
    if scrape_is_running():
        raise HTTPException(status_code=409, detail="Hãy dừng tác vụ quét trước")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    count = reset_favorite_cursors(db_p, req.favorite_ids)
    return {"status": "success", "count": count}


@router.post("/favorites/scan")
def scan_favorite_pages(req: FavoriteScanRequest):
    global _active_task_run_id, _scraper_thread, _active_profile_lease_owner, _active_profile_lease_keys
    db_p = get_db_path(config.get("scraper_db_path", ""))
    available = {item["id"]: item for item in get_favorite_pages(db_p, active_only=True)}
    requested_ids = list(dict.fromkeys(int(value) for value in req.favorite_ids))
    favorite_ids = requested_ids or list(available)
    invalid = [value for value in favorite_ids if value not in available]
    if invalid:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy Fanpage yêu thích #{invalid[0]}")
    if not favorite_ids:
        raise HTTPException(status_code=422, detail="Chưa có Fanpage yêu thích để quét")
    selected_account = None
    if req.account_mode == "specific":
        selected_account = next(
            (item for item in get_all_accounts(db_p) if item.get("id") == req.account_id), None
        )
        if selected_account is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy Account Chrome đã chọn")
        if not selected_account.get("is_active", 1):
            raise HTTPException(status_code=422, detail="Account Chrome đang bị tắt")
    favorites = [available[value] for value in favorite_ids]
    accounts = get_all_accounts(db_p)
    queues = _build_favorite_queues(
        favorites, accounts, req.account_mode, req.account_id, req.max_concurrency
    )
    if req.account_mode == "auto" and not queues:
        raise HTTPException(status_code=422, detail="Không có Account Chrome đang hoạt động")
    worker_count = min(req.max_concurrency, len(queues))
    for queue in queues:
        queue["download_media"] = req.download_media
        queue["download_urls"] = []
        queue["requires_preflight"] = True
        queue["scan_direction"] = req.scan_direction
        queue["scan_limit"] = req.scan_limit
        queue["delay_profile"] = DELAY_PROFILES[req.delay_mode]
    with _scrape_lock:
        if _scrape_status["is_running"]:
            raise HTTPException(status_code=409, detail="Tác vụ quét Page đang chạy")
        _active_profile_lease_owner = f"scrape-{uuid4().hex[:8]}"
        try:
            _active_profile_lease_keys = acquire_profile_leases(
                _active_profile_lease_owner, [queue.get("account") for queue in queues]
            )
        except ProfileLeaseConflict as exc:
            _active_profile_lease_owner = ""
            _active_profile_lease_keys = set()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _active_task_run_id = create_task_run(
            db_p,
            "scrape_favorites",
            total_items=len(favorite_ids),
            summary={
                "workers": worker_count,
                "scan_limit": req.scan_limit,
                "download_media": bool(req.download_media),
                "scan_direction": req.scan_direction,
                "account_mode": req.account_mode,
            },
        )
        _stop_requested.clear()
        _scrape_status.update({
            "is_running": True, "current_page": "", "posts_found": 0,
            "start_time": time.time(), "queue_total": len(favorite_ids),
            "queue_completed": 0, "current_favorite_id": 0, "new_posts": 0,
            "queue_successful": 0, "queue_failed": 0,
            "task_type": "favorites", "keyword": "", "error": "", "search_results": [],
            "workers": {
                queue["worker_id"]: {
                    "worker_id": queue["worker_id"],
                    "account_id": queue["account"].get("id") if queue.get("account") else None,
                    "account_label": queue["account_label"],
                    "queue_total": len(queue["favorite_ids"]), "queue_completed": 0,
                    "current_page": "", "current_favorite_id": 0, "posts_found": 0,
                    "new_posts": 0, "status": "Đang chờ", "error": queue.get("account_error", ""),
                } for queue in queues
            },
        })
        _favorite_worker_stop_events.clear()
        for queue in queues:
            _favorite_worker_stop_events[queue["worker_id"]] = threading.Event()
    _scraper_thread = threading.Thread(
        target=_run_favorite_parallel,
        args=(queues, req.max_concurrency, req.download_media),
        daemon=True,
    )
    _scraper_thread.start()
    if req.account_mode == "specific":
        account_label = (
            selected_account.get("label") or selected_account.get("username")
            or f"Account #{req.account_id}"
        )
    elif req.account_mode == "default":
        account_label = "Profile mặc định"
    elif req.account_mode == "auto":
        account_label = f"Tự chọn {worker_count} Account khả dụng"
    else:
        account_label = "Theo Account đã gán từng Page"
    return {
        "status": "success", "queued": len(favorite_ids),
        "account_label": account_label, "workers": worker_count,
    }


@router.post("/favorites/stop-worker")
def stop_favorite_worker(req: FavoriteWorkerStopRequest):
    """Stop one Account queue without interrupting other Account workers."""
    with _scrape_lock:
        if not _scrape_status["is_running"] or _scrape_status["task_type"] not in {"favorites", "quick_batch"}:
            raise HTTPException(status_code=409, detail="Không có hàng đợi Page đang chạy")
        stop_event = _favorite_worker_stop_events.get(req.worker_id)
        scraper = _active_favorite_scrapers.get(req.worker_id)
    if stop_event is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hàng đợi Account")
    stop_event.set()
    if scraper:
        try:
            scraper.stop()
        except Exception:
            pass
    _update_favorite_worker(req.worker_id, status="Đang dừng")
    log_to_web(f"Đã gửi lệnh dừng hàng đợi {req.worker_id}.", "WARNING")
    return {"status": "success", "message": "Đã gửi lệnh dừng hàng đợi Account"}


@router.post("/search/start")
def start_page_search(req: PageSearchRequest):
    """Start an authenticated Facebook Page discovery task."""
    global _active_task_run_id, _scraper_thread, _active_profile_lease_owner, _active_profile_lease_keys
    keyword = req.keyword.strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="Từ khóa không được để trống")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    accounts = get_all_accounts(db_p)
    account = None
    if req.account_mode == "specific":
        account = next((item for item in accounts if item.get("id") == req.account_id), None)
        if account is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy Account Chrome đã chọn")
        if not account.get("is_active", 1):
            raise HTTPException(status_code=422, detail="Account Chrome đang bị tắt")
    elif req.account_mode == "auto":
        account = next((item for item in accounts if item.get("is_active", 1)), None)
        if account is None:
            raise HTTPException(status_code=422, detail="Không có Account Chrome đang hoạt động")
    with _scrape_lock:
        if _scrape_status["is_running"]:
            raise HTTPException(status_code=409, detail="Một tác vụ Facebook khác đang chạy")
        _active_profile_lease_owner = f"page-search-{uuid4().hex[:8]}"
        try:
            _active_profile_lease_keys = acquire_profile_leases(_active_profile_lease_owner, [account])
        except ProfileLeaseConflict as exc:
            _active_profile_lease_owner = ""
            _active_profile_lease_keys = set()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        _active_task_run_id = create_task_run(
            db_p, "page_search", total_items=req.limit,
            summary={"account_mode": req.account_mode},
        )
        _stop_requested.clear()
        _scrape_status.update({
            "is_running": True, "current_page": "", "posts_found": 0,
            "start_time": time.time(), "queue_total": req.limit, "queue_completed": 0,
            "queue_successful": 0, "queue_failed": 0,
            "current_favorite_id": 0, "new_posts": 0, "task_type": "page_search",
            "keyword": keyword, "error": "", "search_results": [],
            "workers": {},
        })
    _scraper_thread = threading.Thread(
        target=_run_page_search,
        args=(keyword, req.limit, req.min_followers, req.sort_by, account), daemon=True,
    )
    _scraper_thread.start()
    return {"status": "success", "message": "Đã bắt đầu tìm Fanpage"}


@router.get("/search/results")
def get_page_search_results():
    """Return latest transient results enriched with the current favorite state."""
    with _scrape_lock:
        results = [dict(item) for item in _scrape_status["search_results"]]
        keyword = _scrape_status["keyword"]
        error = _scrape_status["error"]
    db_p = get_db_path(config.get("scraper_db_path", ""))
    favorites = {item["page_url"]: item for item in get_favorite_pages(db_p)}
    for item in results:
        favorite = favorites.get(item["page_url"])
        item["is_favorite"] = favorite is not None
        item["favorite_id"] = favorite["id"] if favorite else None
    return {"status": "success", "keyword": keyword, "error": error, "data": results}
