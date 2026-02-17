"""Container Executor Service - Docker container execution for workflow nodes.
This module provides a generic Docker container execution service that can be used
by workflow nodes (like CodeImplementNode) to run tasks in isolated containers.
Extracted from the original TaskScheduler (server/services/scheduler.py) to support
the Task -> Workflow migration.
"""
import asyncio
import os
import platform
import time
from dataclasses import dataclass, field
from typing import Any
import docker
import structlog
from docker.errors import APIError, ImageNotFound, NotFound
logger = structlog.get_logger
@dataclass
class ExecutionRequest:
 """Container execution request."""
 execution_id: str # WorkflowExecution.id (for directory isolation)
 node_execution_id: str # NodeExecution.id (for callback identification)
 image: str = "friday-task:latest"
 environment: dict = field(default_factory=dict)
 volumes: dict = field(default_factory=dict)
 timeout: int = 3600 # Default 1 hour
 callback_url: str = ""
 # Resource limits
 mem_limit: str = "2g"
 cpu_quota: int = 100000 # 1 CPU
 # Container naming
 container_name_prefix: str = "friday-workflow"
 # Labels for tracking
 labels: dict = field(default_factory=dict)
@dataclass
class ExecutionResult:
 """Container execution result."""
 success: bool
 status: str # completed, failed, timeout, cancelled
 output: dict = field(default_factory=dict)
 logs: str = ""
 error: str | None = None
 duration: float = 0.0
 container_id: str = ""
 exit_code: int | None = None
class ContainerExecutor:
 """Docker container execution service.
 Provides generic container execution capabilities for workflow nodes.
 Handles network detection, environment configuration, and container lifecycle.
 """
 # Docker network names to detect (Compose mode)
 NETWORK_NAMES = ["friday-ai_friday-network", "friday-network"]
 def __init__(self):
 """Initialize the container executor."""
 self.client = docker.from_env
 self._docker_network = self._detect_docker_network
 self._running_containers: dict[str, str] = {} # execution_id -> container_id
 # Data directories
 self.data_dir = os.path.abspath(
 os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
 )
 self.transfers_dir = os.path.join(self.data_dir, "transfers")
 os.makedirs(self.transfers_dir, exist_ok=True)
 if self._docker_network:
 logger.info(
 "container_executor_initialized",
 network_mode="compose",
 network=self._docker_network,
 )
 else:
 logger.info("container_executor_initialized", network_mode="host")
 def _detect_docker_network(self) -> str | None:
 """Detect Docker Compose network for container communication."""
 try:
 for network_name in self.NETWORK_NAMES:
 networks = self.client.networks.list(names=[network_name])
 if networks:
 logger.info("docker_network_detected", network=network_name)
 return network_name
 except Exception as e:
 logger.warning("docker_network_detection_failed", error=str(e))
 return None
 def _get_host_callback_url(self, port: int = 8000) -> str:
 """Get callback URL for host networking mode (local development)."""
 system = platform.system.lower
 if system in ("darwin", "windows"):
 # macOS/Windows: use host.docker.internal
 return f"http://host.docker.internal:{port}/api"
 else:
 # Linux: use default gateway IP
 return f"http://172.17.0.1:{port}/api"
 def _build_callback_url(self, port: int = 8000) -> str:
 """Build the appropriate callback URL based on network mode."""
 if self._docker_network:
 # Compose mode: use container name
 return f"http://friday-server:{port}/api/containers/callback/"
 else:
 # Local development: use host networking
 base = self._get_host_callback_url(port)
 return f"{base}/containers/callback/"
 def _build_run_kwargs(self, request: ExecutionRequest) -> dict[str, Any]:
 """Build docker run kwargs from execution request."""
 kwargs: dict[str, Any] = {
 "detach": True,
 "environment": request.environment,
 "mem_limit": request.mem_limit,
 "cpu_period": 100000,
 "cpu_quota": request.cpu_quota,
 "auto_remove": False, # Keep container for debugging
 "labels": {
 "friday.execution_id": request.execution_id,
 "friday.node_execution_id": request.node_execution_id,
 **request.labels,
 },
 }
 # Container name
 container_name = f"{request.container_name_prefix}-{request.node_execution_id[:8]}"
 kwargs["name"] = container_name
 # Volumes
 if request.volumes:
 kwargs["volumes"] = request.volumes
 # Network configuration
 if self._docker_network:
 kwargs["network"] = self._docker_network
 else:
 # Local development: add host.docker.internal mapping
 kwargs["extra_hosts"] = {"host.docker.internal": "host-gateway"}
 return kwargs
 async def start_execution(self, request: ExecutionRequest) -> str:
 """Start a container execution.
 Args:
 request: Execution request with container configuration
 Returns:
 Container ID
 Raises:
 RuntimeError: If container fails to start
 """
 logger.info(
 "starting_execution",
 execution_id=request.execution_id,
 node_execution_id=request.node_execution_id,
 image=request.image,
 )
 # Prepare transfer directory for this execution
 transfer_dir = os.path.join(self.transfers_dir, request.execution_id)
 os.makedirs(transfer_dir, exist_ok=True)
 # Ensure image exists
 await self._ensure_image(request.image)
 # Build environment with callback URL
 env = request.environment.copy
 env["FRIDAY_CALLBACK_URL"] = request.callback_url or self._build_callback_url
 env["FRIDAY_EXECUTION_ID"] = request.execution_id
 env["FRIDAY_NODE_EXECUTION_ID"] = request.node_execution_id
 env["FRIDAY_OUTPUT_DIR"] = "/app/transfer"
 # Add transfer directory to volumes
 volumes = request.volumes.copy if request.volumes else {}
 volumes[transfer_dir] = {"bind": "/app/transfer", "mode": "rw"}
 # Build run kwargs
 run_kwargs = self._build_run_kwargs(request)
 run_kwargs["environment"] = env
 run_kwargs["volumes"] = volumes
 try:
 # Remove existing container with same name if exists
 container_name = run_kwargs.get("name")
 if container_name:
 await self._remove_container_by_name(container_name)
 # Start container
 container = await asyncio.to_thread(
 self.client.containers.run, request.image, **run_kwargs
 )
 container_id = str(container.id)
 self._running_containers[request.execution_id] = container_id
 logger.info(
 "container_started",
 container_id=container_id[:12],
 execution_id=request.execution_id,
 )
 return container_id
 except ImageNotFound:
 logger.error("image_not_found", image=request.image)
 raise RuntimeError(f"Container image not found: {request.image}")
 except APIError as e:
 logger.error("docker_api_error", error=str(e))
 raise RuntimeError(f"Failed to start container: {e}")
 async def wait_for_completion(self, container_id: str, timeout: int = 3600) -> ExecutionResult:
 """Wait for container to complete.
 Args:
 container_id: Docker container ID
 timeout: Maximum wait time in seconds
 Returns:
 ExecutionResult with status and output
 """
 start_time = time.time
 try:
 container = self.client.containers.get(container_id)
 except NotFound:
 return ExecutionResult(
 success=False,
 status="not_found",
 error="Container not found",
 container_id=container_id,
 )
 try:
 # Wait for container to exit
 result = await asyncio.wait_for(asyncio.to_thread(container.wait), timeout=timeout)
 duration = time.time - start_time
 logs = await self.get_logs(container_id, tail=500)
 exit_code = result.get("StatusCode", -1)
 if exit_code == 0:
 # Try to read result file
 output = self._read_result_file(container_id) or {}
 return ExecutionResult(
 success=True,
 status="completed",
 output=output,
 logs=logs,
 duration=duration,
 container_id=container_id,
 exit_code=exit_code,
 )
 else:
 return ExecutionResult(
 success=False,
 status="failed",
 error=f"Container exited with code {exit_code}",
 logs=logs,
 duration=duration,
 container_id=container_id,
 exit_code=exit_code,
 )
 except asyncio.TimeoutError:
 await self.stop_execution(container_id, force=True)
 return ExecutionResult(
 success=False,
 status="timeout",
 error=f"Execution timed out after {timeout}s",
 duration=float(timeout),
 container_id=container_id,
 )
 async def stop_execution(self, container_id: str, force: bool = False) -> bool:
 """Stop a running container.
 Args:
 container_id: Docker container ID
 force: If True, kill immediately; otherwise graceful stop
 Returns:
 True if container was stopped, False if not found
 """
 try:
 container = self.client.containers.get(container_id)
 if force:
 await asyncio.to_thread(container.kill)
 else:
 await asyncio.to_thread(container.stop, timeout=30)
 logger.info("container_stopped", container_id=container_id[:12], force=force)
 return True
 except NotFound:
 logger.warning("container_not_found", container_id=container_id[:12])
 return False
 except Exception as e:
 logger.error("stop_container_failed", container_id=container_id[:12], error=str(e))
 return False
 async def get_logs(self, container_id: str, tail: int = 100) -> str:
 """Get container logs.
 Args:
 container_id: Docker container ID
 tail: Number of lines to return
 Returns:
 Log content as string
 """
 try:
 container = self.client.containers.get(container_id)
 logs = await asyncio.to_thread(container.logs, tail=tail, timestamps=True)
 return logs.decode("utf-8", errors="replace")
 except NotFound:
 return ""
 except Exception as e:
 logger.warning("get_logs_failed", container_id=container_id[:12], error=str(e))
 return ""
 async def get_status(self, container_id: str) -> dict[str, Any] | None:
 """Get container status.
 Args:
 container_id: Docker container ID
 Returns:
 Status dict or None if not found
 """
 try:
 container = self.client.containers.get(container_id)
 return {
 "container_id": container_id[:12],
 "status": container.status,
 "state": container.attrs.get("State", {}),
 "created": container.attrs.get("Created"),
 }
 except NotFound:
 return None
 async def cleanup_finished_containers(self, older_than_hours: int = 24) -> int:
 """Clean up finished containers.
 Args:
 older_than_hours: Only cleanup containers older than this
 Returns:
 Number of containers removed
 """
 containers = self.client.containers.list(
 all=True,
 filters={
 "label": "friday.execution_id",
 "status": "exited",
 },
 )
 removed = 0
 for container in containers:
 try:
 await asyncio.to_thread(container.remove, v=True)
 removed += 1
 except Exception as e:
 logger.warning(
 "cleanup_container_failed",
 container_id=str(container.id)[:12] if container.id else "unknown",
 error=str(e),
 )
 if removed:
 logger.info("containers_cleaned_up", count=removed)
 return removed
 async def _ensure_image(self, image: str) -> None:
 """Ensure container image exists."""
 try:
 self.client.images.get(image)
 except ImageNotFound:
 logger.warning("image_not_found_will_build", image=image)
 await self._build_image(image)
 async def _build_image(self, image: str) -> None:
 """Build container image if Dockerfile exists."""
 # Try to find Dockerfile in task directory
 task_dir = os.path.join(os.path.dirname(self.data_dir), "task")
 dockerfile_path = os.path.join(task_dir, "Dockerfile")
 if not os.path.exists(dockerfile_path):
 raise RuntimeError(
 f"Image {image} not found and Dockerfile not available at {dockerfile_path}"
 )
 logger.info("building_image", image=image, path=task_dir)
 try:
 await asyncio.to_thread(
 self.client.images.build,
 path=task_dir,
 tag=image,
 rm=True,
 )
 logger.info("image_built", image=image)
 except APIError as e:
 logger.error("build_image_failed", image=image, error=str(e))
 raise RuntimeError(f"Failed to build image {image}: {e}")
 async def _remove_container_by_name(self, name: str) -> None:
 """Remove container by name if exists."""
 try:
 container = self.client.containers.get(name)
 await asyncio.to_thread(container.remove, force=True)
 logger.debug("removed_existing_container", name=name)
 except NotFound:
 pass
 def _read_result_file(self, container_id: str) -> dict | None:
 """Read result file from transfer directory."""
 # Find execution_id from running containers
 execution_id = None
 for exec_id, cont_id in self._running_containers.items:
 if cont_id == container_id:
 execution_id = exec_id
 break
 if not execution_id:
 return None
 result_file = os.path.join(self.transfers_dir, execution_id, "result.json")
 if not os.path.exists(result_file):
 return None
 try:
 import json
 with open(result_file) as f:
 return json.load(f)
 except Exception as e:
 logger.warning("read_result_file_failed", error=str(e))
 return None
 def get_result_from_file(self, execution_id: str) -> dict | None:
 """Read result file directly by execution ID.
 Args:
 execution_id: Workflow execution ID
 Returns:
 Result dict or None if not found
 """
 result_file = os.path.join(self.transfers_dir, execution_id, "result.json")
 if not os.path.exists(result_file):
 return None
 try:
 import json
 with open(result_file) as f:
 return json.load(f)
 except Exception as e:
 logger.warning("read_result_file_failed", execution_id=execution_id, error=str(e))
 return None
# Singleton instance
_executor: ContainerExecutor | None = None
def get_container_executor -> ContainerExecutor:
 """Get the container executor singleton."""
 global _executor
 if _executor is None:
 _executor = ContainerExecutor
 return _executor
