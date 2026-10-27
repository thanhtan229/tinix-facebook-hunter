"""Regression tests for data-loss and recovery findings from the production review."""

from __future__ import annotations

import copy
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from core import database_maintenance, db_storage, media_downloader
from core.data_cleanup import cleanup_scraped_data, delete_downloaded_media
from utils import config, process_cleanup
from web.routes import scraper as scraper_routes


@pytest.fixture
def storage(tmp_path, monkeypatch):
    output = tmp_path / "downloads"
    output.mkdir()
    database = str(tmp_path / "scraper.sqlite")
    monkeypatch.setenv("TINIX_DB_PATH", database)
    monkeypatch.setattr(config, "_config_cache", {**config.DEFAULTS, "output_dir": str(output)})
    db_storage.initialize_database(database)
    return database, output


def post(post_id):
    return SimpleNamespace(
        post_id=post_id, page_name="Demo", date="01/01/2026", post_type="Ảnh",
        engagement=0, comments=0, shares=0, view_count=0, caption="Caption", url="", media_count=1,
    )


@pytest.mark.parametrize("operation", ["rows", "page"])
@pytest.mark.parametrize("post_id", ["123456789012345", "pfbidAbc_123456789"])
def test_deletion_retains_shared_flat_media_until_last_reference(storage, operation, post_id):
    database, output = storage
    urls = ["https://www.facebook.com/page-a", "https://www.facebook.com/page-b"]
    for name, url in zip(["Page A", "Page B"], urls, strict=True):
        db_storage.save_posts(database, name, url, [post(post_id)])
    files = [output / f"{post_id}_1.jpeg", output / f"{post_id}.txt"]
    for path in files:
        path.write_bytes(b"complete media or caption")
    connection = db_storage._get_conn(database)
    connection.execute("UPDATE posts SET download_path = ?, downloaded = 1", (str(output),))
    connection.commit()
    row_ids = [row[0] for row in connection.execute("SELECT id FROM posts ORDER BY id")]
    connection.close()

    if operation == "rows":
        result = db_storage.bulk_delete_post_rows(database, [row_ids[0]])
        delete_downloaded_media(result["paths"], str(output))
        assert result["deleted"] == 1
    else:
        result = cleanup_scraped_data(database, page_urls=[urls[0]], delete_media=True, output_root=str(output))
        assert result["posts_deleted"] == 1
    assert all(path.exists() for path in files)
    connection = db_storage._get_conn(database)
    assert connection.execute("SELECT downloaded FROM posts").fetchall() == [(1,)]
    connection.close()

    result = db_storage.bulk_delete_post_rows(database, [row_ids[1]])
    delete_downloaded_media(result["paths"], str(output))
    assert all(not path.exists() for path in files)


def test_deletion_protects_legacy_parent_with_surviving_nested_reference(storage):
    database, output = storage
    legacy = output / "legacy"
    child = legacy / "123456789012345.mp4"
    legacy.mkdir()
    child.write_bytes(b"video")
    db_storage.save_posts(database, "Page A", "https://www.facebook.com/page-a", [post("123456789012345")])
    db_storage.save_posts(database, "Page B", "https://www.facebook.com/page-b", [post("223456789012345")])
    connection = db_storage._get_conn(database)
    rows = connection.execute("SELECT id FROM posts ORDER BY id").fetchall()
    connection.execute("UPDATE posts SET download_path = ? WHERE id = ?", (str(legacy), rows[0][0]))
    connection.execute("UPDATE posts SET download_path = ? WHERE id = ?", (str(child), rows[1][0]))
    connection.commit()
    connection.close()
    result = db_storage.bulk_delete_post_rows(database, [rows[0][0]])
    assert result["paths"] == []
    assert child.exists()


def install_abort_trigger(database):
    connection = db_storage._get_conn(database)
    connection.execute("""
        CREATE TRIGGER reject_second_post BEFORE INSERT ON posts
        WHEN NEW.post_id = '223456789012345'
        BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END
    """)
    connection.commit()
    connection.close()


def test_save_failure_rolls_back_entire_batch_and_propagates(storage):
    database, _ = storage
    install_abort_trigger(database)
    with pytest.raises(sqlite3.IntegrityError, match="simulated write failure"):
        db_storage.save_posts(database, "Demo", "https://www.facebook.com/demo", [
            post("123456789012345"), post("223456789012345"),
        ])
    connection = db_storage._get_conn(database)
    assert connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0
    connection.close()


@pytest.mark.parametrize("direction", ["new", "older"])
def test_failed_favorite_save_preserves_both_cursors(storage, monkeypatch, direction):
    database, _ = storage
    favorite_id = db_storage.save_favorite_page(database, "https://www.facebook.com/demo", "Demo")
    db_storage.finish_favorite_scan(
        database, favorite_id, status="Thành công", new_posts=0,
        cursor_post_ids=["new-marker"], successful=True,
    )
    db_storage.finish_favorite_archive_scan(
        database, favorite_id, status="Đã quét thêm bài cũ", saved_posts=1,
        cursor_post_ids=["old-marker"], successful=True,
    )
    install_abort_trigger(database)

    class FakeScraper:
        last_observed_post_ids = ["123456789012345", "223456789012345"]
        last_scan_complete = True
        last_scan_stop_reason = "complete"

        def __init__(self, account=None):
            pass

        def start(self):
            return True

        def stop(self):
            pass

        def scrape_page(self, **kwargs):
            return [post(value) for value in self.last_observed_post_ids]

    worker_id = "regression-worker"
    status = copy.deepcopy(scraper_routes._scrape_status)
    status.update(new_posts=0, queue_completed=0, queue_successful=0)
    status["workers"] = {worker_id: {"new_posts": 0}}
    monkeypatch.setattr(scraper_routes, "_scrape_status", status)
    monkeypatch.setattr(scraper_routes, "_stop_requested", threading.Event())
    monkeypatch.setattr(scraper_routes, "_favorite_worker_stop_events", {worker_id: threading.Event()})
    monkeypatch.setattr(scraper_routes, "_active_favorite_scrapers", {})
    monkeypatch.setattr(scraper_routes, "PageScraper", FakeScraper)
    queue = {
        "worker_id": worker_id, "favorite_ids": [favorite_id], "account_label": "Test",
        "scan_direction": direction, "download_media": True,
    }
    assert scraper_routes._run_favorite_worker(queue) == 0
    favorite = db_storage.get_favorite_page(database, favorite_id)
    assert favorite["cursor_post_ids"] == ["new-marker"]
    assert favorite["archive_cursor_post_ids"] == ["old-marker"]
    assert favorite["archive_scanned_count"] == 1
    assert favorite["last_status"] == "Lỗi"
    assert "simulated write failure" in favorite["last_error"]
    assert not queue.get("download_urls")


@pytest.mark.parametrize("kind", ["image", "video"])
@pytest.mark.parametrize("failure", ["network", "length", "small", "success"])
@pytest.mark.parametrize("existing", [False, True])
def test_direct_media_is_published_only_after_complete_response(tmp_path, monkeypatch, kind, failure, existing):
    destination = tmp_path / ("123456789012345.jpeg" if kind == "image" else "123456789012345.mp4")
    original = b"previous complete file"
    if existing:
        destination.write_bytes(original)
    payload = b"x" * (10 if failure == "small" else 20000)
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {"content-length": str(len(payload) + (100 if failure == "length" else 0))}

    def chunks(**kwargs):
        yield payload
        if failure == "network":
            raise httpx.ReadError("connection interrupted")

    response.iter_bytes.side_effect = chunks
    client = MagicMock()
    client.__enter__.return_value = client
    client.stream.return_value = response
    monkeypatch.setattr(media_downloader.httpx, "Client", lambda **kwargs: client)

    def progress(downloaded, total):
        assert destination.exists() == existing
        if existing:
            assert destination.read_bytes() == original
        assert list(tmp_path.glob("*.part"))

    download = media_downloader.download_image if kind == "image" else media_downloader.download_video_direct
    assert download("https://example.com/media", destination, {}, progress) == (failure == "success")
    assert not list(tmp_path.glob("*.part"))
    if failure == "success":
        assert destination.read_bytes() == payload
    elif existing:
        assert destination.read_bytes() == original
    else:
        assert not destination.exists()


def test_crashed_download_temporary_file_is_not_promoted_by_sync(storage):
    database, output = storage
    post_id = "123456789012345"
    db_storage.save_posts(database, "Demo", "https://www.facebook.com/demo", [post(post_id)])
    (output / f".{post_id}_1.jpeg.crash.part").write_bytes(b"partial media" * 100)
    (output / f"{post_id}.txt").write_text("caption", encoding="utf-8")
    db_storage.sync_downloaded_posts_from_folder(database, str(output))
    connection = db_storage._get_conn(database)
    assert connection.execute("SELECT downloaded FROM posts").fetchone()[0] == 0
    connection.close()


def test_cleanup_never_terminates_foreign_port_listener(tmp_path, monkeypatch):
    foreign = MagicMock()
    foreign.pid = 20001
    foreign.name.return_value = "python.exe"
    foreign.cwd.return_value = str(tmp_path / "other-project")
    foreign.exe.return_value = "C:/Python311/python.exe"
    foreign.cmdline.return_value = ["python", str(tmp_path / "other-project" / "main.py")]
    workspace = tmp_path / "tinix-project"
    workspace.mkdir()
    owned = MagicMock()
    owned.pid = 20002
    owned.name.return_value = "python.exe"
    owned.exe.return_value = "C:/Python311/python.exe"
    owned.cwd.return_value = str(workspace)
    owned.cmdline.return_value = ["python", str(workspace / "main.py")]
    connection = SimpleNamespace(laddr=SimpleNamespace(port=7866), pid=foreign.pid, status="LISTEN")
    monkeypatch.setattr(process_cleanup.psutil, "net_connections", lambda **kwargs: [connection])
    monkeypatch.setattr(process_cleanup.psutil, "Process", lambda pid: foreign)
    monkeypatch.setattr(process_cleanup.psutil, "process_iter", lambda *args: [foreign, owned])
    terminated = []

    def terminate(processes, **kwargs):
        terminated.extend(processes)
        return len(processes)

    monkeypatch.setattr(process_cleanup, "terminate_processes", terminate)
    monkeypatch.setattr(process_cleanup, "get_current_and_ancestor_pids", lambda: set())
    monkeypatch.setattr(process_cleanup, "is_port_in_use", lambda *args: True)
    monkeypatch.setattr(process_cleanup, "wait_for_port_free", lambda *args, **kwargs: False)
    result = process_cleanup.cleanup_previous_sessions(workspace_root=workspace, verbose=False)
    assert terminated == [owned]
    assert result["port_freed"] is False
    monkeypatch.setattr(process_cleanup, "cleanup_previous_sessions", lambda **kwargs: result)
    monkeypatch.setattr("sys.argv", ["process_cleanup.py", "--quiet"])
    assert process_cleanup.main() == 1


@pytest.mark.parametrize("install_failure", [False, True])
def test_restore_corrupt_db_preserves_original_and_sidecars(tmp_path, monkeypatch, install_failure):
    database = tmp_path / "corrupt.sqlite"
    backup = tmp_path / "valid.sqlite"
    db_storage.save_posts(str(backup), "Demo", "https://www.facebook.com/demo", [post("123456789012345")])
    originals = {
        "": b"corrupt database header" * 100,
        "-wal": b"original wal evidence",
        "-shm": b"original shm evidence",
        "-journal": b"original journal evidence",
    }
    for suffix, content in originals.items():
        Path(str(database) + suffix).write_bytes(content)
    if install_failure:
        replace = database_maintenance.os.replace

        def fail_install(source, target):
            if str(source).endswith(".restore.sqlite") and Path(target) == database:
                raise PermissionError("simulated restore installation failure")
            return replace(source, target)

        monkeypatch.setattr(database_maintenance.os, "replace", fail_install)
        with pytest.raises(PermissionError, match="simulated restore"):
            database_maintenance.restore_database(database, backup)
        safety = database
        assert not list(tmp_path.glob("*.corrupt-backup-*"))
    else:
        safety = Path(database_maintenance.restore_database(database, backup))
        assert database_maintenance.inspect_database(database)["integrity"] == "ok"
        connection = sqlite3.connect(database)
        assert connection.execute("SELECT post_id FROM posts").fetchall() == [("123456789012345",)]
        connection.close()
    for suffix, content in originals.items():
        assert Path(str(safety) + suffix).read_bytes() == content
    assert not list(tmp_path.glob("*.restore.sqlite"))


def test_invalid_backup_does_not_replace_corrupt_database(tmp_path):
    database = tmp_path / "corrupt.sqlite"
    backup = tmp_path / "invalid.sqlite"
    database.write_bytes(b"original corrupt bytes")
    backup.write_bytes(b"invalid backup")
    with pytest.raises(sqlite3.DatabaseError):
        database_maintenance.restore_database(database, backup)
    assert database.read_bytes() == b"original corrupt bytes"
