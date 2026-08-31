"""Background executor for persisted social post schedules."""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from core.auto_poster import AutoPoster
from core.db_storage import get_account, get_managed_pages, update_history_status_with_error
from core.job_states import PostJobStatus
from utils import logger


PosterFactory = Callable[..., AutoPoster]


class PostQueueRunner:
    """Execute reviewed post_history records without blocking the WebUI."""

    def __init__(self, poster_factory: PosterFactory = AutoPoster):
        self._poster_factory = poster_factory
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._poster: Optional[AutoPoster] = None
        self._status = {
            "is_running": False,
            "total": 0,
            "completed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "current": "",
            "started_at": "",
            "finished_at": "",
        }

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(
        self,
        db_path: str,
        records: List[dict],
        *,
        brand_name: str = "",
        cta_enabled: bool = False,
        share_to_story: bool = True,
        headless: bool = False,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
        delay_range: tuple[float, float] = (5.0, 12.0),
    ) -> bool:
        with self._lock:
            if self._status["is_running"] or not records:
                return False
            self._stop_event.clear()
            self._status.update({
                "is_running": True,
                "total": len(records),
                "completed": 0,
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "current": "",
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": "",
            })
            self._thread = threading.Thread(
                target=self._run,
                args=(db_path, list(records), brand_name, cta_enabled, share_to_story,
                      headless, on_status, on_progress, delay_range),
                daemon=True,
                name="tinix-post-queue",
            )
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._status["is_running"]:
                return False
            self._stop_event.set()
            poster = self._poster
        if poster:
            poster.request_stop()
        return True

    def wait(self, timeout: Optional[float] = None) -> bool:
        thread = self._thread
        if thread:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    def _emit_status(self, message: str, callback: Optional[Callable[[str], None]]) -> None:
        with self._lock:
            self._status["current"] = message
        logger.info(message)
        if callback:
            callback(message)

    def _complete_one(self, outcome: str, on_progress: Optional[Callable[[int, int], None]]) -> None:
        with self._lock:
            self._status["completed"] += 1
            self._status[outcome] += 1
            completed = self._status["completed"]
            total = self._status["total"]
        if on_progress:
            on_progress(completed, total)

    @staticmethod
    def _validate_window(record: dict) -> str:
        try:
            scheduled = datetime.strptime(record.get("scheduled_time", ""), "%Y-%m-%d %H:%M")
        except ValueError:
            return "Thời gian đăng không hợp lệ"
        now = datetime.now()
        if scheduled < now + timedelta(minutes=20):
            return "Thời gian phải cách hiện tại ít nhất 20 phút"
        if scheduled > now + timedelta(days=29):
            return "Facebook chỉ cho phép đặt lịch trong vòng 29 ngày"
        return ""

    def _run(
        self,
        db_path: str,
        records: List[dict],
        brand_name: str,
        cta_enabled: bool,
        share_to_story: bool,
        headless: bool,
        on_status: Optional[Callable[[str], None]],
        on_progress: Optional[Callable[[int, int], None]],
        delay_range: tuple[float, float],
    ) -> None:
        try:
            grouped: Dict[int, List[dict]] = {}
            for record in sorted(records, key=lambda item: item.get("scheduled_time", "")):
                grouped.setdefault(int(record.get("account_id") or 0), []).append(record)

            for account_id, account_records in grouped.items():
                if self._stop_event.is_set():
                    break
                account = get_account(db_path, account_id)
                if not account:
                    for record in account_records:
                        message = f"Không tìm thấy tài khoản #{account_id}"
                        update_history_status_with_error(db_path, record["history_id"], PostJobStatus.FAILED, message)
                        self._complete_one("failed", on_progress)
                    continue

                pages = {str(page.get("page_name") or "").strip().lower(): page for page in get_managed_pages(db_path, account_id)}
                poster = self._poster_factory(account=account, headless=headless)
                with self._lock:
                    self._poster = poster
                self._emit_status(f"Đang mở Chrome cho {account.get('label') or account.get('username')}", on_status)
                if not poster.start():
                    for record in account_records:
                        message = "Không thể mở Facebook session"
                        update_history_status_with_error(db_path, record["history_id"], PostJobStatus.FAILED, message)
                        self._complete_one("failed", on_progress)
                    with self._lock:
                        self._poster = None
                    continue

                try:
                    for index, record in enumerate(account_records):
                        if self._stop_event.is_set() or poster.is_stopped():
                            break
                        window_error = self._validate_window(record)
                        if window_error:
                            update_history_status_with_error(db_path, record["history_id"], PostJobStatus.FAILED, window_error)
                            self._complete_one("failed", on_progress)
                            continue

                        page = pages.get(str(record.get("page_name") or "").strip().lower(), {})
                        page_id = str(page.get("page_id") or "")
                        if not page_id:
                            message = f"Không tìm thấy Page ID cho {record.get('page_name', '')}"
                            update_history_status_with_error(db_path, record["history_id"], PostJobStatus.FAILED, message)
                            self._complete_one("failed", on_progress)
                            continue

                        label = f"{record.get('folder_name', '')} → {record.get('page_name', '')}"
                        self._emit_status(f"Đang xử lý {label}", on_status)
                        update_history_status_with_error(db_path, record["history_id"], PostJobStatus.RUNNING, "")
                        poster._last_error = ""
                        try:
                            ok = poster.post_content(
                                folder_path=record.get("folder_path", ""),
                                caption=record.get("caption", ""),
                                scheduled_time=record.get("scheduled_time", ""),
                                page_name=record.get("page_name", ""),
                                page_id=page_id,
                                brand_name=brand_name,
                                cta_enabled=cta_enabled,
                                share_to_story=share_to_story,
                                on_status=lambda msg: self._emit_status(msg, on_status),
                            )
                            error = "" if ok else (
                                getattr(poster, "_last_error", "") or "Facebook automation failed"
                            )
                        except Exception as exc:
                            ok = False
                            error = f"Post automation error: {str(exc)[:180]}"
                            logger.exception("Post queue item failed", exc)
                        update_history_status_with_error(
                            db_path,
                            record["history_id"],
                            PostJobStatus.SCHEDULED if ok else PostJobStatus.FAILED,
                            error,
                        )
                        self._complete_one("success" if ok else "failed", on_progress)
                        if index < len(account_records) - 1 and not self._stop_event.is_set():
                            time.sleep(random.uniform(*delay_range))
                finally:
                    poster.stop()
                    with self._lock:
                        self._poster = None

            if self._stop_event.is_set():
                remaining = self.snapshot()["total"] - self.snapshot()["completed"]
                with self._lock:
                    self._status["skipped"] += max(remaining, 0)
                self._emit_status("Hàng đợi đã được dừng; các job chưa chạy vẫn giữ trạng thái Pending", on_status)
        except Exception as exc:
            logger.exception("Post queue runner failed", exc)
            self._emit_status(f"Hàng đợi lỗi: {str(exc)[:160]}", on_status)
        finally:
            with self._lock:
                self._status["is_running"] = False
                self._status["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._poster = None
