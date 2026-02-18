"""HTTP 回调服务器 — 接收容器回调并转发到 Server。"""
from __future__ import annotations
import aiohttp.web
import structlog
from .protocol import make_message
from .queue import MessageQueue
log = structlog.get_logger
CALLBACK_PORT = 8976
CALLBACK_TO_WS: dict[str, str] = {
 "completed": "task.completed",
 "failed": "task.failed",
 "question": "task.question",
 "heartbeat": "task.progress",
 "progress": "task.progress",
 "action_log": "task.log",
 "token_usage": "task.token_usage",
}
async def start_callback_server(
 queue: MessageQueue, callback_token: str,
) -> aiohttp.web.AppRunner:
 """启动 HTTP 回调服务器，返回 AppRunner（调用方负责 cleanup）。"""
 async def handle_callback(request: aiohttp.web.Request) -> aiohttp.web.Response:
 try:
 data = await request.json
 except Exception:
 return aiohttp.web.json_response({"error": "bad json"}, status=400)
 if data.get("token") != callback_token:
 return aiohttp.web.json_response({"error": "unauthorized"}, status=401)
 cb_type = data.get("type", "")
 ws_type = CALLBACK_TO_WS.get(cb_type)
 if not ws_type:
 return aiohttp.web.json_response({"error": "unknown type"}, status=400)
 session_id = data.get("session_id", "")
 payload = data.get("payload", {})
 queue.push(make_message(ws_type, {"task_id": session_id, **payload}))
 return aiohttp.web.json_response({"ok": True})
 app = aiohttp.web.Application
 app.router.add_post("/callback", handle_callback)
 runner = aiohttp.web.AppRunner(app)
 await runner.setup
 site = aiohttp.web.TCPSite(runner, "0.0.0.0", CALLBACK_PORT)
 await site.start
 log.info("callback_server_started", port=CALLBACK_PORT)
 return runner
