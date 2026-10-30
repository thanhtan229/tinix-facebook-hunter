"""Regression: profile-blocked auto-download retries must back off instead of polling every 5 seconds forever."""

import unittest

import web.routes.downloader as downloader


class PendingRetryBackoffTests(unittest.TestCase):
    def setUp(self) -> None:
        downloader._pending_auto_download_retry_attempts = 0

    def tearDown(self) -> None:
        downloader._pending_auto_download_retry_attempts = 0

    def test_delay_doubles_then_caps_at_five_minutes(self) -> None:
        delays = [downloader._next_pending_retry_delay() for _ in range(9)]

        self.assertEqual(delays, [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 300.0, 300.0, 300.0])

    def test_attempt_counter_stays_bounded_over_long_blockage(self) -> None:
        for _ in range(1000):
            downloader._next_pending_retry_delay()

        self.assertLessEqual(downloader._pending_auto_download_retry_attempts, 16)
        self.assertEqual(downloader._next_pending_retry_delay(), 300.0)


if __name__ == "__main__":
    unittest.main()
