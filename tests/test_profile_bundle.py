from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.db_storage import add_account, add_social_account, get_all_accounts, initialize_database
from utils.profile_bundle import export_bundle, import_bundle_profile, read_bundle
from web.routes.accounts import (
    ProfileExportRequest,
    ProfileImportRequest,
    export_account_profile,
    import_account_profile,
)


def make_profile(path: Path, session: str = "session") -> Path:
    (path / "Default" / "Cache").mkdir(parents=True)
    (path / "Local State").write_text("{}", encoding="utf-8")
    (path / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    (path / "Default" / "Cookies").write_text(session, encoding="utf-8")
    (path / "Default" / "Cache" / "ignored.bin").write_bytes(b"cache")
    (path / "SingletonLock").write_text("lock", encoding="utf-8")
    return path


class ProfileBundleTests(unittest.TestCase):
    def test_accounts_ui_exposes_import_and_export_controls(self) -> None:
        root = Path(__file__).resolve().parents[1] / "web" / "static"
        html = (root / "index.html").read_text(encoding="utf-8")
        javascript = (root / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="btn-import-profile"', html)
        self.assertIn('id="btn-export-profile"', html)
        self.assertIn("exportAccountProfile", javascript)
        self.assertIn("exportSelectedAccountProfile", javascript)
        self.assertIn("/api/accounts/profile/import", javascript)
        self.assertIn("/api/accounts/profile/export", javascript)

    def test_export_and_import_portable_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_profile(root / "fb_2")
            exported = export_bundle(source, root / "exports", {
                "account_name": "Facebook chính",
                "platform": "facebook",
                "username": "demo",
                "source_app": "Tinix FB Down",
                "source_app_version": "test",
                "source_account_id": "2",
            })
            bundle = Path(exported["bundle_path"])
            _, manifest, profile = read_bundle(str(bundle))
            self.assertEqual(manifest["bundle_format"], "tinix-profile")
            self.assertEqual(manifest["account_name"], "Facebook chính")
            self.assertEqual(manifest["platform"], "facebook")
            self.assertFalse((profile / "Default" / "Cache" / "ignored.bin").exists())
            self.assertFalse((profile / "SingletonLock").exists())

            destination = root / "imported" / "fb_9"
            imported_manifest, result = import_bundle_profile(str(bundle), destination)
            self.assertEqual(imported_manifest["username"], "demo")
            self.assertEqual(Path(result["profile_path"]), destination)
            self.assertEqual((destination / "Default" / "Cookies").read_text(), "session")

    def test_accepts_social_hub_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "from-hub.tinix-profile"
            make_profile(bundle / "chrome-profile")
            (bundle / "manifest.json").write_text(json.dumps({
                "bundle_format": "tinix-profile",
                "format_version": 1,
                "account_name": "Hub Account",
                "platform": "facebook",
                "source_app": "Tinix Social Hub",
                "source_account_id": "abc",
            }), encoding="utf-8")
            _, manifest, _ = read_bundle(str(bundle))
            self.assertEqual(manifest["account_name"], "Hub Account")

    def test_accounts_routes_preserve_name_through_export_and_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = str(root / "tinix.db")
            initialize_database(db_path)
            legacy_id = add_account(db_path, label="Tên giữ nguyên", username="demo")
            source = make_profile(root / "profiles" / "fb_source")
            add_social_account(
                db_path, platform="facebook", label="Tên giữ nguyên", username="demo",
                profile_dir=str(source), legacy_fb_id=legacy_id, is_active=1,
            )

            def config_value(key, default=None):
                return db_path if key == "scraper_db_path" else default

            with (
                patch("web.routes.accounts.config.get", side_effect=config_value),
                patch("web.routes.accounts.project_root", return_value=root),
                patch("web.routes.accounts.chrome_profiles_root", return_value=root / "imported-profiles"),
            ):
                exported = export_account_profile(ProfileExportRequest(account_id=legacy_id))
                imported = import_account_profile(ProfileImportRequest(bundle_path=exported["bundle_path"]))

            accounts = get_all_accounts(db_path)
            imported_account = next(item for item in accounts if item["id"] == imported["account_id"])
            self.assertEqual(imported_account["label"], "Tên giữ nguyên")
            self.assertEqual(imported["platform"], "facebook")
            self.assertTrue(Path(imported["profile_path"]).is_dir())


if __name__ == "__main__":
    unittest.main()
