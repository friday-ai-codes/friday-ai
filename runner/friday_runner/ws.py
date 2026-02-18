"""WebSocket 客户端：连接、心跳、重连、消息缓冲、任务执行。"""
from __future__ import annotations
import asyncio
import json
import random
import secrets
import time
import structlog
import websockets
import websockets.asyncio.client
from .callback import CALLBACK_PORT, start_callback_server
from .executor import DockerExecutor
from .heartbeat import collect_metrics, warmup
from .models import TaskInfo
from .protocol import MessageType, make_message, make_response
from .queue import MessageQueue
from .scheduler import TaskScheduler
log = structlog.get_logger
INITIAL_DELAY = 1.0
MAX_DELAY = 60.0
BACKOFF_FACTOR = 2.0
MAX_RETRIES = 20
HEARTBEAT_INTERVAL = 30.0
CLOSE_CODE_REPLACED = 4002
async def run_ws(
 url: str, token: str, name: str, version: str, concurrent: int,
 image: str = "friday-task:latest",
 timeout: int = 1800,
 callback_token: str = "",
) -> None:
 """主入口：连接 Server WS 端点，维持心跳，自动重连。"""
 uri = url.replace("https://", "wss://").replace("http://", "ws://")
 uri = uri.rstrip("/") + f"/ws/v1/runner/?token={token}"
 if not any(h in url for h in ("localhost", "127.0.0.1")) and not uri.startswith("wss://"):
 log.warning("insecure_connection", msg="生产环境应使用 WSS (TLS) 连接")
 warmup
 queue = MessageQueue
 # 初始化组件
 executor = DockerExecutor(default_image=image)
 scheduler = TaskScheduler(max_concurrent=concurrent)
 if not callback_token:
 callback_token = secrets.token_urlsafe(32)
 callback_url = f"http://host.docker.internal:{CALLBACK_PORT}/callback"
 callback_runner = await start_callback_server(queue, callback_token)
 async def on_task(task: TaskInfo) -> None:
 await _run_task(task, executor, scheduler, queue, callback_url, callback_token, timeout)
 scheduler.set_task_callback(on_task)
 scheduler_task = asyncio.create_task(scheduler.run)
 try:
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
 await _message_loop(ws, concurrent, queue, scheduler)
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
 finally:
 scheduler_task.cancel
 await callback_runner.cleanup
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
 scheduler: TaskScheduler,
) -> None:
 """接收消息循环 + 心跳定时器。"""
 heartbeat_task = asyncio.create_task(_heartbeat_loop(ws, concurrent, queue, scheduler))
 try:
 async for raw in ws:
 content = json.loads(raw)
 if content.get("type") == MessageType.TASK_ASSIGN:
 await _handle_task_assign(ws, content, queue, scheduler)
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
 scheduler: TaskScheduler,
) -> None:
 """每 HEARTBEAT_INTERVAL 秒发送心跳。"""
 while True:
 await asyncio.sleep(HEARTBEAT_INTERVAL)
 msg = make_message(MessageType.RUNNER_HEARTBEAT, collect_metrics(scheduler.active_count, concurrent))
 try:
 await ws.send(json.dumps(msg))
 except Exception:
 queue.push(msg)
async def _handle_task_assign(
 ws: websockets.asyncio.client.ClientConnection,
 content: dict,
 queue: MessageQueue,
 scheduler: TaskScheduler,
) -> None:
 """收到 task.assign 后响应 accepted 并提交到 scheduler。"""
 payload = content.get("payload", {})
 task_id = payload.get("task_id", "")
 response = make_response(content.get("id", ""), MessageType.TASK_ACCEPTED, {"task_id": task_id})
 try:
 await ws.send(json.dumps(response))
 except Exception:
 queue.push(response)
 task = TaskInfo(
 task_id=task_id,
 task_type=payload.get("task_type", "coding"),
 image=payload.get("image", ""),
 repo_url=payload.get("repo_url", ""),
 branch=payload.get("branch", ""),
 timeout=payload.get("timeout", 0),
 payload=payload,
 )
 await scheduler.submit(task)
 log.info("task_accepted", task_id=task_id)
async def _run_task(
 task: TaskInfo, executor: DockerExecutor, scheduler: TaskScheduler,
 queue: MessageQueue, callback_url: str, callback_token: str,
 default_timeout: int,
) -> None:
 """任务执行核心：启动容器 → 等待完成 → 上报结果。"""
 start = time.monotonic
 try:
 container_id = await executor.start_container(task, callback_url, callback_token)
 scheduler.register_container(task.task_id, container_id)
 timeout = task.timeout or default_timeout
 exit_code, logs = await executor.wait_container(container_id, timeout)
 duration_ms = int((time.monotonic - start) * 1000)
 if exit_code == 0:
 result = make_message(MessageType.TASK_COMPLETED, {
 "task_id": task.task_id, "exit_code": 0, "duration_ms": duration_ms, "logs": logs,
 })
 elif exit_code == -1:
 result = make_message(MessageType.TASK_FAILED, {
 "task_id": task.task_id, "exit_code": -1, "error": "timeout", "duration_ms": duration_ms, "logs": logs,
 })
 else:
 result = make_message(MessageType.TASK_FAILED, {
 "task_id": task.task_id, "exit_code": exit_code, "error": f"exited with code {exit_code}",
 "duration_ms": duration_ms, "logs": logs,
 })
 queue.push(result)
 except Exception as e:
 queue.push(make_message(MessageType.TASK_FAILED, {
 "task_id": task.task_id, "exit_code": -1, "error": str(e),
 "duration_ms": int((time.monotonic - start) * 1000), "logs": "",
 }))
 finally:
 scheduler.unregister_container(task.task_id)
