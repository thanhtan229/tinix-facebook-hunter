# Checklist phát hành nội bộ

## Trước khi đóng gói

- [ ] Chạy trên Windows 10/11 với Python 3.11.
- [ ] Cài `requirements.txt`, `requirements-dev.txt` và Playwright Chromium.
- [ ] `./scripts/quality.ps1` hoàn tất với exit code 0.
- [ ] Xác nhận test migration giữ nguyên file nguồn khi có trùng tên, lỗi di chuyển,
      khóa database hoặc thư mục con; retry phải giữ đúng thứ tự media và chỉ báo
      hoàn tất sau khi migration xong.
- [ ] `/api/system/health` báo database/schema/Windows/Chrome/Playwright/yt-dlp
      đều đạt.
- [ ] Không có `.env`, database, backup, log hoặc `Chrome Profiles` trong commit.
- [ ] Tạo và verify một backup bằng `manage_database.py`.

## Smoke test WebUI

- [ ] Trang chính tải được, không có lỗi console.
- [ ] Realtime hiển thị `Connected`.
- [ ] Mở/đóng Cài đặt và chuyển qua tất cả tab.
- [ ] Khi thiếu một thành phần health, UI hiển thị cảnh báo và không báo hệ
      thống sẵn sàng.
- [ ] Khi chưa có account active, tải bằng Profile dẫn người dùng đến Tài khoản;
      sau khi Check Preflight đạt, tác vụ mới bắt đầu.
- [ ] Quét thử cả hai chế độ: có và không có **Tự tải media bài mới**; kiểm tra
      chỉ chế độ đầu tiên tạo tác vụ tải.
- [ ] Kiểm tra account không đạt preflight không nhận Page; account đạt vẫn tiếp
      tục xử lý hàng đợi của mình.
- [ ] Dừng một tải/quét thử, khởi động lại và kiểm tra **Hoạt động gần đây**
      hiển thị trạng thái phù hợp mà không chứa URL, cookie hoặc credential.
- [ ] Tạo hai batch Auto Download; kiểm tra **Dừng lượt hiện tại** giữ batch
      tiếp theo, **Dừng tất cả** hủy queue và restart khôi phục batch đang dở.
- [ ] Cleanup hiển thị đúng số lượng, tạo backup và chỉ xóa dữ liệu scraper đã
      chọn; kiểm tra media ngoài output root vẫn còn nguyên.
- [ ] API accounts/config không trả password, cookie hoặc token.
- [ ] API bảo vệ không chấp nhận request thiếu session; Host phải là loopback và
      request có Origin phải khớp HTTP/địa chỉ/port local đang mở WebUI.

## Kiểm thử tích hợp có kiểm soát

- [ ] Chỉ dùng tài khoản/page thử nghiệm đã được phép.
- [ ] Chỉ quét hoặc tải một Page/bài thử nghiệm được phép, xác nhận trạng thái
      và file kết quả trong Kho Bài Viết.
- [ ] Không chạy thử tích hợp trên danh sách Page hoặc account sản xuất.
- [ ] Dừng ngay nếu Facebook hiển thị checkpoint, challenge hoặc giới hạn.

## Phát hành

- [ ] Ghi phiên bản và tóm tắt thay đổi.
- [ ] Đính kèm hướng dẫn backup/restore và lưu ý DPAPI.
- [ ] Lưu artifact/checksum trong kho nội bộ có kiểm soát truy cập.
- [ ] Có người chịu trách nhiệm rollback và đường dẫn backup đã verify.
