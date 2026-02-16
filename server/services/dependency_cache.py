"""Dependency Cache Manager - Docker volume management for pre-installed dependencies.
This module provides Docker named volume management for caching pre-installed
dependencies based on lock files (requirements.txt, package-lock.json, pnpm-lock.yaml),
enabling fast dependency restoration for subsequent container executions.
"""
from __future__ import annotations
import asyncio
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import docker
import structlog
from django.utils import timezone as dj_timezone
from docker.errors import APIError, NotFound
from system.models import CacheVolumeTracker
logger = structlog.get_logger
class PackageManager(Enum):
 """Supported package managers."""
 PIP = "pip"
 NPM = "npm"
 PNPM = "pnpm"
@dataclass
class LockFileInfo:
 """Lock file information."""
 manager: PackageManager
 content_hash: str
 file_path: str
class DependencyCacheManager:
 """依赖预安装卷管理。
 职责：
 - 检测项目 lock 文件类型（requirements.txt, package-lock.json, pnpm-lock.yaml）
 - 基于 lock 文件 hash 创建 Docker named volume
 - 运行临时容器预安装依赖
 - 查询和清理缓存卷
 """
 CACHE_VOLUME_PREFIX = "friday-deps-"
 # Lock file detection with priority (higher index = higher priority)
 LOCK_FILES: dict[str, PackageManager] = {
 "requirements.txt": PackageManager.PIP,
 "requirements-dev.txt": PackageManager.PIP,
 "package-lock.json": PackageManager.NPM,
 "pnpm-lock.yaml": PackageManager.PNPM,
 }
 # Detection priority: pnpm > npm > pip
 DETECTION_PRIORITY: list[str] = [
 "pnpm-lock.yaml",
 "package-lock.json",
 "requirements.txt",
 "requirements-dev.txt",
 ]
 # Mount paths for each package manager
 MOUNT_PATHS: dict[PackageManager, str] = {
 PackageManager.PIP: "/deps/site-packages",
 PackageManager.NPM: "/deps/node_modules",
 PackageManager.PNPM: "/deps/node_modules",
 }
 def __init__(self) -> None:
 """Initialize the dependency cache manager."""
 self.client = docker.from_env
 def get_volume_name(self, repo_id: str, lock_hash: str) -> str:
 """生成卷名：friday-deps-{repo_id[:8]}-{lock_hash[:8]}。
 Args:
 repo_id: Repository identifier
 lock_hash: SHA256 hash of lock file content
 Returns:
 Volume name in format: friday-deps-{repo_id[:8]}-{lock_hash[:8]}
 """
 return f"{self.CACHE_VOLUME_PREFIX}{repo_id[:8]}-{lock_hash[:8]}"
 def compute_lock_hash(self, lock_file_path: str) -> str:
 """计算 lock 文件的 SHA256 hash。
 Args:
 lock_file_path: Path to the lock file
 Returns:
 SHA256 hash of the file content
 """
 with open(lock_file_path, "rb") as f:
 return hashlib.sha256(f.read).hexdigest
 def detect_lock_file(self, workspace_path: str) -> LockFileInfo | None:
 """检测工作区的 lock 文件类型和内容 hash。
 优先级：pnpm-lock.yaml > package-lock.json > requirements.txt
 Args:
 workspace_path: Path to the workspace directory
 Returns:
 LockFileInfo if a lock file is found, None otherwise
 """
 for lock_file_name in self.DETECTION_PRIORITY:
 lock_file_path = os.path.join(workspace_path, lock_file_name)
 if os.path.exists(lock_file_path):
 manager = self.LOCK_FILES[lock_file_name]
 content_hash = self.compute_lock_hash(lock_file_path)
 logger.info(
 "deps_cache_lock_file_detected",
 lock_file=lock_file_name,
 manager=manager.value,
 content_hash=content_hash[:12],
 )
 return LockFileInfo(
 manager=manager,
 content_hash=content_hash,
 file_path=lock_file_path,
 )
 logger.info(
 "deps_cache_no_lock_file",
 workspace_path=workspace_path,
 )
 return None
 async def ensure_deps_cache(
 self,
 repo_id: str,
 lock_info: LockFileInfo,
 image: str = "friday-task:latest",
 ) -> str | None:
 """确保依赖缓存卷存在。
 如果卷已存在（hash 匹配），直接返回卷名。
 如果不存在，创建卷并运行临时容器安装依赖。
 Args:
 repo_id: Repository identifier
 lock_info: Lock file information
 image: Docker image to use for installation
 Returns:
 Volume name if successful, None if failed
 """
 volume_name = self.get_volume_name(repo_id, lock_info.content_hash)
 # Check if volume already exists
 try:
 volume = self.client.volumes.get(volume_name)
 logger.info(
 "deps_cache_exists",
 volume_name=volume_name,
 repo_id=repo_id,
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
 "friday.repo_id": repo_id,
 "friday.lock_hash": lock_info.content_hash,
 "friday.manager": lock_info.manager.value,
 "friday.type": "deps-cache",
 "friday.created": datetime.now(timezone.utc).isoformat,
 }
 self.client.volumes.create(name=volume_name, labels=labels)
 logger.info(
 "deps_cache_volume_created",
 volume_name=volume_name,
 repo_id=repo_id,
 manager=lock_info.manager.value,
 )
 except APIError as e:
 if "already exists" in str(e):
 # Race condition - volume created by another process
 logger.info(
 "deps_cache_volume_race_condition",
 volume_name=volume_name,
 )
 return volume_name
 logger.error(
 "deps_cache_volume_create_failed",
 volume_name=volume_name,
 error=str(e),
 )
 return None
 # Run dependency installation in temporary container
 install_success = await self._run_install(
 volume_name=volume_name,
 lock_info=lock_info,
 image=image,
 )
 if not install_success:
 # Clean up volume on failure
 await self.remove_deps_cache(volume_name)
 return None
 # 创建使用跟踪记录
 await CacheVolumeTracker.objects.acreate(
 volume_name=volume_name,
 volume_type="deps",
 repo_url="",
 )
 return volume_name
 def _get_install_command(self, manager: PackageManager, lock_file_path: str) -> str:
 """返回对应包管理器的安装命令。
 Args:
 manager: Package manager type
 lock_file_path: Path to lock file (for pip)
 Returns:
 Shell command to install dependencies
 """
 lock_file_name = os.path.basename(lock_file_path)
 if manager == PackageManager.PIP:
 return f"pip install -r /workspace/{lock_file_name} --target /deps/site-packages"
 elif manager == PackageManager.NPM:
 return "npm ci --prefix /deps"
 elif manager == PackageManager.PNPM:
 return "pnpm install --frozen-lockfile --store-dir /deps/.pnpm-store"
 else:
 raise ValueError(f"Unsupported package manager: {manager}")
 def get_mount_path(self, manager: PackageManager) -> str:
 """返回容器内依赖挂载路径。
 Args:
 manager: Package manager type
 Returns:
 Mount path inside container
 """
 return self.MOUNT_PATHS[manager]
 async def _run_install(
 self,
 volume_name: str,
 lock_info: LockFileInfo,
 image: str,
 ) -> bool:
 """Run dependency installation in a temporary container.
 Args:
 volume_name: Docker volume name to mount
 lock_info: Lock file information
 image: Docker image to use
 Returns:
 True if installation succeeded, False otherwise
 """
 install_command = self._get_install_command(
 lock_info.manager,
 lock_info.file_path,
 )
 # Mount lock file directory as /workspace
 lock_dir = os.path.dirname(lock_info.file_path)
 mount_path = self.get_mount_path(lock_info.manager)
 logger.info(
 "deps_cache_install_starting",
 volume_name=volume_name,
 manager=lock_info.manager.value,
 command=install_command,
 )
 try:
 await asyncio.to_thread(
 self.client.containers.run,
 image=image,
 command=["sh", "-c", install_command],
 volumes={
 volume_name: {"bind": "/deps", "mode": "rw"},
 lock_dir: {"bind": "/workspace", "mode": "ro"},
 },
 remove=True,
 mem_limit="2g",
 network_mode="bridge",
 )
 logger.info(
 "deps_cache_install_completed",
 volume_name=volume_name,
 manager=lock_info.manager.value,
 )
 return True
 except docker.errors.ContainerError as e:
 logger.error(
 "deps_cache_install_failed",
 volume_name=volume_name,
 exit_code=e.exit_status,
 stderr=e.stderr.decode if e.stderr else "",
 )
 return False
 except Exception as e:
 logger.error(
 "deps_cache_install_error",
 volume_name=volume_name,
 error=str(e),
 )
 return False
 async def list_deps_volumes(self, repo_id: str | None = None) -> list[dict[str, Any]]:
 """列出依赖缓存卷，可按 repo_id 过滤。
 Args:
 repo_id: Optional repository ID to filter by
 Returns:
 List of volume info dicts
 """
 try:
 volumes = await asyncio.to_thread(
 self.client.volumes.list,
 filters={"name": self.CACHE_VOLUME_PREFIX},
 )
 result: list[dict[str, Any]] =
 for volume in volumes:
 if not volume.name.startswith(self.CACHE_VOLUME_PREFIX):
 continue
 labels = volume.attrs.get("Labels", {})
 # Filter by repo_id if specified
 if repo_id and labels.get("friday.repo_id") != repo_id:
 continue
 result.append({
 "name": volume.name,
 "labels": labels,
 "repo_id": labels.get("friday.repo_id"),
 "lock_hash": labels.get("friday.lock_hash"),
 "manager": labels.get("friday.manager"),
 "created": volume.attrs.get("CreatedAt"),
 })
 logger.info(
 "deps_cache_volumes_listed",
 count=len(result),
 repo_id=repo_id,
 )
 return result
 except Exception as e:
 logger.error(
 "deps_cache_list_failed",
 error=str(e),
 )
 return
 async def remove_deps_cache(self, volume_name: str) -> bool:
 """删除依赖缓存卷。
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
 "deps_cache_removed",
 volume_name=volume_name,
 )
 return True
 except NotFound:
 logger.warning(
 "deps_cache_remove_not_found",
 volume_name=volume_name,
 )
 return True # Already removed
 except APIError as e:
 logger.error(
 "deps_cache_remove_failed",
 volume_name=volume_name,
 error=str(e),
 )
 return False
