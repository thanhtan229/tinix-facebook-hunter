import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

from core.account_preflight import check_facebook_account, resolve_download_profile
from core.downloader import DownloadOrchestrator
from core.facebook_parser import BrowserManager
from core.profile_lease import ProfileLeaseConflict, acquire_profile_leases, release_profile_leases


class AccountPreflightTest(unittest.TestCase):
    def test_profile_lease_rejects_another_background_task_until_released(self):
        account = {"id": 42, "profile_dir": "C:/profiles/lease-test", "is_active": 1}
        first = acquire_profile_leases("scan-test", [account])
        try:
            with self.assertRaises(ProfileLeaseConflict):
                acquire_profile_leases("download-test", [account])
        finally:
            release_profile_leases("scan-test", first)

        second = acquire_profile_leases("download-test", [account])
        release_profile_leases("download-test", second)

    @patch("core.account_preflight.scraper_profile_dir")
    def test_preflight_uses_the_same_default_profile_as_the_account_login_ui(self, scraper_profile_dir):
        scraper_profile_dir.return_value = "C:/profiles/scraper_42"

        profile_dir = resolve_download_profile({"id": 42})

        self.assertEqual(profile_dir, "C:/profiles/scraper_42")
        scraper_profile_dir.assert_called_once_with(42)

    def test_live_profile_session_is_not_overwritten_by_saved_cookie(self):
        context = MagicMock()
        browser_connection = MagicMock()
        browser_connection.contexts = [context]
        playwright_instance = MagicMock()
        playwright_instance.chromium.connect_over_cdp.return_value = browser_connection
        sync_playwright = MagicMock()
        sync_playwright.return_value.start.return_value = playwright_instance
        playwright_module = ModuleType("playwright")
        sync_api_module = ModuleType("playwright.sync_api")
        sync_api_module.sync_playwright = sync_playwright
        chrome_process = MagicMock()
        manager = BrowserManager(profile_dir="C:/profiles/ready", cdp_port=9742)

        with patch.dict("sys.modules", {
            "playwright": playwright_module,
            "playwright.sync_api": sync_api_module,
        }), patch("core.facebook_parser._find_chrome", return_value="C:/Chrome/chrome.exe"), patch(
            "subprocess.Popen", return_value=chrome_process
        ), patch("core.facebook_parser.time.sleep"), patch.object(
            manager, "_has_authenticated_facebook_session", return_value=True
        ) as session_check:
            self.assertTrue(manager.start({"c_user": "stale", "xs": "stale"}, require_authenticated=True))

        context.add_cookies.assert_not_called()
        session_check.assert_called_once()
        manager.stop()

    @patch("core.account_preflight.BrowserManager")
    def test_ready_account_requires_an_authenticated_browser_session(self, browser_cls):
        browser = browser_cls.return_value
        browser.start.return_value = True

        result = check_facebook_account({
            "id": 42, "label": "Ready", "is_active": 1,
            "cookie": "c_user=1; xs=test", "profile_dir": "C:/profiles/ready",
        })

        self.assertTrue(result.ready)
        self.assertEqual(result.code, "READY")
        browser.start.assert_called_once_with({"c_user": "1", "xs": "test"}, require_authenticated=True)
        browser.stop.assert_called_once()

    @patch("core.account_preflight.BrowserManager")
    def test_preflight_returns_safe_failure_reason(self, browser_cls):
        browser = browser_cls.return_value
        browser.start.return_value = False
        browser.last_start_error_code = "AUTH_EXPIRED"
        browser.last_start_error_message = "Cookie Facebook đã hết hạn hoặc cần xác nhận lại."

        result = check_facebook_account({"id": 7, "label": "Expired", "is_active": 1, "cookie": "c_user=1"})

        self.assertFalse(result.ready)
        self.assertEqual(result.code, "AUTH_EXPIRED")
        self.assertNotIn("c_user=1", result.message)


class FacebookSessionCheckTest(unittest.TestCase):
    def _check_session(self, url: str, login_form: bool = False) -> bool:
        context = MagicMock()
        page = MagicMock()
        page.url = url
        page.query_selector.return_value = object() if login_form else None
        context.new_page.return_value = page
        manager = BrowserManager()
        manager._context = context

        return manager._has_authenticated_facebook_session()

    def test_landing_page_without_login_form_is_not_treated_as_authenticated(self):
        self.assertFalse(self._check_session("https://www.facebook.com/"))

    def test_profile_redirect_is_treated_as_authenticated(self):
        self.assertTrue(self._check_session("https://www.facebook.com/profile.php?id=42"))

    def test_login_redirect_is_not_treated_as_authenticated(self):
        self.assertFalse(self._check_session("https://www.facebook.com/login/?next=%2Fme%2F"))

    def test_profile_page_with_login_form_is_not_treated_as_authenticated(self):
        self.assertFalse(self._check_session("https://www.facebook.com/profile.php?id=42", login_form=True))


class DownloadAttemptTest(unittest.TestCase):
    def test_retry_attempt_does_not_increment_final_failure_counter(self):
        orchestrator = DownloadOrchestrator()

        def simulated_failure(url, index, **_kwargs):
            orchestrator._notify_post_failed(url, index, "Không thể parse post: test")
            orchestrator._update_stats(failed=True)

        with patch.object(orchestrator, "_process_single_post", side_effect=simulated_failure):
            success, error = orchestrator._run_post_attempt(
                "https://www.facebook.com/watch/?v=12345678901", 1,
                object(), {}, "Test", 1, 1,
            )

        self.assertFalse(success)
        self.assertIn("Không thể parse post", error)
        self.assertEqual(orchestrator.stats.completed_posts, 0)
        self.assertEqual(orchestrator.stats.failed_posts, 0)

    def test_error_classification_keeps_invalid_urls_out_of_retry(self):
        self.assertEqual(
            DownloadOrchestrator._classify_download_error("URL không hợp lệ: thiếu post ID"),
            "POST_INVALID_URL",
        )
        self.assertEqual(
            DownloadOrchestrator._classify_download_error("Chỉ tải được thumbnail/caption, không tải được video"),
            "MEDIA_ACCESS_DENIED",
        )

    def test_preflight_stops_after_workers_and_one_ready_fallback(self):
        class FakeBrowser:
            def __init__(self, **_kwargs):
                self.last_start_error_code = ""
                self.last_start_error_message = ""

            def start(self, _cookies, require_authenticated=False):
                return True

            def stop(self):
                return None

        orchestrator = DownloadOrchestrator()
        orchestrator._max_threads = 1
        orchestrator.stats.total_posts = 1
        accounts = [
            {"id": account_id, "label": f"Account {account_id}", "is_active": 1}
            for account_id in (1, 2, 3, 4)
        ]
        ready = type("Result", (), {"ready": True, "code": "READY", "message": "Ready"})()
        with patch("core.downloader.BrowserManager", FakeBrowser), patch(
            "core.downloader.check_facebook_account", return_value=ready
        ) as preflight, patch("core.downloader.resolve_download_profile", return_value="profile"), patch.object(
            orchestrator, "_mark_urls_download_status"
        ), patch.object(orchestrator, "_mark_post_download_status"), patch.object(
            orchestrator, "_process_single_post", side_effect=lambda *_args, **_kwargs: orchestrator._update_stats()
        ):
            orchestrator._run_multi_account_pipeline(["https://facebook.com/1234567890123"], accounts)

        self.assertEqual(preflight.call_count, 2)
        self.assertEqual(orchestrator.stats.success_posts, 1)
