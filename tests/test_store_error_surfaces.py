"""Regression: an unreadable account table must never strand a batch, hide Chrome cleanup, or look like success."""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from core.db_storage import AccountStoreError
import web.routes.accounts as accounts_routes
import web.routes.downloader as downloader


class AccountStoreErrorSurfaceTests(unittest.TestCase):
    def test_batch_returns_to_queue_when_accounts_cannot_be_read(self) -> None:
        batch = {"id": 7, "urls": ["https://www.facebook.com/example/posts/1"], "account_ids": [3]}
        with (
            patch.object(downloader, "_db_path", return_value="unused.db"),
            patch.object(downloader, "_active_accounts_for_ids", side_effect=AccountStoreError("db locked")),
            patch.object(downloader, "set_download_queue_batch_status") as set_status,
            patch.object(downloader, "_schedule_pending_auto_download_retry") as schedule,
            patch.object(downloader, "acquire_profile_leases") as acquire,
        ):
            started = downloader._start_claimed_auto_batch(batch)

        self.assertFalse(started)
        set_status.assert_called_once()
        args, kwargs = set_status.call_args
        self.assertEqual(args[1], 7)
        self.assertEqual(args[2], "queued", "batch must return to queued, never stay in starting")
        schedule.assert_called_once()
        acquire.assert_not_called()

    def test_close_all_still_closes_tracked_windows_when_accounts_unreadable(self) -> None:
        with (
            patch.object(accounts_routes, "get_db_path", return_value="unused.db"),
            patch.object(accounts_routes, "get_all_accounts", side_effect=AccountStoreError("db locked")),
            patch.object(accounts_routes, "_close_managed_chrome", return_value=True) as close,
            patch.object(accounts_routes, "log_to_web"),
            patch.dict(accounts_routes._CHROME_PROCESSES, {5: object()}, clear=True),
        ):
            result = accounts_routes.close_all_chrome_profiles(MagicMock())

        self.assertEqual(result["closed_count"], 1)
        close.assert_called_once_with(5)

    def test_app_maps_account_store_error_to_503_with_clear_message(self) -> None:
        from web.app import account_store_error_handler, app

        self.assertIn(AccountStoreError, app.exception_handlers, "handler must be registered on the app")
        response = asyncio.run(account_store_error_handler(MagicMock(), AccountStoreError("db locked")))

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Kh", response.body)


if __name__ == "__main__":
    unittest.main()
