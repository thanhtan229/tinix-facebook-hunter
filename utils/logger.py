"""
Tinix Facebook Down — Logger
Custom logging system that emits messages to both file and GUI console.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional


class GUIHandler(logging.Handler):
    """
    Custom logging handler that forwards log records to a GUI callback.
    The callback receives (level, message) where level is 'INFO', 'WARNING', or 'ERROR'.
    """

    def __init__(self, callback: Optional[Callable] = None):
        super().__init__()
        self._callback = callback

    def set_callback(self, callback: Callable) -> None:
        """Set or update the GUI callback function."""
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        if self._callback is None:
            return
        try:
            msg = self.format(record)
            level = record.levelname  # INFO, WARNING, ERROR
            self._callback(level, msg)
        except Exception:
            self.handleError(record)


# --- Module-level singleton logger ---

_logger: Optional[logging.Logger] = None
_gui_handler: Optional[GUIHandler] = None


def _get_log_dir() -> Path:
    """Get the log directory."""
    if getattr(sys, 'frozen', False):
        log_dir = Path(sys.executable).parent / "logs"
    else:
        log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logger(name: str = "TinixFBDown") -> logging.Logger:
    """
    Initialize and configure the application logger.
    Creates both file and GUI handlers.
    """
    global _logger, _gui_handler

    if _logger is not None:
        return _logger

    _logger = logging.getLogger(name)
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False

    # Formatter
    fmt = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    # File handler — log everything to file
    log_file = _get_log_dir() / f"app_{datetime.now().strftime('%Y%m%d')}.log"
    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        _logger.addHandler(file_handler)
    except IOError:
        pass  # If can't write log file, skip silently

    # GUI handler — will be connected later
    _gui_handler = GUIHandler()
    _gui_handler.setLevel(logging.INFO)
    _gui_handler.setFormatter(fmt)
    _logger.addHandler(_gui_handler)

    return _logger


def get_logger() -> logging.Logger:
    """Get the application logger (creates if needed)."""
    global _logger
    if _logger is None:
        setup_logger()
    return _logger


def set_gui_callback(callback: Callable) -> None:
    """Connect the GUI console to receive log messages."""
    global _gui_handler
    if _gui_handler is None:
        setup_logger()
    _gui_handler.set_callback(callback)


def info(message: str) -> None:
    """Log an info message."""
    get_logger().info(message)


def warning(message: str) -> None:
    """Log a warning message."""
    get_logger().warning(message)


def error(message: str) -> None:
    """Log an error message."""
    get_logger().error(message)


def exception(
    message: str,
    exc: Optional[BaseException] = None,
    *,
    context: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    widget: Any = None,
) -> Optional[Path]:
    """Log an exception with traceback and write a diagnostic report."""
    import traceback

    report_path: Optional[Path] = None
    if exc is not None:
        try:
            from utils import diagnostics

            report_path = diagnostics.capture_exception(
                context or message,
                exc,
                extra=extra,
                widget=widget,
            )
        except Exception:
            report_path = None

    log = get_logger()
    if exc is None:
        log.exception(message)
    else:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
        log.error(f"{message}\n{tb}")

    if report_path:
        log.error(f"Diagnostic report saved: {report_path}")
    return report_path


def debug(message: str) -> None:
    """Log a debug message."""
    get_logger().debug(message)
