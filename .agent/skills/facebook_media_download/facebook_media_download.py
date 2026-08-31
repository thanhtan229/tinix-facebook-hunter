"""
Facebook Media Download — Reference patterns & utilities.

Tập hợp các URL patterns, extraction strategies, download methods,
và verified approaches dùng trong pipeline tải media từ Facebook.

Không import trực tiếp — dùng làm reference khi debug hoặc mở rộng.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# 1. FACEBOOK URL PATTERNS
# ═══════════════════════════════════════════════════════════════════════════════

SUPPORTED_DOMAINS = [
    "facebook.com",
    "m.facebook.com",
    "mbasic.facebook.com",
    "web.facebook.com",
    "www.facebook.com",
    "fb.watch",
    "fb.com",
]

URL_PATTERNS = {
    "posts":      r'(?:facebook\.com|fb\.com)/(?:[\w.]+)/posts/(\w+)',
    "permalink":  r'(?:facebook\.com|fb\.com)/permalink\.php',
    "photo":      r'(?:facebook\.com|fb\.com)/photo',
    "share":      r'(?:facebook\.com|fb\.com)/share/p/([\w]+)',
    "story_php":  r'(?:facebook\.com|fb\.com)/story\.php',
    "reel":       r'(?:facebook\.com|fb\.com)/reel/(\w+)',
    "watch":      r'(?:facebook\.com|fb\.com)/watch/?\?v=(\w+)',
    "fb_watch":   r'fb\.watch/([\w-]+)',
    "videos":     r'(?:facebook\.com|fb\.com)/([\w.]+)/videos/(\w+)',
    "pfbid":      r'(?:facebook\.com|fb\.com)/.*?(pfbid\w+)',
    "numeric":    r'(?:facebook\.com|fb\.com)/(?:[\w.]+/)?(?:posts|photos|videos|activity)/(\d+)',
}

# Post ID extraction priority:
# 1. pfbid (most common in share links)
# 2. /posts/ID
# 3. Query params: story_fbid, fbid, v, id  
# 4. /share/p/ID
# 5. /reel/ID
# 6. /videos/ID
# 7. Last path segment


# ═══════════════════════════════════════════════════════════════════════════════
# 2. BROWSER / CDP CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CHROME_CDP_PORT = 9223  # Default download port
MULTI_ACCOUNT_PORT_BASE = 9700  # port = 9700 + (account_id % 200)

CHROME_LAUNCH_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-popup-blocking",
    "--disable-gpu",
    "--window-size=1280,900",
    "--disable-blink-features=AutomationControlled",
    # "--headless=new",  # Optional
]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ARTICLE DETECTION STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════════

ARTICLE_DETECTION_ORDER = """
1. role="dialog"  → Photo post permalinks (full-screen viewer)
   - Verify: inner_text > 50 chars
   
2. <video> element → Video page layout
   - Use role="main" as container (NOT role="article" which is just comments)
   
3. role="article"  → Standard feed posts (first one)
   
4. role="main"     → General fallback
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TEXT EXTRACTION STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════════

TEXT_EXTRACTION_ORDER = """
Strategy 0: Watch page panel
  - Selector: #watch_feed → div[dir="auto"]
  - Skip UI texts: thích, bình luận, chia sẻ, xem thêm, lượt xem, etc.
  - Return first substantial (>10 chars) non-UI text

Strategy 0.5: JSON from page source (video posts)
  - Pattern: "message":{"text":"..."}
  - Find nearest to "video_id":"<videoId>"
  - Decode: \\n → newline, \\u0026 → &, \\uXXXX → unicode

Strategy 1: data-ad-comet-preview="message" (most reliable)
Strategy 2: data-ad-preview="message" (alternate)

Strategy 3: div[dir="auto"] scan
  - Skip: UI labels, profile names, headings, numbers-only, short texts
  - Return first content-like text

Strategy 4: Generic JSON fallback
  - First "message":{"text":"..."} match in page HTML
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 5. IMAGE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

IMAGE_EXTRACTION_NOTES = """
Primary approach: Photo page navigation
1. Find <a> links with /photo or fbid= in article
2. Filter: only links near substantial images (naturalWidth > 100, naturalHeight > 100)
3. Navigate to each photo page URL
4. Extract full-res from: img[data-visualcompletion="media-vc-image"]
5. Fallback: largest img[src*="scontent"] on photo page

Fallback approach: Direct article scan
- Find all img[src*="scontent"] in article
- Filter by size (naturalWidth > 100)
- Deduplicate by base URL (before query params)

Important:
- Video posts may have thumbnail images — skip images if has_video=True
- Facebook CDN URLs (scontent-xxx.xx.fbcdn.net) require cookies for full-res
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 6. VIDEO DOWNLOAD CHAIN
# ═══════════════════════════════════════════════════════════════════════════════

VIDEO_DOWNLOAD_CHAIN = """
Method 1: Browser session download (most reliable for CDN)
  - BrowserManager.download_file(video_url, save_path)
  - Uses page.request.get() with Referer + Origin headers
  - Advantage: uses browser's full cookie jar + session
  - Verify: file_size > 10KB (otherwise it's an error page)

Method 2: Direct HTTP download (httpx)
  - download_video_direct(url, save_path, cookies)
  - Headers: User-Agent, Referer, Origin, Sec-Fetch-* 
  - 300s timeout, 128KB chunks
  - Verify: file_size > 10KB, not HTML content

Method 3: yt-dlp subprocess (universal fallback)
  - download_video(original_url, save_dir, cookies)
  - Writes cookies to temp Netscape file
  - Flags: --no-playlist --merge-output-format mp4 --retries 3
  - 600s timeout
  - Output: video_001.mp4, video_002.mp4, ...
"""

# HTTP headers for direct video download
VIDEO_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.facebook.com/",
    "Origin": "https://www.facebook.com",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "video",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-site",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 7. OUTPUT STRUCTURE
# ═══════════════════════════════════════════════════════════════════════════════

OUTPUT_NAMING = """
Folder name = Post's numeric ID (digits only)
  - pfbid posts: full pfbid string (truncated to 30 chars)
  - Numeric posts: raw number (e.g. 836851975657298)
  - Unknown: "post_unknown"

Files:
  - image_001.jpg, image_002.jpg, ...  (sequential, .jpg default)
  - video_001.mp4                       (single video per post)
  - No text file — caption not saved
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 8. KNOWN ISSUES & WORKAROUNDS
# ═══════════════════════════════════════════════════════════════════════════════

KNOWN_ISSUES = """
1. Video URL not found in page source
   → Cause: Facebook lazy-loads video data via GraphQL, may not be in initial HTML
   → Fix: yt-dlp fallback handles this case

2. CDN 403 errors on direct download
   → Cause: Facebook CDN requires valid session cookies  
   → Fix: Use browser session download (Method 1) or yt-dlp

3. "Lỗi không xác định" page
   → Cause: Facebook shows generic error, sometimes transient
   → Fix: Auto-retry once (page.reload())

4. Photo page returns feed-resolution image instead of full-res
   → Cause: data-visualcompletion="media-vc-image" not always present
   → Fix: Fallback to largest img[src*="scontent"] sorted by area

5. Watch page caption extraction fails
   → Cause: #watch_feed layout different from standard posts
   → Fix: Strategy 0 (watch panel) and Strategy 0.5 (JSON from source)

6. Multi-account download: Chrome profile conflicts
   → Cause: Two threads using same profile directory
   → Fix: Each account gets unique profile_dir and CDP port
"""
