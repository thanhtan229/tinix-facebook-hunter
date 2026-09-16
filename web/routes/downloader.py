from __future__ import annotations

import threading
import time
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import Field

from core.cookie_handler import parse_cookie_string, validate_cookies
from core.db_storage import (
    cancel_pending_download_queue_batches,
    claim_next_download_queue_batch,
    create_task_run,
    enqueue_download_queue_batch,
    finish_task_run,
    get_all_accounts,
    get_db_path,
    get_download_queue_status,
    set_download_queue_batch_status,
)
from core.downloader import DownloadOrchestrator
from core.profile_lease import ProfileLeaseConflict, acquire_profile_leases, release_profile_leases
from core.url_handler import parse_urls
from utils import config
from web.models import ApiRequest
from web.ws_manager import account_status_to_web, download_item_to_web, log_to_web, progress_to_web

router = APIRouter(prefix="/api/download", tags=["Downloader"])

orchestrator = DownloadOrchestrator()
_download_start_lock = threading.RLock()
_active_task_run_id = 0
_active_queue_batch_id = 0
_download_stop_requested = False
_stop_all_requested = False
_shutdown_requested = False
_active_profile_lease_owner = ""
_active_profile_lease_keys: set[str] = set()
_pending_auto_download_retry: Optional[threading.Timer] = None


def _db_path() -> str:
    return get_db_path(config.get("scraper_db_path", ""))


def download_is_running() -> bool:
    return bool(orchestrator.is_running)


def download_has_active_or_pending_work() -> bool:
    """Return true for a running download or a persisted batch awaiting start."""
    status = get_download_queue_status(_db_path())
    return bool(orchestrator.is_running or status["batches"] or status["running_batches"])


def _on_progress_update(current: int, total: int, speed: str = "", status: str = "") -> None:
    progress_to_web("download", current, total, speed, status)


def _on_stats_update(stats) -> None:
    progress_to_web(
        "download", stats.completed_posts, stats.total_posts,
        f"{stats.completed_posts}/{stats.total_posts}", "downloading",
    )


def _on_account_status(payload) -> None:
    account_status_to_web(payload)


def _on_download_item(payload) -> None:
    download_item_to_web(payload)


def _finish_active_queue_batch(status: str, message: str) -> None:
    global _active_queue_batch_id
    if not _active_queue_batch_id:
        return
    if _shutdown_requested:
        set_download_queue_batch_status(
            _db_path(), _active_queue_batch_id, "queued",
            error_message="Ứng dụng đang dừng; batch sẽ tiếp tục ở lần khởi động sau.",
        )
    else:
        queue_status = "completed" if status in {"completed", "partial"} else (
            "cancelled" if status == "stopped" else "failed"
        )
        set_download_queue_batch_status(
            _db_path(), _active_queue_batch_id, queue_status,
            error_message="" if queue_status == "completed" else message,
            purge_payload=True,
        )
    _active_queue_batch_id = 0


def _on_all_complete(success: bool, msg: str) -> None:
    global _active_task_run_id, _download_stop_requested
    log_to_web(f"Hoàn thành tải xuống: {msg}", "OK" if success else "WARNING")
    stats = orchestrator.stats
    status = "completed" if success else ("partial" if stats.success_posts > 0 else "failed")
    if _download_stop_requested:
        status = "stopped"
    progress_to_web("download", stats.completed_posts, stats.total_posts, msg, status)
    _finish_active_queue_batch(status, msg)
    if _active_task_run_id:
        finish_task_run(
            _db_path(), _active_task_run_id, status,
            completed_items=stats.completed_posts,
            successful_items=stats.success_posts,
            failed_items=stats.failed_posts,
            error_message="" if status == "completed" else msg,
        )
        _active_task_run_id = 0
    _download_stop_requested = False


def _release_active_profile_leases() -> None:
    global _active_profile_lease_owner, _active_profile_lease_keys
    if _active_profile_lease_keys:
        release_profile_leases(_active_profile_lease_owner, _active_profile_lease_keys)
    _active_profile_lease_owner = ""
    _active_profile_lease_keys = set()


def _on_download_idle() -> None:
    """Release browser ownership before handing FIFO work to the next batch."""
    with _download_start_lock:
        _release_active_profile_leases()
        if not _stop_all_requested and not _shutdown_requested:
            _start_pending_auto_download()


orchestrator.set_callbacks(
    on_progress=_on_progress_update,
    on_stats_update=_on_stats_update,
    on_all_complete=_on_all_complete,
    on_account_status=_on_account_status,
    on_download_item=_on_download_item,
    on_idle=_on_download_idle,
)


class DownloadStartRequest(ApiRequest):
    urls: str = Field(min_length=1, max_length=500_000)
    output_dir: Optional[str] = Field(default=None, max_length=4_096)
    max_threads: Optional[int] = Field(default=None, ge=1, le=20)
    cookies: Optional[str] = Field(default=None, max_length=200_000)
    use_accounts: Optional[bool] = None
    account_ids: List[int] = Field(default_factory=list, max_length=20)


def _active_accounts_for_ids(db_path: str, account_ids: list[int]) -> list[dict]:
    selected = {int(value or 0) for value in account_ids if int(value or 0) > 0}
    accounts = [
        account for account in get_all_accounts(db_path)
        if account.get("is_active", 1) and (not selected or int(account.get("id") or 0) in selected)
    ]
    return sorted(accounts, key=lambda account: str(account.get("preflight_status") or "") != "READY")


def _selected_download_accounts(db_path: str, account_ids: list[int]) -> list[dict]:
    """Return requested active accounts, rejecting stale or inactive selections."""
    selected = {int(value or 0) for value in account_ids if int(value or 0) > 0}
    if not selected:
        return _active_accounts_for_ids(db_path, [])
    all_accounts = {int(account.get("id") or 0): account for account in get_all_accounts(db_path)}
    invalid = sorted(account_id for account_id in selected if not all_accounts.get(account_id, {}).get("is_active"))
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Account đã chọn không tồn tại hoặc không active: {', '.join(map(str, invalid))}",
        )
    return _active_accounts_for_ids(db_path, list(selected))


def _start_with_accounts_or_cookie(
    urls: list[str], accounts: list[dict], *, output_dir: str, max_threads: int, cookie_string: str = "",
) -> bool:
    """Start once and return whether the orchestrator accepted the run.

    Older test doubles may not return a value, so retain the running-state
    fallback only for that compatibility case. Production orchestrators return
    an explicit boolean.
    """
    if accounts:
        started = orchestrator.start_with_accounts(
            urls_text="\n".join(urls), accounts=accounts, output_dir=output_dir, max_threads=max_threads,
        )
    else:
        started = orchestrator.start(
            urls_text="\n".join(urls), cookie_string=cookie_string,
            output_dir=output_dir, max_threads=max_threads,
        )
    return bool(orchestrator.is_running) if started is None else bool(started)


def _start_claimed_auto_batch(batch: dict) -> bool:
    """Start a durable queue batch that has atomically moved to ``starting``."""
    global _active_task_run_id, _active_queue_batch_id, _download_stop_requested
    global _active_profile_lease_owner, _active_profile_lease_keys
    urls = list(batch.get("urls") or [])
    if not urls:
        set_download_queue_batch_status(_db_path(), int(batch["id"]), "failed", error_message="Batch không có URL hợp lệ", purge_payload=True)
        return False
    db_path = _db_path()
    accounts = _active_accounts_for_ids(db_path, list(batch.get("account_ids") or []))
    owner = f"auto-download-{uuid4().hex[:8]}"
    try:
        lease_keys = acquire_profile_leases(owner, accounts) if accounts else set()
    except ProfileLeaseConflict as exc:
        set_download_queue_batch_status(db_path, int(batch["id"]), "queued", error_message=str(exc))
        _schedule_pending_auto_download_retry()
        return False

    _download_stop_requested = False
    _active_profile_lease_owner = owner
    _active_profile_lease_keys = lease_keys
    _active_queue_batch_id = int(batch["id"])
    _active_task_run_id = create_task_run(
        db_path, "download", total_items=len(urls),
        summary={"source": "auto", "use_accounts": bool(accounts), "workers": min(len(accounts), int(config.get("max_threads", 3) or 3))},
    )
    if not set_download_queue_batch_status(
        db_path, _active_queue_batch_id, "running", expected_statuses={"starting"},
    ):
        finish_task_run(
            db_path, _active_task_run_id, "stopped",
            error_message="Batch đã bị hủy trước khi khởi động",
        )
        _active_task_run_id = 0
        _active_queue_batch_id = 0
        _release_active_profile_leases()
        return False
    try:
        started = _start_with_accounts_or_cookie(
            urls, accounts, output_dir=config.get("output_dir", ".") or ".",
            max_threads=max(1, min(int(config.get("max_threads", 3) or 3), 20)),
            cookie_string=config.get("saved_cookies", ""),
        )
    except Exception as exc:
        set_download_queue_batch_status(db_path, _active_queue_batch_id, "failed", error_message="Không thể khởi động Auto Download", purge_payload=True)
        if _active_task_run_id:
            finish_task_run(db_path, _active_task_run_id, "failed", error_message="Không thể khởi động Auto Download")
        _active_task_run_id = 0
        _active_queue_batch_id = 0
        _release_active_profile_leases()
        log_to_web(f"Auto Download lỗi: {str(exc)[:160]}", "WARNING")
        return False
    if not started:
        return False
    return True


def _start_pending_auto_download() -> None:
    """Claim and start at most one persisted batch once the downloader is idle."""
    if orchestrator.is_running or _stop_all_requested or _shutdown_requested:
        return
    batch = claim_next_download_queue_batch(_db_path())
    if batch is None:
        return
    if _start_claimed_auto_batch(batch):
        log_to_web(f"⬇ Auto Download bắt đầu {batch['item_count']} bài đang chờ.", "OK")


def _schedule_pending_auto_download_retry() -> None:
    """Retry profile-blocked work while preserving FIFO order in SQLite."""
    global _pending_auto_download_retry
    if _shutdown_requested or _stop_all_requested:
        return
    if _pending_auto_download_retry and _pending_auto_download_retry.is_alive():
        return
    timer = threading.Timer(5.0, _retry_pending_auto_download)
    timer.daemon = True
    _pending_auto_download_retry = timer
    timer.start()


def _retry_pending_auto_download() -> None:
    global _pending_auto_download_retry
    with _download_start_lock:
        _pending_auto_download_retry = None
        _start_pending_auto_download()


def enqueue_auto_download(urls: list[str], account_ids: list[int]) -> bool:
    """Persist scan output first, then let the single coordinator start it."""
    batch_id = enqueue_download_queue_batch(_db_path(), urls, account_ids, source="auto")
    if not batch_id:
        return False
    global _stop_all_requested
    with _download_start_lock:
        _stop_all_requested = False
        _start_pending_auto_download()
    return True


@router.post("/start")
def start_download(req: DownloadStartRequest):
    """Start a manual download through the same serialized coordinator."""
    global _active_task_run_id, _download_stop_requested, _stop_all_requested, _shutdown_requested
    global _active_profile_lease_owner, _active_profile_lease_keys
    urls = parse_urls(req.urls)
    if not urls:
        raise HTTPException(status_code=422, detail="Không tìm thấy URL Facebook hợp lệ")
    out_dir = req.output_dir or config.get("output_dir", ".")
    threads = req.max_threads or config.get("max_threads", 3)
    if not isinstance(threads, int) or not 1 <= threads <= 20:
        raise HTTPException(status_code=422, detail="Số luồng phải nằm trong khoảng 1-20")
    cookies_str = req.cookies or config.get("saved_cookies", "")
    db_path = _db_path()

    with _download_start_lock:
        if orchestrator.is_running:
            raise HTTPException(status_code=409, detail="Tiến trình tải đang chạy rồi")
        _stop_all_requested = False
        use_accounts = config.get("download_use_accounts", True) if req.use_accounts is None else req.use_accounts
        accounts = (
            _selected_download_accounts(db_path, req.account_ids)
            if use_accounts else _active_accounts_for_ids(db_path, req.account_ids)
        )
        if not use_accounts:
            is_valid, _ = validate_cookies(parse_cookie_string(cookies_str))
            if not is_valid:
                if accounts:
                    use_accounts = True
                    log_to_web("Cookies cấu hình trống hoặc hết hạn, tự động dùng Facebook Account có sẵn...", "INFO")
                else:
                    raise HTTPException(status_code=400, detail="Cookies cấu hình trống hoặc không hợp lệ")
        if use_accounts and not accounts:
            raise HTTPException(status_code=400, detail="Không có tài khoản nào sẵn sàng/active!")

        owner, lease_keys = "", set()
        if use_accounts:
            owner = f"download-{uuid4().hex[:8]}"
            try:
                lease_keys = acquire_profile_leases(owner, accounts)
            except ProfileLeaseConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        _download_stop_requested = False
        _active_profile_lease_owner = owner
        _active_profile_lease_keys = lease_keys
        _active_task_run_id = create_task_run(
            db_path, "download", total_items=len(urls),
            summary={
                "source": "manual", "use_accounts": bool(use_accounts), "workers": int(threads),
                "account_mode": "selected" if req.account_ids else "auto",
            },
        )
        try:
            started = _start_with_accounts_or_cookie(
                urls, accounts if use_accounts else [], output_dir=out_dir,
                max_threads=threads, cookie_string=cookies_str,
            )
        except Exception:
            if _active_task_run_id:
                finish_task_run(db_path, _active_task_run_id, "failed", error_message="Không thể khởi động tác vụ tải")
            _active_task_run_id = 0
            _release_active_profile_leases()
            raise
        if not started:
            raise HTTPException(status_code=409, detail="Không thể khởi động tác vụ tải")
    effective_threads = getattr(orchestrator, "_max_threads", threads)
    log_to_web(f"Bắt đầu tác vụ tải xuống ({effective_threads} luồng hiệu lực)...", "INFO")
    return {"status": "success", "message": "Đã bắt đầu tải xuống", "state": "started"}


@router.post("/stop")
def stop_download():
    """Stop only the current batch; durable queued work remains available."""
    global _download_stop_requested
    if not orchestrator.is_running:
        return {"status": "success", "message": "Không có tác vụ nào đang chạy"}
    _download_stop_requested = True
    orchestrator.stop()
    log_to_web("Đã dừng tác vụ tải hiện tại; các batch chờ vẫn được giữ lại.", "WARNING")
    return {"status": "success", "message": "Đã dừng tác vụ tải hiện tại"}


@router.post("/stop-all")
def stop_all_downloads():
    """Stop the current batch and cancel every queued Auto Download batch."""
    global _download_stop_requested, _stop_all_requested
    with _download_start_lock:
        _stop_all_requested = True
        cancelled = cancel_pending_download_queue_batches(_db_path())
        if orchestrator.is_running:
            _download_stop_requested = True
            orchestrator.stop()
    log_to_web(f"Đã dừng toàn bộ download và hủy {cancelled} batch đang chờ.", "WARNING")
    return {"status": "success", "cancelled_batches": cancelled}


@router.post("/queue/clear")
def clear_pending_download_queue():
    """Cancel only batches that have not started."""
    with _download_start_lock:
        cancelled = cancel_pending_download_queue_batches(_db_path())
    log_to_web(f"Đã hủy {cancelled} batch Auto Download đang chờ.", "WARNING")
    return {"status": "success", "cancelled_batches": cancelled}


@router.post("/pause")
def pause_download():
    orchestrator.pause()
    log_to_web("Tạm dừng tác vụ tải xuống.", "WARNING")
    return {"status": "success", "message": "Đã tạm dừng"}


@router.post("/resume")
def resume_download():
    orchestrator.resume()
    log_to_web("Tiếp tục tác vụ tải xuống.", "INFO")
    return {"status": "success", "message": "Đã tiếp tục"}


@router.get("/status")
def get_download_status():
    st = orchestrator.stats
    return {
        "status": "success",
        "data": {
            "is_running": orchestrator.is_running,
            "is_paused": orchestrator.is_paused,
            "total_posts": st.total_posts,
            "completed_posts": st.completed_posts,
            "success_posts": st.success_posts,
            "failed_posts": st.failed_posts,
            "progress_fraction": st.progress_fraction,
            "elapsed_seconds": round(st.elapsed_seconds, 1),
            "eta_seconds": round(st.eta_seconds, 1),
            "retrying_posts": orchestrator._retrying_posts,
            "safety_pause_reason": orchestrator.safety_pause_reason,
            "accounts": list(orchestrator.account_statuses.values()),
            "pending_auto_downloads": get_download_queue_status(_db_path()),
        },
    }


def start_pending_downloads_after_startup() -> None:
    """Schedule persisted work after FastAPI has bound its event loop."""
    global _shutdown_requested, _stop_all_requested
    with _download_start_lock:
        _shutdown_requested = False
        _stop_all_requested = False
        _start_pending_auto_download()


def shutdown_downloader(timeout_seconds: float = 5.0) -> None:
    """Stop safely without losing persisted queue payloads or profile leases."""
    global _shutdown_requested, _pending_auto_download_retry
    with _download_start_lock:
        _shutdown_requested = True
        if _pending_auto_download_retry:
            _pending_auto_download_retry.cancel()
            _pending_auto_download_retry = None
        if orchestrator.is_running:
            orchestrator.stop()
        else:
            _release_active_profile_leases()
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while orchestrator.is_running and time.monotonic() < deadline:
        time.sleep(0.05)
    if orchestrator.is_running:
        log_to_web("Download chưa dừng kịp khi đóng app; batch sẽ được khôi phục ở lần mở sau.", "WARNING")
