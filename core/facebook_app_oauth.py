"""
Facebook App-owned OAuth flow for shared app login.

This module opens the Facebook Login dialog in the already-authenticated Chrome
profile, waits for a localhost callback, exchanges the returned code for a user
access token owned by the configured Facebook App, and returns that token so the
caller can continue with long-lived exchange and /me/accounts.
"""

import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from utils import logger
from utils.config import get_env


DEFAULT_SCOPES = ",".join([
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "pages_manage_metadata",
    "pages_read_user_content",
    "pages_manage_engagement",
    "business_management",
    "public_profile",
])


class _OAuthCallbackState:
    def __init__(self, expected_state: str):
        self.expected_state = expected_state
        self.code = ""
        self.error = ""
        self.error_reason = ""
        self.error_description = ""
        self.received_state = ""
        self.event = threading.Event()


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    state_obj: _OAuthCallbackState = None

    def log_message(self, format, *args):
        return

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        state_obj = self.__class__.state_obj
        if state_obj is None:
            self.send_error(500)
            return

        state_obj.code = (params.get("code") or [""])[0]
        state_obj.error = (params.get("error") or [""])[0]
        state_obj.error_reason = (params.get("error_reason") or [""])[0]
        state_obj.error_description = (params.get("error_description") or [""])[0]
        state_obj.received_state = (params.get("state") or [""])[0]
        state_obj.event.set()

        body = """
        <html><head><meta charset="utf-8"><title>Tinix Facebook Down</title></head>
        <body style="font-family:Segoe UI,Arial,sans-serif;padding:24px;">
        <h2>Đăng nhập Facebook App đã hoàn tất</h2>
        <p>Bạn có thể đóng tab này và quay lại Tinix Facebook Down.</p>
        </body></html>
        """.strip().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FacebookAppOAuth:
    def __init__(self, build_api_opener: Callable[[], tuple], account: Optional[dict] = None):
        self._build_api_opener = build_api_opener
        self._account = account or {}

    @staticmethod
    def is_configured() -> bool:
        return bool(get_env("FB_APP_ID") and get_env("FB_APP_SECRET"))

    @staticmethod
    def get_redirect_uri() -> str:
        return get_env("FB_REDIRECT_URI", "http://localhost:8787/facebook/callback").strip()

    @staticmethod
    def get_scopes() -> str:
        return get_env("FB_OAUTH_SCOPES", DEFAULT_SCOPES).strip() or DEFAULT_SCOPES

    def _start_callback_server(self, redirect_uri: str, state: str):
        parsed = urllib.parse.urlparse(redirect_uri)
        host = parsed.hostname or "127.0.0.1"
        port = int(parsed.port or 80)
        path = parsed.path or "/"

        state_obj = _OAuthCallbackState(expected_state=state)
        handler_cls = type(
            "TinixFacebookOAuthHandler",
            (_OAuthCallbackHandler,),
            {"state_obj": state_obj},
        )
        server = ThreadingHTTPServer((host, port), handler_cls)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, state_obj, path

    def _build_auth_url(self, state: str) -> str:
        app_id = get_env("FB_APP_ID")
        redirect_uri = self.get_redirect_uri()
        params = {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": self.get_scopes(),
            "auth_type": "rerequest",
        }
        return "https://www.facebook.com/v25.0/dialog/oauth?" + urllib.parse.urlencode(params)

    def _try_click_oauth_buttons(self, page) -> str:
        text_variants = [
            "Tiếp tục dưới tên",
            "Tiếp tục",
            "Continue as",
            "Continue",
            "Cho phép",
            "Đồng ý",
            "OK",
            "Authorize",
        ]

        def _iter_frames():
            try:
                frames = list(page.frames)
            except Exception:
                frames = []
            return frames or [page]

        # Prefer trusted Playwright clicks first, including iframe content.
        for frame in _iter_frames():
            for text in text_variants:
                selectors = [
                    f'button:has-text("{text}")',
                    f'[role="button"]:has-text("{text}")',
                    f'input[type="submit"][value*="{text}"]',
                ]
                for sel in selectors:
                    try:
                        loc = frame.locator(sel).first
                        if loc.count() < 1:
                            continue
                        if not loc.is_visible(timeout=800):
                            continue
                        label = (loc.inner_text(timeout=800) or text).strip()
                        loc.click(timeout=1500)
                        logger.info(f"[app-oauth] Clicked consent button: {label[:60]}")
                        return label
                    except Exception:
                        continue

        # Fallback: JS click in top document.
        try:
            clicked = page.evaluate(
                """() => {
                    const wanted = [
                        'continue as', 'continue', 'allow', 'ok', 'authorize',
                        'tiếp tục', 'cho phép', 'đồng ý', 'xác nhận'
                    ];
                    const nodes = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'));
                    for (const node of nodes) {
                        const text = ((node.innerText || node.textContent || node.value || '') + '').trim().toLowerCase();
                        if (!text) continue;
                        if (wanted.some(key => text.includes(key))) {
                            node.click();
                            return text;
                        }
                    }
                    return '';
                }"""
            )
            if clicked:
                logger.info(f"[app-oauth] Clicked consent button: {clicked[:60]}")
                return clicked
        except Exception:
            pass
        return ""

    def _wait_for_callback(self, page, state_obj: _OAuthCallbackState, callback_path: str, timeout_s: int = 90) -> bool:
        deadline = time.time() + timeout_s
        last_click_at = 0.0
        repeated_clicks = 0
        last_clicked_label = ""
        while time.time() < deadline:
            if state_obj.event.wait(timeout=1.0):
                return True
            try:
                current_url = page.url or ""
            except Exception:
                current_url = ""
            if current_url.startswith(self.get_redirect_uri()):
                return True
            if callback_path and callback_path in current_url and "code=" in current_url:
                return True
            if time.time() - last_click_at >= 2.0:
                clicked = self._try_click_oauth_buttons(page)
                if clicked:
                    last_click_at = time.time()
                    if clicked == last_clicked_label:
                        repeated_clicks += 1
                    else:
                        last_clicked_label = clicked
                        repeated_clicks = 1
                    if repeated_clicks >= 5:
                        logger.warning(
                            "[app-oauth] OAuth dialog is looping on the same consent button "
                            f"('{clicked[:40]}') — stopping early and using fallback flow"
                        )
                        return False
            try:
                body_text = page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 600)")
            except Exception:
                body_text = ""
            lowered = (body_text or "").lower()
            if any(msg in lowered for msg in [
                "app isn't available",
                "app not active",
                "feature unavailable",
                "feature isn't available",
                "login with facebook is currently unavailable for this app",
                "invalid redirect_uri",
                "url blocked",
                "không dùng được ứng dụng này",
                "hiện không dùng được tính năng này",
                "phương thức đăng nhập bằng facebook hiện chưa dùng được cho ứng dụng này",
                "đăng nhập bằng facebook hiện chưa dùng được cho ứng dụng này",
                "chúng tôi đang cập nhật các chi tiết bổ sung cho ứng dụng",
                "redirect_uri",
            ]):
                logger.warning(
                    "[app-oauth] Facebook Login is unavailable for this app. "
                    "Check Facebook Login setup, app mode/roles, and Valid OAuth Redirect URIs. "
                    f"Dialog: {body_text[:160]}"
                )
                return False
        logger.warning("[app-oauth] Timed out waiting for app authorization callback")
        return False

    def exchange_code(self, code: str) -> Optional[str]:
        if not code:
            return None
        app_id = get_env("FB_APP_ID")
        app_secret = get_env("FB_APP_SECRET")
        redirect_uri = self.get_redirect_uri()
        opener, headers = self._build_api_opener()
        params = urllib.parse.urlencode({
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        })
        url = f"https://graph.facebook.com/v25.0/oauth/access_token?{params}"
        try:
            req = urllib.request.Request(url)
            for k, v in headers.items():
                req.add_header(k, v)
            with opener.open(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
            token = data.get("access_token", "")
            if token:
                logger.info("[app-oauth] Received app-owned short-lived user token")
                return token
            logger.warning(f"[app-oauth] Code exchange returned no token: {str(data)[:160]}")
            return None
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode())
                msg = err.get("error", {}).get("message", "")[:160]
                logger.warning(f"[app-oauth] Code exchange failed: HTTP {e.code} — {msg}")
            except Exception:
                logger.warning(f"[app-oauth] Code exchange failed: HTTP {e.code}")
            return None
        except Exception as e:
            logger.warning(f"[app-oauth] Code exchange error: {str(e)[:120]}")
            return None

    def acquire_user_token(self, context, timeout_s: int = 90) -> Optional[str]:
        if not self.is_configured():
            return None

        state = secrets.token_urlsafe(24)
        redirect_uri = self.get_redirect_uri()
        auth_url = self._build_auth_url(state)
        server = None
        page = None
        try:
            server, _thread, state_obj, callback_path = self._start_callback_server(redirect_uri, state)
            page = context.new_page()
            try:
                page.bring_to_front()
            except Exception:
                pass
            logger.info("[app-oauth] Opening Facebook Login dialog for shared app")
            page.goto(auth_url, wait_until="domcontentloaded", timeout=30000)
            ok = self._wait_for_callback(page, state_obj, callback_path, timeout_s=timeout_s)
            if not ok:
                return None

            if state_obj.received_state and state_obj.received_state != state:
                logger.warning("[app-oauth] OAuth state mismatch — ignoring callback")
                return None
            if state_obj.error:
                msg = state_obj.error_description or state_obj.error_reason or state_obj.error
                logger.warning(f"[app-oauth] Facebook authorization error: {msg[:180]}")
                return None

            code = state_obj.code
            if not code:
                try:
                    parsed = urllib.parse.urlparse(page.url or "")
                    params = urllib.parse.parse_qs(parsed.query)
                    code = (params.get("code") or [""])[0]
                except Exception:
                    code = ""
            if not code:
                logger.warning("[app-oauth] Callback completed but no authorization code was found")
                return None
            return self.exchange_code(code)
        except OSError as e:
            logger.warning(f"[app-oauth] Cannot start localhost callback server: {str(e)[:120]}")
            return None
        except Exception as e:
            logger.warning(f"[app-oauth] OAuth flow error: {str(e)[:140]}")
            return None
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass
            if server:
                try:
                    server.shutdown()
                    server.server_close()
                except Exception:
                    pass
