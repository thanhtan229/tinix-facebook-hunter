import os
from fastapi import APIRouter, HTTPException, Query
from pydantic import Field
from typing import Optional, List, Dict, Any
from core.content_scanner import scan_main_folder, count_media_in_folder
from core.db_storage import get_db_path
from core.db_storage import delete_history_records, get_schedule_history_filtered, retry_failed_posts
from core.post_queue import PostQueueRunner
from core.schedule_service import (
    ScheduleValidationError,
    build_schedule,
    persist_reviewed_schedule,
)
from utils import config
from web.ws_manager import log_to_web, progress_to_web
from web.security import is_allowed_content_path, register_media_root
from web.models import ApiRequest

router = APIRouter(prefix="/api/poster", tags=["Social Poster"])
queue_runner = PostQueueRunner()

class ScanFolderRequest(ApiRequest):
    folder_path: str = Field(min_length=1, max_length=4_096)

class UpdateCaptionRequest(ApiRequest):
    folder_path: str = Field(min_length=1, max_length=4_096)
    caption: str = Field(max_length=100_000)

class GenerateScheduleRequest(ApiRequest):
    items: List[Dict[str, Any]] = Field(min_length=1, max_length=5_000)
    target_pages: List[Any] = Field(min_length=1, max_length=5_000)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    time_slots: List[str] = Field(default_factory=lambda: ["08:00", "20:00"], min_length=1, max_length=48)
    order_mode: Optional[str] = Field(default="Thứ tự", max_length=100)


class PersistScheduleRequest(ApiRequest):
    schedules: List[Dict[str, Any]] = Field(min_length=1, max_length=5_000)


class JobIdsRequest(ApiRequest):
    history_ids: List[int] = Field(default_factory=list, max_length=5_000)


class RunQueueRequest(JobIdsRequest):
    brand_name: Optional[str] = Field(default="", max_length=200)
    cta_enabled: Optional[bool] = False
    share_to_story: Optional[bool] = True
    headless: Optional[bool] = False

@router.post("/scan-folder")
def scan_folder_endpoint(req: ScanFolderRequest):
    """Scan a content folder for post subfolders and their media/captions."""
    if not os.path.exists(req.folder_path):
        raise HTTPException(status_code=400, detail=f"Thư mục không tồn tại: {req.folder_path}")

    try:
        register_media_root(req.folder_path)
        items = scan_main_folder(req.folder_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Enrich each item with media list and counts
    enriched = []
    for idx, it in enumerate(items):
        fpath = it["folder_path"]
        img_count, vid_count = count_media_in_folder(fpath)
        media_files = []
        for file in sorted(os.listdir(fpath)):
            ext = os.path.splitext(file)[1].lower()
            if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".webm"]:
                media_files.append({
                    "name": file,
                    "rel_path": f"/media-preview?path={os.path.abspath(os.path.join(fpath, file))}",
                    "is_video": ext in [".mp4", ".mov", ".webm"]
                })
        enriched.append({
            "id": idx + 1,
            "folder_name": it["folder_name"],
            "folder_path": it["folder_path"],
            "caption": it.get("caption", ""),
            "img_count": img_count,
            "vid_count": vid_count,
            "media_files": media_files
        })

    log_to_web(f"Đã quét thư mục '{req.folder_path}': tìm thấy {len(enriched)} bài viết.", "OK")
    return {
        "status": "success",
        "total": len(enriched),
        "data": enriched
    }

@router.post("/update-caption")
def update_caption_endpoint(req: UpdateCaptionRequest):
    """Save updated caption into the folder's caption.txt file."""
    if not os.path.exists(req.folder_path) or not is_allowed_content_path(req.folder_path):
        raise HTTPException(status_code=400, detail="Thư mục không tồn tại")

    txt_path = os.path.join(req.folder_path, "caption.txt")
    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(req.caption)
        log_to_web(f"Đã lưu caption cho thư mục {os.path.basename(req.folder_path)}.", "OK")
        return {"status": "success", "message": "Đã lưu caption"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@router.post("/generate-schedule")
def generate_schedule_endpoint(req: GenerateScheduleRequest):
    """Generate a scheduled timeline preview from items and time slots."""
    try:
        schedule = build_schedule(
            req.items,
            req.target_pages,
            req.start_date,
            req.end_date,
            req.time_slots,
            path_validator=is_allowed_content_path,
        )
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return {
        "status": "success",
        "total_jobs": len(schedule),
        "data": schedule
    }


@router.post("/persist-schedule")
def persist_schedule_endpoint(req: PersistScheduleRequest):
    """Persist a reviewed WebUI schedule to content_pool and post_history."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    try:
        result = persist_reviewed_schedule(
            db_p, req.schedules, path_validator=is_allowed_content_path
        )
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    inserted, skipped = result["inserted"], result["skipped"]
    log_to_web(f"Đã lưu {inserted} công việc vào hàng đợi; bỏ qua {skipped} bản trùng.", "OK")
    return {"status": "success", "inserted": inserted, "skipped": skipped}


@router.get("/jobs")
def list_schedule_jobs(
    status: str = Query(default="", pattern="^(|Pending|Running|Scheduled|Failed|Posted|Skipped|Unsupported)$")
):
    """List persisted WebUI schedule records after application restarts."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    jobs = get_schedule_history_filtered(
        db_p,
        status=status.strip(),
        scheduling_method="WebUI",
    )
    return {"status": "success", "total": len(jobs), "data": jobs}


@router.get("/queue-status")
def get_queue_status():
    return {"status": "success", "data": queue_runner.snapshot()}


@router.post("/queue-run")
def run_schedule_queue(req: RunQueueRequest):
    """Start submitting pending schedules to Facebook in a background worker."""
    if queue_runner.snapshot()["is_running"]:
        raise HTTPException(status_code=409, detail="Hàng đợi đang chạy")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    jobs = get_schedule_history_filtered(db_p, status="Pending", scheduling_method="WebUI")
    if req.history_ids:
        selected = {int(job_id) for job_id in req.history_ids}
        jobs = [job for job in jobs if int(job.get("history_id") or 0) in selected]
    if not jobs:
        raise HTTPException(status_code=400, detail="Không có job Pending để chạy")

    started = queue_runner.start(
        db_p,
        jobs,
        brand_name=req.brand_name or "",
        cta_enabled=bool(req.cta_enabled),
        share_to_story=bool(req.share_to_story),
        headless=bool(req.headless),
        on_status=lambda message: log_to_web(message, "INFO"),
        on_progress=lambda current, total: progress_to_web(
            "poster", current, total, f"{current}/{total}", "posting"
        ),
    )
    if not started:
        raise HTTPException(status_code=409, detail="Không thể khởi động hàng đợi")
    log_to_web(f"Bắt đầu xử lý {len(jobs)} job đăng bài.", "INFO")
    return {"status": "success", "total": len(jobs)}


@router.post("/queue-stop")
def stop_schedule_queue():
    stopped = queue_runner.stop()
    return {
        "status": "success",
        "message": "Đã gửi lệnh dừng" if stopped else "Hàng đợi không chạy",
    }


@router.post("/jobs/retry")
def retry_schedule_jobs(req: JobIdsRequest):
    db_p = get_db_path(config.get("scraper_db_path", ""))
    changed = retry_failed_posts(db_p, [int(job_id) for job_id in req.history_ids])
    return {"status": "success", "changed": changed}


@router.post("/jobs/delete")
def delete_schedule_jobs(req: JobIdsRequest):
    if queue_runner.snapshot()["is_running"]:
        raise HTTPException(status_code=409, detail="Hãy dừng hàng đợi trước khi xóa job")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    requested = {int(job_id) for job_id in req.history_ids}
    existing = get_schedule_history_filtered(db_p, scheduling_method="WebUI")
    deletable = [
        int(job["history_id"])
        for job in existing
        if int(job["history_id"]) in requested and job.get("status") in {"Pending", "Failed"}
    ]
    deleted = delete_history_records(db_p, deletable)
    return {"status": "success", "deleted": deleted}
