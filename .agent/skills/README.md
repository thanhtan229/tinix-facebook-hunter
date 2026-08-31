# Tinix Skill References

The folders in `.agent/skills` are reference documents for development and debugging. They are not loaded by the Tinix app at runtime.

Runtime code lives in `core/` and `gui/`. When changing a job, edit the runtime files first, then update the matching `SKILL.md` if the behavior, architecture, selectors, or debugging guidance changed.

Mapping:
- `facebook_media_download` documents `gui/app.py`, `core/downloader.py`, `core/facebook_parser.py`, `core/media_downloader.py`, `core/url_handler.py`, and `core/cookie_handler.py`.
- `scan_facebook_page` documents `gui/scrape_tab.py`, `core/page_scraper.py`, `core/db_storage.py`, `gui/page_spy_manager.py`, `gui/post_spy_manager.py`, and `gui/results_dialog.py`.
- `photo_post` documents `gui/social_post_tab.py`, `core/auto_poster.py`, `core/content_scanner.py`, `core/video_post_dispatcher.py`, and `core/db_storage.py`.
- `facebook-token-management` documents safe authorized Facebook token workflows for `gui/account_manager.py`, `core/fb_login.py`, `core/db_storage.py`, and a possible `core/facebook_token_manager.py`.

Do not put runtime-only logic here unless the app is explicitly refactored to load skills as plugins.
