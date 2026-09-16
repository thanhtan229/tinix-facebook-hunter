"""In-process ownership for Chrome profiles used by background Facebook work."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterable

from core.account_preflight import resolve_download_profile
from utils.chrome_profiles import scraper_profile_dir


class ProfileLeaseConflict(RuntimeError):
    """Raised when a task attempts to open a profile owned by another task."""


_LEASE_LOCK = threading.RLock()
_LEASES: dict[str, str] = {}


def profile_key(account: dict[str, Any] | None = None) -> str:
    """Return a stable, case-insensitive key for an account or default scraper profile."""
    profile_dir = resolve_download_profile(account) if account else str(scraper_profile_dir())
    return str(Path(profile_dir).expanduser().resolve()).casefold()


def acquire_profile_leases(owner: str, accounts: Iterable[dict[str, Any] | None]) -> set[str]:
    """Atomically reserve all requested profiles for one in-process task."""
    owner = str(owner or "facebook-task")[:120]
    keys = {profile_key(account) for account in accounts}
    with _LEASE_LOCK:
        conflicts = sorted({current for key, current in _LEASES.items() if key in keys and current != owner})
        if conflicts:
            raise ProfileLeaseConflict(
                "Chrome profile đang được dùng bởi " + ", ".join(conflicts[:3]) + "."
            )
        for key in keys:
            _LEASES[key] = owner
    return keys


def release_profile_leases(owner: str, keys: Iterable[str]) -> None:
    """Release only leases still owned by this task."""
    with _LEASE_LOCK:
        for key in keys:
            if _LEASES.get(key) == owner:
                _LEASES.pop(key, None)


def profile_lease_owner(account: dict[str, Any] | None = None) -> str:
    """Return the current owner label, if any."""
    with _LEASE_LOCK:
        return _LEASES.get(profile_key(account), "")
