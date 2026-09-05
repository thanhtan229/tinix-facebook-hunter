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
from utils.profile_bundle import (
    ProfileBundleError,
    export_bundle,
    export_profiles_archive,
    extracted_profiles_archive,
    import_bundle_profile,
    import_profile_from_directory,
    cleanup_profiles as cleanup_chrome_profile_data,
    preview_profiles_cleanup,
    read_bundle,
)
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
                "email": str(account.get("email") or ""),
                "password": str(account.get("password") or ""),
                "secret_2fa": str(account.get("secret_2fa") or ""),
                "email_pass": str(account.get("email_pass") or ""),
                "cookie": str(account.get("cookie") or ""),
                "source_app": "Tinix-Facebook-Hunter",
                "source_app_version": APP_VERSION,
                "source_account_id": str(req.account_id),
            },
        )
    except ProfileBundleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log_to_web(f"Đã Export profile “{name}” tới {result['bundle_path']}", "OK")
    return {"status": "success", **result}


@router.post("/profile/export-all")
def export_all_account_profiles():
    """Export every Facebook account/profile into one cross-app ZIP archive."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    profiles: list[tuple[Path, dict[str, Any]]] = []
    for account in get_all_accounts(db_p):
        account_id = int(account["id"])
        profile_value = str(account.get("profile_dir") or "").strip()
        profile_dir = (
            Path(profile_value).expanduser().resolve()
            if profile_value else (chrome_profiles_root() / f"scraper_{account_id}").resolve()
        )
        profiles.append((profile_dir, {
            "account_name": str(account.get("label") or account.get("username") or f"Account #{account_id}").strip(),
            "platform": "facebook",
            "username": str(account.get("username") or ""),
            "email": str(account.get("email") or ""),
            "password": str(account.get("password") or ""),
            "secret_2fa": str(account.get("secret_2fa") or ""),
            "email_pass": str(account.get("email_pass") or ""),
            "cookie": str(account.get("cookie") or ""),
            "source_account_id": str(account_id),
        }))
    log_to_web(f"Bắt đầu Export {len(profiles)} account/profile. Quá trình sao chép và nén có thể mất vài phút.", "INFO")
    try:
        result = export_profiles_archive(
            profiles,
            project_root() / "exports" / "profiles",
            source_app="Tinix-Facebook-Hunter",
            source_app_version=APP_VERSION,
        )
    except ProfileBundleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log_to_web(f"Đã Export {result['accounts_exported']} profile vào {result['archive_path']}", "OK")
    return {"status": "success", **result}


def _cleanup_profile_sources(db_p: str) -> list[tuple[Path, str]]:
    profiles: list[tuple[Path, str]] = []
    for account in get_all_accounts(db_p):
        account_id = int(account["id"])
        profile_value = str(account.get("profile_dir") or "").strip()
        profile_dir = (
            Path(profile_value).expanduser().resolve()
            if profile_value else (chrome_profiles_root() / f"scraper_{account_id}").resolve()
        )
        name = str(account.get("label") or account.get("username") or f"Account #{account_id}").strip()
        profiles.append((profile_dir, name))
    return profiles


@router.get("/profile/cleanup-preview")
def preview_account_profiles_cleanup():
    db_p = get_db_path(config.get("scraper_db_path", ""))
    try:
        result = preview_profiles_cleanup(_cleanup_profile_sources(db_p))
    except ProfileBundleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "success", **result}


@router.post("/profile/cleanup")
def cleanup_account_profiles():
    db_p = get_db_path(config.get("scraper_db_path", ""))
    log_to_web("Bắt đầu dọn cache và dữ liệu tạm của các Chrome profile.", "INFO")
    try:
        result = cleanup_chrome_profile_data(_cleanup_profile_sources(db_p))
    except ProfileBundleError as exc:
        log_to_web(f"Không thể dọn Chrome profile: {exc}", "ERROR")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log_to_web(
        f"Đã dọn {result['profiles_cleaned']} profile, giải phóng {result['bytes_freed']} byte.", "OK"
    )
    return {"status": "success", **result}


def _create_account_from_profile(db_p: str, metadata: dict[str, Any], source_profile: Path) -> dict[str, Any]:
    name = str(metadata["account_name"]).strip()
    username = str(metadata.get("username") or "").strip()
    used_legacy_usernames = {str(item.get("username") or "") for item in get_all_accounts(db_p)}
    stored_username = username
    if not stored_username or stored_username in used_legacy_usernames:
        stored_username = f"tinix-import-{uuid.uuid4().hex[:8]}"
    legacy_id = add_account(
        db_p, label=name, username=stored_username,
        email=str(metadata.get("email") or ""), password=str(metadata.get("password") or ""),
        secret_2fa=str(metadata.get("secret_2fa") or ""),
        email_pass=str(metadata.get("email_pass") or ""), cookie=str(metadata.get("cookie") or ""),
        is_active=1,
    )
    if legacy_id < 1:
        raise ProfileBundleError(f"Không thể tạo account “{name}”.")

    social_username = stored_username
    used_social_usernames = {str(item.get("username") or "") for item in get_social_accounts(db_p, platform="facebook")}
    if not social_username or social_username in used_social_usernames:
        social_username = f"tinix-import-{legacy_id}"
    social_id = add_social_account(
        db_p,
        platform="facebook",
        label=name,
        username=social_username,
        profile_dir="",
        is_active=1,
        legacy_fb_id=legacy_id,
        notes=f"Imported from {metadata.get('source_app') or 'Tinix profiles archive'}",
    )
    if social_id < 1:
        delete_account(db_p, legacy_id)
        raise ProfileBundleError(f"Không thể tạo liên kết Chrome profile cho “{name}”.")
    destination = (chrome_profiles_root() / f"fb_{social_id}").resolve()
    try:
        result = import_profile_from_directory(source_profile, destination)
        if not update_social_account(db_p, social_id, profile_dir=str(destination)):
            raise ProfileBundleError("Không thể lưu đường dẫn profile đã Import.")
    except Exception:
        delete_social_account(db_p, social_id)
        delete_account(db_p, legacy_id)
        if destination.exists():
            shutil.rmtree(destination)
        raise
    return {
        "account_id": legacy_id,
        "social_account_id": social_id,
        "account_name": name,
        "platform": "facebook",
        **result,
    }


@router.post("/profile/import")
def import_account_profile(req: ProfileImportRequest):
    """Import one legacy bundle or every Facebook profile from a Tinix ZIP."""
    source_path = Path(os.path.expandvars(os.path.expanduser(req.bundle_path))).resolve()
    if source_path.is_file():
        db_p = get_db_path(config.get("scraper_db_path", ""))
        imported: list[dict[str, Any]] = []
        try:
            with extracted_profiles_archive(req.bundle_path) as (archive_manifest, entries):
                facebook_entries = [(metadata, profile) for metadata, profile in entries if metadata["platform"] == "facebook"]
                skipped = [metadata["account_name"] for metadata, _ in entries if metadata["platform"] != "facebook"]
                if not facebook_entries:
                    raise ProfileBundleError("File ZIP không có profile Facebook để Import vào FB Down.")
                for metadata, profile in facebook_entries:
                    imported.append(_create_account_from_profile(
                        db_p, {**metadata, "source_app": archive_manifest.get("source_app")}, profile
                    ))
                result = {
                    "status": "success",
                    "accounts_imported": len(imported),
                    "accounts": imported,
                    "profiles_skipped": len(skipped),
                    "skipped_accounts": skipped,
                    "source_app": archive_manifest.get("source_app"),
                }
        except Exception as exc:
            for account in reversed(imported):
                profile = Path(str(account.get("profile_path") or ""))
                delete_social_account(db_p, int(account["social_account_id"]))
                delete_account(db_p, int(account["account_id"]))
                if profile.is_dir() and profile.parent == chrome_profiles_root().resolve():
                    shutil.rmtree(profile)
            if isinstance(exc, ProfileBundleError):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise
        log_to_web(f"Đã Import {len(imported)} account/profile Facebook từ một file ZIP.", "OK")
        return result

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
    legacy_id = add_account(
        db_p, label=name, username=stored_username,
        email=str(manifest.get("email") or ""), password=str(manifest.get("password") or ""),
        secret_2fa=str(manifest.get("secret_2fa") or ""),
        email_pass=str(manifest.get("email_pass") or ""), cookie=str(manifest.get("cookie") or ""),
        is_active=1,
    )
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
