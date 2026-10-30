"""Regression: credentials are left out of profile bundles unless the user explicitly opts in."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.db_storage import add_account, add_social_account, initialize_database
from utils.profile_bundle import export_bundle
from web.routes.accounts import ProfileExportRequest, export_account_profile

from tests.test_profile_bundle import make_profile


def _manifest_of_bundle(bundle: Path) -> dict:
    return json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))


class BundleSecretOptInTests(unittest.TestCase):
    def _export_route(self, root: Path, include_secrets: bool) -> dict:
        db_path = str(root / "tinix.db")
        initialize_database(db_path)
        legacy_id = add_account(
            db_path, label="Bundle", username="demo", email="demo@example.com",
            password="fb-password", secret_2fa="JBSWY3DPEHPK3PXP",
            email_pass="mail-password", cookie="db-cookie",
        )
        source = make_profile(root / "profiles" / "fb_source", session="session-cookie")
        add_social_account(
            db_path, platform="facebook", label="Bundle", username="demo",
            profile_dir=str(source), legacy_fb_id=legacy_id, is_active=1,
        )

        def config_value(key, default=None):
            return db_path if key == "scraper_db_path" else default

        with (
            patch("web.routes.accounts.config.get", side_effect=config_value),
            patch("web.routes.accounts.project_root", return_value=root),
            patch("web.routes.accounts.log_to_web"),
        ):
            return export_account_profile(ProfileExportRequest(account_id=legacy_id, include_secrets=include_secrets))

    def test_default_export_contains_no_credentials_but_keeps_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self._export_route(root, include_secrets=False)
            bundle = Path(result["bundle_path"])

            manifest = _manifest_of_bundle(bundle)
            for key in ("password", "secret_2fa", "email_pass", "cookie"):
                self.assertEqual(manifest.get(key, ""), "", f"{key} must not be written by default")
            self.assertFalse(manifest["contains_account_secrets"])
            # The Chrome session is still packaged, so the bundle is not credential-free.
            self.assertTrue(any(bundle.rglob("Cookies")), "session files stay in the bundle")

    def test_explicit_opt_in_writes_credentials_and_flags_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self._export_route(root, include_secrets=True)
            manifest = _manifest_of_bundle(Path(result["bundle_path"]))

            self.assertEqual(manifest["password"], "fb-password")
            self.assertEqual(manifest["secret_2fa"], "JBSWY3DPEHPK3PXP")
            self.assertTrue(manifest["contains_account_secrets"])

    def test_flag_reflects_content_for_bundle_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_profile(root / "src")
            bundle = export_bundle(
                source, root / "out",
                {"account_name": "No secrets", "platform": "facebook", "password": "", "cookie": ""},
            )
            manifest = _manifest_of_bundle(Path(bundle["bundle_path"]))

            self.assertFalse(manifest["contains_account_secrets"])


if __name__ == "__main__":
    unittest.main()
