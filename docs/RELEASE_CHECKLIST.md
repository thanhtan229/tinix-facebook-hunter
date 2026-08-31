# Checklist phát hành nội bộ

## Trước khi đóng gói

- [ ] Chạy trên Windows 10/11 với Python 3.11.
- [ ] Cài `requirements.txt`, `requirements-dev.txt` và Playwright Chromium.
- [ ] `./scripts/quality.ps1` hoàn tất với exit code 0.
- [ ] `/api/system/health` báo database/schema/Windows/Chrome/Playwright/yt-dlp
      đều đạt.
- [ ] Không có `.env`, database, backup, log hoặc `Chrome Profiles` trong commit.
- [ ] Tạo và verify một backup bằng `manage_database.py`.

## Smoke test WebUI

- [ ] Trang chính tải được, không có lỗi console.
- [ ] Realtime hiển thị `Connected`.
- [ ] Mở/đóng Cài đặt và chuyển qua tất cả tab.
- [ ] Quét một thư mục nội dung thử; preview chỉ đọc file trong thư mục đã chọn.
- [ ] Tạo lịch thử trong cửa sổ 20 phút–29 ngày, lưu và thấy job `Pending`.
- [ ] Retry/delete chỉ tác động job hợp lệ; dừng queue giữ job chưa chạy là
      `Pending`.
- [ ] Cleanup hiển thị đúng số lượng, tạo backup và chỉ xóa dữ liệu scraper đã
      chọn; kiểm tra media ngoài output root vẫn còn nguyên.
- [ ] API accounts/config không trả password, cookie hoặc token.

## Kiểm thử tích hợp có kiểm soát

- [ ] Chỉ dùng tài khoản/page thử nghiệm đã được phép.
- [ ] Đăng một nội dung không nhạy cảm ở chế độ quan sát, xác nhận trạng thái
      `Scheduled` và kiểm tra trực tiếp trên Facebook.
- [ ] Không chạy thử tích hợp trên danh sách tài khoản hoặc lịch sản xuất.
- [ ] Dừng ngay nếu Facebook hiển thị checkpoint, challenge hoặc giới hạn.

## Phát hành

- [ ] Ghi phiên bản và tóm tắt thay đổi.
- [ ] Đính kèm hướng dẫn backup/restore và lưu ý DPAPI.
- [ ] Lưu artifact/checksum trong kho nội bộ có kiểm soát truy cập.
- [ ] Có người chịu trách nhiệm rollback và đường dẫn backup đã verify.
