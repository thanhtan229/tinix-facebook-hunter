"""
Tinix-Facebook-Hunter — Main Entry Point
Launches the WebUI Studio server and opens the browser.
"""

import sys
import os

# Ensure the project root is in the Python path
if getattr(sys, 'frozen', False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))

if _base_dir not in sys.path:
    sys.path.insert(0, _base_dir)

# Under pythonw.exe on Windows, sys.stdout and sys.stderr are None.
log_dir = os.path.join(_base_dir, "logs")
os.makedirs(log_dir, exist_ok=True)
startup_log = os.path.join(log_dir, "server_startup.log")

if sys.stdout is None:
    try:
        sys.stdout = open(startup_log, "a", encoding="utf-8", buffering=1)
    except Exception:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")

if sys.stderr is None:
    try:
        sys.stderr = open(startup_log, "a", encoding="utf-8", buffering=1)
    except Exception:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

from start_webui import main  # noqa: E402 - pythonw streams must be configured before importing the launcher.

if __name__ == "__main__":
    raise SystemExit(main())
