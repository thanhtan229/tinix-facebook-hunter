"""
Diagnostics helpers for writing actionable crash and error reports.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple


_LOCK = threading.Lock()
_LAST_REPORT: Optional[Path] = None


def get_diagnostics_dir() -> Path:
    """Return the directory used for diagnostic reports."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    path = base / "diagnostics"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_latest_report() -> Optional[Path]:
    """Return the newest diagnostic text report, if one exists."""
    global _LAST_REPORT
    if _LAST_REPORT and _LAST_REPORT.exists():
        return _LAST_REPORT

    reports = sorted(
        get_diagnostics_dir().glob("diagnostic_*.txt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return reports[0] if reports else None


def capture_exception(
    context: str,
    exc: BaseException,
    *,
    exc_tb: Any = None,
    extra: Optional[Dict[str, Any]] = None,
    widget: Any = None,
) -> Path:
    """
    Write a diagnostic report for an exception and return its path.

    The report is intentionally plain text so it can be opened easily on any
    Windows machine and pasted into a bug report.
    """
    if exc_tb is None:
        exc_tb = exc.__traceback__

    return _write_report(
        context=context,
        exception_text=f"{type(exc).__name__}: {exc}",
        traceback_text="".join(traceback.format_exception(type(exc), exc, exc_tb)).rstrip(),
        extra=extra,
        widget=widget,
    )


def capture_message(
    context: str,
    message: str,
    *,
    extra: Optional[Dict[str, Any]] = None,
    widget: Any = None,
) -> Path:
    """Write a non-exception diagnostic report."""
    return _write_report(
        context=context,
        exception_text=f"Not an exception: {message}",
        traceback_text="Not an exception",
        extra=extra,
        widget=widget,
    )


@contextmanager
def diagnostic_context(
    context: str,
    *,
    extra: Optional[Dict[str, Any]] = None,
    widget: Any = None,
) -> Iterator[None]:
    """Capture and re-raise exceptions from a risky operation."""
    try:
        yield
    except Exception as exc:
        capture_exception(context, exc, extra=extra, widget=widget)
        raise


def _write_report(
    *,
    context: str,
    exception_text: str,
    traceback_text: str,
    extra: Optional[Dict[str, Any]],
    widget: Any,
) -> Path:
    with _LOCK:
        report_dir = get_diagnostics_dir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        report_path = report_dir / f"diagnostic_{stamp}.txt"
        screenshot_path = _capture_widget_screenshot(widget, report_dir, stamp)

        lines = [
            "Tinix Diagnostic Report",
            "=" * 60,
            f"Created: {datetime.now().isoformat(timespec='seconds')}",
            f"Context: {context}",
            f"Exception: {exception_text}",
            "",
            "Environment",
            "-" * 60,
            f"Python: {sys.version.replace(os.linesep, ' ')}",
            f"Executable: {sys.executable}",
            f"Platform: {platform.platform()}",
            f"Working directory: {Path.cwd()}",
            f"Frozen exe: {getattr(sys, 'frozen', False)}",
            f"Git revision: {_git_revision()}",
            "",
            "Extra",
            "-" * 60,
            _format_extra(extra),
            "",
            "Screenshot",
            "-" * 60,
            str(screenshot_path) if screenshot_path else "Not captured",
            "",
            "Traceback",
            "-" * 60,
            traceback_text,
            "",
            "Recent Log",
            "-" * 60,
            _recent_log_tail(),
            "",
        ]

        report_path.write_text("\n".join(lines), encoding="utf-8")

        global _LAST_REPORT
        _LAST_REPORT = report_path
        return report_path


def _format_extra(extra: Optional[Dict[str, Any]]) -> str:
    if not extra:
        return "None"
    try:
        return json.dumps(extra, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return repr(extra)


def _recent_log_tail(max_lines: int = 120) -> str:
    log_dir = _log_dir()
    if not log_dir.exists():
        return "No log directory"

    logs = sorted(log_dir.glob("app_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return "No log files"

    try:
        lines = logs[0].read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-max_lines:]
        return f"File: {logs[0]}\n" + "\n".join(tail)
    except Exception as exc:
        return f"Could not read log: {exc}"


def _log_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "logs"
    return Path(__file__).parent.parent / "logs"


def _git_revision() -> str:
    try:
        root = Path(__file__).parent.parent
        cmd = [
            "git",
            "-c",
            f"safe.directory={root.as_posix()}",
            "rev-parse",
            "--short",
            "HEAD",
        ]
        result = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _capture_widget_screenshot(widget: Any, report_dir: Path, stamp: str) -> Optional[Path]:
    if widget is None:
        return None

    try:
        from PIL import ImageGrab

        widget.update_idletasks()
        x = widget.winfo_rootx()
        y = widget.winfo_rooty()
        w = widget.winfo_width()
        h = widget.winfo_height()
        if w <= 1 or h <= 1:
            return None

        path = report_dir / f"diagnostic_{stamp}.png"
        image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        image.save(path)
        return path
    except Exception:
        return None
