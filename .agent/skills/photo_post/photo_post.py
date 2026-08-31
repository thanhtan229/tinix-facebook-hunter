"""
Photo Post — Reference patterns & utilities.

Tập hợp các UI selectors, upload strategies, scheduling patterns,
và verified approaches dùng trong AutoPoster để post bài lên Facebook/Instagram.

Không import trực tiếp — dùng làm reference khi debug hoặc mở rộng.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# 1. CHROME CDP CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CDP_PORT_POSTER = 9226  # Tách biệt với scraper port (9224) và downloader (9223)

# CRITICAL: Do NOT run headless — Facebook detects it and breaks:
#   - React synthetic events
#   - File chooser API
#   - GPU fingerprinting
HEADLESS_ALLOWED = False

CHROME_EXTRA_ARGS = [
    "--window-size=1280,900",
    "--window-position=60,60",  # Prevents off-screen from stale profile state
]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. META BUSINESS SUITE URLS
# ═══════════════════════════════════════════════════════════════════════════════

URLS = {
    "home":     "https://business.facebook.com/latest/home",
    "composer": "https://business.facebook.com/latest/composer",
    "reels":    "https://business.facebook.com/latest/composer/reels",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ASSET SWITCHER SELECTORS
# ═══════════════════════════════════════════════════════════════════════════════

# Priority order for finding the page switcher dropdown button
SWITCHER_SELECTORS = [
    'div[aria-label*="Chuyển tài sản"]',
    'div[aria-label*="Switch asset"]',
    'div[aria-label*="tài sản"]',
    'button[aria-label*="tài sản"]',
    '[role="combobox"]',
    '[aria-haspopup="listbox"]',
    '[aria-haspopup="dialog"]',
]

# Selectors to verify current page is correct
PAGE_CHECK_SELECTORS = [
    '[aria-selected="true"]',
    '[aria-current="page"]',
]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. COMPOSER UPLOAD SELECTORS
# ═══════════════════════════════════════════════════════════════════════════════

# Photo/video add button texts (tried in order, exact=False)
PHOTO_BUTTON_TEXTS = [
    "Thêm ảnh/video", "Thêm ảnh", "Thêm video", "Ảnh/video",
    "File phương tiện", "Add Photo", "Add photo", "Photo/video",
    "Add photo/video", "Add photos/videos",
]

# Sub-option for "upload from computer" in dropdown layout
UPLOAD_SUB_OPTION_TEXTS = [
    "Tải lên từ máy tính", "Upload from computer",
    "Tải ảnh lên", "Upload Photos", "Upload photo",
    "Upload", "From computer", "Ảnh từ máy tính",
]

# Remove existing media buttons (clear drafts)
DELETE_MEDIA_SELECTORS = [
    '[aria-label="Xóa"]',
    '[aria-label="Xoá"]',
    '[aria-label="Remove"]',
    '[aria-label="Delete"]',
    '[aria-label="Gỡ"]',
    '[aria-label="Close"]',
    '[aria-label="Đóng"]',
    '[aria-label*="Xóa"][role="button"]',
    '[aria-label*="Remove"][role="button"]',
]

# Upload method chain explanation
UPLOAD_METHODS = """
M2 (Direct):    photo_loc.click() → file chooser opens directly
M3 (Dropdown):  photo_loc.click() → dropdown → sub-option click → chooser
M3b (Retry):    re-click photo_loc → try sub-options again
M4 (Input):     find <input type="file"> → set_input_files() directly
"""

# Supported media extensions
MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".mp4", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg"}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CAPTION INPUT SELECTORS
# ═══════════════════════════════════════════════════════════════════════════════

CAPTION_SELECTORS = [
    '[aria-label*="Write something"]',
    '[aria-label*="Viết gì đó"]',
    "[aria-label*=\"What's on your mind\"]",
    '[role="textbox"]',
    'div[contenteditable="true"]',
]

CAPTION_TYPING_RULES = """
- Short (<200 chars): Character-by-character, 20-60ms delay, 5% random pause
- Long (≥200 chars): keyboard.insert_text() (instant paste)
- Always click() + delay before typing
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 6. CTA BUTTON SELECTORS
# ═══════════════════════════════════════════════════════════════════════════════

CTA_TARGET_VALUES = [
    "Gửi tin nhắn", "Send Message", "Send message",
    "Nhận tin nhắn", "Get messages",
]

CTA_DROPDOWN_TRIGGERS = [
    "Không dùng nút",  # Current default value
    "No button",
    "None",
]

CTA_LABEL_ANCHORS = [
    "Nhãn nút",  # Section label
    "Button label",
    "Nút",
    "Button",
]


# ═══════════════════════════════════════════════════════════════════════════════
# 7. PUBLISH / SCHEDULE SELECTORS
# ═══════════════════════════════════════════════════════════════════════════════

PUBLISH_NOW_SELECTORS = [
    'button:has-text("Publish")',
    'button:has-text("Đăng")',
    'button:has-text("Post")',
    '[aria-label="Publish"]',
    '[aria-label*="Đăng bài"]',
    'div[role="button"]:has-text("Publish")',
    'div[role="button"]:has-text("Đăng")',
    'div[role="button"]:has-text("Post")',
]

SCHEDULE_TOGGLE_LABELS = [
    "đặt ngày và giờ",
    "set date and time",
    "schedule date",
]


# ═══════════════════════════════════════════════════════════════════════════════
# 8. EXIF BRANDING
# ═══════════════════════════════════════════════════════════════════════════════

EXIF_BRANDING_FIELDS = """
piexif fields used for branding:
  0th.ImageDescription = brand_name
  0th.Artist = brand_name
  0th.Copyright = brand_name
  Exif.UserComment = b"ASCII\\x00\\x00\\x00" + brand_name

Only .jpg/.jpeg files are branded (piexif requirement).
Files are copied to temp dir first — originals are never modified.
Temp dir: <app_dir>/_temp_uploads/post_XXXX/
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 9. BUSINESS ID RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════════

BUSINESS_ID_PATTERNS = [
    r'"business_id"\s*:\s*"(\d{6,})"',
    r'"businessId"\s*:\s*"(\d{6,})"',
    r'"global_scope_id"\s*:\s*"(\d{6,})"',
    r'business_id=(\d{6,})',
    r'global_scope_id=(\d{6,})',
]

BUSINESS_ID_RESOLUTION_ORDER = """
1. Open tabs: Check existing BS tabs for business_id query param
2. URL query params: After navigating to /latest/home
3. URL path segment: business.facebook.com/<numeric_id>/
4. HTML source regex: scan page content for business_id patterns
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 10. RANDOM DELAY RANGES
# ═══════════════════════════════════════════════════════════════════════════════

DELAY_RANGES = {
    "between_actions":      (1.5, 4.0),   # General between-step delay
    "after_page_load":      (3.0, 5.0),   # After composer/BS home loads
    "after_upload":         (2.0, 4.0),   # Wait for upload to process
    "after_caption":        (1.5, 3.0),   # After typing caption
    "before_confirm":       (2.0, 3.0),   # Before clicking schedule/publish
    "after_confirm":        (3.0, 5.0),   # After final button click
    "dropdown_open":        (0.8, 1.5),   # After opening a dropdown
    "type_pause":           (0.2, 0.5),   # Random pause during typing (5% chance)
}


# ═══════════════════════════════════════════════════════════════════════════════
# 11. KNOWN ISSUES & WORKAROUNDS
# ═══════════════════════════════════════════════════════════════════════════════

KNOWN_ISSUES = """
1. File chooser not triggered (headless mode)
   → MUST use visible Chrome window. --headless=new breaks file chooser API.

2. Draft media restored by Facebook  
   → Call _clear_existing_media() TWICE (animation delay hides items)

3. Caption input not found
   → Composer may not be fully loaded. Wait for networkidle + extra delay.

4. Page switch fails in Business Suite
   → Asset switcher dropdown may have been redesigned. Check screenshots.

5. Schedule toggle not working
   → JS walks from label text to [role="switch"]. FB may change labels.
   → Check Vietnamese/English label variations.

6. CTA dropdown not found
   → Walk from "Nhãn nút" label → ancestors → adjacent dropdown.
   → FB may restructure the DOM. Check error screenshots.

7. Upload button has 2 layouts:
   A) Click → file chooser directly (simpler pages)
   B) Click → dropdown → "Tải lên từ máy tính" → file chooser
   Both must be handled.

8. Instagram cross-posting
   → Business Suite composer has "Also post to Instagram" toggle.
   → Must be enabled separately; auto-detection not implemented.
"""
