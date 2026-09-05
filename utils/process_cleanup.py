"""
Tinix FB Studio — Process Cleanup Utility
Safely closes old backend and frontend sessions before launching a new session.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import List, Optional, Set

# Reconfigure stdout/stderr for proper UTF-8 console output on Windows
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import psutil
except ImportError:
    psutil = None

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger("tinix.cleanup")

DEFAULT_PORT = 7866
WINDOW_TITLE_KEYWORDS = ["Tinix FB Studio", "All-in-One Facebook Hub"]
CHROME_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")


def get_workspace_root() -> Path:
    """Return the resolved root directory of the Tinix FB Down workspace."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).resolve().parent.parent


def get_current_and_ancestor_pids() -> Set[int]:
    """Return the set of PIDs including the current process and all its ancestors."""
    pids = {os.getpid()}
    try:
        if psutil is not None:
            cur = psutil.Process()
            for parent in cur.parents():
                pids.add(parent.pid)
        else:
            pids.add(os.getppid())
    except Exception:
        pass
    return pids


def is_path_relative_to(path: Path, base: Path) -> bool:
    """Check if path is inside base directory (case-insensitive for Windows)."""
    try:
        norm_path = os.path.normcase(str(path.resolve()))
        norm_base = os.path.normcase(str(base.resolve()))
        return norm_path == norm_base or norm_path.startswith(norm_base + os.sep)
    except Exception:
        return False


def is_port_in_use(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> bool:
    """Check if a TCP port is currently listening."""
    bind_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.4)
            return sock.connect_ex((bind_host, port)) == 0
    except Exception:
        return False


def wait_for_port_free(host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 3.0) -> bool:
    """Wait until the specified port is no longer bound."""
    start = time.time()
    while time.time() - start < timeout:
        if not is_port_in_use(host, port):
            return True
        time.sleep(0.15)
    return not is_port_in_use(host, port)


def is_workspace_python_process(proc, workspace_root: Path, exclude_pids: Set[int]) -> bool:
    """Check if a psutil.Process is a Python process belonging to this workspace."""
    if proc.pid in exclude_pids:
        return False

    try:
        name = (proc.name() or "").lower()
        if not ("python" in name or name == "py.exe"):
            return False

        norm_ws = os.path.normcase(str(workspace_root.resolve()))

        # 1. Check executable location (e.g. .venv)
        try:
            exe_path = proc.exe()
            if exe_path and is_path_relative_to(Path(exe_path), workspace_root):
                return True
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        # 2. Check current working directory
        try:
            cwd_path = proc.cwd()
            if cwd_path and is_path_relative_to(Path(cwd_path), workspace_root):
                return True
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        # 3. Check command line arguments referencing this workspace path or files
        try:
            cmdline = proc.cmdline() or []
            cmd_str = " ".join(cmdline).lower()
            if norm_ws in os.path.normcase(cmd_str):
                return True
            for marker in ("main.py", "start_webui.py", "web.app:app"):
                if marker in cmd_str:
                    # Also check if it references workspace or was run here
                    for arg in cmdline:
                        if norm_ws in os.path.normcase(arg):
                            return True
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

    return False


def is_project_chrome_process(proc, chrome_profiles_dir: Path, exclude_pids: Set[int]) -> bool:
    """
    Check if a process is a Chrome/Edge automation process launched with the project's Chrome Profiles.
    Crucial: NEVER matches the user's regular personal browser processes.
    """
    if proc.pid in exclude_pids:
        return False

    try:
        name = (proc.name() or "").lower()
        if not any(browser in name for browser in ("chrome", "msedge", "chromium")):
            return False

        cmdline = proc.cmdline() or []
        norm_profile_dir = os.path.normcase(str(chrome_profiles_dir.resolve()))

        for arg in cmdline:
            norm_arg = os.path.normcase(str(arg))
            if norm_profile_dir in norm_arg:
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

    return False


def terminate_processes(processes: List, timeout: float = 2.5) -> int:
    """Gracefully terminate a list of psutil processes and kill if still alive after timeout."""
    if not processes or psutil is None:
        return 0

    unique_procs = {}
    for p in processes:
        try:
            if p.is_running() and p.pid != os.getpid():
                unique_procs[p.pid] = p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if not unique_procs:
        return 0

    # Step 1: Send graceful termination
    for proc in unique_procs.values():
        try:
            for child in proc.children(recursive=True):
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Wait for processes to exit
    all_targets = list(unique_procs.values())
    _, alive = psutil.wait_procs(all_targets, timeout=timeout)

    # Step 2: Force kill remaining
    for proc in alive:
        try:
            for child in proc.children(recursive=True):
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return len(unique_procs)


CONSOLE_WINDOW_CLASSES = {
    "ConsoleWindowClass",
    "CASCADIA_HOSTING_WINDOW_CLASS",  # Windows Terminal
    "PseudoConsoleWindow",
    "mintty",
    "VirtualConsoleClass",
}
TERMINAL_PROCESS_NAMES = {
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "conhost.exe",
    "windowsterminal.exe",
    "openconsole.exe",
    "code.exe",
    "devenv.exe",
}


def close_frontend_windows(
    title_keywords: Optional[List[str]] = None,
    exclude_pids: Optional[Set[int]] = None,
) -> int:
    """
    Finds and closes top-level frontend windows matching Tinix FB Studio titles.
    Uses Win32 WM_CLOSE so the browser window or tab closes gracefully.
    Excludes windows owned by the current process, ancestors, or terminal/console hosts.
    """
    if sys.platform != "win32":
        return 0

    keywords = [k.lower() for k in (title_keywords or WINDOW_TITLE_KEYWORDS)]
    if exclude_pids is None:
        exclude_pids = get_current_and_ancestor_pids()

    closed_windows = 0
    WM_CLOSE = 0x0010

    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        console_hwnd = kernel32.GetConsoleWindow() if hasattr(kernel32, "GetConsoleWindow") else None

        def enum_window_callback(hwnd, extra):
            nonlocal closed_windows
            if not user32.IsWindowVisible(hwnd):
                return True

            # Never close our own console window
            if console_hwnd and hwnd == console_hwnd:
                return True

            # Never close terminal/console windows
            class_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buff, 256)
            if class_buff.value in CONSOLE_WINDOW_CLASSES:
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True

            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value.strip()

            if any(k in title.lower() for k in keywords):
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value and pid.value not in exclude_pids:
                    # Never close developer IDEs or terminal shells
                    if psutil is not None:
                        try:
                            proc_name = (psutil.Process(pid.value).name() or "").lower()
                            if proc_name in TERMINAL_PROCESS_NAMES or any(
                                t in proc_name for t in ("terminal", "conhost")
                            ):
                                return True
                        except Exception:
                            pass
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                    closed_windows += 1

            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_window_callback), 0)
    except Exception as e:
        logger.debug("Loi khi quet cua so Windows: %s", e)

    return closed_windows


def cleanup_chrome_profile_locks(chrome_profiles_dir: Path) -> int:
    """Removes stale Chrome profile lockfiles (SingletonLock, lockfile, etc.)."""
    removed_count = 0
    if not chrome_profiles_dir.exists():
        return 0

    try:
        for profile_folder in chrome_profiles_dir.iterdir():
            if profile_folder.is_dir():
                for lock_name in CHROME_LOCK_FILES:
                    lock_path = profile_folder / lock_name
                    if lock_path.exists():
                        try:
                            if lock_path.is_file() or lock_path.is_symlink():
                                lock_path.unlink(missing_ok=True)
                                removed_count += 1
                        except Exception:
                            pass
    except Exception:
        pass

    return removed_count


def cleanup_previous_sessions(
    port: int = DEFAULT_PORT,
    workspace_root: Optional[Path] = None,
    timeout: float = 2.5,
    close_windows: bool = False,
    verbose: bool = True,
) -> dict:
    """
    Main cleanup coordinator:
    1. Closes old backend processes (listening on port or running in workspace).
    2. Closes old frontend sessions (Chrome automation profiles and WebUI windows).
    3. Cleans stale Chrome locks and verifies port availability.
    """
    ws = (workspace_root or get_workspace_root()).resolve()
    chrome_profiles_dir = ws / "Chrome Profiles"
    exclude_pids = get_current_and_ancestor_pids()

    backend_procs: list = []
    chrome_procs: list = []

    if psutil is not None:
        # 1. Collect processes bound to target port
        try:
            for conn in psutil.net_connections(kind="inet"):
                if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                    if conn.pid and conn.pid not in exclude_pids:
                        try:
                            backend_procs.append(psutil.Process(conn.pid))
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
        except Exception:
            pass

        # 2. Iterate system processes to find workspace backend & project Chrome
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.pid in exclude_pids:
                    continue

                if is_workspace_python_process(proc, ws, exclude_pids):
                    backend_procs.append(proc)
                elif is_project_chrome_process(proc, chrome_profiles_dir, exclude_pids):
                    chrome_procs.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    # Terminate identified processes
    num_backend = terminate_processes(backend_procs, timeout=timeout)
    num_chrome = terminate_processes(chrome_procs, timeout=timeout)

    # 3. Close frontend WebUI browser windows if requested
    num_windows = close_frontend_windows(exclude_pids=exclude_pids) if close_windows else 0

    # 4. Remove stale lockfiles from Chrome Profiles
    num_locks = cleanup_chrome_profile_locks(chrome_profiles_dir)

    # 5. Verify and wait for port to be free
    port_freed = True
    if is_port_in_use("127.0.0.1", port):
        port_freed = wait_for_port_free("127.0.0.1", port, timeout=timeout)

    results = {
        "backend_closed": num_backend,
        "chrome_closed": num_chrome,
        "windows_closed": num_windows,
        "locks_removed": num_locks,
        "port_freed": port_freed,
    }

    if verbose:
        details = []
        if num_backend > 0:
            details.append(f"{num_backend} tiến trình backend cũ")
        if num_chrome > 0:
            details.append(f"{num_chrome} tiến trình Chrome cào dữ liệu")
        if num_windows > 0:
            details.append(f"{num_windows} cửa sổ giao diện cũ")
        if num_locks > 0:
            details.append(f"đã mở khóa {num_locks} file lock profile")

        if details:
            logger.info("  ✓ Đã đóng: %s.", ", ".join(details))
        else:
            logger.info("  ✓ Không có phiên làm việc cũ nào tồn đọng.")

        if not port_freed:
            logger.warning("  ⚠ Cảnh báo: Cổng %d vẫn đang bị chiếm dụng.", port)

    return results


def main():
    parser = argparse.ArgumentParser(description="Tinix FB Studio — Process Cleanup Utility")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to verify and free (default: 7866)")
    parser.add_argument("--workspace", type=str, default="", help="Workspace root directory")
    parser.add_argument("--timeout", type=float, default=2.5, help="Termination timeout in seconds")
    parser.add_argument("--close-windows", action="store_true", help="Close existing frontend/browser windows")
    parser.add_argument("--skip-windows", action="store_true", help="Skip closing browser/frontend windows (default)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")
    args = parser.parse_args()

    ws_path = Path(args.workspace) if args.workspace else get_workspace_root()
    should_close_windows = args.close_windows and not args.skip_windows
    cleanup_previous_sessions(
        port=args.port,
        workspace_root=ws_path,
        timeout=args.timeout,
        close_windows=should_close_windows,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
