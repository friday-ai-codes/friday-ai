"""Task Scheduler Service - Manages Docker containers for task execution.
迁移自 FastAPI 版本，适配 Django 框架。
任务容器镜像由独立的 task/ 项目构建（friday-task:latest）。
task 是一个独立的 Python 项目，支持：
1. CLI 模式 - 直接命令行调用
2. 容器模式 - 由本 scheduler 启动执行
参见: task/README.md 了解详情
"""
import json
import logging
import os
import platform
from typing import Any, Optional
import docker
from docker.errors import APIError, ImageNotFound
from system.models import SettingKeys, SystemSetting
logger = logging.getLogger(__name__)
# 检测是否在 Docker 网络环境中运行
def _detect_docker_network -> Optional[str]:
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
 self.client = docker.from_env
 self.image_name = "friday-task:latest"
 self._running_containers: dict[str, str] = {} # task_id -> container_id
 # 检测 Docker 网络环境
 self._docker_network = _detect_docker_network
 if self._docker_network:
 logger.info(
 f"Docker network detected, using container networking: {self._docker_network}"
 )
 else:
 logger.info("Docker network not found, using host networking for callbacks")
 # 确保数据传输目录存在 (server/data/transfers)
 self.data_dir = os.path.abspath(
 os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
 )
 self.transfers_dir = os.path.join(self.data_dir, "transfers")
 os.makedirs(self.transfers_dir, exist_ok=True)
 async def start_task(
 self,
 task,
 repo_url: str,
 branch: str,
 git_credentials: dict[str, str],
 mode: str = "plan",
 claude_config: Optional[dict[str, str]] = None,
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
 task_id = str(task.id)
 project_id = str(task.project_id)
 logger.info(f"Starting task container: task_id={task_id}, mode={mode}")
 # 准备任务传输目录
 task_transfer_dir = os.path.join(self.transfers_dir, task_id)
 os.makedirs(task_transfer_dir, exist_ok=True)
 # 清理旧的结果文件
 result_file = os.path.join(task_transfer_dir, "result.json")
 if os.path.exists(result_file):
 os.remove(result_file)
 # Build environment variables for the container
 env = await self._build_env(task, repo_url, branch, git_credentials, mode, claude_config)
 # 注入传输目录环境变量
 env["FRIDAY_TASK_OUTPUT_DIR"] = "/app/transfer"
 try:
 # Ensure image exists
 await self._ensure_image
 # 构建容器运行参数
 run_kwargs: dict[str, Any] = {
 "detach": True,
 "environment": env,
 "name": f"friday-task-{task_id}",
 "labels": {
 "friday.task_id": task_id,
 "friday.project_id": project_id,
 "friday.mode": mode,
 },
 # 资源限制
 "mem_limit": "2g",
 "cpu_period": 100000,
 "cpu_quota": 100000, # 1 CPU
 # 持久化卷
 "volumes": {
 f"friday-sessions-{task_id}": {
 "bind": "/app/sessions",
 "mode": "rw",
 },
 # [新增] 挂载宿主机传输目录到容器
 task_transfer_dir: {
 "bind": "/app/transfer",
 "mode": "rw",
 },
 },
 # 完成后不自动删除（便于查看日志）
 "auto_remove": False,
 }
 # 网络配置：如果检测到 Docker 网络则加入，否则使用默认 bridge 网络
 if self._docker_network:
 run_kwargs["network"] = self._docker_network
 logger.debug(f"Using Docker network: {self._docker_network}")
 else:
 # 本地开发模式：不指定网络，使用默认 bridge
 # 需要添加 extra_hosts 让容器能访问宿主机（Linux 需要）
 run_kwargs["extra_hosts"] = {"host.docker.internal": "host-gateway"}
 logger.debug("Using host networking mode for local development")
 # Run container
 container = self.client.containers.run(self.image_name, **run_kwargs)
 container_id = str(container.id)
 self._running_containers[task_id] = container_id
 logger.info(f"Task container started: container_id={container_id[:12]}")
 return container_id
 except ImageNotFound:
 logger.error("Task image not found")
 raise RuntimeError("Task container image not found. Please build it first.")
 except APIError as e:
 logger.error(f"Docker API error: {e}")
 raise RuntimeError(f"Failed to start container: {e}")
 async def _build_env(
 self,
 task,
 repo_url: str,
 branch: str,
 git_credentials: dict[str, str],
 mode: str,
 claude_config: Optional[dict[str, str]] = None,
 ) -> dict[str, str]:
 """Build environment variables for the task container."""
 task_id = str(task.id)
 # Proxy Configuration Logic
 # Priority: 1. Repository specific proxy 2. System global proxy
 git_http_proxy = ""
 # 1. Check repository specific proxy
 if task.repository and task.repository.proxy_url:
 git_http_proxy = task.repository.proxy_url
 logger.info(f"Using repository proxy for task {task_id}")
 # 2. Check system global proxy if not set
 if not git_http_proxy:
 try:
 # Use sync_to_async or assume this runs in async context safe for ORM?
 # Since we are in async method, we should be careful.
 # However, _build_env is now async, so we can use ahelper or async ORM.
 # Django 5+ supports async ORM.
 # Check if SystemSetting has async support or wrap it.
 # Simplest way is to use sync_to_async if needed, but let's try direct async access if model allows
 # or just use synchronous access if wrapped in sync_to_async in caller.
 # But wait, start_task is async.
 # Let's use asgiref.sync.sync_to_async for safety
 from asgiref.sync import sync_to_async
 get_setting = sync_to_async(
 SystemSetting.objects.filter(key=SettingKeys.GIT_HTTP_PROXY).first
 )
 proxy_setting = await get_setting
 if proxy_setting and proxy_setting.value:
 git_http_proxy = proxy_setting.value
 logger.info(f"Using system global proxy for task {task_id}")
 except Exception as e:
 logger.warning(f"Failed to fetch system proxy setting: {e}")
 # 根据网络环境选择回调 URL
 if self._docker_network:
 # Docker Compose 模式：使用容器名进行通信
 callback_url = "http://friday-server:8000/api"
 else:
 # 本地开发模式：使用宿主机地址
 # 从配置中读取端口，默认 8000
 port = int(os.environ.get("FRIDAY_PORT", "8000"))
 callback_url = _get_host_callback_url(port)
 # Claude 配置：必须通过 Web UI 配置（项目级或系统级）
 claude_api_key = ""
 claude_base_url = ""
 if claude_config:
 claude_api_key = claude_config.get("api_key", "")
 claude_base_url = claude_config.get("base_url", "")
 logger.info(
 f"Claude config received: has_api_key={bool(claude_api_key)}, "
 f"base_url={claude_base_url or '(not set)'}"
 )
 else:
 logger.warning("No claude_config provided")
 if not claude_api_key:
 logger.error(
 "No Claude API Key configured! "
 "Please configure it in Web UI (Project Settings or System Settings)"
 )
 env = {
 # Task identification
 "FRIDAY_TASK_TASK_ID": task_id,
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
 # Inject Proxy Environment Variables
 if git_http_proxy:
 env["FRIDAY_TASK_GIT_HTTP_PROXY"] = git_http_proxy
 # Also set standard proxy env vars just in case, though Friday Task mainly uses FRIDAY_TASK_ prefix
 # The Task CLI will handle setting http_proxy/https_proxy based on FRIDAY_TASK_GIT_HTTP_PROXY
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
 task_dir = os.path.join(os.path.dirname(__file__), "..", "task")
 if not os.path.exists(os.path.join(task_dir, "Dockerfile")):
 raise RuntimeError("Task Dockerfile not found")
 logger.info(f"Building task container image: path={task_dir}")
 try:
 self.client.images.build(
 path=task_dir,
 tag=self.image_name,
 rm=True,
 )
 logger.info("Task image built successfully")
 except APIError as e:
 logger.error(f"Failed to build task image: {e}")
 raise
 async def stop_task(self, task_id: str, force: bool = False) -> bool:
 """Stop a running task container.
 Args:
 task_id: The task ID
 force: Whether to force kill the container
 Returns:
 True if container was stopped, False if not found
 """
 container_id: str | None = self._running_containers.get(task_id)
 if not container_id:
 # Try to find by label
 containers = self.client.containers.list(filters={"label": f"friday.task_id={task_id}"})
 if not containers:
 logger.warning(f"No container found for task: {task_id}")
 return False
 container_id = str(containers[0].id)
 try:
 container = self.client.containers.get(container_id)
 if force:
 container.kill
 else:
 container.stop(timeout=30)
 logger.info(f"Task container stopped: container_id={container_id[:12]}")
 self._running_containers.pop(task_id, None)
 return True
 except APIError as e:
 logger.error(f"Failed to stop container: {e}")
 return False
 async def get_task_status(self, task_id: str) -> Optional[dict[str, Any]]:
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
 container_id = str(container.id) if container.id else ""
 return {
 "container_id": container_id[:12],
 "status": container.status,
 "state": container.attrs.get("State", {}),
 "created": container.attrs.get("Created"),
 }
 async def get_task_logs(self, task_id: str, tail: int = 100) -> Optional[str]:
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
 container_id = str(container.id) if container.id else ""
 logger.debug(f"Removed finished container: {container_id[:12]}")
 except APIError as e:
 logger.warning(f"Failed to remove container: {e}")
 if removed:
 logger.info(f"Cleaned up finished containers: count={removed}")
 return removed
 def get_task_result_file(self, task_id: str) -> Optional[dict[str, Any]]:
 """Read the result file from the transfer directory."""
 result_file = os.path.join(self.transfers_dir, task_id, "result.json")
 if not os.path.exists(result_file):
 return None
 try:
 with open(result_file, "r") as f:
 return json.load(f)
 except Exception as e:
 logger.error(f"Failed to read result file for task {task_id}: {e}")
 return None
# Singleton instance
_scheduler: Optional[TaskScheduler] = None
def get_scheduler -> TaskScheduler:
 """Get the task scheduler singleton."""
 global _scheduler
 if _scheduler is None:
 _scheduler = TaskScheduler
 return _scheduler
