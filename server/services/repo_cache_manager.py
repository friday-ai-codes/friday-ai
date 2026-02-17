"""Repository Cache Manager - Docker volume management for repo bare clones.
This module provides Docker named volume management for storing bare clones of
frequently used repositories, enabling fast reference clones for subsequent
container executions.
"""
from __future__ import annotations
import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any
import docker
import structlog
from django.utils import timezone as dj_timezone
from docker.errors import APIError, ContainerError, NotFound
from system.models import CacheVolumeTracker
logger = structlog.get_logger
class RepoCacheManager:
 """仓库预克隆卷管理。
 职责：
 - 创建/获取 Docker named volume 存储 bare clone
 - 运行临时容器执行 git clone --bare
 - 刷新缓存卷（git fetch --all）
 - 查询卷状态
 """
 CACHE_VOLUME_PREFIX = "friday-repo-"
 CACHE_MOUNT_PATH = "/cache/repo.git"
 def __init__(self) -> None:
 """Initialize the repository cache manager."""
 self.client = docker.from_env
 def get_volume_name(self, repo_url: str) -> str:
 """从仓库 URL 生成确定性卷名（sha256[:12]）。
 Args:
 repo_url: Git repository URL
 Returns:
 Volume name in format: friday-repo-{hash[:12]}
 """
 url_hash = hashlib.sha256(repo_url.encode).hexdigest[:12]
 return f"{self.CACHE_VOLUME_PREFIX}{url_hash}"
 async def ensure_repo_cache(
 self,
 repo_url: str,
 repo_id: str,
 image: str = "friday-task:latest",
 ) -> str | None:
 """确保仓库预克隆卷存在。
 如果卷已存在，直接返回卷名。
 如果不存在，创建卷并运行临时容器执行 bare clone。
 Args:
 repo_url: Git repository URL to clone
 repo_id: Repository identifier for labeling
 image: Docker image to use for cloning
 Returns:
 Volume name if successful, None if failed
 """
 volume_name = self.get_volume_name(repo_url)
 # Check if volume already exists
 try:
 self.client.volumes.get(volume_name)
 logger.info(
 "repo_cache_exists",
 volume_name=volume_name,
 repo_url=repo_url,
 )
 # 更新使用时间跟踪
 await CacheVolumeTracker.objects.filter(
 volume_name=volume_name,
 ).aupdate(last_used_at=dj_timezone.now)
 return volume_name
 except NotFound:
 pass
 # Create volume with labels
 try:
 labels = {
 "friday.repo_url": repo_url,
 "friday.repo_id": repo_id,
 "friday.type": "repo-cache",
 "friday.created": datetime.now(timezone.utc).isoformat,
 }
 self.client.volumes.create(name=volume_name, labels=labels)
 logger.info(
 "repo_cache_volume_created",
 volume_name=volume_name,
 repo_url=repo_url,
 )
 except APIError as e:
 if "already exists" in str(e):
 # Race condition - volume created by another process
 logger.info(
 "repo_cache_volume_race_condition",
 volume_name=volume_name,
 )
 return volume_name
 logger.error(
 "repo_cache_volume_create_failed",
 volume_name=volume_name,
 error=str(e),
 )
 return None
 # Run bare clone in temporary container
 clone_success = await self._run_bare_clone(
 volume_name=volume_name,
 repo_url=repo_url,
 image=image,
 )
 if not clone_success:
 # Clean up volume on failure
 await self.remove_cache(volume_name)
 return None
 # 创建使用跟踪记录
 await CacheVolumeTracker.objects.acreate(
 volume_name=volume_name,
 volume_type="repo",
 repo_url=repo_url,
 )
 return volume_name
 async def _run_bare_clone(
 self,
 volume_name: str,
 repo_url: str,
 image: str,
 ) -> bool:
 """Run bare clone in a temporary container.
 Args:
 volume_name: Docker volume name to mount
 repo_url: Git repository URL to clone
 image: Docker image to use
 Returns:
 True if clone succeeded, False otherwise
 """
 clone_command = f"git clone --bare {repo_url} {self.CACHE_MOUNT_PATH}"
 logger.info(
 "repo_cache_bare_clone_starting",
 volume_name=volume_name,
 repo_url=repo_url,
 )
 try:
 # Run container synchronously in thread pool
 await asyncio.to_thread(
 self.client.containers.run,
 image=image,
 command=["sh", "-c", clone_command],
 volumes={volume_name: {"bind": self.CACHE_MOUNT_PATH, "mode": "rw"}},
 remove=True,
 mem_limit="1g",
 network_mode="bridge",
 )
 logger.info(
 "repo_cache_bare_clone_completed",
 volume_name=volume_name,
 repo_url=repo_url,
 )
 return True
 except ContainerError as e:
 logger.error(
 "repo_cache_bare_clone_failed",
 volume_name=volume_name,
 repo_url=repo_url,
 exit_code=e.exit_status,
 stderr=e.stderr.decode if isinstance(e.stderr, bytes) else (e.stderr or ""),
 )
 return False
 except Exception as e:
 logger.error(
 "repo_cache_bare_clone_error",
 volume_name=volume_name,
 repo_url=repo_url,
 error=str(e),
 )
 return False
 async def refresh_cache(
 self,
 volume_name: str,
 image: str = "friday-task:latest",
 ) -> bool:
 """更新预克隆卷（git fetch --all --prune）。
 Args:
 volume_name: Docker volume name to refresh
 image: Docker image to use
 Returns:
 True if refresh succeeded, False otherwise
 """
 # Verify volume exists
 try:
 self.client.volumes.get(volume_name)
 except NotFound:
 logger.error(
 "repo_cache_refresh_volume_not_found",
 volume_name=volume_name,
 )
 return False
 fetch_command = f"cd {self.CACHE_MOUNT_PATH} && git fetch --all --prune"
 logger.info(
 "repo_cache_refresh_starting",
 volume_name=volume_name,
 )
 try:
 await asyncio.to_thread(
 self.client.containers.run,
 image=image,
 command=["sh", "-c", fetch_command],
 volumes={volume_name: {"bind": self.CACHE_MOUNT_PATH, "mode": "rw"}},
 remove=True,
 mem_limit="512m",
 network_mode="bridge",
 )
 logger.info(
 "repo_cache_refresh_completed",
 volume_name=volume_name,
 )
 return True
 except ContainerError as e:
 logger.error(
 "repo_cache_refresh_failed",
 volume_name=volume_name,
 exit_code=e.exit_status,
 stderr=e.stderr.decode if isinstance(e.stderr, bytes) else (e.stderr or ""),
 )
 return False
 except Exception as e:
 logger.error(
 "repo_cache_refresh_error",
 volume_name=volume_name,
 error=str(e),
 )
 return False
 def get_cache_path(self, volume_name: str) -> str:
 """返回容器内挂载路径（只读）。
 Args:
 volume_name: Docker volume name (unused, path is constant)
 Returns:
 Mount path inside container: /cache/repo.git
 """
 return self.CACHE_MOUNT_PATH
 async def list_cache_volumes(self) -> list[dict[str, Any]]:
 """列出所有 friday-repo-* 缓存卷及其元数据。
 Returns:
 List of volume info dicts with name, labels, and created timestamp
 """
 try:
 volumes = await asyncio.to_thread(
 self.client.volumes.list,
 filters={"name": self.CACHE_VOLUME_PREFIX},
 )
 result: list[dict[str, Any]] =
 for volume in volumes:
 if volume.name.startswith(self.CACHE_VOLUME_PREFIX):
 result.append({
 "name": volume.name,
 "labels": volume.attrs.get("Labels", {}),
 "created": volume.attrs.get("CreatedAt"),
 "mountpoint": volume.attrs.get("Mountpoint"),
 })
 logger.info(
 "repo_cache_volumes_listed",
 count=len(result),
 )
 return result
 except Exception as e:
 logger.error(
 "repo_cache_list_failed",
 error=str(e),
 )
 return
 async def remove_cache(self, volume_name: str) -> bool:
 """删除缓存卷（需要无容器使用）。
 Args:
 volume_name: Docker volume name to remove
 Returns:
 True if removal succeeded, False otherwise
 """
 try:
 volume = self.client.volumes.get(volume_name)
 await asyncio.to_thread(volume.remove)
 # 清理跟踪记录
 await CacheVolumeTracker.objects.filter(volume_name=volume_name).adelete
 logger.info(
 "repo_cache_removed",
 volume_name=volume_name,
 )
 return True
 except NotFound:
 logger.warning(
 "repo_cache_remove_not_found",
 volume_name=volume_name,
 )
 return True # Already removed
 except APIError as e:
 logger.error(
 "repo_cache_remove_failed",
 volume_name=volume_name,
 error=str(e),
 )
 return False
