"""
Tinix Facebook Down — Configuration Manager
Handles loading/saving application settings from/to JSON file.
"""

import json
import os
from pathlib import Path
from typing import Any

# Default configuration values
DEFAULTS = {
    "max_threads": 1,
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

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config.update(saved)
        except (json.JSONDecodeError, IOError) as e:
            # If config is corrupted, use defaults
            print(f"[WARN] Could not load config: {e}. Using defaults.")

    _config_cache = config
    return config


def save_config(config: dict) -> None:
    """Save configuration to config.json."""
    global _config_cache
    config_path = _get_config_path()

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
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
