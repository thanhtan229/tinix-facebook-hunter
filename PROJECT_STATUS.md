# PROJECT_STATUS.md

> Snapshot trạng thái hiện tại để phiên/agent sau tiếp tục nhanh. Không phải nhật ký.

## 0. Status Metadata

**Project:** Tinix FB Studio (Tinix-Facebook-Hunter)
**Overall Status:** Stable — đã duyệt bàn giao nội bộ v1.21.47; đã có remote GitHub
**Current Phase:** Vận hành nội bộ; chờ quyết định về các mục còn mở
**Last Updated:** 2026-10-28

## 1. Current Objective

Giữ ứng dụng ổn định trên nhánh `master` và đồng bộ với GitHub; xử lý các mục còn mở ở mục 9.

## 2. Current State Summary

- Nhánh `master` đã được đẩy lên `origin` (`https://github.com/thanhtan229/tinix-facebook-hunter`). Remote và HEAD đồng bộ.
- Version code hiện tại: **v1.21.49** (commit `f29a6299`). Hook pre-commit tự bump version mỗi lần commit, nên commit trạng thái này sẽ là **v1.21.50**.
- SQLite schema **14**.
- Gói artifact `v1.21.47` (SHA256 `3d775951…58`) tương ứng commit `b1873f2a`. Không tạo lại gói trừ khi có yêu cầu.
- Health `/api/system/health`: `ready=true`, schema 14, mọi check đều true.

## 3. Completed

- [x] Audit production và fix F1–F6 (`FINAL_REVIEW.md`), commit `924994ed`.
- [x] Quality gate: 235 passed + 10 subtests, coverage 81% (trên candidate v1.21.44).
- [x] Backup DB verify: schema14, integrity ok (`exports/releases/`, ngoài Git).
- [x] Owner rollback: **Tinix** (2026-10-27), commit `7598ae41`.
- [x] Kiểm tra reboot máy (2026-10-28): DB `quick_check` ok, không tác vụ bị kẹt.
- [x] Chấp nhận giới hạn khối lượng lớn trên tài khoản Facebook thật (2026-10-28), commit `b1873f2a`.
- [x] Gói source v1.21.47 và biên bản duyệt bàn giao (`exports/releases/RELEASE_APPROVAL_v1.21.47.md`).
- [x] Thêm remote GitHub và push `master` (2026-10-28), commit `f33aaa46`.
- [x] Commit 6 docs chuẩn (ARCHITECTURE, UX_UI, PLAN, RESEARCH, RESEARCH_COMPARISON, DEVELOPMENT_WORKFLOW), commit `f29a6299`, đã push.
- [x] Kiểm tra launcher STOP → START: 4/4 lần đạt (1 lần đầu + 3 lần lặp). Cổng đóng sau 1 giây, server `ready` sau 2–4 giây. Không tái hiện được lỗi đã gặp trước đó.

## 4. In Progress

Không có tác vụ đang chạy.

## 5. Blockers / Known Issues

Không có blocker kỹ thuật đã biết.

### Đã ghi nhận nhưng chưa xác định nguyên nhân

- Trước đó có vài lần `START.vbs` không bật server (2026-10-28). Sau đó không tái hiện được trong 4 lần thử liên tiếp. Nghi ngờ lỗi phụ thuộc thời điểm, khi có tác vụ nền khác đang chạy. Chưa có bằng chứng xác nhận; chưa sửa launcher. Nếu tái diễn, cần log của đúng lần đó.

### Known limitations (đã chấp nhận, không phải finding mới)

- Chưa nghiệm thu khối lượng lớn trên tài khoản Facebook thật (nhiều Page, nhiều bài, chạy lâu).
- Chưa nghiệm thu chuyển profile sang máy khác.
- App không tự khởi động sau reboot; cần chạy `START.vbs`.
- 3 DeprecationWarning escape sequence trong parser (đã tồn tại trước đó, không làm fail gate).
- HTML title chưa có version (badge đúng version).
- File media tải dở từ bản cũ có tên cuối không tự sửa/xóa.
- DPAPI gắn Windows user/máy; profile ZIP và backup có thể chứa secret; ứng dụng chỉ localhost; không có auto-update.

## 6. Important Recent Decisions

- Người chịu trách nhiệm rollback: Tinix.
- Chấp nhận release nội bộ với giới hạn khối lượng lớn đã nêu ở mục 5 (2026-10-28).
- Push lên GitHub được thực hiện theo yêu cầu rõ ràng của Product Owner; push thường, không force.
- Hook pre-commit tự bump version khi commit. Không tạo lại gói artifact sau commit docs để tránh lệch version.

## 7. Verification State

```text
Targeted tests: pass (test_production_recovery, test_chrome_handoff, test_p0_hardening trong quality gate)
Full tests: 235 passed, 10 subtests passed (scripts/quality.ps1, 2026-10-27, candidate v1.21.44)
Typecheck: mypy pass (6 source files)
Lint: ruff pass; pip check pass
Build: Build.bat chạy qua pre-commit hook khi commit (hiện v1.21.49)
Runtime: v1.21.49 chạy qua START.vbs, health ready=true (2026-10-28)
Launcher: STOP → START đạt 4/4 lần (2026-10-28)
Reboot: đã kiểm tra 2026-10-28 (DB ok, không tác vụ kẹt)
Known pre-existing failures: không có
```

## 8. Runtime / Environment State

```text
Frontend/Backend: main.py chạy qua START.vbs, cổng 7866 (localhost)
Database: tinix_scraper.db, schema 14, quick_check ok
Current development mode: standalone App Mode
Lưu ý: sau reboot cần chạy START.vbs thủ công
Chrome: cửa sổ App Mode của dự án có thể còn mở sau khi dừng app; các cửa sổ của dự án khác không liên quan
```

## 9. Next Actions

1. Chuyển profile sang máy khác: chưa nghiệm thu, chỉ làm khi có yêu cầu.
2. Nếu lỗi launcher tái diễn: ghi lại thời điểm, đọc `logs/server_startup.log` và log của đúng lần đó.

Đã xử lý (2026-10-28): hai file sidecar `tinix_scraper.db.backup-20261003_085213_115026.sqlite-shm/-wal` được chuyển vào `exports/releases/backup-sidecars/` (ngoài Git, không xóa). File backup chính vẫn ở gốc dự án.

## 10. Resume Context

```text
Start here:
- PROJECT_STATUS.md, sau đó exports/releases/RELEASE_APPROVAL_v1.21.47.md.

Read first:
- docs/RELEASE_CHECKLIST.md, docs/OPERATIONS.md, FINAL_REVIEW.md.

Current implementation checkpoint:
- origin/master đồng bộ với HEAD. Xem git log.

Do not redo:
- F1–F6 đã fix và có test; không chạy lại tải/quét Facebook thật nếu không được yêu cầu.
- Không tạo lại gói artifact trừ khi có commit code mới và được yêu cầu.
- Không sửa launcher khi chưa tái hiện được lỗi.

Next expected action:
- Chuyển profile sang máy khác khi có yêu cầu; theo dõi launcher nếu lỗi tái diễn (mục 9).

Important caveat:
- Mỗi commit kích hoạt hook bump version. Kiểm tra version thực tế trước khi ghi version cụ thể vào tài liệu.
```

## 11. Relevant Documents

```text
AGENTS.md
DEVELOPMENT_WORKFLOW.md
UX_UI.md
ARCHITECTURE.md
PLAN.md
FINAL_REVIEW.md
docs/RELEASE_CHECKLIST.md
docs/OPERATIONS.md
exports/releases/RELEASE_APPROVAL_v1.21.47.md
```
