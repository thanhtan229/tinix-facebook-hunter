# ARCHITECTURE.md

> Kiến trúc kỹ thuật hiện tại của Tinix FB Studio (Tinix-Facebook-Hunter). Mô tả hệ thống như đang chạy trong code, không phải kiến trúc tương lai.

## 0. Metadata

**Project:** Tinix FB Studio (Tinix-Facebook-Hunter)
**Architecture Version:** 1.1
**Status:** Active
**Last Updated:** 2026-10-30

## 1. Tổng quan

Ứng dụng desktop cục bộ cho Windows. Backend FastAPI (uvicorn) chỉ lắng nghe `127.0.0.1:7866`. Giao diện là HTML/JS tĩnh do backend phục vụ, mở trong cửa sổ Chrome/Edge App Mode. Tác vụ tải media và quét fanpage dùng Chrome thật (điều khiển qua Playwright CDP) với profile riêng cho từng tài khoản. Dữ liệu lưu trong SQLite và thư mục media trên đĩa.

```text
Trình duyệt App Mode (web/static)
      ↓ HTTP /api/* + WebSocket /ws (cookie phiên, host/origin localhost)
web/app.py (FastAPI, middleware bảo mật, lifespan khôi phục)
      ↓
web/routes/* (accounts, downloader, scraper, spy, system)
      ↓
core/* (download orchestrator, scanner, preflight, lease profile, DB)
      ↓
SQLite (tinix_scraper.db) · thư mục media · Chrome profiles · Chrome/Playwright CDP · Facebook
```

## 2. Mục tiêu kiến trúc

- Chạy cục bộ, không mở ra mạng.
- Dữ liệu nhạy cảm (mật khẩu, 2FA, cookie) được mã hóa khi lưu.
- Tác vụ dài bền vững: hàng đợi và trạng thái lưu trong SQLite, khôi phục được sau khi tắt đột ngột.
- Thay đổi file đích dùng ghi tạm rồi thay thế nguyên tử (`.part`, `os.replace`).

## 3. Ranh giới tin cậy

- **Người dùng cục bộ:** mọi API `/api/*` (trừ `/api/system/health`) cần cookie phiên được tạo ngẫu nhiên mỗi lần khởi động.
- **Trình duyệt khác trên cùng máy:** request phải có `Host` là localhost và `Origin` (nếu có) là localhost cùng cổng.
- **Facebook và Chrome:** nguồn dữ liệu bên ngoài; mọi phản hồi được coi là không tin cậy và kiểm tra trước khi ghi.
- **Máy/tài khoản Windows:** secret được mã hóa DPAPI theo tài khoản Windows, chỉ giải mã trên đúng máy và user đó.

## 4. Thành phần chạy

### Launcher
- `START.vbs` → `START.bat`: chọn Python (`.venv` nếu có), kiểm tra cổng, dọn tiến trình cũ của dự án, khởi động `main.py` bằng `pythonw`, mở App Mode.
- `STOP.vbs` / `STOP.bat`: dừng tiến trình đã xác minh thuộc dự án, không dừng tiến trình ngoài.
- `install.bat`: cài đặt một lần cho máy mới (tạo `.venv`, cài `requirements.txt`, tải Chromium).

### Backend (`main.py`, `web/app.py`)
- Khởi động uvicorn; ghi log khởi động vào `logs/server_startup.log`.
- `lifespan`: đánh dấu tác vụ đang chạy từ phiên trước là `interrupted`, đưa download dở về trạng thái cần xử lý, rồi tự chạy lại hàng đợi đã lưu (xem mục 7).
- Middleware kiểm tra host, origin và cookie phiên. WebSocket `/ws` kiểm tra cùng điều kiện.

### Routes (`web/routes/`)
- `accounts.py`: CRUD tài khoản, preflight, mở Chrome profile, export/import profile (`.tinix-profile`, `.tinix-profiles.zip`).
- `downloader.py`: hàng đợi và worker tải media, retry có backoff khi profile bị khóa.
- `scraper.py`, `spy.py`: quét fanpage và tìm fanpage.
- `system.py`: cấu hình, thống kê, task runs, health.

### Core (`core/`)
- `db_storage.py`: toàn bộ truy cập SQLite, schema, migration, mã hóa secret khi ghi.
- `downloader.py`, `media_downloader.py`: tải media (ảnh trực tiếp, video qua yt-dlp), ghi `.part` rồi thay thế.
- `page_scraper.py`, `facebook_parser.py`: điều khiển Chrome CDP, quét Page, `BrowserManager`.
- `account_preflight.py`: kiểm tra phiên Facebook của tài khoản trước khi tải.
- `profile_lease.py`: khóa profile để một tác vụ dùng một profile tại một thời điểm.
- `database_maintenance.py`: backup, verify, restore (từ chối khi app đang chạy).
- `data_cleanup.py`, `storage_migration.py`: dọn dữ liệu và chuyển cấu trúc lưu trữ.

### Utils (`utils/`)
- `secure_store.py`: DPAPI `protect_secret` / `unprotect_secret`.
- `profile_bundle.py`: đóng gói và giải nén profile; chống zip-slip và symlink.
- `process_cleanup.py`: xác định và dừng tiến trình thuộc dự án; giải phóng cổng.
- `config.py`: `config.json` và `.env`.

## 5. Ranh giới module

- `web/` có thể gọi `core/` và `utils/`. `core/` không import `web/` (ngoại lệ: `core/database_maintenance.py` gọi `utils.process_cleanup` để kiểm tra cổng).
- Chỉ `core/db_storage.py` được ghi vào SQLite. Route không tự viết SQL.
- Mọi ghi file đích đi qua đường ghi tạm rồi thay thế.

## 6. Cấu trúc thư mục quan trọng

```text
main.py, web/app.py          khởi động và API
web/routes/                  endpoint theo chức năng
web/static/                  giao diện (HTML/JS/CSS)
core/                        logic nghiệp vụ, DB, tải, quét
utils/                       bảo mật, bundle, tiến trình, cấu hình
tests/                       pytest; conftest.py tắt kiểm tra cổng khi restore
scripts/quality.ps1          quality gate
exports/                     backup, gói release, bundle (ngoài Git)
logs/                        log (ngoài Git)
```

## 7. Luồng dữ liệu chính

### Quét fanpage và tự tải media
```text
Người dùng bấm quét → route scraper → PageScraper (Chrome CDP, profile của tài khoản)
→ lưu bài vào SQLite (transaction; lỗi ghi thì không đẩy cursor)
→ tạo batch trong download_queue (SQLite) → downloader lấy batch khi rảnh
→ tải media vào .part → thay thế nguyên tử → cập nhật trạng thái bài
```
Lỗi ở bước nào thì trạng thái đã ghi vẫn nhất quán: batch chưa xong ở trạng thái `queued`/`interrupted`, không mất hàng đợi.

### Khởi động lại sau khi tắt đột ngột
```text
lifespan → recover_interrupted_task_runs (task running → interrupted)
        → recover_interrupted_downloads (download dở → cần xử lý lại)
        → start_pending_downloads_after_startup (chạy lại batch đã queued, một batch tại một thời điểm)
```

### Export / import profile
```text
Export: lấy account (đã giải mã secret) → manifest.json + thư mục Chrome session → .tinix-profile / .tinix-profiles.zip
Import: kiểm tra đường dẫn an toàn → giải nén vào thư mục tạm → thay thế vào profile đích → ghi DB; lỗi thì rollback
```
Định dạng này được chia sẻ với Tinix-Social-Hub. Xem `docs/TINIX_PROFILE_BUNDLE.md`.

## 8. Quyền sở hữu state

| State | Chủ sở hữu | Lưu ở | Ghi chú |
|---|---|---|---|
| Tài khoản Facebook, secret | `core/db_storage.py` | SQLite `fb_accounts` | Secret mã hóa DPAPI khi ghi |
| Tài khoản social và liên kết profile | `core/db_storage.py` | SQLite `social_accounts` | `AUTOINCREMENT` |
| Hàng đợi tải | `web/routes/downloader.py` + `core/db_storage.py` | SQLite `download_queue*` | Khôi phục khi khởi động |
| Lịch sử tác vụ | `core/db_storage.py` | SQLite `task_runs` | Tác vụ dở → `interrupted` |
| Khóa profile | `core/profile_lease.py` | Bộ nhớ tiến trình | Mất khi app tắt |
| Session WebUI | `web/security.py` | Bộ nhớ tiến trình | Tạo mới mỗi lần khởi động |
| Cấu hình | `utils/config.py` | `config.json`, `.env` | Secret trong config mã hóa DPAPI |
| Media | `core/downloader.py` | Thư mục `_DOWNLOAD/` (cấu hình được) | Ghi qua `.part` |

## 9. Lưu trữ dữ liệu

- **SQLite:** `tinix_scraper.db`, schema v14, WAL. Backup/restore qua `manage_database.py` (đóng app trước khi restore).
- **Thư mục media:** ảnh/video theo bài, có tên ổn định; migration cấu trúc phẳng có backup trước.
- **Chrome profiles:** thư mục riêng cho từng tài khoản; chứa cookie phiên (không mã hóa ngoài DPAPI của Chrome).
- **Không lưu trong Git:** `.env`, `config.json`, `*.db`, `logs/`, `exports/`, `_DOWNLOAD/`, `chrome_profile*/`.

## 10. Giao tiếp

- HTTP JSON `/api/*` (cần cookie phiên trừ health).
- WebSocket `/ws` đẩy log và trạng thái cho giao diện.
- Chrome qua CDP cổng cục bộ theo tài khoản (`127.0.0.1`).

## 11. Tác vụ nền

- **Download orchestrator:** một batch tại một thời điểm. Khi profile bị khóa, batch quay về `queued` và được thử lại với backoff lũy thừa tối đa 5 phút; khi thành công, backoff được reset.
- **Quét:** worker theo tài khoản, dùng profile lease.
- **Khôi phục:** chạy một lần khi khởi động.

## 12. Tích hợp bên ngoài

- **Facebook:** web (không qua API chính thức cho việc quét/tải). Preflight kiểm tra phiên; đăng nhập tự động dùng `core/fb_login.py`.
- **Facebook Graph/OAuth:** tùy chọn, cấu hình trong `.env` (xem `.env.template`).
- **yt-dlp:** tải video.
- **Chrome/Edge:** mở App Mode và điều khiển profile.

## 13. Xác thực và phân quyền

- Không có tài khoản người dùng cho WebUI. Bảo vệ dựa trên localhost, host/origin và cookie phiên mỗi lần khởi động.
- Không có cơ chế phân quyền nhiều người dùng.

## 14. Giới hạn kiến trúc đã biết

- Chỉ chạy trên Windows (DPAPI, wscript, Chrome/Edge).
- Chỉ một tiến trình WebUI tại một thời điểm (dựa vào cổng 7866).
- Không auto-update, không cài đặt dạng installer.
- Lệnh `restore` không kiểm tra lock SQLite ngoài cổng app; dựa vào việc người dùng đóng app.
