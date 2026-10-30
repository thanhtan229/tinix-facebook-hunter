# PLAN.md

> Kế hoạch triển khai cho công việc lớn, nhiều bước. Không dùng làm nhật ký tiến độ.

## 0. Metadata

**Project / Feature:** Tinix FB Studio — kế hoạch hardening sau Final Production Review (2026-10-29)
**Plan Version:** 1.0
**Status:** In Progress
**Owner / Primary Agent:** Boss (Claude) theo yêu cầu Product Owner
**Created:** 2026-10-30
**Last Updated:** 2026-10-30

## 1. Mục tiêu

Xử lý các finding của Final Production Review trước khi dùng thực tế.

## 2. Phạm vi

### Trong phạm vi
- Mất dấu tiếng Việt trong log/selector đăng nhập (`core/fb_login.py`, `core/fanpage_scanner.py`, `core/page_scraper.py`).
- Coverage gate phản ánh đúng phạm vi đo.
- Xóa Chrome profile khi xóa tài khoản (tùy chọn, mặc định tắt).

### Ngoài phạm vi
- Mã hóa bundle export/import (đang chờ quyết định vì ảnh hưởng định dạng chia sẻ với Tinix-Social-Hub và cần thêm dependency).
- Chạy tải/quét trên tài khoản Facebook thật khi chưa có phạm vi được duyệt.

## 3. Trạng thái các finding

| # | Finding | Trạng thái |
|---|---|---|
| 1 | Secret plaintext trong bundle export | Chờ quyết định (xem mục 4) |
| 2 | Lỗi giải mã bị che | Đã sửa, có test, reviewer LGTM |
| 3 | Restore khi app đang chạy | Đã sửa, có test |
| 4 | Retry vô hạn | Đã sửa (backoff tối đa 5 phút), có test |
| 5 | Xóa account để lại profile | Chưa làm |
| 6 | Rollback import xóa nhầm thư mục | Đã sửa, có test hồi quy |
| 7 | Coverage gate đo ít module | Chờ quyết định (xem mục 4) |
| 8 | Mất dấu tiếng Việt | Chưa làm; ảnh hưởng bộ chọn đăng nhập, cần kiểm chứng trên giao diện thật |
| 9 | Tài liệu còn template | Đã làm cho DEVELOPMENT_WORKFLOW, ARCHITECTURE, PLAN |
| 10 | Hàng đợi tự chạy khi khởi động | Chờ xác nhận hành vi |

## 4. Quyết định còn lại

1. Bundle: (a) mã hóa bằng mật khẩu người dùng, cần sửa Tinix-Social-Hub và thêm dependency; (b) mặc định không đưa secret vào bundle, chỉ đưa khi bật tùy chọn có cảnh báo; (c) PO chấp nhận rủi ro bằng văn bản.
2. Coverage: giữ ngưỡng 75% trên 5 module hiện tại, hoặc mở rộng phạm vi đo (đo thực tế toàn bộ `core`, `web`, `utils` là 54%).

## 5. Kiểm chứng

- Mỗi thay đổi có test hồi quy và được reviewer độc lập đánh giá.
- Quality gate: `scripts/quality.ps1`.
- Không kiểm chứng trên tài khoản Facebook thật trong kế hoạch này.
