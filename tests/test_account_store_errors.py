"""Regression: a failing account read must raise, not look like an empty account list."""

import tempfile
import unittest
from pathlib import Path

from core.db_storage import AccountStoreError, add_account, get_all_accounts, initialize_database


class AccountStoreErrorTests(unittest.TestCase):
    def test_unreadable_database_raises_instead_of_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            # A directory is not an openable SQLite file, so the read must fail.
            broken = Path(directory) / "not-a-database"
            broken.mkdir()

            with self.assertRaises(AccountStoreError):
                get_all_accounts(str(broken))

    def test_readable_database_still_returns_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "tinix.db")
            initialize_database(db_path)
            add_account(db_path, label="OK", username="demo", password="pw")

            self.assertEqual([item["label"] for item in get_all_accounts(db_path)], ["OK"])


if __name__ == "__main__":
    unittest.main()
