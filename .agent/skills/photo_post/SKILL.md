---
name: Photo Post
description: Skill để post bài hình ảnh hoặc chỉ caption lên Facebook và Instagram — bao gồm composer automation, media upload strategies, scheduling, và các pattern đã verified.
---

# Photo Post (Facebook & Instagram)

## Runtime Status

This skill folder is reference-only. The app does not import or execute files from `.agent/skills` at runtime.

Runtime code lives in:
- `gui/social_post_tab.py`
- `core/auto_poster.py`
- `core/content_scanner.py`
- `core/video_post_dispatcher.py`
- `core/db_storage.py`

When improving the Photo Post job, update the runtime files first. After a meaningful behavior change, update this `SKILL.md` so the reference stays current.

## Tổng quan

Module `core/auto_poster.py` (class `AutoPoster`) tự động đăng bài viết ảnh/caption lên Facebook Page qua **Meta Business Suite Composer**, sử dụng Playwright CDP connection tới Chrome profile có sẵn session.

## Kiến trúc

### Core Files

| File | Vai trò |
|------|---------|
| `core/auto_poster.py` | **AutoPoster engine** — browser automation, upload, schedule |
| `core/content_scanner.py` | Scan thư mục media, phân loại ảnh/video |
| `gui/social_post_tab.py` | UI tab Social Post |
| `core/video_post_dispatcher.py` | Job dispatcher cho multi-account posting |

### Data Flow

```
User chọn folder + caption + schedule time + target page
                    ↓
AutoPoster.start()
  ├── Chrome CDP (persistent profile, NOT headless)
  ├── Login check (cookie/username+password)
  └── AutoPoster.post_content() hoặc post_now()
      ├── brand_media_to_temp() → Copy + EXIF branding
      ├── _navigate_to_composer() → Switch page + open composer
      │   ├── Navigate to Business Suite home
      │   ├── _is_correct_bs_page() → Check current page
      │   ├── _switch_bs_asset() → Open dropdown → click target page
      │   └── Navigate to /latest/composer
      ├── _upload_media() → Multi-method file upload
      ├── _enter_caption() → Type/paste caption
      ├── _toggle_cta() → Optional "Gửi tin nhắn" button
      ├── _toggle_share_to_story() → Share as Story
      ├── _set_schedule() / _click_publish_now()
      └── cleanup_temp()
```

## Anti-Detection

### Critical Rules

1. **NEVER run headless** — Facebook detects headless via GPU fingerprint, breaks React events and file choosers
2. **Random delays** between every action: `_random_delay(min, max)` → `time.sleep(random.uniform(min, max))`
3. **Human-like typing** for short captions (<200 chars): char-by-char with 20-60ms delay + random pauses
4. **Long captions** (>200 chars): use `keyboard.insert_text()` (paste) for speed
5. **Window position forced**: `--window-position=60,60` to avoid off-screen from stale profile

### Chrome Launch Args
```
--remote-debugging-port=9226
--user-data-dir=<profile_dir>
--no-first-run
--no-default-browser-check
--disable-popup-blocking
--disable-blink-features=AutomationControlled
--window-size=1280,900
--window-position=60,60
```

## EXIF Metadata Branding

Trước khi upload, copy media sang thư mục temp và ghi EXIF metadata:

```python
# Sử dụng piexif library
exif_dict["0th"][ImageIFD.ImageDescription] = brand_name
exif_dict["0th"][ImageIFD.Artist] = brand_name
exif_dict["0th"][ImageIFD.Copyright] = brand_name
exif_dict["Exif"][ExifIFD.UserComment] = b"ASCII\x00\x00\x00" + brand_name
```

**Chỉ áp dụng cho `.jpg/.jpeg`**, các format khác skip.

## Page Switching (Business Suite)

### Flow

1. Navigate to `business.facebook.com/latest/home`
2. Check if already on correct page:
   - URL contains `page_id`
   - Switcher button text matches `page_name`
3. If need switch: `_switch_bs_asset()`
   - Click asset switcher dropdown (7 selectors tried)
   - Click matching page in list (exact → partial text match)
4. Navigate to `business.facebook.com/latest/composer`

### Asset Switcher Selectors (Priority)
```
div[aria-label*="Chuyển tài sản"]
div[aria-label*="Switch asset"]
div[aria-label*="tài sản"]
button[aria-label*="tài sản"]
[role="combobox"]
[aria-haspopup="listbox"]
[aria-haspopup="dialog"]
```

## Media Upload (4 Methods)

### Method Chain (try in order):

```
M2: Layout A — Direct file chooser
    photo_loc.click() → expect_file_chooser → set_files()
    
M3: Layout B — Dropdown then sub-option
    photo_loc.click() → dropdown opens
    click "Tải lên từ máy tính" → expect_file_chooser → set_files()

M3b: Re-open dropdown retry
    photo_loc.click() again → find sub-option → chooser

M4: Input fallback
    Find <input type="file"> → set_input_files() directly
```

### Photo Button Texts (tried in order)
```
"Thêm ảnh/video", "Thêm ảnh", "Thêm video", "Ảnh/video",
"File phương tiện", "Add Photo", "Add photo", "Photo/video",
"Add photo/video", "Add photos/videos"
```

### Upload Sub-option Texts
```
"Tải lên từ máy tính", "Upload from computer",
"Tải ảnh lên", "Upload Photos", "Upload photo",
"Upload", "From computer", "Ảnh từ máy tính"
```

### Important: Clear Existing Media First
Facebook restores drafts from previous sessions. Must call `_clear_existing_media()` **twice** before uploading (some items only appear after first removal animation).

## Caption Entry

### Selectors (priority)
```
[aria-label*="Write something"]
[aria-label*="Viết gì đó"]
[aria-label*="What's on your mind"]
[role="textbox"]
div[contenteditable="true"]
```

### Typing Strategy
- **Short caption** (<200 chars): Character-by-character, 20-60ms delay per char, 5% chance of random pause
- **Long caption** (≥200 chars): `keyboard.insert_text()` (instant paste)

## CTA Button ("Gửi tin nhắn")

3 strategies to set CTA:

1. **Native `<select>`**: `select_option(label="Gửi tin nhắn")`
2. **Click dropdown text**: Find "Không dùng nút" → click → select "Gửi tin nhắn"
3. **Label walking**: Find "Nhãn nút" label → walk ancestors → find adjacent dropdown → click option

## Share to Story

Toggle the "Chia sẻ lên Tin" switch, then confirm the dialog if it appears.

## Scheduling

### Flow
1. Enable "Đặt ngày và giờ" toggle (JS walk from label to nearest `[role="switch"]`)
2. Pick date via calendar navigation (month/year arrows + day click)
3. Fill time field (`HH:MM` format)

### Publish Now
Button selectors:
```
button:has-text("Publish")
button:has-text("Đăng")
button:has-text("Post")
[aria-label="Publish"]
[aria-label*="Đăng bài"]
```

## Business ID Resolution

Needed for Reel Composer URL. 4 strategies:

1. **Open tabs**: Check existing Business Suite tabs for `business_id` query param
2. **URL query params**: After navigating to BS home
3. **URL path segment**: `business.facebook.com/<numeric_id>/`
4. **HTML source regex**: `"business_id":"<id>"` patterns

## Error Handling

- **Screenshots on error**: `_screenshot_error(page, "tag")` saves PNG to `_debug_screenshots/`
  - Filename: `error_{tag}_{YYYYMMDD_HHMMSS}.png`
- **Temp cleanup**: Always in `finally` block via `cleanup_temp(temp_dir)`
- **Stop support**: `_stop_event` checked between every major step

## Debug Tips

- Upload fails → check `error_before_upload_*.png` screenshot
- Caption not entered → verify composer loaded (networkidle wait)
- Page switch fails → check dropdown screenshot, may need new selector
- Schedule toggle not found → Facebook UI may have changed labels
- `_last_error` attribute stores last exception message for UI display
