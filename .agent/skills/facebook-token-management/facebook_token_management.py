"""
Facebook Token Management - reference only.

This file is not imported by the Tinix runtime. Keep runtime code in core/ and gui/.

Safety rule: do not harvest access tokens from arbitrary browser network traffic.
Use explicit OAuth/Graph API authorization flows for accounts and assets the app user owns
or administers, store tokens securely, and redact token values from logs.
"""

RUNTIME_FILES = [
    "gui/account_manager.py",
    "core/fb_login.py",
    "core/db_storage.py",
    "core/facebook_token_manager.py",
]

DEBUG_TIMEOUT_SECONDS = 30

