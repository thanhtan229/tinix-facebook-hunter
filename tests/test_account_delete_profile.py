"""Regression: deleting an account keeps its Chrome profile unless the user explicitly asks to remove it."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from core.db_storage import add_account, add_social_account, get_account, get_all_accounts, initialize_database
from web.routes.accounts import AccountDeleteRequest, delete_account_endpoint


class DeleteAccountProfileTests(unittest.TestCase):
    def _setup(self, root: Path, profile_dir: Path) -> tuple[str, int]:
        db_path = str(root / "tinix.db")
        initialize_database(db_path)
        legacy_id = add_account(db_path, label="Xóa profile", username="demo", password="pw")
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "Cookies").write_text("session", encoding="utf-8")
        add_social_account(
            db_path, platform="facebook", label="Xóa profile", username="demo",
            profile_dir=str(profile_dir), legacy_fb_id=legacy_id, is_active=1,
        )
        return db_path, legacy_id

    def _delete(self, db_path: str, root: Path, account_id: int, delete_profile: bool):
        def config_value(key, default=None):
            return db_path if key == "scraper_db_path" else default

        with (
            patch("web.routes.accounts.config.get", side_effect=config_value),
            patch("web.routes.accounts.chrome_profiles_root", return_value=root / "profiles"),
            patch("web.routes.accounts.log_to_web"),
            patch("web.routes.scraper.scrape_is_running", return_value=False),
            patch("web.routes.downloader.download_has_active_or_pending_work", return_value=False),
        ):
            return delete_account_endpoint(AccountDeleteRequest(account_id=account_id, delete_profile=delete_profile))

    def test_default_delete_keeps_profile_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profiles" / "fb_1"
            db_path, legacy_id = self._setup(root, profile)

            result = self._delete(db_path, root, legacy_id, delete_profile=False)

            self.assertIsNone(get_account(db_path, legacy_id))
            self.assertFalse(result["profile_deleted"])
            self.assertTrue((profile / "Cookies").is_file())

    def test_explicit_delete_removes_profile_inside_managed_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profiles" / "fb_1"
            db_path, legacy_id = self._setup(root, profile)

            result = self._delete(db_path, root, legacy_id, delete_profile=True)

            self.assertIsNone(get_account(db_path, legacy_id))
            self.assertTrue(result["profile_deleted"])
            self.assertFalse(profile.exists())

    def test_profile_outside_managed_root_is_never_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "elsewhere" / "fb_1"
            db_path, legacy_id = self._setup(root, outside)

            with self.assertRaises(HTTPException) as ctx:
                self._delete(db_path, root, legacy_id, delete_profile=True)

            self.assertEqual(ctx.exception.status_code, 409)
            self.assertTrue((outside / "Cookies").is_file(), "folder outside the managed root must survive")
            self.assertTrue(any(item["id"] == legacy_id for item in get_all_accounts(db_path)),
                            "account must not be deleted when the profile step is refused")

    def test_default_delete_reports_failure_instead_of_success_when_db_delete_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profiles" / "fb_1"
            db_path, legacy_id = self._setup(root, profile)

            with patch("web.routes.accounts.delete_account", return_value=False):
                with self.assertRaises(HTTPException) as ctx:
                    self._delete(db_path, root, legacy_id, delete_profile=False)

            self.assertEqual(ctx.exception.status_code, 500)
            self.assertTrue((profile / "Cookies").is_file())

    def test_failed_db_delete_never_touches_the_profile_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profiles" / "fb_1"
            db_path, legacy_id = self._setup(root, profile)

            with patch("web.routes.accounts.delete_account", return_value=False):
                with self.assertRaises(HTTPException) as ctx:
                    self._delete(db_path, root, legacy_id, delete_profile=True)

            self.assertEqual(ctx.exception.status_code, 500)
            self.assertTrue((profile / "Cookies").is_file(), "folder must survive a failed DB delete")
            self.assertTrue(any(item["id"] == legacy_id for item in get_all_accounts(db_path)))

    def test_folder_failure_is_reported_as_partial_and_lease_is_released(self) -> None:
        from core.profile_lease import acquire_profile_leases, release_profile_leases

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profiles" / "fb_1"
            db_path, legacy_id = self._setup(root, profile)
            account = {"id": legacy_id, "profile_dir": str(profile), "is_active": 1}

            with patch("web.routes.accounts.shutil.rmtree", side_effect=PermissionError("locked")):
                result = self._delete(db_path, root, legacy_id, delete_profile=True)

            self.assertEqual(result["status"], "partial")
            self.assertFalse(result["profile_deleted"])
            self.assertIsNone(get_account(db_path, legacy_id), "account row is deleted in this case")
            # The lease must be free again: a second acquire must succeed.
            keys = acquire_profile_leases("after-partial-delete", [account])
            release_profile_leases("after-partial-delete", keys)

    def test_profile_shared_with_another_account_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "profiles" / "fb_shared"
            db_path, legacy_id = self._setup(root, profile)
            other_id = add_account(db_path, label="Chia sẻ", username="other", password="pw")
            add_social_account(
                db_path, platform="facebook", label="Chia sẻ", username="other",
                profile_dir=str(profile), legacy_fb_id=other_id, is_active=1,
            )

            with self.assertRaises(HTTPException) as ctx:
                self._delete(db_path, root, legacy_id, delete_profile=True)

            self.assertEqual(ctx.exception.status_code, 409)
            self.assertTrue((profile / "Cookies").is_file())
            self.assertTrue(any(item["id"] == legacy_id for item in get_all_accounts(db_path)))


if __name__ == "__main__":
    unittest.main()
