import os
import json
import subprocess
import threading
import urllib.request
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import Field, HttpUrl
from typing import Optional, Dict, Any
from core.db_storage import (
    get_db_path,
    get_all_accounts,
    get_account,
    add_account,
    update_account,
    delete_account,
    get_all_managed_pages,
    get_social_accounts,
    add_social_account,
    update_social_account,
    delete_social_account,
)
from utils.chrome_profiles import scraper_profile_dir, chrome_profiles_root, project_root
from utils.profile_bundle import ProfileBundleError, export_bundle, import_bundle_profile, read_bundle
from utils import config
from core.version import APP_VERSION
from web.ws_manager import log_to_web
from web.models import ApiRequest, model_data
from websockets.sync.client import connect as websocket_connect

router = APIRouter(prefix="/api/accounts", tags=["Accounts"])

_CHROME_PROCESSES: Dict[int, subprocess.Popen] = {}
_CHROME_PROCESS_LOCK = threading.RLock()

ACCOUNT_SECRET_FIELDS = {
    "password", "secret_2fa", "email_pass", "cookie", "profile_dir"
}


def _public_account(account: Dict[str, Any]) -> Dict[str, Any]:
    """Return account metadata without credentials, cookies or tokens."""
    public = {k: v for k, v in account.items() if k not in ACCOUNT_SECRET_FIELDS}
    public["has_password"] = bool(account.get("password"))
    public["has_2fa"] = bool(account.get("secret_2fa"))
    public["has_cookie"] = bool(account.get("cookie"))
    return public

def _find_chrome_path() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return "chrome"

class AccountSaveRequest(ApiRequest):
    id: Optional[int] = Field(default=None, gt=0)
    label: Optional[str] = Field(default="", max_length=200)
    username: Optional[str] = Field(default="", max_length=500)
    password: Optional[str] = Field(default="", max_length=2_000)
    secret_2fa: Optional[str] = Field(default="", max_length=500)
    email: Optional[str] = Field(default="", max_length=500)
    email_pass: Optional[str] = Field(default="", max_length=2_000)
    cookie: Optional[str] = Field(default="", max_length=200_000)
    is_active: Optional[bool] = True

class AccountDeleteRequest(ApiRequest):
    account_id: int = Field(gt=0)

class LaunchProfileRequest(ApiRequest):
    account_id: int = Field(gt=0)
    url: Optional[HttpUrl] = "https://www.facebook.com"


class CloseProfileRequest(ApiRequest):
    account_id: int = Field(gt=0)


class ProfileExportRequest(ApiRequest):
    account_id: int = Field(gt=0)


class ProfileImportRequest(ApiRequest):
    bundle_path: str = Field(min_length=3, max_length=2_000)


def _chrome_debug_port(account_id: int) -> int:
    return 9400 + (int(account_id) % 400)


def _close_chrome_via_cdp(port: int) -> bool:
    """Gracefully close a Tinix Chrome instance through its local CDP port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as response:
            details = json.loads(response.read().decode("utf-8"))
        websocket_url = str(details.get("webSocketDebuggerUrl") or "")
        if not websocket_url:
            return False
        sent = False
        try:
            with websocket_connect(websocket_url, open_timeout=2, close_timeout=1) as socket:
                socket.send(json.dumps({"id": 1, "method": "Browser.close"}))
                sent = True
        except Exception:
            return sent
        return sent
    except Exception:
        return False


def _close_managed_chrome(account_id: int) -> bool:
    """Close one app-managed Chrome without touching the user's normal Chrome."""
    account_id = int(account_id)
    port = _chrome_debug_port(account_id)
    closed = _close_chrome_via_cdp(port)
    with _CHROME_PROCESS_LOCK:
        process = _CHROME_PROCESSES.pop(account_id, None)
    if process is not None and process.poll() is None:
        closed = True
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
    return closed

@router.get("/")
def list_accounts():
    """List all configured Facebook accounts."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    accounts = get_all_accounts(db_p)
    return {"status": "success", "data": [_public_account(account) for account in accounts]}

@router.post("/save")
def save_account_endpoint(req: AccountSaveRequest):
    """Add or update an account."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if req.id:
        # Update
        fields = model_data(req, exclude_unset=True)
        acc_id = fields.pop("id")
        success = update_account(db_p, acc_id, **fields)
        if not success:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản hoặc không có thay đổi")
        log_to_web(f"Đã cập nhật tài khoản ID #{acc_id}.", "OK")
        return {"status": "success", "id": acc_id}
    else:
        # Insert
        new_id = add_account(
            db_p,
            username=req.username or "",
            password=req.password or "",
            label=req.label or req.username or "Account mới",
            secret_2fa=req.secret_2fa or "",
            email=req.email or "",
            email_pass=req.email_pass or "",
            cookie=req.cookie or "",
            is_active=int(bool(req.is_active))
        )
        log_to_web(f"Đã thêm tài khoản mới ID #{new_id}.", "OK")
        return {"status": "success", "id": new_id}

@router.post("/delete")
def delete_account_endpoint(req: AccountDeleteRequest):
    """Delete an account by ID."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    delete_account(db_p, req.account_id)
    log_to_web(f"Đã xóa tài khoản ID #{req.account_id}.", "WARNING")
    return {"status": "success", "message": "Đã xóa tài khoản"}

@router.post("/launch")
def launch_chrome_profile(req: LaunchProfileRequest):
    """Launch dedicated Chrome Profile for account."""
    chrome_bin = _find_chrome_path()
    db_p = get_db_path(config.get("scraper_db_path", ""))
    account = get_account(db_p, req.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    stored_profile = str(account.get("profile_dir") or "").strip()
    profile_dir = str(
        Path(stored_profile).expanduser().resolve()
        if stored_profile else scraper_profile_dir(req.account_id).resolve()
    )
    port = _chrome_debug_port(req.account_id)
    target_url = str(req.url or "https://www.facebook.com")

    cmd = [
        chrome_bin,
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        target_url,
    ]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with _CHROME_PROCESS_LOCK:
            _CHROME_PROCESSES[req.account_id] = process
        log_to_web(f"Đã mở Chrome Profile cho Account #{req.account_id} (Port {port}).", "INFO")
        return {"status": "success", "profile_dir": profile_dir, "port": port}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể mở Chrome: {str(e)}") from e


@router.post("/close")
def close_chrome_profile(req: CloseProfileRequest):
    """Close the dedicated Chrome window for one account."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if get_account(db_p, req.account_id) is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    closed = _close_managed_chrome(req.account_id)
    message = "Đã đóng Chrome" if closed else "Chrome của account này không chạy"
    log_to_web(f"{message} cho Account #{req.account_id}.", "INFO")
    return {"status": "success", "closed": closed, "message": message}


@router.post("/close-all")
def close_all_chrome_profiles(_req: ApiRequest):
    """Close every Chrome instance launched from the Accounts tab."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    account_ids = {int(account["id"]) for account in get_all_accounts(db_p)}
    with _CHROME_PROCESS_LOCK:
        account_ids.update(_CHROME_PROCESSES)
    closed_count = sum(1 for account_id in sorted(account_ids) if _close_managed_chrome(account_id))
    log_to_web(f"Đã đóng {closed_count} cửa sổ Chrome do Tinix quản lý.", "INFO")
    return {"status": "success", "closed_count": closed_count}


@router.post("/profile/export")
def export_account_profile(req: ProfileExportRequest):
    """Export account metadata and its Chrome session as a portable Tinix bundle."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    account = get_account(db_p, req.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    profile_value = str(account.get("profile_dir") or "").strip()
    profile_dir = (
        Path(profile_value).expanduser().resolve()
        if profile_value else (chrome_profiles_root() / f"scraper_{req.account_id}").resolve()
    )
    name = str(account.get("label") or account.get("username") or f"Account #{req.account_id}").strip()
    try:
        result = export_bundle(
            profile_dir,
            project_root() / "exports" / "profiles",
            {
                "account_name": name,
                "platform": "facebook",
                "username": str(account.get("username") or ""),
                "source_app": "Tinix FB Down",
                "source_app_version": APP_VERSION,
                "source_account_id": str(req.account_id),
            },
        )
    except ProfileBundleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log_to_web(f"Đã Export profile “{name}” tới {result['bundle_path']}", "OK")
    return {"status": "success", **result}


@router.post("/profile/import")
def import_account_profile(req: ProfileImportRequest):
    """Create a Facebook account from a portable Tinix profile bundle."""
    try:
        _, manifest, _ = read_bundle(req.bundle_path)
    except ProfileBundleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    platform = str(manifest.get("platform") or "").strip().lower()
    if platform != "facebook":
        raise HTTPException(
            status_code=409,
            detail=f"Tab Accounts của FB Down hiện chỉ Import Facebook; gói này là {platform or 'không xác định'}.",
        )
    name = str(manifest["account_name"]).strip()
    username = str(manifest.get("username") or "").strip()
    db_p = get_db_path(config.get("scraper_db_path", ""))
    used_legacy_usernames = {str(item.get("username") or "") for item in get_all_accounts(db_p)}
    stored_username = username
    if not stored_username or stored_username in used_legacy_usernames:
        stored_username = f"tinix-import-{uuid.uuid4().hex[:8]}"
    legacy_id = add_account(db_p, label=name, username=stored_username, is_active=1)
    if legacy_id < 1:
        raise HTTPException(status_code=409, detail="Không thể tạo account từ gói profile.")

    existing_social = get_social_accounts(db_p, platform="facebook")
    social_username = stored_username
    used_usernames = {str(item.get("username") or "") for item in existing_social}
    if not social_username or social_username in used_usernames:
        social_username = f"tinix-import-{legacy_id}"
    social_id = add_social_account(
        db_p,
        platform="facebook",
        label=name,
        username=social_username,
        profile_dir="",
        is_active=1,
        legacy_fb_id=legacy_id,
        notes=f"Imported from {manifest.get('source_app') or 'Tinix profile bundle'}",
    )
    if social_id < 1:
        delete_account(db_p, legacy_id)
        raise HTTPException(status_code=409, detail="Không thể tạo liên kết Chrome profile cho account.")

    destination = (chrome_profiles_root() / f"fb_{social_id}").resolve()
    try:
        imported_manifest, result = import_bundle_profile(req.bundle_path, destination)
        if not update_social_account(db_p, social_id, profile_dir=str(destination)):
            raise ProfileBundleError("Không thể lưu đường dẫn profile đã Import.")
    except Exception as exc:
        delete_social_account(db_p, social_id)
        delete_account(db_p, legacy_id)
        if destination.exists():
            shutil.rmtree(destination)
        if isinstance(exc, ProfileBundleError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise
    log_to_web(f"Đã Import account “{name}” và Chrome profile từ gói Tinix.", "OK")
    return {
        "status": "success",
        "account_id": legacy_id,
        "account_name": name,
        "platform": platform,
        "source_app": imported_manifest.get("source_app"),
        **result,
    }

@router.get("/managed-pages")
def list_managed_pages():
    """List all managed Facebook fanpages across all accounts."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    pages = get_all_managed_pages(db_p)
    return {"status": "success", "data": pages}
