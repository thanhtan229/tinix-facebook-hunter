"""
Tinix-Facebook-Hunter — WebUI Launcher
Starts FastAPI on an available localhost port beginning at 7866 and opens the browser.
"""

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


def find_available_port(start_port: int = DEFAULT_PORT) -> int:
    port = start_port
    while is_port_in_use(port):
        port += 1
    return port


def open_browser(url: str):
    time.sleep(1.2)
    print(f"🚀 Opening Tinix-Facebook-Hunter in your browser: {url}")
    webbrowser.open(url)


def main():
    port = find_available_port(DEFAULT_PORT)
    url = f"http://{HOST}:{port}"

    print("=" * 60)
    print(f"  ⚡ Tinix-Facebook-Hunter (Modern WebUI Hub) is starting...")
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
    except BaseException as exc:
        print(f"UVICORN RUN CRASHED: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        if hasattr(sys.stdout, "flush"):
            sys.stdout.flush()
        if hasattr(sys.stderr, "flush"):
            sys.stderr.flush()


if __name__ == "__main__":
    main()
