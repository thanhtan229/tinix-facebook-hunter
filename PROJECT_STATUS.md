# PROJECT_STATUS.md

> Snapshot trạng thái hiện tại để phiên/agent sau tiếp tục nhanh. Không phải nhật ký.

## 0. Status Metadata

**Project:** Tinix FB Studio (Tinix-Facebook-Hunter)
**Overall Status:** Stable — đã duyệt bàn giao nội bộ
**Current Phase:** Release nội bộ v1.21.47 đã duyệt; chưa có remote/publish
**Last Updated:** 2026-10-28

## 1. Current Objective

Giữ bản v1.21.47 ổn định và sẵn sàng sử dụng; quyết định nơi lưu trữ/phát hành từ xa (GitHub) khi Product Owner xác nhận.

## 2. Current State Summary

- Version sau commit này: **v1.21.48** (hook bump từ 1.21.47). Gói artifact v1.21.47 tương ứng commit `b1873f2a`. SQLite schema **14**.
- Các fix F1–F6 và checklist kỹ thuật v1.21.44 nằm trong commit `924994ed`. Commit `7598ae41` ghi người chịu trách nhiệm rollback. Commit `b1873f2a` ghi giới hạn đã chấp nhận.
- Quality gate (candidate v1.21.44, trước khi hook bump version): 235 passed, 10 subtests, coverage 81%, exit 0.
- Health `/api/system/health` sau khi khởi động lại: `ready=true`, version 1.21.47, schema 14, mọi check đều true.
- Repo **chưa có remote** (`git remote -v` rỗng). URL GitHub được cung cấp là `https://github.com/thanhtan229/tinix-facebook-hunter` nhưng chưa được cấu hình hay push.

## 3. Completed

- [x] Audit production và fix F1–F6 (`FINAL_REVIEW.md`).
- [x] Quality gate pass (235 passed + 10 subtests, coverage 81%).
- [x] Backup DB verify: schema14, integrity ok (`exports/releases/`, ngoài Git).
- [x] Owner rollback: **Tinix** (2026-10-27).
- [x] Kiểm tra reboot máy (2026-10-28): DB `quick_check` ok, không có tác vụ bị kẹt, app cần khởi động thủ công.
- [x] Chấp nhận giới hạn khối lượng lớn trên tài khoản Facebook thật (2026-10-28).
- [x] Gói source v1.21.47: `exports/releases/Tinix-Facebook-Hunter-v1.21.47-source.zip`, SHA256 `3d775951…58` (xem `SHA256SUMS-v1.21.47.txt`).
- [x] Ghi nhận duyệt bàn giao: `exports/releases/RELEASE_APPROVAL_v1.21.47.md`.

## 4. In Progress

Không có tác vụ đang chạy.

## 5. Blockers / Known Issues

Không có blocker kỹ thuật đã biết.

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
- Không push, upload hay tạo tag khi chưa có chỉ định rõ ràng.
- Hook pre-commit của repo tự bump version khi commit; gói artifact không được tạo lại sau commit docs để tránh lệch version.

## 7. Verification State

```text
Targeted tests: pass (test_production_recovery, test_chrome_handoff, test_p0_hardening trong quality gate)
Full tests: 235 passed, 10 subtests passed (scripts/quality.ps1, 2026-10-27, candidate v1.21.44)
Typecheck: mypy pass (6 source files)
Lint: ruff pass; pip check pass
Build: Build.bat chạy qua pre-commit hook khi commit (v1.21.45 → v1.21.47)
Runtime: v1.21.47 chạy qua START.vbs, health ready=true (2026-10-28)
Reboot: đã kiểm tra 2026-10-28 (DB ok, không tác vụ kẹt)
Known pre-existing failures: không có
```

## 8. Runtime / Environment State

```text
Frontend/Backend: Flask/pythonw chạy qua START.vbs, cổng 7866 (localhost)
Database: tinix_scraper.db, schema 14, quick_check ok; không chỉnh sửa trong các lượt kiểm tra
Current development mode: standalone App Mode
Lưu ý: sau reboot cần chạy START.vbs thủ công
```

## 9. Next Actions

1. Product Owner xác nhận có cấu hình remote GitHub (`https://github.com/thanhtan229/tinix-facebook-hunter`) và có push hay không. Hiện chưa push.
2. Quyết định xử lý file sidecar `tinix_scraper.db.backup-20261003_085213_115026.sqlite-shm/-wal` (chưa commit, chưa xóa).
3. Quyết định đưa các docs chuẩn chưa theo dõi (ARCHITECTURE, UX_UI, PLAN, RESEARCH, RESEARCH_COMPARISON, DEVELOPMENT_WORKFLOW) vào Git hay không.
4. Chuyển profile sang máy khác: chưa nghiệm thu, chỉ làm khi có yêu cầu.

## 10. Resume Context

```text
Start here:
- PROJECT_STATUS.md, sau đó exports/releases/RELEASE_APPROVAL_v1.21.47.md.

Read first:
- docs/RELEASE_CHECKLIST.md, docs/OPERATIONS.md, FINAL_REVIEW.md.

Current implementation checkpoint:
- Commit đã push lên origin/master (sau commit docs này). Xem git log.

Do not redo:
- F1–F6 đã fix và có test; không chạy lại tải/quét Facebook thật nếu không được yêu cầu.
- Không tạo lại gói artifact trừ khi có commit code mới và được yêu cầu.

Next expected action:
- Product Owner quyết định về remote GitHub.

Important caveat:
- Mỗi commit kích hoạt hook bump version; kiểm tra version trước khi ghi tài liệu về version cụ thể.
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
