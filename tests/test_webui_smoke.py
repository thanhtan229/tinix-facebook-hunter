"""Browser smoke coverage for the local WebUI without Facebook access."""

import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import uvicorn
from playwright.sync_api import sync_playwright

from web.app import app
from core.db_storage import add_account, initialize_database


class WebUiSmokeTest(unittest.TestCase):
    def test_local_webui_loads_onboarding_and_scan_controls(self):
        """Open the real WebUI with isolated storage and assert its key startup controls."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = str(root / "smoke.db")
            output_dir = str(root / "downloads")
            initialize_database(db_path)
            add_account(
                db_path,
                label="Smoke Account",
                username="smoke@example.com",
                password="password-smoke",
                secret_2fa="JBSWY3DPEHPK3PXP",
                cookie="c_user=12345; xs=smoke",
                recovery_codes="code-one\ncode-two",
            )
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]

            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))

            def config_value(key, default=None):
                return output_dir if key == "output_dir" else default

            with patch.dict(os.environ, {"TINIX_DB_PATH": db_path}), patch(
                "web.app.config.get", side_effect=config_value
            ):
                thread = threading.Thread(target=server.run, daemon=True)
                thread.start()
                try:
                    deadline = time.monotonic() + 15
                    while not server.started and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertTrue(server.started, "WebUI did not start for browser smoke test")

                    page_errors: list[str] = []
                    with sync_playwright() as playwright:
                        browser = playwright.chromium.launch(channel="chrome", headless=True)
                        page = browser.new_page()
                        download_state = {"paused": False}

                        def download_status_route(route):
                            route.fulfill(
                                status=200,
                                content_type="application/json",
                                body=(
                                    '{"status":"success","data":'
                                    '{"is_running":true,"is_paused":'
                                    f'{str(download_state["paused"]).lower()},'
                                    '"pending_auto_downloads":{"batches":0,"items":0,"running_batches":0}}}'
                                ),
                            )

                        def pause_route(route):
                            download_state["paused"] = True
                            route.fulfill(status=200, content_type="application/json", body='{"status":"success","message":"Đã tạm dừng"}')

                        def resume_route(route):
                            download_state["paused"] = False
                            route.fulfill(status=200, content_type="application/json", body='{"status":"success","message":"Đã tiếp tục"}')

                        page.route("**/api/download/status", download_status_route)
                        page.route("**/api/download/pause", pause_route)
                        page.route("**/api/download/resume", resume_route)
                        page.on("pageerror", lambda error: page_errors.append(str(error)))
                        page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
                        page.locator("#app-version-badge").wait_for(timeout=10000)
                        page.wait_for_function(
                            "document.querySelector('#ws-badge')?.textContent.includes('Realtime Connected')",
                            timeout=10000,
                        )
                        page.locator("#scrape-auto-download").wait_for(state="attached", timeout=10000)
                        self.assertTrue(page.locator("#scrape-auto-download").is_checked())
                        self.assertTrue(page.locator("#btn-stop-all-dl").is_visible())
                        page.locator("#btn-pause-dl").wait_for(timeout=10000)
                        self.assertTrue(page.locator("#btn-pause-dl").is_enabled())
                        self.assertEqual(page.locator("#btn-pause-dl").inner_text(), "⏸ Tạm dừng")
                        page.locator("#btn-pause-dl").click()
                        page.wait_for_timeout(100)
                        self.assertEqual(page.locator("#btn-pause-dl").inner_text(), "▶ Tiếp tục")
                        self.assertTrue(download_state["paused"])
                        page.locator("#btn-pause-dl").click()
                        page.wait_for_timeout(100)
                        self.assertEqual(page.locator("#btn-pause-dl").inner_text(), "⏸ Tạm dừng")
                        self.assertFalse(download_state["paused"])
                        self.assertTrue(page.locator("#dl-account-picker").is_visible())
                        page.locator("#dl-account-picker-summary").click()
                        self.assertTrue(page.locator("#dl-account-ids").is_visible())
                        self.assertEqual(page.locator("#dl-account-ids select").count(), 0)
                        page.locator('[data-tab="tab-spy"]').click()
                        self.assertTrue(page.locator("#btn-retry-spy-posts").is_visible())
                        self.assertEqual(page.locator('#spy-dl-status option[value="Đang tải"]').count(), 1)
                        self.assertEqual(page.locator('#spy-dl-status option[value="Thiếu video"]').count(), 1)
                        self.assertTrue(page.locator("#btn-clear-dl-queue").is_hidden())
                        self.assertTrue(page.locator("#system-readiness").is_hidden())
                        page.locator("#btn-settings-modal").click()
                        self.assertTrue(page.locator("#generic-modal").is_visible())
                        self.assertTrue(page.locator("#setting-output-dir").is_visible())
                        page.locator("#btn-close-modal").click()
                        self.assertFalse(page.locator("#generic-modal").is_visible())
                        page.evaluate("renderSystemReadiness({ready:false,checks:{chrome:false}}, true)")
                        self.assertTrue(page.locator("#system-readiness").is_visible())
                        self.assertIn("Google Chrome", page.locator("#system-readiness-message").inner_text())
                        page.evaluate("renderSystemReadiness({ready:true,checks:{chrome:true}}, true)")
                        self.assertTrue(page.locator("#system-readiness").is_hidden())
                        page.route("**/api/accounts/", lambda route: route.fulfill(
                            status=200, content_type="application/json", body='{"status":"success","data":[]}'
                        ))
                        page.locator('[data-tab="tab-downloader"]').click()
                        page.locator("#dl-urls").fill("https://www.facebook.com/123456789012345")
                        page.locator("#dl-use-accounts").check()
                        page.locator("#btn-start-dl").click()
                        page.wait_for_function("document.querySelector('#tab-accounts').classList.contains('active')")
                        page.unroute("**/api/accounts/")
                        page.evaluate("loadAccounts()")
                        page.locator('[data-tab="tab-accounts"]').click()
                        self.assertTrue(page.locator("#tab-accounts").evaluate("node => node.classList.contains('active')"))
                        page.wait_for_function(
                            "document.querySelector('#detail-input-label')?.value === 'Smoke Account'",
                            timeout=10000,
                        )
                        for field_id, button_id in (
                            ("detail-input-password", "btn-toggle-password"),
                            ("detail-input-2fa", "btn-toggle-2fa"),
                            ("detail-input-recovery-codes", None),
                            ("detail-input-cookie", None),
                        ):
                            field = page.locator(f"#{field_id}")
                            button = (
                                page.locator(f"#{button_id}")
                                if button_id else field.locator("xpath=following-sibling::button")
                            )
                            self.assertEqual(field.input_value(), "")
                            button.click()
                            page.wait_for_function(
                                "fieldId => document.querySelector(`#${fieldId}`)?.dataset.secretVisible === 'true'",
                                arg=field_id,
                                timeout=10000,
                            )
                            self.assertEqual(button.inner_text(), "Hide")
                            self.assertTrue(bool(field.input_value()))
                            button.click()
                            page.wait_for_function(
                                "fieldId => !document.querySelector(`#${fieldId}`)?.dataset.secretVisible",
                                arg=field_id,
                                timeout=10000,
                            )
                            self.assertEqual(button.inner_text(), "Show")
                            self.assertEqual(field.input_value(), "")

                            local_value = f"unsaved-{field_id}"
                            field.fill(local_value)
                            button.click()
                            page.wait_for_function(
                                "fieldId => document.querySelector(`#${fieldId}`)?.dataset.secretVisible === 'true'",
                                arg=field_id,
                                timeout=10000,
                            )
                            button.click()
                            page.wait_for_function(
                                "fieldId => !document.querySelector(`#${fieldId}`)?.dataset.secretVisible",
                                arg=field_id,
                                timeout=10000,
                            )
                            self.assertEqual(field.input_value(), local_value)
                            if field_id in ("detail-input-password", "detail-input-2fa"):
                                self.assertEqual(field.get_attribute("type"), "password")
                        self.assertIn("scheduleSessionRecovery", page.locator("body").evaluate("() => window.scheduleSessionRecovery?.name || ''"))
                        page.evaluate("fetch('/api/system/stats', { credentials: 'omit' })")
                        page.wait_for_timeout(700)
                        page.wait_for_function(
                            "document.querySelector('#ws-badge')?.textContent.includes('Realtime Connected')",
                            timeout=10000,
                        )
                        self.assertTrue(
                            page.evaluate("Number(sessionStorage.getItem('tinix.session-recovery-at') || 0) > 0")
                        )
                        self.assertEqual(page_errors, [])
                        browser.close()
                finally:
                    server.should_exit = True
                    thread.join(timeout=10)
                    self.assertFalse(thread.is_alive(), "WebUI server did not stop after browser smoke test")


if __name__ == "__main__":
    unittest.main()
