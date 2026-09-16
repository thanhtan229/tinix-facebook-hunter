"""Migrate legacy per-post folders into the flat download directory safely."""

import re
import sqlite3
import shutil
from pathlib import Path
from typing import Any, Optional

from core.db_storage import _get_conn, get_db_path
from utils import logger


VIDEO_EXTS = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MIGRATION_PENDING_MARKER = ".tinix-migration-pending"


def _files_match(first: Path, second: Path) -> bool:
    """Compare files in chunks so large media never has to fit in memory."""
    try:
        if first.stat().st_size != second.stat().st_size:
            return False
        with first.open("rb") as first_handle, second.open("rb") as second_handle:
            while first_chunk := first_handle.read(1024 * 1024):
                if first_chunk != second_handle.read(len(first_chunk)):
                    return False
            return second_handle.read(1) == b""
    except OSError:
        return False


def _move_without_overwrite(source: Path, target: Path) -> bool:
    """Move only to an empty destination; leave the source intact on every failure."""
    if target.exists():
        if _files_match(source, target):
            try:
                source.unlink()
                return True
            except OSError as exc:
                logger.warning(f"Không thể xóa bản sao cũ {source}: {exc}")
        logger.warning(f"Giữ file cũ {source} vì file đích đã tồn tại: {target}")
        return False
    try:
        shutil.move(str(source), str(target))
        return True
    except OSError as exc:
        logger.warning(f"Không thể chuyển {source} sang {target}: {exc}")
        return False


def _legacy_media_index(source: Path, fallback: int, used_indices: set[int]) -> int:
    """Use an ordinal in legacy names so a partial migration can resume stably."""
    match = re.search(r"(\d+)(?!.*\d)", source.stem)
    candidate = int(match.group(1)) if match else fallback
    if candidate < 1 or candidate in used_indices:
        candidate = max(1, fallback)
        while candidate in used_indices:
            candidate += 1
    used_indices.add(candidate)
    return candidate


def _migration_summary() -> dict[str, int]:
    return {
        "migrated_folders": 0,
        "files_moved": 0,
        "folders_removed": 0,
        "db_rows_updated": 0,
    }


def migrate_legacy_subfolders_to_flat(
    output_dir: str | Path,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """Safely migrate numeric legacy post folders into ``output_dir``.

    Only a fully migrated, now-empty legacy folder updates its matching database
    row. Conflicts, nested folders, and move failures are deliberately retained
    for manual resolution instead of risking the original media.
    """
    out_path = Path(output_dir).expanduser().resolve()
    if not out_path.is_dir():
        return _migration_summary()

    try:
        connection = _get_conn(get_db_path(db_path))
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.Error as exc:
        logger.error(f"Không thể khóa database để migration an toàn: {exc}")
        return _migration_summary()

    files_moved = 0
    folders_removed = 0
    migrated_entries: list[tuple[str, Path]] = []

    try:
        for entry in list(out_path.iterdir()):
            if not entry.is_dir():
                continue

            post_id = entry.name.strip()
            if not re.fullmatch(r"\d+", post_id):
                continue

            try:
                children = list(entry.iterdir())
            except OSError:
                continue

            if any(child.is_dir() for child in children):
                logger.warning(f"Bỏ qua thư mục cũ có thư mục con để tránh mất dữ liệu: {entry}")
                continue

            marker_path = entry / MIGRATION_PENDING_MARKER
            source_files = [child for child in children if child.is_file() and child != marker_path]
            if not source_files:
                if marker_path.is_file():
                    migrated_entries.append((post_id, entry))
                else:
                    try:
                        entry.rmdir()
                        folders_removed += 1
                    except OSError:
                        pass
                continue

            caption_file: Optional[Path] = None
            video_files: list[Path] = []
            image_files: list[Path] = []
            thumbnail_file: Optional[Path] = None
            other_files: list[Path] = []

            for source in source_files:
                file_name = source.name.lower()
                suffix = source.suffix.lower()
                if file_name == "caption.txt" or (suffix == ".txt" and caption_file is None):
                    caption_file = source
                elif suffix in VIDEO_EXTS:
                    video_files.append(source)
                elif file_name.startswith("thumbnail"):
                    thumbnail_file = source
                elif suffix in IMAGE_EXTS:
                    image_files.append(source)
                else:
                    other_files.append(source)

            image_files.sort(key=lambda path: path.name.lower())
            video_files.sort(key=lambda path: path.name.lower())
            completed = True

            if caption_file:
                if _move_without_overwrite(caption_file, out_path / f"{post_id}.txt"):
                    files_moved += 1
                else:
                    completed = False

            used_video_indices: set[int] = set()
            for index, video_file in enumerate(video_files, start=1):
                media_index = _legacy_media_index(video_file, index, used_video_indices)
                target = out_path / (f"{post_id}.mp4" if media_index == 1 else f"{post_id}_{media_index}.mp4")
                if _move_without_overwrite(video_file, target):
                    files_moved += 1
                else:
                    completed = False

            moved_first_image = False
            used_image_indices: set[int] = set()
            for index, image_file in enumerate(image_files, start=1):
                media_index = _legacy_media_index(image_file, index, used_image_indices)
                target = out_path / f"{post_id}_{media_index}.jpeg"
                if _move_without_overwrite(image_file, target):
                    files_moved += 1
                    moved_first_image = moved_first_image or media_index == 1
                else:
                    completed = False

            if thumbnail_file:
                first_image = out_path / f"{post_id}_1.jpeg"
                if moved_first_image and first_image.exists() and _files_match(thumbnail_file, first_image):
                    try:
                        thumbnail_file.unlink()
                    except OSError:
                        completed = False
                else:
                    target = first_image
                    if target.exists():
                        target = out_path / f"{post_id}_thumbnail{thumbnail_file.suffix.lower()}"
                    if _move_without_overwrite(thumbnail_file, target):
                        files_moved += 1
                    else:
                        completed = False

            for other_file in other_files:
                target = out_path / f"{post_id}_{other_file.name}"
                if _move_without_overwrite(other_file, target):
                    files_moved += 1
                else:
                    completed = False

            if not completed:
                logger.warning(f"Chưa cập nhật database vì di chuyển chưa hoàn tất: {entry}")
                continue

            try:
                marker_path.write_text("pending database update", encoding="utf-8")
            except OSError as exc:
                logger.warning(f"Không thể tạo mốc migration chờ cập nhật DB {entry}: {exc}")
                continue
            migrated_entries.append((post_id, entry))

        db_updated = 0
        try:
            output_path = str(out_path)
            for offset in range(0, len(migrated_entries), 500):
                chunk = [post_id for post_id, _entry in migrated_entries[offset:offset + 500]]
                placeholders = ",".join("?" for _ in chunk)
                cursor = connection.execute(
                    f"UPDATE posts SET download_path = ? WHERE post_id IN ({placeholders})",
                    [output_path, *chunk],
                )
                db_updated += cursor.rowcount
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            logger.error(f"Lỗi cập nhật database sau khi di chuyển thư mục: {exc}")
            migrated_entries = []

        for _post_id, entry in migrated_entries:
            marker_path = entry / MIGRATION_PENDING_MARKER
            try:
                marker_path.unlink(missing_ok=True)
                entry.rmdir()
                folders_removed += 1
            except OSError as exc:
                logger.warning(f"Không thể xóa thư mục cũ đã migrate {entry}: {exc}")
    finally:
        connection.close()

    logger.info(
        f"Hoàn thành di chuyển dữ liệu: {len(migrated_entries)} thư mục, {files_moved} files đã dời, "
        f"{folders_removed} thư mục đã xóa, {db_updated} bản ghi DB đã cập nhật."
    )
    return {
        "migrated_folders": len(migrated_entries),
        "files_moved": files_moved,
        "folders_removed": folders_removed,
        "db_rows_updated": db_updated,
    }
