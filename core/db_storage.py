"""
Tinix Facebook Down — SQLite Storage
Stores all scraped post data in a single SQLite database.
Supports group management and duplicate URL detection.
"""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from utils import logger


def _default_db_path() -> str:
    """Get default database path."""
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    return str(base / "tinix_scraper.db")


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Get database path from custom or default."""
    if custom_path and custom_path.strip():
        return custom_path.strip()
    return _default_db_path()


def _get_conn(db_path: str) -> sqlite3.Connection:
    """Open a connection and ensure the schema exists."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

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
            views         INTEGER NOT NULL DEFAULT 0,
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
        conn.commit()
    except Exception:
        pass

    # Indexes (after migration so columns exist)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_page ON posts(page_name)")
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
            proxy_id    INTEGER DEFAULT NULL,
            is_active   INTEGER NOT NULL DEFAULT 1,
            last_login  TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL DEFAULT '',
            UNIQUE(username)
        )
    """)

    # --- Proxies ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proxies (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            label       TEXT    NOT NULL DEFAULT '',
            protocol    TEXT    NOT NULL DEFAULT 'http',
            host        TEXT    NOT NULL,
            port        INTEGER NOT NULL DEFAULT 80,
            auth_user   TEXT    NOT NULL DEFAULT '',
            auth_pass   TEXT    NOT NULL DEFAULT '',
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL DEFAULT ''
        )
    """)

    conn.commit()
    return conn


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
        # Find the page_name from registry
        row = conn.execute(
            "SELECT page_name FROM pages WHERE page_url = ?", (canonical,)
        ).fetchone()

        post_ids = set()
        if row:
            page_name = row[0]
            rows = conn.execute(
                "SELECT post_id FROM posts WHERE page_name = ?", (page_name,)
            ).fetchall()
            post_ids = {r[0] for r in rows}
        conn.close()
        return post_ids
    except Exception as e:
        logger.debug(f"get_page_post_ids error: {str(e)[:100]}")
        return set()


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

    try:
        for post in posts:
            pid = post.post_id if hasattr(post, 'post_id') else ""
            numeric_id = pid if pid and pid.isdigit() else ""
            post_url = f"https://www.facebook.com/{numeric_id}" if numeric_id else ""

            conn.execute("""
                INSERT OR REPLACE INTO posts
                    (page_name, page_url, group_name, post_id, date, post_type,
                     engagement, comments, views, caption, url, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                page_name,
                canonical,
                group_name,
                pid,
                getattr(post, 'date', ''),
                getattr(post, 'post_type', 'Text'),
                getattr(post, 'engagement', 0),
                getattr(post, 'comments', 0),
                getattr(post, 'views', 0),
                getattr(post, 'caption', ''),
                post_url,
                now,
            ))
            saved += 1

        # Update pages registry
        if canonical:
            conn.execute("""
                INSERT INTO pages (page_url, page_name, group_name, post_count, last_scraped, created_at, follower_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(page_url) DO UPDATE SET
                    page_name = excluded.page_name,
                    group_name = excluded.group_name,
                    post_count = excluded.post_count,
                    last_scraped = excluded.last_scraped,
                    follower_count = CASE WHEN excluded.follower_count > 0 THEN excluded.follower_count ELSE pages.follower_count END
            """, (canonical, page_name, group_name, saved, now, now, follower_count))

        conn.commit()
        logger.info(f"💾 Đã lưu {saved} bài vào database")
    except Exception as e:
        logger.error(f"Lỗi lưu database: {str(e)[:200]}")
    finally:
        conn.close()

    return saved


def get_all_pages(db_path: str) -> List[dict]:
    """Get list of all pages in the database with post counts."""
    try:
        conn = _get_conn(db_path)
        cursor = conn.execute("""
            SELECT page_name, page_url, group_name, post_count, last_scraped
            FROM pages
            ORDER BY last_scraped DESC
        """)
        pages = [
            {
                "page_name": row[0],
                "page_url": row[1],
                "group_name": row[2],
                "post_count": row[3],
                "last_scraped": row[4],
            }
            for row in cursor.fetchall()
        ]
        conn.close()
        return pages
    except Exception as e:
        logger.error(f"Lỗi đọc database: {str(e)[:200]}")
        return []


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
        conn.close()
        return {"total_posts": total_posts, "total_pages": total_pages}
    except Exception:
        return {"total_posts": 0, "total_pages": 0}


# ─── Dashboard Queries ───────────────────────────────────────────────────────

def get_posts_by_page_url_full(db_path: str, page_url: str) -> List[dict]:
    """Get all posts for a page URL with download status. For Page Intelligence."""
    canonical = normalize_page_url(page_url)
    try:
        conn = _get_conn(db_path)
        cursor = conn.execute("""
            SELECT post_id, date, post_type, engagement, comments,
                   views, caption, url, downloaded, download_path, scraped_at
            FROM posts
            WHERE page_url = ?
            ORDER BY date DESC, scraped_at DESC
        """, (canonical,))
        posts = [
            {
                "post_id": r[0], "date": r[1], "post_type": r[2],
                "engagement": r[3], "comments": r[4], "views": r[5],
                "caption": r[6], "url": r[7], "downloaded": r[8],
                "download_path": r[9], "scraped_at": r[10],
            }
            for r in cursor.fetchall()
        ]
        conn.close()
        return posts
    except Exception as e:
        logger.error(f"Dashboard query error: {str(e)[:200]}")
        return []


def get_top_media_posts(db_path: str, limit: int = 50, page_url: str = "") -> List[dict]:
    """Get top media posts (Ảnh/Video) sorted by engagement. For Top Media tab."""
    try:
        conn = _get_conn(db_path)
        if page_url:
            canonical = normalize_page_url(page_url)
            cursor = conn.execute("""
                SELECT page_name, post_id, date, post_type, engagement, comments,
                       views, caption, url
                FROM posts
                WHERE post_type IN ('Ảnh', 'Video') AND page_url = ?
                ORDER BY engagement DESC
                LIMIT ?
            """, (canonical, limit))
        else:
            cursor = conn.execute("""
                SELECT page_name, post_id, date, post_type, engagement, comments,
                       views, caption, url
                FROM posts
                WHERE post_type IN ('Ảnh', 'Video')
                ORDER BY engagement DESC
                LIMIT ?
            """, (limit,))
        posts = [
            {
                "page_name": r[0], "post_id": r[1], "date": r[2],
                "post_type": r[3], "engagement": r[4], "comments": r[5],
                "views": r[6], "caption": r[7], "url": r[8],
            }
            for r in cursor.fetchall()
        ]
        conn.close()
        return posts
    except Exception as e:
        logger.error(f"Top media query error: {str(e)[:200]}")
        return []


def get_pending_downloads(db_path: str) -> List[dict]:
    """Get posts not yet downloaded (Ảnh/Video). For Content Gap tab."""
    try:
        conn = _get_conn(db_path)
        cursor = conn.execute("""
            SELECT page_name, post_id, date, post_type, engagement, comments,
                   caption, url
            FROM posts
            WHERE downloaded = 0 AND post_type IN ('Ảnh', 'Video')
            ORDER BY engagement DESC
        """)
        posts = [
            {
                "page_name": r[0], "post_id": r[1], "date": r[2],
                "post_type": r[3], "engagement": r[4], "comments": r[5],
                "caption": r[6], "url": r[7],
            }
            for r in cursor.fetchall()
        ]
        conn.close()
        return posts
    except Exception as e:
        logger.error(f"Pending downloads query error: {str(e)[:200]}")
        return []


def get_page_leaderboard(db_path: str) -> List[dict]:
    """Calculate engagement rate per page for leaderboard.
    Rate = (SUM(engagement) + SUM(comments)) / COUNT(*)"""
    try:
        conn = _get_conn(db_path)
        cursor = conn.execute("""
            SELECT page_name,
                   COUNT(*) as total_posts,
                   SUM(engagement) as total_engagement,
                   SUM(comments) as total_comments,
                   SUM(views) as total_views,
                   ROUND(CAST(SUM(engagement) + SUM(comments) AS REAL) / COUNT(*), 1) as engagement_rate
            FROM posts
            GROUP BY page_name
            ORDER BY engagement_rate DESC
        """)
        pages = [
            {
                "page_name": r[0], "total_posts": r[1],
                "total_engagement": r[2] or 0, "total_comments": r[3] or 0,
                "total_views": r[4] or 0, "engagement_rate": r[5] or 0.0,
            }
            for r in cursor.fetchall()
        ]
        conn.close()
        return pages
    except Exception as e:
        logger.error(f"Leaderboard query error: {str(e)[:200]}")
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


def query_posts_filtered(
    db_path: str,
    page_name: str = "",
    group_name: str = "",
    post_type: str = "",
    date_from: str = "",
    date_to: str = "",
    min_engagement: int = 0,
    min_views: int = 0,
    keyword: str = "",
    download_status: str = "",
) -> List[dict]:
    """Dynamic multi-filter query. All filters are AND-combined.
    Returns full-schema dicts sorted by engagement DESC."""
    try:
        conn = _get_conn(db_path)
        sql = "SELECT * FROM posts WHERE 1=1"
        params: list = []

        if page_name:
            sql += " AND page_name = ?"
            params.append(page_name)
        if group_name:
            sql += " AND group_name = ?"
            params.append(group_name)
        if post_type:
            sql += " AND post_type = ?"
            params.append(post_type)
        if date_from:
            sql += " AND date >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND date <= ?"
            params.append(date_to)
        if min_engagement > 0:
            sql += " AND engagement >= ?"
            params.append(min_engagement)
        if min_views > 0:
            sql += " AND views >= ?"
            params.append(min_views)
        if keyword:
            sql += " AND caption LIKE ?"
            params.append(f"%{keyword}%")
        if download_status == "downloaded":
            sql += " AND downloaded = 1"
        elif download_status == "not_downloaded":
            sql += " AND downloaded = 0"

        sql += " ORDER BY engagement DESC"

        # Get column names
        col_names = [r[1] for r in conn.execute("PRAGMA table_info(posts)").fetchall()]
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
        result = [dict(zip(col_names, row)) for row in rows]
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Filter query error: {str(e)[:200]}")
        return []


# ─── Facebook Account CRUD ───────────────────────────────────────────────────

def add_account(db_path: str, **kwargs) -> int:
    """Add a new Facebook account. Returns new ID or -1 on error."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _get_conn(db_path)
        cur = conn.execute("""
            INSERT INTO fb_accounts
                (label, username, password, secret_2fa, email, email_pass, cookie, proxy_id, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            kwargs.get("label", ""),
            kwargs.get("username", ""),
            kwargs.get("password", ""),
            kwargs.get("secret_2fa", ""),
            kwargs.get("email", ""),
            kwargs.get("email_pass", ""),
            kwargs.get("cookie", ""),
            kwargs.get("proxy_id"),
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
                "email_pass", "cookie", "proxy_id", "is_active", "last_login"):
        if key in kwargs:
            fields.append(f"{key} = ?")
            values.append(kwargs[key])
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
    """Get all Facebook accounts with their proxy info."""
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT a.id, a.label, a.username, a.password, a.secret_2fa,
                   a.email, a.email_pass, a.cookie, a.proxy_id, a.is_active,
                   a.last_login, a.created_at, a.business_id,
                   p.label as proxy_label, p.protocol, p.host, p.port,
                   p.auth_user, p.auth_pass
            FROM fb_accounts a
            LEFT JOIN proxies p ON a.proxy_id = p.id
            ORDER BY a.id
        """).fetchall()
        conn.close()
        return [
            {
                "id": r[0], "label": r[1], "username": r[2], "password": r[3],
                "secret_2fa": r[4], "email": r[5], "email_pass": r[6],
                "cookie": r[7], "proxy_id": r[8], "is_active": r[9],
                "last_login": r[10], "created_at": r[11], "business_id": r[12] or "",
                "proxy_label": r[13] or "", "proxy_protocol": r[14] or "",
                "proxy_host": r[15] or "", "proxy_port": r[16] or 0,
                "proxy_auth_user": r[17] or "", "proxy_auth_pass": r[18] or "",
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


# ─── Managed Pages CRUD ──────────────────────────────────────────────────────

def get_managed_pages(db_path: str, account_id: int) -> List[dict]:
    """Return pages that a specific account manages, with group and avatar info."""
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT mp.id, mp.page_name, mp.page_url, mp.page_id, mp.scanned_at,
                   COALESCE(pg.group_name, 'Chưa phân loại') as group_name,
                   mp.avatar_path, mp.group_id, mp.last_synced
            FROM managed_pages mp
            LEFT JOIN page_groups pg ON mp.group_id = pg.group_id
            WHERE mp.account_id = ?
            ORDER BY group_name, mp.page_name
        """, (account_id,)).fetchall()
        conn.close()
        return [
            {"id": r[0], "page_name": r[1], "page_url": r[2],
             "page_id": r[3], "scanned_at": r[4], "group_name": r[5],
             "avatar_path": r[6] or "", "group_id": r[7] or 1, "last_synced": r[8] or ""}
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
                   mp.avatar_path, mp.group_id, mp.last_synced,
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
             "account_label": r[9] or "", "account_id": r[10]}
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
        count = 0
        for p in pages:
            page_id = p.get("page_id", "").strip() or p.get("page_url", "").strip()
            if not page_id:
                continue
            conn.execute("""
                INSERT INTO managed_pages
                    (account_id, page_name, page_url, page_id, scanned_at, last_synced, group_name, group_id)
                VALUES (?, ?, ?, ?, ?, ?, '', 1)
                ON CONFLICT(account_id, page_id) DO UPDATE SET
                    page_name  = excluded.page_name,
                    page_url   = excluded.page_url,
                    scanned_at = excluded.scanned_at,
                    last_synced = excluded.last_synced
            """, (account_id, p.get("page_name", ""), p.get("page_url", ""),
                  page_id, now, now))
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


# ─── Proxy CRUD ──────────────────────────────────────────────────────────────

def add_proxy(db_path: str, **kwargs) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _get_conn(db_path)
        cur = conn.execute("""
            INSERT INTO proxies (label, protocol, host, port, auth_user, auth_pass, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            kwargs.get("label", ""),
            kwargs.get("protocol", "http"),
            kwargs.get("host", ""),
            kwargs.get("port", 80),
            kwargs.get("auth_user", ""),
            kwargs.get("auth_pass", ""),
            1,
            now,
        ))
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        return new_id
    except Exception as e:
        logger.error(f"Lỗi thêm proxy: {str(e)[:100]}")
        return -1


def update_proxy(db_path: str, proxy_id: int, **kwargs) -> bool:
    fields = []
    values = []
    for key in ("label", "protocol", "host", "port", "auth_user", "auth_pass", "is_active"):
        if key in kwargs:
            fields.append(f"{key} = ?")
            values.append(kwargs[key])
    if not fields:
        return False
    values.append(proxy_id)
    try:
        conn = _get_conn(db_path)
        conn.execute(f"UPDATE proxies SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def delete_proxy(db_path: str, proxy_id: int) -> bool:
    try:
        conn = _get_conn(db_path)
        # Unassign from any accounts first
        conn.execute("UPDATE fb_accounts SET proxy_id = NULL WHERE proxy_id = ?", (proxy_id,))
        conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_all_proxies(db_path: str) -> List[dict]:
    try:
        conn = _get_conn(db_path)
        rows = conn.execute("""
            SELECT id, label, protocol, host, port, auth_user, auth_pass, is_active, created_at
            FROM proxies ORDER BY id
        """).fetchall()
        conn.close()
        return [
            {
                "id": r[0], "label": r[1], "protocol": r[2], "host": r[3],
                "port": r[4], "auth_user": r[5], "auth_pass": r[6],
                "is_active": r[7], "created_at": r[8],
            }
            for r in rows
        ]
    except Exception:
        return []


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
