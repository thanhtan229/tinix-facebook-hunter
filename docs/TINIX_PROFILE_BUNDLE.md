# Tinix Profiles ZIP v1

Tinix FB Down và Tinix Social Hub dùng chung file `.tinix-profiles.zip` để chuyển toàn bộ account và Chrome profile trong một lần.

## Export

Mở **Quản Lý Tài Khoản & Chrome Profiles**, đóng Chrome của tất cả account, rồi chọn **Export All Profiles ZIP**. File được tạo trong `exports/profiles/` và chứa tên account, nền tảng, username tùy chọn cùng bản sao Chrome profile.

## Import

Chọn **Import Profiles ZIP** và dán đường dẫn tuyệt đối tới file ZIP. FB Down tạo toàn bộ account Facebook cùng tên và sao chép từng Chrome profile vào thư mục do app quản lý. Nếu ZIP từ Social Hub có nền tảng khác, FB Down bỏ qua các profile không phải Facebook và báo số lượng.

Định dạng thư mục `.tinix-profile` cũ vẫn được hỗ trợ. File ZIP không lấy mật khẩu, mã 2FA, mật khẩu email hay cookie riêng từ cơ sở dữ liệu ứng dụng. Cache và Chrome lock file bị loại bỏ.
