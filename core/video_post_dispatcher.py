"""
Multi-platform Video Post dispatcher.

V1 routes Facebook Reels to the existing automation and marks other
platforms as unsupported with explicit job status.
"""

import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.auto_poster import AutoPoster
from core.db_storage import (
    get_account,
    get_managed_pages,
    get_social_account,
    save_managed_pages,
    sync_social_account_to_fb_account,
    update_video_post_job_status,
)
from utils import logger


SUPPORTED_AUTOMATION = {"facebook"}


def _chrome_debug_port(account_id: int) -> int:
    try:
        aid = int(account_id or 0)
    except (TypeError, ValueError):
        aid = 0
    return 9400 + (aid % 400)


def _is_invalid_page_id(page_id: str) -> bool:
    value = str(page_id or "").strip().lower()
    return value in {"", "profile.php", "photo.php", "pages", "page"}


class VideoPostDispatcher:
    """Execute video_post_jobs grouped by social account."""

    def __init__(
        self,
        db_path: str,
        jobs: List[dict],
        brand_name: str = "",
        cta_enabled: bool = False,
        share_to_story: bool = True,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ):
        self.db_path = db_path
        self.jobs = jobs
        self.brand_name = brand_name
        self.cta_enabled = cta_enabled
        self.share_to_story = share_to_story
        self.on_status = on_status
        self.on_progress = on_progress
        self._stop_event = threading.Event()
        self._poster: Optional[AutoPoster] = None
        self._posters: Dict[int, AutoPoster] = {}
        self._lock = threading.Lock()

    def request_stop(self):
        self._stop_event.set()
        with self._lock:
            posters = list(self._posters.values())
            if self._poster:
                posters.append(self._poster)
        for poster in posters:
            poster.request_stop()

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    def run(self) -> Dict[str, int]:
        total = len(self.jobs)
        stats = {"success": 0, "failed": 0, "unsupported": 0, "skipped": 0}
        grouped: Dict[int, List[dict]] = {}
        for job in self.jobs:
            grouped.setdefault(int(job.get("account_id") or 0), []).append(job)

        done = 0
        stats_lock = threading.Lock()

        def mark_done():
            nonlocal done
            with stats_lock:
                done += 1
                current = done
            self._progress(current, total)
            return current

        def merge_stats(local_stats: Dict[str, int]):
            with stats_lock:
                for key, value in local_stats.items():
                    stats[key] += value

        def account_worker(account_id: int, account_jobs: List[dict]):
            local_stats = {"success": 0, "failed": 0, "unsupported": 0, "skipped": 0}
            if self.is_stopped():
                skipped = self._skip_jobs(account_jobs, "Đã dừng trước khi chạy account này")
                local_stats["skipped"] += skipped
                for _job in account_jobs:
                    mark_done()
                merge_stats(local_stats)
                return

            social_account = get_social_account(self.db_path, account_id)
            if not social_account:
                for job in account_jobs:
                    update_video_post_job_status(
                        self.db_path, job["job_id"], "Failed",
                        f"Không tìm thấy social account id={account_id}",
                    )
                    local_stats["failed"] += 1
                    mark_done()
                merge_stats(local_stats)
                return

            fb_jobs = []
            for job in account_jobs:
                platform = job.get("platform", "")
                if platform not in SUPPORTED_AUTOMATION:
                    msg = f"{platform} chưa hỗ trợ đăng video tự động trong v1"
                    update_video_post_job_status(self.db_path, job["job_id"], "Unsupported", msg)
                    logger.info(
                        f"Video job unsupported: job_id={job['job_id']} "
                        f"platform={platform} account_id={account_id} target={job.get('target_uid') or job.get('target_name')}"
                    )
                    local_stats["unsupported"] += 1
                    mark_done()
                else:
                    fb_jobs.append(job)

            if fb_jobs:
                sub_stats = self._run_facebook_jobs(social_account, fb_jobs, mark_done, total)
                for key, value in sub_stats.items():
                    local_stats[key] += value
            merge_stats(local_stats)

        threads = []
        for account_id, account_jobs in grouped.items():
            thread = threading.Thread(
                target=account_worker,
                args=(account_id, account_jobs),
                daemon=True,
            )
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()

        return stats

    def _run_facebook_jobs(
        self, social_account: dict, jobs: List[dict], mark_done: Callable[[], int], total: int
    ) -> Dict[str, int]:
        stats = {"success": 0, "failed": 0, "unsupported": 0, "skipped": 0}
        legacy_id = sync_social_account_to_fb_account(self.db_path, social_account["id"])
        fb_acc = get_account(self.db_path, legacy_id) if legacy_id > 0 else None
        if not fb_acc:
            for job in jobs:
                update_video_post_job_status(
                    self.db_path, job["job_id"], "Failed",
                    "Không tạo được Facebook legacy account",
                )
                stats["failed"] += 1
                mark_done()
            return stats

        fb_acc["profile_dir"] = social_account.get("profile_dir", "")
        fb_acc["cdp_port"] = _chrome_debug_port(social_account["id"])
        self._status(f"Mở Chrome Facebook: {fb_acc.get('label') or fb_acc.get('username')}")
        poster = AutoPoster(account=fb_acc, headless=False)
        with self._lock:
            self._posters[int(social_account["id"])] = poster
        if not poster.start():
            for job in jobs:
                update_video_post_job_status(
                    self.db_path, job["job_id"], "Failed",
                    "Không mở được Facebook session",
                )
                stats["failed"] += 1
                mark_done()
            with self._lock:
                self._posters.pop(int(social_account["id"]), None)
            return stats

        try:
            for job in jobs:
                if self.is_stopped() or poster.is_stopped():
                    update_video_post_job_status(self.db_path, job["job_id"], "Skipped", "Người dùng đã dừng")
                    stats["skipped"] += 1
                    mark_done()
                    continue

                update_video_post_job_status(self.db_path, job["job_id"], "Running", "")
                poster._last_error = ""
                label = f"{job.get('folder_name')} → {job.get('target_name')}"
                self._status(f"Facebook Reels: {label}")

                def _job_status(msg, _job=job):
                    logger.info(
                        f"Video job {msg}: job_id={_job['job_id']} "
                        f"platform=facebook account_id={_job.get('account_id')} "
                        f"target={_job.get('target_uid') or _job.get('target_name')}"
                    )
                    self._status(msg)

                page_id = self._resolve_page_id(job, legacy_id, poster, _job_status)
                if _is_invalid_page_id(page_id):
                    ok = False
                    poster._last_error = (
                        f"Invalid Facebook page id for target '{job.get('target_name')}'"
                    )
                    logger.error(
                        "Video job invalid Facebook page id: "
                        f"job_id={job['job_id']} target={job.get('target_name')} "
                        f"target_uid={job.get('target_uid')}"
                    )
                else:
                    scheduled = job.get("scheduled_time") if job.get("mode") == "schedule" else None
                    if scheduled:
                        ok = poster.post_content(
                            folder_path=job.get("folder_path", ""),
                            caption=job.get("caption", ""),
                            scheduled_time=scheduled,
                            page_name=job.get("target_name", ""),
                            page_id=page_id,
                            brand_name=self.brand_name,
                            cta_enabled=self.cta_enabled,
                            share_to_story=self.share_to_story,
                            video_as_reel=True,
                            on_status=_job_status,
                        )
                    else:
                        ok = poster.post_now(
                            folder_path=job.get("folder_path", ""),
                            caption=job.get("caption", ""),
                            page_name=job.get("target_name", ""),
                            page_id=page_id,
                            brand_name=self.brand_name,
                            cta_enabled=self.cta_enabled,
                            share_to_story=self.share_to_story,
                            video_as_reel=True,
                            on_status=_job_status,
                        )
                scheduled = job.get("scheduled_time") if job.get("mode") == "schedule" else None
                final_status = "Scheduled" if ok and scheduled else ("Success" if ok else "Failed")
                error = "" if ok else (poster._last_error or "Facebook Reels automation failed")
                update_video_post_job_status(self.db_path, job["job_id"], final_status, error)
                stats["success" if ok else "failed"] += 1
                current = mark_done()
                if current < total and not self.is_stopped():
                    time.sleep(4)
        finally:
            poster.stop()
            with self._lock:
                self._posters.pop(int(social_account["id"]), None)
        return stats

    def _resolve_page_id(
        self,
        job: dict,
        legacy_id: int,
        poster: AutoPoster,
        on_status: Callable[[str], None],
    ) -> str:
        page_id = str(job.get("target_uid") or "").strip()
        if not _is_invalid_page_id(page_id):
            return page_id

        target_id = int(job.get("target_id") or 0)
        target_name = str(job.get("target_name") or "").strip().lower()
        for page in get_managed_pages(self.db_path, legacy_id):
            candidate = str(page.get("page_id") or "").strip()
            if _is_invalid_page_id(candidate):
                continue
            same_row = target_id and int(page.get("id") or 0) == target_id
            same_name = target_name and str(page.get("page_name") or "").strip().lower() == target_name
            if same_row or same_name:
                logger.info(
                    f"Resolved Facebook page id from managed_pages: "
                    f"job_id={job['job_id']} page_id={candidate}"
                )
                return candidate

        if not poster:
            return page_id

        on_status("Dang cap nhat lai Page ID Facebook...")
        try:
            pages, _business_id = poster.scan_managed_pages()
            if pages:
                save_managed_pages(self.db_path, legacy_id, pages)
            for page in pages or []:
                candidate = str(page.get("page_id") or "").strip()
                if _is_invalid_page_id(candidate):
                    continue
                same_name = target_name and str(page.get("page_name") or "").strip().lower() == target_name
                if same_name:
                    logger.info(
                        f"Resolved Facebook page id by rescan: "
                        f"job_id={job['job_id']} page_id={candidate}"
                    )
                    return candidate
        except Exception as e:
            logger.error(f"Resolve Facebook page id failed: {str(e)[:200]}")

        return page_id

    def _skip_jobs(self, jobs: List[dict], reason: str) -> int:
        count = 0
        for job in jobs:
            update_video_post_job_status(self.db_path, job["job_id"], "Skipped", reason)
            count += 1
        return count

    def _status(self, message: str):
        if self.on_status:
            self.on_status(message)

    def _progress(self, done: int, total: int):
        if self.on_progress:
            self.on_progress(done, total)
