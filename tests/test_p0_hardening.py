import tempfile
import unittest
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from starlette.testclient import TestClient

from core.db_storage import (
    SCHEMA_VERSION,
    _get_conn,
    add_account,
    add_social_account,
    create_favorite_page_group,
    delete_favorite_page_group,
    get_all_accounts,
    get_db_path,
    get_db_stats,
    get_account,
    get_favorite_pages,
    get_favorite_page_groups,
    finish_favorite_scan,
    finish_favorite_archive_scan,
    migrate_secrets_at_rest,
    initialize_database,
    rebase_missing_social_profile_paths,
    save_favorite_page,
    reset_favorite_cursor,
    query_posts_for_spy,
    mark_posts_download_status,
    set_post_rating,
    save_posts,
    update_favorite_group_members,
    update_favorite_page_group,
)
from web.app import app
from web.routes.accounts import _public_account
from web.routes import accounts as accounts_routes
from web.routes import downloader as downloader_routes
from web.routes import scraper as scraper_routes
from web.routes import spy as spy_routes
from web.routes.system import _public_config
from web.security import register_media_root, resolve_media_file
from core import downloader as core_downloader
from core.page_search import parse_follower_count, _facebook_target_url
from core.page_scraper import (
    PageScraper, _PostCollector, _parse_metric_number, is_valid_facebook_page_name,
)
from core.facebook_parser import PostData
from core.database_maintenance import create_database_backup, inspect_database, restore_database
from utils.secure_store import is_protected, protect_secret, unprotect_secret
from utils import config as app_config


class SecurityHelpersTest(unittest.TestCase):
    def test_video_detection_uses_page_data_when_player_is_lazy(self):
        class EmptyArticle:
            @staticmethod
            def query_selector(_selector):
                return None

        class LazyVideoPage:
            @staticmethod
            def query_selector(_selector):
                return None

            @staticmethod
            def evaluate(script, _video_id):
                if "const signals" in script:
                    return True
                return ""

        result = object.__new__(core_downloader.BrowserManager)._detect_video(
            EmptyArticle(), LazyVideoPage(), "1042220375120456"
        )
        self.assertTrue(result["has_video"])
        self.assertEqual(result["video_url"], "")

    def test_no_dom_media_falls_back_to_ytdlp_and_keeps_completed_video(self):
        class FakeBrowser:
            @staticmethod
            def fetch_post(_url, post_id):
                return PostData(post_id=post_id, text="Video caption")

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = core_downloader.DownloadOrchestrator()
            orchestrator._output_dir = Path(temp_dir)
            orchestrator.stats = core_downloader.DownloadStats(total_posts=1, start_time=time.time())

            def fake_ytdlp(_url, save_dir, _cookies):
                (save_dir / "video_001.mp4").write_bytes(b"completed-video")
                return True

            with patch.object(core_downloader, "download_video", side_effect=fake_ytdlp), patch.object(
                orchestrator, "_mark_post_downloaded"
            ) as mark_mock:
                orchestrator._process_single_post(
                    "https://www.facebook.com/1042220375120456", 1,
                    browser=FakeBrowser(), cookies={"c_user": "1"},
                )

            post_dir = Path(temp_dir) / "1042220375120456"
            self.assertTrue((post_dir / "video_001.mp4").is_file())
            self.assertTrue((post_dir / "caption.txt").is_file())
            self.assertEqual(orchestrator.stats.success_posts, 1)
            mark_mock.assert_called_once()

    def test_failed_ytdlp_fallback_removes_caption_only_folder(self):
        class FakeBrowser:
            @staticmethod
            def fetch_post(_url, post_id):
                return PostData(post_id=post_id, text="Caption without media")

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = core_downloader.DownloadOrchestrator()
            orchestrator._output_dir = Path(temp_dir)
            orchestrator.stats = core_downloader.DownloadStats(total_posts=1, start_time=time.time())
            with patch.object(core_downloader, "download_video", return_value=False):
                orchestrator._process_single_post(
                    "https://www.facebook.com/1234567890123456", 1,
                    browser=FakeBrowser(), cookies={"c_user": "1"},
                )
            self.assertFalse((Path(temp_dir) / "1234567890123456").exists())
            self.assertEqual(orchestrator.stats.failed_posts, 1)

    def test_cookie_parallel_download_owns_browser_in_worker_thread(self):
        events = []

        class FakeBrowser:
            def __init__(self, **kwargs):
                self.created_thread = threading.get_ident()
                events.append(("created", self.created_thread, kwargs.get("cdp_port")))

            def start(self, cookies):
                events.append(("started", threading.get_ident(), bool(cookies)))
                return self.created_thread == threading.get_ident()

            def stop(self):
                events.append(("stopped", threading.get_ident(), None))

        orchestrator = core_downloader.DownloadOrchestrator()
        orchestrator._cookies = {"c_user": "1", "xs": "test"}
        orchestrator._max_threads = 4
        orchestrator.stats = core_downloader.DownloadStats(total_posts=1, start_time=time.time())

        def process(_url, _index, *, browser, cookies, account_label):
            self.assertEqual(browser.created_thread, threading.get_ident())
            self.assertEqual(cookies, orchestrator._cookies)
            self.assertEqual(account_label, "Luồng 1")
            orchestrator._update_stats(failed=False)

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            core_downloader, "BrowserManager", FakeBrowser
        ), patch.object(
            core_downloader, "chrome_profile_dir", return_value=Path(temp_dir)
        ), patch.object(orchestrator, "_process_single_post", side_effect=process):
            orchestrator._run_parallel(["https://facebook.com/123"])

        self.assertEqual(orchestrator.stats.success_posts, 1)
        self.assertEqual([event[0] for event in events], ["created", "started", "stopped"])
        self.assertEqual(events[0][1], events[1][1])
        self.assertEqual(events[1][1], events[2][1])

    def test_failed_download_completion_emits_failed_progress(self):
        old_stats = downloader_routes.orchestrator.stats
        downloader_routes.orchestrator.stats = core_downloader.DownloadStats(
            total_posts=2, completed_posts=2, failed_posts=2
        )
        try:
            with patch.object(downloader_routes, "log_to_web") as log_mock, patch.object(
                downloader_routes, "progress_to_web"
            ) as progress_mock:
                downloader_routes._on_all_complete(False, "0/2 bài thành công; 2 bài thất bại")
            log_mock.assert_called_once()
            self.assertEqual(log_mock.call_args.args[1], "WARNING")
            self.assertEqual(progress_mock.call_args.args[-1], "failed")
        finally:
            downloader_routes.orchestrator.stats = old_stats

    def test_download_route_calls_orchestrator_start_for_cookie_mode(self):
        class FakeOrchestrator:
            is_running = False
            start_kwargs = None

            def start(self, **kwargs):
                self.start_kwargs = kwargs
                self.is_running = True

        fake = FakeOrchestrator()
        request = downloader_routes.DownloadStartRequest(
            urls="https://www.facebook.com/1061899689819191",
            max_threads=2,
            use_accounts=False,
        )
        with patch.object(downloader_routes, "orchestrator", fake), patch.object(
            downloader_routes.config, "get",
            side_effect=lambda key, default=None: {
                "output_dir": "test-output",
                "saved_cookies": "c_user=1; xs=valid-cookie",
            }.get(key, default),
        ):
            result = downloader_routes.start_download(request)
        self.assertEqual(result["status"], "success")
        self.assertEqual(fake.start_kwargs["max_threads"], 2)
        self.assertIn("1061899689819191", fake.start_kwargs["urls_text"])

    def test_view_metric_parser_and_graphql_collector_support_localized_counts(self):
        self.assertEqual(_parse_metric_number("1,2K lượt xem"), 1200)
        self.assertEqual(_parse_metric_number("1.234 lượt xem"), 1234)
        self.assertEqual(_parse_metric_number("2.5M views"), 2500000)
        collector = _PostCollector()
        self.assertEqual(
            collector._extract_view_count({"video": {"video_view_count_text": "3,4K lượt xem"}}),
            3400,
        )

    def test_graphql_collector_extracts_safe_media_preview_and_count(self):
        collector = _PostCollector()
        node = {
            "comet_sections": {
                "content": {
                    "story": {
                        "attachments": [
                            {"media": {"__typename": "Photo", "id": "p1", "image": {
                                "uri": "https://scontent.fhan1-1.fna.fbcdn.net/photo-1.jpg",
                                "width": 900, "height": 900,
                            }}},
                            {"media": {"__typename": "Photo", "id": "p2", "image": {
                                "uri": "https://scontent.fhan1-1.fna.fbcdn.net/photo-2.jpg",
                                "width": 720, "height": 720,
                            }}},
                        ]
                    }
                }
            }
        }
        preview, count = collector._extract_media_metadata(node)
        self.assertEqual(preview, "https://scontent.fhan1-1.fna.fbcdn.net/photo-1.jpg")
        self.assertEqual(count, 2)
        self.assertEqual(collector._valid_preview_url("https://example.com/not-facebook.jpg"), "")

    def test_graphql_preview_prefers_video_thumbnail_and_rejects_avatar(self):
        collector = _PostCollector()
        node = {
            "comet_sections": {"content": {"story": {
                "actors": [{"profile_picture": {
                    "uri": "https://scontent.fhan1-1.fna.fbcdn.net/avatar.jpg",
                    "width": 640, "height": 640,
                }}],
                "attachments": [{"media": {
                    "__typename": "Video", "id": "video-1",
                    "preferred_thumbnail": {"image": {
                        "uri": "https://scontent.fhan1-1.fna.fbcdn.net/video-thumb.jpg",
                        "width": 640, "height": 360,
                    }},
                    "image": {
                        "uri": "https://scontent.fhan1-1.fna.fbcdn.net/video-full.jpg",
                        "width": 1920, "height": 1080,
                    },
                }}],
            }}}
        }
        preview, count = collector._extract_media_metadata(node)
        self.assertEqual(preview, "https://scontent.fhan1-1.fna.fbcdn.net/video-thumb.jpg")
        self.assertEqual(count, 1)

    def test_dom_preview_fallback_merges_safe_thumbnail_without_media_download(self):
        collector = _PostCollector()
        collector._posts["123456789012345"] = {
            "post_id": "123456789012345", "media_preview_url": "", "media_count": 0,
        }

        class FakePage:
            def evaluate(self, _script):
                return [{
                    "postId": "123456789012345",
                    "url": "https://scontent.fhan1-1.fna.fbcdn.net/dom-preview.jpg",
                }]

        scraper = PageScraper(account={"id": 3})
        self.assertEqual(scraper._enrich_previews_from_dom(FakePage(), collector), 1)
        self.assertEqual(
            collector._posts["123456789012345"]["media_preview_url"],
            "https://scontent.fhan1-1.fna.fbcdn.net/dom-preview.jpg",
        )
        self.assertEqual(collector._posts["123456789012345"]["media_count"], 1)

    def test_page_name_rejects_facebook_detail_label_and_uses_graphql_name(self):
        class FakePage:
            url = "https://www.facebook.com/inanhchocon"

            def __init__(self):
                self.calls = 0

            def evaluate(self, _script):
                self.calls += 1
                return "Chi tiết" if self.calls == 1 else "In ảnh cho con"

        self.assertFalse(is_valid_facebook_page_name("Chi tiết"))
        self.assertFalse(is_valid_facebook_page_name("Details"))
        self.assertFalse(is_valid_facebook_page_name("Thông tin liên hệ"))
        self.assertTrue(is_valid_facebook_page_name("In ảnh cho con"))
        self.assertEqual(PageScraper()._extract_page_name(FakePage()), "In ảnh cho con")

    def test_save_posts_never_overwrites_registered_page_name_with_facebook_ui_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "page-name.db")
            valid_post = SimpleNamespace(
                post_id="valid-name", date="01/01/2026", post_type="Ảnh",
                engagement=0, comments=0, shares=0, view_count=0, caption="", media_preview_url="",
            )
            generic_post = SimpleNamespace(
                post_id="generic-name", date="02/01/2026", post_type="Ảnh",
                engagement=0, comments=0, shares=0, view_count=0, caption="", media_preview_url="",
            )
            page_url = "https://www.facebook.com/xuonginhanh"
            save_posts(db_path, "Xưởng In Ảnh Hana 5", page_url, [valid_post])
            save_posts(db_path, "Thông tin liên hệ", page_url, [generic_post])

            conn = _get_conn(db_path)
            page_name = conn.execute(
                "SELECT page_name FROM pages WHERE page_url = ?", (page_url,)
            ).fetchone()[0]
            post_names = {
                row[0] for row in conn.execute(
                    "SELECT DISTINCT page_name FROM posts WHERE page_url = ?", (page_url,)
                )
            }
            conn.close()
            self.assertEqual(page_name, "Xưởng In Ảnh Hana 5")
            self.assertEqual(post_names, {"Xưởng In Ảnh Hana 5"})

    def test_reused_account_chrome_is_not_closed_when_scraper_stops(self):
        browser = SimpleNamespace(close=lambda: self.fail("Reused Chrome must stay open"))
        playwright = SimpleNamespace(stop=lambda: None)
        scraper = PageScraper(account={"id": 3})
        scraper._browser = browser
        scraper._pw_instance = playwright
        scraper._reused_browser = True
        scraper.stop()
        self.assertIsNone(scraper._browser)

    def test_follower_count_parser_handles_localized_facebook_values(self):
        cases = {
            "1.234 người theo dõi": 1234,
            "1,2K followers": 1200,
            "12 nghìn người theo dõi": 12000,
            "2,5 triệu người theo dõi": 2500000,
            "1.2M followers": 1200000,
            "Không công khai": 0,
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(parse_follower_count(label), expected)

    def test_page_search_candidate_urls_are_canonical_and_filter_navigation(self):
        self.assertEqual(
            _facebook_target_url("https://facebook.com/demo.page/posts"),
            "https://www.facebook.com/demo.page",
        )
        self.assertEqual(
            _facebook_target_url("https://www.facebook.com/profile.php?id=123456"),
            "https://www.facebook.com/profile.php?id=123456",
        )
        self.assertEqual(_facebook_target_url("https://facebook.com/groups/demo"), "")
        self.assertEqual(_facebook_target_url("https://example.com/demo"), "")

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
                        json={
                            "page_url": "https://facebook.com/api-demo/posts", "scan_limit": 75,
                            "page_uid": "987654", "follower_count": 12500,
                            "category": "Người sáng tạo nội dung", "verified": True,
                        },
                    )
                    listed = client.get("/api/scrape/favorites")
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(listed.status_code, 200, listed.text)
            favorite = listed.json()["data"][0]
            self.assertEqual(favorite["page_url"], "https://www.facebook.com/api-demo")
            self.assertEqual(favorite["scan_limit"], 75)
            self.assertEqual(favorite["page_uid"], "987654")
            self.assertEqual(favorite["follower_count"], 12500)
            self.assertEqual(favorite["category"], "Người sáng tạo nội dung")
            self.assertTrue(favorite["verified"])

    def test_favorite_group_api_creates_and_assigns_saved_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "favorite-group-api.db")
            with patch.object(
                scraper_routes.config, "get",
                side_effect=lambda key, default=None: db_path if key == "scraper_db_path" else default,
            ):
                with TestClient(app) as client:
                    client.get("/")
                    created = client.post(
                        "/api/scrape/favorites/groups/create",
                        json={"name": "Đối thủ", "color": "#0f766e"},
                    )
                    group_id = created.json()["id"]
                    saved = client.post(
                        "/api/scrape/favorites/save",
                        json={"page_url": "https://facebook.com/grouped-page", "group_ids": [group_id]},
                    )
                    listed = client.get("/api/scrape/favorites")
                    groups = client.get("/api/scrape/favorites/groups")
            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(listed.json()["data"][0]["groups"][0]["name"], "Đối thủ")
            self.assertEqual(groups.json()["data"][0]["page_count"], 1)

    def test_favorite_batch_reset_and_batch_delete_api(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "favorite-batch-api.db")
            with patch.object(
                scraper_routes.config, "get",
                side_effect=lambda key, default=None: db_path if key == "scraper_db_path" else default,
            ):
                with TestClient(app) as client:
                    client.get("/")
                    s1 = client.post("/api/scrape/favorites/save", json={"page_url": "https://facebook.com/page-1"})
                    s2 = client.post("/api/scrape/favorites/save", json={"page_url": "https://facebook.com/page-2"})
                    id1 = s1.json()["id"]
                    id2 = s2.json()["id"]

                    reset_res = client.post("/api/scrape/favorites/batch-reset-cursor", json={"favorite_ids": [id1, id2]})
                    self.assertEqual(reset_res.status_code, 200)
                    self.assertEqual(reset_res.json()["count"], 2)

                    delete_res = client.post("/api/scrape/favorites/batch-delete", json={"favorite_ids": [id1, id2]})
                    self.assertEqual(delete_res.status_code, 200)
                    self.assertEqual(delete_res.json()["count"], 2)

                    listed = client.get("/api/scrape/favorites")
                    self.assertEqual(len(listed.json()["data"]), 0)


class DatabaseBootstrapTest(unittest.TestCase):
    def test_schema_upgrade_removes_legacy_proxy_storage_with_verified_backup(self):
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
            backups = list(Path(temp_dir).glob(f"legacy-proxy.db.pre-schema-v{SCHEMA_VERSION}-*.sqlite"))
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
                follower_count=12345,
            )
            favorite = get_favorite_pages(db_path)[0]
            self.assertEqual(favorite["page_url"], "https://www.facebook.com/demo-page")
            self.assertEqual(favorite["page_name"], "Demo mới")
            self.assertEqual(favorite["scan_limit"], 80)
            self.assertEqual(favorite["cursor_post_ids"], ["p3", "p2", "p1"])
            self.assertEqual(favorite["last_new_posts_count"], 3)
            self.assertEqual(favorite["follower_count"], 12345)
            self.assertTrue(reset_favorite_cursor(db_path, first_id))
            self.assertEqual(get_favorite_pages(db_path)[0]["cursor_post_ids"], [])

    def test_favorite_groups_support_many_to_many_without_changing_scan_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "favorite-groups.db")
            first_id = save_favorite_page(db_path, "https://facebook.com/page-one", "Page One")
            second_id = save_favorite_page(db_path, "https://facebook.com/page-two", "Page Two")
            finish_favorite_scan(
                db_path, first_id, status="Thành công", new_posts=2,
                cursor_post_ids=["post-2", "post-1"], successful=True,
            )
            print_group = create_favorite_page_group(db_path, "In ảnh", "#f97316")
            family_group = create_favorite_page_group(db_path, "Mẹ và Bé", "#0f766e")
            self.assertEqual(update_favorite_group_members(db_path, print_group, [first_id, second_id]), 2)
            self.assertEqual(update_favorite_group_members(db_path, family_group, [first_id]), 1)

            pages = {page["id"]: page for page in get_favorite_pages(db_path)}
            self.assertEqual({group["name"] for group in pages[first_id]["groups"]}, {"In ảnh", "Mẹ và Bé"})
            self.assertEqual([group["name"] for group in pages[second_id]["groups"]], ["In ảnh"])
            self.assertEqual(pages[first_id]["cursor_post_ids"], ["post-2", "post-1"])
            self.assertTrue(update_favorite_page_group(db_path, print_group, "In ảnh quảng cáo", "#f97316"))
            self.assertEqual(get_favorite_page_groups(db_path)[0]["page_count"], 2)
            self.assertEqual(update_favorite_group_members(db_path, print_group, [second_id], "remove"), 1)
            self.assertTrue(delete_favorite_page_group(db_path, family_group))

            remaining = {page["id"]: page for page in get_favorite_pages(db_path)}
            self.assertEqual([group["name"] for group in remaining[first_id]["groups"]], ["In ảnh quảng cáo"])
            self.assertEqual(remaining[second_id]["groups"], [])
            self.assertEqual(remaining[first_id]["cursor_post_ids"], ["post-2", "post-1"])

    def test_spy_sorting_uses_whitelisted_columns_and_real_calendar_dates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "sorting.db")
            posts = [
                SimpleNamespace(
                    post_id="older", date="31/12/2025", post_type="Video",
                    engagement=9, comments=50, shares=1, view_count=1200,
                    caption="Older", url="",
                ),
                SimpleNamespace(
                    post_id="newer", date="01/01/2026", post_type="Video",
                    engagement=100, comments=2, shares=4, view_count=9000,
                    caption="Newer", url="",
                ),
                SimpleNamespace(
                    post_id="unknown-views", date="02/01/2026", post_type="Text",
                    engagement=1, comments=0, shares=0, view_count=0,
                    caption="Unknown views", url="",
                ),
            ]
            save_posts(db_path, "Demo", "https://facebook.com/demo", posts)
            by_date = query_posts_for_spy(db_path, ["Demo"], sort_by="date", sort_order="desc")
            by_comments = query_posts_for_spy(db_path, ["Demo"], sort_by="comments", sort_order="desc")
            by_views = query_posts_for_spy(db_path, ["Demo"], sort_by="view_count", sort_order="desc")
            by_views_asc = query_posts_for_spy(db_path, ["Demo"], sort_by="view_count", sort_order="asc")
            by_views_mode = query_posts_for_spy(db_path, ["Demo"], mode="top_views")
            fallback = query_posts_for_spy(db_path, ["Demo"], sort_by="posts; DROP TABLE posts", sort_order="desc")
            self.assertEqual([item["post_id"] for item in by_date], ["unknown-views", "newer", "older"])
            self.assertEqual([item["post_id"] for item in by_comments], ["older", "newer", "unknown-views"])
            self.assertEqual([item["post_id"] for item in by_views], ["newer", "older", "unknown-views"])
            self.assertEqual([item["post_id"] for item in by_views_asc], ["older", "newer", "unknown-views"])
            self.assertEqual([item["post_id"] for item in by_views_mode], ["newer", "older", "unknown-views"])
            self.assertEqual(len(fallback), 3)
            self.assertEqual(by_views[0]["view_count"], 9000)

    def test_spy_download_status_lifecycle_and_filters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "download-status.db")
            posts = [
                SimpleNamespace(
                    post_id="status-101", date="01/01/2026", post_type="Video",
                    engagement=1, comments=0, shares=0, view_count=10,
                    caption="Status test", url="https://facebook.com/demo/videos/status-101",
                )
            ]
            save_posts(db_path, "Demo", "https://facebook.com/demo", posts)

            initial = query_posts_for_spy(db_path, ["Demo"])[0]
            self.assertEqual(initial["download_status"], "not_downloaded")

            mark_posts_download_status(db_path, ["status-101"], "downloading")
            downloading = query_posts_for_spy(db_path, ["Demo"], download_status="Đang tải")
            self.assertEqual(downloading[0]["download_status"], "downloading")

            mark_posts_download_status(db_path, ["status-101"], "failed", error="Video bị từ chối")
            failed = query_posts_for_spy(db_path, ["Demo"], download_status="Tải lỗi")
            self.assertEqual(failed[0]["download_error"], "Video bị từ chối")

            media_dir = str(Path(temp_dir) / "media" / "status-101")
            mark_posts_download_status(db_path, ["status-101"], "downloaded", folder_path=media_dir)
            downloaded = query_posts_for_spy(db_path, ["Demo"], download_status="Đã tải")
            self.assertEqual(downloaded[0]["download_status"], "downloaded")
            self.assertEqual(downloaded[0]["download_path"], media_dir)

            self.assertTrue(set_post_rating(db_path, downloaded[0]["id"], 4))
            rated = query_posts_for_spy(db_path, ["Demo"])[0]
            self.assertEqual(rated["rating"], 4)

    def test_archive_scan_uses_oldest_boundary_and_persists_separate_cursor(self):
        raw = [
            {"post_id": "new"}, {"post_id": "edge-1"}, {"post_id": "edge-2"},
            {"post_id": "older-1"}, {"post_id": "older-2"},
        ]
        found, candidates = PageScraper._archive_candidates(
            raw, {"new", "edge-1", "edge-2"}, {"edge-1", "edge-2"}
        )
        self.assertTrue(found)
        self.assertEqual([item["post_id"] for item in candidates], ["older-1", "older-2"])

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "archive.db")
            favorite_id = save_favorite_page(db_path, "https://facebook.com/archive", "Archive")
            finish_favorite_scan(
                db_path, favorite_id, status="Thành công", new_posts=1,
                cursor_post_ids=["new-edge"], successful=True,
            )
            finish_favorite_archive_scan(
                db_path, favorite_id, status="Đã quét thêm bài cũ", saved_posts=2,
                cursor_post_ids=["older-1", "older-2"], successful=True,
            )
            favorite = get_favorite_pages(db_path)[0]
            self.assertEqual(favorite["cursor_post_ids"], ["new-edge"])
            self.assertEqual(favorite["archive_cursor_post_ids"], ["older-1", "older-2"])
            self.assertEqual(favorite["archive_scanned_count"], 2)

    def test_spy_prefers_downloaded_media_preview_and_preserves_remote_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = str(root / "preview.db")
            media_dir = root / "post-media"
            media_dir.mkdir()
            preview_file = media_dir / "01-preview.jpg"
            preview_file.write_bytes(b"preview")
            (media_dir / "02-video.mp4").write_bytes(b"video")
            post = SimpleNamespace(
                post_id="123456", date="01/01/2026", post_type="Ảnh",
                engagement=1, comments=2, shares=3, view_count=0,
                caption="Preview", url="",
                media_preview_url="https://scontent.fhan1-1.fna.fbcdn.net/remote.jpg",
                media_count=3,
            )
            save_posts(db_path, "Demo", "https://facebook.com/demo", [post])
            conn = _get_conn(db_path)
            conn.execute(
                "UPDATE posts SET downloaded = 1, download_path = ? WHERE post_id = ?",
                (str(media_dir), "123456"),
            )
            conn.commit()
            conn.close()
            result = query_posts_for_spy(db_path, ["Demo"])[0]
            self.assertEqual(Path(result["preview_path"]), preview_file.resolve())
            self.assertEqual(result["preview_kind"], "image")
            self.assertEqual(result["media_count"], 3)
            self.assertTrue(result["media_preview_url"].endswith("/remote.jpg"))

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

    def test_favorite_scan_can_override_saved_account_for_current_queue(self):
        class CaptureAccountScraper:
            seen_account_ids = []
            last_follower_count = 0
            last_observed_post_ids = []
            last_scan_stop_reason = "complete"
            last_scan_complete = True

            def __init__(self, account=None):
                self.__class__.seen_account_ids.append(account.get("id") if account else None)

            def start(self):
                return True

            def scrape_page(self, **_kwargs):
                return []

            def stop(self):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "favorite-account-override.db")
            saved_account_id = add_account(db_path, username="saved-account", label="Saved")
            override_account_id = add_account(db_path, username="override-account", label="Override")
            favorite_id = save_favorite_page(
                db_path, "https://facebook.com/demo", "Demo", account_id=saved_account_id
            )
            CaptureAccountScraper.seen_account_ids.clear()
            scraper_routes._stop_requested.clear()
            with patch.object(scraper_routes, "PageScraper", CaptureAccountScraper), patch.object(
                scraper_routes.config, "get", return_value=db_path
            ):
                scraper_routes._run_favorite_queue(
                    [favorite_id], account_mode="specific", account_id=override_account_id
                )
            self.assertEqual(CaptureAccountScraper.seen_account_ids, [override_account_id])
            self.assertEqual(get_favorite_pages(db_path)[0]["account_id"], saved_account_id)

    def test_auto_favorite_queues_use_fair_round_robin_and_active_accounts_only(self):
        favorites = [{"id": value, "account_id": None} for value in range(1, 8)]
        accounts = [
            {"id": 11, "label": "A", "is_active": 1},
            {"id": 12, "label": "B", "is_active": 1},
            {"id": 13, "label": "Disabled", "is_active": 0},
        ]
        queues = scraper_routes._build_favorite_queues(
            favorites, accounts, "auto", None, max_concurrency=2
        )
        self.assertEqual([queue["worker_id"] for queue in queues], ["account-11", "account-12"])
        self.assertEqual(queues[0]["favorite_ids"], [1, 3, 5, 7])
        self.assertEqual(queues[1]["favorite_ids"], [2, 4, 6])
        self.assertEqual(
            sorted(value for queue in queues for value in queue["favorite_ids"]),
            list(range(1, 8)),
        )

    def test_favorite_parallel_coordinator_respects_worker_limit(self):
        active = 0
        peak = 0
        completed = []
        guard = threading.Lock()

        def fake_worker(queue):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with guard:
                active -= 1
                completed.append(queue["worker_id"])
            return 0

        queues = [{"worker_id": f"account-{value}"} for value in range(4)]
        scraper_routes._stop_requested.clear()
        with patch.object(scraper_routes, "_run_favorite_worker", side_effect=fake_worker):
            scraper_routes._run_favorite_parallel(queues, max_concurrency=2)
        self.assertEqual(peak, 2)
        self.assertEqual(sorted(completed), ["account-0", "account-1", "account-2", "account-3"])

    def test_auto_download_collects_one_batch_after_parallel_favorite_scan(self):
        def fake_worker(queue):
            queue["download_urls"] = [
                f"https://facebook.com/posts/{queue['worker_id']}",
                "https://facebook.com/posts/shared",
            ]
            return 1

        queues = [
            {"worker_id": "account-1", "account": {"id": 1, "is_active": 1}},
            {"worker_id": "account-2", "account": {"id": 2, "is_active": 1}},
        ]
        scraper_routes._stop_requested.clear()
        with patch.object(scraper_routes, "_run_favorite_worker", side_effect=fake_worker), patch.object(
            scraper_routes, "_start_auto_download", return_value=True
        ) as start_download:
            scraper_routes._run_favorite_parallel(queues, max_concurrency=2, download_media=True)
        start_download.assert_called_once()
        urls, accounts = start_download.call_args.args
        self.assertEqual(len(urls), 4)
        self.assertEqual([account["id"] for account in accounts], [1, 2])

    def test_auto_download_url_collection_is_unique_and_request_defaults_off(self):
        posts = [
            SimpleNamespace(url="https://facebook.com/posts/1"),
            SimpleNamespace(url="https://facebook.com/posts/1"),
            SimpleNamespace(url=""),
            SimpleNamespace(url="https://facebook.com/posts/2"),
        ]
        self.assertEqual(
            scraper_routes._downloadable_post_urls(posts),
            ["https://facebook.com/posts/1", "https://facebook.com/posts/2"],
        )
        self.assertFalse(scraper_routes.FavoriteScanRequest().download_media)
        self.assertTrue(scraper_routes.FavoriteScanRequest(download_media=True).download_media)

    def test_quick_scan_distributes_multiple_urls_across_account_queues(self):
        urls = [
            "https://www.facebook.com/page-1",
            "https://www.facebook.com/page-2",
            "https://www.facebook.com/page-3",
        ]
        accounts = [
            {"id": 1, "username": "one", "is_active": 1},
            {"id": 2, "username": "two", "is_active": 1},
            {"id": 3, "username": "off", "is_active": 0},
        ]
        queues = scraper_routes._build_quick_queues(urls, accounts, "auto", None, 2)
        self.assertEqual(len(queues), 2)
        self.assertEqual(queues[0]["page_urls"], [urls[0], urls[2]])
        self.assertEqual(queues[1]["page_urls"], [urls[1]])
        request = scraper_routes.ScrapeStartRequest(page_urls=urls, max_concurrency=2)
        self.assertEqual(len(request.page_urls), 3)
        self.assertEqual(request.account_mode, "auto")
        self.assertEqual(request.mode, "All")
        with self.assertRaises(ValueError):
            scraper_routes.ScrapeStartRequest(page_urls=urls, mode="New Posts")

    def test_auto_download_uses_available_accounts_and_deduplicates_urls(self):
        class FakeOrchestrator:
            is_running = False
            calls = []

            def start_with_accounts(self, **kwargs):
                self.calls.append(kwargs)
                self.is_running = True

            def start_download(self, **kwargs):
                raise AssertionError("Account khả dụng phải được ưu tiên")

        fake = FakeOrchestrator()

        def config_value(key, default=None):
            return {
                "output_dir": "test-output",
                "max_threads": 3,
                "scraper_db_path": "test.db",
            }.get(key, default)

        with patch("web.routes.downloader.orchestrator", fake), patch.object(
            scraper_routes.config, "get", side_effect=config_value
        ), patch.object(
            scraper_routes, "get_all_accounts",
            return_value=[{"id": 7, "username": "active", "is_active": 1}],
        ):
            started = scraper_routes._start_auto_download([
                "https://facebook.com/posts/1",
                "https://facebook.com/posts/1",
            ])
        self.assertTrue(started)
        self.assertEqual(fake.calls[0]["urls_text"], "https://facebook.com/posts/1")
        self.assertEqual(fake.calls[0]["accounts"][0]["id"], 7)
        self.assertEqual(fake.calls[0]["max_threads"], 3)

    def test_stopping_one_favorite_worker_keeps_other_queue_running(self):
        class FakeActiveScraper:
            stopped = False

            def stop(self):
                self.stopped = True

        first_event = threading.Event()
        second_event = threading.Event()
        first_scraper = FakeActiveScraper()
        with scraper_routes._scrape_lock:
            scraper_routes._scrape_status.update({"is_running": True, "task_type": "favorites"})
            scraper_routes._favorite_worker_stop_events.clear()
            scraper_routes._favorite_worker_stop_events.update({
                "account-1": first_event, "account-2": second_event,
            })
            scraper_routes._active_favorite_scrapers.clear()
            scraper_routes._active_favorite_scrapers["account-1"] = first_scraper
        try:
            result = scraper_routes.stop_favorite_worker(
                scraper_routes.FavoriteWorkerStopRequest(worker_id="account-1")
            )
            self.assertEqual(result["status"], "success")
            self.assertTrue(first_event.is_set())
            self.assertTrue(first_scraper.stopped)
            self.assertFalse(second_event.is_set())
        finally:
            with scraper_routes._scrape_lock:
                scraper_routes._scrape_status.update({"is_running": False, "task_type": ""})
                scraper_routes._favorite_worker_stop_events.clear()
                scraper_routes._active_favorite_scrapers.clear()

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

    def test_downloaded_post_detail_returns_full_caption_and_all_safe_media(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "downloads"
            post_dir = output / "post-123"
            post_dir.mkdir(parents=True)
            (post_dir / "caption.txt").write_text("Nội dung đầy đủ\nDòng thứ hai", encoding="utf-8")
            (post_dir / "image_001.jpg").write_bytes(b"image")
            (post_dir / "video_001.mp4").write_bytes(b"video")
            (post_dir / "ignored.json").write_text("{}", encoding="utf-8")

            db_path = str(root / "detail.db")
            conn = _get_conn(db_path)
            cursor = conn.execute(
                """
                INSERT INTO posts
                    (page_name, post_id, post_type, caption, url, downloaded, download_path)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                ("Test Page", "post-123", "Video", "Caption DB", "https://facebook.com/post-123", str(post_dir)),
            )
            row_id = cursor.lastrowid
            conn.commit()
            conn.close()

            values = {"scraper_db_path": db_path, "output_dir": str(output)}
            with patch.object(spy_routes.config, "get", side_effect=lambda key, default=None: values.get(key, default)):
                detail = spy_routes.get_post_detail(row_id)["data"]
                media_response = spy_routes.get_post_media(row_id, 1)

            self.assertEqual(detail["caption"], "Nội dung đầy đủ\nDòng thứ hai")
            self.assertEqual([item["kind"] for item in detail["media"]], ["image", "video"])
            self.assertNotIn("download_path", detail)
            self.assertEqual(Path(media_response.path), post_dir / "video_001.mp4")

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


if __name__ == "__main__":
    unittest.main()
