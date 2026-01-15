"""Task Scheduler Service - Manages Docker containers for task execution."""
import os
from typing import Any
import docker
import structlog
from docker.errors import APIError, ImageNotFound
from friday.config import get_settings
from friday.models.task import Task
logger = structlog.get_logger
class TaskScheduler:
 """Scheduler for running task containers."""
 def __init__(self):
 """Initialize the task scheduler."""
 self.settings = get_settings
 self.client = docker.from_env
 self.image_name = "friday-task:latest"
 self._running_containers: dict[str, str] = {} # task_id -> container_id
 async def start_task(
 self,
 task: Task,
 repo_url: str,
 branch: str,
 git_credentials: dict[str, str],
 mode: str = "plan",
 ) -> str:
 """Start a container for the given task.
 Args:
 task: The task to execute
 repo_url: Git repository URL
 branch: Git branch name
 git_credentials: Dict with git_ssh_key or git_access_token
 mode: "plan" or "execute"
 Returns:
 Container ID
 """
 log = logger.bind(task_id=task.id, project_id=task.project_id, mode=mode)
 log.info("Starting task container")
 # Build environment variables for the container
 env = self._build_env(task, repo_url, branch, git_credentials, mode)
 try:
 # Ensure image exists
 await self._ensure_image
 # Run container
 container = self.client.containers.run(
 self.image_name,
 detach=True,
 environment=env,
 name=f"friday-task-{task.id}",
 labels={
 "friday.task_id": str(task.id),
 "friday.project_id": str(task.project_id),
 "friday.mode": mode,
 },
 # Resource limits
 mem_limit="2g",
 cpu_period=100000,
 cpu_quota=100000, # 1 CPU
 # Network
 network_mode="bridge",
 # Volumes for persistence
 volumes={
 f"friday-sessions-{task.id}": {
 "bind": "/app/sessions",
 "mode": "rw",
 },
 },
 # Auto-remove when done
 auto_remove=False,
 )
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
 ) -> dict[str, str]:
 """Build environment variables for the task container."""
 settings = self.settings
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
 "FRIDAY_TASK_CLAUDE_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
 # Callback configuration
 "FRIDAY_TASK_CALLBACK_URL": f"http://host.docker.internal:{settings.PORT}/api/v1",
 "FRIDAY_TASK_CALLBACK_TOKEN": "", # TODO: Add internal auth
 }
 # Add git credentials
 if git_credentials.get("ssh_key"):
 env["FRIDAY_TASK_GIT_AUTH_TYPE"] = "ssh"
 env["FRIDAY_TASK_GIT_SSH_KEY"] = git_credentials["ssh_key"]
 elif git_credentials.get("access_token"):
 env["FRIDAY_TASK_GIT_AUTH_TYPE"] = "token"
 env["FRIDAY_TASK_GIT_ACCESS_TOKEN"] = git_credentials["access_token"]
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
