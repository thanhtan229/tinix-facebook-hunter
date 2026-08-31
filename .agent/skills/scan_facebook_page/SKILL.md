---
name: Scan Facebook Page
description: Skill để quét dữ liệu bài viết từ Facebook Page — bao gồm extraction logic, merge strategy, DOM enrichment, và các pattern đã verified.
---

# Scan Facebook Page

## Runtime Status

This skill folder is reference-only. The app does not import or execute files from `.agent/skills` at runtime.

Runtime code lives in:
- `gui/scrape_tab.py`
- `core/page_scraper.py`
- `core/db_storage.py`
- `gui/page_spy_manager.py`
- `gui/post_spy_manager.py`
- `gui/results_dialog.py`

When improving the Facebook page scan job, update the runtime files first. After a meaningful behavior change, update this `SKILL.md` so the reference stays current.

## Tổng quan

Module `core/page_scraper.py` quét bài viết từ Facebook Page bằng cách:
1. Mở page bằng Chrome (Playwright CDP)
2. Intercept GraphQL API responses
3. Parse SSR (Server-Side Rendered) HTML
4. Scroll để trigger thêm GraphQL calls
5. DOM enrichment bổ sung data thiếu
6. Sort và export kết quả

## Kiến trúc chính

### Classes

- **`_PostCollector`**: Thread-safe collector, chứa dict `_posts` (key = post_id)
  - `process_response_body(body)` → split lines → JSON parse hoặc text extract
  - `_extract_from_json(data)` → recursive tìm story nodes
  - `_extract_from_text(text)` → regex fallback cho SSR HTML

- **`PageScraper`**: Main scraper class
  - `scrape_page(url, max_posts)` → orchestrate toàn bộ flow
  - `_scroll_for_posts()` → scroll page để load thêm bài
  - `_enrich_engagement_from_dom()` → scan DOM cho data thiếu
  - `_build_results()` → sort + convert to ScrapedPost

### Data Flow

```
Response Interceptor → process_response_body()
                        ├── JSON parse OK → _extract_from_json() → _find_story_nodes() → _parse_story_node()
                        ├── JSON fail + has <script data-sjs> → extract script JSON → _extract_from_json()
                        └── Final fallback → _extract_from_text() (regex)

After scrolling → scroll to top → _enrich_engagement_from_dom() → merge dates + engagement

_build_results() → sort by date (newest first) → return
```

## Vấn đề đã giải quyết & Patterns

### 1. Bài mới nhất không có date/engagement

**Nguyên nhân**: Facebook SSR response chứa bài mới nhất trong `<script data-sjs>` tags. Khi `json.loads()` fail cho toàn bộ HTML line, code fallback sang regex extraction với window ±15K/35K chars — quá nhỏ để tìm `creation_time` và `reaction_count`.

**Fix**: Trước khi fallback regex, extract JSON từ `<script data-sjs>` tags:
```python
for m in re.finditer(r'<script[^>]*data-sjs[^>]*>', line):
    start = m.end()
    end = line.find('</script>', start)
    chunk = line[start:end].strip()
    if '"post_id"' in chunk:
        script_data = json.loads(chunk)
        self._extract_from_json(script_data)
```

### 2. Post ID khác nhau cho cùng 1 bài

Facebook có thể dùng **story_id** (URL) khác với **node_id** (GraphQL). Chúng là 2 bài KHÁC NHAU, không phải cùng 1 bài. Không merge theo ID.

### 3. Merge-if-better Strategy

Khi cùng 1 post_id xuất hiện nhiều lần (SSR → GraphQL → DOM):
```python
# Trong _extract_from_json và _extract_from_text:
if pid in self._posts:
    existing = self._posts[pid]
    # Merge engagement (take higher)
    if post["engagement"] > existing["engagement"]:
        existing["engagement"] = post["engagement"]
    # Merge empty fields
    if post["date"] and not existing["date"]:
        existing["date"] = post["date"]
    if post["caption"] and not existing["caption"]:
        existing["caption"] = post["caption"]
```

### 4. DOM Enrichment

Sau khi scroll, quay lại đầu trang rồi scan DOM:
- Dùng `link.href` (resolved URL) thay vì `getAttribute('href')` (relative)
- Selector: `a[href]` thay vì `a[href*="facebook.com"]`
- Post ID patterns: `posts/(\d+)`, `pfbid...`, `facebook.com/(\d{15,})`
- Date parsing: "14 giờ" → today, "Hôm qua" → yesterday, "29 tháng 1" → 29/01/YYYY

### 5. Sort — Bài không có date

```python
def date_sort_key(p):
    try:
        return datetime.strptime(p.date, "%d/%m/%Y")
    except (ValueError, TypeError):
        return datetime.max  # Empty date → top (newest)
```

### 6. Group Preservation khi re-scrape

Trong `save_posts()`:
```python
if not group_name and canonical:
    row = conn.execute("SELECT group_name FROM pages WHERE page_url = ?", (canonical,))
    if row and row[0]:
        group_name = row[0]  # Giữ group cũ
```

## Files liên quan

| File | Mô tả |
|------|--------|
| `core/page_scraper.py` | Logic quét chính |
| `core/db_storage.py` | Lưu kết quả vào SQLite |
| `core/excel_exporter.py` | Export ra Excel |
| `gui/scrape_tab.py` | UI tab quét |
| `gui/dashboard_tab.py` | Dashboard hiển thị kết quả |
| `gui/results_dialog.py` | Dialog kết quả popup |

## Debug Tips

- Các `[DEBUG]` log quan trọng:
  - `[TEXT-PATH]` / `[JSON-PATH]` / `[SCRIPT-JSON]` — path nào capture bài
  - `[TEXT-POST]` — giá trị extracted cho mỗi bài từ text
  - `[DEBUG] Post XXX FINAL` — giá trị cuối cùng từ JSON
  - `[DOM] Starting/Found/Enriched` — DOM enrichment status
  - `⚠ DOM enrichment error:` — JS execution error
