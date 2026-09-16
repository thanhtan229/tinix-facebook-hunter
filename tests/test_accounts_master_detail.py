import unittest
from unittest.mock import MagicMock, patch
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from web.app import app
from core.db_storage import initialize_database, add_account, get_account
from core.account_preflight import AccountPreflightResult
from web.routes import accounts as accounts_routes


class AccountsMasterDetailTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "tinix_test.db")
        initialize_database(self.db_path)
        self.client = TestClient(app, base_url="http://127.0.0.1")
        # Establish session cookies
        self.client.get("/")

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_accounts_ui_exposes_selected_preflight_control(self):
        static_root = Path(__file__).resolve().parents[1] / "web" / "static"
        html = (static_root / "index.html").read_text(encoding="utf-8")
        javascript = (static_root / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="btn-preflight-selected-accounts"', html)
        self.assertIn('class="account-list-column-header"', html)
        self.assertIn('id="btn-toggle-select-all-accounts"', html)
        self.assertIn('id="btn-toggle-select-favorite-accounts"', html)
        self.assertIn('class="account-column-name">Tài khoản', html)
        self.assertIn('class="account-column-status">Trạng thái', html)
        self.assertIn('class="account-column-actions">Thao tác', html)
        self.assertIn("checkSelectedAccountsPreflight", javascript)
        self.assertIn("toggleAccountPreflightSelection", javascript)
        self.assertIn("toggleAllVisibleAccountPreflightSelection", javascript)
        self.assertIn("toggleVisibleFavoriteAccountPreflightSelection", javascript)
        self.assertIn("selectedAccountIds", javascript)
        self.assertIn("Mất phiên", javascript)

        header_start = html.index('class="account-list-column-header-left"')
        header_end = html.index('class="account-column-name"', header_start)
        header = html[header_start:header_end]
        self.assertLess(header.index('id="btn-toggle-select-all-accounts"'), header.index('class="account-column-index"'))
        self.assertLess(header.index('id="btn-toggle-select-favorite-accounts"'), header.index('class="account-column-index"'))

    def test_preflight_failure_is_saved_for_account_list_status(self):
        with patch("web.routes.accounts.config.get", return_value=self.db_path):
            acc_id = add_account(
                self.db_path,
                label="Expired session",
                username="expired@example.com",
                is_active=1,
            )
            result = AccountPreflightResult(
                acc_id, "Expired session", "C:/profiles/expired", False,
                "AUTH_REQUIRED", "Profile chưa có phiên đăng nhập Facebook hợp lệ.",
            )
            with patch("web.routes.accounts.check_facebook_account", return_value=result):
                response = self.client.post(f"/api/accounts/{acc_id}/preflight")

            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["data"]["ready"])
            self.assertTrue(response.json()["data"]["checked_at"])
            updated = get_account(self.db_path, acc_id)
            self.assertEqual(updated["preflight_status"], "AUTH_REQUIRED")
            self.assertEqual(
                updated["preflight_message"],
                "Profile chưa có phiên đăng nhập Facebook hợp lệ.",
            )
            self.assertTrue(updated["preflight_checked_at"])

    def test_preflight_releases_a_stale_managed_profile_lease(self):
        with patch("web.routes.accounts.config.get", return_value=self.db_path):
            account_id = add_account(self.db_path, label="Stale profile", username="stale-profile@example.com")
            account = get_account(self.db_path, account_id)
            owner = f"manual-profile-{account_id}"
            lease_keys = accounts_routes.acquire_profile_leases(owner, [account])
            with accounts_routes._CHROME_PROCESS_LOCK:
                accounts_routes._CHROME_PROCESSES.pop(account_id, None)
                accounts_routes._MANAGED_PROFILE_LEASES[account_id] = (owner, lease_keys)
            result = AccountPreflightResult(
                account_id, "Stale profile", "", True, "READY", "Sẵn sàng",
            )
            try:
                with patch("web.routes.accounts.check_facebook_account", return_value=result):
                    response = self.client.post(f"/api/accounts/{account_id}/preflight")
                self.assertEqual(response.status_code, 200)
            finally:
                with accounts_routes._CHROME_PROCESS_LOCK:
                    stale = accounts_routes._MANAGED_PROFILE_LEASES.pop(account_id, None)
                if stale:
                    accounts_routes.release_profile_leases(*stale)

    def test_account_detail_hides_stored_credentials_until_explicit_reveal(self):
        with patch("web.routes.accounts.config.get", return_value=self.db_path):
            acc_id = add_account(
                self.db_path,
                label="Demo Account",
                username="demouser@example.com",
                email="demouser@example.com",
                password="MySecretPassword123",
                secret_2fa="JBSWY3DPEHPK3PXP",
                recovery_email="backup@example.com",
                recovery_codes="code1\ncode2\ncode3",
                cookie="c_user=12345; xs=test",
                notes="Important test note",
                is_active=1
            )
            self.assertGreater(acc_id, 0)

            res = self.client.get(f"/api/accounts/{acc_id}/detail")
            self.assertEqual(res.status_code, 200)
            data = res.json()["data"]
            self.assertEqual(data["label"], "Demo Account")
            self.assertEqual(data["username"], "demouser@example.com")
            self.assertEqual(data["recovery_email"], "backup@example.com")
            self.assertEqual(data["notes"], "Important test note")
            self.assertEqual(data["is_active"], 1)
            self.assertTrue(data["has_password"])
            self.assertTrue(data["has_2fa"])
            self.assertTrue(data["has_cookie"])
            self.assertTrue(data["has_recovery_codes"])
            for field in ("password", "secret_2fa", "cookie", "recovery_codes", "email_pass"):
                self.assertNotIn(field, data)

            revealed = self.client.post(f"/api/accounts/{acc_id}/secret/cookie")
            self.assertEqual(revealed.status_code, 200)
            self.assertEqual(revealed.json()["data"]["value"], "c_user=12345; xs=test")
            self.assertIn("port", data)
            self.assertIn("is_chrome_running", data)

    def test_save_account_updates_existing_directly(self):
        with patch("web.routes.accounts.config.get", return_value=self.db_path):
            acc_id = add_account(
                self.db_path,
                label="Old Name",
                username="olduser@example.com",
                email="olduser@example.com",
                is_active=1
            )

            # Update directly via POST /api/accounts/save
            update_payload = {
                "id": acc_id,
                "label": "New Name",
                "email": "newuser@example.com",
                "recovery_email": "rec@example.com",
                "recovery_codes": "c1\nc2",
                "notes": "Updated note",
                "is_active": False
            }
            res = self.client.post("/api/accounts/save", json=update_payload)
            self.assertEqual(res.status_code, 200)

            updated = get_account(self.db_path, acc_id)
            self.assertEqual(updated["label"], "New Name")
            self.assertEqual(updated["email"], "newuser@example.com")
            self.assertEqual(updated["recovery_email"], "rec@example.com")
            self.assertEqual(updated["recovery_codes"], "c1\nc2")
            self.assertEqual(updated["notes"], "Updated note")
            self.assertEqual(updated["is_active"], 0)

    def test_clear_credentials_endpoint(self):
        with patch("web.routes.accounts.config.get", return_value=self.db_path):
            acc_id = add_account(
                self.db_path,
                label="Cred Account",
                username="creds@example.com",
                password="password",
                secret_2fa="2fakey",
                cookie="cookie_data",
                recovery_codes="rec1\nrec2"
            )

            # Clear credentials
            res = self.client.post("/api/accounts/clear-credentials", json={"account_id": acc_id})
            self.assertEqual(res.status_code, 200)

            account = get_account(self.db_path, acc_id)
            self.assertEqual(account["password"], "")
            self.assertEqual(account["secret_2fa"], "")
            self.assertEqual(account["cookie"], "")
            self.assertEqual(account["recovery_codes"], "")

    def test_account_profile_browser_falls_back_to_microsoft_edge(self):
        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        with patch("web.routes.accounts.os.path.exists", side_effect=lambda path: path == edge_path), patch(
            "web.routes.accounts.shutil.which", return_value=None
        ):
            self.assertEqual(accounts_routes._find_chrome_path(), edge_path)

    def test_launch_profile_reports_missing_supported_browser(self):
        with patch("web.routes.accounts.config.get", return_value=self.db_path):
            account_id = add_account(self.db_path, label="Browser test", username="browser-test@example.com")
            with patch("web.routes.accounts._find_browser_paths", return_value=[]):
                response = self.client.post("/api/accounts/launch", json={"account_id": account_id})

        self.assertEqual(response.status_code, 503)
        self.assertIn("Google Chrome hoặc Microsoft Edge", response.json()["detail"])

    def test_launch_profile_uses_microsoft_edge_when_chrome_is_unavailable(self):
        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        process = MagicMock()
        process.poll.return_value = None
        account_id = 0
        try:
            with patch("web.routes.accounts.config.get", return_value=self.db_path):
                account_id = add_account(self.db_path, label="Edge test", username="edge-test@example.com")
                with patch("web.routes.accounts._find_browser_paths", return_value=[edge_path]), patch(
                    "web.routes.accounts.subprocess.Popen", return_value=process
                ) as launch, patch(
                    "web.routes.accounts.scraper_profile_dir", return_value=Path(self.temp_dir.name) / "edge-profile"
                ), patch(
                    "web.routes.accounts._wait_for_cdp_port", return_value=True
                ):
                    response = self.client.post("/api/accounts/launch", json={"account_id": account_id})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["browser_label"], "Microsoft Edge")
            command = launch.call_args.args[0]
            self.assertEqual(command[0], edge_path)
            self.assertIn("--remote-allow-origins=*", command)
        finally:
            with accounts_routes._CHROME_PROCESS_LOCK:
                accounts_routes._CHROME_PROCESSES.pop(account_id, None)

    def test_launch_profile_falls_back_to_edge_after_chrome_crashes(self):
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        crashed_chrome = MagicMock()
        edge_process = MagicMock()
        account_id = 0
        try:
            with patch("web.routes.accounts.config.get", return_value=self.db_path):
                account_id = add_account(self.db_path, label="Fallback test", username="fallback-test@example.com")
                with patch("web.routes.accounts._find_browser_paths", return_value=[chrome_path, edge_path]), patch(
                    "web.routes.accounts.subprocess.Popen", side_effect=[crashed_chrome, edge_process]
                ) as launch, patch(
                    "web.routes.accounts.scraper_profile_dir", return_value=Path(self.temp_dir.name) / "fallback-profile"
                ), patch(
                    "web.routes.accounts._wait_for_cdp_port", side_effect=[False, True]
                ), patch("web.routes.accounts._stop_failed_browser_process") as stop_failed:
                    response = self.client.post("/api/accounts/launch", json={"account_id": account_id})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["browser_label"], "Microsoft Edge")
            self.assertEqual(launch.call_count, 2)
            self.assertEqual(launch.call_args_list[1].args[0][0], edge_path)
            stop_failed.assert_called_once_with(crashed_chrome)
        finally:
            with accounts_routes._CHROME_PROCESS_LOCK:
                accounts_routes._CHROME_PROCESSES.pop(account_id, None)

    def test_launch_profile_retries_breakpoint_crash_with_gpu_disabled(self):
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        breakpoint_process = MagicMock()
        breakpoint_process.poll.return_value = -2147483645  # 0x80000003
        recovered_process = MagicMock()
        recovered_process.poll.return_value = None
        account_id = 0
        try:
            with patch("web.routes.accounts.config.get", return_value=self.db_path):
                account_id = add_account(self.db_path, label="GPU retry", username="gpu-retry@example.com")
                with patch("web.routes.accounts._find_browser_paths", return_value=[chrome_path]), patch(
                    "web.routes.accounts.subprocess.Popen", side_effect=[breakpoint_process, recovered_process]
                ) as launch, patch(
                    "web.routes.accounts.scraper_profile_dir", return_value=Path(self.temp_dir.name) / "gpu-profile"
                ), patch(
                    "web.routes.accounts._wait_for_cdp_port", side_effect=[False, True]
                ), patch("web.routes.accounts._stop_failed_browser_process") as stop_failed:
                    response = self.client.post("/api/accounts/launch", json={"account_id": account_id})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["browser_label"], "Google Chrome")
            self.assertEqual(response.json()["recovery_mode"], "gpu_disabled")
            self.assertEqual(launch.call_count, 2)
            self.assertNotIn("--disable-gpu", launch.call_args_list[0].args[0])
            self.assertIn("--disable-gpu", launch.call_args_list[1].args[0])
            stop_failed.assert_called_once_with(breakpoint_process)
        finally:
            with accounts_routes._CHROME_PROCESS_LOCK:
                accounts_routes._CHROME_PROCESSES.pop(account_id, None)

    def test_launch_profile_reports_breakpoint_diagnostic(self):
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        breakpoint_process = MagicMock()
        breakpoint_process.poll.return_value = -2147483645  # 0x80000003
        recovery_process = MagicMock()
        recovery_process.poll.return_value = -2147483645
        with patch("web.routes.accounts.config.get", return_value=self.db_path):
            account_id = add_account(self.db_path, label="Breakpoint", username="breakpoint@example.com")
            with patch("web.routes.accounts._find_browser_paths", return_value=[chrome_path]), patch(
                "web.routes.accounts.subprocess.Popen", side_effect=[breakpoint_process, recovery_process]
            ), patch(
                "web.routes.accounts.scraper_profile_dir", return_value=Path(self.temp_dir.name) / "breakpoint-profile"
            ), patch(
                "web.routes.accounts._wait_for_cdp_port", return_value=False
            ), patch("web.routes.accounts._stop_failed_browser_process"):
                response = self.client.post("/api/accounts/launch", json={"account_id": account_id})

        self.assertEqual(response.status_code, 500)
        self.assertIn("STATUS_BREAKPOINT", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
