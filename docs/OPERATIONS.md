# Vận hành Tinix FB Studio

## Phạm vi an toàn

Tinix là ứng dụng Windows chạy cục bộ tại `127.0.0.1`. Không đổi host thành
`0.0.0.0`, không reverse-proxy ra LAN/Internet và không vô hiệu hóa session
cookie, kiểm tra Host hoặc kiểm tra Origin. API health tại
`/api/system/health` công khai để kiểm tra khởi động, chỉ chấp nhận Host
loopback và không trả đường dẫn database hay credential.

Các thao tác test/quality không đăng nhập, tải nội dung hay đăng bài thật. Những
thao tác Facebook chỉ bắt đầu khi người dùng chủ động chạy chức năng tương ứng
trong WebUI.

Khi chạy smoke test cô lập, có thể đặt biến môi trường `TINIX_DB_PATH` trỏ tới
database tạm. Biến môi trường này có độ ưu tiên cao nhất trong tiến trình đó;
hãy xóa biến trước khi chạy dữ liệu thật.

## Khởi động và dừng

1. Chạy `python main.py` hoặc `Start Tinix FB Studio.bat`.
2. Xác nhận WebUI mở ở port cục bộ bắt đầu từ 7866, trạng thái Realtime là
   `Connected` và không có cảnh báo môi trường ở đầu trang.
   Tinix dùng cố định port 7866; nếu port này đang được ứng dụng khác sử dụng,
   launcher dừng với thông báo lỗi thay vì tự đổi URL.
3. Nếu tải/quét bằng Chrome Profile: tạo hoặc chọn account, mở Chrome để đăng
   nhập Facebook rồi chạy **Check Preflight**. Account không đạt preflight sẽ
   không nhận Page hoặc bài tải.
4. Trong **Quét Page**, chọn rõ có cần **Tự tải media bài mới** hay chỉ lưu dữ
   liệu vào Kho Bài Viết.
5. Không mở thủ công Chrome của account đang quét/tải/tìm Page. Mỗi profile chỉ
   có một tác vụ nền sử dụng tại một thời điểm.
6. Media tự tải từ một lần quét khi downloader đang bận sẽ được lưu vào queue
   SQLite và tự chạy sau lượt tải hiện tại. **Dừng lượt hiện tại** giữ queue;
   **Dừng tất cả** hủy cả lượt đang chạy lẫn mọi batch chờ.
7. Dừng queue/download/scrape đang chạy trước khi đóng cửa sổ terminal.

Nếu ứng dụng bị đóng khi queue đang chạy, lần khởi động tiếp theo đưa trạng thái
tải dở về `Tải lỗi`, đánh dấu phiên trong **Hoạt động gần đây** là `Bị gián
đoạn`, và đưa batch Auto Download dở về queue để tiếp tục theo thứ tự. Lịch sử
chỉ giữ thống kê và lựa chọn không nhạy cảm, không giữ URL, cookie hoặc
credential.

Khi khởi động, Tinix cũng chuyển các thư mục media cũ có tên số sang flat
storage. Nếu một lần chuyển bị ngắt, bài tương ứng được giữ ở trạng thái `Tải
lỗi` cho đến khi migration hoàn tất; không xóa thủ công file nguồn còn lại.

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
2. Mở **Kho Bài Viết** và chọn các Page cần xóa, hoặc chọn dọn toàn bộ kho.
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
- **Account không sẵn sàng:** mở Chrome Profile tương ứng, đăng nhập lại hoặc
  xử lý checkpoint rồi chạy **Check Preflight**. Không chạy lại hàng đợi trước
   khi account đạt trạng thái sẵn sàng.
- **Chrome Profile đang được dùng:** chờ tác vụ đang dùng account kết thúc hoặc
  dừng tác vụ đó trước khi mở profile/check preflight.
- **Tác vụ bị gián đoạn:** xem **Hoạt động gần đây** để biết loại tác vụ và số
  mục đã xử lý, sau đó chạy lại đầu vào cần thiết. Lịch sử không lưu lại URL để
  tránh giữ dữ liệu riêng tư.
- **Database integrity khác ok:** dừng ứng dụng, giữ nguyên file lỗi, verify các
  backup và restore bản gần nhất đạt kiểm tra.

## Log và dữ liệu cần bảo vệ

Không gửi `.env`, `config.json`, database, backup, cookie, token hoặc thư mục
`Chrome Profiles` khi báo lỗi. Trước khi chia sẻ log, tìm và xóa email, UID, URL
riêng tư và mọi chuỗi credential.
