"""索引新鲜度服务层（Phase / ）。
提供：
- compute_freshness_status: 三态分级（fresh/stale/unknown）
- update_behind_commits_for_stale_repos: 对 STALE 仓库计算 commit 差值并缓存
- _calculate_commit_distance: 使用本地 clone 执行 git rev-list --count 计算差值
"""
from __future__ import annotations
import asyncio
from typing import Literal
import structlog
from django.conf import settings
from django.utils import timezone
from repositories.models import Repository
logger = structlog.get_logger(__name__)
FreshnessStatus = Literal["fresh", "stale", "unknown"]
def compute_freshness_status(repo: Repository) -> FreshnessStatus:
 """三态分级：FRESH / STALE / UNKNOWN。
 决策表：
 remote_head_sha 空 OR remote_head_checked_at None → unknown
 last_indexed_commit_sha 空 → unknown
 last_indexed_commit_sha == remote_head_sha → fresh
 其余 → stale
 """
 if not repo.remote_head_sha or repo.remote_head_checked_at is None:
 return "unknown"
 if not repo.last_indexed_commit_sha:
 return "unknown"
 if repo.last_indexed_commit_sha == repo.remote_head_sha:
 return "fresh"
 return "stale"
async def update_behind_commits_for_stale_repos -> None:
 """：对所有 STALE 仓库计算 git rev-list --count local..remote 并缓存。
 在 poll_repository_updates 完成后由 calculate_behind_commits job 串联触发。
 失败时只记录 warning，不中断其他仓库计算。
 """
 repos = [
 r
 async for r in Repository.objects.filter(
 is_deleted=False,
 auto_index_enabled=True,
 ).exclude(remote_head_sha="").exclude(last_indexed_commit_sha="")
 ]
 for repo in repos:
 if compute_freshness_status(repo) != "stale":
 continue
 try:
 count = await _calculate_commit_distance(repo)
 if count is not None:
 await Repository.objects.filter(id=repo.id).aupdate(
 behind_commits=count,
 behind_commits_calculated_at=timezone.now,
 )
 except Exception:
 logger.warning(
 "behind_commits_calculation_failed",
 repo_id=str(repo.id),
 git_url=repo.git_url,
 )
async def _calculate_commit_distance(repo: Repository) -> int | None:
 """计算 local..remote 之间的 commit 数（，Q-03 用户裁决本 phase 实现）。
 策略：使用 Friday 已 clone 的本地仓库（settings.REPO_CLONE_DIR/{id}/），
 先 shallow fetch 拉取远端最新 100 个 commit，再用 git rev-list --count 计算差值。
 若仓库未本地 clone 则返回 None（前端文案降级为"本地与远端 HEAD 不一致"）。
 """
 if not repo.last_indexed_commit_sha or not repo.remote_head_sha:
 return None
 if repo.last_indexed_commit_sha == repo.remote_head_sha:
 return 0
 local_repo_path = settings.REPO_CLONE_DIR / str(repo.id)
 if not local_repo_path.exists:
 logger.info(
 "behind_commits_no_local_clone",
 repo_id=str(repo.id),
 )
 return None
 # shallow fetch 拉取远端最新 100 个 commit（减少 IO）
 fetch_proc = await asyncio.create_subprocess_exec(
 "git",
 "-C",
 str(local_repo_path),
 "fetch",
 "--depth=100",
 "origin",
 repo.default_branch or "main",
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.DEVNULL,
 )
 await asyncio.wait_for(fetch_proc.communicate, timeout=30.0)
 # git -C <path> rev-list --count <local_sha>..<remote_sha>
 count_proc = await asyncio.create_subprocess_exec(
 "git",
 "-C",
 str(local_repo_path),
 "rev-list",
 "--count",
 f"{repo.last_indexed_commit_sha}..{repo.remote_head_sha}",
 stdout=asyncio.subprocess.PIPE,
 stderr=asyncio.subprocess.DEVNULL,
 )
 out, _ = await asyncio.wait_for(count_proc.communicate, timeout=15.0)
 try:
 return int(out.decode.strip)
 except (ValueError, AttributeError):
 logger.warning(
 "behind_commits_rev_list_failed",
 repo_id=str(repo.id),
 local_sha=repo.last_indexed_commit_sha,
 remote_sha=repo.remote_head_sha,
 )
 return None
