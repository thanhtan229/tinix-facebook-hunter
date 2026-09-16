"""Tinix-Facebook-Hunter WebUI launcher bound to its desktop App Mode port."""

import os
import sys
import time
import socket
import webbrowser
import threading
import uvicorn

# Under pythonw.exe on Windows, sys.stdout and sys.stderr are None.
# Uvicorn and standard logging require stream objects with isatty() and write().
if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        import io
        sys.stdout = io.StringIO()

if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        import io
        sys.stderr = io.StringIO()

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_PORT = 7866
HOST = "127.0.0.1"


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, port)) == 0


def get_listen_port() -> int:
    """Return the only port understood by the desktop launcher.

    ``START.bat`` opens Chrome App Mode at ``DEFAULT_PORT``.  Falling back to a
    different port would start a hidden backend while the visible application
    still points at the unavailable default URL.
    """
    if is_port_in_use(DEFAULT_PORT):
        raise RuntimeError(
            f"Cổng {DEFAULT_PORT} đang được sử dụng. Dừng ứng dụng đang chiếm cổng rồi chạy lại Tinix."
        )
    return DEFAULT_PORT


def open_browser(url: str):
    time.sleep(1.2)
    print(f"🚀 Opening Tinix-Facebook-Hunter in your browser: {url}")
    webbrowser.open(url)


def main() -> int:
    try:
        port = get_listen_port()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", flush=True)
        return 1
    url = f"http://{HOST}:{port}"

    print("=" * 60)
    print("  ⚡ Tinix-Facebook-Hunter (Modern WebUI Hub) is starting...")
    print(f"  🌐 URL: {url}")
    print("=" * 60)

    # Launch browser in a background thread unless disabled
    no_browser = bool(os.environ.get("TINIX_NO_BROWSER")) or ("--no-browser" in sys.argv)
    if not no_browser:
        threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    # Start Uvicorn ASGI Server
    import traceback
    try:
        uvicorn.run(
            "web.app:app",
            host=HOST,
            port=port,
            ws="wsproto",
            log_level="warning",
            access_log=False
        )
        print(f"[INFO] WebUI server đã dừng: {url}", flush=True)
        return 0
    except BaseException as exc:
        print(f"UVICORN RUN CRASHED: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        if hasattr(sys.stdout, "flush"):
            sys.stdout.flush()
        if hasattr(sys.stderr, "flush"):
            sys.stderr.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
