import asyncio
import json
import threading
from typing import List, Dict, Any, Optional
from fastapi import WebSocket

class ConnectionManager:
    """Manages active WebSocket connections and broadcasts logs/progress updates."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the ASGI event loop used for broadcasts from worker threads."""
        self._loop = loop

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message dict (JSON-serialized) to all connected clients."""
        if not self.active_connections:
            return
        payload = json.dumps(message, ensure_ascii=False)
        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception:
                disconnected.append(connection)

        if disconnected:
            async with self._lock:
                for dead_conn in disconnected:
                    if dead_conn in self.active_connections:
                        self.active_connections.remove(dead_conn)

    def broadcast_sync(self, message: Dict[str, Any]):
        """Helper to safely broadcast from a synchronous background thread."""
        loop = self._loop
        if loop is None or loop.is_closed() or not loop.is_running():
            return
        if threading.current_thread() is threading.main_thread():
            loop.create_task(self.broadcast(message))
        else:
            asyncio.run_coroutine_threadsafe(self.broadcast(message), loop)

manager = ConnectionManager()

def log_to_web(msg: str, level: str = "INFO"):
    """Helper to push a formatted log message to the WebUI terminal."""
    manager.broadcast_sync({
        "type": "log",
        "level": level.upper(),
        "message": msg
    })

def progress_to_web(task: str, current: int, total: int, speed: str = "", status: str = ""):
    """Helper to push progress updates to the WebUI."""
    manager.broadcast_sync({
        "type": "progress",
        "task": task,
        "current": current,
        "total": total,
        "speed": speed,
        "status": status
    })
