"""
Tinix Facebook Down — Download History Manager
Tracks past download sessions for the history dialog.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, asdict


@dataclass
class HistoryEntry:
    """A single download session record."""
    date: str
    urls: List[str]
    total_posts: int
    success: int
    failed: int
    output_dir: str

    @staticmethod
    def create(urls: List[str], success: int, failed: int, output_dir: str) -> "HistoryEntry":
        """Create a new history entry with current timestamp."""
        return HistoryEntry(
            date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            urls=urls,
            total_posts=len(urls),
            success=success,
            failed=failed,
            output_dir=output_dir,
        )


def _get_history_path() -> Path:
    """Get full path to history.json."""
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    return base / "history.json"


def load_history() -> List[HistoryEntry]:
    """Load download history from file."""
    path = _get_history_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [HistoryEntry(**entry) for entry in data]
    except (json.JSONDecodeError, IOError, TypeError) as e:
        print(f"[WARN] Could not load history: {e}")
        return []


def save_history(history: List[HistoryEntry]) -> None:
    """Save download history to file."""
    path = _get_history_path()
    try:
        data = [asdict(entry) for entry in history]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"[ERROR] Could not save history: {e}")


def add_entry(entry: HistoryEntry) -> None:
    """Add a new entry to history and save."""
    history = load_history()
    history.insert(0, entry)  # Newest first
    # Keep only last 100 entries
    history = history[:100]
    save_history(history)


def clear_history() -> None:
    """Clear all history."""
    save_history([])
