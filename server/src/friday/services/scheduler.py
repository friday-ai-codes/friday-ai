"""Task Scheduler Service - Manages Docker containers for task execution.
任务容器镜像由独立的 task/ 项目构建（friday-task:latest）。
task 是一个独立的 Python 项目，支持：
1. CLI 模式 - 直接命令行调用
2. 容器模式 - 由本 scheduler 启动执行
参见: task/README.md 了解详情
"""
import os
import platform
from typing import Any
import docker
import structlog
from docker.errors import APIError, ImageNotFound
from friday.config import get_settings
from friday.models.task import Task
logger = structlog.get_logger
# 检测是否在 Docker 网络环境中运行
def _detect_docker_network -> str | None:
 """检测 friday-network 是否存在。返回网络名称或 None。"""
 try:
 client = docker.from_env
 networks = client.networks.list(names=["friday-ai_friday-network"])
 if networks:
 return "friday-ai_friday-network"
 # 也检查不带前缀的网络名
 networks = client.networks.list(names=["friday-network"])
 if networks:
 return "friday-network"
 except Exception:
 pass
 return None
def _get_host_callback_url(port: int = 8000) -> str:
 """获取宿主机的回调 URL（用于本地开发模式）。"""
 system = platform.system.lower
 if system in ("darwin", "windows"):
 # macOS/Windows: 使用 host.docker.internal
 return f"http://host.docker.internal:{port}/api"
 else:
 # Linux: 使用默认网关 IP
 return f"http://172.17.0.1:{port}/api"
class TaskScheduler:
 """Scheduler for running task containers."""
 def __init__(self):
 """Initialize the task scheduler."""
 self.settings = get_settings
 self.client = docker.from_env
 self.image_name = "friday-task:latest"
 self._running_containers: dict[str, str] = {} # task_id -> container_id
 # 检测 Docker 网络环境
 self._docker_network = _detect_docker_network
 if self._docker_network:
 logger.info(
 "Docker network detected, using container networking",
 network=self._docker_network,
 )
 else:
 logger.info("Docker network not found, using host networking for callbacks")
 async def start_task(
 self,
 task: Task,
 repo_url: str,
 branch: str,
 git_credentials: dict[str, str],
 mode: str = "plan",
 claude_config: dict[str, str] | None = None,
 ) -> str:
 """Start a container for the given task.
 Args:
 task: The task to execute
 repo_url: Git repository URL
 branch: Git branch name
 git_credentials: Dict with git_ssh_key or git_access_token
 mode: "plan" or "execute"
 claude_config: Dict with api_key and base_url for Claude
 Returns:
 Container ID
 """
 log = logger.bind(task_id=task.id, project_id=task.project_id, mode=mode)
 log.info("Starting task container")
 # Build environment variables for the container
 env = self._build_env(
 task, repo_url, branch, git_credentials, mode, claude_config
 )
 try:
 # Ensure image exists
 await self._ensure_image
 # 构建容器运行参数
 run_kwargs: dict[str, Any] = {
 "detach": True,
 "environment": env,
 "name": f"friday-task-{task.id}",
 "labels": {
 "friday.task_id": str(task.id),
 "friday.project_id": str(task.project_id),
 "friday.mode": mode,
 },
 # 资源限制
 "mem_limit": "2g",
 "cpu_period": 100000,
 "cpu_quota": 100000, # 1 CPU
 # 持久化卷
 "volumes": {
 f"friday-sessions-{task.id}": {
 "bind": "/app/sessions",
 "mode": "rw",
 },
 },
 # 完成后不自动删除（便于查看日志）
 "auto_remove": False,
 }
 # 网络配置：如果检测到 Docker 网络则加入，否则使用默认 bridge 网络
 if self._docker_network:
 run_kwargs["network"] = self._docker_network
 log.debug("Using Docker network", network=self._docker_network)
 else:
 # 本地开发模式：不指定网络，使用默认 bridge
 # 需要添加 extra_hosts 让容器能访问宿主机（Linux 需要）
 run_kwargs["extra_hosts"] = {"host.docker.internal": "host-gateway"}
 log.debug("Using host networking mode for local development")
 # Run container
 container = self.client.containers.run(self.image_name, **run_kwargs)
 container_id = str(container.id)
 self._running_containers[str(task.id)] = container_id
 log.info("Task container started", container_id=container_id[:12])
 return container_id
 except ImageNotFound:
 log.error("Task image not found")
 raise RuntimeError("Task container image not found. Please build it first.")
 except APIError as e:
 log.error("Docker API error", error=str(e))
 raise RuntimeError(f"Failed to start container: {e}")
 def _build_env(
 self,
 task: Task,
 repo_url: str,
 branch: str,
 git_credentials: dict[str, str],
 mode: str,
 claude_config: dict[str, str] | None = None,
 ) -> dict[str, str]:
 """Build environment variables for the task container."""
 log = logger.bind(task_id=task.id)
 # 根据网络环境选择回调 URL
 if self._docker_network:
 # Docker Compose 模式：使用容器名进行通信
 callback_url = "http://friday-server:8000/api"
 else:
 # 本地开发模式：使用宿主机地址
 # 从配置中读取端口，默认 8000
 port = int(os.environ.get("FRIDAY_PORT", "8000"))
 callback_url = _get_host_callback_url(port)
 # Claude 配置：优先使用传入的配置，否则回退到环境变量
 claude_api_key = ""
 claude_base_url = ""
 if claude_config:
 claude_api_key = claude_config.get("api_key", "")
 claude_base_url = claude_config.get("base_url", "")
 log.info(
 "Claude config received",
 has_api_key=bool(claude_api_key),
 api_key_length=len(claude_api_key) if claude_api_key else 0,
 base_url=claude_base_url or "(not set)",
 )
 else:
 log.warning(
 "No claude_config provided, falling back to environment variables"
 )
 if not claude_api_key:
 claude_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
 if claude_api_key:
 log.info(
 "Using ANTHROPIC_API_KEY from environment",
 key_length=len(claude_api_key),
 )
 else:
 log.error("No ANTHROPIC_API_KEY found!")
 if not claude_base_url:
 claude_base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
 env = {
 # Task identification
 "FRIDAY_TASK_TASK_ID": str(task.id),
 "FRIDAY_TASK_PROJECT_ID": str(task.project_id),
 # Task details
 "FRIDAY_TASK_TASK_TITLE": task.title,
 "FRIDAY_TASK_TASK_DESCRIPTION": task.description or "",
 "FRIDAY_TASK_TASK_MODE": mode,
 # Git configuration
 "FRIDAY_TASK_GIT_REPO_URL": repo_url,
 "FRIDAY_TASK_GIT_BRANCH": branch,
 # Claude configuration
 "FRIDAY_TASK_CLAUDE_API_KEY": claude_api_key,
 "FRIDAY_TASK_CLAUDE_BASE_URL": claude_base_url,
 # Callback configuration - 根据环境自动选择地址
 "FRIDAY_TASK_CALLBACK_URL": callback_url,
 "FRIDAY_TASK_CALLBACK_TOKEN": "", # TODO: Add internal auth
 }
 # Add git credentials
 if git_credentials.get("ssh_key"):
 env["FRIDAY_TASK_GIT_AUTH_TYPE"] = "ssh"
 env["FRIDAY_TASK_GIT_SSH_KEY"] = git_credentials["ssh_key"]
 elif git_credentials.get("access_token"):
 env["FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
 env["FRIDAY_TASK_GIT_ACCESS_TOKEN"] = git_credentials["access_token"]
 # Git SSL 验证配置（用于处理自签名证书的内部 Git 服务器）
 # 默认禁用 SSL 验证以支持内部 GitLab/GitHub 企业版
 git_ssl_verify = git_credentials.get("ssl_verify", False)
 env["FRIDAY_TASK_GIT_SSL_VERIFY"] = str(git_ssl_verify).lower
 return env
 async def _ensure_image(self) -> None:
 """Ensure the task container image exists."""
 try:
 self.client.images.get(self.image_name)
 except ImageNotFound:
 logger.warning("Task image not found, attempting to build")
 # Try to build the image
 await self._build_image
 async def _build_image(self) -> None:
 """Build the task container image."""
 task_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "task")
 if not os.path.exists(os.path.join(task_dir, "Dockerfile")):
 raise RuntimeError("Task Dockerfile not found")
 logger.info("Building task container image", path=task_dir)
 try:
 self.client.images.build(
 path=task_dir,
 tag=self.image_name,
 rm=True,
 )
 logger.info("Task image built successfully")
 except APIError as e:
 logger.error("Failed to build task image", error=str(e))
 raise
 async def stop_task(self, task_id: str, force: bool = False) -> bool:
 """Stop a running task container.
 Args:
 task_id: The task ID
 force: Whether to force kill the container
 Returns:
 True if container was stopped, False if not found
 """
 log = logger.bind(task_id=task_id)
 container_id = self._running_containers.get(task_id)
 if not container_id:
 # Try to find by label
 containers = self.client.containers.list(
 filters={"label": f"friday.task_id={task_id}"}
 )
 if not containers:
 log.warning("No container found for task")
 return False
 container_id = containers[0].id
 try:
 container = self.client.containers.get(container_id)
 if force:
 container.kill
 else:
 container.stop(timeout=30)
 log.info("Task container stopped", container_id=container_id[:12])
 self._running_containers.pop(task_id, None)
 return True
 except APIError as e:
 log.error("Failed to stop container", error=str(e))
 return False
 async def get_task_status(self, task_id: str) -> dict[str, Any] | None:
 """Get the status of a task container.
 Args:
 task_id: The task ID
 Returns:
 Container status dict or None if not found
 """
 containers = self.client.containers.list(
 all=True,
 filters={"label": f"friday.task_id={task_id}"},
 )
 if not containers:
 return None
 container = containers[0]
 return {
 "container_id": container.id[:12],
 "status": container.status,
 "state": container.attrs.get("State", {}),
 "created": container.attrs.get("Created"),
 }
 async def get_task_logs(self, task_id: str, tail: int = 100) -> str | None:
 """Get logs from a task container.
 Args:
 task_id: The task ID
 tail: Number of lines to return
 Returns:
 Container logs or None if not found
 """
 containers = self.client.containers.list(
 all=True,
 filters={"label": f"friday.task_id={task_id}"},
 )
 if not containers:
 return None
 container = containers[0]
 logs = container.logs(tail=tail, timestamps=True)
 return logs.decode("utf-8") if logs else ""
 async def cleanup_finished_containers(self) -> int:
 """Clean up finished task containers.
 Returns:
 Number of containers removed
 """
 containers = self.client.containers.list(
 all=True,
 filters={
 "label": "friday.task_id",
 "status": "exited",
 },
 )
 removed = 0
 for container in containers:
 try:
 container.remove(v=True) # Also remove volumes
 removed += 1
 logger.debug(
 "Removed finished container", container_id=container.id[:12]
 )
 except APIError as e:
 logger.warning("Failed to remove container", error=str(e))
 if removed:
 logger.info("Cleaned up finished containers", count=removed)
 return removed
# Singleton instance
_scheduler: TaskScheduler | None = None
def get_scheduler -> TaskScheduler:
 """Get the task scheduler singleton."""
 global _scheduler
 if _scheduler is None:
 _scheduler = TaskScheduler
 return _scheduler
