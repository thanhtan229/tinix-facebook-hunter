# Create Skill Guide

## Khi nào dùng

- Khi bạn muốn tạo skill mới từ đầu.
- Khi muốn tạo lại khung chuẩn cho một skill đang thử nghiệm.

## Cách làm nhanh

1. Mở `_Skill tools\skill-tools.bat`
2. Chọn `8. Create skill`
3. Nhập:
   - `key`
   - `name`
   - `description`
4. Chọn profile:
   - `Auto`
   - `Scan`
   - `Post`
   - `Auth`
   - `Backup`
   - `General`
5. Tool sẽ sinh:
   - `SKILL.md`
   - `README.md`
   - `agents/openai.yaml`
   - `core/<key>.py`
   - `gui/<key>.py`

## Gợi ý chọn profile

- `Scan`: skill quét / dò / thu thập dữ liệu
- `Post`: skill đăng bài / lên lịch / publish
- `Auth`: skill token / session / login / cookie
- `Backup`: skill checkpoint / restore / rollback
- `General`: skill chưa xếp được nhóm rõ
- `Auto`: để tool tự đoán từ tên và mô tả

## Sau khi tạo

1. Mở `SKILL.md` trước nếu muốn đổi workflow.
2. Sửa `core/<key>.py` và `gui/<key>.py` theo nhu cầu.
3. Test 1 case nhỏ.
4. Nếu ổn thì checkpoint commit.
5. Nếu lệch thì restore ngay.

## Cach noi chuyen chuan voi moi agent

Khi muon tao skill moi, dung cu phap nay:

`Tao skill <ten>, dung preset <ten>, profile <scan|post|auth|backup|general>`

Quy uoc:

- `ten` cua skill va preset nen giong nhau.
- `preset` dung de gioi han scope file can checkpoint/restore.
- `profile` chi dung de chon khung SKILL.md ban dau.
- Neu khong can profile dac biet, dung `general`.
