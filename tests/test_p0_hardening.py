import tempfile
import unittest
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from starlette.testclient import TestClient

from core.db_storage import (
    SCHEMA_VERSION,
    _get_conn,
    add_account,
    add_social_account,
    get_all_accounts,
    get_all_managed_pages,
    get_db_path,
    get_db_stats,
    get_schedule_history_filtered,
    get_account,
    get_favorite_pages,
    finish_favorite_scan,
    migrate_secrets_at_rest,
    initialize_database,
    rebase_missing_social_profile_paths,
    recover_interrupted_webui_jobs,
    save_managed_pages,
    save_favorite_page,
    reset_favorite_cursor,
)
from web.app import app
from web.routes.accounts import _public_account
from web.routes import accounts as accounts_routes
from web.routes import scraper as scraper_routes
from web.routes.system import _public_config
from web.routes.poster import PersistScheduleRequest, persist_schedule_endpoint
from web.security import register_media_root, resolve_media_file
from core.post_queue import PostQueueRunner
from core.database_maintenance import create_database_backup, inspect_database, restore_database
from utils.secure_store import is_protected, protect_secret, unprotect_secret
from utils import config as app_config


class FakePoster:
    calls = []

    def __init__(self, account, headless=False):
        self.account = account
        self.headless = headless
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

    def post_content(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return True


class SecurityHelpersTest(unittest.TestCase):
    def test_close_managed_chrome_uses_cdp_and_forgets_tracked_process(self):
        class FinishedProcess:
            def poll(self):
                return 0

        accounts_routes._CHROME_PROCESSES[77] = FinishedProcess()
        with patch.object(accounts_routes, "_close_chrome_via_cdp", return_value=True) as close_cdp:
            self.assertTrue(accounts_routes._close_managed_chrome(77))
        close_cdp.assert_called_once_with(accounts_routes._chrome_debug_port(77))
        self.assertNotIn(77, accounts_routes._CHROME_PROCESSES)

    def test_dpapi_round_trip(self):
        encrypted = protect_secret("Tinix secret ✓")
        self.assertTrue(is_protected(encrypted))
        self.assertEqual(unprotect_secret(encrypted), "Tinix secret ✓")

    def test_public_account_does_not_expose_secrets(self):
        public = _public_account({
            "id": 7,
            "username": "demo",
            "password": "password-value",
            "secret_2fa": "2fa-value",
            "email_pass": "mail-value",
            "cookie": "cookie-value",
            "profile_dir": "D:/private/chrome-profile",
        })
        for field in ("password", "secret_2fa", "email_pass", "cookie"):
            self.assertNotIn(field, public)
        self.assertNotIn("profile_dir", public)
        self.assertTrue(public["has_password"])
        self.assertTrue(public["has_2fa"])
        self.assertTrue(public["has_cookie"])

    def test_public_config_does_not_expose_cookie(self):
        public = _public_config({"output_dir": "D:/output", "saved_cookies": "secret"})
        self.assertNotIn("saved_cookies", public)
        self.assertTrue(public["has_saved_cookies"])

    def test_config_persists_cookie_encrypted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            with patch.object(app_config, "_config_path", config_path), patch.object(
                app_config, "_config_cache", None
            ):
                app_config.save_config({"output_dir": "D:/output", "saved_cookies": "cookie-secret"})
                raw = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertTrue(is_protected(raw["saved_cookies"]))
                app_config._config_cache = None
                loaded = app_config.load_config()
                self.assertEqual(loaded["saved_cookies"], "cookie-secret")

    def test_media_must_be_below_registered_root(self):
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as denied:
            allowed_file = Path(allowed) / "preview.jpg"
            denied_file = Path(denied) / "secret.jpg"
            allowed_file.write_bytes(b"preview")
            denied_file.write_bytes(b"secret")
            register_media_root(allowed)
            self.assertEqual(resolve_media_file(allowed_file), allowed_file.resolve())
            self.assertIsNone(resolve_media_file(denied_file))


class ApiSessionTest(unittest.TestCase):
    def _temporary_database(self, temp_dir):
        db_path = str(Path(temp_dir) / "api.db")

        def value(key, default=None):
            return db_path if key == "scraper_db_path" else default

        return patch("web.app.config.get", side_effect=value)

    def test_api_requires_browser_session(self):
        with tempfile.TemporaryDirectory() as temp_dir, self._temporary_database(temp_dir):
            with TestClient(app) as client:
                response = client.get("/api/system/stats")
                self.assertEqual(response.status_code, 401)

    def test_root_establishes_session_and_rejects_foreign_origin(self):
        with tempfile.TemporaryDirectory() as temp_dir, self._temporary_database(temp_dir):
            with TestClient(app) as client:
                self.assertEqual(client.get("/").status_code, 200)
                self.assertIn("no-store", client.get("/").headers["cache-control"])
                self.assertEqual(client.get("/api/system/stats").status_code, 200)
                response = client.post(
                    "/api/system/open-folder",
                    json={},
                    headers={"Origin": "https://attacker.invalid"},
                )
                self.assertEqual(response.status_code, 403)

    def test_validation_error_does_not_echo_request_secrets(self):
        marker = "DO-NOT-ECHO-THIS-COOKIE"
        with tempfile.TemporaryDirectory() as temp_dir, self._temporary_database(temp_dir):
            with TestClient(app) as client:
                client.get("/")
                response = client.post(
                    "/api/accounts/save",
                    json={"username": "demo", "cookie": {"secret": marker}},
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["status"], "error")
                self.assertNotIn(marker, response.text)

    def test_health_reports_schema_without_private_database_path(self):
        with tempfile.TemporaryDirectory() as temp_dir, self._temporary_database(temp_dir):
            with TestClient(app) as client:
                client.get("/")
                response = client.get("/api/system/health")
                self.assertEqual(response.status_code, 200)
                payload = response.json()["data"]
                self.assertTrue(payload["checks"]["database"])
                self.assertNotIn(str(Path(temp_dir)), response.text)

    def test_favorite_page_api_saves_normalized_public_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "favorite-api.db")
            with patch.object(
                scraper_routes.config, "get",
                side_effect=lambda key, default=None: db_path if key == "scraper_db_path" else default,
            ):
                with TestClient(app) as client:
                    client.get("/")
                    saved = client.post(
                        "/api/scrape/favorites/save",
                        json={"page_url": "https://facebook.com/api-demo/posts", "scan_limit": 75},
                    )
                    listed = client.get("/api/scrape/favorites")
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(listed.status_code, 200, listed.text)
            favorite = listed.json()["data"][0]
            self.assertEqual(favorite["page_url"], "https://www.facebook.com/api-demo")
            self.assertEqual(favorite["scan_limit"], 75)


class DatabaseBootstrapTest(unittest.TestCase):
    def test_schema_v3_removes_legacy_proxy_storage_with_verified_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "legacy-proxy.db")
            initialize_database(db_path)
            conn = _get_conn(db_path)
            conn.execute("ALTER TABLE fb_accounts ADD COLUMN proxy_id INTEGER DEFAULT NULL")
            conn.execute("ALTER TABLE social_accounts ADD COLUMN proxy_id INTEGER DEFAULT NULL")
            conn.execute(
                "CREATE TABLE proxies (id INTEGER PRIMARY KEY, host TEXT NOT NULL, auth_pass TEXT NOT NULL DEFAULT '')"
            )
            conn.execute("PRAGMA user_version=1")
            conn.commit()
            conn.close()

            self.assertEqual(initialize_database(db_path, force=True), SCHEMA_VERSION)

            conn = _get_conn(db_path)
            fb_columns = {row[1] for row in conn.execute("PRAGMA table_info(fb_accounts)")}
            social_columns = {row[1] for row in conn.execute("PRAGMA table_info(social_accounts)")}
            proxy_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='proxies'"
            ).fetchone()
            conn.close()
            self.assertNotIn("proxy_id", fb_columns)
            self.assertNotIn("proxy_id", social_columns)
            self.assertIsNone(proxy_table)
            backups = list(Path(temp_dir).glob("legacy-proxy.db.pre-schema-v3-*.sqlite"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(inspect_database(backups[0])["integrity"], "ok")

    def test_favorite_pages_are_normalized_deduplicated_and_keep_scan_cursor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "favorites.db")
            first_id = save_favorite_page(
                db_path, "facebook.com/demo-page/posts", "Demo", scan_limit=120
            )
            second_id = save_favorite_page(
                db_path, "https://www.facebook.com/demo-page/", "Demo mới", scan_limit=80
            )
            self.assertEqual(first_id, second_id)
            finish_favorite_scan(
                db_path, first_id, status="Thành công", new_posts=3,
                cursor_post_ids=["p3", "p2", "p1"], successful=True,
            )
            favorite = get_favorite_pages(db_path)[0]
            self.assertEqual(favorite["page_url"], "https://www.facebook.com/demo-page")
            self.assertEqual(favorite["page_name"], "Demo mới")
            self.assertEqual(favorite["scan_limit"], 80)
            self.assertEqual(favorite["cursor_post_ids"], ["p3", "p2", "p1"])
            self.assertEqual(favorite["last_new_posts_count"], 3)
            self.assertTrue(reset_favorite_cursor(db_path, first_id))
            self.assertEqual(get_favorite_pages(db_path)[0]["cursor_post_ids"], [])

    def test_partial_favorite_scan_saves_posts_without_advancing_cursor(self):
        class PartialScraper:
            last_follower_count = 0
            last_observed_post_ids = ["new-1", "new-2"]
            last_scan_stop_reason = "limit"
            last_scan_complete = False

            def __init__(self, account=None):
                self.account = account

            def start(self):
                return True

            def scrape_page(self, **_kwargs):
                return [SimpleNamespace(
                    post_id="new-1", page_name="Demo", date="01/01/2026",
                    post_type="Text", engagement=0, comments=0, shares=0,
                    caption="new", url="",
                )]

            def stop(self):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "partial-favorite.db")
            favorite_id = save_favorite_page(db_path, "https://facebook.com/demo", "Demo")
            finish_favorite_scan(
                db_path, favorite_id, status="Thành công", new_posts=0,
                cursor_post_ids=["old-marker"], successful=True,
            )
            scraper_routes._stop_requested.clear()
            with patch.object(scraper_routes, "PageScraper", PartialScraper), patch.object(
                scraper_routes.config, "get", return_value=db_path
            ):
                scraper_routes._run_favorite_queue([favorite_id])
            favorite = get_favorite_pages(db_path)[0]
            self.assertEqual(favorite["cursor_post_ids"], ["old-marker"])
            self.assertEqual(favorite["last_status"], "Chưa hoàn tất")
            self.assertEqual(favorite["last_new_posts_count"], 1)

    def test_rebase_missing_social_profiles_and_expose_mapping_to_legacy_account(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "profiles.db")
            legacy_id = add_account(db_path, username="profile-test")
            new_root = Path(temp_dir) / "new-project" / "Chrome Profiles"
            target = new_root / "fb_27"
            target.mkdir(parents=True)
            missing_old = Path(temp_dir) / "old-project" / "Chrome Profiles" / "fb_27"
            add_social_account(
                db_path,
                platform="facebook",
                username="profile-test",
                profile_dir=str(missing_old),
                legacy_fb_id=legacy_id,
            )

            changes = rebase_missing_social_profile_paths(db_path, new_root)

            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0]["to"], str(target.resolve()))
            self.assertEqual(get_account(db_path, legacy_id)["profile_dir"], str(target.resolve()))

    def test_environment_database_override_is_available_for_isolated_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            isolated = str(Path(temp_dir) / "isolated.db")
            with patch.dict(os.environ, {"TINIX_DB_PATH": isolated}):
                self.assertEqual(get_db_path(), isolated)

    def test_database_backup_is_consistent_and_verified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "source.db")
            add_account(db_path, username="backup-test")
            backup_path = create_database_backup(db_path)
            details = inspect_database(backup_path)
            self.assertEqual(details["integrity"], "ok")
            self.assertTrue(details["supported"])
            self.assertEqual(len(get_all_accounts(backup_path)), 1)

    def test_restore_keeps_pre_restore_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "restore.db")
            add_account(db_path, username="before-backup")
            backup_path = create_database_backup(db_path)
            add_account(db_path, username="after-backup")
            safety_backup = restore_database(db_path, backup_path)
            self.assertTrue(Path(safety_backup).is_file())
            self.assertEqual(len(get_all_accounts(db_path)), 1)

    def test_schema_is_versioned_and_initialized_only_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "versioned.db")
            self.assertEqual(initialize_database(db_path), SCHEMA_VERSION)
            conn = _get_conn(db_path)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            conn.close()
            with patch("core.db_storage._initialize_schema") as initializer:
                self.assertEqual(initialize_database(db_path), SCHEMA_VERSION)
                initializer.assert_not_called()

    def test_newer_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "future.db")
            conn = _get_conn(db_path)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
            conn.commit()
            conn.close()
            with self.assertRaisesRegex(RuntimeError, "newer than this application supports"):
                initialize_database(db_path, force=True)

    def test_fresh_database_has_complete_managed_pages_schema_and_stats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "fresh.db")
            conn = _get_conn(db_path)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(managed_pages)")}
            conn.close()
            self.assertTrue({"group_name", "avatar_path", "group_id", "last_synced", "reels_asset_id"} <= columns)
            self.assertEqual(
                get_db_stats(db_path),
                {"total_posts": 0, "total_pages": 0, "downloaded_posts": 0},
            )

    def test_reviewed_schedule_is_persisted_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            content_dir = root / "content" / "post-01"
            content_dir.mkdir(parents=True)
            register_media_root(root / "content")
            db_path = str(root / "schedule.db")
            account_id = add_account(db_path, username="schedule-test", label="Test")
            save_managed_pages(db_path, account_id, [{
                "page_name": "Test Page",
                "page_url": "https://facebook.com/test-page",
                "page_id": "123456",
            }])
            page = get_all_managed_pages(db_path)[0]
            payload = PersistScheduleRequest(schedules=[{
                "folder_name": "post-01",
                "folder_path": str(content_dir),
                "caption": "Caption",
                "target_page": page["page_name"],
                "target_id": page["id"],
                "target_uid": page["page_id"],
                "account_id": page["account_id"],
                "scheduled_time": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
            }])
            with patch("web.routes.poster.config.get", return_value=db_path):
                first = persist_schedule_endpoint(payload)
                second = persist_schedule_endpoint(payload)
            self.assertEqual(first["inserted"], 1)
            self.assertEqual(second["inserted"], 0)
            self.assertEqual(second["skipped"], 1)
            history = get_schedule_history_filtered(db_path)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["page_name"], "Test Page")

    def test_queue_runner_executes_and_updates_pending_job(self):
        FakePoster.calls.clear()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            content_dir = root / "content" / "post-queue"
            content_dir.mkdir(parents=True)
            register_media_root(root / "content")
            db_path = str(root / "queue.db")
            account_id = add_account(db_path, username="queue-test", label="Queue")
            save_managed_pages(db_path, account_id, [{
                "page_name": "Queue Page",
                "page_url": "https://facebook.com/queue-page",
                "page_id": "987654",
            }])
            page = get_all_managed_pages(db_path)[0]
            scheduled = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
            payload = PersistScheduleRequest(schedules=[{
                "folder_name": "post-queue",
                "folder_path": str(content_dir),
                "caption": "Queue caption",
                "target_page": page["page_name"],
                "target_id": page["id"],
                "target_uid": page["page_id"],
                "account_id": page["account_id"],
                "scheduled_time": scheduled,
            }])
            with patch("web.routes.poster.config.get", return_value=db_path):
                persist_schedule_endpoint(payload)
            pending = get_schedule_history_filtered(db_path, status="Pending", scheduling_method="WebUI")
            runner = PostQueueRunner(poster_factory=FakePoster)
            self.assertTrue(runner.start(db_path, pending, delay_range=(0, 0)))
            self.assertTrue(runner.wait(3))
            self.assertEqual(runner.snapshot()["success"], 1)
            self.assertEqual(len(FakePoster.calls), 1)
            history = get_schedule_history_filtered(db_path, scheduling_method="WebUI")
            self.assertEqual(history[0]["status"], "Scheduled")

    def test_plaintext_secret_migration_creates_backup_and_remains_readable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "secrets.db")
            account_id = add_account(db_path, username="secret-test", password="initial")
            conn = _get_conn(db_path)
            conn.execute(
                "UPDATE fb_accounts SET password = ?, cookie = ? WHERE id = ?",
                ("legacy-password", "legacy-cookie", account_id),
            )
            conn.commit()
            conn.close()
            result = migrate_secrets_at_rest(db_path)
            self.assertGreaterEqual(result["changed"], 2)
            self.assertTrue(Path(result["backup_path"]).exists())
            conn = _get_conn(db_path)
            raw = conn.execute(
                "SELECT password, cookie FROM fb_accounts WHERE id = ?", (account_id,)
            ).fetchone()
            conn.close()
            self.assertTrue(is_protected(raw[0]))
            self.assertTrue(is_protected(raw[1]))
            account = get_account(db_path, account_id)
            self.assertEqual(account["password"], "legacy-password")
            self.assertEqual(account["cookie"], "legacy-cookie")

    def test_interrupted_webui_job_returns_to_pending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            content_dir = root / "content" / "recover-post"
            content_dir.mkdir(parents=True)
            register_media_root(root / "content")
            db_path = str(root / "recover.db")
            account_id = add_account(db_path, username="recover-test")
            save_managed_pages(db_path, account_id, [{
                "page_name": "Recover Page", "page_id": "4444", "page_url": ""
            }])
            page = get_all_managed_pages(db_path)[0]
            payload = PersistScheduleRequest(schedules=[{
                "folder_name": "recover-post",
                "folder_path": str(content_dir),
                "caption": "Recover",
                "target_id": page["id"],
                "account_id": page["account_id"],
                "scheduled_time": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
            }])
            with patch("web.routes.poster.config.get", return_value=db_path):
                persist_schedule_endpoint(payload)
            conn = _get_conn(db_path)
            conn.execute("UPDATE post_history SET status = 'Running'")
            conn.commit()
            conn.close()
            self.assertEqual(recover_interrupted_webui_jobs(db_path), 1)
            history = get_schedule_history_filtered(db_path, scheduling_method="WebUI")
            self.assertEqual(history[0]["status"], "Pending")
            self.assertIn("Khôi phục", history[0]["error_log"])


if __name__ == "__main__":
    unittest.main()
