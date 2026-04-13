import pandas as pd
import os

output_dir = os.path.dirname(__file__)
filepath = os.path.join(output_dir, 'post_template.xlsx')

data = {
    "Số thứ tự": [1],
    "Folder Name": ["example_folder"],
    "Tiêu Đề": ["Tiêu đề mẫu"],
    "Nội Dung": ["Nội dung mẫu"],
    "Từ Khóa": ["từ khóa1; từ khóa2"],
}
df = pd.DataFrame(data)
df.to_excel(filepath, index=False)
print(f"Excel template created at {filepath}")
