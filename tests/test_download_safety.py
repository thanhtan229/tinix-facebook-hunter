import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core.downloader import AccountPacingState, DownloadOrchestrator, DownloadSafetySettings, DownloadStats
from core.facebook_parser import BrowserManager, PostData
from utils import config as app_config
from web.routes.system import _public_config


class DownloadSafetyDefaultsTest(unittest.TestCase):
    def test_defaults_favour_three_account_workers_with_pacing(self):
        self.assertEqual(app_config.DEFAULTS["max_threads"], 3)
        self.assertTrue(app_config.DEFAULTS["download_use_accounts"])
        self.assertEqual(app_config.DEFAULTS["download_delay_min"], 2.0)
        self.assertEqual(app_config.DEFAULTS["download_delay_max"], 5.0)
        self.assertEqual(app_config.DEFAULTS["download_batch_size"], 25)
        self.assertEqual(app_config.DEFAULTS["download_batch_rest_min"], 30.0)
        self.assertEqual(app_config.DEFAULTS["download_batch_rest_max"], 90.0)

    def test_existing_config_is_migrated_once_to_safe_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps({"max_threads": 10}), encoding="utf-8")
            with patch.object(app_config, "_config_path", config_path), patch.object(
                app_config, "_config_cache", None
            ):
                loaded = app_config.load_config()

            self.assertEqual(loaded["max_threads"], 3)
            self.assertTrue(loaded["download_use_accounts"])
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertTrue(persisted["_download_safety_defaults_v1"])

    def test_internal_migration_marker_is_not_exposed_to_browser(self):
        public = _public_config({"_download_safety_defaults_v1": True, "max_threads": 3})
        self.assertNotIn("_download_safety_defaults_v1", public)


class DownloadSafetyBehaviorTest(unittest.TestCase):
    def test_cookie_validation_failure_resets_stats_for_the_new_run(self):
        orchestrator = DownloadOrchestrator()
        orchestrator.stats.total_posts = 9
        orchestrator.stats.completed_posts = 9
        completed = []
        orchestrator.set_callbacks(on_all_complete=lambda success, message: completed.append((success, message)))

        with patch("core.downloader.parse_urls", return_value=["https://www.facebook.com/12345678901"]), patch(
            "core.downloader.parse_cookie_string", return_value={}
        ), patch("core.downloader.validate_cookies", return_value=(False, "Thiếu cookie")):
            started = orchestrator.start("https://www.facebook.com/12345678901", "", ".")

        self.assertFalse(started)
        self.assertEqual(orchestrator.stats.total_posts, 1)
        self.assertEqual(orchestrator.stats.completed_posts, 0)
        self.assertEqual(completed, [(False, "Cookies lỗi: Thiếu cookie")])

    def test_shared_cookie_mode_caps_browser_workers_at_one(self):
        orchestrator = DownloadOrchestrator()
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "core.downloader.parse_urls", return_value=["https://www.facebook.com/12345678901"]
        ), patch(
            "core.downloader.parse_cookie_string", return_value={"c_user": "1", "xs": "test"}
        ), patch(
            "core.downloader.validate_cookies", return_value=(True, "OK")
        ), patch.object(orchestrator, "_mark_urls_download_status"), patch(
            "core.downloader.threading.Thread"
        ) as thread_cls:
            started = orchestrator.start("https://www.facebook.com/12345678901", "c_user=1; xs=test", temp_dir, max_threads=8)

        self.assertTrue(started)
        self.assertTrue(orchestrator._cookie_mode)
        self.assertEqual(orchestrator._max_threads, 1)
        thread_cls.return_value.start.assert_called_once()

    def test_machine_error_codes_drive_classification(self):
        self.assertEqual(
            DownloadOrchestrator._classify_download_error("[ACCOUNT_CHECKPOINT] Facebook yêu cầu xác nhận"),
            "ACCOUNT_CHECKPOINT",
        )
        self.assertEqual(
            DownloadOrchestrator._classify_download_error("[RATE_LIMITED] HTTP 429"),
            "RATE_LIMITED",
        )
        self.assertEqual(
            DownloadOrchestrator._classify_download_error("[MEDIA_URL_EXPIRED] CDN URL expired"),
            "MEDIA_URL_EXPIRED",
        )

    def test_checkpoint_login_and_limit_pages_are_separated(self):
        self.assertEqual(
            BrowserManager._detect_facebook_access_issue("https://www.facebook.com/checkpoint/", ""),
            ("ACCOUNT_CHECKPOINT", "Facebook yêu cầu xác nhận danh tính hoặc checkpoint."),
        )
        self.assertEqual(
            BrowserManager._detect_facebook_access_issue("https://www.facebook.com/login/?next=%2F", ""),
            ("ACCOUNT_AUTH_EXPIRED", "Facebook chuyển phiên sang trang đăng nhập."),
        )
        self.assertEqual(
            BrowserManager._detect_facebook_access_issue("https://www.facebook.com/post", "Bạn đang thực hiện quá nhanh"),
            ("RATE_LIMITED", "Facebook đang giới hạn tạm thời các yêu cầu từ account này."),
        )

    def test_checkpoint_fetch_error_reaches_the_account_policy(self):
        class CheckpointBrowser:
            @staticmethod
            def fetch_post(url, post_id):
                return PostData(
                    post_id=post_id,
                    original_url=url,
                    error="Facebook yêu cầu xác nhận danh tính hoặc checkpoint.",
                    error_code="ACCOUNT_CHECKPOINT",
                )

        orchestrator = DownloadOrchestrator()
        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator._output_dir = Path(temp_dir)
            with patch("core.downloader.get_db_path", return_value="test.db"), patch(
                "core.downloader.get_post_by_id", return_value=None
            ), patch.object(orchestrator, "_mark_post_download_status"):
                success, error = orchestrator._run_post_attempt(
                    "https://www.facebook.com/12345678901", 1,
                    CheckpointBrowser(), {}, "Test", 1, 1,
                )

        self.assertFalse(success)
        self.assertIn("[ACCOUNT_CHECKPOINT]", error)
        self.assertEqual(DownloadOrchestrator._classify_download_error(error), "ACCOUNT_CHECKPOINT")

    def test_pacing_uses_short_delay_then_batch_rest(self):
        orchestrator = DownloadOrchestrator()
        orchestrator._safety = DownloadSafetySettings(2.0, 5.0, 25, 30.0, 90.0)
        pacing = AccountPacingState()
        with patch("core.downloader.random.uniform", side_effect=[2.5, 45.0]):
            before = time.monotonic()
            orchestrator._schedule_account_pacing(pacing, 0, "Cookie phiên", failed=False)
            self.assertEqual(pacing.processed_posts, 1)
            self.assertGreaterEqual(pacing.next_ready_at, before + 2.4)
            self.assertEqual(pacing.wait_code, "PACING")

            pacing.processed_posts = 24
            orchestrator._schedule_account_pacing(pacing, 0, "Cookie phiên", failed=False)
            self.assertEqual(pacing.processed_posts, 25)
            self.assertEqual(pacing.wait_code, "BATCH_REST")
            self.assertIn("sau 25 bài", pacing.wait_message)

    def test_second_recent_rate_limit_pauses_the_run(self):
        orchestrator = DownloadOrchestrator()
        orchestrator._running = True
        orchestrator._pause_event.set()
        first = AccountPacingState()
        second = AccountPacingState()
        with patch("core.downloader.random.uniform", return_value=0.0):
            orchestrator._apply_rate_limit(first, 1, "One", "[RATE_LIMITED] HTTP 429")
            self.assertTrue(orchestrator._pause_event.is_set())
            self.assertGreater(first.cooldown_until, time.monotonic())

            orchestrator._apply_rate_limit(second, 2, "Two", "[RATE_LIMITED] HTTP 429")

        self.assertFalse(orchestrator._pause_event.is_set())
        self.assertIn("Hai account", orchestrator.safety_pause_reason)

    def test_terminal_state_freezes_elapsed_time_and_finishes_worker(self):
        orchestrator = DownloadOrchestrator()
        orchestrator.stats = DownloadStats(total_posts=1, completed_posts=1, success_posts=1, start_time=100.0)
        orchestrator._worker_account_ids = {7}
        orchestrator.account_statuses = {
            7: {"account_id": 7, "label": "Ready", "state": "working", "code": "READY", "message": "Đang tải"}
        }
        with patch("core.downloader.time.time", return_value=125.0):
            orchestrator._finish_run_state()
        self.assertEqual(orchestrator.stats.elapsed_seconds, 25.0)
        self.assertEqual(orchestrator.account_statuses[7]["state"], "completed")
        with patch("core.downloader.time.time", return_value=999.0):
            self.assertEqual(orchestrator.stats.elapsed_seconds, 25.0)
