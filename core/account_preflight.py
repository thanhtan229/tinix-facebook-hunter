"""Non-destructive Facebook account readiness checks for media downloads."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List

from core.cookie_handler import parse_cookie_string
from core.facebook_parser import BrowserManager
from utils.chrome_profiles import scraper_profile_dir


@dataclass
class AccountPreflightResult:
    account_id: int
    label: str
    profile_dir: str
    ready: bool
    code: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def resolve_download_profile(account: Dict[str, Any]) -> str:
    """Use the account profile opened by the UI and scraper.

    Older accounts without an explicit linked social profile are opened in
    ``scraper_<id>`` by the account UI.  Preflight and downloading must use
    that same directory, otherwise a freshly completed login is checked
    against a new, anonymous ``download_<id>`` profile.
    """
    account_id = int(account.get("id") or 0)
    return str(account.get("profile_dir") or account.get("download_profile_dir") or scraper_profile_dir(account_id))


def account_label(account: Dict[str, Any]) -> str:
    account_id = int(account.get("id") or 0)
    return str(account.get("label") or account.get("username") or f"Account #{account_id}")


def check_facebook_account(account: Dict[str, Any]) -> AccountPreflightResult:
    """Start an isolated headless profile briefly and verify Facebook authentication."""
    account_id = int(account.get("id") or 0)
    label = account_label(account)
    profile_dir = resolve_download_profile(account)

    if not account.get("is_active"):
        return AccountPreflightResult(
            account_id, label, profile_dir, False, "ACCOUNT_DISABLED",
            "Account đang tắt nên không được dùng để tải.",
        )

    # Preflight only consumes the cookie and the Chrome profile. An unreadable password or
    # 2FA secret must not block an account whose profile session is still valid.
    cookie_unreadable = "cookie" in (account.get("secrets_unreadable") or [])
    cookies = parse_cookie_string(str(account.get("cookie") or ""))
    browser = BrowserManager(
        profile_dir=profile_dir,
        cdp_port=9700 + (account_id % 200),
        headless=True,
    )
    try:
        if browser.start(cookies, require_authenticated=True):
            return AccountPreflightResult(
                account_id, label, profile_dir, True, "READY",
                "Phiên Facebook hợp lệ; sẵn sàng nhận bài tải.",
            )
        if cookie_unreadable:
            return AccountPreflightResult(
                account_id, label, profile_dir, False, "SECRET_UNREADABLE",
                "Không đọc được cookie đã lưu trên máy này và phiên trong profile không hợp lệ. "
                "Mã hóa chỉ giải mã được trên đúng tài khoản Windows và máy đã lưu; hãy nhập lại cookie.",
            )
        return AccountPreflightResult(
            account_id, label, profile_dir, False,
            browser.last_start_error_code or "PREFLIGHT_FAILED",
            browser.last_start_error_message or "Không thể kiểm tra phiên Facebook của profile.",
        )
    finally:
        browser.stop()


def check_facebook_accounts(accounts: Iterable[Dict[str, Any]]) -> List[AccountPreflightResult]:
    return [check_facebook_account(account) for account in accounts]
