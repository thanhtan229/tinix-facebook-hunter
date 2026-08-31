import os
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import Field, model_validator
from typing import Annotated, Optional, List, Literal
from core.db_storage import (
    get_db_path,
    get_scraped_pages_full,
    query_posts_for_spy,
)
from core.data_cleanup import cleanup_scraped_data, preview_scraped_cleanup
from utils import config
from web.ws_manager import log_to_web
from web.models import ApiRequest
from web.routes.downloader import download_is_running
from web.routes.scraper import scrape_is_running

router = APIRouter(prefix="/api/spy", tags=["Spy Studio"])

class QueryPostsRequest(ApiRequest):
    page_names: List[str] = Field(min_length=1, max_length=1_000)
    mode: Optional[str] = Field(default="newest", pattern="^(newest|top_engagement)$")
    limit: Optional[int] = Field(default=0, ge=0, le=100_000)
    post_type: Optional[str] = Field(default="Tất cả", max_length=100)
    download_status: Optional[str] = Field(default="Tất cả", max_length=100)
    query: Optional[str] = Field(default="", max_length=10_000)

class ExportExcelRequest(ApiRequest):
    page_names: List[str] = Field(min_length=1, max_length=1_000)
    mode: Optional[str] = Field(default="newest", pattern="^(newest|top_engagement)$")
    limit: Optional[int] = Field(default=0, ge=0, le=100_000)
    post_type: Optional[str] = Field(default="Tất cả", max_length=100)
    download_status: Optional[str] = Field(default="Tất cả", max_length=100)


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

@router.post("/cleanup-preview")
def cleanup_preview(req: CleanupScopeRequest):
    db_p = get_db_path(config.get("scraper_db_path", ""))
    data = preview_scraped_cleanup(
        db_p, page_urls=req.page_urls, all_pages=req.all_pages
    )
    return {"status": "success", "data": data}


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
