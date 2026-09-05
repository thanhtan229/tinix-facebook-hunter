import asyncio
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from web.ws_manager import manager, log_to_web
from web.security import SESSION_COOKIE, SESSION_TOKEN, resolve_media_file, valid_session
from core.db_storage import get_db_path, recover_interrupted_downloads
from core.version import APP_VERSION
from utils import config
from utils.logger import set_gui_callback
from web.routes.system import router as system_router
from web.routes.downloader import router as downloader_router
from web.routes.scraper import router as scraper_router
from web.routes.spy import router as spy_router
from web.routes.accounts import router as accounts_router

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Capture the ASGI loop so worker threads can publish progress safely."""
    manager.bind_loop(asyncio.get_running_loop())
    db_path = get_db_path(config.get("scraper_db_path", ""))
    interrupted_downloads = recover_interrupted_downloads(db_path)
    if interrupted_downloads:
        log_to_web(
            f"Đã chuyển {interrupted_downloads} bài tải bị gián đoạn sang trạng thái Tải lỗi.",
            "WARNING",
        )
    yield


app = FastAPI(
    title="Tinix-Facebook-Hunter",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    """Return useful validation details without echoing credentials or request bodies."""
    errors = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        {"status": "error", "detail": "Dữ liệu gửi lên không hợp lệ", "errors": errors},
        status_code=422,
    )


def _is_local_origin(origin: str | None, host: str | None) -> bool:
    if not origin:
        return True
    origin_clean = origin.lower().replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
    return origin_clean in {"127.0.0.1", "localhost"}


@app.middleware("http")
async def protect_local_endpoints(request: Request, call_next):
    """Allow localhost requests while protecting against unauthorized cross-origin requests."""
    protected = request.url.path.startswith("/api/") or request.url.path == "/media-preview"
    client_host = request.client.host if request.client else "127.0.0.1"
    is_local = client_host in {"127.0.0.1", "::1", "localhost"}

    if protected and not is_local and not valid_session(request.cookies.get(SESSION_COOKIE)):
        return JSONResponse({"detail": "Phiên WebUI không hợp lệ"}, status_code=401)

    if protected and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if not _is_local_origin(origin, request.headers.get("host")) and not is_local:
            return JSONResponse({"detail": "Origin không được phép"}, status_code=403)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.fbcdn.net; connect-src 'self' ws: wss:"
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response

# Connect logger to WebSocket
def _logger_bridge(level: str, msg: str):
    log_to_web(msg, level)

set_gui_callback(_logger_bridge)

# Include API routers
app.include_router(system_router)
app.include_router(downloader_router)
app.include_router(scraper_router)
app.include_router(spy_router)
app.include_router(accounts_router)

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not valid_session(websocket.cookies.get(SESSION_COOKIE)):
        await websocket.close(code=1008, reason="Invalid WebUI session")
        return
    origin = websocket.headers.get("origin")
    if not _is_local_origin(origin, websocket.headers.get("host")):
        await websocket.close(code=1008, reason="Invalid origin")
        return
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)

# Media preview streaming endpoint
@app.get("/media-preview")
async def preview_media(path: str = Query(..., description="Absolute local path to media file")):
    media_path = resolve_media_file(path)
    if media_path is None:
        raise HTTPException(status_code=404, detail="File không tồn tại hoặc nằm ngoài thư mục được phép")
    mime, _ = mimetypes.guess_type(str(media_path))
    return FileResponse(str(media_path), media_type=mime or "application/octet-stream")

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    favicon_file = STATIC_DIR / "favicon.ico"
    if favicon_file.exists():
        return FileResponse(str(favicon_file), media_type="image/x-icon")
    raise HTTPException(status_code=404, detail="Favicon not found")

@app.get("/")
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        response = FileResponse(str(index_file))
    else:
        response = HTMLResponse("<h1>Tinix-Facebook-Hunter - Static UI files are being initialized...</h1>")
    response.set_cookie(
        SESSION_COOKIE,
        SESSION_TOKEN,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
    return response
