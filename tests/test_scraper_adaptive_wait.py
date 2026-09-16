import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.page_scraper import PageScraper
from utils.logger import GUIHandler


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def advance(self, milliseconds):
        self.now += milliseconds / 1000


class FakePage:
    def __init__(self, clock, on_wait=None):
        self.clock = clock
        self.on_wait = on_wait
        self.waits = []
        self.scrolls = 0

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)
        self.clock.advance(milliseconds)
        if self.on_wait:
            self.on_wait(len(self.waits))

    def evaluate(self, _script):
        self.scrolls += 1


class FakeArchiveCollector(SimpleNamespace):
    def get_posts(self):
        return []


class AdaptiveScrollWaitTest(unittest.TestCase):
    def _scraper(self):
        return PageScraper()

    def test_wait_returns_soon_after_new_posts_settle(self):
        clock = FakeClock()
        collector = SimpleNamespace(count=0)

        def publish_after_first_poll(wait_count):
            if wait_count == 1:
                collector.count = 3

        page = FakePage(clock, publish_after_first_poll)
        with patch("core.page_scraper.time.monotonic", clock.monotonic):
            current, waited = self._scraper()._wait_for_scroll_result(page, collector, 0, 0)

        self.assertEqual(current, 3)
        self.assertGreaterEqual(waited, PageScraper._SCROLL_SETTLE_SECONDS)
        self.assertLess(waited, PageScraper._SCROLL_INITIAL_WAIT_SECONDS)

    def test_empty_scroll_uses_bounded_backoff(self):
        clock = FakeClock()
        collector = SimpleNamespace(count=0)
        page = FakePage(clock)
        with patch("core.page_scraper.time.monotonic", clock.monotonic):
            current, waited = self._scraper()._wait_for_scroll_result(page, collector, 0, 99)

        self.assertEqual(current, 0)
        self.assertGreaterEqual(waited, PageScraper._SCROLL_MAX_WAIT_SECONDS - 0.01)
        self.assertLessEqual(waited, PageScraper._SCROLL_MAX_WAIT_SECONDS + 0.01)

    def test_stop_interrupts_wait_without_waiting_for_timeout(self):
        clock = FakeClock()
        collector = SimpleNamespace(count=0)
        scraper = self._scraper()

        def stop_after_first_poll(wait_count):
            if wait_count == 1:
                scraper.request_stop()

        page = FakePage(clock, stop_after_first_poll)
        with patch("core.page_scraper.time.monotonic", clock.monotonic):
            current, waited = scraper._wait_for_scroll_result(page, collector, 0, 99)

        self.assertEqual(current, 0)
        self.assertLessEqual(waited, PageScraper._SCROLL_POLL_INTERVAL_MS / 1000)

    def test_normal_scan_preserves_time_grace_before_exhausted(self):
        clock = FakeClock()
        collector = SimpleNamespace(count=0)
        page = FakePage(clock)
        scraper = self._scraper()

        with patch("core.page_scraper.time.monotonic", clock.monotonic):
            reason = scraper._scroll_for_posts(page, collector, 50, None)

        self.assertEqual(reason, "exhausted")
        self.assertGreaterEqual(clock.now, PageScraper._SCROLL_EXHAUSTED_AFTER_SECONDS)
        self.assertGreaterEqual(page.scrolls, 12)

    def test_archive_scan_uses_the_same_adaptive_grace_period(self):
        clock = FakeClock()
        collector = FakeArchiveCollector(count=0)
        page = FakePage(clock)
        scraper = self._scraper()

        with patch("core.page_scraper.time.monotonic", clock.monotonic):
            reason = scraper._scroll_for_archive_posts(
                page, collector, 50, None, set(), {"saved-marker"}, None,
            )

        self.assertEqual(reason, "exhausted")
        self.assertGreaterEqual(clock.now, PageScraper._SCROLL_EXHAUSTED_AFTER_SECONDS)
        self.assertGreaterEqual(page.scrolls, 12)


class WebLogBridgeTest(unittest.TestCase):
    def test_gui_handler_forwards_raw_message_not_its_formatter(self):
        received = []
        handler = GUIHandler(lambda level, message: received.append((level, message)))
        handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "Scroll #10: +3 bài", (), None,
        )

        handler.emit(record)

        self.assertEqual(received, [("INFO", "Scroll #10: +3 bài")])


if __name__ == "__main__":
    unittest.main()
