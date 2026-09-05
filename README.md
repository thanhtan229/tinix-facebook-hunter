# Tinix-Facebook-Hunter

Ứng dụng WebUI chạy cục bộ để tải media Facebook, quét fanpage và quản lý tài
khoản.

Tab Quét Page hỗ trợ lưu Fanpage yêu thích, gán Chrome profile, quét tuần tự và
chỉ lưu các bài mới kể từ mốc của lần quét thành công gần nhất. Danh sách yêu
thích và mốc quét không bị xóa khi dọn Kho Dữ Liệu.

## Yêu cầu

- Windows 10/11
- Python 3.11 trở lên
- Google Chrome

## Cài đặt

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Sao chép `.env.template` thành `.env` nếu sử dụng Facebook App OAuth. Không
commit hoặc chia sẻ `.env`, `config.json`, database và thư mục Chrome Profiles.

## Chạy

```powershell
python main.py
```

Ứng dụng chỉ lắng nghe tại `127.0.0.1`, tự mở trình duyệt và tạo một phiên bảo
mật mới sau mỗi lần khởi động. API không được thiết kế để công khai ra mạng LAN
hoặc Internet.

## Kiểm thử

```powershell
python -m pip install -r requirements-dev.txt
./scripts/quality.ps1
```

Quality gate kiểm tra dependency, Ruff, mypy, bộ kiểm thử backend/API/queue,
branch coverage tối thiểu 75% cho các module mới/rủi ro cao và cú pháp
JavaScript. GitHub Actions chạy cùng script trên Windows cho mỗi push và pull
request.

## Dữ liệu nhạy cảm

Tài khoản Facebook, cookie, token và profile Chrome là dữ liệu riêng tư. API
danh sách chỉ trả metadata và các cờ `has_password`, `has_2fa`, `has_cookie`;
không trả giá trị bí mật về trình duyệt.

Secrets mới được mã hóa bằng Windows DPAPI trước khi ghi vào SQLite hoặc
`config.json`. Với database cũ, mở **Cài đặt → Mã hóa secrets hiện có**. Ứng
dụng tạo file `*.pre-secrets-*.bak` trước khi migration. Giữ backup ở nơi an
toàn cho đến khi đã kiểm tra đăng nhập; backup vẫn chứa dữ liệu cũ dạng rõ.

DPAPI gắn dữ liệu với tài khoản Windows hiện tại. Nếu cần chuyển máy hoặc đổi
tài khoản Windows, hãy dùng backup chưa mã hóa hoặc xuất lại credentials trước.

## Backup và khôi phục

Đóng ứng dụng trước khi khôi phục. Lệnh backup dùng SQLite Online Backup API nên
bao gồm cả dữ liệu đang ở WAL và tự kiểm tra integrity:

```powershell
python manage_database.py backup
python manage_database.py verify --file "D:\backup\tinix.db.backup-YYYYMMDD_HHMMSS.sqlite"
python manage_database.py restore --file "D:\backup\tinix.db.backup-YYYYMMDD_HHMMSS.sqlite" --confirm
```

Restore luôn tạo thêm một bản backup của database hiện tại trước khi ghi đè.
Backup vẫn là dữ liệu nhạy cảm và không được commit hoặc gửi qua kênh công khai.

## Dọn Kho Dữ Liệu

Trong tab **Kho Dữ Liệu**, chọn Page rồi dùng **Xóa Pages đã chọn**, hoặc dùng
**Dọn toàn bộ kho** để xóa mọi dữ liệu scraper. Mỗi thao tác hiển thị cửa sổ xác
nhận cuối cùng và tự tạo/verify backup database trước khi xóa. Tài khoản, token
và fanpage quản lý không thuộc phạm vi dọn kho.

Tùy chọn **Xóa cả thư mục media đã tải** mặc định tắt. Khi bật, ứng dụng chỉ xóa
đường dẫn nằm bên dưới thư mục output đã cấu hình, không xóa output root, không
đi theo symlink ra ngoài và không xóa thư mục còn được bài khác tham chiếu.
Backup SQLite không chứa media, nên media đã xóa không thể khôi phục từ file
backup database.

Chi tiết vận hành và xử lý sự cố nằm tại [docs/OPERATIONS.md](docs/OPERATIONS.md);
quy trình phát hành tại [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).
