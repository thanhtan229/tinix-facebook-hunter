import threading
import time
from fastapi import APIRouter, HTTPException
from pydantic import Field, HttpUrl
from typing import List, Optional
from core.page_scraper import PageScraper
from core.db_storage import (
    delete_favorite_page,
    finish_favorite_scan,
    get_all_accounts,
    get_favorite_page,
    get_favorite_pages,
    get_db_path,
    get_page_post_ids,
    mark_favorite_scan_started,
    reset_favorite_cursor,
    save_favorite_page,
    save_posts,
)
from utils import config, logger
from web.ws_manager import log_to_web, progress_to_web
from web.models import ApiRequest

router = APIRouter(prefix="/api/scrape", tags=["Scraper"])

_scraper_thread: Optional[threading.Thread] = None
_active_scraper: Optional[PageScraper] = None
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
    "current_favorite_id": 0,
    "new_posts": 0,
}


def scrape_is_running() -> bool:
    with _scrape_lock:
        return bool(_scrape_status["is_running"])

class ScrapeStartRequest(ApiRequest):
    page_url: HttpUrl
    limit: Optional[int] = Field(default=50, ge=1, le=10_000)
    mode: Optional[str] = Field(default="All", pattern="^(All|New Posts)$")
    account_id: Optional[int] = Field(default=None, gt=0)
    download_media: Optional[bool] = False


class FavoriteSaveRequest(ApiRequest):
    page_url: HttpUrl
    page_name: Optional[str] = Field(default="", max_length=300)
    account_id: Optional[int] = Field(default=None, gt=0)
    scan_limit: int = Field(default=100, ge=5, le=2000)


class FavoriteActionRequest(ApiRequest):
    favorite_id: int = Field(gt=0)


class FavoriteScanRequest(ApiRequest):
    favorite_ids: List[int] = Field(default_factory=list, max_length=500)

def _run_scrape_worker(page_url: str, limit: int, mode: str, account: Optional[dict], download_media: bool):
    global _active_scraper, _scrape_status

    db_p = get_db_path(config.get("scraper_db_path", ""))
    log_to_web(f"Khởi động trình duyệt quét Page: {page_url} (tối đa {limit} bài)...", "INFO")

    try:
        scraper = PageScraper(account=account)
        with _scrape_lock:
            _active_scraper = scraper

        if not scraper.start():
            log_to_web("Không thể khởi động Chrome cho tác vụ quét Page.", "ERROR")
            return

        def _on_progress(count: int, msg: str = ""):
            with _scrape_lock:
                _scrape_status["posts_found"] = count
            progress_to_web("scraper", count, limit, f"{count}/{limit}", "scraping")
            if msg:
                log_to_web(msg, "INFO")

        known_ids = set()
        if mode == "New Posts":
            known_ids = set(get_page_post_ids(db_p, page_url))

        posts = scraper.scrape_page(
            page_url=page_url,
            max_posts=limit,
            on_progress=_on_progress,
            known_post_ids=known_ids if mode == "New Posts" else None,
            stop_post_ids=known_ids if mode == "New Posts" else None,
        )

        if posts:
            page_name = posts[0].page_name if posts else page_url
            saved_count = save_posts(
                db_path=db_p,
                page_name=page_name,
                page_url=page_url,
                posts=posts,
                follower_count=getattr(scraper, "last_follower_count", 0)
            )
            log_to_web(f"✅ Đã quét xong {len(posts)} bài viết! Đã lưu {saved_count} bài vào cơ sở dữ liệu.", "OK")
        else:
            log_to_web("Không tìm thấy bài viết nào hoặc quá trình bị hủy.", "WARNING")

    except Exception as e:
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
        progress_to_web("scraper", 100, 100, "", "completed")


def _run_favorite_queue(favorite_ids: List[int]) -> None:
    """Scan favorite pages sequentially so only one Chrome profile runs at a time."""
    global _active_scraper, _scrape_status
    db_p = get_db_path(config.get("scraper_db_path", ""))
    total_new = 0
    try:
        for position, favorite_id in enumerate(favorite_ids, start=1):
            if _stop_requested.is_set():
                break
            favorite = get_favorite_page(db_p, favorite_id)
            if not favorite:
                continue

            with _scrape_lock:
                _scrape_status.update({
                    "current_page": favorite["page_url"],
                    "current_favorite_id": favorite_id,
                    "posts_found": 0,
                })
            mark_favorite_scan_started(db_p, favorite_id)
            log_to_web(
                f"⭐ [{position}/{len(favorite_ids)}] Quét bài mới: {favorite['page_name'] or favorite['page_url']}",
                "INFO",
            )

            account = None
            if favorite.get("account_id"):
                account = next(
                    (item for item in get_all_accounts(db_p) if item.get("id") == favorite["account_id"]),
                    None,
                )
                if account is None:
                    finish_favorite_scan(
                        db_p, favorite_id, status="Lỗi", new_posts=0,
                        error="Không tìm thấy account Chrome đã gán",
                    )
                    with _scrape_lock:
                        _scrape_status["queue_completed"] = position
                    continue

            scraper = PageScraper(account=account)
            with _scrape_lock:
                _active_scraper = scraper
            try:
                if not scraper.start():
                    finish_favorite_scan(
                        db_p, favorite_id, status="Lỗi", new_posts=0,
                        error="Không thể khởi động Chrome",
                    )
                    continue

                scan_limit = int(favorite["scan_limit"])
                queue_position = position
                queue_total = len(favorite_ids)

                def _on_progress(
                    count: int,
                    msg: str = "",
                    _scan_limit: int = scan_limit,
                    _queue_position: int = queue_position,
                    _queue_total: int = queue_total,
                ):
                    with _scrape_lock:
                        _scrape_status["posts_found"] = count
                    progress_to_web(
                        "scraper", count, _scan_limit,
                        f"{_queue_position}/{_queue_total} · {msg or count}", "scraping",
                    )

                known_ids = set(get_page_post_ids(db_p, favorite["page_url"]))
                cursor_ids = set(favorite.get("cursor_post_ids") or [])
                posts = scraper.scrape_page(
                    page_url=favorite["page_url"],
                    max_posts=scan_limit,
                    on_progress=_on_progress,
                    known_post_ids=known_ids,
                    stop_post_ids=cursor_ids,
                )
                page_name = (
                    posts[0].page_name if posts else favorite.get("page_name") or favorite["page_url"]
                )
                saved_count = save_posts(
                    db_path=db_p,
                    page_name=page_name,
                    page_url=favorite["page_url"],
                    posts=posts,
                    follower_count=getattr(scraper, "last_follower_count", 0),
                ) if posts else 0
                total_new += saved_count
                observed_ids = list(dict.fromkeys(scraper.last_observed_post_ids))
                reason = scraper.last_scan_stop_reason
                initial_scan = not cursor_ids
                complete = initial_scan or scraper.last_scan_complete

                if _stop_requested.is_set() or reason == "stopped":
                    finish_favorite_scan(
                        db_p, favorite_id, status="Đã dừng", new_posts=saved_count,
                        error="Người dùng dừng hàng đợi", page_name=page_name,
                    )
                elif complete and observed_ids:
                    finish_favorite_scan(
                        db_p, favorite_id, status="Thành công", new_posts=saved_count,
                        page_name=page_name, cursor_post_ids=observed_ids[:20], successful=True,
                    )
                    log_to_web(f"✅ {page_name}: {saved_count} bài mới", "OK")
                elif complete:
                    finish_favorite_scan(
                        db_p, favorite_id, status="Không có dữ liệu", new_posts=0,
                        error="Không lấy được mốc bài viết", page_name=page_name,
                    )
                else:
                    detail = (
                        "Đã đạt giới hạn trước khi gặp mốc cũ; mốc quét được giữ nguyên"
                        if reason == "limit" else "Lần quét chưa hoàn tất; mốc quét được giữ nguyên"
                    )
                    finish_favorite_scan(
                        db_p, favorite_id, status="Chưa hoàn tất", new_posts=saved_count,
                        error=detail, page_name=page_name,
                    )
                    log_to_web(f"⚠ {page_name}: {detail}", "WARNING")
            except Exception as exc:
                logger.exception("Lỗi quét Fanpage yêu thích", exc)
                finish_favorite_scan(
                    db_p, favorite_id, status="Lỗi", new_posts=0, error=str(exc)[:500],
                )
            finally:
                try:
                    scraper.stop()
                except Exception:
                    pass
                with _scrape_lock:
                    _active_scraper = None
                    _scrape_status["queue_completed"] = position
                    _scrape_status["new_posts"] = total_new
    finally:
        with _scrape_lock:
            _scrape_status["is_running"] = False
            _scrape_status["current_favorite_id"] = 0
            _active_scraper = None
        progress_to_web("scraper", 100, 100, "", "completed")
        log_to_web(f"Hoàn tất hàng đợi yêu thích: {total_new} bài mới.", "OK")

@router.post("/start")
def start_scrape(req: ScrapeStartRequest):
    """Start page scraper task."""
    global _scraper_thread
    page_url = str(req.page_url)
    limit = req.limit or 50
    if not page_url:
        raise HTTPException(status_code=422, detail="URL fanpage không được để trống")
    if not 1 <= limit <= 2000:
        raise HTTPException(status_code=422, detail="Giới hạn bài viết phải nằm trong khoảng 1-2000")

    with _scrape_lock:
        if _scrape_status["is_running"]:
            raise HTTPException(status_code=400, detail="Tác vụ quét Page đang chạy rồi!")
        _scrape_status.update({
            "is_running": True,
            "current_page": page_url,
            "posts_found": 0,
            "start_time": time.time(),
            "queue_total": 1,
            "queue_completed": 0,
            "current_favorite_id": 0,
            "new_posts": 0,
        })
        _stop_requested.clear()

    db_p = get_db_path(config.get("scraper_db_path", ""))
    account = None
    if req.account_id:
        all_acc = get_all_accounts(db_p)
        account = next((a for a in all_acc if a.get("id") == req.account_id), None)
        if account is None:
            with _scrape_lock:
                _scrape_status["is_running"] = False
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản đã chọn")

    _scraper_thread = threading.Thread(
        target=_run_scrape_worker,
        args=(page_url, limit, req.mode or "All", account, req.download_media or False),
        daemon=True
    )
    _scraper_thread.start()
    return {"status": "success", "message": "Đã bắt đầu tác vụ quét Page"}

@router.post("/stop")
def stop_scrape():
    """Stop active page scraper."""
    global _active_scraper
    with _scrape_lock:
        scraper = _active_scraper
        is_running = _scrape_status["is_running"]
    _stop_requested.set()
    if scraper:
        scraper.stop()
        log_to_web("Đã gửi lệnh dừng quét Page.", "WARNING")
        return {"status": "success", "message": "Đã dừng quét"}
    if is_running:
        return {"status": "success", "message": "Tác vụ đang khởi động; lệnh dừng sẽ khả dụng sau ít giây"}
    return {"status": "success", "message": "Không có tác vụ nào đang chạy"}

@router.get("/status")
def get_scrape_status():
    """Get active scrape status."""
    with _scrape_lock:
        snapshot = dict(_scrape_status)
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
        }
    }


@router.get("/favorites")
def list_favorite_pages():
    db_p = get_db_path(config.get("scraper_db_path", ""))
    return {"status": "success", "data": get_favorite_pages(db_p)}


@router.post("/favorites/save")
def save_favorite_page_endpoint(req: FavoriteSaveRequest):
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if req.account_id and not any(
        account.get("id") == req.account_id for account in get_all_accounts(db_p)
    ):
        raise HTTPException(status_code=404, detail="Không tìm thấy account Chrome")
    favorite_id = save_favorite_page(
        db_p, str(req.page_url), req.page_name or "", req.account_id, req.scan_limit
    )
    return {"status": "success", "id": favorite_id}


@router.post("/favorites/delete")
def delete_favorite_page_endpoint(req: FavoriteActionRequest):
    if scrape_is_running():
        raise HTTPException(status_code=409, detail="Hãy dừng tác vụ quét trước")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if not delete_favorite_page(db_p, req.favorite_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy Fanpage yêu thích")
    return {"status": "success"}


@router.post("/favorites/reset-cursor")
def reset_favorite_cursor_endpoint(req: FavoriteActionRequest):
    if scrape_is_running():
        raise HTTPException(status_code=409, detail="Hãy dừng tác vụ quét trước")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if not reset_favorite_cursor(db_p, req.favorite_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy Fanpage yêu thích")
    return {"status": "success"}


@router.post("/favorites/scan")
def scan_favorite_pages(req: FavoriteScanRequest):
    global _scraper_thread
    db_p = get_db_path(config.get("scraper_db_path", ""))
    available = {item["id"]: item for item in get_favorite_pages(db_p, active_only=True)}
    requested_ids = list(dict.fromkeys(int(value) for value in req.favorite_ids))
    favorite_ids = requested_ids or list(available)
    invalid = [value for value in favorite_ids if value not in available]
    if invalid:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy Fanpage yêu thích #{invalid[0]}")
    if not favorite_ids:
        raise HTTPException(status_code=422, detail="Chưa có Fanpage yêu thích để quét")
    with _scrape_lock:
        if _scrape_status["is_running"]:
            raise HTTPException(status_code=409, detail="Tác vụ quét Page đang chạy")
        _stop_requested.clear()
        _scrape_status.update({
            "is_running": True, "current_page": "", "posts_found": 0,
            "start_time": time.time(), "queue_total": len(favorite_ids),
            "queue_completed": 0, "current_favorite_id": 0, "new_posts": 0,
        })
    _scraper_thread = threading.Thread(
        target=_run_favorite_queue, args=(favorite_ids,), daemon=True
    )
    _scraper_thread.start()
    return {"status": "success", "queued": len(favorite_ids)}
