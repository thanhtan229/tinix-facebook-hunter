---
name: Scan Fanpage Account
description: Skill để quét danh sách fanpage của một Facebook account đang đăng nhập sẵn trong Chrome profile, đi thẳng vào trang Your Pages và trả về tên page, page ID, URL.
---

# Scan Fanpage Account

Skill này dùng cho bài toán quét fanpage của account Facebook từ profile Chrome đã có sẵn session.

## Runtime files

Code runtime hiện tại nằm ở:
- `core/fanpage_scanner.py`
- `gui/account_manager.py`

Không dùng `core/auto_poster.py` cho flow này.

## Workflow

1. Lấy `profile_dir` của `social_account`.
2. Tính `cdp_port` riêng theo account.
3. Kết nối vào Chrome profile sẵn có, chỉ mở Chrome nếu debug port chưa sống.
4. Đi thẳng vào `https://www.facebook.com/pages/?category=your_pages`.
5. Quét card fanpage trong DOM và trả về:
   - `page_name`
   - `page_id`
   - `page_url`
   - `avatar_url`
6. Báo thành công/thất bại và mở dialog kết quả trong `Account Manager`.

## Guardrails

- Chỉ hỗ trợ 1 account Facebook mỗi lần scan.
- Nếu Facebook redirect sang `login` hoặc `checkpoint` thì coi là thất bại.
- Không ghi DB trong v1 scan test.
- Ưu tiên dùng tab Facebook hiện có; chỉ tạo page mới khi context không có tab nào phù hợp.

## Quick Routine

1. Tạo branch riêng cho từng lần thử:
```powershell
git switch -c exp/scan-page
```
2. Tạo checkpoint đầu tiên:
```powershell
git add core/fanpage_scanner.py gui/account_manager.py .agent/skills/scan_fanpage_account
git commit -m "Checkpoint scan page skill"
```
3. Mỗi lần chỉ sửa 1 ý tưởng nhỏ.
4. Kiểm tra cú pháp trước khi mở app.
5. Test 1 account đã login sẵn.
6. Nếu fail, restore file ngay.
7. Nếu ổn, tạo checkpoint mới.
8. Nếu cần quay lại toàn bộ, switch về branch cũ.
9. Không sửa đồng thời scanner, UI và skill doc.
10. Ghi nhanh kết quả vào commit message.
