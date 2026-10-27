"""
Unit tests for flat post storage in a single output directory.
Verifies file naming:
- Caption: <post_id>.txt
- Images: <post_id>_1.jpeg, <post_id>_2.jpeg, ...
- Video: <post_id>.mp4
- Fallback thumbnail: <post_id>_1.jpeg
Verifies existing check, failure cleanup, DB sync, gallery preview, and safe deletion.
"""

import shutil
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core import downloader as core_downloader
from core.facebook_parser import BrowserManager, PostData
from core.db_storage import (
    _get_conn,
    get_scraped_pages_full,
    mark_post_row_downloaded,
    mark_post_row_download_status,
    mark_posts_download_status,
    query_posts_for_spy,
    register_downloaded_post_for_page,
    resolve_download_target,
    save_posts,
    sync_downloaded_posts_from_folder,
)
from web.routes import spy as spy_routes
from web.routes.spy import DeletePostsRequest, RetryPostsRequest, delete_posts, retry_posts


class FlatStorageTest(unittest.TestCase):

    def test_scoped_page_data_extracts_only_target_gallery_images(self):
        """Inline Facebook data adds gallery images only from the target post."""
        target_id = "122126610032883555"
        target_block = (
            f'"post_id":"{target_id}","all_subattachments":{{"count":2,"nodes":['
            '{"media":{"image":{"uri":"https:\\/\\/scontent.xx.fbcdn.net\\/target-1.jpg?x=1"}}},'
            '{"media":{"viewer_image":{"uri":"https:\\/\\/scontent.xx.fbcdn.net\\/target-2.jpg?x=2"}}}'
            ']}}'
        )
        unrelated_block = (
            '"post_id":"122126610032883556","all_subattachments":['
            '"image":{"uri":"https:\\/\\/scontent.xx.fbcdn.net\\/other-post.jpg"}'
        )
        urls = object.__new__(BrowserManager)._extract_scoped_image_urls_from_html(
            target_block + ("x" * 300_000) + unrelated_block, target_id,
        )
        self.assertEqual(urls, [
            "https://scontent.xx.fbcdn.net/target-1.jpg?x=1",
            "https://scontent.xx.fbcdn.net/target-2.jpg?x=2",
        ])

    def test_incomplete_media_status_is_not_marked_downloaded(self):
        """A retryable partial gallery must remain in the Spy download queue."""
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "spy.db")
            post_id = "777777777777778"
            save_posts(
                db_path, "Test Page", "https://www.facebook.com/test-page",
                [SimpleNamespace(post_id=post_id, date="01/01/2026", post_type="Ảnh",
                                 engagement=0, comments=0, shares=0, view_count=0,
                                 caption="Partial gallery", url="", media_count=4)],
            )
            target = resolve_download_target(db_path, [post_id])
            self.assertTrue(mark_post_row_downloaded(
                db_path, target["row_id"], temp_dir, status="failed", error="Thiếu media local: tìm thấy 1/4 file",
            ))
            refreshed = query_posts_for_spy(db_path, ["Test Page"])[0]
            self.assertFalse(refreshed["downloaded"])

    def test_scoped_page_data_is_used_when_article_has_no_photo_links(self):
        """A dialog without photo anchors can still yield its scoped gallery data."""
        class EmptyArticle:
            @staticmethod
            def evaluate(_script):
                return []

            @staticmethod
            def query_selector_all(_selector):
                return []

        post_id = "122126610032883555"
        html = (
            f'"post_id":"{post_id}","attachment":{{"image":{{"uri":'
            '"https:\\/\\/scontent.xx.fbcdn.net\\/gallery-1.jpg"}}}},'
            '"subattachments":[{"image":{"uri":"https:\\/\\/scontent.xx.fbcdn.net\\/gallery-2.jpg"}}]'
        )
        urls = object.__new__(BrowserManager)._extract_images(EmptyArticle(), html, post_id)
        self.assertEqual(urls, [
            "https://scontent.xx.fbcdn.net/gallery-1.jpg",
            "https://scontent.xx.fbcdn.net/gallery-2.jpg",
        ])

    def test_profile_page_uses_permalink_without_corrupting_profile_id(self):
        """Numeric downloads use Facebook's profile permalink when the source is profile.php."""
        class FakeBrowser:
            seen_url = ""

            @classmethod
            def fetch_post(cls, url, post_id):
                cls.seen_url = url
                return PostData(post_id=post_id, text="Image post", image_urls=["https://example.com/image.jpg"])

        with tempfile.TemporaryDirectory() as temp_dir:
            orchestrator = core_downloader.DownloadOrchestrator()
            orchestrator._output_dir = Path(temp_dir)
            orchestrator.stats = core_downloader.DownloadStats(total_posts=1, start_time=time.time())

            def fake_download_image(_url, save_path, _cookies):
                save_path.write_bytes(b"image")
                return True

            with patch.object(core_downloader, "download_image", side_effect=fake_download_image), patch.object(
                core_downloader, "get_post_by_id", return_value={
                    "post_type": "Ảnh", "page_url": "https://www.facebook.com/profile.php?id=61576506666779",
                }
            ), patch.object(orchestrator, "_mark_post_download_status"), patch.object(
                orchestrator, "_mark_post_downloaded"
            ):
                orchestrator._process_single_post(
                    "https://www.facebook.com/122126610032883555", 1,
                    browser=FakeBrowser(), cookies={"c_user": "1"},
                )

            self.assertEqual(
                FakeBrowser.seen_url,
                "https://www.facebook.com/permalink.php?story_fbid=122126610032883555&id=61576506666779",
            )
            self.assertEqual(orchestrator.stats.success_posts, 1)

    def test_distinct_video_id_download_uses_watch_url_and_story_id_for_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = str(root / "video-link.db")
            output_dir = root / "downloads"
            output_dir.mkdir()
            page_url = "https://www.facebook.com/demo-page"
            story_id = "1234567890123"
            video_id = "9876543210987"
            watch_url = f"https://www.facebook.com/watch/?v={video_id}"
            input_url = f"https://www.facebook.com/watch?v={video_id}"
            save_posts(
                db_path, "Demo Page", page_url,
                [SimpleNamespace(
                    post_id=story_id, date="01/01/2026", post_type="Video",
                    engagement=0, comments=0, shares=0, view_count=0,
                    caption="Video caption", url=watch_url, media_count=1, video_url_verified=True,
                )],
            )
            # A later scrape that misses the attachment ID must keep the
            # previously known playable URL for retrying this video.
            save_posts(
                db_path, "Demo Page", page_url,
                [SimpleNamespace(
                    post_id=story_id, date="01/01/2026", post_type="Video",
                    engagement=0, comments=0, shares=0, view_count=0,
                    caption="Video caption", url="", media_count=1,
                )],
            )

            class FakeBrowser:
                fetch_call = None

                def fetch_post(self, url, post_id):
                    self.fetch_call = (url, post_id)
                    return PostData(
                        post_id=post_id, author="Demo Page", author_url=page_url,
                        text="Video caption", has_video=True,
                        video_url="https://video-cdn.example/video.mp4",
                    )

            browser = FakeBrowser()
            orchestrator = core_downloader.DownloadOrchestrator()
            orchestrator._output_dir = output_dir
            orchestrator.stats = core_downloader.DownloadStats(total_posts=1, start_time=time.time())

            def fake_download(_url, save_path, _cookies):
                save_path.write_bytes(b"video")
                return True

            config_values = {"scraper_db_path": db_path}
            with patch.object(core_downloader.config, "get", side_effect=lambda key, default=None: config_values.get(key, default)), patch.object(
                core_downloader, "download_video_direct", side_effect=fake_download
            ):
                orchestrator._process_single_post(
                    input_url, 1, browser=browser, cookies={"c_user": "1"},
                )

            self.assertEqual(browser.fetch_call, (watch_url, video_id))
            self.assertTrue((output_dir / f"{story_id}.mp4").is_file())
            saved = query_posts_for_spy(db_path, ["Demo Page"])[0]
            self.assertEqual(saved["url"], watch_url)
            self.assertEqual(saved["download_status"], "downloaded")

    def test_video_is_not_marked_downloaded_when_downloader_creates_no_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = str(root / "missing-video-file.db")
            output_dir = root / "downloads"
            output_dir.mkdir()
            page_url = "https://www.facebook.com/demo"
            story_id = "1234567890123"
            watch_url = "https://www.facebook.com/watch/?v=9876543210987"
            save_posts(db_path, "Demo", page_url, [SimpleNamespace(
                post_id=story_id, date="", post_type="Video", engagement=0, comments=0,
                shares=0, view_count=0, caption="Video", url=watch_url, video_url_verified=True,
            )])
            row_id = query_posts_for_spy(db_path, ["Demo"])[0]["id"]

            class FakeBrowser:
                def fetch_post(self, _url, post_id):
                    return PostData(
                        post_id=post_id, text="Video", has_video=True,
                        video_url="https://video-cdn.example/video.mp4",
                    )

            orchestrator = core_downloader.DownloadOrchestrator()
            orchestrator._output_dir = output_dir
            orchestrator.stats = core_downloader.DownloadStats(total_posts=1, start_time=time.time())
            with patch.object(
                core_downloader.config, "get",
                side_effect=lambda key, default=None: db_path if key == "scraper_db_path" else default,
            ), patch.object(core_downloader, "download_video_direct", return_value=True), patch.object(
                core_downloader, "download_video", return_value=False
            ):
                orchestrator._process_single_post(
                    watch_url, 1, browser=FakeBrowser(), cookies={"c_user": "1"},
                    source_post_row_id=row_id,
                )

            saved = query_posts_for_spy(db_path, ["Demo"])[0]
            self.assertFalse((output_dir / f"{story_id}.mp4").exists())
            self.assertEqual(saved["download_status"], "failed")
            self.assertEqual(orchestrator.stats.failed_posts, 1)

    def test_manual_url_change_invalidates_verified_video_attachment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "video-provenance.db")
            page_url = "https://www.facebook.com/demo-page"
            story_id = "1234567890123"
            watch_url = "https://www.facebook.com/watch/?v=9876543210987"
            save_posts(db_path, "Demo", page_url, [SimpleNamespace(
                post_id=story_id, date="", post_type="Video", engagement=0, comments=0,
                shares=0, view_count=0, caption="Video", url=watch_url,
                video_url_verified=True,
            )])

            for replacement, expected_verified in (
                (watch_url, 1),
                ("https://www.facebook.com/watch/?v=1111111111111", 0),
            ):
                self.assertTrue(register_downloaded_post_for_page(
                    db_path, story_id, replacement, "Video", page_name="Demo",
                    page_url=page_url, post_type="Video", media_count=1,
                    folder_path=temp_dir,
                ))
                conn = _get_conn(db_path)
                row = conn.execute(
                    "SELECT url, video_url_verified FROM posts WHERE post_id = ?", (story_id,)
                ).fetchone()
                conn.close()
                self.assertEqual(row, (replacement, expected_verified))

    def test_verified_download_is_saved_under_its_source_page(self):
        """A download with a verified source is never assigned to a synthetic page."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = str(root / "source-download.db")
            post_id = "1858757808423158"

            created = register_downloaded_post_for_page(
                db_path,
                post_id,
                f"https://www.facebook.com/watch/?v={post_id}",
                "Source-download caption",
                page_name="Verified Page",
                page_url="https://www.facebook.com/verified-page",
                post_type="Video",
                media_count=1,
                folder_path=str(root),
            )

            self.assertTrue(created)
            self.assertEqual(get_scraped_pages_full(db_path)[0]["page_name"], "Verified Page")
            posts = query_posts_for_spy(db_path, ["Verified Page"])
            self.assertEqual(posts[0]["post_id"], post_id)
            self.assertEqual(posts[0]["download_status"], "downloaded")

    def test_watch_video_matches_scraped_post_by_verified_page_and_caption(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "match-source.db")
            save_posts(
                db_path, "Verified Page", "https://www.facebook.com/verified-page",
                [SimpleNamespace(post_id="777777777777777", date="01/01/2026", post_type="Video",
                                 engagement=0, comments=0, shares=0, view_count=0,
                                 caption="Unique source caption", url="")],
            )
            target = resolve_download_target(
                db_path, ["1858757808423158"], url="https://www.facebook.com/watch/?v=1858757808423158",
                page_url="https://www.facebook.com/verified-page", page_name="Verified Page",
                caption="Unique source caption",
            )
            self.assertEqual(target["page_name"], "Verified Page")
            self.assertTrue(mark_post_row_downloaded(db_path, target["row_id"], temp_dir))
            posts = query_posts_for_spy(db_path, ["Verified Page"])
            self.assertEqual(posts[0]["post_id"], "777777777777777")
            self.assertEqual(posts[0]["download_status"], "downloaded")

    def test_flat_storage_image_and_caption_naming(self):
        """Images and caption are saved directly in output_dir with post_id naming."""
        class FakeBrowser:
            @staticmethod
            def fetch_post(_url, post_id):
                return PostData(
                    post_id=post_id,
                    text="Flat storage test caption",
                    image_urls=["https://example.com/img1.jpeg", "https://example.com/img2.jpeg"],
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            orchestrator = core_downloader.DownloadOrchestrator()
            orchestrator._output_dir = out_dir
            orchestrator.stats = core_downloader.DownloadStats(total_posts=1, start_time=time.time())

            def fake_download_image(url, save_path, _cookies):
                save_path.write_bytes(b"fake-image-bytes-over-100-bytes-1234567890-abcdefghijklmnopqrstuvwxyz-1234567890-abcdefghijklmnopqrstuvwxyz")
                return True

            with patch.object(core_downloader, "download_image", side_effect=fake_download_image), patch.object(
                core_downloader, "get_post_by_id", return_value=None
            ), patch.object(
                orchestrator, "_mark_post_download_status"
            ), patch.object(
                orchestrator, "_mark_post_downloaded"
            ) as mark_mock:
                orchestrator._process_single_post(
                    "https://www.facebook.com/999888777666555", 1,
                    browser=FakeBrowser(), cookies={"c_user": "1"},
                )

            # Assert flat files directly in out_dir (no subfolder 999888777666555/)
            self.assertFalse((out_dir / "999888777666555").exists())
            caption_file = out_dir / "999888777666555.txt"
            img1_file = out_dir / "999888777666555_1.jpeg"
            img2_file = out_dir / "999888777666555_2.jpeg"

            self.assertTrue(caption_file.is_file())
            self.assertEqual(caption_file.read_text(encoding="utf-8"), "Flat storage test caption")
            self.assertTrue(img1_file.is_file())
            self.assertTrue(img2_file.is_file())
            self.assertEqual(orchestrator.stats.success_posts, 1)
            mark_mock.assert_called_once()

    def test_flat_storage_video_naming(self):
        """Video is saved as <post_id>.mp4 directly in output_dir."""
        class FakeBrowser:
            @staticmethod
            def fetch_post(_url, post_id):
                data = PostData(post_id=post_id, text="Video caption", has_video=True)
                data.video_url = "https://video.xx.fbcdn.net/v/test.mp4"
                return data

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            orchestrator = core_downloader.DownloadOrchestrator()
            orchestrator._output_dir = out_dir
            orchestrator.stats = core_downloader.DownloadStats(total_posts=1, start_time=time.time())

            def fake_download_video_direct(url, save_path, _cookies):
                save_path.write_bytes(b"fake-video-bytes-over-10000-bytes-" + b"0" * 10500)
                return True

            with patch.object(core_downloader, "download_video_direct", side_effect=fake_download_video_direct), patch.object(
                core_downloader, "get_post_by_id", return_value=None
            ), patch.object(
                orchestrator, "_mark_post_download_status"
            ), patch.object(
                orchestrator, "_mark_post_downloaded"
            ):
                orchestrator._process_single_post(
                    "https://www.facebook.com/888777666555444", 1,
                    browser=FakeBrowser(), cookies={"c_user": "1"},
                )

            self.assertFalse((out_dir / "888777666555444").exists())
            video_file = out_dir / "888777666555444.mp4"
            caption_file = out_dir / "888777666555444.txt"
            self.assertTrue(video_file.is_file())
            self.assertTrue(caption_file.is_file())
            self.assertEqual(orchestrator.stats.success_posts, 1)

    def test_image_post_ignores_unscoped_video_signal(self):
        """A scanned image post downloads every image even if parsing found an unrelated video."""
        class FakeBrowser:
            @staticmethod
            def fetch_post(_url, post_id):
                return PostData(
                    post_id=post_id,
                    text="Image post",
                    image_urls=["https://example.com/img1.jpeg", "https://example.com/img2.jpeg"],
                    has_video=True,
                    video_url="https://video.xx.fbcdn.net/unrelated.mp4",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            orchestrator = core_downloader.DownloadOrchestrator()
            orchestrator._output_dir = out_dir
            orchestrator.stats = core_downloader.DownloadStats(total_posts=1, start_time=time.time())

            def fake_download_image(_url, save_path, _cookies):
                save_path.write_bytes(b"image")
                return True

            with patch.object(core_downloader, "download_image", side_effect=fake_download_image) as download_image_mock, patch.object(
                core_downloader, "get_post_by_id", return_value={"post_type": "Ảnh", "page_url": "https://www.facebook.com/demo"}
            ), patch.object(orchestrator, "_mark_post_download_status"), patch.object(
                orchestrator, "_mark_post_downloaded"
            ) as mark_mock, patch.object(core_downloader, "download_video_direct") as download_video_mock, patch.object(
                core_downloader, "download_video"
            ) as ytdlp_mock:
                orchestrator._process_single_post(
                    "https://www.facebook.com/demo/posts/999888777666555", 1,
                    browser=FakeBrowser(), cookies={"c_user": "1"},
                )

            self.assertEqual(download_image_mock.call_count, 2)
            download_video_mock.assert_not_called()
            ytdlp_mock.assert_not_called()
            self.assertTrue((out_dir / "999888777666555_1.jpeg").is_file())
            self.assertTrue((out_dir / "999888777666555_2.jpeg").is_file())
            self.assertFalse(mark_mock.call_args.args[0].has_video)
            self.assertEqual(orchestrator.stats.success_posts, 1)

    def test_image_post_without_gallery_does_not_fall_back_to_video(self):
        """A missing image gallery preserves its preview as a retryable image failure, never a video failure."""
        class FakeBrowser:
            @staticmethod
            def fetch_post(_url, post_id):
                return PostData(post_id=post_id, text="Image post")

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            orchestrator = core_downloader.DownloadOrchestrator()
            orchestrator._output_dir = out_dir
            orchestrator.stats = core_downloader.DownloadStats(total_posts=1, start_time=time.time())

            def fake_download_image(_url, save_path, _cookies):
                save_path.write_bytes(b"preview")
                return True

            with patch.object(core_downloader, "download_image", side_effect=fake_download_image), patch.object(
                core_downloader, "download_video", side_effect=AssertionError("Image posts must not use yt-dlp")
            ), patch.object(
                core_downloader, "get_post_by_id", return_value={
                    "post_type": "Ảnh", "page_url": "https://www.facebook.com/demo",
                    "media_preview_url": "https://example.com/preview.jpg",
                }
            ), patch.object(orchestrator, "_mark_post_download_status"), patch.object(
                orchestrator, "_mark_post_downloaded"
            ) as mark_mock:
                orchestrator._process_single_post(
                    "https://www.facebook.com/demo/posts/999888777666555", 1,
                    browser=FakeBrowser(), cookies={"c_user": "1"},
                )

            self.assertTrue((out_dir / "999888777666555_1.jpg").is_file())
            self.assertEqual(mark_mock.call_args.kwargs["status"], "failed")
            self.assertNotIn("video", mark_mock.call_args.kwargs["error"].lower())
            self.assertEqual(orchestrator.stats.failed_posts, 1)

    def test_incomplete_image_gallery_stays_failed_and_reuses_existing_files(self):
        """A multi-image post is complete only after every expected image is local."""
        class FakeBrowser:
            @staticmethod
            def fetch_post(_url, post_id):
                return PostData(
                    post_id=post_id,
                    text="Gallery post",
                    image_urls=["https://example.com/one.jpg", "https://example.com/two.jpg"],
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            existing = out_dir / "999888777666555_1.jpg"
            existing.write_bytes(b"already-downloaded")
            orchestrator = core_downloader.DownloadOrchestrator()
            orchestrator._output_dir = out_dir
            orchestrator.stats = core_downloader.DownloadStats(total_posts=1, start_time=time.time())

            def fake_download_image(_url, save_path, _cookies):
                save_path.write_bytes(b"new-image")
                return True

            with patch.object(core_downloader, "download_image", side_effect=fake_download_image) as download_image_mock, patch.object(
                core_downloader, "get_post_by_id", return_value={
                    "post_type": "Ảnh", "media_count": 4, "page_url": "https://www.facebook.com/demo",
                }
            ), patch.object(orchestrator, "_mark_post_download_status"), patch.object(
                orchestrator, "_mark_post_downloaded"
            ) as mark_mock:
                orchestrator._process_single_post(
                    "https://www.facebook.com/demo/posts/999888777666555", 1,
                    browser=FakeBrowser(), cookies={"c_user": "1"},
                )

            self.assertEqual(download_image_mock.call_count, 1)
            self.assertEqual(mark_mock.call_args.kwargs["status"], "failed")
            self.assertIn("2/4", mark_mock.call_args.kwargs["error"])
            self.assertEqual(orchestrator.stats.failed_posts, 1)

    def test_retry_endpoint_only_starts_failed_or_thumbnail_posts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "retry.db")
            posts = [
                SimpleNamespace(post_id="1111111111111", date="01/01/2026", post_type="Ảnh", engagement=0,
                                comments=0, shares=0, view_count=0, caption="Failed", url="https://facebook.com/1111111111111"),
                SimpleNamespace(post_id="2222222222222", date="01/01/2026", post_type="Video", engagement=0,
                                comments=0, shares=0, view_count=0, caption="Done", url="https://facebook.com/watch/?v=2222222222222"),
            ]
            save_posts(db_path, "Demo", "https://facebook.com/demo", posts)
            rows = query_posts_for_spy(db_path, ["Demo"])
            failed_id = next(row["id"] for row in rows if row["post_id"] == "1111111111111")
            done_id = next(row["id"] for row in rows if row["post_id"] == "2222222222222")
            mark_posts_download_status(db_path, ["1111111111111"], "failed", error="network")
            mark_posts_download_status(db_path, ["2222222222222"], "downloaded", folder_path=temp_dir)
            values = {"scraper_db_path": db_path}
            with patch.object(spy_routes.config, "get", side_effect=lambda key, default=None: values.get(key, default)), patch.object(
                spy_routes, "start_download", return_value={"status": "success", "state": "started"}
            ) as start_mock:
                result = retry_posts(RetryPostsRequest(post_row_ids=[failed_id, done_id], max_threads=1, account_ids=[7]))

            self.assertEqual(result["retrying"], 1)
            self.assertEqual(result["skipped"], 1)
            request = start_mock.call_args.args[0]
            self.assertIn("1111111111111", request.urls)
            self.assertNotIn("2222222222222", request.urls)
            self.assertEqual(request.account_ids, [7])

    def test_retry_endpoint_uses_saved_video_attachment_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "retry-video.db")
            story_id = "1234567890123"
            watch_url = "https://www.facebook.com/watch/?v=9876543210987"
            save_posts(
                db_path, "Demo", "https://www.facebook.com/demo",
                [SimpleNamespace(
                    post_id=story_id, date="01/01/2026", post_type="Video",
                    engagement=0, comments=0, shares=0, view_count=0,
                    caption="Failed video", url=watch_url, media_count=1, video_url_verified=True,
                )],
            )
            post = query_posts_for_spy(db_path, ["Demo"])[0]
            mark_posts_download_status(db_path, [story_id], "failed", error="Network timeout")

            config_values = {"scraper_db_path": db_path}
            with patch.object(spy_routes.config, "get", side_effect=lambda key, default=None: config_values.get(key, default)), patch.object(
                spy_routes, "start_download", return_value={"status": "success", "state": "started"}
            ) as start_mock:
                retry_posts(RetryPostsRequest(post_row_ids=[post["id"]], max_threads=1))

            request = start_mock.call_args.args[0]
            self.assertEqual(request.urls, watch_url)
            self.assertEqual(request.source_post_row_ids, [post["id"]])

    def test_retry_endpoint_accepts_saved_story_permalink_without_attachment_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "retry-story-fallback.db")
            story_id = "1234567890123"
            story_url = f"https://www.facebook.com/demo/posts/{story_id}"
            save_posts(
                db_path, "Demo", "https://www.facebook.com/demo",
                [SimpleNamespace(
                    post_id=story_id, date="01/01/2026", post_type="Video",
                    engagement=0, comments=0, shares=0, view_count=0,
                    caption="Video without attachment ID", url=story_url, media_count=1,
                )],
            )
            post = query_posts_for_spy(db_path, ["Demo"])[0]
            mark_post_row_download_status(db_path, post["id"], "failed", error="No attachment ID")
            values = {"scraper_db_path": db_path}
            with patch.object(spy_routes.config, "get", side_effect=lambda key, default=None: values.get(key, default)), patch.object(
                spy_routes, "start_download", return_value={"status": "success", "state": "started"}
            ) as start_mock:
                retry_posts(RetryPostsRequest(post_row_ids=[post["id"]], max_threads=1))

            request = start_mock.call_args.args[0]
            self.assertEqual(request.urls, story_url)
            self.assertEqual(request.source_post_row_ids, [post["id"]])

    def test_retry_preserves_two_rows_sharing_one_playable_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "retry-shared-url.db")
            shared_url = "https://www.facebook.com/watch/?v=9876543210987"
            save_posts(db_path, "Page One", "https://www.facebook.com/page-one", [SimpleNamespace(
                post_id="1111111111111", date="", post_type="Video", engagement=0, comments=0,
                shares=0, view_count=0, caption="One", url=shared_url, media_count=1, video_url_verified=True,
            )])
            save_posts(db_path, "Page Two", "https://www.facebook.com/page-two", [SimpleNamespace(
                post_id="2222222222222", date="", post_type="Video", engagement=0, comments=0,
                shares=0, view_count=0, caption="Two", url=shared_url, media_count=1, video_url_verified=True,
            )])
            rows = query_posts_for_spy(db_path, ["Page One", "Page Two"])
            row_ids = sorted(row["id"] for row in rows)
            mark_post_row_download_status(db_path, row_ids[0], "failed", error="retry")
            mark_post_row_download_status(db_path, row_ids[1], "thumbnail_only", error="retry")
            values = {"scraper_db_path": db_path}
            with patch.object(spy_routes.config, "get", side_effect=lambda key, default=None: values.get(key, default)), patch.object(
                spy_routes, "start_download", return_value={"status": "success", "state": "started"}
            ) as start_mock:
                result = retry_posts(RetryPostsRequest(post_row_ids=row_ids, max_threads=1))

            request = start_mock.call_args.args[0]
            self.assertEqual(result["retrying"], 2)
            self.assertEqual(request.urls.splitlines(), [shared_url, shared_url])
            self.assertEqual(request.source_post_row_ids, row_ids)

    def test_video_detector_ignores_page_video_without_confirmed_media_id(self):
        """A global player must not turn an image post into a video post."""
        class EmptyArticle:
            @staticmethod
            def query_selector(_selector):
                return None

        class PageWithUnrelatedVideo:
            url = "https://www.facebook.com/demo/posts/999888777666555"

            @staticmethod
            def query_selector(_selector):
                return object()

            @staticmethod
            def evaluate(*_args):
                raise AssertionError("Unconfirmed posts must not inspect global video data")

        result = object.__new__(BrowserManager)._detect_video(
            EmptyArticle(), PageWithUnrelatedVideo(), ""
        )
        self.assertFalse(result["has_video"])
        self.assertEqual(result["video_url"], "")

    def test_flat_sync_and_spy_detail(self):
        """sync_downloaded_posts_from_folder and spy gallery recognize flat files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "downloads"
            out_dir.mkdir()
            db_path = str(root / "flat-sync.db")

            # Create flat files for post 970714485604379
            (out_dir / "970714485604379.txt").write_text("Hello Flat World", encoding="utf-8")
            (out_dir / "970714485604379_1.jpeg").write_bytes(b"img1")
            (out_dir / "970714485604379_2.jpeg").write_bytes(b"img2")
            (out_dir / "970714485604379.mp4").write_bytes(b"video")

            save_posts(
                db_path,
                "Demo Page",
                "https://facebook.com/demopage",
                [SimpleNamespace(
                    post_id="970714485604379", date="01/01/2026", post_type="Video",
                    engagement=10, comments=2, shares=1, view_count=50,
                    caption="Old DB caption", url="https://facebook.com/970714485604379",
                )],
            )

            # Sync from flat folder
            synced = sync_downloaded_posts_from_folder(db_path, str(out_dir))
            self.assertEqual(synced, 1)

            # Query posts for spy
            posts = query_posts_for_spy(db_path, ["Demo Page"])
            self.assertEqual(len(posts), 1)
            p = posts[0]
            self.assertEqual(p["download_status"], "downloaded")
            self.assertEqual(p["media_count"], 3)  # 2 images + 1 video
            self.assertTrue(p["preview_path"].endswith("970714485604379_1.jpeg"))

            # Spy detail endpoint
            values = {"scraper_db_path": db_path, "output_dir": str(out_dir)}
            with patch.object(spy_routes.config, "get", side_effect=lambda k, d=None: values.get(k, d)):
                detail = spy_routes.get_post_detail(p["id"])["data"]
                self.assertEqual(detail["caption"], "Hello Flat World")
                self.assertEqual(len(detail["media"]), 3)
                names = [m["name"] for m in detail["media"]]
                self.assertIn("970714485604379_1.jpeg", names)
                self.assertIn("970714485604379_2.jpeg", names)
                self.assertIn("970714485604379.mp4", names)

    def test_safe_deletion_of_single_flat_post(self):
        """Deleting one post removes only its files and keeps other posts in the common folder."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "downloads"
            out_dir.mkdir()
            db_path = str(root / "safe-delete.db")

            # Post 1 files
            (out_dir / "111111.txt").write_text("Post 1 text", encoding="utf-8")
            (out_dir / "111111_1.jpeg").write_bytes(b"p1-img")
            (out_dir / "111111.mp4").write_bytes(b"p1-vid")

            # Post 2 files (must survive)
            (out_dir / "222222.txt").write_text("Post 2 text", encoding="utf-8")
            (out_dir / "222222_1.jpeg").write_bytes(b"p2-img")

            save_posts(
                db_path,
                "Demo Page",
                "https://facebook.com/demopage",
                [
                    SimpleNamespace(
                        post_id="111111", date="01/01/2026", post_type="Video",
                        engagement=0, comments=0, shares=0, view_count=0,
                        caption="P1", url="https://facebook.com/111111",
                    ),
                    SimpleNamespace(
                        post_id="222222", date="02/01/2026", post_type="Ảnh",
                        engagement=0, comments=0, shares=0, view_count=0,
                        caption="P2", url="https://facebook.com/222222",
                    ),
                ],
            )
            sync_downloaded_posts_from_folder(db_path, str(out_dir))

            posts = query_posts_for_spy(db_path, ["Demo Page"])
            row_to_delete = [p["id"] for p in posts if p["post_id"] == "111111"]

            values = {"scraper_db_path": db_path, "output_dir": str(out_dir)}
            with patch("web.routes.spy.scrape_is_running", return_value=False), patch(
                "web.routes.spy.download_is_running", return_value=False
            ), patch(
                "web.routes.spy.config.get", side_effect=lambda k, d=None: values.get(k, d)
            ):
                result = delete_posts(DeletePostsRequest(post_row_ids=row_to_delete, delete_media=True))

            self.assertEqual(result["data"]["deleted"], 1)
            # Post 1 files must be deleted
            self.assertFalse((out_dir / "111111.txt").exists())
            self.assertFalse((out_dir / "111111_1.jpeg").exists())
            self.assertFalse((out_dir / "111111.mp4").exists())

            # Output dir and Post 2 files must survive!
            self.assertTrue(out_dir.exists())
            self.assertTrue((out_dir / "222222.txt").exists())
            self.assertTrue((out_dir / "222222_1.jpeg").exists())

    def test_storage_migration_from_legacy_subfolders(self):
        """migrate_legacy_subfolders_to_flat converts subfolders to flat files and updates DB."""
        from core.storage_migration import migrate_legacy_subfolders_to_flat
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "downloads"
            out_dir.mkdir()
            db_path = str(root / "migration.db")

            # Legacy subfolder 1: video post
            sub1 = out_dir / "1001"
            sub1.mkdir()
            (sub1 / "caption.txt").write_text("Video post caption", encoding="utf-8")
            (sub1 / "video_001.mp4").write_bytes(b"vid1")

            # Legacy subfolder 2: multi-image post with thumbnail
            sub2 = out_dir / "1002"
            sub2.mkdir()
            (sub2 / "caption.txt").write_text("Image post caption", encoding="utf-8")
            (sub2 / "image_001.jpg").write_bytes(b"img1")
            (sub2 / "image_002.jpg").write_bytes(b"img2")
            (sub2 / "thumbnail.jpg").write_bytes(b"img1")

            # Legacy subfolder 3: thumbnail-only post
            sub3 = out_dir / "1003"
            sub3.mkdir()
            (sub3 / "caption.txt").write_text("Thumb only post", encoding="utf-8")
            (sub3 / "thumbnail.jpg").write_bytes(b"thumb3")

            save_posts(
                db_path,
                "Demo Page",
                "https://facebook.com/demopage",
                [
                    SimpleNamespace(post_id="1001", date="01/01/2026", post_type="Video", caption="V1", url="https://facebook.com/1001", engagement=0, comments=0, shares=0, view_count=0),
                    SimpleNamespace(post_id="1002", date="02/01/2026", post_type="Ảnh", caption="I1", url="https://facebook.com/1002", engagement=0, comments=0, shares=0, view_count=0),
                    SimpleNamespace(post_id="1003", date="03/01/2026", post_type="Video", caption="T1", url="https://facebook.com/1003", engagement=0, comments=0, shares=0, view_count=0),
                ],
            )
            # Point db rows to legacy subfolders
            conn = _get_conn(db_path)
            conn.execute("UPDATE posts SET download_path = ? WHERE post_id = '1001'", (str(sub1),))
            conn.execute("UPDATE posts SET download_path = ? WHERE post_id = '1002'", (str(sub2),))
            conn.execute("UPDATE posts SET download_path = ? WHERE post_id = '1003'", (str(sub3),))
            conn.commit()
            conn.close()

            # Run migration
            res = migrate_legacy_subfolders_to_flat(out_dir, db_path)
            self.assertEqual(res["migrated_folders"], 3)
            self.assertEqual(res["folders_removed"], 3)
            self.assertGreaterEqual(res["files_moved"], 6)

            # Check subfolders removed
            self.assertFalse(sub1.exists())
            self.assertFalse(sub2.exists())
            self.assertFalse(sub3.exists())

            # Check flat files exist
            self.assertTrue((out_dir / "1001.txt").exists())
            self.assertTrue((out_dir / "1001.mp4").exists())
            self.assertTrue((out_dir / "1002.txt").exists())
            self.assertTrue((out_dir / "1002_1.jpeg").exists())
            self.assertTrue((out_dir / "1002_2.jpeg").exists())
            self.assertFalse((out_dir / "1002_thumbnail.jpg").exists())
            self.assertTrue((out_dir / "1003.txt").exists())
            self.assertTrue((out_dir / "1003_1.jpeg").exists())

            # Check DB updated
            conn = _get_conn(db_path)
            rows = conn.execute("SELECT post_id, download_path FROM posts").fetchall()
            conn.close()
            for _pid, dl_path in rows:
                self.assertEqual(dl_path, str(out_dir))

            # Re-running after completion is a no-op.
            self.assertEqual(migrate_legacy_subfolders_to_flat(out_dir, db_path)["migrated_folders"], 0)

    def test_storage_migration_preserves_conflicts_and_nested_content(self):
        """Unsafe or incomplete legacy folders stay intact and keep their DB path."""
        from core.storage_migration import migrate_legacy_subfolders_to_flat

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "downloads"
            out_dir.mkdir()
            db_path = str(root / "migration-conflicts.db")
            conflict_dir = out_dir / "2001"
            conflict_dir.mkdir()
            source_video = conflict_dir / "video_001.mp4"
            source_video.write_bytes(b"legacy video")
            (out_dir / "2001.mp4").write_bytes(b"different existing video")
            nested_dir = conflict_dir / "nested"
            nested_dir.mkdir()
            nested_file = nested_dir / "keep.txt"
            nested_file.write_text("keep", encoding="utf-8")
            ignored = out_dir / "notes-2002"
            ignored.mkdir()
            (ignored / "caption.txt").write_text("not a post folder", encoding="utf-8")

            save_posts(
                db_path, "Demo Page", "https://facebook.com/demopage",
                [SimpleNamespace(post_id="2001", date="01/01/2026", post_type="Video", caption="", url="",
                                 engagement=0, comments=0, shares=0, view_count=0)],
            )
            conn = _get_conn(db_path)
            conn.execute("UPDATE posts SET download_path = ? WHERE post_id = '2001'", (str(conflict_dir),))
            conn.commit()
            conn.close()

            result = migrate_legacy_subfolders_to_flat(out_dir, db_path)

            self.assertEqual(result["migrated_folders"], 0)
            self.assertEqual(source_video.read_bytes(), b"legacy video")
            self.assertEqual(nested_file.read_text(encoding="utf-8"), "keep")
            self.assertTrue((ignored / "caption.txt").exists())
            conn = _get_conn(db_path)
            db_path_after = conn.execute("SELECT download_path FROM posts WHERE post_id = '2001'").fetchone()[0]
            conn.close()
            self.assertEqual(db_path_after, str(conflict_dir))

    def test_storage_migration_keeps_source_when_move_fails(self):
        """A failed move leaves both the legacy file and its database reference intact."""
        from core.storage_migration import migrate_legacy_subfolders_to_flat

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "downloads"
            legacy_dir = out_dir / "3001"
            legacy_dir.mkdir(parents=True)
            source = legacy_dir / "caption.txt"
            source.write_text("must remain", encoding="utf-8")
            db_path = str(root / "migration-failure.db")
            save_posts(
                db_path, "Demo Page", "https://facebook.com/demopage",
                [SimpleNamespace(post_id="3001", date="01/01/2026", post_type="Text", caption="", url="",
                                 engagement=0, comments=0, shares=0, view_count=0)],
            )
            conn = _get_conn(db_path)
            conn.execute("UPDATE posts SET download_path = ? WHERE post_id = '3001'", (str(legacy_dir),))
            conn.commit()
            conn.close()

            with patch("core.storage_migration.shutil.move", side_effect=OSError("disk unavailable")):
                result = migrate_legacy_subfolders_to_flat(out_dir, db_path)

            self.assertEqual(result["migrated_folders"], 0)
            self.assertEqual(source.read_text(encoding="utf-8"), "must remain")
            conn = _get_conn(db_path)
            db_path_after = conn.execute("SELECT download_path FROM posts WHERE post_id = '3001'").fetchone()[0]
            conn.close()
            self.assertEqual(db_path_after, str(legacy_dir))

    def test_storage_migration_resumes_partial_media_without_false_download_status(self):
        """A retry keeps each legacy image's ordinal and stays failed until complete."""
        from core.storage_migration import migrate_legacy_subfolders_to_flat

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "downloads"
            legacy_dir = out_dir / "4001"
            legacy_dir.mkdir(parents=True)
            for ordinal in range(1, 4):
                (legacy_dir / f"image_{ordinal:03d}.jpg").write_bytes(f"image-{ordinal}".encode())
            db_path = str(root / "migration-resume.db")
            save_posts(
                db_path, "Demo Page", "https://facebook.com/demopage",
                [SimpleNamespace(post_id="4001", date="01/01/2026", post_type="Ảnh", media_count=3,
                                 caption="", url="", engagement=0, comments=0, shares=0, view_count=0)],
            )

            real_move = shutil.move

            def fail_second_image(source, target, *args, **kwargs):
                if Path(source).name == "image_002.jpg":
                    raise OSError("temporary media error")
                return real_move(source, target, *args, **kwargs)

            with patch("core.storage_migration.shutil.move", side_effect=fail_second_image):
                first_try = migrate_legacy_subfolders_to_flat(out_dir, db_path)

            self.assertEqual(first_try["migrated_folders"], 0)
            self.assertTrue((legacy_dir / "image_002.jpg").exists())
            self.assertTrue((out_dir / "4001_1.jpeg").exists())
            self.assertTrue((out_dir / "4001_3.jpeg").exists())
            self.assertFalse((out_dir / "4001_2.jpeg").exists())

            self.assertEqual(sync_downloaded_posts_from_folder(db_path, str(out_dir)), 1)
            conn = _get_conn(db_path)
            failed = conn.execute(
                "SELECT downloaded, download_status, download_path FROM posts WHERE post_id = '4001'"
            ).fetchone()
            conn.close()
            self.assertEqual(failed, (0, "failed", str(legacy_dir)))

            second_try = migrate_legacy_subfolders_to_flat(out_dir, db_path)
            self.assertEqual(second_try["migrated_folders"], 1)
            self.assertFalse(legacy_dir.exists())
            self.assertTrue((out_dir / "4001_2.jpeg").exists())

            self.assertEqual(sync_downloaded_posts_from_folder(db_path, str(out_dir)), 1)
            conn = _get_conn(db_path)
            completed = conn.execute(
                "SELECT downloaded, download_status, download_path FROM posts WHERE post_id = '4001'"
            ).fetchone()
            conn.close()
            self.assertEqual(completed, (1, "downloaded", str(out_dir)))

    def test_storage_migration_preserves_files_when_database_is_locked(self):
        """No filesystem mutation is allowed until the migration write lock is held."""
        from core.storage_migration import migrate_legacy_subfolders_to_flat

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "downloads"
            legacy_dir = out_dir / "5001"
            legacy_dir.mkdir(parents=True)
            source = legacy_dir / "caption.txt"
            source.write_text("must remain", encoding="utf-8")

            with patch(
                "core.storage_migration._get_conn",
                side_effect=sqlite3.OperationalError("database is locked"),
            ):
                result = migrate_legacy_subfolders_to_flat(out_dir, str(root / "locked.db"))

            self.assertEqual(result["migrated_folders"], 0)
            self.assertEqual(source.read_text(encoding="utf-8"), "must remain")
            self.assertFalse((out_dir / "5001.txt").exists())

    def test_storage_migration_keeps_conflicting_file_without_nested_folder(self):
        """A differing destination file never causes its legacy source to be removed."""
        from core.storage_migration import migrate_legacy_subfolders_to_flat

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            out_dir = root / "downloads"
            legacy_dir = out_dir / "6001"
            legacy_dir.mkdir(parents=True)
            source = legacy_dir / "caption.txt"
            source.write_text("legacy caption", encoding="utf-8")
            (out_dir / "6001.txt").write_text("different caption", encoding="utf-8")

            result = migrate_legacy_subfolders_to_flat(out_dir, str(root / "conflict.db"))

            self.assertEqual(result["migrated_folders"], 0)
            self.assertEqual(source.read_text(encoding="utf-8"), "legacy caption")
            self.assertTrue(legacy_dir.exists())


if __name__ == "__main__":
    unittest.main()
