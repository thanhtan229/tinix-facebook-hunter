# Skill Workflow

Đây là checklist ngắn để thử nghiệm mỗi skill trên Windows.

Nếu bạn chỉ muốn bản cực ngắn, mở thêm [skill-cheatsheet.md](skill-cheatsheet.md).

## Cách dùng

1. Mở `_Skill tools\skill-tools.bat`.
2. Chọn `1` để xem trạng thái.
3. Chọn `7` để chọn preset skill đang thử.
4. Chọn `3` để tạo checkpoint trước khi sửa.
5. Chọn `6` để chạy app và test.
6. Nếu lỗi, chọn `4` để restore ngay.
7. Nếu ổn, chọn `3` để tạo checkpoint mới.
8. Chọn `8` nếu muốn tạo skill template mới từ các input cơ bản.

## Quy tắc test nhanh

- Mỗi lần chỉ sửa 1 ý tưởng.
- Chỉ test 1 account hoặc 1 case.
- Không commit lan man các file không liên quan.
- Nếu cần quay lại, ưu tiên restore file trước, switch branch sau.
- Mỗi skill mới nên có `SKILL.md` sinh từ template trước, rồi chỉnh dần.
- Template mới có thể sinh thêm `agents/openai.yaml`, icon path và brand color nếu cần.

## Preset hiện tại

Preset mặc định đang trỏ vào skill `Scan Fanpage`:
- `core\fanpage_scanner.py`
- `gui\account_manager.py`
- `.agent\skills\scan_fanpage_account`

Khi sang skill khác, chọn `7` trong `_Skill tools\skill-tools.bat`.
Nếu cần preset mới, bạn có 2 cách:
- Chọn `A` trong menu preset để tạo mới tự động.
- Hoặc tạo thủ công một folder trong `_Skill tools\presets\` với `label.txt` và `scope.txt`.

Ngoài ra bạn còn có thể:
- `R` để đổi tên preset
- `D` để xóa preset
- `U` để nhân bản preset
- `E` để export preset ra file `.json`
- `I` để import preset từ file `.json`
