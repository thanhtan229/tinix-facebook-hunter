"""
Tinix Facebook Down — URL Handler
Validates, normalizes, and extracts information from Facebook post URLs.
"""

import re
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


# Regex patterns for various Facebook URL formats
_FB_DOMAINS = (
    "facebook.com",
    "m.facebook.com",
    "mbasic.facebook.com",
    "web.facebook.com",
    "www.facebook.com",
    "fb.watch",
    "fb.com",
)

# Pattern: /username/posts/postid
_PATTERN_POSTS = re.compile(
    r"(?:facebook\.com|fb\.com)/(?:(?!photo|video|reel|watch|share|story|permalink)[\w.]+)/posts/(\w+)",
    re.IGNORECASE,
)

# Pattern: /permalink.php?story_fbid=...&id=...
_PATTERN_PERMALINK = re.compile(
    r"(?:facebook\.com|fb\.com)/permalink\.php",
    re.IGNORECASE,
)

# Pattern: /photo/?fbid=...
_PATTERN_PHOTO = re.compile(
    r"(?:facebook\.com|fb\.com)/photo",
    re.IGNORECASE,
)

# Pattern: /share/p/... (short share links)
_PATTERN_SHARE = re.compile(
    r"(?:facebook\.com|fb\.com)/share/p/([\w]+)",
    re.IGNORECASE,
)

# Pattern: /story.php?story_fbid=...
_PATTERN_STORY_PHP = re.compile(
    r"(?:facebook\.com|fb\.com)/story\.php",
    re.IGNORECASE,
)

# Pattern: /reel/...
_PATTERN_REEL = re.compile(
    r"(?:facebook\.com|fb\.com)/reel/(\w+)",
    re.IGNORECASE,
)

# Pattern: /watch/?v=...
_PATTERN_WATCH = re.compile(
    r"(?:facebook\.com|fb\.com)/watch/?\?v=(\w+)",
    re.IGNORECASE,
)

# Pattern: fb.watch short URLs
_PATTERN_FB_WATCH = re.compile(
    r"fb\.watch/([\w-]+)",
    re.IGNORECASE,
)

# Pattern: /username/videos/videoid
_PATTERN_VIDEOS = re.compile(
    r"(?:facebook\.com|fb\.com)/([\w.]+)/videos/(\w+)",
    re.IGNORECASE,
)

# Generic pattern: any facebook.com URL with pfbid or numeric ID in path
_PATTERN_GENERIC_PFBID = re.compile(
    r"(?:facebook\.com|fb\.com)/.*?(pfbid\w+)",
    re.IGNORECASE,
)

_PATTERN_GENERIC_NUMERIC = re.compile(
    r"(?:facebook\.com|fb\.com)/(?:[\w.]+/)?(?:posts|photos|videos|activity)/(\d+)",
    re.IGNORECASE,
)


def is_facebook_url(url: str) -> bool:
    """Check if a URL is a valid Facebook URL."""
    url = url.strip()
    if not url:
        return False
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = parsed.hostname or ""
        return any(host.endswith(domain) for domain in _FB_DOMAINS)
    except Exception:
        return False


def normalize_to_mbasic(url: str) -> str:
    """
    Convert any Facebook URL to its mbasic.facebook.com equivalent.
    This makes HTML parsing much simpler (no JavaScript needed).
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    parsed = urlparse(url)
    host = parsed.hostname or ""

    # Handle fb.watch short URLs — keep as-is for yt-dlp, but try to convert
    if "fb.watch" in host:
        return url  # Can't convert short URLs directly, need to follow redirect

    # Replace domain with mbasic.facebook.com
    new_netloc = "mbasic.facebook.com"
    if parsed.port:
        new_netloc += f":{parsed.port}"

    normalized = urlunparse((
        "https",
        new_netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        "",  # Remove fragment
    ))

    return normalized


def get_original_url(url: str) -> str:
    """
    Convert any Facebook URL back to www.facebook.com format.
    Also converts /reel/ and /videos/ URLs to /watch/?v= format.
    Strips Facebook tracking parameters.
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    parsed = urlparse(url)
    host = parsed.hostname or ""

    if "fb.watch" in host:
        return url  # Keep as-is

    new_netloc = "www.facebook.com"
    if parsed.port:
        new_netloc += f":{parsed.port}"

    path = parsed.path
    query = parsed.query

    # Convert /reel/ID to /watch/?v=ID
    reel_match = _PATTERN_REEL.search(url)
    if reel_match:
        video_id = reel_match.group(1)
        path = "/watch/"
        query = f"v={video_id}"
    else:
        # Convert /username/videos/ID to /watch/?v=ID
        videos_match = _PATTERN_VIDEOS.search(url)
        if videos_match:
            video_id = videos_match.group(2)
            path = "/watch/"
            query = f"v={video_id}"
        elif query:
            # Strip ALL Facebook tracking parameters, keep only essential ones
            from urllib.parse import parse_qsl, urlencode
            essential_keys = {'v', 'id', 'fbid', 'story_fbid', 'set', 'type', 'pfbid'}
            params = parse_qsl(query, keep_blank_values=True)
            clean_params = [(k, v) for k, v in params if k in essential_keys]
            query = urlencode(clean_params)

    return urlunparse((
        "https",
        new_netloc,
        path,
        parsed.params,
        query,
        "",
    ))


def extract_post_id(url: str) -> str:
    """
    Try to extract a post ID from the URL for folder naming.
    Returns the best identifier found, or a sanitized URL segment.
    """
    url = url.strip()

    # Try pfbid pattern first (most common in share links)
    match = _PATTERN_GENERIC_PFBID.search(url)
    if match:
        return match.group(1)[:30]  # Truncate long pfbids

    # Try /posts/ID
    match = _PATTERN_POSTS.search(url)
    if match:
        return match.group(1)

    # Try permalink query params
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    for key in ("story_fbid", "fbid", "v", "id"):
        if key in qs:
            return qs[key][0]

    # Try share link
    match = _PATTERN_SHARE.search(url)
    if match:
        return match.group(1)

    # Try reel
    match = _PATTERN_REEL.search(url)
    if match:
        return match.group(1)

    # Try videos
    match = _PATTERN_VIDEOS.search(url)
    if match:
        return match.group(2)

    # Fallback: use last path segment
    path_parts = [p for p in parsed.path.split("/") if p]
    if path_parts:
        return path_parts[-1][:30]

    return "unknown"


def parse_urls(text: str) -> list[str]:
    """
    Parse multi-line text input into a list of cleaned Facebook URLs.
    Filters out empty lines and non-Facebook URLs.
    Supports bare numeric post IDs (e.g., 836851975657298).
    """
    lines = text.strip().splitlines()
    urls = []
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Support bare post_id → convert to FB URL
        if re.match(r'^\d{10,}$', line):
            urls.append(f"https://www.facebook.com/{line}")
            continue
        if re.match(r'^(?:pfbid)?[A-Za-z0-9_-]{12,}$', line):
            urls.append(f"https://www.facebook.com/{line}")
            continue

        if is_facebook_url(line):
            # Normalize to https://www.facebook.com/...
            normalized = get_original_url(line)
            urls.append(normalized)
    return urls


def validate_url(url: str) -> Tuple[bool, str]:
    """
    Validate a single URL.
    Returns (is_valid, message).
    """
    url = url.strip()
    if not url:
        return False, "URL trống"
    if not is_facebook_url(url):
        return False, f"Không phải URL Facebook: {url[:60]}..."
    return True, "OK"
