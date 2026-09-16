"""
Tinix Facebook Down — Configuration Manager
Handles loading/saving application settings from/to JSON file.
"""

import json
import os
from pathlib import Path
from typing import Any

from utils.secure_store import protect_secret, reveal_secret

# ─── .env file loader (no external dependency) ──────────────────────────────
_env_cache: dict = None
_SECRET_CONFIG_KEYS = {"saved_cookies", "cookies"}


def _load_env_file() -> dict:
    """Parse .env file from app root directory. Supports KEY=VALUE lines."""
    global _env_cache
    if _env_cache is not None:
        return _env_cache

    _env_cache = {}
    env_path = _get_config_dir() / ".env"
    if not env_path.exists():
        return _env_cache

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")  # remove surrounding quotes
                if key:
                    _env_cache[key] = value
    except Exception:
        pass
    return _env_cache


def get_env(key: str, default: str = "") -> str:
    """Get an environment variable: .env file first, then os.environ fallback."""
    env = _load_env_file()
    val = env.get(key, "")
    if val:
        return val
    return os.environ.get(key, default)

# Default configuration values
DEFAULTS = {
    # Download defaults deliberately favour account safety over raw throughput.
    "max_threads": 3,
    "download_use_accounts": True,
    "download_delay_min": 2.0,
    "download_delay_max": 5.0,
    "download_batch_size": 25,
    "download_batch_rest_min": 30.0,
    "download_batch_rest_max": 90.0,
    "output_dir": str(Path.home() / "Downloads" / "Tinix FB Down"),
    "auto_open_folder": False,
    "save_cookies": False,
    "saved_cookies": "",
    "scraper_db_path": "",  # Empty = use default (app_dir/tinix_scraper.db)
    "window_width": 950,
    "window_height": 750,
}

# Config file location (next to exe or script)
_config_dir: Path = None
_config_path: Path = None
_config_cache: dict = None


def _get_config_dir() -> Path:
    """Get the config directory (same as the executable/script location)."""
    global _config_dir
    if _config_dir is None:
        # Use the app's own directory for portable config
        if getattr(os.sys, 'frozen', False):
            # Running as compiled .exe
            _config_dir = Path(os.sys.executable).parent
        else:
            # Running as script
            _config_dir = Path(__file__).parent.parent
    return _config_dir


def _get_config_path() -> Path:
    """Get full path to config.json."""
    global _config_path
    if _config_path is None:
        _config_path = _get_config_dir() / "config.json"
    return _config_path


def load_config() -> dict:
    """
    Load configuration from config.json.
    Returns merged config (defaults + saved values).
    """
    global _config_cache
    config = DEFAULTS.copy()
    config_path = _get_config_path()

    migrated_download_safety = False
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for key in _SECRET_CONFIG_KEYS:
                if key in saved:
                    saved[key] = reveal_secret(saved[key])
            # Apply the safer download defaults exactly once to older installs.
            # Subsequent user-selected values are preserved by the marker.
            if not saved.get("_download_safety_defaults_v1"):
                try:
                    saved["max_threads"] = min(max(1, int(saved.get("max_threads", 3))), 3)
                except (TypeError, ValueError):
                    saved["max_threads"] = 3
                for key in (
                    "download_use_accounts", "download_delay_min", "download_delay_max",
                    "download_batch_size", "download_batch_rest_min", "download_batch_rest_max",
                ):
                    saved[key] = DEFAULTS[key]
                saved["_download_safety_defaults_v1"] = True
                migrated_download_safety = True
            config.update(saved)
        except (json.JSONDecodeError, IOError) as e:
            # If config is corrupted, use defaults
            print(f"[WARN] Could not load config: {e}. Using defaults.")

    _config_cache = config
    if migrated_download_safety:
        save_config(config)
    return config


def save_config(config: dict) -> None:
    """Save configuration to config.json."""
    global _config_cache
    config_path = _get_config_path()

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        disk_config = config.copy()
        for key in _SECRET_CONFIG_KEYS:
            if key in disk_config:
                disk_config[key] = protect_secret(disk_config[key])
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(disk_config, f, indent=2, ensure_ascii=False)
        _config_cache = config.copy()
    except IOError as e:
        print(f"[ERROR] Could not save config: {e}")


def get(key: str, default: Any = None) -> Any:
    """Get a single config value."""
    global _config_cache
    if _config_cache is None:
        load_config()
    return _config_cache.get(key, default)


def set_value(key: str, value: Any) -> None:
    """Set a single config value and save."""
    global _config_cache
    if _config_cache is None:
        load_config()
    _config_cache[key] = value
    save_config(_config_cache)


def get_output_dir() -> Path:
    """Get the output directory, creating it if needed."""
    output_dir = Path(get("output_dir", DEFAULTS["output_dir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir
