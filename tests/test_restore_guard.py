"""Regression: a restore must not overwrite a database while the WebUI is running and owns it."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.database_maintenance import create_database_backup, restore_database
from core.db_storage import add_account, get_all_accounts, initialize_database


class RestoreRunningAppGuardTests(unittest.TestCase):
    def test_restore_refuses_while_app_is_running_and_keeps_live_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = str(root / "live.db")
            initialize_database(live)
            add_account(live, label="Đang dùng", username="live", password="pw")
            backup = create_database_backup(live, root / "backup.sqlite")

            add_account(live, label="Sau backup", username="later", password="pw")
            before = Path(live).read_bytes()

            with patch("core.database_maintenance._app_is_running", return_value=True):
                with self.assertRaises(RuntimeError) as ctx:
                    restore_database(live, backup)

            self.assertIn("Đóng ứng dụng", str(ctx.exception))
            self.assertEqual(Path(live).read_bytes(), before, "live database must be untouched")
            labels = [item["label"] for item in get_all_accounts(live)]
            self.assertIn("Sau backup", labels)


if __name__ == "__main__":
    unittest.main()
