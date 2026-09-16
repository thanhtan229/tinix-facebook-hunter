"""Focused tests for the desktop WebUI launcher contract."""

from unittest.mock import patch

import start_webui


def test_get_listen_port_uses_the_desktop_app_mode_port():
    with patch("start_webui.is_port_in_use", return_value=False):
        assert start_webui.get_listen_port() == start_webui.DEFAULT_PORT


def test_get_listen_port_refuses_to_diverge_from_desktop_app_mode_url():
    with patch("start_webui.is_port_in_use", return_value=True):
        try:
            start_webui.get_listen_port()
        except RuntimeError as exc:
            assert str(start_webui.DEFAULT_PORT) in str(exc)
        else:
            raise AssertionError("Expected a port-conflict error")


def test_main_does_not_start_a_hidden_server_on_an_alternate_port():
    with patch("start_webui.is_port_in_use", return_value=True), patch("start_webui.uvicorn.run") as run:
        assert start_webui.main() == 1
        run.assert_not_called()


def test_main_starts_and_records_a_normal_server_stop():
    with patch("start_webui.is_port_in_use", return_value=False), patch("start_webui.uvicorn.run") as run:
        assert start_webui.main() == 0
        run.assert_called_once_with(
            "web.app:app",
            host=start_webui.HOST,
            port=start_webui.DEFAULT_PORT,
            ws="wsproto",
            log_level="warning",
            access_log=False,
        )
