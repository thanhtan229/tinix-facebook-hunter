"""Validation and persistence for reviewed WebUI posting schedules."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from core.db_storage import (
    bulk_insert_schedule,
    check_duplicate_schedule,
    get_all_content_pool,
    get_all_managed_pages,
    save_content_pool,
)
from core.job_states import PostJobStatus

MAX_SCHEDULE_JOBS = 5_000
MIN_LEAD_TIME = timedelta(minutes=20)
MAX_LEAD_TIME = timedelta(days=29)


class ScheduleValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _parse_schedule_time(value: object) -> datetime:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ScheduleValidationError("Thời gian đăng không hợp lệ") from exc


def _validate_lead_time(scheduled_at: datetime, now: datetime) -> None:
    if scheduled_at < now + MIN_LEAD_TIME:
        raise ScheduleValidationError("Mỗi lịch đăng phải cách hiện tại ít nhất 20 phút")
    if scheduled_at > now + MAX_LEAD_TIME:
        raise ScheduleValidationError("Facebook chỉ cho phép đặt lịch trong vòng 29 ngày")


def build_schedule(
    items: Iterable[Mapping[str, Any]],
    target_pages: Iterable[Any],
    start_date: str,
    end_date: str | None,
    time_slots: Iterable[str],
    *,
    path_validator: Callable[[str], bool],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Build a validated preview without performing database writes."""
    item_list = list(items)
    page_list = list(target_pages)
    slot_list = list(time_slots)
    if not item_list or not page_list or not slot_list:
        raise ScheduleValidationError("Thiếu bài viết, fanpage hoặc khung giờ đăng!", 400)
    if len(item_list) * len(page_list) > MAX_SCHEDULE_JOBS:
        raise ScheduleValidationError("Một lần chỉ được tạo tối đa 5.000 công việc")

    try:
        first_day = datetime.strptime(start_date, "%Y-%m-%d")
        last_day = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None
        parsed_slots = [datetime.strptime(slot.strip(), "%H:%M").strftime("%H:%M") for slot in slot_list]
    except (AttributeError, ValueError) as exc:
        raise ScheduleValidationError(f"Ngày hoặc khung giờ không hợp lệ: {exc}") from exc
    if last_day and last_day < first_day:
        raise ScheduleValidationError("Ngày kết thúc phải từ ngày bắt đầu trở đi")

    reference_time = now or datetime.now()
    schedule: list[dict[str, Any]] = []
    for item_index, item in enumerate(item_list):
        item_path = str(item.get("folder_path") or "")
        if not item_path or not path_validator(item_path):
            raise ScheduleValidationError("Nội dung nằm ngoài thư mục đã quét", 400)
        slot_index = item_index % len(parsed_slots)
        day_offset = item_index // len(parsed_slots)
        post_day = first_day + timedelta(days=day_offset)
        if last_day and post_day > last_day:
            raise ScheduleValidationError("Số bài vượt quá khoảng ngày và khung giờ đã chọn")
        scheduled_time = f"{post_day:%Y-%m-%d} {parsed_slots[slot_index]}"
        _validate_lead_time(_parse_schedule_time(scheduled_time), reference_time)

        for page in page_list:
            page_data = page if isinstance(page, Mapping) else {"page_name": str(page)}
            schedule.append(
                {
                    "folder_name": item.get("folder_name"),
                    "folder_path": item_path,
                    "caption": item.get("caption", ""),
                    "target_page": page_data.get("page_name") or page_data.get("page_id", ""),
                    "target_id": page_data.get("id"),
                    "target_uid": page_data.get("page_id", ""),
                    "account_id": page_data.get("account_id"),
                    "scheduled_time": scheduled_time,
                    "status": "Chờ đăng",
                }
            )
    return schedule


def persist_reviewed_schedule(
    db_path: str,
    schedules: Iterable[Mapping[str, Any]],
    *,
    path_validator: Callable[[str], bool],
    now: datetime | None = None,
) -> dict[str, int]:
    """Validate and atomically prepare reviewed jobs for the persistent queue."""
    jobs = list(schedules)
    if not jobs:
        raise ScheduleValidationError("Lịch đăng không được để trống")
    if len(jobs) > MAX_SCHEDULE_JOBS:
        raise ScheduleValidationError("Một lần chỉ được lưu tối đa 5.000 công việc")

    pages = get_all_managed_pages(db_path)
    page_keys = {(int(p.get("id") or 0), int(p.get("account_id") or 0)): p for p in pages}
    reference_time = now or datetime.now()
    content_items: dict[str, dict[str, Any]] = {}
    for job in jobs:
        folder_path = str(job.get("folder_path") or "")
        if not folder_path or not path_validator(folder_path):
            raise ScheduleValidationError("Nội dung nằm ngoài thư mục đã quét", 400)
        _validate_lead_time(_parse_schedule_time(job.get("scheduled_time")), reference_time)
        page_key = (int(job.get("target_id") or 0), int(job.get("account_id") or 0))
        if page_key not in page_keys:
            raise ScheduleValidationError("Fanpage trong lịch không còn tồn tại")
        resolved = str(Path(folder_path).resolve())
        content_items[resolved] = {
            "folder_name": job.get("folder_name") or Path(folder_path).name,
            "folder_path": resolved,
            "caption": job.get("caption", ""),
        }

    save_content_pool(db_path, list(content_items.values()))
    content_by_path = {
        str(Path(item["folder_path"]).resolve()): item for item in get_all_content_pool(db_path)
    }

    records: list[dict[str, Any]] = []
    skipped = 0
    for job in jobs:
        content = content_by_path.get(str(Path(str(job["folder_path"])).resolve()))
        if not content:
            raise RuntimeError("Không thể lưu nội dung vào cơ sở dữ liệu")
        page_key = (int(job.get("target_id") or 0), int(job.get("account_id") or 0))
        page = page_keys[page_key]
        scheduled_time = str(job["scheduled_time"])
        page_name = page.get("page_name") or page.get("page_id", "")
        if check_duplicate_schedule(db_path, content["content_id"], page_name, scheduled_time):
            skipped += 1
            continue
        records.append(
            {
                "content_id": content["content_id"],
                "account_id": page.get("account_id") or "",
                "page_name": page_name,
                "scheduled_time": scheduled_time,
                "status": PostJobStatus.PENDING,
                "scheduling_method": "WebUI",
            }
        )
    return {"inserted": bulk_insert_schedule(db_path, records), "skipped": skipped}
