# PROJECT_STATUS.md

> Snapshot trạng thái hiện tại để phiên/agent sau tiếp tục nhanh. Không phải nhật ký.

## 0. Status Metadata

**Project:** Tinix FB Studio (Tinix-Facebook-Hunter)
**Overall Status:** Active (chờ quyết định release)
**Current Phase:** Release hardening hoàn tất kỹ thuật; còn checklist tổ chức
**Last Updated:** 2026-10-27

## 1. Current Objective

Đưa v1.21.44 vào trạng thái release nội bộ: đã commit checkpoint, chờ chỉ định người chịu trách nhiệm rollback.

## 2. Current State Summary

- Code version v1.21.44, SQLite schema v14.
- Toàn bộ fix F1–F6 và checklist kỹ thuật v1.21.44 đã nằm trong checkpoint commit (xem mục 3).
- Quality gate `scripts/quality.ps1` chạy lại trên candidate này: exit 0, 235 passed + 10 subtests, coverage 81%.
- Tải thật một bài và quét Page có tự tải đã PASS (chi tiết trong `FINAL_REVIEW.md`).

## 3. Completed

- [x] Audit production và fix F1–F6 (`FINAL_REVIEW.md`).
- [x] Quality gate: 235 passed + 10 subtests, coverage 81%.
- [x] Build.bat v1.21.44 (build trước đó đã đạt).
- [x] Backup DB hiện tại verify: schema14, integrity ok (`exports/releases/`, ngoài Git).
- [x] Source snapshot `exports/releases/Tinix-Facebook-Hunter-v1.21.44-source.zip` + SHA256SUMS (ngoài Git).

## 4. In Progress

Không có tác vụ đang chạy.

## 5. Blockers / Known Issues

### Đã đóng: Owner rollback

Người chịu trách nhiệm rollback: **Tinix** (Product Owner chỉ định 2026-10-27). Mục checklist đã `[x]`.
Còn lại trước khi tuyên bố release: không có blocker kỹ thuật đã biết; reboot và workload lớn chưa nghiệm thu (mục dưới).

### Known limitations (không phải finding mới)

- Chưa nghiệm thu: reboot, workload lớn/benchmark, chuyển profile sang máy khác.
- 3 DeprecationWarning escape sequence trong parser (đã tồn tại trước đó, không làm fail gate).
- HTML title chưa có version (badge đúng version).
- File media tải dở từ bản cũ có tên cuối không tự sửa/xóa.
- DPAPI gắn Windows user/máy; profile ZIP và backup có thể chứa secret; ứng dụng chỉ localhost; không có auto-update.

## 6. Important Recent Decisions

- Người chịu trách nhiệm rollback: Tinix.
- Chấp nhận release với giới hạn đã biết (2026-10-28): chưa thử khối lượng lớn trên tài khoản Facebook thật (nhiều Page, nhiều bài, chạy lâu). Đã thử 1 bài và 1 Page trên 1 tài khoản; reboot máy đã kiểm tra, app cần khởi động thủ công sau reboot.

## 7. Verification State

```text
Targeted tests: pass (test_production_recovery, test_chrome_handoff, test_p0_hardening trong quality gate)
Full tests: 235 passed, 10 subtests passed (scripts/quality.ps1, 2026-10-27)
Typecheck: mypy pass (6 source files)
Lint: ruff pass; pip check pass
Build: Build.bat v1.21.44 đã chạy trước đó (2026-10-03)
Runtime: app khởi động lại bằng START.vbs (2026-10-27), pythonw đang chạy
Health check: /api/system/health ready=true, version 1.21.45, schema 14, mọi check true
Known pre-existing failures: không có
```

## 8. Runtime / Environment State

```text
Current development mode: không đổi trong lượt này
Database: scraper.db / tinix_scraper.db hiện tại không bị chỉnh sửa
```

## 9. Next Actions

1. Quyết định có nghiệm thu reboot/workload lớn trước release (cần phạm vi cụ thể) hoặc ghi là giới hạn đã biết.
3. Xử lý sidecar `tinix_scraper.db.backup-20261003_085213_115026.sqlite-shm/-wal` (chưa commit, chưa xóa).

## 10. Resume Context

```text
Start here:
- PROJECT_STATUS.md, sau đó FINAL_REVIEW.md (mục v1.21.42–v1.21.44).

Read first:
- docs/RELEASE_CHECKLIST.md, docs/OPERATIONS.md

Current implementation checkpoint:
- Commit checkpoint v1.21.44 (xem git log -1).

Do not redo:
- F1–F6 đã fix và có test; không chạy lại tải/quét Facebook thật nếu không được yêu cầu.

Next expected action:
- Chỉ định owner rollback.

Important caveat:
- Không tuyên bố release hoàn tất khi owner rollback chưa được xác nhận.
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
```
