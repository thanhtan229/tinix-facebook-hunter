# Checklist phát hành nội bộ

## Trước khi đóng gói

- [x] Chạy trên Windows 10/11 với Python 3.11.
- [x] Cài `requirements.txt`, `requirements-dev.txt` và Playwright Chromium.
- [x] `./scripts/quality.ps1` hoàn tất với exit code 0.
- [x] Xác nhận test migration giữ nguyên file nguồn khi có trùng tên, lỗi di chuyển,
      khóa database hoặc thư mục con; retry phải giữ đúng thứ tự media và chỉ báo
      hoàn tất sau khi migration xong.
- [x] `/api/system/health` báo database/schema/Windows/Chrome/Playwright/yt-dlp
      đều đạt.
- [x] Không có `.env`, database, backup, log hoặc `Chrome Profiles` trong snapshot source.
      Chưa tạo commit; các đường dẫn nhạy cảm không được Git track và bị loại khỏi ZIP.
- [x] Tạo và verify một backup bằng `manage_database.py`.

## Smoke test WebUI

- [x] Trang chính tải được, không có lỗi console.
- [x] Realtime hiển thị `Connected`.
- [x] Mở/đóng Cài đặt và chuyển qua tất cả tab.
- [x] Khi thiếu một thành phần health, UI hiển thị cảnh báo và không báo hệ
      thống sẵn sàng.
- [x] Khi chưa có account active, tải bằng Profile dẫn người dùng đến Tài khoản;
      sau khi Check Preflight đạt, tác vụ mới bắt đầu.
- [x] Quét thử cả hai chế độ: có và không có **Tự tải media bài mới**; kiểm tra
      chỉ chế độ đầu tiên tạo tác vụ tải.
- [x] Kiểm tra account không đạt preflight không nhận Page; account đạt vẫn tiếp
      tục xử lý hàng đợi của mình.
- [x] Dừng một tải/quét thử, khởi động lại và kiểm tra **Hoạt động gần đây**
      hiển thị trạng thái phù hợp mà không chứa URL, cookie hoặc credential.
- [x] Tạo hai batch Auto Download; kiểm tra **Dừng lượt hiện tại** giữ batch
      tiếp theo, **Dừng tất cả** hủy queue và restart khôi phục batch đang dở.
- [x] Cleanup hiển thị đúng số lượng, tạo backup và chỉ xóa dữ liệu scraper đã
      chọn; kiểm tra media ngoài output root vẫn còn nguyên.
- [x] API accounts/config không trả password, cookie hoặc token.
- [x] API bảo vệ không chấp nhận request thiếu session; Host phải là loopback và
      request có Origin phải khớp HTTP/địa chỉ/port local đang mở WebUI.

## Kiểm thử tích hợp có kiểm soát

- [x] Chỉ dùng tài khoản/Page được người dùng cho phép: account #9 và một Page có sẵn.
      Người dùng đã cho phép dùng account/URL bất kỳ; không yêu cầu sandbox riêng.
- [x] Chỉ quét hoặc tải một Page/bài thử nghiệm được phép, xác nhận trạng thái
      và file kết quả trong Kho Bài Viết.
- [x] Không chạy thử tích hợp hàng loạt trên danh sách Page/account; chỉ một Page/bài.
      Account có sẵn được dùng theo chỉ định rõ của người dùng.
- [x] Dừng ngay nếu Facebook hiển thị checkpoint, challenge hoặc giới hạn.

## Phát hành

- [x] Ghi phiên bản và tóm tắt thay đổi.
- [x] Đính kèm hướng dẫn backup/restore và lưu ý DPAPI.
- [x] Lưu artifact/checksum trong kho nội bộ có kiểm soát truy cập.
- [x] Có người chịu trách nhiệm rollback và đường dẫn backup đã verify.
      Người chịu trách nhiệm rollback: **Tinix** (do Product Owner chỉ định, 2026-10-27).
      Backup đã verify: `exports/releases/tinix_scraper.db.backup-20261003_085213_115026.sqlite` (schema14, integrity ok, 2026-10-03).

## Bằng chứng đóng checklist — 2026-10-03

Bản local v1.21.44. Dấu [x] có nghĩa đã kiểm tra trong phạm vi ghi dưới đây,
không có nghĩa mọi mục đều là thao tác Facebook thật hoặc release đã được phê duyệt.

| Nhóm | Bằng chứng / phạm vi |
|---|---|
| Windows/runtime | Windows 11 Pro 10.0.26200, Python 3.11.9; dependency check đạt, Playwright Chromium có trên máy |
| Quality/migration/security | Quality gate 235 test + 10 subtest, coverage81%; test SQLite thật và controlled failures cho conflict/move/lock/retry, secrets/session/Host/Origin |
| UI | Chrome thật: bốn tab, realtime, Cài đặt mở/đóng; mô phỏng thiếu Chrome và không có account active, UI cảnh báo/chuyển Tài khoản. Không lưu thay đổi config từ modal |
| Preflight | Account #3/#6 AUTH_EXPIRED không dùng tải; #9 READY. Worker preflight/rejection và phân phối account được test bằng doubles; không cố tạo checkpoint thật |
| Scan/download | Facebook thật: tắt auto không tạo tải; bật auto tạo task51 completed, video64,34 giây và preview verify; tải thủ công hai ảnh2000x2000 đạt |
| Stop/queue/recovery | Hai batch SQLite thật: stop-current giữ2, stop-all hủy2; restart claim FIFO có test. Backend cô lập kill/restart: session cũ401, account persist, taskinterrupted, orphanfailed; history API chỉ có summary được allow-list. UI stop/pause được controlled test |
| Cleanup | Test DB/media tạm: preview/scope/backup, giữ file ngoài root, bảo vệ shared/nested refs; không cleanup dữ liệu thật |
| Backup | CLI backup/verify dữ liệu hiện tại đạt integrityok/schema14. Bản phục hồi nằm ở exports/releases/tinix_scraper.db.backup-20261003_085213_115026.sqlite |
| Artifact | ZIP source của working tree, SHA256SUMS.txt và bằng chứng trong exports/releases; ACL chỉ Admin/Administrators/SYSTEM. Đây là snapshot portable source cần runtime/dependency, không phải installer |
| Tài liệu rollback | docs/OPERATIONS.md có backup/restore, DB corrupt, DPAPI. Người chịu trách nhiệm rollback còn chờ chỉ định |

Không reboot máy hoặc thử power-loss phần cứng: đây không phải mục trong checklist
phát hành này. Workload lớn/full-profile portability vẫn chưa có tiêu chí nghiệm thu,
không được coi là đã benchmark chỉ vì quality gate đạt. Artifact local đã chuẩn bị;
chưa upload ra kho từ xa hoặc công bố release. Không tạo Git commit.
