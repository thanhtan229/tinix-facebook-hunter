"""
Tinix Facebook Down — Facebook Login Engine
Handles auto-login with username/password + TOTP 2FA.
"""

import time
from typing import Optional

from utils import logger

try:
    import pyotp
except ImportError:
    pyotp = None


class FacebookLogin:
    """Handles Facebook login flow via Playwright page."""

    def __init__(self, page, account: dict):
        """
        Args:
            page: Playwright page instance
            account: dict with keys: username, password, secret_2fa, cookie
        """
        self._page = page
        self._account = account

    def ensure_logged_in(self) -> bool:
        """Check session → login if needed → return True if authenticated."""
        logger.info(f"🔐 Kiểm tra đăng nhập: {self._account.get('username', '?')}")

        # Step 1: Check if already logged in
        if self._check_session():
            logger.info("✅ Đã đăng nhập Facebook")
            return True

        # Step 2: Handle "Tiếp tục" / "Continue as" page
        if self._handle_continue_page():
            if self._check_session():
                logger.info("✅ Đã đăng nhập Facebook (xác nhận)")
                return True

        # Step 3: Try login with credentials
        username = self._account.get("username", "").strip()
        password = self._account.get("password", "").strip()

        if not username or not password:
            logger.warning("⚠ Thiếu username hoặc password")
            return False

        if self._do_login(username, password):
            logger.info("✅ Đăng nhập Facebook thành công!")
            return True

        logger.error("❌ Đăng nhập thất bại")
        return False

    def _check_session(self) -> bool:
        """Navigate to facebook.com and check if logged in."""
        try:
            page = self._page
            current_url = page.url or ""

            # Only navigate if not on facebook
            if "facebook.com" not in current_url:
                page.goto("https://www.facebook.com/", wait_until="load", timeout=20000)
                time.sleep(3)

            state = page.evaluate("""() => ({
                hasNav: !!document.querySelector('[role="navigation"]'),
                hasFeed: !!document.querySelector('[role="feed"]'),
                hasLoginForm: !!document.querySelector('#login_form, form[action*="login"]'),
            })""")

            return state.get("hasNav") or state.get("hasFeed")
        except Exception as e:
            logger.debug(f"Check session error: {str(e)[:80]}")
            return False

    def _handle_continue_page(self) -> bool:
        """Detect and click 'Tiếp tục' / 'Continue' button."""
        try:
            body_text = self._page.evaluate("() => document.body.innerText.slice(0, 300)")

            if "Tiếp tục" not in body_text and "Continue" not in body_text:
                return False

            logger.info("🔄 Trang xác nhận 'Tiếp tục'...")

            clicked = self._page.evaluate("""() => {
                const spans = document.querySelectorAll('span');
                for (const s of spans) {
                    const text = s.textContent.trim();
                    if (text === 'Tiếp tục' || text === 'Continue') {
                        const btn = s.closest('[role="button"]') || s.parentElement;
                        if (btn) { btn.click(); return true; }
                    }
                }
                return false;
            }""")

            if clicked:
                time.sleep(4)
                # Check if it asks for password (expired session)
                has_pw = self._page.evaluate(
                    "() => !!document.querySelector('input[type=\"password\"]')"
                )
                if has_pw:
                    logger.info("Session hết hạn — cần đăng nhập lại")
                    return False
                return True

            return False
        except Exception:
            return False

    def _do_login(self, username: str, password: str) -> bool:
        """Perform the full login flow."""
        try:
            page = self._page

            # Navigate to login page
            page.goto("https://www.facebook.com/login/", wait_until="load", timeout=20000)
            time.sleep(3)

            # Fill email/phone
            email_input = page.locator('input#email, input[name="email"]').first
            email_input.fill(username)
            time.sleep(0.5)

            # Fill password
            pass_input = page.locator('input#pass, input[name="pass"]').first
            pass_input.fill(password)
            time.sleep(0.5)

            # Click login button
            login_btn = page.locator('button[name="login"], button[type="submit"], '
                                     'input[type="submit"]').first
            login_btn.click()
            time.sleep(5)

            # Check what happened
            current_url = page.url

            # Check for 2FA
            if self._is_2fa_page():
                logger.info("🔐 Trang 2FA detected — nhập mã...")
                return self._handle_2fa()

            # Check for checkpoint/security
            if "checkpoint" in current_url:
                logger.warning("⚠ Facebook checkpoint — kiểm tra tài khoản")
                return self._handle_checkpoint()

            # Check if wrong password
            error_text = page.evaluate("""() => {
                const errors = document.querySelectorAll('[role="alert"], .login_error_box, ._9ay7');
                let text = '';
                errors.forEach(e => text += e.textContent);
                return text.slice(0, 200);
            }""")
            if error_text and ("password" in error_text.lower() or "mật khẩu" in error_text.lower()):
                logger.error(f"❌ Sai mật khẩu: {error_text[:100]}")
                return False

            # Check if successfully logged in
            time.sleep(3)
            return self._check_session()

        except Exception as e:
            logger.error(f"Lỗi đăng nhập: {str(e)[:150]}")
            return False

    def _is_2fa_page(self) -> bool:
        """Check if current page is asking for 2FA code."""
        try:
            result = self._page.evaluate("""() => {
                const body = document.body.innerText.slice(0, 500).toLowerCase();
                const has2fa = body.includes('xác thực') || body.includes('authentication') ||
                               body.includes('security code') || body.includes('mã đăng nhập') ||
                               body.includes('two-factor') || body.includes('approval code');
                const hasCodeInput = !!document.querySelector(
                    'input[name="approvals_code"], input[id="approvals_code"], ' +
                    'input[type="text"][autocomplete="one-time-code"], ' +
                    'input[type="tel"]'
                );
                return has2fa || hasCodeInput;
            }""")
            return result
        except Exception:
            return False

    def _handle_2fa(self) -> bool:
        """Generate TOTP code and submit."""
        secret = self._account.get("secret_2fa", "").strip()

        if not secret:
            logger.warning("⚠ Không có 2FA secret — không thể tự nhập mã")
            logger.warning("Vui lòng thêm 2FA secret trong Quản lý tài khoản")
            return False

        if pyotp is None:
            logger.error("❌ Thư viện pyotp chưa cài — pip install pyotp")
            return False

        try:
            # Generate TOTP code
            totp = pyotp.TOTP(secret)
            code = totp.now()
            logger.info(f"🔑 Mã 2FA: {code}")

            # Find the code input field
            code_input = self._page.locator(
                'input[name="approvals_code"], input[id="approvals_code"], '
                'input[type="text"][autocomplete="one-time-code"], '
                'input[type="tel"]'
            ).first

            code_input.fill(code)
            time.sleep(1)

            # Submit
            submit_btn = self._page.locator(
                'button[type="submit"], button:has-text("Tiếp tục"), '
                'button:has-text("Continue"), button:has-text("Submit")'
            ).first
            submit_btn.click()
            time.sleep(5)

            # Check if "remember browser" page
            body_text = self._page.evaluate("() => document.body.innerText.slice(0, 300)")
            if "trình duyệt" in body_text.lower() or "browser" in body_text.lower():
                # Click "Continue" / "Save browser"
                try:
                    self._page.locator(
                        'button:has-text("Tiếp tục"), button:has-text("Continue"), '
                        'button:has-text("Lưu")'
                    ).first.click(timeout=3000)
                    time.sleep(3)
                except Exception:
                    pass

            # Verify
            time.sleep(3)
            return self._check_session()

        except Exception as e:
            logger.error(f"Lỗi 2FA: {str(e)[:150]}")
            return False

    def _handle_checkpoint(self) -> bool:
        """Handle Facebook checkpoint/security check."""
        logger.warning("⚠ Facebook yêu cầu xác minh bảo mật")
        logger.warning("Vui lòng kiểm tra email hoặc SĐT để xác minh")

        # Try to wait for user to resolve manually
        for i in range(30):
            time.sleep(2)
            if self._check_session():
                logger.info("✅ Checkpoint đã được giải quyết")
                return True

            if "checkpoint" not in self._page.url:
                break

        return self._check_session()
