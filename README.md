# Tinix-Facebook-Hunter

Ứng dụng WebUI chạy cục bộ để tải media Facebook, quét fanpage và quản lý tài
khoản.

Tab Quét Page hỗ trợ lưu Fanpage yêu thích, gán Chrome profile, quét tuần tự và
chỉ lưu các bài mới kể từ mốc của lần quét thành công gần nhất.

Khi bắt đầu, WebUI kiểm tra các thành phần cần thiết. Với luồng dùng Chrome
Profile, hãy tạo account, đăng nhập Facebook trong profile rồi chạy **Check
Preflight**. Trong **Quét Page**, có thể tắt **Tự tải media bài mới** để chỉ
lưu dữ liệu vào Kho Bài Viết. Mục **Hoạt động gần đây** lưu kết quả tóm tắt của
tải/quét và đánh dấu phiên bị gián đoạn khi ứng dụng khởi động lại; không lưu
URL đầu vào, cookie hay credential. Luồng **Tìm Fanpage** cũng chạy preflight và
được ghi lịch sử. Một Chrome profile chỉ được một tác vụ nền sử dụng tại một
thời điểm; media tự tải sẽ xếp hàng nếu downloader đang bận.

## Yêu cầu

- Windows 10/11
- Python 3.11 trở lên
- Google Chrome

## Cài đặt

Cách khuyến nghị cho máy mới: cài Python 3.11, tải mã nguồn về, rồi chạy
`install.bat` trong thư mục dự án. Script tạo `.venv`, cài `requirements.txt`,
tải Chromium cho Playwright và kiểm tra lại. Chạy lại script an toàn; script
không tạo dữ liệu, tài khoản hay `.env`.

```powershell
.\install.bat
```

Cài thủ công (tương đương):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Sao chép `.env.template` thành `.env` nếu sử dụng Facebook App OAuth. Không
commit hoặc chia sẻ `.env`, `config.json`, database và thư mục Chrome Profiles.

## Chạy

Double-click `START.vbs` (chạy ngầm, mở cửa sổ ứng dụng) hoặc chạy trực tiếp:

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

Chi tiết vận hành và xử lý sự cố nằm tại [docs/OPERATIONS.md](docs/OPERATIONS.md);
quy trình phát hành tại [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).
