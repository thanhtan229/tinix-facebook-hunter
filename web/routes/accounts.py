import os
import json
import subprocess
import threading
import urllib.request
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
)
from utils.chrome_profiles import scraper_profile_dir
from utils import config
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

@router.get("/managed-pages")
def list_managed_pages():
    """List all managed Facebook fanpages across all accounts."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    pages = get_all_managed_pages(db_p)
    return {"status": "success", "data": pages}
