from __future__ import annotations

import sys
import subprocess
import time
import urllib.request
from pathlib import Path


def shutdown_owned_chrome(browser, process, cdp_port: int, timeout: float = 10.0) -> None:
    """Close worker-owned Chrome and wait before handing off its profile.

    Closing an attached Playwright browser can only disconnect the client.
    Use Browser.close to shut down Chrome itself. Never call for reused Chrome.
    """
    if browser is not None:
        try:
            browser.new_browser_cdp_session().send("Browser.close")
        except Exception:
            # Chrome may disconnect before acknowledging Browser.close.
            pass
        try:
            browser.close()
        except Exception:
            pass
    if process is not None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/version", timeout=0.5):
                running = True
        except OSError:
            running = False
        if not running:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("Chrome worker chưa đóng hoàn toàn; chưa thể bàn giao profile.")
        time.sleep(0.1)


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
