# Tinix Profiles ZIP v1

Tinix FB Down và Tinix Social Hub dùng chung file `.tinix-profiles.zip` để chuyển toàn bộ account và Chrome profile trong một lần.

## Export

Mở **Quản Lý Tài Khoản & Chrome Profiles**, đóng Chrome của tất cả account, rồi chọn **Export All Profiles ZIP**. File được tạo trong `exports/profiles/` và chứa tên account, nền tảng, username tùy chọn cùng bản sao Chrome profile.

## Import

Chọn **Import Profiles ZIP** và dán đường dẫn tuyệt đối tới file ZIP. FB Down tạo toàn bộ account Facebook cùng tên và sao chép từng Chrome profile vào thư mục do app quản lý. Nếu ZIP từ Social Hub có nền tảng khác, FB Down bỏ qua các profile không phải Facebook và báo số lượng.

Định dạng thư mục `.tinix-profile` cũ vẫn được hỗ trợ. File ZIP mới có `profile_content: "session-only-v1"` và chỉ lưu tên account cùng trạng thái cần cho phiên Chrome (Local State, Preferences, cookies, Local/Session Storage, IndexedDB và WebStorage). Mật khẩu, mã 2FA, mật khẩu email, cache, model Chromium và file tạm không được đóng gói.

Nút **Dọn profile** quét trước dung lượng có thể giải phóng rồi xóa cache/model có thể tạo lại của tất cả profile. Phải đóng Chrome trước khi chạy; dữ liệu phiên đăng nhập và thông tin account được giữ nguyên.
