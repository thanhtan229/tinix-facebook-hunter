"""Chrome shutdown must finish before a shared profile is handed to downloading."""

import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.facebook_parser import BrowserManager
from core.page_scraper import PageScraper
from utils import chrome_profiles
from web.routes import scraper as scraper_routes


def test_shutdown_sends_browser_close_and_waits_for_cdp_to_disappear(monkeypatch):
    browser = MagicMock()
    process = MagicMock()
    responses = [MagicMock(), OSError("connection refused")]
    with patch.object(chrome_profiles.urllib.request, "urlopen", side_effect=responses) as probe, patch.object(
        chrome_profiles.time, "sleep"
    ):
        chrome_profiles.shutdown_owned_chrome(browser, process, 9409)
    browser.new_browser_cdp_session.return_value.send.assert_called_once_with("Browser.close")
    process.wait.assert_called_once_with(timeout=5)
    assert probe.call_count == 2
    assert probe.call_args.args[0] == "http://127.0.0.1:9409/json/version"


def test_shutdown_kills_only_owned_process_and_waits_after_timeout():
    process = MagicMock()
    process.wait.side_effect = [subprocess.TimeoutExpired("chrome", 5), subprocess.TimeoutExpired("chrome", 5), 0]
    with patch.object(chrome_profiles.urllib.request, "urlopen", side_effect=OSError):
        chrome_profiles.shutdown_owned_chrome(None, process, 9409)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 3


def test_shutdown_refuses_handoff_when_cdp_stays_alive():
    with patch.object(chrome_profiles.urllib.request, "urlopen", return_value=MagicMock()):
        with pytest.raises(RuntimeError, match="bàn giao profile"):
            chrome_profiles.shutdown_owned_chrome(MagicMock(), MagicMock(), 9409, timeout=0)


@pytest.mark.parametrize("manager_class,module", [
    (PageScraper, "core.page_scraper"), (BrowserManager, "core.facebook_parser"),
])
def test_both_workers_close_owned_chrome_before_stopping_playwright(manager_class, module):
    manager = manager_class()
    manager._browser = MagicMock()
    manager._chrome_process = MagicMock()
    manager._pw_instance = MagicMock()
    events = []
    manager._pw_instance.stop.side_effect = lambda: events.append("playwright stop")
    with patch(module + ".shutdown_owned_chrome", side_effect=lambda *args: events.append("chrome closed")):
        manager.stop()
    assert events == ["chrome closed", "playwright stop"]
    assert manager._browser is None and manager._chrome_process is None


def test_scraper_preserves_reused_browser():
    scraper = PageScraper()
    browser = MagicMock()
    scraper._browser = browser
    scraper._reused_browser = True
    with patch("core.page_scraper.shutdown_owned_chrome") as shutdown:
        scraper.stop()
    shutdown.assert_not_called()
    browser.close.assert_not_called()


def test_scraper_reports_failed_handoff_after_stopping_playwright():
    scraper = PageScraper()
    scraper._browser = MagicMock()
    playwright = MagicMock()
    scraper._pw_instance = playwright
    with patch("core.page_scraper.shutdown_owned_chrome", side_effect=RuntimeError("handoff failed")):
        with pytest.raises(RuntimeError, match="handoff failed"):
            scraper.stop()
    playwright.stop.assert_called_once()


def test_failed_quick_worker_shutdown_discards_auto_download_urls(monkeypatch):
    worker = MagicMock()
    worker.scrape_page.return_value = [SimpleNamespace(page_name="Demo")]
    worker.stop.side_effect = RuntimeError("profile still in use")
    monkeypatch.setattr(scraper_routes, "PageScraper", lambda **kwargs: worker)
    monkeypatch.setattr(scraper_routes.config, "get", lambda *args: "")
    monkeypatch.setattr(scraper_routes, "_resolve_scraped_page_name", lambda *args: "Demo")
    monkeypatch.setattr(scraper_routes, "save_posts", lambda **kwargs: 1)
    monkeypatch.setattr(scraper_routes, "_downloadable_post_urls", lambda *args: ["https://facebook.com/123"])
    monkeypatch.setattr(scraper_routes, "_stop_requested", threading.Event())
    monkeypatch.setattr(scraper_routes, "_favorite_worker_stop_events", {"worker": threading.Event()})
    monkeypatch.setattr(scraper_routes, "_active_favorite_scrapers", {})
    outcomes = []
    monkeypatch.setattr(scraper_routes, "_record_scrape_page_result", outcomes.append)
    status = {"workers": {"worker": {}}, "new_posts": 0}
    monkeypatch.setattr(scraper_routes, "_scrape_status", status)
    queue = {
        "worker_id": "worker", "account_label": "Test",
        "page_urls": ["https://facebook.com/demo", "https://facebook.com/next"],
        "mode": "All", "scan_limit": 1, "delay_profile": {}, "download_media": True,
        "download_urls": [],
    }
    assert scraper_routes._run_quick_worker(queue) == 1
    assert queue["download_urls"] == []
    assert status["workers"]["worker"]["status"] == "Lỗi"
    assert outcomes == [False]
    worker.scrape_page.assert_called_once()
