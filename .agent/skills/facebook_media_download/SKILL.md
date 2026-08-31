---
name: Facebook Media Download
description: Skill để tải ảnh/video từ Facebook post — bao gồm pipeline architecture, browser strategies, video fallback chain, và các pattern đã verified.
---

# Facebook Media Download

## Runtime Status

This skill folder is reference-only. The app does not import or execute files from `.agent/skills` at runtime.

Runtime code lives in:
- `gui/app.py`
- `core/downloader.py`
- `core/facebook_parser.py`
- `core/media_downloader.py`
- `core/url_handler.py`
- `core/cookie_handler.py`

When improving the Facebook media download job, update the runtime files first. After a meaningful behavior change, update this `SKILL.md` so the reference stays current.

## Tổng quan

Module tải media từ Facebook post bằng cách:
1. Parse Facebook post URLs (nhiều formats) 
2. Mở post bằng Chrome (Playwright CDP) với cookies xác thực
3. Parse DOM + page source JS để extract text, images, video URLs
4. Download ảnh gốc full-res qua HTTP / video qua browser session / yt-dlp fallback

## Kiến trúc

### Core Files

| File | Vai trò |
|------|---------|
| `core/downloader.py` | **Orchestrator** — quản lý pipeline, threading, pause/stop |
| `core/facebook_parser.py` | **Parser** — Chrome CDP, parse DOM, extract media URLs |
| `core/media_downloader.py` | **Downloader** — HTTP download ảnh/video, yt-dlp fallback |
| `core/url_handler.py` | **URL utils** — validate, normalize, extract post ID |
| `core/cookie_handler.py` | **Cookie utils** — parse/validate Facebook cookies |

### Data Flow

```
URLs input → parse_urls() → validate + normalize → www.facebook.com format
                                                          ↓
DownloadOrchestrator.start()
  ├── Cookie validation
  ├── BrowserManager.start() → Chrome + Playwright CDP
  ├── For each URL:
  │   ├── BrowserManager.fetch_post(url)
  │   │   ├── page.goto(url)
  │   │   ├── _find_main_article() → locate post container
  │   │   ├── _extract_text() → post caption
  │   │   ├── _extract_images() → full-res image URLs
  │   │   └── _detect_video() → video URL from page source
  │   ├── Create output folder (post_id as name)
  │   ├── Download images via HTTP (httpx)
  │   └── Download video via 3-method fallback chain
  └── Final summary
```

## URL Handling

### Supported URL Formats

| Pattern | Example |
|---------|---------|
| `/username/posts/ID` | `facebook.com/tinix/posts/123456` |
| `/permalink.php?story_fbid=` | `facebook.com/permalink.php?story_fbid=123&id=456` |
| `/photo/?fbid=` | `facebook.com/photo/?fbid=123` |
| `/share/p/ID` | `facebook.com/share/p/abc123` |
| `/reel/ID` | `facebook.com/reel/123456` → converted to `/watch/?v=` |
| `/watch/?v=ID` | `facebook.com/watch/?v=123456` |
| `fb.watch/ID` | Short URL, kept as-is |
| `/username/videos/ID` | `facebook.com/user/videos/123` → converted to `/watch/?v=` |
| `pfbidXXX` | Generic pfbid pattern |
| Bare numeric ID | `836851975657298` → `facebook.com/836851975657298` |

### URL Normalization

```python
# Reel/Video → Watch format (for yt-dlp compatibility)
get_original_url("/reel/123456") → "https://www.facebook.com/watch/?v=123456"

# Strip tracking params, keep only essential
essential_keys = {'v', 'id', 'fbid', 'story_fbid', 'set', 'type', 'pfbid'}
```

## Post Parsing

### Article Detection (Priority Order)

1. **Dialog modal** (`role="dialog"`) — photo post permalinks
2. **Video page** — check for `<video>` element, use `role="main"` container
3. **Article** (`role="article"`) — standard feed posts
4. **Main content** (`role="main"`) — general fallback

### Text Extraction (5 Strategies)

1. **Watch page panel** — `#watch_feed` → `div[dir="auto"]` (video description)
2. **JSON from page source** — `"message":{"text":"..."}` nearest to `"video_id":"X"` 
3. **data-ad-comet-preview="message"** — Facebook's own attribute  
4. **data-ad-preview="message"** — alternate attribute
5. **`div[dir="auto"]`** — scan all auto-dir divs, skip UI labels

### Image Extraction

1. Find photo page links (`/photo`, `fbid=`) with substantial images (>100x100px)
2. Navigate to each photo page individually
3. Extract full-resolution image from `data-visualcompletion="media-vc-image"` img
4. Fallback: use `img[src*="scontent"]` from original article

### Video Detection & Download (3-Method Fallback)

```
Method 1: Browser session download
  └── BrowserManager.download_file(video_url)
      Uses authenticated browser session → bypasses CDN 403
      
Method 2: Direct HTTP download
  └── download_video_direct(url, cookies)
      httpx client with Facebook headers (Referer, Origin, Sec-Fetch-*)
      300s timeout, 128KB chunks

Method 3: yt-dlp fallback
  └── download_video(original_url, cookies)
      Subprocess call with temp cookie file
      600s timeout, --merge-output-format mp4
```

## Threading Model

### Single Account (Cookie-based)
```
ThreadPoolExecutor(max_workers=N)
  └── N threads share same BrowserManager
```

### Multi Account (Chrome profiles) 
```
Thread per account:
  └── Each thread has own BrowserManager (separate Chrome profile + CDP port)
      └── Port = 9700 + (account_id % 200)
```

### Pause/Stop Support
- `_pause_event` (threading.Event) — `.wait()` blocks between posts
- `_stop_event` (threading.Event) — checked before each download step

## Download Statistics

```python
@dataclass
class DownloadStats:
    total_posts: int       # Tổng số posts cần tải
    completed_posts: int   # Đã xử lý (success + failed)
    success_posts: int     # Thành công
    failed_posts: int      # Thất bại  
    total_media: int       # Tổng media items
    downloaded_media: int  # Đã tải xong
    total_bytes: int       # Tổng bytes đã tải
    start_time: float      # UTC timestamp bắt đầu
    
    # progress_fraction = completed / total
    # eta_seconds = avg_time_per_post * remaining_posts
```

## Output Structure

```
_DOWNLOAD/_TINIX/
├── 836851975657298/       # Post ID as folder name
│   ├── image_001.jpg      # Full-res images
│   ├── image_002.jpg
│   └── video_001.mp4      # Video (if present)
├── pfbid2abc123def456/    # pfbid format
│   └── image_001.jpg
└── ...
```

## Debug Tips

- Video download fails → check if `post_data.video_url` is populated
- Image too small (<100 bytes) → likely blocked by Facebook CDN
- 403 errors → cookies expired or CDN requires authenticated session
- yt-dlp fails → check if `yt-dlp.exe` is in PATH or bundled directory
- Page shows "Lỗi không xác định" → auto-retry once, then fail
- `/login` redirect → cookies invalid
