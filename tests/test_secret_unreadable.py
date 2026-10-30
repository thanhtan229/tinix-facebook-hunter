"""Regression: undecryptable stored credentials must be reported, not silently blanked."""

import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.account_preflight import check_facebook_account
from core.db_storage import add_account, get_all_accounts, initialize_database


def _undecryptable_value() -> str:
    # Same prefix as a real DPAPI value, but the bytes are not a DPAPI blob for this user.
    return "dpapi:v1:" + base64.urlsafe_b64encode(b"not-a-real-dpapi-blob").decode("ascii")


class SecretUnreadableTests(unittest.TestCase):
    def _db_with_corrupted_password(self, directory: str) -> tuple[str, int]:
        db_path = str(Path(directory) / "tinix.db")
        initialize_database(db_path)
        account_id = add_account(db_path, label="Mất khóa", username="demo", password="pw-original", cookie="")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("UPDATE fb_accounts SET password = ? WHERE id = ?", (_undecryptable_value(), account_id))
            conn.commit()
        finally:
            conn.close()
        return db_path, account_id

    def test_get_all_accounts_flags_unreadable_password(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path, account_id = self._db_with_corrupted_password(directory)
            account = next(item for item in get_all_accounts(db_path) if item["id"] == account_id)

        self.assertEqual(account["password"], "")
        self.assertEqual(account["secrets_unreadable"], ["password"])

    def test_readable_account_has_no_unreadable_flags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "tinix.db")
            initialize_database(db_path)
            account_id = add_account(db_path, label="OK", username="demo", password="pw-ok")
            account = next(item for item in get_all_accounts(db_path) if item["id"] == account_id)

        self.assertEqual(account["password"], "pw-ok")
        self.assertEqual(account["secrets_unreadable"], [])

    def _run_preflight(self, account: dict, browser_starts: bool):
        browser = MagicMock()
        browser.start.return_value = browser_starts
        browser.last_start_error_code = "" if browser_starts else "AUTH_EXPIRED"
        browser.last_start_error_message = "" if browser_starts else "Phiên hết hạn"
        with (
            patch("core.account_preflight.resolve_download_profile", return_value="C:/tmp/profile"),
            patch("core.account_preflight.BrowserManager", return_value=browser),
        ):
            return check_facebook_account(account), browser

    def test_unreadable_password_does_not_block_account_with_valid_session(self) -> None:
        account = {"id": 7, "label": "Có phiên", "is_active": 1, "cookie": "", "secrets_unreadable": ["password"]}

        result, browser = self._run_preflight(account, browser_starts=True)

        self.assertTrue(result.ready)
        self.assertEqual(result.code, "READY")
        browser.start.assert_called_once()

    def test_unreadable_cookie_with_expired_session_reports_secret_unreadable(self) -> None:
        account = {"id": 7, "label": "Mất cookie", "is_active": 1, "cookie": "", "secrets_unreadable": ["cookie"]}

        result, _ = self._run_preflight(account, browser_starts=False)

        self.assertFalse(result.ready)
        self.assertEqual(result.code, "SECRET_UNREADABLE")
        self.assertIn("cookie", result.message)


if __name__ == "__main__":
    unittest.main()
