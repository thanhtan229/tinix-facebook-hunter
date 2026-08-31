import pandas as pd
import os
from typing import List, Dict

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif'}
VIDEO_EXTS = {'.mp4', '.mov', '.webm', '.avi'}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


def load_post_excel(excel_path: str) -> List[Dict[str, str]]:
    """Read the Excel template (or user-provided file) and return a list of dicts.
    Expected columns: "Số thứ tự", "Folder Name", "Tiêu Đề", "Nội Dung", "Từ Khóa".
    The function validates the presence of these columns and returns the rows as
    dictionaries preserving the original column names.
    """
    if not excel_path or not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")
    df = pd.read_excel(excel_path, engine="openpyxl")
    required = ["Số thứ tự", "Folder Name", "Tiêu Đề", "Nội Dung", "Từ Khóa"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns in Excel: {', '.join(missing)}")
    # Ensure proper types (convert everything to string)
    df = df.astype(str)
    records = df[required].to_dict(orient="records")
    return records


def scan_main_folder(root_path: str) -> List[Dict[str, str]]:
    """Scan a root directory for subfolders representing posts.
    Returns a list of dicts with folder_name, folder_path, and caption (if a txt file exists)."""
    if not root_path or not os.path.isdir(root_path):
        raise FileNotFoundError(f"Thư mục không tồn tại: {root_path}")
    items: List[Dict[str, str]] = []
    for entry in os.scandir(root_path):
        if not entry.is_dir():
            continue
        folder_name = entry.name
        folder_path = entry.path
        caption = ""
        # Look for a caption file (txt or md) inside the folder
        for f in os.listdir(folder_path):
            if f.lower().endswith(('.txt', '.md')):
                try:
                    with open(os.path.join(folder_path, f), 'r', encoding='utf-8') as fp:
                        caption = fp.read().strip()
                except Exception:
                    caption = ""
                break
        items.append({
            "folder_name": folder_name,
            "folder_path": folder_path,
            "caption": caption,
        })
    return items


def count_media_in_folder(folder_path: str) -> tuple[int, int]:
    """Count image and video files inside a folder.
    Returns a tuple (image_count, video_count).
    Recognized image extensions: .jpg, .jpeg, .png, .gif
    Recognized video extensions: .mp4, .mov, .webm, .avi"""
    if not folder_path or not os.path.isdir(folder_path):
        return 0, 0
    img_count = 0
    vid_count = 0
    for f in os.listdir(folder_path):
        ext = os.path.splitext(f)[1].lower()
        if ext in IMAGE_EXTS:
            img_count += 1
        elif ext in VIDEO_EXTS:
            vid_count += 1
    return img_count, vid_count


def folder_has_video(folder_path: str) -> bool:
    """Return True when a folder contains at least one supported video file."""
    if not folder_path or not os.path.isdir(folder_path):
        return False
    for f in os.listdir(folder_path):
        if os.path.splitext(f)[1].lower() in VIDEO_EXTS:
            return True
    return False


# Exported symbols
__all__ = ["load_post_excel", "scan_main_folder", "count_media_in_folder", "folder_has_video"]
