"""Docker Executor — 容器生命周期管理。"""
from __future__ import annotations
import asyncio
import datetime
import uuid
from typing import TYPE_CHECKING
import docker
import docker.errors
import structlog
from .models import TaskInfo
from .protocol import MessageType, make_message
if TYPE_CHECKING:
 from .queue import MessageQueue
 from .scheduler import TaskScheduler
log = structlog.get_logger
class DockerExecutor:
 def __init__(self, default_image: str = "friday-task:latest") -> None:
 self._client = docker.from_env
 self._default_image = default_image
 self._client.ping
 async def start_container(
 self, task: TaskInfo, callback_url: str, callback_token: str
 ) -> str:
 container_name = f"friday-task-{uuid.uuid4.hex[:12]}"
 image = task.image or self._default_image
 env = {
 "FRIDAY_SESSION_ID": task.task_id,
 "FRIDAY_TASK_TYPE": task.task_type,
 "FRIDAY_CALLBACK_URL": callback_url,
 "FRIDAY_CALLBACK_TOKEN": callback_token,
 "FRIDAY_GIT_REPO_URL": task.repo_url,
 "FRIDAY_GIT_BRANCH": task.branch,
 "FRIDAY_TASK_TIMEOUT": str(task.timeout or 1800),
 }
 try:
 container = await asyncio.to_thread(
 self._client.containers.run,
 image,
 detach=True,
 name=container_name,
 environment=env,
 extra_hosts={"host.docker.internal": "host-gateway"},
 labels={"friday.task_id": task.task_id},
 auto_remove=False,
 )
 except docker.errors.ImageNotFound as e:
 raise RuntimeError(f"Image not found: {image}") from e
 except docker.errors.APIError as e:
 raise RuntimeError(f"Docker API error: {e}") from e
 log.info("container_started", task_id=task.task_id, container_id=container.id)
 return str(container.id)
 async def wait_container(self, container_id: str, timeout: int) -> tuple[int, str]:
 try:
 container = await asyncio.to_thread(self._client.containers.get, container_id)
 except docker.errors.NotFound:
 return -1, ""
 logs = ""
 try:
 result = await asyncio.wait_for(
 asyncio.to_thread(container.wait), timeout=timeout
 )
 exit_code = int(result.get("StatusCode", -1))
 except asyncio.TimeoutError:
 log.warning("container_timeout", container_id=container_id)
 await self.kill_container(container_id)
 exit_code = -1
 try:
 raw = await asyncio.to_thread(container.logs, tail=2000)
 logs = raw.decode("utf-8", errors="replace")
 except docker.errors.NotFound:
 pass
 return exit_code, logs
 async def kill_container(self, container_id: str) -> None:
 try:
 container = await asyncio.to_thread(self._client.containers.get, container_id)
 await asyncio.to_thread(container.kill)
 except docker.errors.NotFound:
 pass
 async def remove_container(self, container_id: str) -> None:
 try:
 container = await asyncio.to_thread(self._client.containers.get, container_id)
 await asyncio.to_thread(container.remove, force=True)
 except docker.errors.NotFound:
 pass
 async def get_container_status(self, container_id: str) -> str | None:
 try:
 container = await asyncio.to_thread(self._client.containers.get, container_id)
 await asyncio.to_thread(container.reload)
 return str(container.status)
 except docker.errors.NotFound:
 return None
 async def startup_cleanup(self) -> int:
 """清理上次残留的 friday-task-* 容器。"""
 containers = await asyncio.to_thread(
 self._client.containers.list, all=True, filters={"label": "friday.task_id"}
 )
 count = 0
 for c in containers:
 try:
 await asyncio.to_thread(c.remove, force=True)
 count += 1
 except docker.errors.NotFound:
 pass
 log.info("startup_cleanup_completed", count=count)
 return count
 async def zombie_scan(
 self, scheduler: TaskScheduler, queue: MessageQueue,
 interval: float = 30.0, zombie_threshold: float = 120.0, retain_hours: float = 1.0,
 ) -> None:
 """后台僵尸容器扫描循环。"""
 while True:
 await asyncio.sleep(interval)
 await self._scan_once(scheduler, queue, zombie_threshold, retain_hours)
 async def _scan_once(
 self, scheduler: TaskScheduler, queue: MessageQueue,
 zombie_threshold: float, retain_hours: float,
 ) -> None:
 try:
 containers = await asyncio.to_thread(
 self._client.containers.list, all=True, filters={"label": "friday.task_id"}
 )
 except Exception:
 log.exception("zombie_scan_list_failed")
 return
 known_ids = set(scheduler.get_all_container_ids)
 now = datetime.datetime.now(datetime.timezone.utc)
 for c in containers:
 try:
 task_id = c.labels.get("friday.task_id", "")
 status = c.status
 if status == "running" and c.id not in known_ids:
 created = c.attrs.get("Created", "")
 created_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
 age = (now - created_dt).total_seconds
 if age > zombie_threshold:
 await asyncio.to_thread(c.kill)
 queue.push(make_message(MessageType.TASK_FAILED, {
 "task_id": task_id, "exit_code": -1,
 "error": "zombie container killed",
 "duration_ms": int(age * 1000), "logs": "",
 }))
 log.warning("zombie_killed", task_id=task_id, container_id=c.id)
 elif status == "exited":
 finished = c.attrs.get("State", {}).get("FinishedAt", "")
 if finished:
 finished_dt = datetime.datetime.fromisoformat(finished.replace("Z", "+00:00"))
 hours = (now - finished_dt).total_seconds / 3600
 if hours > retain_hours:
 await asyncio.to_thread(c.remove, force=True)
 log.info("container_cleaned", task_id=task_id, container_id=c.id)
 except Exception:
 log.exception("zombie_scan_container_error", container_id=c.id)
