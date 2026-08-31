# Skill Tools Cheat Sheet

## Mở nhanh

1. Chạy `_Skill tools\skill-tools.bat`
2. Chọn preset đúng skill đang làm
3. Chọn `3` để tạo checkpoint trước khi sửa
4. Chọn `6` để chạy app và test
5. Lỗi thì chọn `4` để restore ngay
6. Ổn thì chọn `3` để chốt checkpoint mới

## Tạo skill mới

1. Chọn `8` trong `_Skill tools\skill-tools.bat`
2. Nhập `key`, `name`, `description`
3. Chọn profile:
   - `Scan`
   - `Post`
   - `Auth`
   - `Backup`
   - `General`
   - `Auto` nếu chưa rõ
4. Tool tự sinh:
   - `SKILL.md`
   - `README.md`
   - `agents/openai.yaml`
   - `core/<key>.py`
   - `gui/<key>.py`

## Backup và restore

- `3` = commit checkpoint
- `4` = restore scope hiện tại
- `7` = đổi preset / scope

## Quy tắc làm việc

- Mỗi lần chỉ sửa 1 ý tưởng
- Test 1 case nhỏ
- Nếu ổn mới checkpoint
- Nếu lỗi thì restore ngay
- Không cần nhớ lệnh PowerShell, chỉ cần nhớ số menu

## Preset hữu ích

- `scan` = quét fanpage / account / target
- `post` = đăng bài / lên lịch
- `auth` = session / token / login
- `backup` = checkpoint / restore / rollback
- `general` = skill chưa phân nhóm rõ
