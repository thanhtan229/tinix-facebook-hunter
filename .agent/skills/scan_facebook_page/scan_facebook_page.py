"""
Scan Facebook Page — Reference patterns & utilities.

Tập hợp các regex patterns, extraction logic, và verified strategies
dùng trong core/page_scraper.py để quét bài viết từ Facebook Page.

Không import trực tiếp — dùng làm reference khi debug hoặc mở rộng scraper.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# 1. POST ID EXTRACTION PATTERNS
# ═══════════════════════════════════════════════════════════════════════════════

# Regex tìm post_id trong JSON text (SSR response)
POST_ID_REGEX = r'"post_id":\s*"(\d+)"'

# Regex tìm post_id trong URL (DOM links)
URL_POST_ID_PATTERNS = [
    r'(?:posts|videos|permalink)/?\d*/?(\d{10,})',  # /posts/123, /videos/123
    r'(pfbid[A-Za-z0-9]+)',                          # /pfbid2abc...
    r'facebook\.com/(\d{15,})',                       # /122129141792999978 (direct ID)
]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ENGAGEMENT EXTRACTION PATTERNS
# ═══════════════════════════════════════════════════════════════════════════════

# JSON patterns (trong GraphQL response)
ENGAGEMENT_JSON_PATTERNS = {
    "reactions": r'"reaction_count":\s*\{"count":\s*(\d+)',
    "comments": [
        r'"comment_count":\s*\{"total_count":\s*(\d+)',
        r'"total_comment_count":\s*(\d+)',
        r'"comments":\s*\{"total_count":\s*(\d+)',
    ],
    "shares": [
        r'"share_count":\s*\{"count":\s*(\d+)',
        r'"reshare_count":\s*\{"count":\s*(\d+)',
        r'"share_count":\s*(\d+)',
    ],
}

# DOM text patterns (Vietnamese)
ENGAGEMENT_DOM_PATTERNS_VI = {
    "comments": r'([\d,.]+[KkMmNn]?)\s*(?:bình luận|comments?)',
    "shares": r'([\d,.]+[KkMmNn]?)\s*(?:lượt chia sẻ|chia sẻ|shares?)',
    "reactions": r'([\d,.]+[KkMmNn]?)\s*(?:lượt thích|likes?|reactions?)',
}


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DATE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

# JSON: Unix timestamp
DATE_JSON_PATTERN = r'"creation_time":\s*(\d{10})'

# DOM: Vietnamese relative dates → parse rules
DATE_DOM_RULES = {
    r'\d+\s*phút':         "today",        # "5 phút" → today
    r'\d+\s*giờ':          "today",        # "14 giờ" → today  
    r'hôm qua':            "yesterday",    # "Hôm qua" → yesterday
    r'hôm nay':            "today",        # "Hôm nay" → today
    r'(\d+)\s*ngày':       "days_ago",     # "3 ngày" → 3 days ago
    r'(\d{1,2})\s*tháng\s*(\d{1,2})':  "dd_mm",  # "29 tháng 1" → 29/01/YYYY
}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SSR SCRIPT TAG EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

# Facebook SSR HTML chứa JSON data trong <script data-sjs> tags
# Pattern để tìm script boundaries:
SSR_SCRIPT_PATTERN = r'<script[^>]*data-sjs[^>]*>'

# Flow:
# 1. re.finditer(SSR_SCRIPT_PATTERN, html_line) → tìm tất cả script tags
# 2. Với mỗi match: start = match.end(), end = html.find('</script>', start)
# 3. chunk = html[start:end] → json.loads(chunk) → _extract_from_json()
# 
# Quan trọng: KHÔNG dùng regex greedy/non-greedy cho content vì JSON rất lớn
# và chứa nested braces. Dùng string.find('</script>') để tìm end boundary.


# ═══════════════════════════════════════════════════════════════════════════════
# 5. STORY NODE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

# Một "story node" hợp lệ trong GraphQL JSON phải có:
# - "comet_sections" (dict) chứa "content" hoặc "feedback"  
# - "post_id" (string)
#
# Feedback section chứa engagement data:
# node["comet_sections"]["feedback"]["story"]["feedback_context"]
#     → "reaction_count": {"count": N}
#     → "comment_rendering_instance" → "comments" → {"total_count": N}
#     → "share_count": {"count": N}
#
# Date từ:
# node["comet_sections"] → deep_find("creation_time") → Unix timestamp


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MERGE STRATEGY
# ═══════════════════════════════════════════════════════════════════════════════

MERGE_RULES = """
Khi cùng 1 post_id xuất hiện nhiều lần (SSR → GraphQL → DOM enrichment):

1. Engagement: TAKE HIGHER value
   if new.engagement > existing.engagement: update

2. Text fields: FILL IF EMPTY  
   if new.date and not existing.date: update
   if new.caption and not existing.caption: update

3. Post type: UPGRADE from Text
   if existing.type == "Text" and new.type in ("Ảnh", "Video"): update

4. URL: UPGRADE from generic
   if existing.url == f"facebook.com/{pid}" and new.url is better: update
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 7. GROUP PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════════

GROUP_PRESERVATION_SQL = """
-- Khi save_posts, auto-lookup existing group:
SELECT group_name FROM pages WHERE page_url = ?

-- Trong ON CONFLICT clause, chỉ update group nếu giá trị mới non-empty:
ON CONFLICT(page_url) DO UPDATE SET
    group_name = CASE 
        WHEN excluded.group_name != '' THEN excluded.group_name 
        ELSE pages.group_name 
    END
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 8. KNOWN ISSUES & WORKAROUNDS
# ═══════════════════════════════════════════════════════════════════════════════

KNOWN_ISSUES = """
1. Bài mới nhất trên page thường chỉ xuất hiện trong SSR response đầu tiên
   (KHÔNG xuất hiện lại trong GraphQL scroll responses)
   → Fix: Parse <script data-sjs> tags trong SSR HTML

2. DOM enrichment cần scroll về đầu trang trước khi scan
   → page.evaluate("() => window.scrollTo(0, 0)") + sleep(2)

3. Facebook dùng relative URLs trong DOM (/122xxx thay vì facebook.com/122xxx)  
   → Dùng link.href (resolved) thay vì getAttribute('href') (raw)

4. Sort: bài không có date xếp ĐẦU (datetime.max) vì chúng thường là bài mới nhất

5. Page name extraction: tránh lấy "Đoạn chat" từ sidebar
   → Ưu tiên <title> tag, filter bỏ các từ khóa navigation
"""
