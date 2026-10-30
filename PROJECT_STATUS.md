# PROJECT_STATUS.md

> Snapshot trạng thái hiện tại để phiên/agent sau tiếp tục nhanh. Không phải nhật ký.

## 0. Status Metadata

**Project:** Tinix FB Studio (Tinix-Facebook-Hunter)
**Overall Status:** Ổn định cho sử dụng nội bộ; các mục còn mở cần quyết định của Product Owner
**Current Phase:** Hardening sau Final Production Review đã commit và push; chờ nghiệm thu luồng đăng nhập mật khẩu và cài đặt trên máy sạch
**Last Updated:** 2026-10-30

## 1. Current Objective

Giữ ứng dụng ổn định trên `master` đồng bộ với GitHub; hoàn tất các mục còn mở ở mục 9.

## 2. Current State Summary

- Nhánh `master` đã đẩy lên `origin` (`https://github.com/thanhtan229/tinix-facebook-hunter`). Remote và HEAD đồng bộ tại `42acf470`.
- Version hiện tại: **v1.21.64**. SQLite schema **14**.
- Health `/api/system/health`: `ready=true`, schema 14, mọi check đều true (kiểm tra sau khi khởi động lại bằng launcher).
- Quality gate `scripts/quality.ps1`: **260 passed**, 10 subtests, exit 0 (trên các commit cuối).
- Gói artifact `v1.21.47` (SHA256 `3d775951…58`) tương ứng commit `b1873f2a`. Không tạo lại gói trừ khi có yêu cầu.

## 3. Completed

- [x] Final Production Review và các finding đã duyệt (`FINAL_REVIEW.md` cho đợt trước; đợt 2026-10-29 ghi trong lịch sử commit).
- [x] Hardening dữ liệu: import rollback chỉ xóa thư mục do chính lần import tạo ra (`d6cd147b`).
- [x] Secret không giải mã được được báo rõ, không còn bị coi là rỗng; preflight báo `SECRET_UNREADABLE` khi cookie hỏng (`d6cd147b`).
- [x] Retry hàng đợi tải có backoff tối đa 5 phút (`d6cd147b`).
- [x] Restore DB bị chặn khi app đang giữ database (`d6cd147b`).
- [x] Xóa tài khoản: giữ Chrome profile mặc định; tùy chọn xóa có kiểm tra vùng quản lý, dùng chung và lease (`9421edae`).
- [x] Bundle export không chứa mật khẩu, 2FA, email pass, cookie mặc định; phiên Chrome vẫn có trong file và được ghi rõ (`6b4478a9`).
- [x] Khôi phục dấu tiếng Việt cho chuỗi đăng nhập và scanner; bỏ ghi mã 2FA ra log (`6b4478a9`).
- [x] Đọc DB lỗi không còn trả danh sách rỗng; batch tải quay về hàng đợi; giao diện nhận 503 rõ ràng (`c722ca31`).
- [x] Launcher `STOP.vbs` / `START.vbs`: không chờ hộp thoại khi chạy có tham số `silent` (`4aacd29a`).
- [x] Tài liệu: `DEVELOPMENT_WORKFLOW.md`, `ARCHITECTURE.md`, `PLAN.md`, `RESEARCH*.md` thay template bằng nội dung thật (`121305f9`, `d6cd147b`).
- [x] Thử đăng nhập có kiểm soát trên Facebook thật, mỗi tài khoản đúng một lần: tài khoản 3, 9, 20 đăng nhập được (phiên còn sống hoặc trang "Tiếp tục"); tài khoản 6 bị từ chối mật khẩu.

## 4. In Progress

Không có tác vụ đang chạy.

## 5. Blockers / Known Issues

### Chưa xác minh

- **Luồng nhập mật khẩu** (`_do_login`) chưa được xác minh thành công trên Facebook. Tài khoản 6 bị từ chối mật khẩu đã lưu; các tài khoản khác không đi qua bước nhập mật khẩu. Nguyên nhân chưa rõ, khả năng cao mật khẩu đã lưu không còn đúng.
- **Cài đặt `install.bat` trên máy Windows sạch** chưa thử. Đã thử trên bản sao cô lập của cùng máy (kể cả nhánh `py -3.10`).

### Known limitations (đã chấp nhận)

- Chưa nghiệm thu tải/quét lâu với khối lượng lớn trên tài khoản Facebook thật.
- Chưa nghiệm thu chuyển profile sang máy khác.
- Bundle mặc định vẫn chứa phiên Chrome (cookie đăng nhập); file phải được bảo quản như dữ liệu đăng nhập và không mã hóa.
- DPAPI gắn với Windows user/máy; app chỉ lắng nghe localhost; không có auto-update.
- App không tự khởi động sau reboot; cần chạy `START.vbs`.
- Còn 3 DeprecationWarning escape sequence trong parser (cũ, không làm fail gate); HTML title chưa có version.
- Quality gate chỉ đo 5 module (~82%); đo toàn bộ `core`, `web`, `utils` là khoảng 54%.
- Log ứng dụng vẫn ghi email đăng nhập ở dạng rõ (hành vi có sẵn).

## 6. Important Recent Decisions

- Người chịu trách nhiệm rollback: Tinix.
- Push lên GitHub chỉ khi có chỉ định rõ; push thường, không force.
- Bundle không chứa credential mặc định; người dùng phải chủ động bật tùy chọn.
- Hook pre-commit tự bump version khi commit; sau mỗi commit cần kiểm tra version thực tế trước khi ghi vào tài liệu.

## 7. Verification State

```text
Quality gate: 260 passed, 10 subtests passed, exit 0 (scripts/quality.ps1, 2026-10-30)
Typecheck/Lint: mypy pass (6 source files); ruff pass; pip check pass
Build: Build.bat / pre-commit hook bump version; syntax verification pass
Runtime: v1.21.64 chạy qua START.vbs silent; health ready=true, schema 14
Launcher: STOP/START silent đạt; STOP/START 4/4 lần trước đó (2026-10-28)
Login: 3 tài khoản đăng nhập được (phiên sống / Tiếp tục); 1 tài khoản bị từ chối mật khẩu
Installer: đã thử trên bản sao cô lập cùng máy; chưa thử máy sạch
Reboot: đã kiểm tra 2026-10-28 (DB ok, không tác vụ kẹt)
Known pre-existing failures: không có trong quality gate
```

## 8. Runtime / Environment State

```text
Backend: main.py chạy qua START.vbs, cổng 7866 (localhost)
Database: tinix_scraper.db, schema 14, quick_check ok
Mode: standalone App Mode
Lưu ý: sau reboot cần chạy START.vbs thủ công
Chrome: cửa sổ App Mode có thể còn mở sau khi dừng app; chỉ đóng cửa sổ do dự án mở
```

## 9. Next Actions

1. Kiểm tra thủ công mật khẩu của tài khoản 6 trong trình duyệt thường. Nếu đúng, điều tra luồng nhập mật khẩu; nếu sai, cập nhật mật khẩu trong app và thử lại đúng một lần.
2. Thử `install.bat` trên máy Windows sạch (Python 3.11, có internet) khi có máy thử.
3. Chỉ nghiệm thu chuyển profile sang máy khác và tải/quét khối lượng lớn khi có yêu cầu và phạm vi cụ thể.
4. Nếu lỗi launcher tái diễn: ghi thời điểm, giữ `logs/server_startup.log` và log của lần đó trước khi chẩn đoán.

Đã xử lý (2026-10-28): hai file sidecar backup đã chuyển vào `exports/releases/backup-sidecars/` (ngoài Git, giữ nguyên). File backup chính vẫn ở thư mục gốc.

## 10. Resume Context

```text
Bắt đầu từ:
- PROJECT_STATUS.md, sau đó FINAL_REVIEW.md và docs/RELEASE_CHECKLIST.md.

Đọc trước khi sửa code:
- ARCHITECTURE.md, DEVELOPMENT_WORKFLOW.md (lệnh chạy/test/build thật).

Mốc hiện tại:
- origin/master khớp HEAD 42acf470 (v1.21.64).

Không làm lại:
- F1–F6 và các hardening đã commit có test; không chạy tải/quét Facebook thật nếu không được yêu cầu.
- Không thử đăng nhập mật khẩu lặp lại khi chưa có quyết định, vì có thể khóa tài khoản.
- Không tạo lại gói artifact nếu chưa có yêu cầu.

Việc tiếp theo:
- Mục 9.1 (mật khẩu tài khoản 6).

Lưu ý:
- Mỗi commit kích hoạt hook bump version; kiểm tra version thực tế trước khi ghi version cụ thể.
```

## 11. Relevant Documents

```text
AGENTS.md
DEVELOPMENT_WORKFLOW.md
ARCHITECTURE.md
PLAN.md
FINAL_REVIEW.md
docs/RELEASE_CHECKLIST.md
docs/OPERATIONS.md
docs/TINIX_PROFILE_BUNDLE.md
exports/releases/RELEASE_APPROVAL_v1.21.47.md
install.bat
README.md
```
