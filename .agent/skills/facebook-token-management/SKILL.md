---
name: Facebook Token Management
description: Reference-only skill for adding safe Facebook token management to Tinix. Use when improving authorized Facebook login/token workflows, Playwright persistent profiles per UID, per-account proxy and user-agent handling, OAuth/Graph API token validation, encrypted token storage, expiry tracking, and screenshot/debug behavior. Do not use for harvesting access tokens from arbitrary browser network traffic.
---

# Facebook Token Management

## Runtime Status

This skill folder is reference-only. The Tinix app does not import or execute files from `.agent/skills` at runtime.

Runtime code should live in:
- `gui/account_manager.py`
- `core/fb_login.py`
- `core/db_storage.py`
- optional new runtime module such as `core/facebook_token_manager.py`

When implementing this workflow, edit runtime files first. After meaningful behavior changes, update this `SKILL.md`.

## Safety Boundary

Do not implement token harvesting from arbitrary `graph.facebook.com` traffic or hidden browser requests. Facebook access tokens are credentials.

Allowed patterns:
- Use an explicit OAuth/Login flow for accounts/pages/business assets the user owns or administers.
- Capture tokens only from an authorized redirect/callback or official API response where the user has intentionally granted permissions.
- Validate tokens with Graph API token inspection where appropriate.
- Store tokens securely, avoid printing them in logs, and redact tokens in diagnostics.

Disallowed patterns:
- Sniff browser traffic to extract `access_token` query/body values from unrelated requests.
- Save tokens from accounts not explicitly authorized by the app user.
- Log full token values to console, diagnostic reports, screenshots, or crash dumps.

## Workflow

1. Load the social account row by UID/account id from `core/db_storage.py`.
2. Resolve the persistent Chrome profile path from UID:
   - Prefer `social_accounts.profile_dir` if present.
   - Fallback to `chrome_profiles/facebook_<account_id>`.
3. Launch Playwright with `chromium.launch_persistent_context(...)` or attach to the existing profile through CDP if the app already has one open.
4. Apply the account-specific proxy:
   - `proxy_protocol`
   - `proxy_host`
   - `proxy_port`
   - optional `proxy_auth_user`
   - optional `proxy_auth_pass`
5. Apply the account-specific user-agent if the account has one. If not, use a stable desktop Chrome UA and persist it per account to avoid fingerprint churn.
6. Open Facebook or the explicit OAuth authorization URL.
7. Run `FacebookLogin.ensure_logged_in()` only if the session is not already logged in. Do not refresh an existing logged-in Facebook tab just to check status.
8. Wait up to 30 seconds for an authorized token result.
9. If a token is obtained from an explicit OAuth/official response:
   - Save token metadata in DB with `uid`, `account_id`, `token_type`, `expires_at`, `expires_in`, `scopes`, and `updated_at`.
   - Store the token encrypted or at minimum avoid logging it.
10. If no token is obtained within 30 seconds:
   - Log a clear error without token values.
   - Capture a screenshot into `debug_screenshots/`.
   - Save diagnostic context: account id, uid, current URL, page title, and timeout reason.

## Suggested DB Shape

Add a separate table instead of stuffing token fields into unrelated account rows:

```sql
CREATE TABLE IF NOT EXISTS facebook_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    uid TEXT NOT NULL DEFAULT '',
    token_type TEXT NOT NULL DEFAULT 'user',
    access_token TEXT NOT NULL DEFAULT '',
    scopes TEXT NOT NULL DEFAULT '',
    expires_in INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_facebook_tokens_account ON facebook_tokens(account_id);
CREATE INDEX IF NOT EXISTS idx_facebook_tokens_uid ON facebook_tokens(uid);
```

Prefer encrypting `access_token` before saving. If encryption is not available yet, keep the storage boundary explicit and do not include token values in logs or exported reports.

## Playwright Pattern

Use persistent profile and per-account proxy/user-agent:

```python
context = playwright.chromium.launch_persistent_context(
    user_data_dir=profile_dir,
    channel="chrome",
    headless=False,
    proxy=proxy_config_or_none,
    user_agent=user_agent,
    args=[
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1280,900",
    ],
)
```

If attaching to an existing app Chrome window through CDP, do not spawn a duplicate process for the same profile/port. Reuse the existing context and tab when possible.

## Timeout And Debug

On a 30 second timeout:

```python
debug_dir = Path("debug_screenshots")
debug_dir.mkdir(exist_ok=True)
page.screenshot(path=str(debug_dir / f"facebook_token_timeout_{account_id}_{ts}.png"), full_page=True)
logger.error(f"Không lấy được token hợp lệ sau 30 giây: account_id={account_id}, uid={uid}")
```

Do not include token-like query strings in screenshots metadata or diagnostic logs.

## Runtime Integration Checklist

- Add DB helpers in `core/db_storage.py`:
  - `save_facebook_token(...)`
  - `get_facebook_token(account_id, token_type="user")`
  - `mark_facebook_token_error(...)`
- Add runtime manager in `core/facebook_token_manager.py`.
- Add a button/action in `gui/account_manager.py` only if the UX needs manual token refresh.
- Use existing account proxy/profile helpers instead of creating separate profile rules.
- Ensure all logs redact token values:
  - show first 0 chars of token; never partial-token logs unless explicitly masked like `token=[redacted]`.

