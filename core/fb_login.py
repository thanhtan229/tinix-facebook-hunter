"""
Tinix Facebook Down - Facebook Login Engine
Handles auto-login with username/password + TOTP 2FA.
"""

import time

from utils import logger

try:
    import pyotp
except ImportError:
    pyotp = None


class FacebookLogin:
    """Handles Facebook login flow via a Playwright page."""

    def __init__(self, page, account: dict):
        """
        Args:
            page: Playwright page instance.
            account: dict with keys like username, password, secret_2fa, cookie.
        """
        self._page = page
        self._account = account

    def _refresh_page(self):
        """Rebind to a live page in the same context when the current tab changes."""
        try:
            if self._page and not self._page.is_closed():
                return self._page
        except Exception:
            pass

        try:
            context = self._page.context
        except Exception:
            context = None

        if context:
            for candidate in reversed(context.pages):
                try:
                    if candidate and not candidate.is_closed():
                        self._page = candidate
                        return candidate
                except Exception:
                    continue
        return self._page

    def ensure_logged_in(self) -> bool:
        """Check session -> login if needed -> return True if authenticated."""
        logger.info(f"Kiểm tra đăng nhập: {self._account.get('username', '?')}")

        if self.check_session():
            logger.info("✅ Đã đăng nhập Facebook")
            return True

        if self._handle_continue_page():
            if self.check_session():
                logger.info("✅ Đã đăng nhập Facebook (xác nhận)")
                return True

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

    def check_session(self) -> bool:
        """Public wrapper so callers can safely probe session state first."""
        return self._check_session()

    def _check_session(self) -> bool:
        """Navigate to Facebook and check if logged in on desktop or mobile UI."""
        try:
            page = self._refresh_page()
            current_url = page.url or ""

            if "facebook.com" not in current_url:
                page.goto("https://m.facebook.com/", wait_until="load", timeout=20000)
                time.sleep(3)
            else:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass

            state = page.evaluate("""() => ({
                hasNav: !!document.querySelector('[role="navigation"]'),
                hasFeed: !!document.querySelector('[role="feed"]'),
                hasLoginForm: !!document.querySelector('#login_form, form[action*="login"], form[action*="/login"]'),
                hasEmailInput: !!document.querySelector('input#email, input[name="email"]'),
                hasPasswordInput: !!document.querySelector('input#pass, input[name="pass"], input[type="password"]'),
                hasMobileHome: !!document.querySelector(
                    'a[href*="/home.php"], a[href="/"], a[href*="/friends/"], #m_news_feed_stream'
                ),
                hasLogoutForm: !!document.querySelector('form[action*="logout"], a[href*="logout.php"]'),
                hasComposer: !!document.querySelector(
                    'textarea[name="xc_message"], div[contenteditable="true"], form[action*="composer"]'
                ),
            })""")

            if state.get("hasNav") or state.get("hasFeed"):
                return True
            if state.get("hasMobileHome") or state.get("hasLogoutForm") or state.get("hasComposer"):
                return True
            return False
        except Exception as e:
            logger.debug(f"Check session error: {str(e)[:80]}")
            try:
                page = self._refresh_page()
                state = page.evaluate("""() => ({
                    hasNav: !!document.querySelector('[role="navigation"]'),
                    hasFeed: !!document.querySelector('[role="feed"]'),
                    hasMobileHome: !!document.querySelector(
                        'a[href*="/home.php"], a[href="/"], a[href*="/friends/"], #m_news_feed_stream'
                    ),
                    hasLogoutForm: !!document.querySelector('form[action*="logout"], a[href*="logout.php"]'),
                    hasComposer: !!document.querySelector(
                        'textarea[name="xc_message"], div[contenteditable="true"], form[action*="composer"]'
                    ),
                })""")
                return bool(
                    state.get("hasNav")
                    or state.get("hasFeed")
                    or state.get("hasMobileHome")
                    or state.get("hasLogoutForm")
                    or state.get("hasComposer")
                )
            except Exception:
                pass
            return False

    def _handle_continue_page(self) -> bool:
        """Detect and click 'Tiếp tục' / 'Continue' button."""
        try:
            page = self._refresh_page()
            body_text = page.evaluate("() => document.body.innerText.slice(0, 300)")

            if "Tiếp tục" not in body_text and "Continue" not in body_text:
                return False

            logger.info("Trang xác nhận 'Tiếp tục'...")

            clicked = page.evaluate("""() => {
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

            if not clicked:
                return False

            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            time.sleep(2)

            if self.check_session():
                return True

            try:
                page.wait_for_selector('input[type="password"]', timeout=5000)
                has_pw = True
            except Exception:
                has_pw = page.evaluate(
                    "() => !!document.querySelector('input[type=\\\"password\\\"]')"
                )

            if has_pw:
                password = self._account.get("password", "").strip()
                if not password:
                    logger.info("Session cần xác nhận password nhưng không có password trong DB")
                    return False

                logger.info("Nhập lại mật khẩu xác nhận trên trang 'Tiếp tục'...")
                try:
                    page = self._refresh_page()
                    pw_input = page.locator('input[type="password"]').first
                    pw_input.fill(password)
                    time.sleep(0.5)

                    submitted = page.evaluate("""() => {
                        const buttons = document.querySelectorAll(
                            'button[type="submit"], [role="button"], input[type="submit"]'
                        );
                        for (const btn of buttons) {
                            const text = (btn.textContent || btn.value || '').trim().toLowerCase();
                            if (['tiếp tục', 'continue', 'đăng nhập', 'log in', 'submit'].some(
                                k => text.includes(k)
                            )) {
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    }""")
                    if not submitted:
                        pw_input.press("Enter")

                    time.sleep(5)
                    if not self.check_session():
                        logger.warning("Xác nhận password xong nhưng session chưa live")
                        return False

                    logger.info("Đã xác nhận mật khẩu trên trang 'Tiếp tục'")
                    return True
                except Exception as e:
                    time.sleep(3)
                    if self.check_session():
                        logger.info("Session đã live sau khi xác nhận trang Continue")
                        return True
                    logger.warning(f"Nhập password xác nhận thất bại: {str(e)[:80]}")
                    return False

            return self.check_session()
        except Exception:
            return False

    def _do_login(self, username: str, password: str) -> bool:
        """Perform the full login flow."""
        try:
            page = self._refresh_page()
            page.goto("https://m.facebook.com/login/", wait_until="load", timeout=20000)
            time.sleep(3)

            if self._handle_continue_page() and self.check_session():
                return True

            page = self._refresh_page()
            email_input = page.locator('input#email, input[name="email"]').first
            email_input.fill(username)
            time.sleep(0.5)

            page = self._refresh_page()
            pass_input = page.locator('input#pass, input[name="pass"]').first
            pass_input.fill(password)
            time.sleep(0.5)

            if not self._click_login_button():
                logger.warning("Không click được nút login, thử nhấn Enter")
                pass_input.press("Enter")
            time.sleep(5)

            current_url = page.url

            if self._is_2fa_page():
                logger.info("Trang 2FA được phát hiện, đang nhập mã...")
                return self._handle_2fa()

            if "checkpoint" in current_url:
                logger.warning("⚠ Facebook checkpoint — kiểm tra tài khoản")
                return self._handle_checkpoint()

            error_text = page.evaluate("""() => {
                const errors = document.querySelectorAll('[role="alert"], .login_error_box, ._9ay7');
                let text = '';
                errors.forEach(e => text += e.textContent);
                return text.slice(0, 200);
            }""")
            if error_text and ("password" in error_text.lower() or "mật khẩu" in error_text.lower()):
                logger.error(f"❌ Sai mật khẩu: {error_text[:100]}")
                return False

            time.sleep(3)
            return self._check_session()
        except Exception as e:
            logger.error(f"Lỗi đăng nhập: {str(e)[:150]}")
            return False

    def _click_login_button(self) -> bool:
        """Click Facebook login button across mobile and desktop variants."""
        selectors = [
            'button[name="login"]',
            'button[type="submit"]',
            'input[name="login"]',
            'input[type="submit"]',
            'div[role="button"]:has-text("Log in")',
            'div[role="button"]:has-text("Đăng nhập")',
            'button:has-text("Log in")',
            'button:has-text("Đăng nhập")',
            'text=/^(Log in|Đăng nhập)$/i',
        ]
        for selector in selectors:
            try:
                btn = self._page.locator(selector).first
                if btn.count() > 0:
                    btn.click(timeout=4000)
                    return True
            except Exception:
                continue

        try:
            return bool(self._page.evaluate("""() => {
                const labels = /^(log in|login|đăng nhập|dang nhap)$/i;
                const candidates = Array.from(document.querySelectorAll(
                    'button,input[type="submit"],div[role="button"],a[role="button"]'
                ));
                const el = candidates.find(node => {
                    const text = (node.innerText || node.value || node.getAttribute('aria-label') || '').trim();
                    return labels.test(text);
                });
                if (el) {
                    el.click();
                    return true;
                }
                const form = document.querySelector('form');
                if (form) {
                    form.requestSubmit ? form.requestSubmit() : form.submit();
                    return true;
                }
                return false;
            }"""))
        except Exception:
            return False

    def _is_2fa_page(self) -> bool:
        """Check if current page is asking for a 2FA code."""
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
        """Generate a TOTP code and submit it."""
        secret = self._account.get("secret_2fa", "").strip()

        if not secret:
            logger.warning("⚠ Không có 2FA secret — không thể tự nhập mã")
            logger.warning("Vui lòng thêm 2FA secret trong Quản lý tài khoản")
            return False

        if pyotp is None:
            logger.error("❌ Thư viện pyotp chưa cài — pip install pyotp")
            return False

        try:
            totp = pyotp.TOTP(secret)
            code = totp.now()
            logger.info("Đã tạo mã 2FA cho bước xác thực")

            code_input = self._page.locator(
                'input[name="approvals_code"], input[id="approvals_code"], ' +
                'input[type="text"][autocomplete="one-time-code"], ' +
                'input[type="tel"]'
            ).first
            code_input.fill(code)
            time.sleep(1)

            submit_btn = self._page.locator(
                'button[type="submit"], button:has-text("Tiếp tục"), ' +
                'button:has-text("Continue"), button:has-text("Submit")'
            ).first
            submit_btn.click()
            time.sleep(5)

            body_text = self._page.evaluate("() => document.body.innerText.slice(0, 300)")
            if "trình duyệt" in body_text.lower() or "browser" in body_text.lower():
                try:
                    self._page.locator(
                        'button:has-text("Tiếp tục"), button:has-text("Continue"), ' +
                        'button:has-text("Lưu")'
                    ).first.click(timeout=3000)
                    time.sleep(3)
                except Exception:
                    pass

            time.sleep(3)
            return self._check_session()
        except Exception as e:
            logger.error(f"Lỗi 2FA: {str(e)[:150]}")
            return False

    def _handle_checkpoint(self) -> bool:
        """Handle Facebook checkpoint or security verification."""
        logger.warning("⚠ Facebook yêu cầu xác minh bảo mật")
        logger.warning("Vui lòng kiểm tra email hoặc SĐT để xác minh")

        for _ in range(30):
            time.sleep(2)
            if self._check_session():
                logger.info("✅ Checkpoint đã được giải quyết")
                return True

            if "checkpoint" not in self._page.url:
                break

        return self._check_session()
