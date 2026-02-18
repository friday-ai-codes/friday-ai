"""HTTP 回调服务器 — 接收容器回调并转发到 Server。"""
from __future__ import annotations
import asyncio
import aiohttp.web
import structlog
from .protocol import MessageType, make_message
from .queue import MessageQueue
log = structlog.get_logger
CALLBACK_PORT = 8976
DEFAULT_TOOL_TIMEOUT = 60
CALLBACK_TO_WS: dict[str, str] = {
 "completed": "task.completed",
 "failed": "task.failed",
 "question": "task.question",
 "heartbeat": "task.progress",
 "progress": "task.progress",
 "action_log": "task.log",
 "token_usage": "task.token_usage",
}
# tool call 同步等待：call_id -> Future
_pending_tool_calls: dict[str, asyncio.Future[dict]] = {}
def resolve_tool_call(call_id: str, result: dict) -> None:
 """由 WS 层调用，resolve 对应 Future。"""
 fut = _pending_tool_calls.get(call_id)
 if fut and not fut.done:
 fut.set_result(result)
def cleanup_pending_tool_calls(task_id: str) -> None:
 """任务结束时取消该 task 所有未完成的 tool call Future。"""
 to_remove = [cid for cid, fut in _pending_tool_calls.items if not fut.done]
 for cid in to_remove:
 fut = _pending_tool_calls.pop(cid, None)
 if fut and not fut.done:
 fut.cancel
async def _handle_tool_call(
 data: dict, queue: MessageQueue,
) -> aiohttp.web.Response:
 """处理 tool_call 回调：转发到 Server 并同步等待结果。"""
 payload = data.get("payload", {})
 call_id = payload.get("call_id", "")
 tool_name = payload.get("tool_name", "")
 arguments = payload.get("arguments", {})
 session_id = data.get("session_id", "")
 if not call_id or not tool_name:
 return aiohttp.web.json_response({"error": "missing call_id or tool_name"}, status=400)
 loop = asyncio.get_running_loop
 fut: asyncio.Future[dict] = loop.create_future
 _pending_tool_calls[call_id] = fut
 queue.push(make_message(MessageType.TOOL_CALL, {
 "task_id": session_id,
 "call_id": call_id,
 "tool_name": tool_name,
 "arguments": arguments,
 }))
 try:
 result = await asyncio.wait_for(fut, timeout=DEFAULT_TOOL_TIMEOUT)
 return aiohttp.web.json_response({"ok": True, "result": result})
 except asyncio.TimeoutError:
 return aiohttp.web.json_response(
 {"ok": False, "error": {"code": "timeout", "message": f"tool call {call_id} timed out"}},
 status=504,
 )
 finally:
 _pending_tool_calls.pop(call_id, None)
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
 # tool_call 走专用路径（同步等待结果）
 if cb_type == "tool_call":
 return await _handle_tool_call(data, queue)
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
