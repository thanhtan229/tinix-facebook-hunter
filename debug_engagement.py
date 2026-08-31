"""
Debug script: Quét 1 page và log chi tiết cấu trúc feedback/engagement.
Mục đích: Xem Facebook trả về engagement data ở đâu trong JSON.

Chạy: python debug_engagement.py
"""
import json
import os
import re
import sys
import time

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.db_storage import get_db_path, get_social_accounts
from core.page_scraper import PageScraper
from utils import config

TARGET_URL = "https://www.facebook.com/profile.php?id=61579999349195"
MAX_POSTS = 5
DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_output")
os.makedirs(DEBUG_DIR, exist_ok=True)


def get_first_live_account():
    db_path = get_db_path(config.get("scraper_db_path", ""))
    all_fb = get_social_accounts(db_path, platform="facebook")
    for acc in all_fb:
        if acc.get("is_active") or acc.get("sync_status") == "Live":
            if not acc.get("profile_dir") and acc.get("id"):
                acc["profile_dir"] = os.path.join(
                    os.getcwd(), "chrome_profiles", f"facebook_{acc['id']}"
                )
            return acc
    return None


def main():
    account = get_first_live_account()
    if not account:
        print("❌ Không có account Live!")
        return

    label = account.get("label") or account.get("username")
    print(f"👤 Account: {label}")
    print(f"📁 Profile: {account.get('profile_dir', 'N/A')}")
    print(f"🔗 URL: {TARGET_URL}")
    print(f"📊 Max posts: {MAX_POSTS}")
    print()

    scraper = PageScraper(account=account)
    if not scraper.start():
        print("❌ Không khởi tạo được Chrome!")
        return

    try:
        page = scraper._context.new_page()
        page.set_viewport_size({"width": 1280, "height": 900})

        # Capture ALL responses
        captured_responses = []

        def on_response(response):
            try:
                url = response.url
                if any(ext in url for ext in [".js", ".css", ".png", ".jpg", ".gif", ".woff", ".svg"]):
                    return
                body = response.text()
                if '"post_id"' not in body and '"creation_time"' not in body:
                    return
                captured_responses.append({
                    "url": url[:200],
                    "body": body,
                })
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(TARGET_URL, wait_until="load", timeout=30000)
        time.sleep(5)

        # Scroll a few times
        for i in range(5):
            page.evaluate("""() => {
                window.scrollBy(0, 1200);
                const sv = document.getElementById('scrollview');
                if (sv) { sv.scrollTop += 1200; }
            }""")
            time.sleep(2)
            print(f"  Scroll #{i+1}, captured {len(captured_responses)} responses")

        # Also get page source
        html = page.evaluate("() => document.documentElement.outerHTML")
        captured_responses.append({"url": "PAGE_SOURCE", "body": html})

        print(f"\n📦 Total captured responses: {len(captured_responses)}")
        print()

        # Now analyze each response for engagement data
        post_count = 0
        for idx, resp in enumerate(captured_responses):
            body = resp["body"]

            # Find all post_ids
            post_ids = set(re.findall(r'"post_id":\s*"(\d+)"', body))
            if not post_ids:
                continue

            print(f"\n{'='*60}")
            print(f"Response #{idx}: {resp['url'][:100]}")
            print(f"  Post IDs found: {len(post_ids)}")

            for pid in list(post_ids)[:3]:  # Only analyze first 3
                pos = body.find(f'"post_id":"{pid}"')
                if pos == -1:
                    continue

                # Get a large window around this post
                start = max(0, pos - 5000)
                end = min(len(body), pos + 50000)
                block = body[start:end]

                print(f"\n  --- Post ID: {pid} ---")

                # Check for reaction count
                react = re.search(r'"reaction_count":\s*\{"count":\s*(\d+)', block)
                print(f"  reaction_count: {react.group(1) if react else 'NOT FOUND'}")

                # Check ALL comment patterns
                for pattern_name, pattern in [
                    ("total_comment_count", r'"total_comment_count":\s*(\d+)'),
                    ("comment_count.total_count", r'"comment_count":\s*\{"total_count":\s*(\d+)'),
                    ("comments.total_count", r'"comments":\s*\{"total_count":\s*(\d+)'),
                    ("i18n_comment_count", r'"i18n_comment_count":\s*"([^"]+)"'),
                    ("top_level_comment_count", r'"top_level_comment_count":\s*(\d+)'),
                    ("comment_rendering_instance", r'"comment_rendering_instance"'),
                    ("ufi_renderer", r'"ufi_renderer"'),
                ]:
                    m = re.search(pattern, block)
                    if m:
                        print(f"  {pattern_name}: {m.group(1) if m.lastindex else 'EXISTS'}")

                # Check ALL view patterns
                for pattern_name, pattern in [
                    ("video_view_count", r'"video_view_count":\s*(\d+)'),
                    ("play_count", r'"play_count":\s*(\d+)'),
                    ("see_count", r'"see_count":\s*(\d+)'),
                    ("view_count", r'"view_count":\s*(\d+)'),
                    ("video_view_count_renderer", r'"video_view_count_renderer"'),
                    ("i18n_social_context", r'"i18n_social_context":\s*"([^"]+)"'),
                ]:
                    m = re.search(pattern, block)
                    if m:
                        print(f"  {pattern_name}: {m.group(1) if m.lastindex else 'EXISTS'}")

                # Check feedback section structure
                fb_section = re.search(r'"feedback":\s*\{', block)
                if fb_section:
                    fb_start = fb_section.start()
                    # Get a snippet of the feedback section
                    snippet = block[fb_start:fb_start+500]
                    print(f"  feedback snippet: {snippet[:300]}...")

                # Check for comet_sections presence
                cs = re.search(r'"comet_sections":\s*\{', block)
                print(f"  has comet_sections: {'YES' if cs else 'NO'}")

                # Save full block to file for manual inspection
                post_count += 1
                if post_count <= 5:
                    out_file = os.path.join(DEBUG_DIR, f"post_{pid}.json")
                    with open(out_file, "w", encoding="utf-8") as f:
                        f.write(block)
                    print(f"  📁 Saved to: {out_file}")

        print(f"\n\n✅ Debug complete. Check {DEBUG_DIR} for full post data.")
        page.close()

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        scraper.stop()


if __name__ == "__main__":
    main()
