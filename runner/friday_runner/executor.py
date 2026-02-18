"""Docker Executor — 容器生命周期管理。"""
from __future__ import annotations
import asyncio
import uuid
import docker
import docker.errors
import structlog
from .models import TaskInfo
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
