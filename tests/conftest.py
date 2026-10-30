"""Pytest process setup that keeps test diagnostics out of operational logs."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

import pytest


_ORIGINAL_LOG_DIR = os.environ.get("TINIX_LOG_DIR")
_TEST_LOG_DIR = Path(tempfile.mkdtemp(prefix="tinix-facebook-hunter-pytest-"))
os.environ["TINIX_LOG_DIR"] = str(_TEST_LOG_DIR)


@pytest.fixture(autouse=True)
def _restore_tests_do_not_depend_on_a_running_app(monkeypatch):
    """A developer's running WebUI must not make restore tests fail; the guard has its own test."""
    monkeypatch.setattr("core.database_maintenance._app_is_running", lambda: False)


def pytest_sessionfinish(session, exitstatus):
    """Close handlers before deleting the per-process test log directory."""
    try:
        from utils import logger as app_logger

        active_logger = app_logger._logger
        if active_logger:
            for handler in list(active_logger.handlers):
                active_logger.removeHandler(handler)
                handler.close()
        app_logger._logger = None
        app_logger._gui_handler = None
    finally:
        if _ORIGINAL_LOG_DIR is None:
            os.environ.pop("TINIX_LOG_DIR", None)
        else:
            os.environ["TINIX_LOG_DIR"] = _ORIGINAL_LOG_DIR
        logging.shutdown()
        shutil.rmtree(_TEST_LOG_DIR, ignore_errors=True)
