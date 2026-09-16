# Kiểm toán hoàn thành kế hoạch cải tiến

Ngày kiểm toán: 2026-09-14. Phạm vi: trạng thái sẵn sàng phát hành nội bộ của
Tinix FB Studio, không thực hiện thao tác trên tài khoản, Page hoặc dữ liệu
Facebook thật.

| Yêu cầu | Bằng chứng hiện tại | Kết quả |
|---|---|---|
| Kiến trúc và migration | Schema v13 qua `PRAGMA user_version`; initializer chỉ chạy một lần/process và từ chối schema mới hơn. Queue Auto Download được lưu SQLite để khôi phục sau restart; migration flat storage lấy khóa ghi SQLite trước khi đổi file, chỉ nhận thư mục post số, không ghi đè/xóa đệ quy, dùng tên media ổn định để chạy lại và chỉ đổi DB khi toàn bộ thư mục đã hoàn tất | Đạt |
| Bảo vệ dữ liệu | Session bắt buộc cho API bảo vệ; health khởi động công khai chỉ trả trạng thái sẵn sàng. Host phải là loopback và Origin hiện diện phải khớp HTTP/host/port local; CSP, media allow-list, DPAPI cho config/SQLite và validation không echo request body. Danh sách API account/config đã lọc secret; dữ liệu chi tiết chỉ có trong phiên WebUI local hợp lệ | Đạt |
| Backup/restore | SQLite Online Backup API, `quick_check`, kiểm tra schema, backup tự động trước restore, CLI offline | Đạt |
| API và queue | Pydantic v2 với giới hạn/enum/extra=forbid; trạng thái download chuẩn hóa; một coordinator tuần tự hóa tải thủ công, Kho Bài Viết và Auto Download; queue SQLite có dừng lượt/dừng tất cả và recovery; preflight trước quét/tải/tìm Page; task run có recovery, giới hạn 500 bản ghi và chuẩn hóa counter cũ; Chrome profile được khóa theo tác vụ | Đạt |
| WebUI và realtime | Health banner chỉ báo sẵn sàng khi kiểm tra đạt; người dùng có thể tắt tự tải media sau quét; timeline hoạt động gần đây. Integration test ASGI xác nhận trang gốc cấp session local, các API bảo vệ chặn session/Host/Origin không hợp lệ; smoke test Chrome headless cô lập kiểm tra UI khởi động, WebSocket và tab Tài khoản | Đạt |
| Dependency và CI | Runtime/dev dependency có biên phiên bản; pip check; cùng một PowerShell quality gate trên máy dev và GitHub Actions Windows | Đạt |
| Kiểm thử | Quality gate tự động kiểm tra backend/API/security/migration/backup/queue; 150 test và 6 subtest đều đạt. Test mới bao phủ conflict, lỗi move, khóa database, retry migration, preflight quét/tìm Page, profile lease, queue Auto Download bền vững, dừng tất cả, recovery và chuẩn hóa lịch sử phiên; browser smoke cô lập xác nhận WebSocket; coverage nhóm module rủi ro cao đạt 78% (ngưỡng 75%) | Đạt |
| Tài liệu vận hành | README, backup/restore, xử lý sự cố, DPAPI portability và checklist phát hành | Đạt |
| Không tác động dữ liệu thật | Unit/integration dùng `TemporaryDirectory`; UI dùng `TINIX_DB_PATH` tạm; không chạy download/scrape/post hoặc migration trên dữ liệu thật; fake poster cho queue | Đạt |

## Quality gate bắt buộc

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
./scripts/quality.ps1
```

Kết quả cuối phải đồng thời đạt: dependency nhất quán, Ruff, mypy, pytest,
coverage ≥75% và JavaScript syntax. Endpoint `/api/system/health` phải báo
`ready=true` trên máy phát hành.

## Ranh giới xác minh

Không chạy kiểm thử đăng bài Facebook thật vì điều đó mâu thuẫn với yêu cầu
không tác động tài khoản/dữ liệu thật. Checklist tích hợp có kiểm soát dành cho
người phát hành khi họ có tài khoản/Page sandbox được cấp quyền; đây là bước
acceptance của môi trường, không phải điều kiện để quality gate mã nguồn đạt.
