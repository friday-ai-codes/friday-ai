"""WebSocket 客户端：连接、心跳、重连、消息缓冲。"""
from __future__ import annotations
import asyncio
import json
import random
import structlog
import websockets
import websockets.asyncio.client
from .heartbeat import collect_metrics, warmup
from .protocol import MessageType, make_message, make_response
from .queue import MessageQueue
log = structlog.get_logger
INITIAL_DELAY = 1.0
MAX_DELAY = 60.0
BACKOFF_FACTOR = 2.0
MAX_RETRIES = 20
HEARTBEAT_INTERVAL = 30.0
CLOSE_CODE_REPLACED = 4002
async def run_ws(url: str, token: str, name: str, version: str, concurrent: int) -> None:
 """主入口：连接 Server WS 端点，维持心跳，自动重连。"""
 # 构造 WS URI
 uri = url.replace("https://", "wss://").replace("http://", "ws://")
 uri = uri.rstrip("/") + f"/ws/v1/runner/?token={token}"
 if not any(h in url for h in ("localhost", "127.0.0.1")) and not uri.startswith("wss://"):
 log.warning("insecure_connection", msg="生产环境应使用 WSS (TLS) 连接")
 warmup
 queue = MessageQueue
 delay = INITIAL_DELAY
 retries = 0
 while retries < MAX_RETRIES:
 try:
 async with websockets.asyncio.client.connect(
 uri, ping_interval=20, ping_timeout=10
 ) as ws:
 delay = INITIAL_DELAY
 retries = 0
 await _on_connected(ws, name, version, concurrent, queue)
 await _message_loop(ws, concurrent, queue)
 except websockets.ConnectionClosed as e:
 if e.code == CLOSE_CODE_REPLACED:
 log.info("connection_replaced", msg="被新连接替代，停止重连")
 return
 except (OSError, websockets.WebSocketException):
 pass
 retries += 1
 jitter = random.uniform(0, delay * 0.1)
 log.info("reconnecting", attempt=retries, delay=f"{delay + jitter:.1f}s")
 await asyncio.sleep(delay + jitter)
 delay = min(delay * BACKOFF_FACTOR, MAX_DELAY)
 raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")
async def _on_connected(
 ws: websockets.asyncio.client.ClientConnection,
 name: str,
 version: str,
 concurrent: int,
 queue: MessageQueue,
) -> None:
 """连接成功后发送 hello 并 drain 队列。"""
 hello = make_message(MessageType.RUNNER_HELLO, {
 "name": name, "version": version, "concurrent": concurrent,
 })
 await ws.send(json.dumps(hello))
 for msg in queue.drain:
 await ws.send(json.dumps(msg))
 log.info("connected", name=name)
async def _message_loop(
 ws: websockets.asyncio.client.ClientConnection,
 concurrent: int,
 queue: MessageQueue,
) -> None:
 """接收消息循环 + 心跳定时器。"""
 heartbeat_task = asyncio.create_task(_heartbeat_loop(ws, concurrent, queue))
 try:
 async for raw in ws:
 content = json.loads(raw)
 if content.get("type") == MessageType.TASK_ASSIGN:
 await _handle_task_assign(ws, content, queue)
 else:
 log.debug("received", type=content.get("type"))
 finally:
 heartbeat_task.cancel
 try:
 await heartbeat_task
 except asyncio.CancelledError:
 pass
async def _heartbeat_loop(
 ws: websockets.asyncio.client.ClientConnection,
 concurrent: int,
 queue: MessageQueue,
) -> None:
 """每 HEARTBEAT_INTERVAL 秒发送心跳。"""
 while True:
 await asyncio.sleep(HEARTBEAT_INTERVAL)
 msg = make_message(MessageType.RUNNER_HEARTBEAT, collect_metrics(0, concurrent))
 try:
 await ws.send(json.dumps(msg))
 except Exception:
 queue.push(msg)
async def _handle_task_assign(
 ws: websockets.asyncio.client.ClientConnection,
 content: dict,
 queue: MessageQueue,
) -> None:
 """收到 task.assign 后响应 task.accepted。"""
 task_id = content.get("payload", {}).get("task_id")
 response = make_response(content.get("id", ""), MessageType.TASK_ACCEPTED, {"task_id": task_id})
 try:
 await ws.send(json.dumps(response))
 except Exception:
 queue.push(response)
 log.info("task_accepted", task_id=task_id)
