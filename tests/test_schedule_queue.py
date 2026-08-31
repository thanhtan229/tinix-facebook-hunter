import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.db_storage import (
    add_account,
    get_all_managed_pages,
    get_schedule_history_filtered,
    save_managed_pages,
    update_history_status_with_error,
)
from core.post_queue import PostQueueRunner
from core.schedule_service import ScheduleValidationError, build_schedule, persist_reviewed_schedule


class RaisingPoster:
    def __init__(self, account, headless=False):
        self._last_error = ""
        self._stopped = False

    def start(self):
        return True

    def stop(self):
        self._stopped = True

    def request_stop(self):
        self._stopped = True

    def is_stopped(self):
        return self._stopped

    def post_content(self, **_kwargs):
        raise RuntimeError("simulated browser failure")


class BlockingPoster(RaisingPoster):
    entered = threading.Event()

    def post_content(self, **_kwargs):
        self.__class__.entered.set()
        self.__class__.entered.wait(0.05)
        for _ in range(100):
            if self._stopped:
                self._last_error = "stopped by test"
                return False
            threading.Event().wait(0.01)
        return True


class ScheduleServiceTest(unittest.TestCase):
    def test_build_schedule_assigns_slots_and_pages_deterministically(self):
        now = datetime(2026, 1, 1, 0, 0)
        items = [
            {"folder_path": "allowed/one", "folder_name": "one"},
            {"folder_path": "allowed/two", "folder_name": "two"},
        ]
        pages = [{"id": 1, "account_id": 9, "page_name": "A"}, {"id": 2, "account_id": 9, "page_name": "B"}]
        jobs = build_schedule(
            items,
            pages,
            "2026-01-02",
            "2026-01-02",
            ["08:00", "20:00"],
            path_validator=lambda path: path.startswith("allowed/"),
            now=now,
        )
        self.assertEqual(len(jobs), 4)
        self.assertEqual([jobs[0]["scheduled_time"], jobs[2]["scheduled_time"]], ["2026-01-02 08:00", "2026-01-02 20:00"])

    def test_build_schedule_rejects_insufficient_date_range(self):
        with self.assertRaisesRegex(ScheduleValidationError, "vượt quá khoảng ngày"):
            build_schedule(
                [{"folder_path": f"allowed/{index}"} for index in range(2)],
                ["Page"],
                "2026-01-02",
                "2026-01-02",
                ["08:00"],
                path_validator=lambda _path: True,
                now=datetime(2026, 1, 1),
            )


class QueueFailureTest(unittest.TestCase):
    @staticmethod
    def _create_jobs(root: Path, page_count: int = 1):
        content_dir = root / "content"
        content_dir.mkdir()
        db_path = str(root / "queue.db")
        account_id = add_account(db_path, username="failure-test")
        save_managed_pages(
            db_path,
            account_id,
            [
                {"page_name": f"Page {index}", "page_id": str(1000 + index), "page_url": ""}
                for index in range(page_count)
            ],
        )
        pages = get_all_managed_pages(db_path)
        scheduled = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        schedules = [
            {
                "folder_name": "content",
                "folder_path": str(content_dir),
                "caption": "test",
                "target_id": page["id"],
                "account_id": page["account_id"],
                "scheduled_time": scheduled,
            }
            for page in pages
        ]
        persist_reviewed_schedule(db_path, schedules, path_validator=lambda _path: True)
        return db_path, get_schedule_history_filtered(db_path, status="Pending", scheduling_method="WebUI")

    def test_queue_marks_automation_exception_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, jobs = self._create_jobs(Path(temp_dir))
            runner = PostQueueRunner(poster_factory=RaisingPoster)
            self.assertTrue(runner.start(db_path, jobs, delay_range=(0, 0)))
            self.assertTrue(runner.wait(3))
            failed = get_schedule_history_filtered(db_path, status="Failed", scheduling_method="WebUI")
            self.assertEqual(len(failed), 1)
            self.assertIn("simulated browser failure", failed[0]["error_log"])

    def test_stopping_queue_leaves_unstarted_job_pending(self):
        BlockingPoster.entered.clear()
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path, jobs = self._create_jobs(Path(temp_dir), page_count=2)
            runner = PostQueueRunner(poster_factory=BlockingPoster)
            self.assertTrue(runner.start(db_path, jobs, delay_range=(0, 0)))
            self.assertTrue(BlockingPoster.entered.wait(2))
            self.assertTrue(runner.stop())
            self.assertTrue(runner.wait(3))
            pending = get_schedule_history_filtered(db_path, status="Pending", scheduling_method="WebUI")
            self.assertEqual(len(pending), 1)
            self.assertEqual(runner.snapshot()["skipped"], 1)

    def test_unknown_persistent_status_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported post job status"):
            update_history_status_with_error("unused.db", 1, "Typo")


if __name__ == "__main__":
    unittest.main()
