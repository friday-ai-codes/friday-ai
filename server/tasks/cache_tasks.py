"""缓存管理后台任务。
提供仓库预克隆和依赖缓存的预热、刷新、清理功能。
"""
from __future__ import annotations
from datetime import timedelta
import structlog
from django.utils import timezone
from services.dependency_cache import DependencyCacheManager
from services.repo_cache_manager import RepoCacheManager
from system.models import CacheVolumeTracker
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
 _cutoff = timezone.now - timedelta(hours=max_age_hours)
 results: dict[str, bool] = {}
 for vol in volumes:
 # 检查 labels 中的 friday.created 时间戳
 labels = vol.get("labels", {})
 _created_str = labels.get("friday.created", "")
 # 简化处理：刷新所有卷（后续可增加时间过滤）
 success = await manager.refresh_cache(vol["name"], image)
 results[vol["name"]] = success
 if success:
 await CacheVolumeTracker.objects.filter(
 volume_name=vol["name"],
 ).aupdate(last_used_at=timezone.now)
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
 使用两阶段清理策略：先标记过期，再批量删除。
 基于 CacheVolumeTracker.last_used_at 判断过期，
 而非 Docker volume label 的创建时间。
 Args:
 older_than_days: 清理超过此天数未使用的卷
 dry_run: 仅标记过期并返回待清理列表，不实际删除
 Returns:
 已删除（或待删除）的卷名列表
 """
 repo_manager = RepoCacheManager
 deps_manager = DependencyCacheManager
 cutoff = timezone.now - timedelta(days=older_than_days)
 # Step 1: 标记过期
 expired_count = await CacheVolumeTracker.objects.filter(
 last_used_at__lt=cutoff,
 is_expired=False,
 ).aupdate(is_expired=True)
 logger.info(
 "cache_volumes_marked_expired",
 newly_marked=expired_count,
 cutoff_days=older_than_days,
 )
 # 获取所有已标记过期的卷
 expired_trackers = [
 tracker
 async for tracker in CacheVolumeTracker.objects.filter(is_expired=True)
 ]
 if dry_run:
 names = [t.volume_name for t in expired_trackers]
 logger.info(
 "cache_volumes_prune_dry_run",
 count=len(names),
 )
 return names
 # Step 2: 批量清理已标记的卷
 pruned: list[str] =
 for tracker in expired_trackers:
 if tracker.volume_type == "repo":
 success = await repo_manager.remove_cache(tracker.volume_name)
 else:
 success = await deps_manager.remove_deps_cache(tracker.volume_name)
 if success:
 # remove_cache / remove_deps_cache 内部已调用 adelete，
 # 但若记录仍存在则再次删除（幂等）
 await CacheVolumeTracker.objects.filter(
 pk=tracker.pk,
 ).adelete
 pruned.append(tracker.volume_name)
 else:
 logger.warning(
 "cache_volume_prune_failed",
 volume_name=tracker.volume_name,
 volume_type=tracker.volume_type,
 )
 logger.info(
 "cache_volumes_pruned",
 pruned_count=len(pruned),
 older_than_days=older_than_days,
 )
 return pruned
