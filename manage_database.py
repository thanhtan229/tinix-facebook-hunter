"""Offline database maintenance CLI. Stop Tinix before using restore."""

import argparse
import json
import sys

from core.database_maintenance import create_database_backup, inspect_database, restore_database
from core.db_storage import get_db_path
from utils import config


def main() -> int:
    parser = argparse.ArgumentParser(description="Tinix FB Studio database maintenance")
    parser.add_argument("action", choices=("backup", "verify", "restore"))
    parser.add_argument("--database", help="Database path; defaults to configured scraper database")
    parser.add_argument("--file", help="Backup destination for backup, or source for verify/restore")
    parser.add_argument("--confirm", action="store_true", help="Required for restore")
    args = parser.parse_args()
    database = get_db_path(args.database or config.get("scraper_db_path", ""))

    if args.action == "backup":
        print(json.dumps({"backup_path": create_database_backup(database, args.file)}, ensure_ascii=False, indent=2))
        return 0
    if args.action == "verify":
        print(json.dumps(inspect_database(args.file or database), ensure_ascii=False, indent=2))
        return 0
    if not args.file or not args.confirm:
        parser.error("restore requires --file BACKUP and --confirm")
    try:
        safety_backup = restore_database(database, args.file)
    except RuntimeError as exc:
        # Refused (e.g. the WebUI is running) or failed verification; show the reason, not a traceback.
        # A pre-restore safety backup is created before any overwrite, so the data stays recoverable.
        print(f"[KHÔNG KHÔI PHỤC] {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"restored": database, "pre_restore_backup": safety_backup}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
