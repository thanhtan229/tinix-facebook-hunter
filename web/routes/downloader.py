from fastapi import APIRouter, HTTPException
from pydantic import Field
from typing import Optional
from core.downloader import DownloadOrchestrator
from core.db_storage import get_db_path, get_all_accounts
from utils import config
from web.ws_manager import progress_to_web, log_to_web
from web.models import ApiRequest

router = APIRouter(prefix="/api/download", tags=["Downloader"])

orchestrator = DownloadOrchestrator()


def download_is_running() -> bool:
    return bool(orchestrator.is_running)

# Setup callbacks to broadcast progress
def _on_progress_update(current: int, total: int, speed: str = "", status: str = ""):
    progress_to_web("download", current, total, speed, status)

def _on_stats_update(stats):
    progress_to_web(
        "download",
        stats.completed_posts,
        stats.total_posts,
        f"{stats.completed_posts}/{stats.total_posts}",
        "downloading"
    )

def _on_all_complete(success: bool, msg: str):
    log_to_web(f"Hoàn thành tải xuống: {msg}", "OK" if success else "WARNING")
    stats = orchestrator.stats
    if success:
        status = "completed"
    elif stats.success_posts > 0:
        status = "partial"
    else:
        status = "failed"
    progress_to_web(
        "download", stats.completed_posts, stats.total_posts, msg, status
    )

orchestrator.set_callbacks(
    on_progress=_on_progress_update,
    on_stats_update=_on_stats_update,
    on_all_complete=_on_all_complete
)

class DownloadStartRequest(ApiRequest):
    urls: str = Field(min_length=1, max_length=500_000)
    output_dir: Optional[str] = Field(default=None, max_length=4_096)
    max_threads: Optional[int] = Field(default=None, ge=1, le=20)
    cookies: Optional[str] = Field(default=None, max_length=200_000)
    use_accounts: Optional[bool] = False

@router.post("/start")
def start_download(req: DownloadStartRequest):
    """Start a media download task."""
    if orchestrator.is_running:
        raise HTTPException(status_code=400, detail="Tiến trình tải đang chạy rồi!")

    if not req.urls.strip():
        raise HTTPException(status_code=422, detail="Danh sách URL không được để trống")

    out_dir = req.output_dir or config.get("output_dir", ".")
    threads = req.max_threads or config.get("max_threads", 4)
    if not isinstance(threads, int) or not 1 <= threads <= 20:
        raise HTTPException(status_code=422, detail="Số luồng phải nằm trong khoảng 1-20")
    cookies_str = req.cookies or config.get("saved_cookies", "")

    if req.use_accounts:
        db_p = get_db_path(config.get("scraper_db_path", ""))
        accounts = [a for a in get_all_accounts(db_p) if a.get("is_active")]
        if not accounts:
            raise HTTPException(status_code=400, detail="Không có tài khoản nào sẵn sàng/active!")
        orchestrator.start_with_accounts(
            urls_text=req.urls,
            accounts=accounts,
            output_dir=out_dir,
            max_threads=threads
        )
    else:
        orchestrator.start(
            urls_text=req.urls,
            cookie_string=cookies_str,
            output_dir=out_dir,
            max_threads=threads
        )

    log_to_web(f"Bắt đầu tác vụ tải xuống ({threads} luồng)...", "INFO")
    return {"status": "success", "message": "Đã bắt đầu tải xuống"}

@router.post("/stop")
def stop_download():
    """Stop active download."""
    if not orchestrator.is_running:
        return {"status": "success", "message": "Không có tác vụ nào đang chạy"}
    orchestrator.stop()
    log_to_web("Đã dừng tác vụ tải xuống.", "WARNING")
    return {"status": "success", "message": "Đã dừng tải xuống"}

@router.post("/pause")
def pause_download():
    """Pause active download."""
    orchestrator.pause()
    log_to_web("Tạm dừng tác vụ tải xuống.", "WARNING")
    return {"status": "success", "message": "Đã tạm dừng"}

@router.post("/resume")
def resume_download():
    """Resume active download."""
    orchestrator.resume()
    log_to_web("Tiếp tục tác vụ tải xuống.", "INFO")
    return {"status": "success", "message": "Đã tiếp tục"}

@router.get("/status")
def get_download_status():
    """Get active download status and counters."""
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
            "eta_seconds": round(st.eta_seconds, 1)
        }
    }
