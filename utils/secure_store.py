"""Windows DPAPI-backed protection for local application secrets."""

from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes


PREFIX = "dpapi:v1:"
CRYPTPROTECT_UI_FORBIDDEN = 0x01


class SecretProtectionError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def is_protected(value: str) -> bool:
    return str(value or "").startswith(PREFIX)


def _require_windows():
    if sys.platform != "win32":
        raise SecretProtectionError("DPAPI secret protection is only available on Windows")
    return ctypes.windll.crypt32, ctypes.windll.kernel32


def _input_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def protect_secret(value: str) -> str:
    """Encrypt a string for the current Windows user; protected values are idempotent."""
    value = str(value or "")
    if not value or is_protected(value):
        return value
    crypt32, kernel32 = _require_windows()
    source, source_buffer = _input_blob(value.encode("utf-8"))
    output = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(source),
        "Tinix FB Studio",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output),
    )
    if not ok:
        raise SecretProtectionError(f"CryptProtectData failed: {ctypes.get_last_error()}")
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
        return PREFIX + base64.urlsafe_b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer


def unprotect_secret(value: str) -> str:
    """Decrypt a protected string. Legacy plaintext values pass through unchanged."""
    value = str(value or "")
    if not value or not is_protected(value):
        return value
    crypt32, kernel32 = _require_windows()
    try:
        encrypted = base64.urlsafe_b64decode(value[len(PREFIX):].encode("ascii"))
    except Exception as exc:
        raise SecretProtectionError("Invalid protected secret encoding") from exc
    source, source_buffer = _input_blob(encrypted)
    output = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output),
    )
    if not ok:
        raise SecretProtectionError(
            "Secret belongs to another Windows user or is corrupted"
        )
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer


def reveal_secret(value: str) -> str:
    """Best-effort decrypt for runtime consumers; never expose encrypted blobs as credentials."""
    try:
        return unprotect_secret(value)
    except SecretProtectionError:
        return ""
