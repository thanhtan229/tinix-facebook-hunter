"""Safe SQLite backup, verification and restore primitives."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from core.db_storage import (
    SCHEMA_VERSION,
    has_escaped_page_names,
    initialize_database,
    normalize_escaped_page_names,
)


def inspect_database(path: str | Path) -> dict[str, object]:
    database = Path(path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(str(database), timeout=30)
    try:
        integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()
    return {
        "path": str(database),
        "schema_version": version,
        "integrity": integrity,
        "supported": integrity == "ok" and version <= SCHEMA_VERSION,
        "size_bytes": database.stat().st_size,
    }


def create_database_backup(path: str | Path, destination: str | Path | None = None) -> str:
    database = Path(path).expanduser().resolve()
    initialize_database(str(database))
    if destination is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = database.with_name(f"{database.name}.backup-{stamp}.sqlite")
    else:
        backup_path = Path(destination).expanduser().resolve()
    if backup_path == database:
        raise ValueError("Backup destination must differ from the live database")
    backup_path.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(str(database), timeout=30)
    target = sqlite3.connect(str(backup_path), timeout=30)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    result = inspect_database(backup_path)
    if not result["supported"]:
        raise RuntimeError(f"Backup verification failed: {result['integrity']}")
    return str(backup_path)


def restore_database(path: str | Path, backup: str | Path) -> str:
    """Restore a verified backup and return the automatic pre-restore backup path."""
    database = Path(path).expanduser().resolve()
    backup_path = Path(backup).expanduser().resolve()
    details = inspect_database(backup_path)
    if not details["supported"]:
        raise RuntimeError("Backup is corrupt or uses an unsupported schema")
    safety_backup = create_database_backup(database)
    source = sqlite3.connect(str(backup_path), timeout=30)
    target = sqlite3.connect(str(database), timeout=30)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    restored = inspect_database(database)
    if not restored["supported"]:
        raise RuntimeError("Restored database failed verification")
    return safety_backup


def normalize_page_names_with_backup(path: str | Path) -> dict[str, object]:
    """Back up first, then apply the idempotent legacy Page-name cleanup."""
    database = Path(path).expanduser().resolve()
    if not has_escaped_page_names(str(database)):
        return {"changed": 0, "skipped": 0, "backup_path": ""}
    backup_path = create_database_backup(database)
    result = normalize_escaped_page_names(str(database))
    return {**result, "backup_path": backup_path}
