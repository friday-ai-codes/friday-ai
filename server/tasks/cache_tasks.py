"""缓存管理后台任务。
提供仓库预克隆和依赖缓存的预热、刷新、清理功能。
"""
from __future__ import annotations
from datetime import timedelta
import structlog
from django.utils import timezone
from services.dependency_cache import DependencyCacheManager
from services.repo_cache_manager import RepoCacheManager
logger = structlog.get_logger(__name__)
async def warmup_repo_cache(
 repo_url: str,
 repo_id: str,
 image: str = "friday-task:latest",
) -> str | None:
 """预热单个仓库缓存。
 Args:
 repo_url: 仓库 URL
 repo_id: 仓库标识（用于日志）
 image: 用于 clone 的 Docker 镜像
 Returns:
 卷名（成功）或 None（失败）
 """
 manager = RepoCacheManager
 logger.info(
 "warmup_repo_cache_started",
 repo_url=repo_url[:50],
 repo_id=repo_id,
 )
 return await manager.ensure_repo_cache(repo_url, repo_id, image)
async def refresh_repo_caches(
 max_age_hours: int = 24,
 image: str = "friday-task:latest",
) -> dict[str, bool]:
 """刷新所有超过指定时间的仓库缓存。
 Args:
 max_age_hours: 超过此小时数的缓存需要刷新
 image: 用于 fetch 的 Docker 镜像
 Returns:
 {volume_name: success} 映射
 """
 manager = RepoCacheManager
 volumes = await manager.list_cache_volumes
 cutoff = timezone.now - timedelta(hours=max_age_hours)
 results: dict[str, bool] = {}
 for vol in volumes:
 # 检查 labels 中的 friday.created 时间戳
 labels = vol.get("labels", {})
 created_str = labels.get("friday.created", "")
 # 简化处理：刷新所有卷（后续可增加时间过滤）
 success = await manager.refresh_cache(vol["name"], image)
 results[vol["name"]] = success
 logger.info(
 "repo_caches_refreshed",
 total=len(volumes),
 succeeded=sum(1 for v in results.values if v),
 failed=sum(1 for v in results.values if not v),
 )
 return results
async def prune_cache_volumes(
 older_than_days: int = 7,
 dry_run: bool = False,
) -> list[str]:
 """清理过期的缓存卷。
 Args:
 older_than_days: 清理超过此天数未使用的卷
 dry_run: 仅返回待清理列表，不实际删除
 Returns:
 已删除（或待删除）的卷名列表
 """
 repo_manager = RepoCacheManager
 deps_manager = DependencyCacheManager
 pruned: list[str] =
 cutoff = timezone.now - timedelta(days=older_than_days)
 # 清理 repo 缓存
 repo_volumes = await repo_manager.list_cache_volumes
 for vol in repo_volumes:
 # TODO: 检查最后使用时间（需要额外跟踪机制）
 # 当前简化：基于创建时间
 labels = vol.get("labels", {})
 created_str = labels.get("friday.created", "")
 # 如果无法解析创建时间，跳过
 if not created_str:
 continue
 if not dry_run:
 success = await repo_manager.remove_cache(vol["name"])
 if success:
 pruned.append(vol["name"])
 else:
 pruned.append(vol["name"])
 # 清理 deps 缓存
 deps_volumes = await deps_manager.list_deps_volumes
 for vol in deps_volumes:
 if not dry_run:
 success = await deps_manager.remove_deps_cache(vol["name"])
 if success:
 pruned.append(vol["name"])
 else:
 pruned.append(vol["name"])
 logger.info(
 "cache_volumes_pruned",
 pruned_count=len(pruned),
 dry_run=dry_run,
 older_than_days=older_than_days,
 )
 return pruned
