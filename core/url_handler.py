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
    Also converts video URLs to /watch/?v= format.
    Strips Facebook tracking parameters.
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    parsed = urlparse(url)
    host = parsed.hostname or ""

    if "fb.watch" in host:
        return url  # Keep as-is

    video_url = normalize_video_post_url(url)
    if video_url:
        return video_url

    new_netloc = "www.facebook.com"
    if parsed.port:
        new_netloc += f":{parsed.port}"

    path = parsed.path
    query = parsed.query

    if query:
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
        return match.group(1)

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
        return path_parts[-1]

    return "unknown"


def normalize_video_post_url(url: str) -> str:
    """Return a canonical watch URL for a Facebook video attachment."""
    clean_url = str(url or "").strip()
    if not clean_url:
        return ""
    parsed = urlparse(clean_url if "://" in clean_url else f"https://{clean_url}")
    host = (parsed.hostname or "").lower()
    if not (host in {"facebook.com", "fb.com"} or host.endswith((".facebook.com", ".fb.com"))):
        return ""

    segments = [segment for segment in parsed.path.split("/") if segment]
    video_id = ""
    if len(segments) == 1 and segments[0].lower() == "watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    else:
        for index, segment in enumerate(segments[:-1]):
            if segment.lower() in {"reel", "videos"}:
                video_id = segments[index + 1]
                break
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", video_id):
        return ""
    return f"https://www.facebook.com/watch/?v={video_id}"


def is_playable_video_url(url: str) -> bool:
    """Return whether a Facebook URL carries an addressable video attachment."""
    return bool(normalize_video_post_url(url))


def is_video_url_for_story_id(url: str, post_id: str) -> bool:
    """Accept a video URL without provenance when its attachment ID is the story ID."""
    canonical = normalize_video_post_url(url)
    return bool(canonical and str(post_id or "").strip() == extract_post_id(canonical))


def is_story_permalink_for_id(url: str, post_id: str) -> bool:
    """Return whether a non-video Facebook permalink identifies the given story."""
    expected_id = str(post_id or "").strip()
    clean_url = str(url or "").strip()
    if not expected_id or not clean_url or normalize_video_post_url(clean_url):
        return False
    try:
        parsed = urlparse(clean_url if "://" in clean_url else f"https://{clean_url}")
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    is_facebook_host = (
        host in {"facebook.com", "fb.com"}
        or host.endswith((".facebook.com", ".fb.com"))
    )
    if not is_facebook_host:
        return False
    segments = [segment for segment in parsed.path.split("/") if segment]
    query = parse_qs(parsed.query)
    if len(segments) == 1 and segments[0].lower() in {"permalink.php", "story.php"}:
        candidates = query.get("story_fbid", [])
    elif len(segments) == 1 and segments[0].lower() in {"photo", "photo.php"}:
        candidates = query.get("fbid", [])
    elif len(segments) >= 2 and segments[-2].lower() == "posts":
        candidates = [segments[-1]]
    elif len(segments) == 3 and [part.lower() for part in segments[:2]] == ["share", "p"]:
        candidates = [segments[-1]]
    elif len(segments) == 1 or (len(segments) == 2 and segments[-1].lower().startswith("pfbid")):
        candidates = [segments[-1]]
    else:
        candidates = []
    return expected_id in candidates


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
