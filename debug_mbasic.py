"""
Test v2: Add explicit login verification after scraper.start(), 
then check if page has feed/nav after navigating to target.
"""
import time
from core.page_scraper import PageScraper, _PostCollector
from core.cookie_handler import parse_cookie_string
from utils import config, logger

logger.setup_logger()

cookies = parse_cookie_string(config.get("saved_cookies", ""))

scraper = PageScraper(cookies)
print("Starting Chrome + login...")
if not scraper.start():
    exit(1)

# Verify login by opening a page and checking
print("\n=== Manual login verification ===")
check_page = scraper._context.new_page()
check_page.goto("https://www.facebook.com/", wait_until="load", timeout=20000)
time.sleep(3)

state = check_page.evaluate("""() => ({
    url: window.location.href,
    title: document.title,
    hasNav: !!document.querySelector('[role="navigation"]'),
    hasFeed: !!document.querySelector('[role="feed"]'),
    bodyText: document.body.innerText.slice(0, 300),
})""")
print(f"URL: {state['url']}")
print(f"Nav: {state['hasNav']}, Feed: {state['hasFeed']}")
print(f"Body: {state['bodyText'][:200]}")

logged_in = state['hasNav'] or state['hasFeed']
print(f"\nLogin status: {'✅ Logged in' if logged_in else '❌ NOT logged in'}")

if not logged_in and "Tiếp tục" in state['bodyText']:
    print("\n=== 'Tiếp tục' page detected — clicking ===")
    try:
        # Try multiple selector strategies
        clicked = False
        
        # Strategy 1: Look for the specific button
        for selector in [
            'div[role="button"] >> text=Tiếp tục',
            'span >> text=Tiếp tục',
            'text=Tiếp tục',
        ]:
            try:
                el = check_page.locator(selector).first
                if el.is_visible(timeout=2000):
                    el.click()
                    print(f"  Clicked: {selector}")
                    clicked = True
                    break
            except:
                continue
        
        if not clicked:
            # Strategy 2: Find by evaluating DOM
            check_page.evaluate("""() => {
                const spans = document.querySelectorAll('span');
                for (const s of spans) {
                    if (s.textContent.trim() === 'Tiếp tục') {
                        const btn = s.closest('[role="button"]') || s.parentElement;
                        if (btn) { btn.click(); return true; }
                    }
                }
                return false;
            }""")
            print("  Clicked via DOM search")
        
        time.sleep(5)
        
        state2 = check_page.evaluate("""() => ({
            url: window.location.href,
            hasNav: !!document.querySelector('[role="navigation"]'),
            hasFeed: !!document.querySelector('[role="feed"]'),
            bodyText: document.body.innerText.slice(0, 200),
        })""")
        print(f"  After click — Nav: {state2['hasNav']}, Feed: {state2['hasFeed']}")
        print(f"  URL: {state2['url']}")
        logged_in = state2['hasNav'] or state2['hasFeed']
        
    except Exception as e:
        print(f"  Error: {e}")

check_page.close()

if logged_in:
    print("\n=== Scraping inanhchocon (authenticated) ===")
    posts = scraper.scrape_page("https://www.facebook.com/inanhchocon", max_posts=25)
    print(f"\nResults: {len(posts)} posts")
    for i, p in enumerate(posts[:10], 1):
        print(f"  [{i}] {p.date} | {p.post_type} | {p.caption[:40] if p.caption else 'N/A'}")
else:
    print("\n⚠ Still not logged in!")
    
    # Try one more thing: open the target page directly
    print("\n=== Trying target page anyway ===")
    page2 = scraper._context.new_page()
    page2.set_viewport_size({"width": 1280, "height": 900})
    page2.goto("https://www.facebook.com/inanhchocon", wait_until="load", timeout=30000)
    time.sleep(5)
    
    info = page2.evaluate("""() => ({
        hasFeed: !!document.querySelector('[role="feed"]'),
        hasNav: !!document.querySelector('[role="navigation"]'),
        bodyH: document.body.scrollHeight,
        svH: document.getElementById('scrollview')?.scrollHeight,
        bodyText: document.body.innerText.slice(0, 300),
    })""")
    print(f"  Feed: {info['hasFeed']}, Nav: {info['hasNav']}")
    print(f"  BodyH: {info['bodyH']}, ScrollviewH: {info['svH']}")
    print(f"  Body: {info['bodyText'][:200]}")
    page2.close()

scraper.stop()
print("\nDone!")
