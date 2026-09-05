import os
import mimetypes
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field, model_validator
from typing import Annotated, Optional, List, Literal
from core.db_storage import (
    bulk_delete_post_rows,
    get_db_path,
    get_scraped_pages_full,
    get_spy_post_by_row_id,
    query_posts_for_spy,
    MEDIA_DOWNLOAD_EXTS,
    set_post_rating,
)
from core.data_cleanup import cleanup_scraped_data, delete_downloaded_media, preview_scraped_cleanup
from utils import config
from web.ws_manager import log_to_web
from web.models import ApiRequest
from web.routes.downloader import download_is_running
from web.routes.scraper import scrape_is_running

router = APIRouter(prefix="/api/spy", tags=["Spy Studio"])

class QueryPostsRequest(ApiRequest):
    page_names: List[str] = Field(min_length=1, max_length=1_000)
    mode: Optional[str] = Field(default="newest", pattern="^(newest|oldest|top_engagement|top_reactions|top_comments|top_shares|top_views)$")
    limit: Optional[int] = Field(default=0, ge=0, le=100_000)
    post_type: Optional[str] = Field(default="Tất cả", max_length=100)
    download_status: Optional[str] = Field(default="Tất cả", max_length=100)
    query: Optional[str] = Field(default="", max_length=10_000)
    sort_by: Optional[str] = Field(
        default="", pattern="^(|date|page_name|post_type|engagement|comments|shares|view_count|total_engagement|downloaded)$"
    )
    sort_order: Optional[str] = Field(default="desc", pattern="^(asc|desc)$")

class ExportExcelRequest(ApiRequest):
    page_names: List[str] = Field(min_length=1, max_length=1_000)
    mode: Optional[str] = Field(default="newest", pattern="^(newest|oldest|top_engagement|top_reactions|top_comments|top_shares|top_views)$")
    limit: Optional[int] = Field(default=0, ge=0, le=100_000)
    post_type: Optional[str] = Field(default="Tất cả", max_length=100)
    download_status: Optional[str] = Field(default="Tất cả", max_length=100)
    sort_by: Optional[str] = Field(
        default="", pattern="^(|date|page_name|post_type|engagement|comments|shares|view_count|total_engagement|downloaded)$"
    )
    sort_order: Optional[str] = Field(default="desc", pattern="^(asc|desc)$")


class CleanupScopeRequest(ApiRequest):
    page_urls: List[Annotated[str, Field(min_length=1, max_length=4_096)]] = Field(
        default_factory=list, max_length=1_000
    )
    all_pages: bool = False

    @model_validator(mode="after")
    def validate_scope(self):
        if self.all_pages == bool(self.page_urls):
            raise ValueError("Chọn page_urls hoặc all_pages, không chọn đồng thời")
        return self


class CleanupRequest(CleanupScopeRequest):
    confirmation: Literal["XOA"]
    delete_media: bool = False


class DeletePostsRequest(ApiRequest):
    post_row_ids: List[Annotated[int, Field(gt=0)]] = Field(min_length=1, max_length=100_000)
    delete_media: bool = False


class PostRatingRequest(ApiRequest):
    rating: int = Field(ge=0, le=5)


def _downloaded_media_files(post: dict) -> List[Path]:
    """Resolve local media without allowing paths outside the configured output directory."""
    if not post.get("downloaded") or not post.get("download_path"):
        return []
    output_root = Path(config.get("output_dir", ".")).expanduser().resolve()
    download_path = Path(post["download_path"]).expanduser().resolve()
    try:
        download_path.relative_to(output_root)
    except ValueError:
        return []
    try:
        files = [download_path] if download_path.is_file() else [p for p in download_path.iterdir() if p.is_file()]
    except OSError:
        return []
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    media = [p for p in files if p.suffix.lower() in MEDIA_DOWNLOAD_EXTS]
    return sorted(media, key=lambda p: (p.suffix.lower() not in image_exts, p.name.lower()))


def _downloaded_caption(post: dict) -> str:
    """Prefer the caption saved with the download, falling back to the database text."""
    path = Path(post.get("download_path") or "").expanduser()
    caption_file = path / "caption.txt" if path.is_dir() else path.parent / "caption.txt"
    output_root = Path(config.get("output_dir", ".")).expanduser().resolve()
    try:
        caption_file.resolve().relative_to(output_root)
        if caption_file.is_file() and caption_file.stat().st_size <= 2_000_000:
            return caption_file.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError, ValueError):
        pass
    return post.get("caption", "")

@router.get("/pages")
def get_pages():
    """Get list of all scraped fanpages with metadata."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    pages = get_scraped_pages_full(db_p)
    return {"status": "success", "data": pages}

@router.post("/posts")
def query_posts(req: QueryPostsRequest):
    """Query and filter scraped posts."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    posts = query_posts_for_spy(
        db_path=db_p,
        page_names=req.page_names,
        mode=req.mode or "newest",
        limit=req.limit or 0,
        post_type_filter=req.post_type or "Tất cả",
        download_status=req.download_status or "Tất cả",
        sort_by=req.sort_by or "",
        sort_order=req.sort_order or "desc",
    )

    if req.query and req.query.strip():
        q = req.query.strip().lower()
        posts = [
            p for p in posts
            if q in p.get("caption", "").lower()
            or q in p.get("post_id", "").lower()
            or q in p.get("page_name", "").lower()
        ]

    return {
        "status": "success",
        "total": len(posts),
        "data": posts
    }


@router.get("/posts/{post_row_id}/detail")
def get_post_detail(post_row_id: int):
    """Return full text and the complete local media gallery for a downloaded post."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    post = get_spy_post_by_row_id(db_p, post_row_id)
    if not post:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài viết")
    if not post["downloaded"]:
        raise HTTPException(status_code=409, detail="Bài viết chưa được tải về")
    media_files = _downloaded_media_files(post)
    post["caption"] = _downloaded_caption(post)
    post.pop("download_path", None)
    post["media"] = [
        {
            "index": index,
            "name": media.name,
            "kind": "image" if media.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"} else "video",
            "url": f"/api/spy/posts/{post_row_id}/media/{index}",
        }
        for index, media in enumerate(media_files)
    ]
    return {"status": "success", "data": post}


@router.get("/posts/{post_row_id}/media/{media_index}")
def get_post_media(post_row_id: int, media_index: int):
    """Stream one media item selected from the validated downloaded-post folder."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    post = get_spy_post_by_row_id(db_p, post_row_id)
    if not post:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài viết")
    media_files = _downloaded_media_files(post)
    if media_index < 0 or media_index >= len(media_files):
        raise HTTPException(status_code=404, detail="Không tìm thấy media")
    media = media_files[media_index]
    mime, _ = mimetypes.guess_type(str(media))
    return FileResponse(str(media), media_type=mime or "application/octet-stream")


@router.post("/posts/{post_row_id}/rating")
def rate_post(post_row_id: int, req: PostRatingRequest):
    """Save the user's star rating for one repository post."""
    db_p = get_db_path(config.get("scraper_db_path", ""))
    if not set_post_rating(db_p, post_row_id, req.rating):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài viết")
    return {"status": "success", "data": {"id": post_row_id, "rating": req.rating}}

@router.post("/cleanup-preview")
def cleanup_preview(req: CleanupScopeRequest):
    db_p = get_db_path(config.get("scraper_db_path", ""))
    data = preview_scraped_cleanup(
        db_p, page_urls=req.page_urls, all_pages=req.all_pages
    )
    return {"status": "success", "data": data}


@router.post("/posts/delete")
def delete_posts(req: DeletePostsRequest):
    """Delete exact repository rows and optionally their safely-scoped local media."""
    if scrape_is_running() or download_is_running():
        raise HTTPException(
            status_code=409,
            detail="Hãy dừng tác vụ quét và tải xuống trước khi xóa bài",
        )
    db_p = get_db_path(config.get("scraper_db_path", ""))
    try:
        result = bulk_delete_post_rows(db_p, req.post_row_ids)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Xóa bài thất bại: {str(exc)[:160]}") from exc
    media_result = {"media_deleted": 0, "media_skipped": 0, "media_failed": 0}
    if req.delete_media:
        media_result = delete_downloaded_media(result["paths"], config.get("output_dir", "."))
    log_to_web(
        f"Đã xóa {result['deleted']} bài khỏi Kho Dữ Liệu; "
        f"xóa {media_result['media_deleted']} thư mục media.",
        "WARNING",
    )
    return {
        "status": "success",
        "data": {
            "deleted": result["deleted"],
            "media_preserved": 0 if req.delete_media else len(result["paths"]),
            **media_result,
        },
    }


@router.post("/cleanup")
def cleanup_repository(req: CleanupRequest):
    """Back up and remove only scraped pages/posts, optionally scoped media."""
    if scrape_is_running() or download_is_running():
        raise HTTPException(
            status_code=409,
            detail="Hãy dừng tác vụ quét và tải xuống trước khi dọn kho",
        )
    db_p = get_db_path(config.get("scraper_db_path", ""))
    try:
        result = cleanup_scraped_data(
            db_p,
            page_urls=req.page_urls,
            all_pages=req.all_pages,
            delete_media=req.delete_media,
            output_root=config.get("output_dir", "."),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Dọn kho thất bại: {str(exc)[:160]}") from exc
    log_to_web(
        f"Đã dọn {result['pages_deleted']} Page và {result['posts_deleted']} bài; "
        f"backup: {result['backup_path'] or 'không cần tạo'}.",
        "WARNING",
    )
    return {"status": "success", "data": result}

@router.post("/export-excel")
def export_excel_endpoint(req: ExportExcelRequest):
    """Export filtered posts to an Excel spreadsheet."""
    import pandas as pd
    from openpyxl.styles import Font, PatternFill, Alignment

    db_p = get_db_path(config.get("scraper_db_path", ""))
    posts = query_posts_for_spy(
        db_path=db_p,
        page_names=req.page_names,
        mode=req.mode or "newest",
        limit=req.limit or 0,
        post_type_filter=req.post_type or "Tất cả",
        download_status=req.download_status or "Tất cả",
        sort_by=req.sort_by or "",
        sort_order=req.sort_order or "desc",
    )

    if not posts:
        raise HTTPException(status_code=400, detail="Không có bài viết nào để xuất Excel!")

    df = pd.DataFrame(posts)
    # Reorder / drop technical columns if present
    drop_cols = [c for c in ["id", "_key"] if c in df.columns]
    if drop_cols:
        df = df.drop(columns=drop_cols)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"Tinix_Posts_Export_{ts}.xlsx"
    out_dir = config.get("output_dir", ".")
    os.makedirs(out_dir, exist_ok=True)
    filepath = os.path.join(out_dir, filename)

    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Posts")
        ws = writer.sheets["Posts"]
        hdr_fill = PatternFill(start_color="124548", end_color="124548", fill_type="solid")
        hdr_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
        for cell in ws[1]:
            cell.fill = hdr_fill
            cell.font = hdr_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

    log_to_web(f"Đã xuất {len(posts)} bài viết ra file Excel: {filename}", "OK")
    return {
        "status": "success",
        "filename": filename,
        "filepath": os.path.abspath(filepath)
    }
