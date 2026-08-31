import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.testclient import TestClient

from core.data_cleanup import cleanup_scraped_data, preview_scraped_cleanup
from core.db_storage import (
    _get_conn, add_account, get_all_accounts, get_favorite_pages,
    get_scraped_pages_full, save_favorite_page,
)
from web.routes.spy import CleanupRequest, cleanup_repository
from web.app import app


def seed_scraped_data(db_path: str, output_root: Path, outside_root: Path) -> dict[str, Path]:
    page_a_media = output_root / "page-a-post"
    page_b_media = output_root / "page-b-post"
    outside_media = outside_root / "must-survive"
    for folder in (page_a_media, page_b_media, outside_media):
        folder.mkdir(parents=True)
        (folder / "media.txt").write_text("temporary test media", encoding="utf-8")

    connection = _get_conn(db_path)
    try:
        connection.executemany(
            "INSERT INTO pages (page_url, page_name, post_count) VALUES (?, ?, ?)",
            [
                ("https://facebook.com/page-a", "Page A", 3),
                ("https://facebook.com/page-b", "Page B", 1),
            ],
        )
        connection.executemany(
            """
            INSERT INTO posts
                (page_name, page_url, post_id, download_path, downloaded)
            VALUES (?, ?, ?, ?, 1)
            """,
            [
                ("Page A", "https://facebook.com/page-a", "a-1", str(page_a_media)),
                ("Page A", "https://facebook.com/page-a", "a-2", str(outside_media)),
                ("Page A", "https://facebook.com/page-a", "a-3", str(page_b_media)),
                ("Page B", "https://facebook.com/page-b", "b-1", str(page_b_media)),
            ],
        )
        connection.commit()
    finally:
        connection.close()
    return {"page_a": page_a_media, "page_b": page_b_media, "outside": outside_media}


class ScrapedCleanupTest(unittest.TestCase):
    def test_scoped_cleanup_backs_up_and_preserves_unselected_data(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(temp_dir)
            output_root = root / "output"
            output_root.mkdir()
            db_path = str(root / "cleanup.db")
            account_id = add_account(db_path, username="must-survive")
            favorite_id = save_favorite_page(db_path, "https://facebook.com/page-a", "Page A")
            media = seed_scraped_data(db_path, output_root, Path(outside_dir))

            preview = preview_scraped_cleanup(
                db_path, page_urls=["https://facebook.com/page-a"]
            )
            self.assertEqual(preview, {"pages": 1, "posts": 3, "media_paths": 3})
            result = cleanup_scraped_data(
                db_path,
                page_urls=["https://facebook.com/page-a"],
                delete_media=True,
                output_root=str(output_root),
            )

            self.assertTrue(Path(str(result["backup_path"])).is_file())
            self.assertEqual(result["pages_deleted"], 1)
            self.assertEqual(result["posts_deleted"], 3)
            self.assertEqual(result["media_deleted"], 1)
            self.assertEqual(result["media_skipped"], 1)
            self.assertFalse(media["page_a"].exists())
            self.assertTrue(media["page_b"].exists())
            self.assertTrue(media["outside"].exists())
            self.assertEqual([page["page_name"] for page in get_scraped_pages_full(db_path)], ["Page B"])
            self.assertEqual(get_all_accounts(db_path)[0]["id"], account_id)
            self.assertEqual(get_favorite_pages(db_path)[0]["id"], favorite_id)
            self.assertEqual(len(get_scraped_pages_full(str(result["backup_path"]))), 2)

    def test_clear_all_keeps_media_when_option_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(temp_dir)
            output_root = root / "output"
            output_root.mkdir()
            db_path = str(root / "all.db")
            media = seed_scraped_data(db_path, output_root, Path(outside_dir))
            result = cleanup_scraped_data(db_path, all_pages=True, output_root=str(output_root))
            self.assertEqual(result["pages_deleted"], 2)
            self.assertEqual(result["posts_deleted"], 4)
            self.assertTrue(media["page_a"].exists())
            self.assertTrue(media["page_b"].exists())
            self.assertEqual(get_scraped_pages_full(db_path), [])

    def test_cleanup_requires_exact_confirmation_and_refuses_during_scrape(self):
        with self.assertRaises(ValidationError):
            CleanupRequest(all_pages=True, confirmation="NO")
        request = CleanupRequest(all_pages=True, confirmation="XOA")
        with patch("web.routes.spy.scrape_is_running", return_value=True):
            with self.assertRaises(HTTPException) as context:
                cleanup_repository(request)
        self.assertEqual(context.exception.status_code, 409)

    def test_cleanup_api_returns_json_and_deletes_only_temporary_scraped_data(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(temp_dir)
            output_root = root / "output"
            output_root.mkdir()
            db_path = str(root / "api-cleanup.db")
            seed_scraped_data(db_path, output_root, Path(outside_dir))
            with patch.dict("os.environ", {"TINIX_DB_PATH": db_path}):
                with TestClient(app) as client:
                    client.get("/")
                    response = client.post(
                        "/api/spy/cleanup",
                        json={
                            "page_urls": ["https://facebook.com/page-a"],
                            "all_pages": False,
                            "delete_media": False,
                            "confirmation": "XOA",
                        },
                    )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()["data"]
            self.assertEqual(payload["pages_deleted"], 1)
            self.assertEqual(payload["posts_deleted"], 3)
            self.assertTrue(Path(payload["backup_path"]).is_file())
            self.assertEqual([page["page_name"] for page in get_scraped_pages_full(db_path)], ["Page B"])


if __name__ == "__main__":
    unittest.main()
