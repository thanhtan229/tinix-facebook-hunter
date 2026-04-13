# core/video_poster.py
"""
VideoPoster module – handles posting video content to multiple platforms.
Current implementation focuses on Facebook Reels; other platforms are placeholders for future expansion.
"""
import os
import subprocess
import logging
from pathlib import Path
from typing import List, Optional

from utils import logger

# Constants
FB_REELS_COMPOSER_URL = "https://business.facebook.com/latest/reels_composer/?asset_id={asset_id}&business_id={business_id}&ir_qe_exposed=1"

class VideoPoster:
    def __init__(self, auto_poster):
        """Receive a reference to the existing AutoPoster instance to reuse its browser context and utilities."""
        self.auto_poster = auto_poster
        self.context = auto_poster._context
        self._stop_event = auto_poster._stop_event

    # ---------------------------------------------------------------------
    # Thumbnail handling
    # ---------------------------------------------------------------------
    def generate_thumbnail(self, video_path: str) -> Optional[str]:
        """Generate a thumbnail from the first second of the video using ffmpeg.
        Returns the path to the thumbnail image if successful, otherwise None.
        """
        try:
            thumb_path = Path(video_path).with_suffix('.jpg')
            # ffmpeg -ss 00:00:01 -i input.mp4 -frames:v 1 output.jpg
            cmd = [
                "ffmpeg",
                "-y",  # overwrite
                "-ss", "00:00:01",
                "-i", video_path,
                "-frames:v", "1",
                str(thumb_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and thumb_path.is_file():
                logger.info(f"✅ Thumbnail generated: {thumb_path}")
                return str(thumb_path)
            else:
                logger.warning(f"Thumbnail generation failed for {video_path}: {result.stderr.strip()}")
        except Exception as e:
            logger.error(f"Exception during thumbnail generation: {e}")
        return None

    def select_thumbnail(self, folder_path: str) -> str:
        """Select thumbnail for a video post.
        1. Try to generate from the first video file in the folder.
        2. If generation fails, pick the first image file in the folder.
        3. If no image, fall back to a placeholder asset.
        """
        folder = Path(folder_path)
        # Find first video file
        video_file = next((f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in {".mp4", ".mov"}), None)
        if video_file:
            thumb = self.generate_thumbnail(str(video_file))
            if thumb:
                return thumb
        # Fallback: first image file
        image_file = next((f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in {".jpg", ".jpeg", ".png"}), None)
        if image_file:
            return str(image_file)
        # Final fallback: placeholder asset bundled with the project
        placeholder = Path(__file__).parent.parent / "assets" / "video_placeholder.png"
        if placeholder.is_file():
            return str(placeholder)
        # As a last resort, return empty string (caller should handle)
        return ""

    # ---------------------------------------------------------------------
    # Facebook Reels posting
    # ---------------------------------------------------------------------
    def post_to_facebook_reel(
        self,
        page_id: str,
        page_name: str,
        folder_path: str,
        caption: str,
        scheduled_time: Optional[str] = None,
        cta_enabled: bool = False,
        share_to_story: bool = True,
        on_status: Optional[callable] = None,
    ) -> bool:
        """Perform the full Reel posting flow using Playwright.
        Returns True on success, False otherwise.
        """
        if not self.context:
            logger.error("Browser context not initialized for VideoPoster.")
            return False
        try:
            # Resolve business ID via AutoPoster helper
            business_id = self.auto_poster._business_id or ""
            asset_id = page_id  # For Reels Composer the asset_id is the page id
            url = FB_REELS_COMPOSER_URL.format(asset_id=asset_id, business_id=business_id)
            if on_status:
                on_status("🌐 Opening Facebook Reels Composer...")
            page = self.context.new_page()
            page.set_default_timeout(30000)
            page.goto(url, wait_until="domcontentloaded")
            # Wait for the composer UI to load
            self.auto_poster._random_delay(3, 5)

            # Upload video
            if on_status:
                on_status("📎 Uploading video file...")
            video_path = next(
                (str(p) for p in Path(folder_path).iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".mov"}),
                None,
            )
            if not video_path:
                logger.error("No video file found in folder for Reel posting.")
                return False
            # Click "Thêm video" button – selector may vary; using a generic file input
            file_input = page.locator('input[type="file"]').first
            file_input.set_input_files(video_path)
            self.auto_poster._random_delay(2, 4)

            # Caption
            if caption:
                if on_status:
                    on_status("📝 Entering caption...")
                self.auto_poster._enter_caption(page, caption)
                self.auto_poster._random_delay(1, 2)

            # CTA button (Send Message)
            if cta_enabled:
                if on_status:
                    on_status("💬 Adding CTA button...")
                self.auto_poster._toggle_cta(page)
                self.auto_poster._random_delay(1, 2)

            # Thumbnail handling – Facebook Reels allows custom thumbnail via a button
            thumb_path = self.select_thumbnail(folder_path)
            if thumb_path:
                if on_status:
                    on_status("🖼 Setting thumbnail...")
                # Click thumbnail button then upload image
                thumb_btn = page.get_by_text("Thêm hình thu nhỏ").first
                if thumb_btn.is_visible():
                    thumb_btn.click()
                    self.auto_poster._random_delay(1, 2)
                    thumb_input = page.locator('input[type="file"]').first
                    thumb_input.set_input_files(thumb_path)
                    self.auto_poster._random_delay(1, 2)
                else:
                    logger.warning("Thumbnail button not found – skipping custom thumbnail.")

            # Scheduling – reuse AutoPoster schedule helper
            if scheduled_time:
                if on_status:
                    on_status(f"📅 Scheduling for {scheduled_time}...")
                success = self.auto_poster._set_schedule(page, scheduled_time)
                if not success:
                    logger.error("Failed to set schedule for Reel.")
                    return False

            # Final share / post
            if on_status:
                on_status("✅ Confirming and sharing Reel...")
            # Click the primary share button – selector may be "Đăng" or similar
            share_btn = page.get_by_role("button", name="Đăng").first
            if not share_btn.is_visible():
                share_btn = page.get_by_role("button", name="Share").first
            share_btn.click()
            self.auto_poster._random_delay(3, 5)
            logger.info("✅ Reel posted successfully.")
            return True
        except Exception as e:
            logger.error(f"Exception in post_to_facebook_reel: {e}")
            return False
        finally:
            try:
                page.close()
            except Exception:
                pass

    # ---------------------------------------------------------------------
    # Placeholder methods for future platforms
    # ---------------------------------------------------------------------
    def post_to_tiktok(self, *args, **kwargs):
        logger.info("TikTok posting not yet implemented.")
        return False

    def post_to_instagram(self, *args, **kwargs):
        logger.info("Instagram posting not yet implemented.")
        return False

    def post_to_zalo(self, *args, **kwargs):
        logger.info("Zalo video posting not yet implemented.")
        return False

    def post_to_youtube(self, *args, **kwargs):
        logger.info("YouTube posting not yet implemented.")
        return False

# Helper to instantiate a singleton for the current session
_video_poster_instance: Optional[VideoPoster] = None

def get_video_poster(auto_poster) -> VideoPoster:
    global _video_poster_instance
    if _video_poster_instance is None:
        _video_poster_instance = VideoPoster(auto_poster)
    return _video_poster_instance
