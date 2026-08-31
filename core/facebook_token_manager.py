"""
Facebook token management helpers.

Tokens are credentials. Runtime code may display a token in the account dialog by
user choice, but should never write token values to logs or diagnostics.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from core.db_storage import (
    delete_facebook_token,
    get_db_path,
    get_facebook_token,
    save_facebook_token,
)
from utils import config, logger


class FacebookTokenManager:
    """Small service layer for Facebook token DB operations."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or get_db_path(config.get("scraper_db_path", ""))

    def get(self, account_id: int, token_type: str = "user") -> Optional[dict]:
        return get_facebook_token(self._db_path, account_id, token_type)

    def save_manual(
        self,
        account_id: int,
        uid: str,
        access_token: str,
        token_type: str = "user",
        page_id: str = "",
        scopes: str = "",
        expires_in: int = 0,
    ) -> bool:
        expires_at = ""
        if expires_in:
            expires_at = (datetime.now() + timedelta(seconds=int(expires_in))).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        return save_facebook_token(
            self._db_path,
            account_id=account_id,
            uid=uid,
            access_token=access_token,
            token_type=token_type,
            page_id=page_id,
            scopes=scopes,
            expires_in=expires_in,
            expires_at=expires_at,
            status="Valid" if access_token else "Missing",
            error="",
        )

    def save_page_tokens(
        self,
        account_id: int,
        uid: str,
        page_tokens: List[dict],
        permanent: bool = False,
    ) -> int:
        """Save a batch of page access tokens.

        Args:
            account_id: Social account ID.
            uid: Facebook user UID (c_user).
            page_tokens: List of dicts with keys: page_id, page_name, access_token.
            permanent: Whether this batch was fetched from the long-lived token flow.

        Returns:
            Number of tokens successfully saved.
        """
        saved = 0
        token_status = "Permanent" if permanent else "Temporary"
        for pt in page_tokens:
            pid = pt.get("page_id", "")
            tok = pt.get("access_token", "")
            if not pid or not tok:
                continue
            ok = save_facebook_token(
                self._db_path,
                account_id=account_id,
                uid=uid,
                access_token=tok,
                token_type="page",
                page_id=pid,
                scopes="",
                expires_in=0,
                expires_at="",
                status=token_status,
                error="",
            )
            if ok:
                saved += 1
        if saved:
            logger.info(
                f"[token] Saved {saved}/{len(page_tokens)} {token_status.lower()} page tokens "
                f"for account_id={account_id}"
            )
        return saved

    def delete(self, account_id: int, token_type: str = "user") -> bool:
        return delete_facebook_token(self._db_path, account_id, token_type)
