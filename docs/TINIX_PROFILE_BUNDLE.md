# Tinix Profiles ZIP v1

Tinix FB Down và Tinix Social Hub dùng chung file `.tinix-profiles.zip` để chuyển toàn bộ account và Chrome profile trong một lần.

## Export

Mở **Quản Lý Tài Khoản & Chrome Profiles**, đóng Chrome của tất cả account, rồi chọn **Export All Profiles ZIP**. File được tạo trong `exports/profiles/` và chứa tên account, nền tảng, username tùy chọn cùng bản sao Chrome profile.

## Import

Chọn **Import Profiles ZIP** và dán đường dẫn tuyệt đối tới file ZIP. FB Down tạo toàn bộ account Facebook cùng tên và sao chép từng Chrome profile vào thư mục do app quản lý. Nếu ZIP từ Social Hub có nền tảng khác, FB Down bỏ qua các profile không phải Facebook và báo số lượng.

Định dạng thư mục `.tinix-profile` cũ vẫn được hỗ trợ. File ZIP mới có `profile_content: "session-only-v1"`. Mặc định file lưu tên account, username/UID, email và trạng thái cần cho phiên Chrome (Local State, Preferences, cookies, Local/Session Storage, IndexedDB và WebStorage). Mật khẩu, secret 2FA, mật khẩu email và cookie lưu trong database **chỉ được đưa vào khi người dùng chọn tường minh** (`include_secrets`). Cache, model Chromium và file tạm không được đóng gói. `contains_account_secrets` phản ánh đúng nội dung file: `true` chỉ khi có credential. **Lưu ý:** phiên Chrome (cookie đăng nhập) luôn có trong file, nên file vẫn phải được bảo quản như dữ liệu đăng nhập; file ZIP không mã hóa.

Nút **Dọn profile** quét trước dung lượng có thể giải phóng rồi xóa cache/model có thể tạo lại của tất cả profile. Phải đóng Chrome trước khi chạy; dữ liệu phiên đăng nhập và thông tin account được giữ nguyên.
