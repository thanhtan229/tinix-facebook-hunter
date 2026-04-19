---
name: Facebook_login
description: Mo Chrome profile Facebook, dang nhap bang username/password/2FA secret va lay avatar account.
---

# Facebook_login

## Muc tieu

- Mo dung Chrome profile co san.
- Dang nhap Facebook bang username, password, va 2FA secret.
- Lay anh avatar cua account sau khi login thanh cong.

## Runtime files

- `core/Facebook_login.py`
- `gui/Facebook_login.py`

## Workflow

1. Xac dinh profile Chrome can dung.
2. Mo dung profile va kiem tra trang thai login hien tai.
3. Neu can login, dung username/password de vao Facebook.
4. Neu co 2FA, sinh ma OTP tu 2FA secret va nhap tiep.
5. Xac nhan vao duoc trang tai khoan.
6. Lay avatar hien tai cua account va luu ve output.
7. Neu that bai, ghi ro buoc that bai va ly do.
8. Test tren 1 account truoc khi mo rong.

## Guardrails

- Khong luu thong tin nhay cam khong can thiet.
- Neu token loi, ghi ro subcode / message neu co.
- Khong in ra password hoac 2FA secret trong log.
- Uu tien dung profile co san, khong tao profile moi neu khong can.
