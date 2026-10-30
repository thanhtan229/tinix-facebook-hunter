import os
import json
import subprocess
import threading
import time
import urllib.request
import shutil
import uuid
import psutil
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import Field, HttpUrl
from typing import Literal, Optional, Dict, Any
from core.db_storage import AccountStoreError
from core.db_storage import (
    get_db_path,
    get_all_accounts,
    get_account,
    add_account,
    update_account,
    save_account_preflight_result,
    delete_account,
    get_all_managed_pages,
    get_social_accounts,
    add_social_account,
    update_social_account,
    delete_social_account,
)
from core.account_preflight import check_facebook_account
from core.profile_lease import (
    ProfileLeaseConflict,
    acquire_profile_leases,
    release_profile_leases,
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
_MANAGED_PROFILE_LEASES: Dict[int, tuple[str, set[str]]] = {}

# Large, long-lived account profiles can need more than a few seconds after a
# browser upgrade before their DevTools endpoint is ready.  Keep this bounded so
# the web request cannot wait indefinitely.
_CDP_START_TIMEOUT_S = 25.0
_CDP_RECOVERY_TIMEOUT_S = 15.0
_STATUS_BREAKPOINT = 0x80000003

ACCOUNT_SECRET_FIELDS = {
    "password", "secret_2fa", "email_pass", "cookie", "profile_dir", "recovery_codes"
}


def _public_account(account: Dict[str, Any]) -> Dict[str, Any]:
    """Return account metadata without credentials, cookies or tokens."""
    public = {k: v for k, v in account.items() if k not in ACCOUNT_SECRET_FIELDS}
    public["has_password"] = bool(account.get("password"))
    public["has_2fa"] = bool(account.get("secret_2fa"))
    public["has_cookie"] = bool(account.get("cookie"))
    public["has_recovery_codes"] = bool(account.get("recovery_codes"))
    # Lets the UI show "credential không đọc được" instead of a silent "chưa có mật khẩu".
    public["secrets_unreadable"] = list(account.get("secrets_unreadable") or [])
    account_id = int(account.get("id") or 0)
    port = _chrome_debug_port(account_id) if account_id else 0
    with _CHROME_PROCESS_LOCK:
        proc = _CHROME_PROCESSES.get(account_id)
        is_running = proc is not None and proc.poll() is None
    public["port"] = port
    public["is_chrome_running"] = is_running
    return public

def _find_browser_paths() -> list[str]:
    """Find installed Chromium browsers in launch preference order."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    found: list[str] = []
    for path in candidates:
        if path and os.path.exists(path) and path not in found:
            found.append(path)
    for command in ("chrome", "msedge"):
        resolved = shutil.which(command)
        if resolved and resolved not in found:
            found.append(resolved)
    return found


def _find_chrome_path() -> Optional[str]:
    """Return the preferred Chromium browser for compatibility callers."""
    paths = _find_browser_paths()
    return paths[0] if paths else None


def _browser_label(browser_path: str) -> str:
    return "Microsoft Edge" if Path(browser_path).stem.casefold() == "msedge" else "Google Chrome"


def _wait_for_cdp_port(
    process: subprocess.Popen,
    port: int,
    timeout_s: float = _CDP_START_TIMEOUT_S,
) -> bool:
    """Wait until the launched browser exposes the account's local CDP endpoint."""
    deadline = time.monotonic() + timeout_s
    url = f"http://127.0.0.1:{port}/json/version"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.75) as response:
                if response.status == 200:
                    return True
        except Exception:
            # Chrome can hand work to a child process while the original
            # launcher is exiting.  Check the endpoint once before treating
            # that hand-off as a startup failure.
            if process.poll() is not None:
                return False
            time.sleep(0.2)
    return False


def _browser_exit_code(process: subprocess.Popen) -> Optional[int]:
    """Return the browser exit code without allowing diagnostics to fail launch."""
    try:
        code = process.poll()
        return int(code) if code is not None else None
    except Exception:
        return None


def _is_breakpoint_exit(process: subprocess.Popen) -> bool:
    """Identify Windows STATUS_BREAKPOINT regardless of signed exit-code form."""
    code = _browser_exit_code(process)
    return code is not None and (code & 0xFFFFFFFF) == _STATUS_BREAKPOINT


def _browser_failure_message(process: subprocess.Popen, timeout_s: float) -> str:
    """Produce a safe, actionable browser-start diagnosis for the web UI."""
    code = _browser_exit_code(process)
    if code is None:
        return f"không mở được cổng điều khiển sau {int(timeout_s)} giây"
    code_hex = f"0x{code & 0xFFFFFFFF:08X}"
    if (code & 0xFFFFFFFF) == _STATUS_BREAKPOINT:
        return (
            "browser gặp lỗi Windows STATUS_BREAKPOINT (0x80000003); "
            "profile hoặc GPU cache có thể đang lỗi"
        )
    return f"browser thoát sớm với mã {code_hex}"


def _stop_failed_browser_process(process: subprocess.Popen) -> None:
    """Best-effort cleanup for a failed browser and all of its child processes."""
    try:
        if process.poll() is not None:
            return
        root = psutil.Process(process.pid)
        processes = root.children(recursive=True) + [root]
        for child in reversed(processes):
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(processes, timeout=2)
        for child in alive:
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:
        # Fall back to the process handle when the OS no longer exposes a
        # process tree (for example, during a very early browser crash).
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        except Exception:
            pass

class AccountSaveRequest(ApiRequest):
    id: Optional[int] = Field(default=None, gt=0)
    label: Optional[str] = Field(default=None, max_length=200)
    username: Optional[str] = Field(default=None, max_length=500)
    password: Optional[str] = Field(default=None, max_length=2_000)
    secret_2fa: Optional[str] = Field(default=None, max_length=500)
    email: Optional[str] = Field(default=None, max_length=500)
    email_pass: Optional[str] = Field(default=None, max_length=2_000)
    recovery_email: Optional[str] = Field(default=None, max_length=500)
    recovery_codes: Optional[str] = Field(default=None, max_length=50_000)
    cookie: Optional[str] = Field(default=None, max_length=200_000)
    notes: Optional[str] = Field(default=None, max_length=10_000)
    is_active: Optional[bool] = None

class AccountDeleteRequest(ApiRequest):
    account_id: int = Field(gt=0)
    # Off by default: the Chrome profile holds login cookies, so removing it is an explicit choice.
    delete_profile: bool = False

class LaunchProfileRequest(ApiRequest):
    account_id: int = Field(gt=0)
    url: Optional[HttpUrl] = "https://www.facebook.com"


class CloseProfileRequest(ApiRequest):
    account_id: int = Field(gt=0)


class ProfileExportRequest(ApiRequest):
    account_id: int = Field(gt=0)
    # Credentials are left out of the bundle unless the user explicitly opts in.
    include_secrets: bool = False


def _bundle_secret_fields(account: dict, include_secrets: bool) -> dict:
    """Return credential fields for a bundle only when the user opted in; blank them otherwise."""
    keys = ("password", "secret_2fa", "email_pass", "cookie")
    if include_secrets:
        return {key: str(account.get(key) or "") for key in keys}
    return {key: "" for key in keys}


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
    with _CHROME_PROCESS_LOCK:
        lease = _MANAGED_PROFILE_LEASES.pop(account_id, None)
    if lease:
        release_profile_leases(*lease)
    return closed


def _release_stale_managed_profile_lease(account_id: int) -> None:
    """Free a manual-profile lease when its tracked browser has already exited."""
    account_id = int(account_id)
    with _CHROME_PROCESS_LOCK:
        process = _CHROME_PROCESSES.get(account_id)
        if process is not None and process.poll() is None:
            return
        _CHROME_PROCESSES.pop(account_id, None)
        lease = _MANAGED_PROFILE_LEASES.pop(account_id, None)
    if lease:
        release_profile_leases(*lease)

@router.get("/")
def list_accounts():
    """List all configured Facebook accounts."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    accounts = get_all_accounts(db_p)
    return {"status": "success", "data": [_public_account(account) for account in accounts]}

@router.get("/{account_id}/detail")
def get_account_detail(account_id: int):
    """Return account metadata for editing without exposing stored secrets."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    account = get_account(db_p, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")

    port = _chrome_debug_port(account_id)
    with _CHROME_PROCESS_LOCK:
        proc = _CHROME_PROCESSES.get(account_id)
        is_running = proc is not None and proc.poll() is None

    stored_profile = str(account.get("profile_dir") or "").strip()
    profile_dir = str(
        Path(stored_profile).expanduser().resolve()
        if stored_profile else scraper_profile_dir(account_id).resolve()
    )

    data = {
        **_public_account(account),
        "port": port,
        "is_chrome_running": is_running,
        "cdp_url": f"http://127.0.0.1:{port}",
        "profile_dir": profile_dir,
    }
    return {"status": "success", "data": data}


@router.post("/{account_id}/secret/{secret_name}")
def reveal_account_secret(
    account_id: int,
    secret_name: Literal["password", "secret_2fa", "cookie", "recovery_codes"],
):
    """Reveal one stored credential only after an explicit local UI action."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    account = get_account(db_p, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    return {"status": "success", "data": {"value": str(account.get(secret_name) or "")}}


@router.post("/{account_id}/preflight")
def preflight_account(account_id: int):
    """Manually verify that this profile can authenticate before a large download."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    account = get_account(db_p, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")

    _release_stale_managed_profile_lease(account_id)
    with _CHROME_PROCESS_LOCK:
        process = _CHROME_PROCESSES.get(account_id)
        chrome_open = process is not None and process.poll() is None
    if chrome_open:
        raise HTTPException(
            status_code=409,
            detail="Hãy đóng Chrome Profile của account này trước khi check preflight.",
        )
    lease_owner = f"manual-preflight-{account_id}"
    try:
        lease_keys = acquire_profile_leases(lease_owner, [account])
    except ProfileLeaseConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        result = check_facebook_account(account).to_dict()
    finally:
        release_profile_leases(lease_owner, lease_keys)
    result["checked_at"] = save_account_preflight_result(
        db_p,
        account_id,
        code=result["code"],
        message=result["message"],
    )
    level = "OK" if result["ready"] else "WARNING"
    log_to_web(
        f"[Account #{account_id} · {result['label']}] PREFLIGHT {result['code']}: {result['message']}",
        level,
    )
    return {"status": "success", "data": result}

@router.post("/save")
def save_account_endpoint(req: AccountSaveRequest):
    """Add or update an account."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if req.id:
        # Update
        fields = model_data(req, exclude_unset=True)
        acc_id = fields.pop("id")
        fields = {k: v for k, v in fields.items() if v is not None}
        if "is_active" in fields:
            fields["is_active"] = int(bool(fields["is_active"]))
        fields.update(
            preflight_status="",
            preflight_message="",
            preflight_checked_at="",
        )
        success = update_account(db_p, acc_id, **fields)
        if not success:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
        log_to_web(f"Đã cập nhật tài khoản ID #{acc_id}.", "OK")
        return {"status": "success", "id": acc_id}
    else:
        # Insert
        username = req.username or req.email or f"acc_{uuid.uuid4().hex[:6]}"
        new_id = add_account(
            db_p,
            username=username,
            password=req.password or "",
            label=req.label or req.username or req.email or "Account mới",
            secret_2fa=req.secret_2fa or "",
            email=req.email or "",
            email_pass=req.email_pass or "",
            recovery_email=req.recovery_email or "",
            recovery_codes=req.recovery_codes or "",
            cookie=req.cookie or "",
            notes=req.notes or "",
            is_active=int(bool(req.is_active if req.is_active is not None else True))
        )
        if new_id < 0:
            raise HTTPException(status_code=400, detail="Không thể tạo tài khoản mới (có thể username/UID đã tồn tại)")
        log_to_web(f"Đã thêm tài khoản mới ID #{new_id}.", "OK")
        return {"status": "success", "id": new_id}

@router.post("/clear-credentials")
def clear_account_credentials(req: AccountDeleteRequest):
    """Clear stored password, 2FA secret, cookie, and recovery codes for an account."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    account = get_account(db_p, req.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    update_account(
        db_p,
        req.account_id,
        password="",
        secret_2fa="",
        cookie="",
        recovery_codes="",
        preflight_status="",
        preflight_message="",
        preflight_checked_at="",
    )
    log_to_web(f"Đã xóa credentials cho tài khoản ID #{req.account_id}.", "WARNING")
    return {"status": "success", "message": "Đã xóa credentials"}

@router.post("/delete")
def delete_account_endpoint(req: AccountDeleteRequest):
    """Delete an account by ID."""
    from web.routes.downloader import download_has_active_or_pending_work
    from web.routes.scraper import scrape_is_running
    if scrape_is_running() or download_has_active_or_pending_work():
        raise HTTPException(status_code=409, detail="Hãy dừng tác vụ quét và tải trước khi xóa account")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if not req.delete_profile:
        if not delete_account(db_p, req.account_id):
            raise HTTPException(status_code=500, detail="Không xóa được tài khoản.")
        log_to_web(f"Đã xóa tài khoản ID #{req.account_id}.", "WARNING")
        return {"status": "success", "message": "Đã xóa tài khoản", "profile_deleted": False}

    account = get_account(db_p, req.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    profile_path = _owned_profile_dir(str(account.get("profile_dir") or ""), req.account_id)
    if _profile_shared_with_other_account(db_p, profile_path, req.account_id):
        raise HTTPException(status_code=409, detail="Profile này đang được tài khoản khác dùng chung; không xóa.")
    _release_stale_managed_profile_lease(req.account_id)
    owner = f"delete-account-{req.account_id}"
    try:
        lease_keys = acquire_profile_leases(owner, [account])
    except ProfileLeaseConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        # Delete the DB row first and touch the folder only after it succeeded.
        if not delete_account(db_p, req.account_id):
            raise HTTPException(status_code=500, detail="Không xóa được tài khoản; thư mục profile được giữ nguyên.")
        profile_error = ""
        if profile_path.is_dir():
            try:
                shutil.rmtree(profile_path)
            except OSError as exc:
                profile_error = str(exc)
    finally:
        release_profile_leases(owner, lease_keys)
    if profile_error:
        log_to_web(f"Đã xóa tài khoản ID #{req.account_id} nhưng không xóa được thư mục profile.", "ERROR")
        return {
            "status": "partial",
            "message": "Đã xóa tài khoản nhưng chưa xóa được thư mục profile. Đóng Chrome đang dùng profile rồi thử lại việc xóa thư mục.",
            "profile_deleted": False,
            "profile_error": profile_error,
        }
    log_to_web(f"Đã xóa tài khoản ID #{req.account_id} và Chrome profile.", "WARNING")
    return {"status": "success", "message": "Đã xóa tài khoản và Chrome profile", "profile_deleted": True}


def _profile_shared_with_other_account(db_p: str, profile_path: Path, account_id: int) -> bool:
    """True when another account resolves to the same profile folder."""
    root = chrome_profiles_root().resolve()
    for other in get_all_accounts(db_p):
        other_id = int(other["id"])
        if other_id == account_id:
            continue
        value = str(other.get("profile_dir") or "").strip()
        other_path = (Path(value).expanduser().resolve() if value else (root / f"scraper_{other_id}").resolve())
        if other_path == profile_path:
            return True
    return False


def _owned_profile_dir(profile_value: str, account_id: int) -> Path | None:
    """Return the profile folder only when it lies inside the app-managed profiles root."""
    root = chrome_profiles_root().resolve()
    candidate = (Path(profile_value).expanduser().resolve() if profile_value
                 else (root / f"scraper_{account_id}").resolve())
    if candidate == root or root not in candidate.parents:
        raise HTTPException(status_code=409, detail="Thư mục profile nằm ngoài vùng app quản lý; không xóa.")
    return candidate

@router.post("/launch")
def launch_chrome_profile(req: LaunchProfileRequest):
    """Launch a dedicated account profile in a verified Chromium browser."""
    browser_paths = _find_browser_paths()
    if not browser_paths:
        raise HTTPException(
            status_code=503,
            detail="Không tìm thấy Google Chrome hoặc Microsoft Edge. Hãy cài đặt một trong hai trình duyệt rồi thử lại.",
        )
    db_p = get_db_path(config.get("scraper_db_path", ""))
    account = get_account(db_p, req.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    _release_stale_managed_profile_lease(req.account_id)
    lease_owner = f"manual-profile-{req.account_id}"
    try:
        lease_keys = acquire_profile_leases(lease_owner, [account])
    except ProfileLeaseConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    stored_profile = str(account.get("profile_dir") or "").strip()
    profile_dir = str(
        Path(stored_profile).expanduser().resolve()
        if stored_profile else scraper_profile_dir(req.account_id).resolve()
    )
    port = _chrome_debug_port(req.account_id)
    target_url = str(req.url or "https://www.facebook.com")

    with _CHROME_PROCESS_LOCK:
        running_process = _CHROME_PROCESSES.get(req.account_id)
        if running_process is not None and running_process.poll() is None:
            _MANAGED_PROFILE_LEASES[req.account_id] = (lease_owner, lease_keys)
            return {
                "status": "success",
                "profile_dir": profile_dir,
                "port": port,
                "browser_label": "Chrome/Edge",
                "already_running": True,
            }

    failed_browsers: list[str] = []
    failure_reasons: list[str] = []
    for browser_bin in browser_paths:
        label = _browser_label(browser_bin)
        retry_with_gpu_disabled = False
        for recovery_mode, timeout_s in ((False, _CDP_START_TIMEOUT_S), (True, _CDP_RECOVERY_TIMEOUT_S)):
            if recovery_mode and not retry_with_gpu_disabled:
                break
            cmd = [
                browser_bin,
                f"--user-data-dir={profile_dir}",
                f"--remote-debugging-port={port}",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
                "--new-window",
            ]
            if recovery_mode:
                # Retry only after the exact Windows breakpoint crash shown to
                # the user.  This preserves extensions and normal GPU behavior
                # for every healthy profile.
                cmd.append("--disable-gpu")
            cmd.append(target_url)
            try:
                process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as exc:
                failure_reasons.append(f"{label}: không thể tạo tiến trình ({exc.__class__.__name__})")
                break

            if _wait_for_cdp_port(process, port, timeout_s=timeout_s):
                with _CHROME_PROCESS_LOCK:
                    _CHROME_PROCESSES[req.account_id] = process
                    _MANAGED_PROFILE_LEASES[req.account_id] = (lease_owner, lease_keys)
                mode_note = " (đã tắt GPU để phục hồi)" if recovery_mode else ""
                log_to_web(
                    f"Đã mở {label} Profile cho Account #{req.account_id} (Port {port}){mode_note}.",
                    "INFO",
                )
                return {
                    "status": "success",
                    "profile_dir": profile_dir,
                    "port": port,
                    "browser_label": label,
                    "recovery_mode": "gpu_disabled" if recovery_mode else None,
                }

            failure = _browser_failure_message(process, timeout_s)
            retry_with_gpu_disabled = not recovery_mode and _is_breakpoint_exit(process)
            _stop_failed_browser_process(process)
            failure_reasons.append(f"{label}: {failure}")
            if retry_with_gpu_disabled:
                log_to_web(
                    f"{label} không khởi động được profile ({failure}); đang thử lại với GPU tắt.",
                    "WARNING",
                )
                continue
            break

        failed_browsers.append(label)
        reason = failure_reasons[-1] if failure_reasons else f"{label}: không rõ nguyên nhân"
        log_to_web(f"{reason}; đang thử trình duyệt thay thế.", "WARNING")

    tried = " và ".join(dict.fromkeys(failed_browsers)) or "trình duyệt Chromium"
    diagnostic = "; ".join(failure_reasons)
    suffix = f" Chi tiết: {diagnostic}." if diagnostic else ""
    release_profile_leases(lease_owner, lease_keys)
    raise HTTPException(
        status_code=500,
        detail=(
            f"Không thể khởi động profile bằng {tried}. "
            f"Hãy đóng các cửa sổ profile còn sót rồi thử lại.{suffix}"
        ),
    )


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
    try:
        account_ids = {int(account["id"]) for account in get_all_accounts(db_p)}
    except AccountStoreError:
        # Still close the Chrome windows this process launched, even if the account table is unreadable.
        account_ids = set()
    with _CHROME_PROCESS_LOCK:
        account_ids.update(_CHROME_PROCESSES)
    closed_count = sum(1 for account_id in sorted(account_ids) if _close_managed_chrome(account_id))
    log_to_web(f"Đã đóng {closed_count} cửa sổ Chrome do Tinix quản lý.", "INFO")
    return {"status": "success", "closed_count": closed_count}


def shutdown_managed_chrome_profiles() -> None:
    """Close only browser instances launched from the Accounts workspace."""
    with _CHROME_PROCESS_LOCK:
        account_ids = list(_CHROME_PROCESSES)
    for account_id in account_ids:
        _close_managed_chrome(account_id)


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
                **_bundle_secret_fields(account, req.include_secrets),
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
def export_all_account_profiles(include_secrets: bool = Query(default=False)):
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
            **_bundle_secret_fields(account, include_secrets),
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
    # Only remove a folder that this import created; never delete a pre-existing profile.
    destination_preexisted = destination.exists()
    try:
        result = import_profile_from_directory(source_profile, destination)
        if not update_social_account(db_p, social_id, profile_dir=str(destination)):
            raise ProfileBundleError("Không thể lưu đường dẫn profile đã Import.")
    except Exception:
        delete_social_account(db_p, social_id)
        delete_account(db_p, legacy_id)
        if destination.exists() and not destination_preexisted:
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
    # Only remove a folder that this import created; never delete a pre-existing profile.
    destination_preexisted = destination.exists()
    try:
        imported_manifest, result = import_bundle_profile(req.bundle_path, destination)
        if not update_social_account(db_p, social_id, profile_dir=str(destination)):
            raise ProfileBundleError("Không thể lưu đường dẫn profile đã Import.")
    except Exception as exc:
        delete_social_account(db_p, social_id)
        delete_account(db_p, legacy_id)
        if destination.exists() and not destination_preexisted:
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
