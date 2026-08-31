import os
import subprocess
import shutil
import importlib.util
from fastapi import APIRouter, HTTPException
from pydantic import Field
from typing import Dict, Any, Optional
from utils import config
from core.db_storage import (
    get_db_path,
    get_db_stats,
    get_all_accounts,
    migrate_secrets_at_rest,
    SCHEMA_VERSION,
)
from core.database_maintenance import inspect_database
from core.version import APP_VERSION
from web.ws_manager import log_to_web
from web.models import ApiRequest, model_data

router = APIRouter(prefix="/api/system", tags=["System"])

CONFIG_SECRET_FIELDS = {"saved_cookies", "cookies", "fb_app_secret", "access_token"}


def _public_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return UI settings without persisted cookies or credentials."""
    public = {k: v for k, v in cfg.items() if k.lower() not in CONFIG_SECRET_FIELDS}
    public["has_saved_cookies"] = bool(cfg.get("saved_cookies") or cfg.get("cookies"))
    return public

class ConfigUpdateRequest(ApiRequest):
    output_dir: Optional[str] = Field(default=None, max_length=4_096)
    max_threads: Optional[int] = Field(default=None, ge=1, le=20)
    auto_open_folder: Optional[bool] = None
    scraper_db_path: Optional[str] = Field(default=None, max_length=4_096)
    theme: Optional[str] = Field(default=None, pattern="^(light|dark|system)$")

class OpenFolderRequest(ApiRequest):
    path: Optional[str] = Field(default=None, max_length=4_096)


class SecretMigrationRequest(ApiRequest):
    confirm: bool = False

@router.get("/config")
def get_config():
    """Get active configuration."""
    cfg = config.load_config()
    return {"status": "success", "data": _public_config(cfg)}

@router.post("/config")
def update_config(req: ConfigUpdateRequest):
    """Update active configuration."""
    cfg = config.load_config()
    data = model_data(req, exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            cfg[k] = v
    config.save_config(cfg)
    log_to_web("Đã lưu cấu hình cài đặt hệ thống.", "OK")
    return {"status": "success", "data": _public_config(cfg)}

@router.post("/open-folder")
def open_folder(req: OpenFolderRequest):
    """Open specified folder (or output_dir) in Windows Explorer."""
    target_path = req.path or config.get("output_dir", ".")
    if not os.path.exists(target_path):
        os.makedirs(target_path, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(os.path.abspath(target_path))
        else:
            subprocess.Popen(["xdg-open", os.path.abspath(target_path)])
        return {"status": "success", "path": os.path.abspath(target_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@router.get("/stats")
def get_stats():
    """Get overall database metrics for the dashboard banner."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    stats = get_db_stats(db_p)
    accounts = get_all_accounts(db_p)
    return {
        "status": "success",
        "data": {
            "total_posts": stats.get("total_posts", 0),
            "downloaded_posts": stats.get("downloaded_posts", 0),
            "total_pages": stats.get("total_pages", 0),
            "total_accounts": len(accounts),
            "active_accounts": sum(1 for a in accounts if a.get("is_active")),
        }
    }


@router.get("/health")
def get_health():
    """Report release-readiness prerequisites without returning private paths."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    details = inspect_database(db_p)
    checks = {
        "database": details["integrity"] == "ok",
        "schema": details["schema_version"] == SCHEMA_VERSION,
        "windows": os.name == "nt",
        "chrome": bool(shutil.which("chrome") or os.path.exists(r"C:\Program Files\Google\Chrome\Application\chrome.exe")),
        "playwright": importlib.util.find_spec("playwright") is not None,
        "yt_dlp": importlib.util.find_spec("yt_dlp") is not None,
    }
    return {
        "status": "success",
        "data": {
            "ready": all(checks.values()),
            "version": APP_VERSION,
            "schema_version": details["schema_version"],
            "checks": checks,
        },
    }


@router.post("/secure-storage/migrate")
def migrate_secure_storage(req: SecretMigrationRequest):
    """Back up the database and encrypt legacy secrets with Windows DPAPI."""
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Cần xác nhận migration secrets")
    db_p = get_db_path(config.get("scraper_db_path", ""))
    try:
        result = migrate_secrets_at_rest(db_p)
        config.save_config(config.load_config())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Mã hóa secrets thất bại: {str(exc)[:160]}") from exc
    log_to_web(f"Đã mã hóa {result['changed']} secrets. Backup: {result['backup_path']}", "OK")
    return {"status": "success", **result}
