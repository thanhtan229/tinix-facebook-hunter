---
name: Facebook_login
description: 
---

# Facebook_login

## Muc tieu

- Quan ly session, token, cookie, va profile dang nhap.

## Runtime files

- `core/Facebook_login.py`
- `gui/Facebook_login.py`

## Workflow

- Mở chrome profile sẵn có
- Đăng nhập vào facebook
- Lấy avatar, name, id, url
- Lưu vào database  
- Thể hiện kết quả trên giao diện

## Guardrails

- Khong luu thong tin nhay cam khong can thiet.
- Neu token loi, ghi ro subcode / message neu co.