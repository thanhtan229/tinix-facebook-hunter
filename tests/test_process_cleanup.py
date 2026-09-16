"""
Tests for utils.process_cleanup module.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch


from utils.process_cleanup import (
    CHROME_LOCK_FILES,
    CONSOLE_WINDOW_CLASSES,
    DEFAULT_PORT,
    TERMINAL_PROCESS_NAMES,
    cleanup_chrome_profile_locks,
    cleanup_previous_sessions,
    get_current_and_ancestor_pids,
    get_workspace_root,
    is_path_relative_to,
    is_port_in_use,
    is_project_chrome_process,
    is_workspace_python_process,
    wait_for_port_free,
)
from utils import logger as app_logger


def test_get_workspace_root():
    ws = get_workspace_root()
    assert ws.exists()
    assert (ws / "main.py").exists()
    assert (ws / "Run.bat").exists()


def test_get_current_and_ancestor_pids():
    pids = get_current_and_ancestor_pids()
    assert isinstance(pids, set)
    assert os.getpid() in pids


def test_is_path_relative_to(tmp_path):
    sub_dir = tmp_path / "subdir" / "nested"
    sub_dir.mkdir(parents=True)
    other_dir = tmp_path / "other"
    other_dir.mkdir()

    assert is_path_relative_to(sub_dir, tmp_path) is True
    assert is_path_relative_to(tmp_path, sub_dir) is False
    assert is_path_relative_to(other_dir, sub_dir) is False


def test_is_port_in_use_unused_port():
    # Use a high unassigned port
    assert is_port_in_use("127.0.0.1", 59182) is False


def test_wait_for_port_free_unused_port():
    assert wait_for_port_free("127.0.0.1", 59183, timeout=0.5) is True


def test_cleanup_chrome_profile_locks(tmp_path):
    profiles_dir = tmp_path / "Chrome Profiles"
    profile1 = profiles_dir / "browser"
    profile2 = profiles_dir / "scraper_1"
    profile1.mkdir(parents=True)
    profile2.mkdir(parents=True)

    # Create dummy locks
    for lock_name in CHROME_LOCK_FILES:
        (profile1 / lock_name).write_text("lock")
        (profile2 / lock_name).write_text("lock")

    # Also create a legitimate user file that shouldn't be touched
    (profile1 / "Preferences").write_text("{}")

    removed = cleanup_chrome_profile_locks(profiles_dir)
    assert removed == len(CHROME_LOCK_FILES) * 2

    # Check lock files are gone
    for lock_name in CHROME_LOCK_FILES:
        assert not (profile1 / lock_name).exists()
        assert not (profile2 / lock_name).exists()

    # Preferences file should still exist
    assert (profile1 / "Preferences").exists()


def test_is_workspace_python_process():
    ws = get_workspace_root()
    exclude_pids = {1000}

    # Process in exclude_pids
    p_excluded = MagicMock()
    p_excluded.pid = 1000
    assert is_workspace_python_process(p_excluded, ws, exclude_pids) is False

    # Non-python process
    p_not_py = MagicMock()
    p_not_py.pid = 2000
    p_not_py.name.return_value = "notepad.exe"
    assert is_workspace_python_process(p_not_py, ws, exclude_pids) is False

    # Python process running in workspace cwd
    p_py_cwd = MagicMock()
    p_py_cwd.pid = 2001
    p_py_cwd.name.return_value = "python.exe"
    p_py_cwd.cwd.return_value = str(ws)
    p_py_cwd.cmdline.return_value = ["python", "main.py"]
    assert is_workspace_python_process(p_py_cwd, ws, exclude_pids) is True

    # Python process from completely different folder
    p_py_other = MagicMock()
    p_py_other.pid = 2002
    p_py_other.name.return_value = "python.exe"
    p_py_other.cwd.return_value = "C:\\OtherTools\\App"
    p_py_other.cmdline.return_value = ["python", "C:\\OtherTools\\App\\script.py"]
    p_py_other.exe.return_value = "C:\\Python311\\python.exe"
    assert is_workspace_python_process(p_py_other, ws, exclude_pids) is False


def test_is_project_chrome_process(tmp_path):
    chrome_profiles = tmp_path / "Chrome Profiles"
    chrome_profiles.mkdir()
    exclude_pids = {1000}

    # Regular Chrome process (user's personal browser)
    p_personal_chrome = MagicMock()
    p_personal_chrome.pid = 3001
    p_personal_chrome.name.return_value = "chrome.exe"
    p_personal_chrome.cmdline.return_value = [
        "chrome.exe",
        "--user-data-dir=C:\\Users\\Admin\\AppData\\Local\\Google\\Chrome\\User Data",
    ]
    assert is_project_chrome_process(p_personal_chrome, chrome_profiles, exclude_pids) is False

    # Tinix FB Down Chrome process
    p_project_chrome = MagicMock()
    p_project_chrome.pid = 3002
    p_project_chrome.name.return_value = "chrome.exe"
    p_project_chrome.cmdline.return_value = [
        "chrome.exe",
        f"--user-data-dir={chrome_profiles}\\browser",
    ]
    assert is_project_chrome_process(p_project_chrome, chrome_profiles, exclude_pids) is True


def test_cleanup_previous_sessions_dry_run(tmp_path):
    """The cleanup coordinator can be inspected without scanning live processes."""
    with patch("utils.process_cleanup.psutil", None), patch(
        "utils.process_cleanup.is_port_in_use", return_value=False
    ):
        result = cleanup_previous_sessions(
            port=DEFAULT_PORT, workspace_root=tmp_path, close_windows=False, verbose=False
        )
    assert isinstance(result, dict)
    assert "backend_closed" in result
    assert "chrome_closed" in result
    assert "windows_closed" in result
    assert "locks_removed" in result
    assert "port_freed" in result


def test_console_and_terminal_definitions():
    assert "ConsoleWindowClass" in CONSOLE_WINDOW_CLASSES
    assert "CASCADIA_HOSTING_WINDOW_CLASS" in CONSOLE_WINDOW_CLASSES
    assert "cmd.exe" in TERMINAL_PROCESS_NAMES
    assert "conhost.exe" in TERMINAL_PROCESS_NAMES
    assert "windowsterminal.exe" in TERMINAL_PROCESS_NAMES


def test_logger_uses_configured_test_log_directory(tmp_path):
    log_dir = tmp_path / "isolated-logs"
    previous_logger = app_logger._logger
    previous_gui_handler = app_logger._gui_handler
    test_logger = None
    try:
        with patch.dict(os.environ, {"TINIX_LOG_DIR": str(log_dir)}):
            app_logger._logger = None
            app_logger._gui_handler = None
            test_logger = app_logger.setup_logger("TinixLoggerIsolationTest")
            test_logger.error("isolated test log")
        log_files = list(log_dir.glob("app_*.log"))
        assert len(log_files) == 1
        assert "isolated test log" in log_files[0].read_text(encoding="utf-8")
    finally:
        if test_logger:
            for handler in list(test_logger.handlers):
                test_logger.removeHandler(handler)
                handler.close()
        app_logger._logger = previous_logger
        app_logger._gui_handler = previous_gui_handler


def test_pytest_session_uses_an_isolated_log_directory():
    log_dir = Path(os.environ["TINIX_LOG_DIR"])
    assert log_dir.name.startswith("tinix-facebook-hunter-pytest-")
    assert log_dir.is_dir()
    assert log_dir.resolve() != (get_workspace_root() / "logs").resolve()


def test_pytest_session_logger_writes_only_to_the_isolated_directory():
    marker = "pytest-session-log-isolation"
    app_logger.error(marker)
    log_files = list(Path(os.environ["TINIX_LOG_DIR"]).glob("app_*.log"))
    assert log_files
    assert any(marker in log_file.read_text(encoding="utf-8") for log_file in log_files)
