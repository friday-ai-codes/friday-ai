"""索引自动触发任务（implementation）。

包含：
- Webhook push 事件处理
- APScheduler 定时轮询
- 防抖去重缓存
"""

import asyncio
import hashlib
import hmac
import time
from typing import Any

import structlog

from asgiref.sync import sync_to_async

from repositories.models import (
    BranchIndexStatus,
    IndexHistory,
    IndexHistoryStatus,
    IndexStatus,
    Repository,
    RepositoryBranchIndex,
    TriggerType,
)
from services.background_runner import run_in_background
from services.indexer import clone_and_index_repository
from services.qdrant_service import QdrantService

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 防抖去重缓存（work item）
# ---------------------------------------------------------------------------

# {commit_sha: timestamp} — 10 分钟内存窗口
_dedup_cache: dict[str, float] = {}
_DEDUP_WINDOW_SECONDS = 600  # 10 分钟


def _is_duplicate(commit_sha: str, branch_name: str = "") -> bool:
    """检查 commit SHA 是否在去重窗口内（可按分支区分，避免跨分支 cherry-pick SHA 冲突）。"""
    key = f"{branch_name}:{commit_sha}" if branch_name else commit_sha
    now = time.monotonic()
    # 清理过期条目
    expired = [k for k, v in _dedup_cache.items() if now - v > _DEDUP_WINDOW_SECONDS]
    for k in expired:
        del _dedup_cache[k]
    # 检查是否重复
    if key in _dedup_cache:
        return True
    _dedup_cache[key] = now
    return False


def clear_dedup_cache() -> None:
    """清空去重缓存（用于测试）。"""
    _dedup_cache.clear()


# ---------------------------------------------------------------------------
# Webhook 签名验证（work item）
# ---------------------------------------------------------------------------


def verify_webhook_signature(payload: bytes, secret: str, signature: str) -> bool:
    """验证 work item 签名（兼容 GitHub/Gitea 格式）。"""
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    # GitHub 格式: sha256=<hex>
    if signature.startswith("sha256="):
        signature = signature[7:]
    return hmac.compare_digest(expected, signature)


def verify_gitlab_token(secret: str, token: str) -> bool:
    """验证 GitLab X-Gitlab-Token。"""
    return hmac.compare_digest(secret, token)


# ---------------------------------------------------------------------------
# 解析 push 事件 payload
# ---------------------------------------------------------------------------

_ZERO_DELETE_SHA = "0" * 40


def _branch_name_from_ref(ref: str) -> str:
    return ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else ""


def parse_push_event(platform: str, payload: dict) -> dict[str, Any]:
    """从不同平台的 push 事件中提取关键信息。

    返回: ref、after、branch_name、is_delete
    """
    if platform == "github":
        ref = str(payload.get("ref", ""))
        after = str(payload.get("after", ""))
    elif platform == "gitlab":
        ref = str(payload.get("ref", ""))
        after = str(payload.get("after", payload.get("checkout_sha", "")))
    elif platform == "gitea":
        ref = str(payload.get("ref", ""))
        after = str(payload.get("after", ""))
    else:
        return {"ref": "", "after": "", "branch_name": "", "is_delete": False}

    is_delete = bool(payload.get("deleted", False)) or after == _ZERO_DELETE_SHA
    branch_name = _branch_name_from_ref(ref)
    return {"ref": ref, "after": after, "branch_name": branch_name, "is_delete": is_delete}


# ---------------------------------------------------------------------------
# 触发索引（共用逻辑）
# ---------------------------------------------------------------------------

# 历史上这里用 asyncio.create_task + set 防 GC，但任务跑在请求 event loop 里
# 会随 ASGI CurrentThreadExecutor 一起死。改走 background_runner 后无需手动管理强引用。


async def trigger_auto_index(
    repository: Repository,
    trigger_type: str,
    commit_sha: str = "",
    *,
    dedup_branch_name: str = "",
) -> dict[str, str]:
    """触发自动索引（webhook 或定时轮询共用）。

    返回: {"status": "triggered"/"skipped"/"duplicate", ...}

    dedup_branch_name: 防抖键中的分支段；定时轮询等无分支上下文时留空。
    """
    repo_id = str(repository.id)

    # 检查开关
    if not repository.auto_index_enabled:
        return {"status": "skipped", "reason": "auto_index_disabled"}

    # 正在索引中则跳过
    if repository.index_status == IndexStatus.INDEXING:
        return {"status": "skipped", "reason": "already_indexing"}

    # 防抖去重
    if commit_sha and _is_duplicate(commit_sha, dedup_branch_name):
        return {"status": "duplicate", "sha": commit_sha}

    # 重置上一轮索引的进度残留，避免 UI 在 INDEXING 初期读到旧的 N/N → 误显示 100%
    await Repository.objects.filter(id=repo_id).aupdate(
        index_total_chunks=0,
        index_processed_chunks=0,
        index_write_total=0,
        index_write_processed=0,
        index_error=None,
    )

    # 创建 IndexHistory 记录
    tt = TriggerType.WEBHOOK if trigger_type == "webhook" else TriggerType.SCHEDULED
    from django.utils import timezone

    history = await IndexHistory.objects.acreate(
        repository_id=repo_id,
        trigger_type=tt,
        status=IndexHistoryStatus.RUNNING,
        started_at=timezone.now(),
    )

    history_id_str = str(history.id)

    # durable 入队 + deterministic key 去重（index:{repo_id}）；保留上面的
    # already_indexing / _is_duplicate 业务防抖（与队列层 key 去重互补）。
    # IndexHistory 仍为进度真相源，FileIndex checkpoint 在任务体内复用。
    from durable import QUEUE_INDEX, DurableTaskService

    await DurableTaskService.defer(
        "durable_index",
        {
            "repository_id": str(repo_id),
            "history_id": history_id_str,
            "branch": None,
            "trigger": tt,
        },
        queue=QUEUE_INDEX,
        idempotency_key=f"index:{repo_id}",
    )

    logger.info(
        "auto_index_triggered",
        repository_id=repo_id,
        trigger_type=trigger_type,
        commit_sha=commit_sha,
        history_id=str(history.id),
    )

    return {
        "status": "triggered",
        "history_id": str(history.id),
        "trigger_type": trigger_type,
    }


# ---------------------------------------------------------------------------
# 分支 overlay 重建 / 回收（implementation）
# ---------------------------------------------------------------------------

# overlay 重建后台任务也走 background_runner，避免随请求 loop 一起死。
OVERLAY_UPGRADE_THRESHOLD = 0.5


async def trigger_branch_rebuild(
    repository: Repository, branch_name: str, commit_sha: str = "",
) -> dict[str, str]:
    """功能分支 push → 异步触发 overlay 重建。"""
    repo_id = str(repository.id)

    if not repository.auto_index_enabled:
        return {"status": "skipped", "reason": "auto_index_disabled"}

    if repository.index_status == IndexStatus.INDEXING:
        return {"status": "skipped", "reason": "base_indexing"}

    if commit_sha and _is_duplicate(commit_sha, branch_name):
        return {"status": "duplicate", "sha": commit_sha}

    lock_statuses = [BranchIndexStatus.INDEXING, BranchIndexStatus.UPGRADING]
    claimed = await RepositoryBranchIndex.objects.filter(
        repository=repository,
        branch_name=branch_name,
        is_base_branch=False,
    ).exclude(status__in=lock_statuses).aupdate(status=BranchIndexStatus.INDEXING)

    if claimed == 0:
        busy = await RepositoryBranchIndex.objects.filter(
            repository=repository,
            branch_name=branch_name,
            is_base_branch=False,
            status__in=lock_statuses,
        ).aexists()
        if busy:
            return {"status": "skipped", "reason": "already_indexing"}
        await RepositoryBranchIndex.objects.acreate(
            repository=repository,
            branch_name=branch_name,
            is_base_branch=False,
            status=BranchIndexStatus.INDEXING,
        )

    run_in_background(
        lambda: _rebuild_branch_overlay(repository, branch_name, commit_sha),
        name=f"branch-rebuild-{repo_id}-{branch_name}",
    )

    logger.info("branch_rebuild_triggered", repository_id=repo_id, branch=branch_name)
    return {"status": "triggered", "branch": branch_name}


async def _check_and_upgrade_overlay(repository: Repository, branch_name: str) -> bool:
    """overlay chunk 规模相对 base 过大时，触发完整重索引并切换 collection。"""
    base_qs = RepositoryBranchIndex.objects.filter(
        repository=repository,
        is_base_branch=True,
    )
    if not await base_qs.aexists():
        return False

    branch_qs = RepositoryBranchIndex.objects.filter(
        repository=repository,
        branch_name=branch_name,
        is_base_branch=False,
    )
    branch_index = await branch_qs.afirst()
    if branch_index is None:
        return False

    health = await sync_to_async(QdrantService.check_collection_health)(str(repository.id))
    base_count = int(health.get("points_count", 0))
    if base_count <= 0:
        return False

    ratio = branch_index.effective_chunks_count / base_count
    if ratio < OVERLAY_UPGRADE_THRESHOLD:
        return False

    logger.info(
        "overlay_upgrade_triggered",
        branch=branch_name,
        ratio=round(ratio, 2),
        threshold=OVERLAY_UPGRADE_THRESHOLD,
    )
    old_collection = branch_index.collection_name
    try:
        await RepositoryBranchIndex.objects.filter(pk=branch_index.pk).aupdate(
            status=BranchIndexStatus.UPGRADING,
        )
        await clone_and_index_repository(str(repository.id), branch=branch_name)
        if old_collection:
            await sync_to_async(QdrantService.delete_collection_by_name)(old_collection)
        logger.info("overlay_upgrade_complete", branch=branch_name)
        return True
    except Exception as e:
        logger.error(
            "overlay_upgrade_failed",
            branch=branch_name,
            repository_id=str(repository.id),
            error=str(e),
        )
        await RepositoryBranchIndex.objects.filter(
            repository=repository,
            branch_name=branch_name,
            is_base_branch=False,
        ).aupdate(status=BranchIndexStatus.FAILED)
        return False


async def _rebuild_branch_overlay(
    repository: Repository, branch_name: str, commit_sha: str,
) -> None:
    """overlay 重建，含指数退避重试；成功后尝试规模升级。"""
    repo_id = str(repository.id)
    retry_delays = [1.0, 4.0, 16.0]

    for attempt in range(3):
        try:
            await clone_and_index_repository(repo_id, branch=branch_name)
            try:
                await _check_and_upgrade_overlay(repository, branch_name)
            except Exception:
                logger.warning(
                    "overlay_upgrade_check_failed",
                    repository_id=repo_id,
                    branch=branch_name,
                    exc_info=True,
                )
            return
        except Exception as e:
            logger.warning(
                "branch_rebuild_retry",
                repository_id=repo_id,
                branch=branch_name,
                attempt=attempt + 1,
                error=str(e),
            )
            if attempt < 2:
                await asyncio.sleep(retry_delays[attempt])
            else:
                logger.error(
                    "branch_rebuild_failed",
                    repository_id=repo_id,
                    branch=branch_name,
                    error=str(e),
                )
                await RepositoryBranchIndex.objects.filter(
                    repository_id=repo_id,
                    branch_name=branch_name,
                ).aupdate(status=BranchIndexStatus.FAILED)


async def cleanup_branch_index(repository: Repository, branch_name: str) -> dict[str, str]:
    """功能分支删除 → 删除 overlay collection 与 DB 记录。"""
    qs = RepositoryBranchIndex.objects.filter(
        repository=repository,
        branch_name=branch_name,
        is_base_branch=False,
    )
    row = await qs.afirst()
    if row is None:
        return {"status": "skipped", "reason": "not_found"}

    if row.collection_name:
        await sync_to_async(QdrantService.delete_collection_by_name)(row.collection_name)
    await row.adelete()

    logger.info(
        "branch_index_cleaned",
        repository_id=str(repository.id),
        branch=branch_name,
    )
    return {"status": "cleaned", "branch": branch_name}


async def _get_remote_branches(git_url: str) -> set[str]:
    """git ls-remote --heads 解析远端分支名集合。"""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "ls-remote",
        "--heads",
        git_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError("git ls-remote --heads timed out") from None
    if proc.returncode != 0:
        raise RuntimeError("git ls-remote --heads failed")
    out = stdout.decode().strip()
    if not out:
        return set()
    names: set[str] = set()
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        ref = parts[1].strip()
        if ref.startswith("refs/heads/"):
            names.add(ref.removeprefix("refs/heads/"))
    return names


async def cleanup_stale_branch_indexes() -> dict[str, int]:
    """定时：回收远端已不存在的分支 overlay。"""
    cleaned = 0
    async for repo in Repository.objects.filter(auto_index_enabled=True, is_deleted=False):
        if not repo.git_url:
            continue
        try:
            remote_branches = await _get_remote_branches(repo.git_url)
        except Exception as e:
            logger.warning(
                "cleanup_branch_check_failed",
                repository_id=str(repo.id),
                error=str(e),
            )
            continue
        if not remote_branches:
            continue

        orphan_qs = RepositoryBranchIndex.objects.filter(
            repository=repo,
            is_base_branch=False,
        ).exclude(branch_name__in=remote_branches)
        async for orphan in orphan_qs:
            if orphan.collection_name:
                await sync_to_async(QdrantService.delete_collection_by_name)(
                    orphan.collection_name,
                )
            await orphan.adelete()
            cleaned += 1

    logger.info("stale_branch_cleanup_complete", cleaned=cleaned)
    return {"cleaned": cleaned}


# ---------------------------------------------------------------------------
# 定时轮询任务（work item）
# ---------------------------------------------------------------------------


async def poll_repository_updates() -> dict[str, int]:
    """轮询所有启用自动索引的仓库，检查远端 HEAD 是否变化。"""
    repositories = [
        repo
        async for repo in Repository.objects.filter(
            auto_index_enabled=True, is_deleted=False
        )
    ]

    checked = 0
    triggered = 0

    for repo in repositories:
        checked += 1
        if not repo.git_url:
            continue

        try:
            remote_sha = await _get_remote_head_sha(repo.git_url)
            # contract：顺手缓存 remote_head_sha + checked_at（即使仓库还没首次索引也写）
            if remote_sha:
                from django.utils import timezone

                await Repository.objects.filter(id=repo.id).aupdate(
                    remote_head_sha=remote_sha,
                    remote_head_checked_at=timezone.now(),
                )

            if not repo.last_indexed_commit_sha:
                continue  # 还没首次索引，跳过 auto-trigger（Pitfall 7）

            if remote_sha and remote_sha != repo.last_indexed_commit_sha:
                result = await trigger_auto_index(repo, "scheduled", remote_sha)
                if result["status"] == "triggered":
                    triggered += 1
        except Exception:
            logger.exception(
                "poll_check_failed",
                repository_id=str(repo.id),
                git_url=repo.git_url,
            )

    logger.info("poll_complete", checked=checked, triggered=triggered)
    return {"checked": checked, "triggered": triggered}


async def _get_remote_head_sha(git_url: str) -> str:
    """通过 git ls-remote 获取远端 HEAD SHA。"""
    proc = await asyncio.create_subprocess_exec(
        "git", "ls-remote", git_url, "HEAD",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
    if proc.returncode != 0:
        return ""
    output = stdout.decode().strip()
    if output:
        return output.split()[0]
    return ""
