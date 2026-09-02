from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


class ProfileBundleError(RuntimeError):
    pass


BUNDLE_FORMAT = "tinix-profile"
BUNDLE_VERSION = 1
COLLECTION_FORMAT = "tinix-profiles"
COLLECTION_VERSION = 1
MAX_ARCHIVE_FILES = 250_000
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024 * 1024
CACHE_DIRECTORIES = {
    "cache", "code cache", "gpucache", "shadercache", "grshadercache",
    "dawncache", "crashpad", "component_crx_cache",
}
LOCK_FILES = {"singletonlock", "singletoncookie", "singletonsocket", "lockfile"}
REPARSE_POINT = 0x400


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _is_reparse(path: Path) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
        return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & REPARSE_POINT)
    except OSError as exc:
        raise ProfileBundleError(f"Không thể đọc đường dẫn: {path}") from exc


def _chrome_uses_path(path: Path) -> bool:
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            if "chrome" not in (process.info.get("name") or "").lower():
                continue
            for argument in process.info.get("cmdline") or []:
                if argument.lower().startswith("--user-data-dir="):
                    current = Path(argument.split("=", 1)[1].strip('"'))
                    if _same_path(current, path):
                        return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return False


def validate_chrome_profile(path: Path) -> None:
    if not path.is_absolute() or not path.is_dir():
        raise ProfileBundleError("Thư mục Chrome profile không tồn tại.")
    if _is_reparse(path):
        raise ProfileBundleError("Không hỗ trợ profile là symlink/junction/reparse point.")
    markers = [path / "Local State", path / "Default" / "Preferences"]
    markers.extend(path.glob("Profile */Preferences"))
    if not any(marker.is_file() for marker in markers):
        raise ProfileBundleError("Không nhận diện được Chrome user-data directory.")


def _copy_tree(source: Path, destination: Path) -> tuple[int, int]:
    files = 0
    total = 0
    destination.mkdir(parents=True, exist_ok=False)

    def copy_directory(current_source: Path, current_destination: Path) -> None:
        nonlocal files, total
        with os.scandir(current_source) as entries:
            for entry in entries:
                source_item = Path(entry.path)
                lowered = entry.name.lower()
                if lowered in LOCK_FILES:
                    continue
                if _is_reparse(source_item):
                    raise ProfileBundleError(f"Profile chứa symlink/junction không an toàn: {source_item}")
                if entry.is_dir(follow_symlinks=False):
                    if lowered in CACHE_DIRECTORIES:
                        continue
                    destination_item = current_destination / entry.name
                    destination_item.mkdir()
                    copy_directory(source_item, destination_item)
                elif entry.is_file(follow_symlinks=False):
                    size = entry.stat(follow_symlinks=False).st_size
                    shutil.copy2(source_item, current_destination / entry.name)
                    files += 1
                    total += size

    copy_directory(source, destination)
    return files, total


def _safe_label(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return clean[:60] or "profile"


def read_bundle(bundle_path: str) -> tuple[Path, dict[str, Any], Path]:
    bundle = Path(os.path.expandvars(os.path.expanduser(bundle_path))).resolve()
    if not bundle.is_absolute() or not bundle.is_dir() or _is_reparse(bundle):
        raise ProfileBundleError("Gói Tinix profile không tồn tại hoặc không an toàn.")
    try:
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileBundleError("Gói profile thiếu manifest.json hợp lệ.") from exc
    if manifest.get("bundle_format") != BUNDLE_FORMAT or manifest.get("format_version") != BUNDLE_VERSION:
        raise ProfileBundleError("Định dạng gói Tinix profile không được hỗ trợ.")
    name = str(manifest.get("account_name") or "").strip()
    platform = str(manifest.get("platform") or "").strip().lower()
    if not name or len(name) > 200:
        raise ProfileBundleError("Tên account trong manifest không hợp lệ.")
    if not platform:
        raise ProfileBundleError("Manifest thiếu nền tảng account.")
    profile = (bundle / "chrome-profile").resolve()
    if profile.parent != bundle:
        raise ProfileBundleError("Đường dẫn Chrome profile trong gói không hợp lệ.")
    validate_chrome_profile(profile)
    return bundle, manifest, profile


def export_bundle(source: Path, export_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    source = source.resolve()
    validate_chrome_profile(source)
    if _chrome_uses_path(source):
        raise ProfileBundleError("Chrome đang sử dụng profile; hãy đóng Chrome trước khi Export.")
    export_root = export_root.resolve()
    export_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    destination = export_root / f"{_safe_label(str(manifest['account_name']))}-{timestamp}.tinix-profile"
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=export_root))
    try:
        files, size = _copy_tree(source, staging / "chrome-profile")
        validate_chrome_profile(staging / "chrome-profile")
        payload = {
            "bundle_format": BUNDLE_FORMAT,
            "format_version": BUNDLE_VERSION,
            **manifest,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        (staging / "manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(staging, destination)
        return {"bundle_path": str(destination), "files_copied": files, "bytes_copied": size}
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def import_bundle_profile(bundle_path: str, destination: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    _, manifest, source = read_bundle(bundle_path)
    destination = destination.resolve()
    if destination.exists():
        raise ProfileBundleError(f"Profile đích đã tồn tại: {destination}")
    if _chrome_uses_path(source):
        raise ProfileBundleError("Chrome đang sử dụng profile trong gói; hãy đóng Chrome trước khi Import.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-import-", dir=destination.parent))
    staging.rmdir()
    try:
        files, size = _copy_tree(source, staging)
        validate_chrome_profile(staging)
        os.replace(staging, destination)
        return manifest, {"profile_path": str(destination), "files_copied": files, "bytes_copied": size}
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def export_profiles_archive(
    profiles: list[tuple[Path, dict[str, Any]]],
    export_root: Path,
    *,
    source_app: str,
    source_app_version: str,
) -> dict[str, Any]:
    if not profiles:
        raise ProfileBundleError("App chưa có account để Export.")
    resolved: list[tuple[Path, dict[str, Any]]] = []
    for source, metadata in profiles:
        source = source.resolve()
        name = str(metadata.get("account_name") or "").strip()
        platform = str(metadata.get("platform") or "").strip().lower()
        if not name or not platform:
            raise ProfileBundleError("Metadata account Export không hợp lệ.")
        validate_chrome_profile(source)
        if _chrome_uses_path(source):
            raise ProfileBundleError(f"Chrome đang sử dụng profile “{name}”; hãy đóng Chrome trước khi Export.")
        resolved.append((source, metadata))

    export_root = export_root.resolve()
    export_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    destination = export_root / f"Tinix-FB-Down-all-profiles-{timestamp}.tinix-profiles.zip"
    staging = Path(tempfile.mkdtemp(prefix=".tinix-profiles-", dir=export_root))
    temporary_zip = destination.with_suffix(destination.suffix + ".tmp")
    files = 0
    size = 0
    accounts: list[dict[str, Any]] = []
    try:
        for index, (source, metadata) in enumerate(resolved, 1):
            relative = f"profiles/{index:04d}"
            copied_files, copied_size = _copy_tree(source, staging / relative)
            files += copied_files
            size += copied_size
            accounts.append({**metadata, "profile_path": relative})
        manifest = {
            "bundle_format": COLLECTION_FORMAT,
            "format_version": COLLECTION_VERSION,
            "source_app": source_app,
            "source_app_version": source_app_version,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "accounts": accounts,
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with zipfile.ZipFile(temporary_zip, "w", zipfile.ZIP_DEFLATED, allowZip64=True, compresslevel=6) as archive:
            for item in staging.rglob("*"):
                if item.is_file():
                    archive.write(item, item.relative_to(staging).as_posix())
        os.replace(temporary_zip, destination)
    except Exception:
        if temporary_zip.exists():
            temporary_zip.unlink()
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {
        "archive_path": str(destination), "bundle_path": str(destination),
        "accounts_exported": len(accounts), "files_copied": files, "bytes_copied": size,
    }


def _extract_archive(archive_path: str, destination: Path) -> None:
    archive = Path(os.path.expandvars(os.path.expanduser(archive_path))).resolve()
    if not archive.is_absolute() or not archive.is_file() or _is_reparse(archive):
        raise ProfileBundleError("File ZIP Tinix profile không tồn tại hoặc không an toàn.")
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > MAX_ARCHIVE_FILES or sum(item.file_size for item in entries) > MAX_ARCHIVE_BYTES:
                raise ProfileBundleError("File ZIP vượt giới hạn an toàn.")
            root = destination.resolve()
            seen: set[str] = set()
            copied = 0
            for item in entries:
                relative = item.filename.replace("\\", "/").strip("/")
                parts = [part for part in relative.split("/") if part]
                if not parts:
                    continue
                if any(part in {".", ".."} for part in parts) or ":" in parts[0]:
                    raise ProfileBundleError("File ZIP chứa đường dẫn không an toàn.")
                key = "/".join(parts).lower()
                if key in seen:
                    raise ProfileBundleError("File ZIP chứa đường dẫn trùng lặp.")
                seen.add(key)
                if ((item.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ProfileBundleError("File ZIP chứa symlink không an toàn.")
                target = (root.joinpath(*parts)).resolve()
                if root not in target.parents and target != root:
                    raise ProfileBundleError("File ZIP chứa đường dẫn vượt ra ngoài thư mục giải nén.")
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        copied += len(chunk)
                        if copied > MAX_ARCHIVE_BYTES:
                            raise ProfileBundleError("File ZIP vượt giới hạn dung lượng giải nén 100 GB.")
                        output.write(chunk)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ProfileBundleError("Không đọc được file ZIP Tinix profile.") from exc


@contextmanager
def extracted_profiles_archive(archive_path: str):
    extraction = Path(tempfile.mkdtemp(prefix="tinix-profiles-import-"))
    try:
        _extract_archive(archive_path, extraction)
        try:
            manifest = json.loads((extraction / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileBundleError("File ZIP thiếu manifest.json hợp lệ.") from exc
        if manifest.get("bundle_format") != COLLECTION_FORMAT or manifest.get("format_version") != COLLECTION_VERSION:
            raise ProfileBundleError("Định dạng ZIP đa profile không được hỗ trợ.")
        raw_accounts = manifest.get("accounts")
        if not isinstance(raw_accounts, list) or not raw_accounts or len(raw_accounts) > 10_000:
            raise ProfileBundleError("Danh sách account trong ZIP không hợp lệ.")
        profiles_root = (extraction / "profiles").resolve()
        entries: list[tuple[dict[str, Any], Path]] = []
        for raw in raw_accounts:
            if not isinstance(raw, dict):
                raise ProfileBundleError("Metadata account trong ZIP không hợp lệ.")
            name = str(raw.get("account_name") or "").strip()
            platform = str(raw.get("platform") or "").strip().lower()
            relative = str(raw.get("profile_path") or "").replace("\\", "/").strip("/")
            profile = (extraction / relative).resolve()
            if not name or len(name) > 200 or not platform or profiles_root not in profile.parents or profile == profiles_root:
                raise ProfileBundleError("Metadata hoặc đường dẫn profile trong ZIP không hợp lệ.")
            validate_chrome_profile(profile)
            entries.append(({**raw, "account_name": name, "platform": platform}, profile))
        yield manifest, entries
    finally:
        shutil.rmtree(extraction, ignore_errors=True)


def import_profile_from_directory(source: Path, destination: Path) -> dict[str, Any]:
    source = source.resolve()
    destination = destination.resolve()
    validate_chrome_profile(source)
    if destination.exists():
        raise ProfileBundleError(f"Profile đích đã tồn tại: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-import-", dir=destination.parent))
    staging.rmdir()
    try:
        files, size = _copy_tree(source, staging)
        validate_chrome_profile(staging)
        os.replace(staging, destination)
        return {"profile_path": str(destination), "files_copied": files, "bytes_copied": size}
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
