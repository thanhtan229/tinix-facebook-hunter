# Vận hành Tinix FB Studio

## Phạm vi an toàn

Tinix là ứng dụng Windows chạy cục bộ tại `127.0.0.1`. Không đổi host thành
`0.0.0.0`, không reverse-proxy ra LAN/Internet và không vô hiệu hóa session
cookie hoặc kiểm tra Origin. API health tại `/api/system/health` yêu cầu phiên
WebUI hợp lệ và không trả đường dẫn database hay credential.

Các thao tác test/quality không đăng nhập, tải nội dung hay đăng bài thật. Những
thao tác Facebook chỉ bắt đầu khi người dùng chủ động chạy chức năng tương ứng
trong WebUI.

Khi chạy smoke test cô lập, có thể đặt biến môi trường `TINIX_DB_PATH` trỏ tới
database tạm. Biến môi trường này có độ ưu tiên cao nhất trong tiến trình đó;
hãy xóa biến trước khi chạy dữ liệu thật.

## Khởi động và dừng

1. Chạy `python main.py` hoặc `Start Tinix FB Studio.bat`.
2. Xác nhận WebUI mở ở port cục bộ bắt đầu từ 7866 và trạng thái Realtime là
   `Connected`.
3. Dừng queue/download/scrape đang chạy trước khi đóng cửa sổ terminal.

Nếu ứng dụng bị đóng khi queue đang chạy, lần khởi động tiếp theo tự đưa các job
WebUI còn `Running` về `Pending`, kèm ghi chú khôi phục.

## Backup định kỳ

Đóng ứng dụng nếu có thể, rồi chạy:

```powershell
python manage_database.py backup
```

Có thể chọn file đích:

```powershell
python manage_database.py backup --file "E:\Tinix Backups\tinix-2026-08-31.sqlite"
python manage_database.py verify --file "E:\Tinix Backups\tinix-2026-08-31.sqlite"
```

`integrity` phải là `ok` và `supported` phải là `true`. Lưu backup trên ổ mã hóa
và giới hạn quyền truy cập. DPAPI bảo vệ secrets mới nhưng backup có thể chứa dữ
liệu cũ chưa migration.

## Khôi phục

1. Đóng Tinix hoàn toàn và kiểm tra không còn tiến trình `python`/`uvicorn` của
   ứng dụng.
2. Verify file backup.
3. Chạy restore có xác nhận rõ ràng:

```powershell
python manage_database.py restore --file "E:\Tinix Backups\tinix-2026-08-31.sqlite" --confirm
```

CLI tạo một file `*.backup-*.sqlite` từ database hiện tại trước khi restore và
in đường dẫn đó. Khởi động lại, mở dashboard và kiểm tra `/api/system/health`.

## Migration secrets

Trong **Cài đặt**, chọn **Mã hóa secrets hiện có** đúng một lần cho database cũ.
Ứng dụng tạo `*.pre-secrets-*.bak` trước khi thay đổi. Sau migration:

1. Kiểm tra đăng nhập bằng một tài khoản thử nghiệm được phép sử dụng.
2. Giữ backup ở nơi an toàn cho đến khi xác nhận hoàn tất.
3. Không chuyển ciphertext DPAPI sang tài khoản Windows/máy khác và kỳ vọng nó
   giải mã được.

## Dọn dữ liệu scraper

1. Dừng tác vụ Quét Page và Tải xuống.
2. Mở **Kho Dữ Liệu** và chọn các Page cần xóa, hoặc chọn dọn toàn bộ kho.
3. Chỉ bật xóa media khi chắc chắn không cần các file đã tải.
4. Kiểm tra số Page/bài/media trong cảnh báo rồi nhấn **Xóa dữ liệu**.
5. Ghi lại đường dẫn backup được hiển thị trong Terminal Logs.

Cleanup chỉ tác động `pages` và `posts`. Database backup được tạo và kiểm tra
trước transaction xóa. Tài khoản, token, fanpage quản lý, content pool và
lịch sử đăng được giữ nguyên. Media nằm ngoài output root, media còn được bài
khác tham chiếu và output root luôn được bỏ qua.

## Xử lý sự cố

- **Realtime Disconnected:** kiểm tra đã cài `websockets`, tải lại trang, xem
  terminal có lỗi WebSocket hay không.
- **Health schema=false:** không chạy queue; cập nhật ứng dụng. Ứng dụng từ chối
  database có schema mới hơn phiên bản đang chạy.
- **Health chrome=false:** cài Google Chrome ở vị trí chuẩn hoặc thêm Chrome vào
  `PATH`.
- **Job Failed:** xem `error_log`, sửa tài khoản/page/time rồi dùng Retry. Không
  xóa job `Running`; hãy dừng queue trước.
- **Database integrity khác ok:** dừng ứng dụng, giữ nguyên file lỗi, verify các
  backup và restore bản gần nhất đạt kiểm tra.

## Log và dữ liệu cần bảo vệ

Không gửi `.env`, `config.json`, database, backup, cookie, token hoặc thư mục
`Chrome Profiles` khi báo lỗi. Trước khi chia sẻ log, tìm và xóa email, UID, URL
riêng tư và mọi chuỗi credential.
