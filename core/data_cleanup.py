"""Backed-up cleanup operations for the scraped-data repository."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Iterable

from core.database_maintenance import create_database_backup
from core.db_storage import _get_conn


def _normalized_urls(page_urls: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(url.strip() for url in page_urls if url and url.strip()))


def preview_scraped_cleanup(
    db_path: str,
    *,
    page_urls: Iterable[str] = (),
    all_pages: bool = False,
) -> dict[str, int]:
    urls = _normalized_urls(page_urls)
    if not all_pages and not urls:
        return {"pages": 0, "posts": 0, "media_paths": 0}
    connection = _get_conn(db_path)
    try:
        if all_pages:
            page_count = int(connection.execute("SELECT COUNT(*) FROM pages").fetchone()[0])
            post_count = int(connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
            media_count = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT download_path) FROM posts WHERE download_path != ''"
                ).fetchone()[0]
            )
        else:
            placeholders = ",".join("?" for _ in urls)
            page_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM pages WHERE page_url IN ({placeholders})", urls
                ).fetchone()[0]
            )
            post_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM posts WHERE page_url IN ({placeholders})", urls
                ).fetchone()[0]
            )
            media_count = int(
                connection.execute(
                    f"SELECT COUNT(DISTINCT download_path) FROM posts "
                    f"WHERE page_url IN ({placeholders}) AND download_path != ''",
                    urls,
                ).fetchone()[0]
            )
        return {"pages": page_count, "posts": post_count, "media_paths": media_count}
    finally:
        connection.close()


def _delete_scraped_records(
    db_path: str,
    *,
    page_urls: Iterable[str] = (),
    all_pages: bool = False,
) -> tuple[int, int, list[str]]:
    urls = _normalized_urls(page_urls)
    connection = _get_conn(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        from utils import config
        out_root = Path(config.get("output_dir", ".")).expanduser().resolve()

        if all_pages:
            post_rows = connection.execute(
                "SELECT DISTINCT post_id, download_path FROM posts WHERE download_path != ''"
            ).fetchall()
            posts_deleted = connection.execute("DELETE FROM posts").rowcount
            pages_deleted = connection.execute("DELETE FROM pages").rowcount
        else:
            placeholders = ",".join("?" for _ in urls)
            post_rows = connection.execute(
                f"SELECT DISTINCT post_id, download_path FROM posts "
                f"WHERE page_url IN ({placeholders}) AND download_path != ''",
                urls,
            ).fetchall()
            posts_deleted = connection.execute(
                f"DELETE FROM posts WHERE page_url IN ({placeholders})", urls
            ).rowcount
            pages_deleted = connection.execute(
                f"DELETE FROM pages WHERE page_url IN ({placeholders})", urls
            ).rowcount

        media_paths = []
        for pid, dl_path in post_rows:
            clean_pid = re.sub(r"\D", "", str(pid or "")).strip() or str(pid or "").strip()
            target_dir = Path(dl_path).expanduser().resolve() if dl_path else out_root
            if not target_dir.exists():
                target_dir = out_root
            if target_dir.is_dir():
                if target_dir != out_root:
                    media_paths.append(str(target_dir))
                else:
                    if clean_pid:
                        try:
                            for item in target_dir.iterdir():
                                if item.is_file() and (
                                    item.stem == clean_pid
                                    or item.name.startswith(f"{clean_pid}_")
                                    or item.name.startswith(f"{clean_pid}.")
                                ):
                                    media_paths.append(str(item))
                        except Exception:
                            pass
            elif target_dir.is_file():
                media_paths.append(str(target_dir))

        if media_paths:
            media_placeholders = ",".join("?" for _ in media_paths)
            still_referenced = {
                row[0]
                for row in connection.execute(
                    f"SELECT DISTINCT download_path FROM posts "
                    f"WHERE download_path IN ({media_placeholders})",
                    media_paths,
                ).fetchall()
            }
            media_paths = [path for path in media_paths if path not in still_referenced and path != str(out_root)]
        connection.commit()
        return int(pages_deleted), int(posts_deleted), media_paths
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _is_below(candidate: Path, root: Path) -> bool:
    return candidate != root and root in candidate.parents


def delete_downloaded_media(paths: Iterable[str], output_root: str) -> dict[str, int]:
    """Delete only paths resolving strictly below the configured output root."""
    root = Path(output_root).expanduser().resolve()
    deleted = skipped = failed = 0
    for raw_path in dict.fromkeys(path for path in paths if path):
        try:
            candidate = Path(raw_path).expanduser().resolve()
            if not root.is_dir() or not _is_below(candidate, root):
                skipped += 1
                continue
            if not candidate.exists():
                skipped += 1
            elif candidate.is_dir():
                shutil.rmtree(candidate)
                deleted += 1
            elif candidate.is_file():
                candidate.unlink()
                deleted += 1
            else:
                skipped += 1
        except OSError:
            failed += 1
    return {"media_deleted": deleted, "media_skipped": skipped, "media_failed": failed}


def cleanup_scraped_data(
    db_path: str,
    *,
    page_urls: Iterable[str] = (),
    all_pages: bool = False,
    delete_media: bool = False,
    output_root: str = "",
) -> dict[str, object]:
    """Back up, delete scraped records, and optionally remove safely-scoped media."""
    preview = preview_scraped_cleanup(db_path, page_urls=page_urls, all_pages=all_pages)
    if preview["pages"] == 0 and preview["posts"] == 0:
        return {
            "backup_path": "",
            "pages_deleted": 0,
            "posts_deleted": 0,
            "media_deleted": 0,
            "media_skipped": 0,
            "media_failed": 0,
        }

    backup_path = create_database_backup(db_path)
    pages_deleted, posts_deleted, media_paths = _delete_scraped_records(
        db_path, page_urls=page_urls, all_pages=all_pages
    )
    media_result = {"media_deleted": 0, "media_skipped": 0, "media_failed": 0}
    if delete_media:
        media_result = delete_downloaded_media(media_paths, output_root)
    return {
        "backup_path": backup_path,
        "pages_deleted": pages_deleted,
        "posts_deleted": posts_deleted,
        **media_result,
    }
