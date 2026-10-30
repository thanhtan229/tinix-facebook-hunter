# RESEARCH_COMPARISON.md

> So sánh phương án khi có nhiều lựa chọn kỹ thuật thật sự.

## Trạng thái

Chưa có so sánh nào được ghi lại.

Các lựa chọn đang chờ quyết định, sẽ ghi ở đây khi có so sánh:
- Mã hóa bundle export: mật khẩu người dùng (AES-GCM qua thư viện `cryptography`, đã có trong môi trường nhưng chưa khai báo trong `requirements.txt`) so với không đưa secret vào bundle mặc định.
- Đóng gói Windows: `install.bat` (đang dùng) so với bản `.exe` (chưa làm).
