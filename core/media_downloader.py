"""
Tinix Facebook Down — Media Downloader
Downloads images and videos from extracted URLs.
"""

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from core.cookie_handler import format_cookies_for_ytdlp
from utils import logger

# Download chunk size
CHUNK_SIZE = 65536  # 64KB for images

# Timeout for media downloads
DOWNLOAD_TIMEOUT = 120.0

# User agent for downloads
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def save_text_content(text: str, save_path: Path) -> bool:
    """
    Save post text content to a .txt file.

    Args:
        text: The post text content.
        save_path: Full path to the output .txt file.

    Returns:
        True if saved successfully.
    """
    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(text)
        logger.info(f"Đã lưu text: {save_path.name}")
        return True
    except IOError as e:
        logger.error(f"Lỗi lưu text: {e}")
        return False


def download_image(
    url: str,
    save_path: Path,
    cookies: Dict[str, str],
    progress_callback: Optional[Callable] = None,
) -> bool:
    """
    Download a single image.

    Args:
        url: Image URL (typically scontent CDN).
        save_path: Full path to save the image.
        cookies: Facebook cookies for authentication.
        progress_callback: Optional callback(bytes_downloaded, total_bytes).

    Returns:
        True if download was successful.
    """
    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Determine file extension from URL or content type
        ext = _get_extension_from_url(url) or ".jpg"
        if not save_path.suffix:
            save_path = save_path.with_suffix(ext)

        with httpx.Client(
            cookies=cookies,
            headers={"User-Agent": USER_AGENT},
            timeout=DOWNLOAD_TIMEOUT,
            follow_redirects=True,
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()

                total = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(save_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            progress_callback(downloaded, total)

        # Verify file is not empty
        if save_path.stat().st_size < 100:
            logger.warning(f"Ảnh tải về quá nhỏ, có thể bị lỗi: {save_path.name}")
            return False

        logger.info(f"Đã tải ảnh: {save_path.name} ({_format_size(save_path.stat().st_size)})")
        return True

    except httpx.HTTPStatusError as e:
        logger.error(f"Lỗi HTTP {e.response.status_code} khi tải ảnh: {save_path.name}")
        return False
    except httpx.TimeoutException:
        logger.error(f"Hết thời gian chờ khi tải ảnh: {save_path.name}")
        return False
    except Exception as e:
        logger.error(f"Lỗi tải ảnh {save_path.name}: {str(e)[:100]}")
        return False


def download_video_direct(
    url: str,
    save_path: Path,
    cookies: Dict[str, str],
    progress_callback: Optional[Callable] = None,
) -> bool:
    """
    Download a video directly from a CDN URL (e.g. from DASH manifest BaseURL).
    Uses proper Facebook headers to avoid 403 errors.

    Args:
        url: Direct video CDN URL (scontent/fbcdn).
        save_path: Full path to save the video file.
        cookies: Facebook cookies for authentication.
        progress_callback: Optional callback(bytes_downloaded, total_bytes).

    Returns:
        True if download was successful.
    """
    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)

        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.facebook.com/",
            "Origin": "https://www.facebook.com",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "video",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        }

        with httpx.Client(
            cookies=cookies,
            headers=headers,
            timeout=300.0,  # 5 min timeout for videos
            follow_redirects=True,
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()

                total = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(save_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=131072):  # 128KB chunks for video
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            progress_callback(downloaded, total)

        file_size = save_path.stat().st_size
        if file_size < 10000:  # Video should be at least 10KB
            logger.warning(f"Video tải về quá nhỏ ({_format_size(file_size)}), có thể bị lỗi")
            # Try to read content to see if it's an error page
            try:
                with open(save_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(500)
                if "<html" in content.lower() or "error" in content.lower():
                    logger.error("File tải về là trang lỗi, không phải video")
                    save_path.unlink(missing_ok=True)
                    return False
            except Exception:
                pass
            save_path.unlink(missing_ok=True)
            return False

        logger.info(f"Đã tải video: {save_path.name} ({_format_size(file_size)})")
        return True

    except httpx.HTTPStatusError as e:
        logger.error(f"Lỗi HTTP {e.response.status_code} khi tải video: {save_path.name}")
        return False
    except httpx.TimeoutException:
        logger.error(f"Hết thời gian chờ khi tải video")
        return False
    except Exception as e:
        logger.error(f"Lỗi tải video {save_path.name}: {str(e)[:100]}")
        return False


def download_video(
    post_url: str,
    save_dir: Path,
    cookies: Dict[str, str],
    progress_callback: Optional[Callable] = None,
) -> bool:
    """
    Download video from a Facebook post using yt-dlp.

    Args:
        post_url: Original Facebook post URL (www.facebook.com).
        save_dir: Directory to save the video.
        cookies: Facebook cookies for authentication.
        progress_callback: Optional callback(status_text).

    Returns:
        True if download was successful.
    """
    try:
        save_dir.mkdir(parents=True, exist_ok=True)

        # Create a temporary cookie file for yt-dlp
        cookie_content = format_cookies_for_ytdlp(cookies)
        cookie_file = None

        try:
            # Write cookies to temp file
            cookie_file = tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".txt",
                prefix="tinix_cookies_",
                delete=False,
                encoding="utf-8",
            )
            cookie_file.write(cookie_content)
            cookie_file.close()

            # Build yt-dlp command
            output_template = str(save_dir / "video_%(autonumber)03d.%(ext)s")

            cmd = [
                _get_ytdlp_path(),
                "--cookies", cookie_file.name,
                "-o", output_template,
                "--no-playlist",
                "--merge-output-format", "mp4",
                "--no-warnings",
                "--no-check-certificates",
                "--retries", "3",
                "--user-agent", USER_AGENT,
                post_url,
            ]

            logger.info("Đang tải video bằng yt-dlp...")

            if progress_callback:
                progress_callback("Đang tải video...")

            # Run yt-dlp
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout for large videos
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            if result.returncode == 0:
                # Find downloaded video files
                video_files = list(save_dir.glob("video_*"))
                if video_files:
                    for vf in video_files:
                        logger.info(f"Đã tải video: {vf.name} ({_format_size(vf.stat().st_size)})")
                    return True
                else:
                    logger.warning("yt-dlp hoàn thành nhưng không tìm thấy file video")
                    return False
            else:
                error_msg = result.stderr.strip()[:200] if result.stderr else "Unknown error"
                logger.error(f"yt-dlp thất bại: {error_msg}")
                return False

        finally:
            # Clean up temp cookie file
            if cookie_file and os.path.exists(cookie_file.name):
                try:
                    os.unlink(cookie_file.name)
                except OSError:
                    pass

    except subprocess.TimeoutExpired:
        logger.error("Tải video quá thời gian (> 10 phút)")
        return False
    except FileNotFoundError:
        logger.error("Không tìm thấy yt-dlp. Đảm bảo yt-dlp đã được cài đặt.")
        return False
    except Exception as e:
        logger.error(f"Lỗi tải video: {str(e)[:200]}")
        return False


def _get_ytdlp_path() -> str:
    """Get the path to yt-dlp executable."""
    if getattr(sys, 'frozen', False):
        # When bundled with PyInstaller, yt-dlp should be in the same directory
        bundled = Path(sys.executable).parent / "yt-dlp.exe"
        if bundled.exists():
            return str(bundled)
    # Fall back to system yt-dlp
    return "yt-dlp"


def _get_extension_from_url(url: str) -> Optional[str]:
    """Extract file extension from a URL."""
    parsed = urlparse(url)
    path = parsed.path.lower()

    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        if path.endswith(ext):
            return ext

    # Check for Facebook CDN URLs that may have extension in query
    if "scontent" in url:
        return ".jpg"  # Facebook images are typically JPEG

    return None


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
