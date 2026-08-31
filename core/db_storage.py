"""
Tinix Facebook Down — SQLite Storage
Stores all scraped post data in a single SQLite database.
Supports group management and duplicate URL detection.
"""

import os
import json
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from utils import logger
from utils.secure_store import is_protected, protect_secret, reveal_secret


ACCOUNT_SECRET_FIELDS = {"password", "secret_2fa", "email_pass", "cookie"}
SCHEMA_VERSION = 3
_SCHEMA_LOCK = threading.RLock()
_SCHEMA_READY: set[str] = set()


MEDIA_DOWNLOAD_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".webm", ".avi", ".mkv"}


def _default_db_path() -> str:
    """Get default database path."""
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    return str(base / "tinix_scraper.db")


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Get database path from custom or default."""
    environment_path = os.environ.get("TINIX_DB_PATH", "").strip()
    if environment_path:
        return environment_path
    if custom_path and custom_path.strip():
        return custom_path.strip()
    return _default_db_path()


def _open_raw_connection(db_path: str) -> sqlite3.Connection:
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _initialize_schema(db_path: str) -> sqlite3.Connection:
    """Create/upgrade the schema. Caller owns the returned connection."""
    conn = _open_raw_connection(db_path)
    previous_version = int(conn.execute("PRAGMA user_version").fetchone()[0])

    # --- Posts table ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            page_name     TEXT    NOT NULL,
            page_url      TEXT    NOT NULL DEFAULT '',
            group_name    TEXT    NOT NULL DEFAULT '',
            post_id       TEXT    NOT NULL,
            date          TEXT    NOT NULL DEFAULT '',
            post_type     TEXT    NOT NULL DEFAULT 'Text',
            engagement    INTEGER NOT NULL DEFAULT 0,
            comments      INTEGER NOT NULL DEFAULT 0,
            shares         INTEGER NOT NULL DEFAULT 0,
            caption       TEXT    NOT NULL DEFAULT '',
            url           TEXT    NOT NULL DEFAULT '',
            scraped_at    TEXT    NOT NULL DEFAULT '',
            UNIQUE(page_name, post_id)
        )
    """)

    # --- Pages registry (tracks known pages + groups) ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            page_url      TEXT    NOT NULL UNIQUE,
            page_name     TEXT    NOT NULL DEFAULT '',
            group_name    TEXT    NOT NULL DEFAULT '',
            post_count    INTEGER NOT NULL DEFAULT 0,
            last_scraped  TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL DEFAULT ''
        )
    """)

    # --- Favorite pages and their incremental scan cursor ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorite_pages (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            page_url                 TEXT    NOT NULL UNIQUE,
            page_name                TEXT    NOT NULL DEFAULT '',
            account_id               INTEGER DEFAULT NULL,
            scan_limit               INTEGER NOT NULL DEFAULT 100,
            is_active                INTEGER NOT NULL DEFAULT 1,
            cursor_post_ids          TEXT    NOT NULL DEFAULT '[]',
            last_attempt_at          TEXT    NOT NULL DEFAULT '',
            last_successful_scan_at  TEXT    NOT NULL DEFAULT '',
            last_new_posts_count     INTEGER NOT NULL DEFAULT 0,
            last_status              TEXT    NOT NULL DEFAULT 'Chưa quét',
            last_error               TEXT    NOT NULL DEFAULT '',
            created_at               TEXT    NOT NULL DEFAULT '',
            updated_at               TEXT    NOT NULL DEFAULT ''
        )
    """)

    # --- Migration: add missing columns for existing DBs ---
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()]
        if "group_name" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN group_name TEXT NOT NULL DEFAULT ''")
        if "downloaded" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN downloaded INTEGER NOT NULL DEFAULT 0")
        if "download_path" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN download_path TEXT NOT NULL DEFAULT ''")
        if "downloaded_at" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN downloaded_at TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except Exception:
        pass

    # Migration: add follower_count to pages table
    try:
        page_cols = [row[1] for row in conn.execute("PRAGMA table_info(pages)").fetchall()]
        if "follower_count" not in page_cols:
            conn.execute("ALTER TABLE pages ADD COLUMN follower_count INTEGER NOT NULL DEFAULT 0")
            conn.commit()
    except Exception:
        pass

    # Migration: rename views -> shares in posts table
    try:
        post_cols = [row[1] for row in conn.execute("PRAGMA table_info(posts)").fetchall()]
        if "views" in post_cols and "shares" not in post_cols:
            conn.execute("ALTER TABLE posts RENAME COLUMN views TO shares")
            conn.commit()
        elif "shares" not in post_cols:
            conn.execute("ALTER TABLE posts ADD COLUMN shares INTEGER NOT NULL DEFAULT 0")
            conn.commit()
    except Exception:
        pass

    # Migration: add business_id to fb_accounts
    try:
        ac_cols = [row[1] for row in conn.execute("PRAGMA table_info(fb_accounts)").fetchall()]
        if "business_id" not in ac_cols:
            conn.execute("ALTER TABLE fb_accounts ADD COLUMN business_id TEXT NOT NULL DEFAULT ''")
            conn.commit()
    except Exception:
        pass

    # Migration: add new columns to managed_pages
    try:
        mp_cols = [row[1] for row in conn.execute("PRAGMA table_info(managed_pages)").fetchall()]
        if "group_name" not in mp_cols:
            conn.execute("ALTER TABLE managed_pages ADD COLUMN group_name TEXT NOT NULL DEFAULT ''")
        if "avatar_path" not in mp_cols:
            conn.execute("ALTER TABLE managed_pages ADD COLUMN avatar_path TEXT NOT NULL DEFAULT ''")
        if "group_id" not in mp_cols:
            conn.execute("ALTER TABLE managed_pages ADD COLUMN group_id INTEGER NOT NULL DEFAULT 1")
        if "last_synced" not in mp_cols:
            conn.execute("ALTER TABLE managed_pages ADD COLUMN last_synced TEXT NOT NULL DEFAULT ''")
        if "reels_asset_id" not in mp_cols:
            conn.execute("ALTER TABLE managed_pages ADD COLUMN reels_asset_id TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except Exception:
        pass

    # Indexes (after migration so columns exist)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_page ON posts(page_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_page_url_id ON posts(page_url, post_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_date ON posts(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_group ON posts(group_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pages_group ON pages(group_name)")

    # --- Social Post: content_pool ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS content_pool (
            content_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_name   TEXT    NOT NULL,
            folder_path   TEXT    NOT NULL DEFAULT '',
            caption       TEXT    NOT NULL DEFAULT '',
            title         TEXT    NOT NULL DEFAULT '',
            keywords      TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL DEFAULT '',
            UNIQUE(folder_name)
        )
    """)
    # Migration: add title/keywords columns if DB was created before this version
    for _col in ("title", "keywords"):
        try:
            conn.execute(f"ALTER TABLE content_pool ADD COLUMN {_col} TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # column already exists

    # --- Social Post: post_history ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS post_history (
            history_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id      INTEGER NOT NULL,
            account_id      TEXT    NOT NULL DEFAULT '',
            page_name       TEXT    NOT NULL DEFAULT '',
            scheduled_time  TEXT    NOT NULL DEFAULT '',
            status          TEXT    NOT NULL DEFAULT 'Pending',
            platforms       TEXT    NOT NULL DEFAULT '[]',
            scheduling_method TEXT NOT NULL DEFAULT 'App',
            FOREIGN KEY (content_id) REFERENCES content_pool(content_id) ON DELETE CASCADE
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_content_folder ON content_pool(folder_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_content ON post_history(content_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_status ON post_history(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_scheduled ON post_history(scheduled_time)")

    # --- Video Post: multi-platform job queue ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS video_post_jobs (
            job_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id      INTEGER NOT NULL,
            platform        TEXT    NOT NULL DEFAULT '',
            account_id      INTEGER NOT NULL DEFAULT 0,
            target_id       INTEGER NOT NULL DEFAULT 0,
            target_name     TEXT    NOT NULL DEFAULT '',
            target_uid      TEXT    NOT NULL DEFAULT '',
            scheduled_time  TEXT    NOT NULL DEFAULT '',
            mode            TEXT    NOT NULL DEFAULT 'schedule',
            status          TEXT    NOT NULL DEFAULT 'Pending',
            error_log       TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL DEFAULT '',
            updated_at      TEXT    NOT NULL DEFAULT '',
            FOREIGN KEY (content_id) REFERENCES content_pool(content_id) ON DELETE CASCADE,
            UNIQUE(content_id, platform, account_id, target_uid, scheduled_time)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_jobs_content ON video_post_jobs(content_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_jobs_platform ON video_post_jobs(platform)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_jobs_status ON video_post_jobs(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_jobs_scheduled ON video_post_jobs(scheduled_time)")

    # Migration: V15.0 — add new columns to post_history
    try:
        ph_cols = [row[1] for row in conn.execute("PRAGMA table_info(post_history)").fetchall()]
        for col, defn in [
            ("platforms",          "TEXT NOT NULL DEFAULT '[]'"),
            ("scheduling_method", "TEXT NOT NULL DEFAULT 'App'"),
            ("error_log",         "TEXT NOT NULL DEFAULT ''"),
            ("is_duplicate",      "INTEGER NOT NULL DEFAULT 0"),
            ("last_retry_at",     "TEXT NOT NULL DEFAULT ''"),
        ]:
            if col not in ph_cols:
                conn.execute(f"ALTER TABLE post_history ADD COLUMN {col} {defn}")
        conn.commit()
    except Exception:
        pass

    # --- Managed pages (account → pages it administrates) ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS managed_pages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id  INTEGER NOT NULL,
            page_name   TEXT    NOT NULL DEFAULT '',
            page_url    TEXT    NOT NULL DEFAULT '',
            page_id     TEXT    NOT NULL DEFAULT '',
            scanned_at  TEXT    NOT NULL DEFAULT '',
            group_name  TEXT    NOT NULL DEFAULT '',
            avatar_path TEXT    NOT NULL DEFAULT '',
            group_id    INTEGER NOT NULL DEFAULT 1,
            last_synced TEXT    NOT NULL DEFAULT '',
            reels_asset_id TEXT NOT NULL DEFAULT '',
            UNIQUE(account_id, page_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_managed_pages_account ON managed_pages(account_id)")

    # --- Page Groups (named groups for managed pages) ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS page_groups (
            group_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name  TEXT    NOT NULL UNIQUE,
            created_at  TEXT    NOT NULL DEFAULT ''
        )
    """)
    # Ensure "Chưa phân loại" (Uncategorized) group always exists as id=1
    conn.execute("""
        INSERT OR IGNORE INTO page_groups (group_id, group_name, created_at)
        VALUES (1, 'Chưa phân loại', ?)
    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))

    # --- Facebook accounts ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fb_accounts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            label       TEXT    NOT NULL DEFAULT '',
            username    TEXT    NOT NULL,
            password    TEXT    NOT NULL DEFAULT '',
            secret_2fa  TEXT    NOT NULL DEFAULT '',
            email       TEXT    NOT NULL DEFAULT '',
            email_pass  TEXT    NOT NULL DEFAULT '',
            cookie      TEXT    NOT NULL DEFAULT '',
            is_active   INTEGER NOT NULL DEFAULT 1,
            last_login  TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL DEFAULT '',
            UNIQUE(username)
        )
    """)
    try:
        ac_cols = [row[1] for row in conn.execute("PRAGMA table_info(fb_accounts)").fetchall()]
        if "business_id" not in ac_cols:
            conn.execute("ALTER TABLE fb_accounts ADD COLUMN business_id TEXT NOT NULL DEFAULT ''")
            conn.commit()
    except Exception:
        pass

    # --- Multi-platform social accounts ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS social_accounts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            platform      TEXT    NOT NULL DEFAULT 'facebook',
            label         TEXT    NOT NULL DEFAULT '',
            username      TEXT    NOT NULL DEFAULT '',
            password      TEXT    NOT NULL DEFAULT '',
            secret_2fa    TEXT    NOT NULL DEFAULT '',
            email         TEXT    NOT NULL DEFAULT '',
            email_pass    TEXT    NOT NULL DEFAULT '',
            cookie        TEXT    NOT NULL DEFAULT '',
            profile_dir   TEXT    NOT NULL DEFAULT '',
            is_active     INTEGER NOT NULL DEFAULT 0,
            sync_status   TEXT    NOT NULL DEFAULT 'Chưa đồng bộ',
            status_reason TEXT    NOT NULL DEFAULT '',
            uid           TEXT    NOT NULL DEFAULT '',
            avatar_path   TEXT    NOT NULL DEFAULT '',
            last_checked  TEXT    NOT NULL DEFAULT '',
            last_synced   TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL DEFAULT '',
            updated_at    TEXT    NOT NULL DEFAULT '',
            notes         TEXT    NOT NULL DEFAULT '',
            legacy_fb_id  INTEGER DEFAULT NULL,
            UNIQUE(platform, username)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS social_targets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id    INTEGER NOT NULL,
            platform      TEXT    NOT NULL DEFAULT '',
            target_type   TEXT    NOT NULL DEFAULT '',
            target_name   TEXT    NOT NULL DEFAULT '',
            target_uid    TEXT    NOT NULL DEFAULT '',
            target_url    TEXT    NOT NULL DEFAULT '',
            avatar_path   TEXT    NOT NULL DEFAULT '',
            group_name    TEXT    NOT NULL DEFAULT '',
            last_synced   TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL DEFAULT '',
            UNIQUE(account_id, platform, target_uid)
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_social_accounts_platform ON social_accounts(platform)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_social_accounts_status ON social_accounts(sync_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_social_targets_account ON social_targets(account_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_social_targets_platform ON social_targets(platform)")

    # Migration: add user_agent, display_name to social_accounts
    try:
        sa_cols = [row[1] for row in conn.execute("PRAGMA table_info(social_accounts)").fetchall()]
        if "user_agent" not in sa_cols:
            conn.execute("ALTER TABLE social_accounts ADD COLUMN user_agent TEXT NOT NULL DEFAULT ''")
        if "display_name" not in sa_cols:
            conn.execute("ALTER TABLE social_accounts ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except Exception:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS facebook_tokens (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id    INTEGER NOT NULL,
            uid           TEXT    NOT NULL DEFAULT '',
            token_type    TEXT    NOT NULL DEFAULT 'user',
            page_id       TEXT    NOT NULL DEFAULT '',
            access_token  TEXT    NOT NULL DEFAULT '',
            scopes        TEXT    NOT NULL DEFAULT '',
            expires_in    INTEGER NOT NULL DEFAULT 0,
            expires_at    TEXT    NOT NULL DEFAULT '',
            updated_at    TEXT    NOT NULL DEFAULT '',
            status        TEXT    NOT NULL DEFAULT '',
            error         TEXT    NOT NULL DEFAULT '',
            UNIQUE(account_id, token_type, page_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facebook_tokens_account ON facebook_tokens(account_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_facebook_tokens_uid ON facebook_tokens(uid)")

    # Migration: Ensure facebook_tokens has correct UNIQUE constraint
    # Old DBs may have UNIQUE(account_id, token_type) without page_id.
    # We need UNIQUE(account_id, token_type, page_id) for per-page token storage.
    try:
        ft_cols = [row[1] for row in conn.execute("PRAGMA table_info(facebook_tokens)").fetchall()]
        needs_rebuild = False
        if "page_id" not in ft_cols:
            needs_rebuild = True
        else:
            # Check if the UNIQUE index includes page_id
            idxs = conn.execute("PRAGMA index_list(facebook_tokens)").fetchall()
            for idx_row in idxs:
                idx_name = idx_row[1]
                idx_cols = [r[2] for r in conn.execute(f"PRAGMA index_info({idx_name})").fetchall()]
                if "account_id" in idx_cols and "token_type" in idx_cols and "page_id" not in idx_cols:
                    needs_rebuild = True
                    break
        if needs_rebuild:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facebook_tokens_new (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id    INTEGER NOT NULL,
                    uid           TEXT    NOT NULL DEFAULT '',
                    token_type    TEXT    NOT NULL DEFAULT 'user',
                    page_id       TEXT    NOT NULL DEFAULT '',
                    access_token  TEXT    NOT NULL DEFAULT '',
                    scopes        TEXT    NOT NULL DEFAULT '',
                    expires_in    INTEGER NOT NULL DEFAULT 0,
                    expires_at    TEXT    NOT NULL DEFAULT '',
                    updated_at    TEXT    NOT NULL DEFAULT '',
                    status        TEXT    NOT NULL DEFAULT '',
                    error         TEXT    NOT NULL DEFAULT '',
                    UNIQUE(account_id, token_type, page_id)
                )
            """)
            # Copy existing data (handle missing page_id gracefully)
            if "page_id" in ft_cols:
                conn.execute("""
                    INSERT OR IGNORE INTO facebook_tokens_new
                        (account_id, uid, token_type, page_id, access_token, scopes,
                         expires_in, expires_at, updated_at, status, error)
                    SELECT account_id, uid, token_type, page_id, access_token, scopes,
                           expires_in, expires_at, updated_at, status, error
                    FROM facebook_tokens
                """)
            else:
                conn.execute("""
                    INSERT OR IGNORE INTO facebook_tokens_new
                        (account_id, uid, token_type, page_id, access_token, scopes,
                         expires_in, expires_at, updated_at, status, error)
                    SELECT account_id, uid, token_type, '', access_token, scopes,
                           expires_in, expires_at, updated_at, status, error
                    FROM facebook_tokens
                """)
            conn.execute("DROP TABLE facebook_tokens")
            conn.execute("ALTER TABLE facebook_tokens_new RENAME TO facebook_tokens")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_facebook_tokens_account ON facebook_tokens(account_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_facebook_tokens_uid ON facebook_tokens(uid)")
            conn.commit()
            logger.info("✅ Migrated facebook_tokens with UNIQUE(account_id, token_type, page_id)")
    except Exception as e:
        logger.debug(f"facebook_tokens migration check: {str(e)[:100]}")

    # Migration: copy existing Facebook accounts into the new multi-platform table.
    try:
        rows = conn.execute("""
            SELECT id, label, username, password, secret_2fa, email, email_pass,
                   cookie, is_active, last_login, created_at, business_id
            FROM fb_accounts
        """).fetchall()
        for r in rows:
            exists = conn.execute(
                "SELECT id FROM social_accounts WHERE platform = 'facebook' AND legacy_fb_id = ?",
                (r[0],),
            ).fetchone()
            if exists:
                continue
            status = "Live" if r[8] else "Chưa đồng bộ"
            conn.execute("""
                INSERT OR IGNORE INTO social_accounts
                    (platform, label, username, password, secret_2fa, email, email_pass,
                     cookie, is_active, sync_status, status_reason, uid,
                     last_checked, last_synced, created_at, updated_at, legacy_fb_id)
                VALUES ('facebook', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8],
                status, "Migrated from fb_accounts", r[2], r[9] or "",
                r[9] or "", r[10] or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), r[0],
            ))
        conn.commit()
    except Exception as e:
        logger.debug(f"social account migration skipped: {str(e)[:100]}")

    if previous_version < 2:
        for table in ("fb_accounts", "social_accounts"):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "proxy_id" in columns:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN proxy_id")
        conn.execute("DROP TABLE IF EXISTS proxies")

    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()
    return conn


def initialize_database(db_path: str, *, force: bool = False) -> int:
    """Initialize a database once per process and return its schema version."""
    resolved = str(Path(db_path).expanduser().resolve())
    with _SCHEMA_LOCK:
        if not force and resolved in _SCHEMA_READY:
            conn = _open_raw_connection(resolved)
            try:
                version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            finally:
                conn.close()
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema v{version} is newer than this application supports "
                    f"(v{SCHEMA_VERSION}). Please update Tinix FB Studio."
                )
            return version

        probe = _open_raw_connection(resolved)
        try:
            version = int(probe.execute("PRAGMA user_version").fetchone()[0])
        finally:
            probe.close()

        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema v{version} is newer than this application supports "
                f"(v{SCHEMA_VERSION}). Please update Tinix FB Studio."
            )

        if 0 < version < SCHEMA_VERSION:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_path = f"{resolved}.pre-schema-v{SCHEMA_VERSION}-{stamp}.sqlite"
            source = sqlite3.connect(resolved, timeout=30)
            backup = sqlite3.connect(backup_path, timeout=30)
            try:
                source.backup(backup)
                backup.commit()
                integrity = backup.execute("PRAGMA quick_check").fetchone()[0]
                if integrity != "ok":
                    raise RuntimeError(f"Pre-upgrade backup failed integrity check: {integrity}")
            finally:
                backup.close()
                source.close()
            logger.info(f"Database backup trước nâng schema: {backup_path}")

        if force or version < SCHEMA_VERSION:
            conn = _initialize_schema(resolved)
            try:
                version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            finally:
                conn.close()
        _SCHEMA_READY.add(resolved)
        return version


def _get_conn(db_path: str) -> sqlite3.Connection:
    """Open an application connection after versioned schema initialization."""
    resolved = str(Path(db_path).expanduser().resolve())
    initialize_database(resolved)
    return _open_raw_connection(resolved)


# ─── URL Lookup (Duplicate Check) ───────────────────────────────────────────

def normalize_page_url(url: str) -> str:
    """Normalize a Facebook page URL to a canonical form for comparison."""
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    # Handle profile.php?id=XXXXX format
    if path == "profile.php":
        qs = parse_qs(parsed.query)
        pid = qs.get("id", [None])[0]
        if pid:
            return f"https://www.facebook.com/profile.php?id={pid}"
        return url

    for suffix in ("posts", "photos", "videos", "about", "reviews", "events"):
        if path.endswith(suffix):
            path = path[:path.rfind(suffix)].strip("/")

    first_segment = path.split("/")[0] if path else ""
    if not first_segment:
        return url

    return f"https://www.facebook.com/{first_segment}"


def find_page_by_url(db_path: str, page_url: str) -> Optional[dict]:
    """Check if a URL already exists in the pages registry."""
    canonical = normalize_page_url(page_url)
    try:
        conn = _get_conn(db_path)
        row = conn.execute(
            "SELECT page_url, page_name, group_name, post_count, last_scraped "
            "FROM pages WHERE page_url = ?",
            (canonical,),
        ).fetchone()
        conn.close()
        if row:
            return {
                "page_url": row[0],
                "page_name": row[1],
                "group_name": row[2],
                "post_count": row[3],
                "last_scraped": row[4],
            }
    except Exception as e:
        logger.debug(f"URL lookup error: {str(e)[:100]}")
    return None


def get_page_post_ids(db_path: str, page_url: str) -> set:
    """Get all post IDs already scraped for a given page URL.
    Used by 'Scan New Posts' to know when to stop."""
    canonical = normalize_page_url(page_url)
    try:
        conn = _get_conn(db_path)
        rows = conn.execute(
            "SELECT post_id FROM posts WHERE page_url = ?", (canonical,)
        ).fetchall()
        post_ids = {r[0] for r in rows}
        if not post_ids:
            row = conn.execute(
                "SELECT page_name FROM pages WHERE page_url = ?", (canonical,)
            ).fetchone()
            if row:
                rows = conn.execute(
                    "SELECT post_id FROM posts WHERE page_name = ?", (row[0],)
                ).fetchall()
                post_ids = {r[0] for r in rows}
        conn.close()
        return post_ids
    except Exception as e:
        logger.debug(f"get_page_post_ids error: {str(e)[:100]}")
    return set()


def get_favorite_pages(db_path: str, active_only: bool = False) -> List[dict]:
    """Return saved favorite pages without exposing account credentials."""
    conn = _get_conn(db_path)
    try:
        sql = """
            SELECT f.id, f.page_url, f.page_name, f.account_id, f.scan_limit,
                   f.is_active, f.cursor_post_ids, f.last_attempt_at,
                   f.last_successful_scan_at, f.last_new_posts_count,
                   f.last_status, f.last_error, f.created_at, f.updated_at,
                   COALESCE(a.label, a.username, '') AS account_label
            FROM favorite_pages f
            LEFT JOIN fb_accounts a ON a.id = f.account_id
        """
        if active_only:
            sql += " WHERE f.is_active = 1"
        sql += " ORDER BY lower(COALESCE(NULLIF(f.page_name, ''), f.page_url))"
        rows = conn.execute(sql).fetchall()
        result = []
        for row in rows:
            try:
                cursor_ids = [str(value) for value in json.loads(row[6] or "[]") if str(value)]
            except (TypeError, ValueError):
                cursor_ids = []
            result.append({
                "id": row[0], "page_url": row[1], "page_name": row[2] or "",
                "account_id": row[3], "scan_limit": row[4], "is_active": row[5],
                "cursor_post_ids": cursor_ids, "last_attempt_at": row[7] or "",
                "last_successful_scan_at": row[8] or "", "last_new_posts_count": row[9] or 0,
                "last_status": row[10] or "Chưa quét", "last_error": row[11] or "",
                "created_at": row[12] or "", "updated_at": row[13] or "",
                "account_label": row[14] or "",
            })
        return result
    finally:
        conn.close()


def get_favorite_page(db_path: str, favorite_id: int) -> Optional[dict]:
    return next((item for item in get_favorite_pages(db_path) if item["id"] == favorite_id), None)


def save_favorite_page(
    db_path: str,
    page_url: str,
    page_name: str = "",
    account_id: Optional[int] = None,
    scan_limit: int = 100,
) -> int:
    """Add or update a favorite page while preserving its successful scan cursor."""
    canonical = normalize_page_url(page_url)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _get_conn(db_path)
    try:
        existing = conn.execute(
            "SELECT page_name FROM pages WHERE page_url = ?", (canonical,)
        ).fetchone()
        resolved_name = str(page_name or (existing[0] if existing else "")).strip()
        conn.execute("""
            INSERT INTO favorite_pages
                (page_url, page_name, account_id, scan_limit, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(page_url) DO UPDATE SET
                page_name = CASE WHEN excluded.page_name != '' THEN excluded.page_name ELSE favorite_pages.page_name END,
                account_id = excluded.account_id,
                scan_limit = excluded.scan_limit,
                is_active = 1,
                updated_at = excluded.updated_at
        """, (canonical, resolved_name, account_id, max(5, min(int(scan_limit), 2000)), now, now))
        row = conn.execute("SELECT id FROM favorite_pages WHERE page_url = ?", (canonical,)).fetchone()
        conn.commit()
        return int(row[0])
    finally:
        conn.close()


def delete_favorite_page(db_path: str, favorite_id: int) -> bool:
    conn = _get_conn(db_path)
    try:
        deleted = conn.execute("DELETE FROM favorite_pages WHERE id = ?", (favorite_id,)).rowcount
        conn.commit()
        return bool(deleted)
    finally:
        conn.close()


def reset_favorite_cursor(db_path: str, favorite_id: int) -> bool:
    conn = _get_conn(db_path)
    try:
        updated = conn.execute("""
            UPDATE favorite_pages
            SET cursor_post_ids = '[]', last_status = 'Đã đặt lại mốc',
                last_error = '', updated_at = ?
            WHERE id = ?
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), favorite_id)).rowcount
        conn.commit()
        return bool(updated)
    finally:
        conn.close()


def mark_favorite_scan_started(db_path: str, favorite_id: int) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _get_conn(db_path)
    try:
        conn.execute("""
            UPDATE favorite_pages
            SET last_attempt_at = ?, last_status = 'Đang quét', last_error = '', updated_at = ?
            WHERE id = ?
        """, (now, now, favorite_id))
        conn.commit()
    finally:
        conn.close()


def finish_favorite_scan(
    db_path: str,
    favorite_id: int,
    *,
    status: str,
    new_posts: int,
    error: str = "",
    page_name: str = "",
    cursor_post_ids: Optional[List[str]] = None,
    successful: bool = False,
) -> None:
    """Persist one scan result; advance the cursor only for a complete scan."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fields = [
        "last_status = ?", "last_new_posts_count = ?", "last_error = ?", "updated_at = ?"
    ]
    values: list = [status, int(new_posts), str(error or "")[:1000], now]
    if page_name:
        fields.append("page_name = ?")
        values.append(page_name)
    if successful:
        fields.extend(("last_successful_scan_at = ?", "cursor_post_ids = ?"))
        values.extend((now, json.dumps((cursor_post_ids or [])[:20], ensure_ascii=False)))
    values.append(favorite_id)
    conn = _get_conn(db_path)
    try:
        conn.execute(f"UPDATE favorite_pages SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def delete_page_data(db_path: str, page_url: str) -> int:
    """Delete all posts for a given page URL (for rescan). Returns deleted count."""
    canonical = normalize_page_url(page_url)
    try:
        conn = _get_conn(db_path)
        # Find the page_name from registry
        row = conn.execute(
            "SELECT page_name FROM pages WHERE page_url = ?", (canonical,)
        ).fetchone()

        deleted = 0
        if row:
            page_name = row[0]
            cursor = conn.execute(
                "DELETE FROM posts WHERE page_name = ?", (page_name,)
            )
            deleted = cursor.rowcount
            conn.execute(
                "UPDATE pages SET post_count = 0, last_scraped = '' WHERE page_url = ?",
                (canonical,),
            )
        else:
            # Fallback: try matching by page_url in posts table
            cursor = conn.execute(
                "DELETE FROM posts WHERE page_url = ?", (canonical,)
            )
            deleted = cursor.rowcount

        conn.commit()
        conn.close()
        if deleted > 0:
            logger.info(f"🗑 Đã xóa {deleted} bài cũ để quét lại")
        return deleted
    except Exception as e:
        logger.error(f"Lỗi xóa dữ liệu: {str(e)[:200]}")
        return 0


# ─── Group Management ────────────────────────────────────────────────────────

def get_all_groups(db_path: str) -> List[str]:
    """Get list of all unique group names."""
    try:
        conn = _get_conn(db_path)
        rows = conn.execute(
            "SELECT DISTINCT group_name FROM pages "
            "WHERE group_name != '' ORDER BY group_name"
        ).fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception:
        return []


# ─── Save / Query ────────────────────────────────────────────────────────────

def save_posts(
    db_path: str,
    page_name: str,
    page_url: str,
    posts: list,
    group_name: str = "",
    follower_count: int = 0,
) -> int:
    """
    Save scraped posts to SQLite database.
    Also updates the pages registry.
    """
    if not posts:
        return 0

    canonical = normalize_page_url(page_url) if page_url else ""
    conn = _get_conn(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saved = 0

    # Auto-preserve existing group: if no group specified, look up the page's
    # current group from DB so it doesn't get wiped on re-scrape
    if not group_name and canonical:
        try:
            row = conn.execute(
                "SELECT group_name FROM pages WHERE page_url = ?", (canonical,)
            ).fetchone()
            if row and row[0]:
                group_name = row[0]
                logger.debug(f"📂 Giữ group cũ: '{group_name}'")
        except Exception:
            pass

    try:
        for post in posts:
            pid = post.post_id if hasattr(post, 'post_id') else ""
            numeric_id = pid if pid and pid.isdigit() else ""
            post_url = f"https://www.facebook.com/{numeric_id}" if numeric_id else ""

            conn.execute("""
                INSERT INTO posts
                    (page_name, page_url, group_name, post_id, date, post_type,
                     engagement, comments, shares, caption, url, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(page_name, post_id) DO UPDATE SET
                    page_url = excluded.page_url,
                    group_name = excluded.group_name,
                    date = excluded.date,
                    post_type = excluded.post_type,
                    engagement = excluded.engagement,
                    comments = excluded.comments,
                    shares = excluded.shares,
                    caption = excluded.caption,
                    url = excluded.url,
                    scraped_at = excluded.scraped_at
            """, (
                page_name,
                canonical,
                group_name,
                pid,
                getattr(post, 'date', ''),
                getattr(post, 'post_type', 'Text'),
                getattr(post, 'engagement', 0),
                getattr(post, 'comments', 0),
                getattr(post, 'shares', 0),
                getattr(post, 'caption', ''),
                post_url,
                now,
            ))
            saved += 1

        total_posts = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE page_url = ?", (canonical,)
        ).fetchone()[0] if canonical else saved

        # Update pages registry
        if canonical:
            conn.execute("""
                INSERT INTO pages (page_url, page_name, group_name, post_count, last_scraped, created_at, follower_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(page_url) DO UPDATE SET
                    page_name = excluded.page_name,
                    group_name = CASE
                        WHEN excluded.group_name != '' THEN excluded.group_name
                        ELSE pages.group_name
                    END,
                    post_count = excluded.post_count,
                    last_scraped = excluded.last_scraped,
                    follower_count = CASE WHEN excluded.follower_count > 0 THEN excluded.follower_count ELSE pages.follower_count END
            """, (canonical, page_name, group_name, total_posts, now, now, follower_count))

        conn.commit()
        logger.info(f"💾 Đã lưu {saved} bài vào database")
    except Exception as e:
        logger.error(f"Lỗi lưu database: {str(e)[:200]}")
    finally:
        conn.close()

    return saved


def get_all_pages_full(db_path: str) -> List[dict]:
    """Get all pages with full schema for report export."""
    try:
        conn = _get_conn(db_path)
        col_names = [r[1] for r in conn.execute("PRAGMA table_info(pages)").fetchall()]
        cursor = conn.execute("SELECT * FROM pages ORDER BY last_scraped DESC")
        rows = cursor.fetchall()
        result = [dict(zip(col_names, row)) for row in rows]
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Pages report error: {str(e)[:200]}")
        return []


def get_posts_by_page(db_path: str, page_name: str) -> List[dict]:
    """Get all posts for a specific page."""
    try:
        conn = _get_conn(db_path)
        cursor = conn.execute("""
            SELECT post_id, date, post_type, engagement, comments,
                   views, caption, url, scraped_at
            FROM posts
            WHERE page_name = ?
            ORDER BY scraped_at DESC, date DESC
        """, (page_name,))
        posts = [
            {
                "post_id": row[0],
                "date": row[1],
                "post_type": row[2],
                "engagement": row[3],
                "comments": row[4],
                "views": row[5],
                "caption": row[6],
                "url": row[7],
                "scraped_at": row[8],
            }
            for row in cursor.fetchall()
        ]
        conn.close()
        return posts
    except Exception as e:
        logger.error(f"Lỗi đọc database: {str(e)[:200]}")
        return []


def get_db_stats(db_path: str) -> dict:
    """Get database statistics."""
    try:
        conn = _get_conn(db_path)
        total_posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        total_pages = conn.execute("SELECT COUNT(DISTINCT page_name) FROM posts").fetchone()[0]
        downloaded_posts = conn.execute("SELECT COUNT(*) FROM posts WHERE downloaded = 1").fetchone()[0]
        conn.close()
        return {
            "total_posts": total_posts,
            "total_pages": total_pages,
            "downloaded_posts": downloaded_posts,
        }
    except Exception:
        return {"total_posts": 0, "total_pages": 0, "downloaded_posts": 0}


# ─── Post Spy Queries ────────────────────────────────────────────────────────

def query_posts_for_spy(
    db_path: str,
    page_names: List[str],
    mode: str = "newest",
    limit: int = 0,
    post_type_filter: str = "Tất cả",
    download_status: str = "Tất cả",
) -> List[dict]:
    """Query posts for Post Spy Manager.

    Args:
        page_names: List of page_name values to filter by.
        mode: 'newest' (sort by date DESC) or 'top_engagement' (sort by engagement+comments+shares DESC).
        limit: Max number of posts to return. 0 = ALL.
        post_type_filter: 'Tất cả', 'Ảnh', 'Video', or 'Text'.
        download_status: 'Tất cả', 'Chưa tải', or 'Đã tải'.

    Returns:
        List of post dicts with group_name, page_name, post_id, date, post_type,
        engagement, comments, shares, caption, url, downloaded.
    """
    if not page_names:
        return []

    try:
        conn = _get_conn(db_path)
        placeholders = ",".join("?" for _ in page_names)
        where = f"page_name IN ({placeholders})"
        params: list = list(page_names)

        if post_type_filter and post_type_filter != "Tất cả":
            where += " AND post_type = ?"
            params.append(post_type_filter)

        if download_status == "Chưa tải":
            where += " AND downloaded = 0"
        elif download_status == "Đã tải":
            where += " AND downloaded = 1"

        if mode == "top_engagement":
            order = "(engagement + comments + shares) DESC"
        else:
            order = "date DESC, scraped_at DESC"

        limit_clause = f"LIMIT {int(limit)}" if limit > 0 else ""

        sql = f"""
            SELECT group_name, page_name, post_id, date, post_type,
                   engagement, comments, shares, caption, url, downloaded
            FROM posts
            WHERE {where}
            ORDER BY {order}
            {limit_clause}
        """

        cursor = conn.execute(sql, params)
        posts = [
            {
                "group_name": r[0], "page_name": r[1], "post_id": r[2],
                "date": r[3], "post_type": r[4], "engagement": r[5] or 0,
                "comments": r[6] or 0, "shares": r[7] or 0,
                "caption": r[8] or "", "url": r[9] or "",
                "downloaded": r[10] or 0,
            }
            for r in cursor.fetchall()
        ]
        conn.close()
        return posts
    except Exception as e:
        logger.error(f"Post spy query error: {str(e)[:200]}")
        return []


def mark_posts_downloaded(db_path: str, post_ids: List[str], folder_path: str = "") -> int:
    """Mark posts as downloaded. Returns count of updated rows."""
    if not post_ids:
        return 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _get_conn(db_path)
        updated = 0
        for pid in post_ids:
            cur = conn.execute("""
                UPDATE posts SET downloaded = 1, download_path = ?, downloaded_at = ?
                WHERE post_id = ?
            """, (folder_path, now, pid))
            updated += cur.rowcount
        conn.commit()
        conn.close()
        return updated
    except Exception as e:
        logger.error(f"Mark downloaded error: {str(e)[:200]}")
        return 0


def get_downloaded_posts_by_ids(db_path: str, post_ids: List[str]) -> Dict[str, dict]:
    """Return downloaded post rows keyed by post_id for pre-download checks."""
    clean_ids = [str(pid or "").strip() for pid in post_ids if str(pid or "").strip()]
    if not clean_ids:
        return {}
    try:
        conn = _get_conn(db_path)
        placeholders = ",".join("?" for _ in clean_ids)
        rows = conn.execute(f"""
            SELECT post_id, page_name, post_type, url, download_path, downloaded_at
            FROM posts
            WHERE downloaded = 1 AND post_id IN ({placeholders})
        """, clean_ids).fetchall()
        conn.close()
        return {
            r[0]: {
                "post_id": r[0],
                "page_name": r[1] or "",
                "post_type": r[2] or "",
                "url": r[3] or "",
                "download_path": r[4] or "",
                "downloaded_at": r[5] or "",
            }
            for r in rows
        }
    except Exception as e:
        logger.error(f"Get downloaded posts error: {str(e)[:200]}")
        return {}


def sync_downloaded_posts_from_folder(db_path: str, output_dir: str) -> int:
    """Mark scraped posts as downloaded when their post-id folder contains media."""
    if not output_dir or not os.path.isdir(output_dir):
        return 0
    try:
        post_folders = {}
        for entry in os.scandir(output_dir):
            if not entry.is_dir():
                continue
            post_id = entry.name.strip()
            if not post_id:
                continue
            try:
                has_media = any(
                    f.is_file() and Path(f.name).suffix.lower() in MEDIA_DOWNLOAD_EXTS
                    for f in os.scandir(entry.path)
                )
            except Exception:
                has_media = False
            if has_media:
                post_folders[post_id] = entry.path

        if not post_folders:
            return 0

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = _get_conn(db_path)
        updated = 0
        for post_id, folder_path in post_folders.items():
            cur = conn.execute("""
                UPDATE posts
                SET downloaded = 1,
                    download_path = CASE WHEN download_path = '' THEN ? ELSE download_path END,
                    downloaded_at = CASE WHEN downloaded_at = '' THEN ? ELSE downloaded_at END
                WHERE post_id = ? AND downloaded = 0
            """, (folder_path, now, post_id))
            updated += cur.rowcount
        conn.commit()
        conn.close()
        if updated:
            logger.info(f"Đã đồng bộ {updated} bài đã tải từ thư mục media.")
        return updated
    except Exception as e:
        logger.error(f"Sync downloaded posts error: {str(e)[:200]}")
        return 0


def bulk_delete_posts(db_path: str, post_ids: List[str]) -> dict:
    """Delete posts by post_id. Returns {deleted: int, paths: [str]}."""
    if not post_ids:
        return {"deleted": 0, "paths": []}
    try:
        conn = _get_conn(db_path)
        # Collect download paths first
        placeholders = ",".join("?" for _ in post_ids)
        cursor = conn.execute(
            f"SELECT download_path FROM posts WHERE post_id IN ({placeholders})",
            post_ids,
        )
        paths = [r[0] for r in cursor.fetchall() if r[0]]

        # Delete records
        cur = conn.execute(
            f"DELETE FROM posts WHERE post_id IN ({placeholders})",
            post_ids,
        )
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        logger.info(f"🗑 Đã xóa {deleted} bài viết từ database")
        return {"deleted": deleted, "paths": paths}
    except Exception as e:
        logger.error(f"Bulk delete error: {str(e)[:200]}")
        return {"deleted": 0, "paths": []}

# ─── Facebook Account CRUD ───────────────────────────────────────────────────

def add_account(db_path: str, **kwargs) -> int:
    """Add a new Facebook account. Returns new ID or -1 on error."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _get_conn(db_path)
        cur = conn.execute("""
            INSERT INTO fb_accounts
                (label, username, password, secret_2fa, email, email_pass, cookie, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            kwargs.get("label", ""),
            kwargs.get("username", ""),
            protect_secret(kwargs.get("password", "")),
            protect_secret(kwargs.get("secret_2fa", "")),
            kwargs.get("email", ""),
            protect_secret(kwargs.get("email_pass", "")),
            protect_secret(kwargs.get("cookie", "")),
            1,
            now,
        ))
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return new_id
    except Exception as e:
        logger.error(f"Lỗi thêm account: {str(e)[:100]}")
        return -1


def update_account(db_path: str, account_id: int, **kwargs) -> bool:
    """Update an existing account."""
    fields = []
    values = []
    for key in ("label", "username", "password", "secret_2fa", "email",
                "email_pass", "cookie", "is_active", "last_login"):
        if key in kwargs:
            fields.append(f"{key} = ?")
            value = kwargs[key]
            values.append(protect_secret(value) if key in ACCOUNT_SECRET_FIELDS else value)
    if not fields:
        return False
    values.append(account_id)
    try:
        conn = _get_conn(db_path)
        conn.execute(f"UPDATE fb_accounts SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Lỗi cập nhật account: {str(e)[:100]}")
        return False


def save_business_id(db_path: str, account_id: int, business_id: str) -> bool:
    """Persist the Meta Business Portfolio ID for an account."""
    try:
        conn = _get_conn(db_path)
        conn.execute(
            "UPDATE fb_accounts SET business_id = ? WHERE id = ?",
            (business_id.strip(), account_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"save_business_id error: {str(e)[:100]}")
        return False


def delete_account(db_path: str, account_id: int) -> bool:
    try:
        conn = _get_conn(db_path)
        conn.execute("DELETE FROM fb_accounts WHERE id = ?", (account_id,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_all_accounts(db_path: str) -> List[dict]:
    """Get all Facebook accounts and their dedicated Chrome profile."""
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT a.id, a.label, a.username, a.password, a.secret_2fa,
                   a.email, a.email_pass, a.cookie, a.is_active,
                   a.last_login, a.created_at, a.business_id,
                   (SELECT sa.profile_dir
                    FROM social_accounts sa
                    WHERE sa.platform = 'facebook' AND sa.legacy_fb_id = a.id
                    ORDER BY sa.id DESC LIMIT 1) AS profile_dir
            FROM fb_accounts a
            ORDER BY a.id
        """).fetchall()
        conn.close()
        return [
            {
                "id": r[0], "label": r[1], "username": r[2], "password": reveal_secret(r[3]),
                "secret_2fa": reveal_secret(r[4]), "email": r[5], "email_pass": reveal_secret(r[6]),
                "cookie": reveal_secret(r[7]), "is_active": r[8],
                "last_login": r[9], "created_at": r[10], "business_id": r[11] or "",
                "profile_dir": r[12] or "",
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Lỗi đọc accounts: {str(e)[:100]}")
        return []


def get_account(db_path: str, account_id: int) -> Optional[dict]:
    accounts = get_all_accounts(db_path)
    for a in accounts:
        if a["id"] == account_id:
            return a
    return None


def get_random_active_account(db_path: str) -> Optional[dict]:
    """Pick a random active account for scraping."""
    import random
    accounts = [a for a in get_all_accounts(db_path) if a["is_active"]]
    return random.choice(accounts) if accounts else None


def _social_account_from_row(r) -> dict:
    return {
        "id": r[0],
        "platform": r[1] or "facebook",
        "label": r[2] or "",
        "username": r[3] or "",
        "password": reveal_secret(r[4]),
        "secret_2fa": reveal_secret(r[5]),
        "email": r[6] or "",
        "email_pass": reveal_secret(r[7]),
        "cookie": reveal_secret(r[8]),
        "profile_dir": r[9] or "",
        "is_active": r[10],
        "sync_status": r[11] or "Chưa đồng bộ",
        "status_reason": r[12] or "",
        "uid": r[13] or "",
        "avatar_path": r[14] or "",
        "last_checked": r[15] or "",
        "last_synced": r[16] or "",
        "created_at": r[17] or "",
        "updated_at": r[18] or "",
        "notes": r[19] or "",
        "legacy_fb_id": r[20],
        "user_agent": r[21] or "",
        "display_name": r[22] or "" if len(r) > 22 else "",
        "page_count": r[23] if len(r) > 23 else 0,
    }


def get_social_accounts(
    db_path: str,
    platform: str = "",
    status: str = "",
    query: str = "",
) -> List[dict]:
    """Get multi-platform social accounts with optional filters."""
    try:
        conn = _get_conn(db_path)
        sql = """
            SELECT a.id, a.platform, a.label, a.username, a.password, a.secret_2fa,
                   a.email, a.email_pass, a.cookie, a.profile_dir,
                   a.is_active, a.sync_status, a.status_reason, a.uid, a.avatar_path,
                   a.last_checked, a.last_synced, a.created_at, a.updated_at,
                   a.notes, a.legacy_fb_id, a.user_agent,
                   a.display_name,
                   (SELECT COUNT(*) FROM managed_pages mp WHERE mp.account_id = a.id) as page_count
            FROM social_accounts a
            WHERE 1=1
        """
        params = []
        if platform:
            sql += " AND a.platform = ?"
            params.append(platform)
        if status:
            sql += " AND a.sync_status = ?"
            params.append(status)
        if query:
            like = f"%{query.lower()}%"
            sql += """ AND (
                lower(a.label) LIKE ? OR lower(a.username) LIKE ? OR
                lower(a.email) LIKE ? OR lower(a.uid) LIKE ?
            )"""
            params.extend([like, like, like, like])
        sql += " ORDER BY a.id"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [_social_account_from_row(r) for r in rows]
    except Exception as e:
        logger.error(f"get_social_accounts error: {str(e)[:100]}")
        return []


def get_social_account(db_path: str, account_id: int) -> Optional[dict]:
    accounts = get_social_accounts(db_path)
    for account in accounts:
        if account["id"] == account_id:
            return account
    return None


def rebase_missing_social_profile_paths(db_path: str, profile_root: str | Path) -> List[dict]:
    """Point stale social-account profile paths at matching folders in a new project root.

    Existing source paths are never changed. A row is updated only when its old path is
    missing and a directory with the same leaf name already exists below ``profile_root``.
    """
    root = Path(profile_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)

    conn = _get_conn(db_path)
    changes: List[dict] = []
    try:
        rows = conn.execute(
            "SELECT id, profile_dir FROM social_accounts WHERE profile_dir != '' ORDER BY id"
        ).fetchall()
        for account_id, stored_path in rows:
            source = Path(stored_path).expanduser()
            target = (root / source.name).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                continue
            if source.exists() or not target.is_dir() or source.resolve() == target:
                continue
            conn.execute(
                "UPDATE social_accounts SET profile_dir = ?, updated_at = ? WHERE id = ?",
                (str(target), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), account_id),
            )
            changes.append({"account_id": account_id, "from": str(source), "to": str(target)})
        conn.commit()
        return changes
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def add_social_account(db_path: str, **kwargs) -> int:
    """Add a multi-platform social account."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _get_conn(db_path)
        cur = conn.execute("""
            INSERT INTO social_accounts
                (platform, label, username, password, secret_2fa, email, email_pass,
                 cookie, profile_dir, is_active, sync_status, status_reason,
                 uid, avatar_path, last_checked, last_synced, created_at, updated_at,
                 notes, legacy_fb_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            kwargs.get("platform", "facebook"),
            kwargs.get("label", ""),
            kwargs.get("username", ""),
            protect_secret(kwargs.get("password", "")),
            protect_secret(kwargs.get("secret_2fa", "")),
            kwargs.get("email", ""),
            protect_secret(kwargs.get("email_pass", "")),
            protect_secret(kwargs.get("cookie", "")),
            kwargs.get("profile_dir", ""),
            kwargs.get("is_active", 0),
            kwargs.get("sync_status", "Chưa đồng bộ"),
            kwargs.get("status_reason", ""),
            kwargs.get("uid", ""),
            kwargs.get("avatar_path", ""),
            kwargs.get("last_checked", ""),
            kwargs.get("last_synced", ""),
            now,
            now,
            kwargs.get("notes", ""),
            kwargs.get("legacy_fb_id"),
        ))
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return new_id
    except Exception as e:
        logger.error(f"add_social_account error: {str(e)[:100]}")
        return -1


def update_social_account(db_path: str, account_id: int, **kwargs) -> bool:
    fields = []
    values = []
    allowed = (
        "platform", "label", "username", "password", "secret_2fa", "email",
        "email_pass", "cookie", "profile_dir", "is_active",
        "sync_status", "status_reason", "uid", "avatar_path", "last_checked",
        "last_synced", "notes", "legacy_fb_id", "user_agent", "display_name",
    )
    for key in allowed:
        if key in kwargs:
            fields.append(f"{key} = ?")
            value = kwargs[key]
            values.append(protect_secret(value) if key in ACCOUNT_SECRET_FIELDS else value)
    if not fields:
        return False
    fields.append("updated_at = ?")
    values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    values.append(account_id)
    try:
        conn = _get_conn(db_path)
        conn.execute(f"UPDATE social_accounts SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"update_social_account error: {str(e)[:100]}")
        return False


def delete_social_account(db_path: str, account_id: int) -> bool:
    try:
        conn = _get_conn(db_path)
        row = conn.execute(
            "SELECT platform, legacy_fb_id FROM social_accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        conn.execute("DELETE FROM social_targets WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM social_accounts WHERE id = ?", (account_id,))
        if row and row[0] == "facebook" and row[1]:
            conn.execute("DELETE FROM managed_pages WHERE account_id = ?", (row[1],))
            conn.execute("DELETE FROM fb_accounts WHERE id = ?", (row[1],))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"delete_social_account error: {str(e)[:100]}")
        return False


def sync_social_account_to_fb_account(db_path: str, account_id: int) -> int:
    """
    Mirror a Facebook social account into fb_accounts for legacy posting flows.
    Returns fb_accounts.id, or -1 if not applicable/error.
    """
    account = get_social_account(db_path, account_id)
    if not account or account.get("platform") != "facebook":
        return -1
    data = {
        "label": account.get("label", ""),
        "username": account.get("username") or account.get("uid") or f"facebook_{account_id}",
        "password": account.get("password", ""),
        "secret_2fa": account.get("secret_2fa", ""),
        "email": account.get("email", ""),
        "email_pass": account.get("email_pass", ""),
        "cookie": account.get("cookie", ""),
        "is_active": account.get("is_active", 0),
    }
    legacy_id = account.get("legacy_fb_id")
    if legacy_id:
        ok = update_account(db_path, legacy_id, **data)
        return legacy_id if ok else -1
    new_id = add_account(db_path, **data)
    if new_id > 0:
        update_social_account(db_path, account_id, legacy_fb_id=new_id)
    return new_id


def save_social_targets(db_path: str, account_id: int, targets: List[dict]) -> int:
    """Replace social targets for one account."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _get_conn(db_path)
        account = get_social_account(db_path, account_id)
        platform = account.get("platform", "") if account else ""
        group_lookup = {}
        rows = conn.execute("""
            SELECT platform, target_type, target_name, target_uid, target_url, group_name
            FROM social_targets
            WHERE group_name != ''
        """).fetchall()
        for row_platform, target_type, target_name, target_uid, target_url, group_name in rows:
            for key in (
                f"{row_platform}|uid:{str(target_uid or '').strip().lower()}",
                f"{row_platform}|url:{str(target_url or '').strip().lower().rstrip('/')}",
                f"{row_platform}|name:{str(target_name or '').strip().lower()}",
            ):
                if not key.endswith(":") and key not in group_lookup:
                    group_lookup[key] = group_name or ""
        conn.execute("DELETE FROM social_targets WHERE account_id = ?", (account_id,))
        saved = 0
        for target in targets:
            uid = target.get("target_uid") or target.get("page_id") or target.get("uid") or ""
            name = target.get("target_name") or target.get("page_name") or target.get("name") or ""
            url = target.get("target_url") or target.get("page_url") or target.get("url") or ""
            target_platform = target.get("platform", platform)
            group_name = target.get("group_name", "")
            if not group_name:
                for key in (
                    f"{target_platform}|uid:{str(uid or '').strip().lower()}",
                    f"{target_platform}|url:{str(url or '').strip().lower().rstrip('/')}",
                    f"{target_platform}|name:{str(name or '').strip().lower()}",
                ):
                    if key in group_lookup:
                        group_name = group_lookup[key]
                        break
            if not uid and not name:
                continue
            conn.execute("""
                INSERT OR REPLACE INTO social_targets
                    (account_id, platform, target_type, target_name, target_uid,
                     target_url, avatar_path, group_name, last_synced, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                account_id,
                target_platform,
                target.get("target_type", "channel" if platform != "facebook" else "fanpage"),
                name,
                uid,
                url,
                target.get("avatar_path", ""),
                group_name,
                now,
                now,
            ))
            saved += 1
        conn.commit()
        conn.close()
        return saved
    except Exception as e:
        logger.error(f"save_social_targets error: {str(e)[:100]}")
        return 0


def get_social_targets(
    db_path: str,
    account_id: Optional[int] = None,
    platform: str = "",
) -> List[dict]:
    try:
        conn = _get_conn(db_path)
        sql = """
            SELECT id, account_id, platform, target_type, target_name, target_uid,
                   target_url, avatar_path, group_name, last_synced, created_at
            FROM social_targets
            WHERE 1=1
        """
        params = []
        if account_id is not None:
            sql += " AND account_id = ?"
            params.append(account_id)
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        sql += " ORDER BY platform, target_name"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [
            {
                "id": r[0], "account_id": r[1], "platform": r[2],
                "target_type": r[3], "target_name": r[4], "target_uid": r[5],
                "target_url": r[6], "avatar_path": r[7], "group_name": r[8],
                "last_synced": r[9], "created_at": r[10],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_social_targets error: {str(e)[:100]}")
        return []


def get_social_target_groups(db_path: str, platform: str) -> List[dict]:
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT COALESCE(NULLIF(group_name, ''), 'Chưa phân loại') as grp,
                   COUNT(*) as target_count
            FROM social_targets
            WHERE platform = ?
            GROUP BY grp
            ORDER BY CASE WHEN grp = 'Chưa phân loại' THEN 0 ELSE 1 END, grp
        """, (platform,)).fetchall()
        conn.close()
        return [{"group_name": r[0], "target_count": r[1]} for r in rows]
    except Exception as e:
        logger.error(f"get_social_target_groups error: {str(e)[:100]}")
        return []


def move_social_targets_to_group(db_path: str, target_ids: List[int], group_name: str) -> int:
    if not target_ids:
        return 0
    try:
        clean_group = "" if group_name == "Chưa phân loại" else group_name.strip()
        conn = _get_conn(db_path)
        placeholders = ",".join("?" * len(target_ids))
        cur = conn.execute(
            f"UPDATE social_targets SET group_name = ? WHERE id IN ({placeholders})",
            [clean_group] + list(target_ids),
        )
        conn.commit()
        conn.close()
        return cur.rowcount
    except Exception as e:
        logger.error(f"move_social_targets_to_group error: {str(e)[:100]}")
        return 0


def delete_social_target_group(db_path: str, platform: str, group_name: str) -> int:
    if not group_name or group_name == "Chưa phân loại":
        return 0
    try:
        conn = _get_conn(db_path)
        cur = conn.execute(
            "UPDATE social_targets SET group_name = '' WHERE platform = ? AND group_name = ?",
            (platform, group_name),
        )
        conn.commit()
        conn.close()
        return cur.rowcount
    except Exception as e:
        logger.error(f"delete_social_target_group error: {str(e)[:100]}")
        return 0


def sync_social_target_duplicate_groups(db_path: str, platform: str) -> int:
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT id, target_name, target_uid, target_url, group_name
            FROM social_targets
            WHERE platform = ?
        """, (platform,)).fetchall()
        group_lookup = {}
        for _rid, name, uid, url, group_name in rows:
            if not group_name:
                continue
            for key in (
                f"uid:{str(uid or '').strip().lower()}",
                f"url:{str(url or '').strip().lower().rstrip('/')}",
                f"name:{str(name or '').strip().lower()}",
            ):
                if key not in ("uid:", "url:", "name:"):
                    group_lookup.setdefault(key, group_name)
        changed = 0
        for rid, name, uid, url, group_name in rows:
            if group_name:
                continue
            keys = (
                f"uid:{str(uid or '').strip().lower()}",
                f"url:{str(url or '').strip().lower().rstrip('/')}",
                f"name:{str(name or '').strip().lower()}",
            )
            match = next((group_lookup[key] for key in keys if key in group_lookup), None)
            if not match:
                continue
            conn.execute("UPDATE social_targets SET group_name = ? WHERE id = ?", (match, rid))
            changed += 1
        conn.commit()
        conn.close()
        return changed
    except Exception as e:
        logger.error(f"sync_social_target_duplicate_groups error: {str(e)[:100]}")
        return 0


# ─── Managed Pages CRUD ──────────────────────────────────────────────────────

def get_managed_pages(db_path: str, account_id: int) -> List[dict]:
    """Return pages that a specific account manages, with group and avatar info."""
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT mp.id, mp.page_name, mp.page_url, mp.page_id, mp.scanned_at,
                   COALESCE(pg.group_name, 'Chưa phân loại') as group_name,
                   mp.avatar_path, mp.group_id, mp.last_synced, mp.reels_asset_id
            FROM managed_pages mp
            LEFT JOIN page_groups pg ON mp.group_id = pg.group_id
            WHERE mp.account_id = ?
            ORDER BY group_name, mp.page_name
        """, (account_id,)).fetchall()
        conn.close()
        return [
            {"id": r[0], "page_name": r[1], "page_url": r[2],
             "page_id": r[3], "scanned_at": r[4], "group_name": r[5],
             "avatar_path": r[6] or "", "group_id": r[7] or 1, "last_synced": r[8] or "",
             "reels_asset_id": r[9] or ""}
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_managed_pages error: {str(e)[:100]}")
        return []


def get_all_managed_pages(db_path: str) -> List[dict]:
    """Return all managed pages across all accounts, with group and account info."""
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT mp.id, mp.page_name, mp.page_url, mp.page_id, mp.scanned_at,
                   COALESCE(pg.group_name, 'Chưa phân loại') as group_name,
                   mp.avatar_path, mp.group_id, mp.last_synced, mp.reels_asset_id,
                   COALESCE(NULLIF(fa.label,''), fa.username, '') as account_label,
                   mp.account_id
            FROM managed_pages mp
            LEFT JOIN page_groups pg ON mp.group_id = pg.group_id
            LEFT JOIN fb_accounts fa ON mp.account_id = fa.id
            ORDER BY group_name, mp.page_name
        """).fetchall()
        conn.close()
        return [
            {"id": r[0], "page_name": r[1], "page_url": r[2],
             "page_id": r[3], "scanned_at": r[4], "group_name": r[5],
             "avatar_path": r[6] or "", "group_id": r[7] or 1, "last_synced": r[8] or "",
             "reels_asset_id": r[9] or "", "account_label": r[10] or "", "account_id": r[11]}
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_all_managed_pages error: {str(e)[:100]}")
        return []


def get_managed_page_groups(db_path: str, account_id: int) -> List[str]:
    """Return group names that contain at least one page for this account."""
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT DISTINCT pg.group_name
            FROM page_groups pg
            INNER JOIN managed_pages mp ON mp.group_id = pg.group_id
            WHERE mp.account_id = ? AND pg.group_id != 1
            ORDER BY pg.group_name
        """, (account_id,)).fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        logger.error(f"get_managed_page_groups error: {str(e)[:100]}")
        return []


def update_managed_page_group(db_path: str, page_ids: List[int], group_name: str) -> int:
    """Move pages (by row id) into a named group. Creates the group if needed."""
    if not page_ids:
        return 0
    try:
        conn = _get_conn(db_path)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not group_name:
            group_id = 1
            group_name = "Chưa phân loại"
        else:
            row = conn.execute(
                "SELECT group_id FROM page_groups WHERE group_name = ?", (group_name,)
            ).fetchone()
            if row:
                group_id = row[0]
            else:
                cur = conn.execute(
                    "INSERT INTO page_groups (group_name, created_at) VALUES (?, ?)",
                    (group_name, now),
                )
                group_id = cur.lastrowid
        placeholders = ",".join("?" * len(page_ids))
        cur = conn.execute(
            f"UPDATE managed_pages SET group_id = ?, group_name = ? WHERE id IN ({placeholders})",
            [group_id, group_name] + page_ids,
        )
        conn.commit()
        conn.close()
        return cur.rowcount
    except Exception as e:
        logger.error(f"update_managed_page_group error: {str(e)[:100]}")
        return 0


def save_managed_pages(db_path: str, account_id: int, pages: List[dict]) -> int:
    """
    Upsert list of managed pages for an account.
    Each item: {page_name, page_url, page_id, group_name?, avatar_url?}
    Returns number of rows inserted/updated.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _get_conn(db_path)
        group_lookup = {}
        rows = conn.execute("""
            SELECT page_id, page_url, page_name, group_id, group_name
            FROM managed_pages
            WHERE group_id IS NOT NULL AND group_id != 1
        """).fetchall()
        for page_id, page_url, page_name, group_id, group_name in rows:
            for key in (
                f"id:{str(page_id or '').strip().lower()}",
                f"url:{str(page_url or '').strip().lower().rstrip('/')}",
                f"name:{str(page_name or '').strip().lower()}",
            ):
                if key not in ("id:", "url:", "name:") and key not in group_lookup:
                    group_lookup[key] = (group_id, group_name or "")
        count = 0
        for p in pages:
            page_id = p.get("page_id", "").strip() or p.get("page_url", "").strip()
            if not page_id:
                continue
            group_id = int(p.get("group_id") or 0)
            group_name = p.get("group_name", "")
            if group_id <= 1:
                keys = (
                    f"id:{str(page_id or '').strip().lower()}",
                    f"url:{str(p.get('page_url') or '').strip().lower().rstrip('/')}",
                    f"name:{str(p.get('page_name') or '').strip().lower()}",
                )
                for key in keys:
                    if key in group_lookup:
                        group_id, group_name = group_lookup[key]
                        break
            if group_id <= 1:
                group_id = 1
                group_name = "Chưa phân loại"
            conn.execute("""
                INSERT INTO managed_pages
                    (account_id, page_name, page_url, page_id, scanned_at, last_synced, group_name, group_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, page_id) DO UPDATE SET
                    page_name  = excluded.page_name,
                    page_url   = excluded.page_url,
                    scanned_at = excluded.scanned_at,
                    last_synced = excluded.last_synced,
                    group_name = CASE
                        WHEN managed_pages.group_id IS NOT NULL AND managed_pages.group_id != 1
                        THEN managed_pages.group_name
                        ELSE excluded.group_name
                    END,
                    group_id = CASE
                        WHEN managed_pages.group_id IS NOT NULL AND managed_pages.group_id != 1
                        THEN managed_pages.group_id
                        ELSE excluded.group_id
                    END
            """, (account_id, p.get("page_name", ""), p.get("page_url", ""),
                  page_id, now, now, group_name, group_id))
            count += 1
        conn.commit()
        conn.close()
        return count
    except Exception as e:
        logger.error(f"save_managed_pages error: {str(e)[:100]}")
        return 0


def delete_managed_pages(db_path: str, account_id: int) -> int:
    """Remove all managed pages for an account (before re-scan)."""
    try:
        conn = _get_conn(db_path)
        cur = conn.execute("DELETE FROM managed_pages WHERE account_id = ?", (account_id,))
        conn.commit()
        conn.close()
        return cur.rowcount
    except Exception as e:
        logger.error(f"delete_managed_pages error: {str(e)[:100]}")
        return 0


def sync_managed_page_duplicate_groups(db_path: str) -> int:
    """Propagate a non-default group to duplicate managed-page rows."""
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT id, page_id, page_url, page_name, group_id, group_name
            FROM managed_pages
        """).fetchall()
        group_lookup = {}
        for _rid, page_id, page_url, page_name, group_id, group_name in rows:
            if not group_id or group_id == 1:
                continue
            for key in (
                f"id:{str(page_id or '').strip().lower()}",
                f"url:{str(page_url or '').strip().lower().rstrip('/')}",
                f"name:{str(page_name or '').strip().lower()}",
            ):
                if key not in ("id:", "url:", "name:"):
                    group_lookup.setdefault(key, (group_id, group_name or ""))
        changed = 0
        for rid, page_id, page_url, page_name, group_id, _group_name in rows:
            if group_id and group_id != 1:
                continue
            keys = (
                f"id:{str(page_id or '').strip().lower()}",
                f"url:{str(page_url or '').strip().lower().rstrip('/')}",
                f"name:{str(page_name or '').strip().lower()}",
            )
            match = next((group_lookup[key] for key in keys if key in group_lookup), None)
            if not match:
                continue
            new_group_id, new_group_name = match
            conn.execute(
                "UPDATE managed_pages SET group_id = ?, group_name = ? WHERE id = ?",
                (new_group_id, new_group_name, rid),
            )
            changed += 1
        conn.commit()
        conn.close()
        return changed
    except Exception as e:
        logger.error(f"sync_managed_page_duplicate_groups error: {str(e)[:100]}")
        return 0


def delete_managed_page(db_path: str, page_row_id: int) -> bool:
    """Remove a single managed page by its DB row id."""
    try:
        conn = _get_conn(db_path)
        conn.execute("DELETE FROM managed_pages WHERE id = ?", (page_row_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"delete_managed_page error: {str(e)[:100]}")
        return False


# ─── Page Groups CRUD ────────────────────────────────────────────────────────

def get_page_groups(db_path: str) -> List[dict]:
    """Return all page groups with their page count."""
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT pg.group_id, pg.group_name, pg.created_at,
                   COUNT(mp.id) as page_count
            FROM page_groups pg
            LEFT JOIN managed_pages mp ON mp.group_id = pg.group_id
            GROUP BY pg.group_id
            ORDER BY pg.group_id
        """).fetchall()
        conn.close()
        return [
            {"group_id": r[0], "group_name": r[1],
             "created_at": r[2], "page_count": r[3]}
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_page_groups error: {str(e)[:100]}")
        return []


def add_page_group(db_path: str, group_name: str) -> int:
    """Create a new page group. Returns new group_id, or -1 on error."""
    group_name = group_name.strip()
    if not group_name:
        return -1
    try:
        conn = _get_conn(db_path)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            "INSERT INTO page_groups (group_name, created_at) VALUES (?, ?)",
            (group_name, now),
        )
        conn.commit()
        gid = cur.lastrowid
        conn.close()
        return gid
    except Exception as e:
        logger.error(f"add_page_group error: {str(e)[:100]}")
        return -1


def delete_page_group(db_path: str, group_id: int) -> bool:
    """
    Delete a page group (cannot delete the Uncategorized group, id=1).
    Pages in the deleted group are moved to Uncategorized (group_id=1).
    """
    if group_id == 1:
        return False
    try:
        conn = _get_conn(db_path)
        conn.execute(
            "UPDATE managed_pages SET group_id = 1, group_name = 'Chưa phân loại' "
            "WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM page_groups WHERE group_id = ?", (group_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"delete_page_group error: {str(e)[:100]}")
        return False


def move_pages_to_group(db_path: str, page_row_ids: List[int], group_id: int) -> int:
    """Move pages (by DB row id) to a different group. Returns updated count."""
    if not page_row_ids:
        return 0
    try:
        conn = _get_conn(db_path)
        grp = conn.execute(
            "SELECT group_name FROM page_groups WHERE group_id = ?", (group_id,)
        ).fetchone()
        if not grp:
            conn.close()
            return 0
        group_name = grp[0]
        placeholders = ",".join("?" * len(page_row_ids))
        cur = conn.execute(
            f"UPDATE managed_pages SET group_id = ?, group_name = ? WHERE id IN ({placeholders})",
            [group_id, group_name] + list(page_row_ids),
        )
        conn.commit()
        conn.close()
        return cur.rowcount
    except Exception as e:
        logger.error(f"move_pages_to_group error: {str(e)[:100]}")
        return 0


def update_page_avatar(db_path: str, fb_page_id: str, avatar_path: str) -> bool:
    """Set local avatar_path for a managed page identified by its Facebook page_id."""
    try:
        conn = _get_conn(db_path)
        conn.execute(
            "UPDATE managed_pages SET avatar_path = ? WHERE page_id = ?",
            (avatar_path, fb_page_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"update_page_avatar error: {str(e)[:100]}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SOCIAL POST — content_pool & post_history
# ═══════════════════════════════════════════════════════════════════════════

def save_content_pool(db_path: str, items: List[dict]) -> int:
    """
    Upsert content_pool entries.
    Each item: {folder_name, folder_path, caption}
    Returns number of saved items.
    """
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    saved = 0
    try:
        conn = _get_conn(db_path)
        for item in items:
            conn.execute("""
                INSERT INTO content_pool
                    (folder_name, folder_path, caption, title, keywords, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(folder_name) DO UPDATE SET
                    folder_path = excluded.folder_path,
                    caption = excluded.caption,
                    title = excluded.title,
                    keywords = excluded.keywords,
                    created_at = excluded.created_at
            """, (
                item["folder_name"],
                item["folder_path"],
                item.get("caption", ""),
                item.get("title", ""),
                item.get("keywords", ""),
                now,
            ))
            saved += 1
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"save_content_pool error: {str(e)[:200]}")
    return saved


def get_all_content_pool(db_path: str) -> List[dict]:
    """Get all content_pool entries with posting status summary."""
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT c.content_id, c.folder_name, c.folder_path, c.caption,
                   c.title, c.keywords, c.created_at
            FROM content_pool c
            ORDER BY c.created_at DESC
        """).fetchall()

        result = []
        for r in rows:
            cid = r[0]
            # Get posting history for this content
            history = conn.execute("""
                SELECT page_name, status FROM post_history WHERE content_id = ?
            """, (cid,)).fetchall()
            status_parts = []
            for h in history:
                icon = "✅" if h[1] == "Success" else ("🕒" if h[1] in ("Pending", "Scheduled") else "❌")
                status_parts.append(f"{h[0]}: {icon}")
            status_str = " | ".join(status_parts) if status_parts else "—"

            result.append({
                "content_id": cid,
                "folder_name": r[1],
                "folder_path": r[2],
                "caption": r[3],
                "title": r[4],
                "keywords": r[5],
                "created_at": r[6],
                "post_status": status_str,
            })
        conn.close()
        return result
    except Exception as e:
        logger.error(f"get_all_content_pool error: {str(e)[:200]}")
        return []


def delete_content_pool(db_path: str, content_ids: List[int]) -> int:
    """Delete content_pool entries by IDs."""
    try:
        conn = _get_conn(db_path)
        placeholders = ",".join("?" * len(content_ids))
        conn.execute(f"DELETE FROM post_history WHERE content_id IN ({placeholders})", content_ids)
        cur = conn.execute(f"DELETE FROM content_pool WHERE content_id IN ({placeholders})", content_ids)
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        return deleted
    except Exception as e:
        logger.error(f"delete_content_pool error: {str(e)[:200]}")
        return 0


def update_content_caption(db_path: str, content_id: int, new_caption: str) -> bool:
    """Update caption for a single content_pool entry. Returns True on success."""
    try:
        conn = _get_conn(db_path)
        conn.execute(
            "UPDATE content_pool SET caption = ? WHERE content_id = ?",
            (new_caption, content_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"update_content_caption error: {str(e)[:200]}")
        return False


def bulk_insert_schedule(db_path: str, records: List[dict]) -> int:
    """
    Insert multiple post_history records in a single transaction.
    Each record: {content_id, account_id, page_name, scheduled_time, status}
    Returns number of inserted records.
    """
    if not records:
        return 0
    try:
        conn = _get_conn(db_path)
        conn.execute("BEGIN TRANSACTION")
        count = 0
        for rec in records:
            conn.execute("""
                INSERT INTO post_history
                    (content_id, account_id, page_name, scheduled_time, status, scheduling_method)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                rec["content_id"],
                rec.get("account_id", ""),
                rec["page_name"],
                rec["scheduled_time"],
                rec.get("status", "Pending"),
                rec.get("scheduling_method", "App"),
            ))
            count += 1
        conn.commit()
        conn.close()
        return count
    except Exception as e:
        logger.error(f"bulk_insert_schedule error: {str(e)[:200]}")
        return 0


def check_duplicate_schedule(
    db_path: str, content_id: int, page_name: str, scheduled_time: str,
) -> bool:
    """Check if this content is already scheduled for this page at this time."""
    try:
        conn = _get_conn(db_path)
        row = conn.execute("""
            SELECT COUNT(*) FROM post_history
            WHERE content_id = ? AND page_name = ? AND scheduled_time = ?
              AND status IN ('Pending', 'Scheduled', 'Success')
        """, (content_id, page_name, scheduled_time)).fetchone()
        conn.close()
        return row[0] > 0 if row else False
    except Exception:
        return False


def bulk_insert_video_jobs(db_path: str, records: List[dict]) -> int:
    """Insert multi-platform video post jobs, skipping duplicate rows."""
    if not records:
        return 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _get_conn(db_path)
        conn.execute("BEGIN TRANSACTION")
        inserted = 0
        for rec in records:
            target_key = rec.get("target_uid", "") or rec.get("target_name", "")
            exists = conn.execute("""
                SELECT 1 FROM video_post_jobs
                WHERE content_id = ? AND platform = ? AND target_uid = ?
                  AND scheduled_time = ? AND status IN
                      ('Pending', 'Running', 'Scheduled', 'Success', 'Unsupported')
                LIMIT 1
            """, (
                rec["content_id"],
                rec.get("platform", ""),
                target_key,
                rec.get("scheduled_time", ""),
            )).fetchone()
            if exists:
                continue
            cur = conn.execute("""
                INSERT OR IGNORE INTO video_post_jobs
                    (content_id, platform, account_id, target_id, target_name, target_uid,
                     scheduled_time, mode, status, error_log, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rec["content_id"],
                rec.get("platform", ""),
                int(rec.get("account_id") or 0),
                int(rec.get("target_id") or 0),
                rec.get("target_name", ""),
                target_key,
                rec.get("scheduled_time", ""),
                rec.get("mode", "schedule"),
                rec.get("status", "Pending"),
                rec.get("error_log", ""),
                now,
                now,
            ))
            inserted += cur.rowcount
        conn.commit()
        conn.close()
        return inserted
    except Exception as e:
        logger.error(f"bulk_insert_video_jobs error: {str(e)[:200]}")
        return 0


def get_video_post_jobs_filtered(
    db_path: str,
    platform: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    account_id: Optional[int] = None,
) -> List[dict]:
    """Fetch video post jobs joined with content and social account info."""
    try:
        conn = _get_conn(db_path)
        sql = """
            SELECT j.job_id, j.content_id, j.platform, j.account_id, j.target_id,
                   j.target_name, j.target_uid, j.scheduled_time, j.mode, j.status,
                   j.error_log, j.created_at, j.updated_at,
                   c.folder_name, c.folder_path, c.caption, c.title, c.keywords,
                   COALESCE(NULLIF(sa.label,''), NULLIF(sa.username,''), NULLIF(sa.email,''), '') as account_label,
                   sa.profile_dir
            FROM video_post_jobs j
            JOIN content_pool c ON c.content_id = j.content_id
            LEFT JOIN social_accounts sa ON sa.id = j.account_id
            WHERE 1=1
        """
        params = []
        if platform:
            sql += " AND j.platform = ?"
            params.append(platform)
        if status:
            sql += " AND j.status = ?"
            params.append(status)
        if date_from:
            sql += " AND j.scheduled_time >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND j.scheduled_time <= ?"
            params.append(date_to + " 23:59:59")
        if account_id is not None:
            sql += " AND j.account_id = ?"
            params.append(account_id)
        sql += " ORDER BY j.scheduled_time, j.job_id"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [
            {
                "job_id": r[0], "content_id": r[1], "platform": r[2],
                "account_id": r[3], "target_id": r[4], "target_name": r[5],
                "target_uid": r[6], "scheduled_time": r[7], "mode": r[8],
                "status": r[9], "error_log": r[10], "created_at": r[11],
                "updated_at": r[12], "folder_name": r[13], "folder_path": r[14],
                "caption": r[15], "title": r[16], "keywords": r[17],
                "account_label": r[18], "profile_dir": r[19],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_video_post_jobs_filtered error: {str(e)[:200]}")
        return []


def get_video_post_jobs_by_ids(db_path: str, job_ids: List[int]) -> List[dict]:
    if not job_ids:
        return []
    try:
        conn = _get_conn(db_path)
        placeholders = ",".join("?" * len(job_ids))
        rows = conn.execute(f"""
            SELECT j.job_id, j.content_id, j.platform, j.account_id, j.target_id,
                   j.target_name, j.target_uid, j.scheduled_time, j.mode, j.status,
                   j.error_log, j.created_at, j.updated_at,
                   c.folder_name, c.folder_path, c.caption, c.title, c.keywords,
                   COALESCE(NULLIF(sa.label,''), NULLIF(sa.username,''), NULLIF(sa.email,''), '') as account_label,
                   sa.profile_dir
            FROM video_post_jobs j
            JOIN content_pool c ON c.content_id = j.content_id
            LEFT JOIN social_accounts sa ON sa.id = j.account_id
            WHERE j.job_id IN ({placeholders})
            ORDER BY j.scheduled_time, j.job_id
        """, job_ids).fetchall()
        conn.close()
        return [
            {
                "job_id": r[0], "content_id": r[1], "platform": r[2],
                "account_id": r[3], "target_id": r[4], "target_name": r[5],
                "target_uid": r[6], "scheduled_time": r[7], "mode": r[8],
                "status": r[9], "error_log": r[10], "created_at": r[11],
                "updated_at": r[12], "folder_name": r[13], "folder_path": r[14],
                "caption": r[15], "title": r[16], "keywords": r[17],
                "account_label": r[18], "profile_dir": r[19],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_video_post_jobs_by_ids error: {str(e)[:200]}")
        return []


def get_video_post_jobs_for_records(db_path: str, records: List[dict]) -> List[dict]:
    """Fetch persisted video jobs matching generated record keys."""
    if not records:
        return []
    found_ids = []
    try:
        conn = _get_conn(db_path)
        for rec in records:
            row = conn.execute("""
                SELECT job_id FROM video_post_jobs
                WHERE content_id = ? AND platform = ? AND account_id = ?
                  AND target_uid = ? AND scheduled_time = ?
            """, (
                rec["content_id"],
                rec.get("platform", ""),
                int(rec.get("account_id") or 0),
                rec.get("target_uid", "") or rec.get("target_name", ""),
                rec.get("scheduled_time", ""),
            )).fetchone()
            if row:
                found_ids.append(row[0])
        conn.close()
    except Exception as e:
        logger.error(f"get_video_post_jobs_for_records error: {str(e)[:200]}")
        return []
    return get_video_post_jobs_by_ids(db_path, found_ids)


def update_video_post_job_status(
    db_path: str, job_id: int, status: str, error_log: str = ""
) -> bool:
    try:
        conn = _get_conn(db_path)
        conn.execute("""
            UPDATE video_post_jobs
            SET status = ?, error_log = ?, updated_at = ?
            WHERE job_id = ?
        """, (status, error_log, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"update_video_post_job_status error: {str(e)[:200]}")
        return False


def update_video_post_job_time(db_path: str, job_id: int, scheduled_time: str) -> bool:
    try:
        conn = _get_conn(db_path)
        conn.execute("""
            UPDATE video_post_jobs
            SET scheduled_time = ?, status = 'Pending', error_log = '', updated_at = ?
            WHERE job_id = ?
        """, (scheduled_time, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_id))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"update_video_post_job_time error: {str(e)[:200]}")
        return False


def delete_video_post_jobs(db_path: str, job_ids: List[int]) -> int:
    if not job_ids:
        return 0
    try:
        conn = _get_conn(db_path)
        placeholders = ",".join("?" * len(job_ids))
        cur = conn.execute(f"DELETE FROM video_post_jobs WHERE job_id IN ({placeholders})", job_ids)
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        return deleted
    except Exception as e:
        logger.error(f"delete_video_post_jobs error: {str(e)[:200]}")
        return 0


def retry_video_post_jobs(db_path: str, job_ids: List[int]) -> int:
    if not job_ids:
        return 0
    try:
        conn = _get_conn(db_path)
        placeholders = ",".join("?" * len(job_ids))
        cur = conn.execute(f"""
            UPDATE video_post_jobs
            SET status = 'Pending', error_log = '', updated_at = ?
            WHERE job_id IN ({placeholders}) AND status IN ('Failed', 'Unsupported', 'Skipped')
        """, [datetime.now().strftime("%Y-%m-%d %H:%M:%S")] + job_ids)
        conn.commit()
        changed = cur.rowcount
        conn.close()
        return changed
    except Exception as e:
        logger.error(f"retry_video_post_jobs error: {str(e)[:200]}")
        return 0


def reset_pending_schedule(db_path: str, page_name: str = "") -> int:
    """
    Delete all 'Pending' records from post_history.
    If page_name given, only delete for that page.
    Returns number of deleted records.
    """
    try:
        conn = _get_conn(db_path)
        if page_name:
            cur = conn.execute(
                "DELETE FROM post_history WHERE status = 'Pending' AND page_name = ?",
                (page_name,),
            )
        else:
            cur = conn.execute("DELETE FROM post_history WHERE status = 'Pending'")
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        return deleted
    except Exception as e:
        logger.error(f"reset_pending_schedule error: {str(e)[:200]}")
        return 0


# ─── V15.0: Advanced Schedule History Functions ─────────────────────────────

def update_history_status_with_error(
    db_path: str, history_id: int, status: str, error_log: str = ""
) -> bool:
    """Update post_history status and optionally record an error message."""
    from core.job_states import POST_JOB_STATUSES

    if status not in POST_JOB_STATUSES:
        raise ValueError(f"Unsupported post job status: {status}")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _get_conn(db_path)
        conn.execute(
            "UPDATE post_history SET status = ?, error_log = ?, last_retry_at = ? WHERE history_id = ?",
            (status, error_log, now if error_log else "", history_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"update_history_status_with_error: {str(e)[:100]}")
        return False


def get_missed_app_posts(db_path: str) -> List[dict]:
    """
    Return Pending App-mode posts whose scheduled_time has already passed.
    These are posts the app was supposed to handle but missed (e.g. app was closed).
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT h.history_id, h.content_id, h.page_name, h.scheduled_time,
                   h.account_id, h.scheduling_method,
                   c.folder_name, c.folder_path, c.caption
            FROM post_history h
            JOIN content_pool c ON h.content_id = c.content_id
            WHERE h.status = 'Pending'
              AND h.scheduling_method = 'App'
              AND h.scheduled_time < ?
            ORDER BY h.scheduled_time
        """, (now,)).fetchall()
        conn.close()
        return [
            {
                "history_id": r[0], "content_id": r[1], "page_name": r[2],
                "scheduled_time": r[3], "account_id": r[4], "scheduling_method": r[5],
                "folder_name": r[6], "folder_path": r[7], "caption": r[8],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_missed_app_posts error: {str(e)[:200]}")
        return []


def get_schedule_history_filtered(
    db_path: str,
    page_name: str = "",
    date_from: str = "",
    date_to: str = "",
    status: str = "",
    scheduling_method: str = "",
) -> List[dict]:
    """Fetch post_history records with optional filters, joined with content info."""
    try:
        conn = _get_conn(db_path)
        sql = """
            SELECT h.history_id, h.content_id, h.page_name, h.scheduled_time,
                   h.status, h.scheduling_method, h.error_log, h.is_duplicate,
                   h.last_retry_at, h.account_id,
                   c.folder_name, c.folder_path, c.caption
            FROM post_history h
            JOIN content_pool c ON h.content_id = c.content_id
            WHERE 1=1
        """
        params: list = []
        if page_name:
            sql += " AND h.page_name = ?"
            params.append(page_name)
        if date_from:
            sql += " AND h.scheduled_time >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND h.scheduled_time <= ?"
            params.append(date_to + " 23:59:59")
        if status:
            sql += " AND h.status = ?"
            params.append(status)
        if scheduling_method:
            sql += " AND h.scheduling_method = ?"
            params.append(scheduling_method)
        sql += " ORDER BY h.scheduled_time DESC"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [
            {
                "history_id": r[0], "content_id": r[1], "page_name": r[2],
                "scheduled_time": r[3], "status": r[4], "scheduling_method": r[5],
                "error_log": r[6] or "", "is_duplicate": bool(r[7]),
                "last_retry_at": r[8] or "", "account_id": r[9],
                "folder_name": r[10], "folder_path": r[11], "caption": r[12],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_schedule_history_filtered error: {str(e)[:200]}")
        return []


def duplicate_history_record(db_path: str, history_id: int, new_scheduled_time: str) -> int:
    """
    Clone a post_history record with a new scheduled time and status='Pending'.
    Returns new history_id, or -1 on error.
    """
    try:
        conn = _get_conn(db_path)
        row = conn.execute(
            "SELECT content_id, account_id, page_name, scheduling_method "
            "FROM post_history WHERE history_id = ?",
            (history_id,),
        ).fetchone()
        if not row:
            conn.close()
            return -1
        cur = conn.execute("""
            INSERT INTO post_history
                (content_id, account_id, page_name, scheduled_time, status,
                 scheduling_method, is_duplicate, error_log, last_retry_at)
            VALUES (?, ?, ?, ?, 'Pending', ?, 1, '', '')
        """, (row[0], row[1], row[2], new_scheduled_time, row[3]))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()
        return new_id
    except Exception as e:
        logger.error(f"duplicate_history_record error: {str(e)[:200]}")
        return -1


def update_history_scheduled_time(db_path: str, history_id: int, new_time: str) -> bool:
    """Update scheduled_time for a single post_history record. Returns True on success."""
    try:
        conn = _get_conn(db_path)
        conn.execute(
            "UPDATE post_history SET scheduled_time = ? WHERE history_id = ?",
            (new_time, history_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"update_history_scheduled_time error: {str(e)[:200]}")
        return False


def delete_history_records(db_path: str, history_ids: List[int]) -> int:
    """Delete post_history records by id. Returns number deleted."""
    if not history_ids:
        return 0
    try:
        conn = _get_conn(db_path)
        placeholders = ",".join("?" * len(history_ids))
        cur = conn.execute(
            f"DELETE FROM post_history WHERE history_id IN ({placeholders})",
            history_ids,
        )
        conn.commit()
        conn.close()
        return cur.rowcount
    except Exception as e:
        logger.error(f"delete_history_records error: {str(e)[:200]}")
        return 0


def retry_failed_posts(db_path: str, history_ids: List[int]) -> int:
    """
    Reset status to 'Pending' for given history_ids so they can be retried.
    Only affects records that currently have status='Failed'.
    Returns number of updated rows.
    """
    if not history_ids:
        return 0
    try:
        conn = _get_conn(db_path)
        placeholders = ",".join("?" * len(history_ids))
        cur = conn.execute(
            f"UPDATE post_history "
            f"SET status = 'Pending', error_log = '', last_retry_at = '' "
            f"WHERE history_id IN ({placeholders}) AND status = 'Failed'",
            history_ids,
        )
        conn.commit()
        conn.close()
        return cur.rowcount
    except Exception as e:
        logger.error(f"retry_failed_posts error: {str(e)[:200]}")
        return 0


def recover_interrupted_webui_jobs(db_path: str) -> int:
    """Return WebUI jobs left Running by a previous crash to Pending."""
    try:
        conn = _get_conn(db_path)
        cur = conn.execute("""
            UPDATE post_history
            SET status = 'Pending',
                error_log = 'Khôi phục sau khi ứng dụng bị đóng trong lúc xử lý',
                last_retry_at = ?
            WHERE status = 'Running' AND scheduling_method = 'WebUI'
        """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
        conn.commit()
        changed = cur.rowcount
        conn.close()
        return changed
    except Exception as e:
        logger.error(f"recover_interrupted_webui_jobs error: {str(e)[:200]}")
        return 0


# ─── Page Spy Manager: Scraped Pages CRUD ────────────────────────────────────
# These functions operate on the `pages` and `posts` tables
# (used by the scraper), NOT the `managed_pages`/`page_groups` tables
# (used by account_manager).


def get_scraped_pages_full(db_path: str) -> List[dict]:
    """Return all scraped pages with full info for Page Spy Manager."""
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT p.id, p.page_url, p.page_name, p.group_name,
                   p.post_count, p.follower_count, p.last_scraped, p.created_at
            FROM pages p
            ORDER BY p.group_name, p.page_name
        """).fetchall()
        conn.close()
        return [
            {
                "id": r[0], "page_url": r[1], "page_name": r[2],
                "group_name": r[3] or "Chưa phân loại",
                "post_count": r[4] or 0, "follower_count": r[5] or 0,
                "last_scraped": r[6] or "", "created_at": r[7] or "",
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_scraped_pages_full error: {str(e)[:200]}")
        return []


def get_scraped_groups_stats(db_path: str) -> List[dict]:
    """Return scraped-page groups with aggregate statistics."""
    try:
        conn = _get_conn(db_path)
        # Get distinct groups from pages table
        rows = conn.execute("""
            SELECT COALESCE(NULLIF(group_name, ''), 'Chưa phân loại') as gname,
                   COUNT(*) as page_count,
                   SUM(post_count) as total_posts,
                   SUM(follower_count) as total_followers
            FROM pages
            GROUP BY gname
            ORDER BY gname
        """).fetchall()
        conn.close()
        return [
            {
                "group_name": r[0], "page_count": r[1],
                "total_posts": r[2] or 0, "total_followers": r[3] or 0,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_scraped_groups_stats error: {str(e)[:200]}")
        return []


def update_scraped_page_group(
    db_path: str, page_urls: List[str], group_name: str,
) -> int:
    """Move scraped pages to a group. Also updates matching posts."""
    if not page_urls:
        return 0
    try:
        conn = _get_conn(db_path)
        updated = 0
        for url in page_urls:
            cur = conn.execute(
                "UPDATE pages SET group_name = ? WHERE page_url = ?",
                (group_name, url),
            )
            updated += cur.rowcount
            # Sync group_name in posts table
            conn.execute(
                "UPDATE posts SET group_name = ? WHERE page_url = ?",
                (group_name, url),
            )
        conn.commit()
        conn.close()
        return updated
    except Exception as e:
        logger.error(f"update_scraped_page_group error: {str(e)[:200]}")
        return 0


def delete_scraped_page(db_path: str, page_url: str) -> dict:
    """Delete a scraped page and all its posts. Returns stats."""
    try:
        conn = _get_conn(db_path)
        # Delete posts first
        posts_cur = conn.execute(
            "DELETE FROM posts WHERE page_url = ?", (page_url,)
        )
        posts_deleted = posts_cur.rowcount
        # Delete page registry
        page_cur = conn.execute(
            "DELETE FROM pages WHERE page_url = ?", (page_url,)
        )
        page_deleted = page_cur.rowcount
        conn.commit()
        conn.close()
        return {"pages_deleted": page_deleted, "posts_deleted": posts_deleted}
    except Exception as e:
        logger.error(f"delete_scraped_page error: {str(e)[:200]}")
        return {"pages_deleted": 0, "posts_deleted": 0}


def rename_scraped_page_group(
    db_path: str, old_name: str, new_name: str,
) -> int:
    """Rename a scraped-page group in both pages and posts tables."""
    new_name = new_name.strip()
    if not new_name or old_name == new_name:
        return 0
    try:
        conn = _get_conn(db_path)
        cur = conn.execute(
            "UPDATE pages SET group_name = ? WHERE group_name = ?",
            (new_name, old_name),
        )
        updated = cur.rowcount
        conn.execute(
            "UPDATE posts SET group_name = ? WHERE group_name = ?",
            (new_name, old_name),
        )
        conn.commit()
        conn.close()
        return updated
    except Exception as e:
        logger.error(f"rename_scraped_page_group error: {str(e)[:200]}")
        return 0


def delete_scraped_page_group(db_path: str, group_name: str) -> int:
    """Delete a scraped-page group by moving its pages to 'Chưa phân loại'."""
    if not group_name or group_name == "Chưa phân loại":
        return 0
    try:
        conn = _get_conn(db_path)
        cur = conn.execute(
            "UPDATE pages SET group_name = 'Chưa phân loại' WHERE group_name = ?",
            (group_name,),
        )
        updated = cur.rowcount
        conn.execute(
            "UPDATE posts SET group_name = 'Chưa phân loại' WHERE group_name = ?",
            (group_name,),
        )
        conn.commit()
        conn.close()
        return updated
    except Exception as e:
        logger.error(f"delete_scraped_page_group error: {str(e)[:200]}")
        return 0


def save_facebook_token(
    db_path: str,
    account_id: int,
    uid: str = "",
    access_token: str = "",
    token_type: str = "user",
    page_id: str = "",
    scopes: str = "",
    expires_in: int = 0,
    expires_at: str = "",
    status: str = "Valid",
    error: str = "",
) -> bool:
    """Insert or update a Facebook token row. Do not log token values."""
    if not account_id:
        return False
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = _get_conn(db_path)
        conn.execute("""
            INSERT INTO facebook_tokens
                (account_id, uid, token_type, page_id, access_token, scopes, expires_in,
                 expires_at, updated_at, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, token_type, page_id) DO UPDATE SET
                uid = excluded.uid,
                access_token = excluded.access_token,
                scopes = excluded.scopes,
                expires_in = excluded.expires_in,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at,
                status = excluded.status,
                error = excluded.error
        """, (
            account_id, uid or "", token_type or "user", page_id or "",
            protect_secret(access_token or ""), scopes or "", int(expires_in or 0),
            expires_at or "", now, status or "", error or "",
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"save_facebook_token error: {str(e)[:200]}")
        return False


def get_facebook_token(
    db_path: str,
    account_id: int,
    token_type: str = "user",
) -> Optional[dict]:
    """Return a Facebook token row for an account. Caller controls display safety."""
    if not account_id:
        return None
    try:
        conn = _get_conn(db_path)
        row = conn.execute("""
            SELECT id, account_id, uid, token_type, access_token, scopes, expires_in,
                   expires_at, updated_at, status, error
            FROM facebook_tokens
            WHERE account_id = ? AND token_type = ?
            ORDER BY updated_at DESC
            LIMIT 1
        """, (account_id, token_type or "user")).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0],
            "account_id": row[1],
            "uid": row[2] or "",
            "token_type": row[3] or "",
            "access_token": reveal_secret(row[4]),
            "scopes": row[5] or "",
            "expires_in": row[6] or 0,
            "expires_at": row[7] or "",
            "updated_at": row[8] or "",
            "status": row[9] or "",
            "error": row[10] or "",
        }
    except Exception as e:
        logger.error(f"get_facebook_token error: {str(e)[:200]}")
        return None


def delete_facebook_token(
    db_path: str,
    account_id: int,
    token_type: str = "user",
) -> bool:
    """Delete a stored Facebook token row."""
    if not account_id:
        return False
    try:
        conn = _get_conn(db_path)
        conn.execute(
            "DELETE FROM facebook_tokens WHERE account_id = ? AND token_type = ?",
            (account_id, token_type or "user"),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"delete_facebook_token error: {str(e)[:200]}")
        return False


def migrate_secrets_at_rest(db_path: str) -> dict:
    """Encrypt legacy plaintext secrets after creating a SQLite backup.

    DPAPI binds ciphertext to the current Windows user.  This migration is
    intentionally explicit and idempotent; callers must present the backup path
    to the user so portability implications remain visible.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.pre-secrets-{timestamp}.bak"
    source = _get_conn(db_path)
    backup = sqlite3.connect(backup_path)
    changed = 0
    try:
        source.backup(backup)
        backup.commit()
        specs = (
            ("fb_accounts", "id", ("password", "secret_2fa", "email_pass", "cookie")),
            ("social_accounts", "id", ("password", "secret_2fa", "email_pass", "cookie")),
            ("facebook_tokens", "id", ("access_token",)),
        )
        source.execute("BEGIN IMMEDIATE")
        for table, primary_key, columns in specs:
            selected = ", ".join((primary_key, *columns))
            rows = source.execute(f"SELECT {selected} FROM {table}").fetchall()
            for row in rows:
                updates = []
                values = []
                for index, column in enumerate(columns, start=1):
                    value = str(row[index] or "")
                    if value and not is_protected(value):
                        updates.append(f"{column} = ?")
                        values.append(protect_secret(value))
                if updates:
                    values.append(row[0])
                    source.execute(
                        f"UPDATE {table} SET {', '.join(updates)} WHERE {primary_key} = ?",
                        values,
                    )
                    changed += len(updates)
        source.commit()
        return {"changed": changed, "backup_path": backup_path}
    except Exception:
        source.rollback()
        raise
    finally:
        backup.close()
        source.close()
