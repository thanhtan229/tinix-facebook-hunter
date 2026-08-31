from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def chrome_profiles_root() -> Path:
    root = project_root() / "Chrome Profiles"
    root.mkdir(parents=True, exist_ok=True)
    return root


def chrome_profile_dir(name: str) -> Path:
    path = chrome_profiles_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def browser_profile_dir() -> Path:
    return chrome_profile_dir("browser")


def scraper_profile_dir(account_id: int | None = None) -> Path:
    if account_id:
        return chrome_profile_dir(f"scraper_{int(account_id)}")
    return chrome_profile_dir("scraper")


def poster_profile_dir(account_id: int | None = None) -> Path:
    if account_id:
        return chrome_profile_dir(f"poster_{int(account_id)}")
    return chrome_profile_dir("poster")


def download_profile_dir(account_id: int | None = None) -> Path:
    if account_id:
        return chrome_profile_dir(f"download_{int(account_id)}")
    return chrome_profile_dir("download")


def debug_profile_dir() -> Path:
    return chrome_profile_dir("debug")


def platform_prefix(platform: str) -> str:
    mapping = {
        "facebook": "fb",
    }
    key = str(platform or "").strip().lower().replace(" ", "_")
    return mapping.get(key, "fb")


def social_profile_dir(platform: str, account_id: int | None = None) -> Path:
    prefix = platform_prefix(platform)
    if account_id:
        return chrome_profile_dir(f"{prefix}_{int(account_id)}")
    return chrome_profile_dir(prefix)
