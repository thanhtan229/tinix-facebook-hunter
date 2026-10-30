"""Regression: deleting a Facebook account must not leave linked social rows that point at it."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db_storage import add_account, add_social_account, delete_account, get_all_accounts, initialize_database, save_facebook_token


class DeleteCascadeTests(unittest.TestCase):
    def test_delete_removes_linked_social_rows_and_keeps_other_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "tinix.db")
            initialize_database(db_path)
            gone = add_account(db_path, label="Xóa", username="gone", password="pw")
            kept = add_account(db_path, label="Giữ", username="kept", password="pw")
            add_social_account(db_path, platform="facebook", label="Xóa", username="gone",
                               profile_dir="x/fb_1", legacy_fb_id=gone, is_active=1)
            add_social_account(db_path, platform="facebook", label="Giữ", username="kept",
                               profile_dir="x/fb_2", legacy_fb_id=kept, is_active=1)

            save_facebook_token(db_path, gone, uid="1", access_token="token-gone")
            save_facebook_token(db_path, kept, uid="2", access_token="token-kept")

            self.assertTrue(delete_account(db_path, gone))

            conn = sqlite3.connect(db_path)
            try:
                linked_gone = conn.execute("SELECT COUNT(*) FROM social_accounts WHERE legacy_fb_id = ?", (gone,)).fetchone()[0]
                linked_kept = conn.execute("SELECT COUNT(*) FROM social_accounts WHERE legacy_fb_id = ?", (kept,)).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(linked_gone, 0)
            self.assertEqual(linked_kept, 1)
            conn = sqlite3.connect(db_path)
            try:
                tokens = [r[0] for r in conn.execute("SELECT account_id FROM facebook_tokens ORDER BY account_id")]
            finally:
                conn.close()
            self.assertEqual(tokens, [kept], "tokens of a deleted account must not survive")
            self.assertEqual([item["id"] for item in get_all_accounts(db_path)], [kept])


if __name__ == "__main__":
    unittest.main()
