"""Incremental indexer service for code repositories."""

import asyncio
import hashlib
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as dt_timezone
from enum import Enum
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from code_relations.types import ChunkRegistryRow
from code_relations.utils import generate_chunk_id
from repositories.models import (
    BranchFileIndex,
    BranchIndexStatus,
    FileIndex,
    GraphBuildHistory,
    GraphBuildHistoryStatus,
    GraphBuildHistoryTrigger,
    IndexStatus,
    Repository,
    RepositoryBranchIndex,
    RepositoryGraphStatus,
)
from repositories.views import build_authenticated_git_url
from services.branch_utils import (
    MAX_OVERLAY_COLLECTIONS_PER_REPO,
    BranchOverlayLimitExceeded,
    get_overlay_collection_name,
)
from services.code_parser import CodeChunk, CodeParser, compute_file_hash, scan_directory
from services.embedding import EmbeddingService
from services.exclusion import build_matcher_for_repo
from services.graph_builder import (
    mark_repository_graph_terminal,
    reset_repository_graph_progress,
)
from services.purge import purge_file
from services.qdrant_service import QdrantService
from system.models import SettingKeys, SystemSetting


# KEEP: Qdrant SDK 使用同步 httpx 客户端，async 化属于独立重构项（Out of Scope）
# Wrap sync Qdrant operations for use in async context
@sync_to_async
def qdrant_create_collection(repository_id: str, vector_size: int, hybrid: bool = False) -> bool:
    return QdrantService.create_collection(repository_id, vector_size=vector_size, hybrid=hybrid)


@sync_to_async
def qdrant_create_branch_payload_index(collection_name: str) -> bool:
    return QdrantService.create_branch_payload_index(collection_name)


@sync_to_async  # KEEP: Qdrant SDK 同步限制
def qdrant_get_stored_file_hashes(repository_id: str) -> dict[str, str]:
    return QdrantService.get_stored_file_hashes(repository_id)


@sync_to_async  # KEEP: Qdrant SDK 同步限制
def qdrant_delete_by_file_path(repository_id: str, file_path: str) -> bool:
    return QdrantService.delete_by_file_path(repository_id, file_path)


@sync_to_async  # KEEP: Qdrant SDK 同步限制
def qdrant_upsert_vectors(repository_id: str, points: list[dict]) -> bool:
    return QdrantService.upsert_vectors(repository_id, points)


@sync_to_async  # KEEP: Qdrant SDK 同步限制
def qdrant_update_file_path(repository_id: str, old_path: str, new_path: str) -> bool:
    return QdrantService.update_file_path(repository_id, old_path, new_path)


@sync_to_async  # KEEP: Qdrant SDK 同步限制
def qdrant_create_collection_by_name(
    collection_name: str, vector_size: int, hybrid: bool = False
) -> bool:
    return QdrantService.create_collection_by_name(collection_name, vector_size, hybrid=hybrid)


@sync_to_async  # KEEP: Qdrant SDK 同步限制
def qdrant_upsert_vectors_by_name(collection_name: str, points: list[dict]) -> bool:
    return QdrantService.upsert_vectors_by_name(collection_name, points)


def _resolve_write_branch(repository: Repository, branch_name: str | None) -> str:
    """写入侧分支归一化：None/""/==base_branch/==default_branch → ""（base），否则原样。

    集中式归一化入口，避免「等于 base 视为空串」的判断散落各 callsite（Pitfall 4）。
    base 分支来源对齐向量层 ``resolve_branch_for_query``（branch_utils.py）：
    ``base = repository.base_branch or repository.default_branch``，base_branch 优先回退
    default_branch。返回 ``""`` 表示 base 路径——配合 ``generate_chunk_id`` 的 base
    命名空间，chunk_id 字节不变（293 golden 不回归）。
    """
    base = repository.base_branch or repository.default_branch
    if not branch_name or branch_name == base:
        return ""
    return branch_name


async def update_index_progress(repository_id: str, total: int, processed: int) -> None:
    """Update indexing progress in database."""
    await Repository.objects.filter(id=repository_id).aupdate(
        index_total_chunks=total,
        index_processed_chunks=processed,
    )


async def persist_vector_track_complete(repository_id: str, repo_path: str) -> str | None:
    """主向量轨完成时立即把仓库标记为"已索引"——含 last_indexed_commit_sha 与 status。

    设计动机：BUILDING_GRAPH（图谱抽取）和 FINALIZING（repo summary）会调 LLM，
    可能很慢且容易在开发环境被服务重启 / autoreload 打断。这两步失败不应让
    用户看到"索引失败"——主索引向量数据已经完整入库，搜索完全可用。

    这里同时写入：
      - last_indexed_commit_sha / remote_head_sha / remote_head_checked_at
        → 让 Hash 新鲜度卡片立刻显示 fresh
      - index_status = INDEXED + last_indexed_at = now
        → 让"代码索引"卡片立刻显示"已就绪"
      - index_error = None
        → 清掉之前 run 留下的错误信息

    Graph / Summary 失败后续可单独重跑（或下次索引自动重做），不影响 INDEXED 状态。

    幂等：clone_and_index_repository 末尾还会再写一次（同样的值），aupdate 重复
    执行无副作用。

    Reliability：本函数任何异常都不应让索引 fail（主向量轨已成功才进来的）。
    所以外层 catch-all：拿不到 HEAD、Repository 不存在、非 UUID 测试场景等
    都只 log warning 后 return None。
    """
    from django.utils import timezone as _tz

    try:
        head_sha = await _get_head_sha(repo_path)
        if not head_sha:
            return None

        now = _tz.now()
        await Repository.objects.filter(id=repository_id).aupdate(
            # Hash 新鲜度元数据
            last_indexed_commit_sha=head_sha,
            remote_head_sha=head_sha,
            remote_head_checked_at=now,
            behind_commits=0,
            behind_commits_calculated_at=now,
            # contract 关键：主向量轨完成即视为"已索引"，让 UI 立刻可用
            index_status=IndexStatus.INDEXED,
            last_indexed_at=now,
            index_error=None,
        )
        logger.info(
            "vector_track_complete_persisted",
            repository_id=repository_id,
            head_sha=head_sha[:10],
        )
        return head_sha
    except Exception as e:
        logger.warning(
            "persist_vector_track_complete_failed",
            repository_id=repository_id,
            error=str(e),
        )
        return None


async def update_current_indexing_file(
    repository_id: str,
    *,
    file_path: str | None = None,
    processed: int | None = None,
    total: int | None = None,
) -> None:
    """更新文件级索引进度字段（contract — 文件级实时进度）。

    任一非 None 参数都会写入；为减少 DB 写入压力，调用方应仅在数值真实变化时调用。
    写入失败仅 warning，不打断索引主流程（与 update_index_stage 同等级）。
    """
    update_fields: dict[str, Any] = {}
    if file_path is not None:
        # 防御截断：CharField max_length=1000，超长路径直接落到末尾
        update_fields["current_indexing_file"] = file_path[-1000:]
    if processed is not None:
        update_fields["indexed_files_processed"] = processed
    if total is not None:
        update_fields["indexed_files_total"] = total
    if not update_fields:
        return
    try:
        await Repository.objects.filter(id=repository_id).aupdate(**update_fields)
    except Exception as exc:
        logger.warning(
            "update_current_indexing_file_failed",
            repository_id=repository_id,
            error=str(exc),
        )


async def get_files_last_commit(
    repo_path: str,
    file_paths: list[str],
) -> dict[str, tuple[str, int]]:
    """批量获取一组文件各自最近一次 commit 的 (sha, author_timestamp_unix)。

    实现方式：用一次 `git log --name-only --format=%H|%ct` 走整个仓库历史，
    逐 commit 取出 changed paths 与该 commit 信息，对每个目标 path 记录第一次
    (即最新一次) 出现的 commit。比对 N 次 `git log -1 -- <file>` 快若干个数量级。

    Args:
        repo_path: 克隆仓库路径
        file_paths: 关心的相对路径集合（剩余 path 会被忽略）

    Returns:
        dict {file_path: (commit_sha, author_unix_ts)}；查无记录的文件不会出现在结果里。
    """
    if not file_paths:
        return {}
    targets = set(file_paths)
    result: dict[str, tuple[str, int]] = {}
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "log",
            "--name-only",
            "--format=%H|%ct",
            "--no-renames",
            "HEAD",
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120.0)
    except (asyncio.TimeoutError, FileNotFoundError) as exc:
        logger.warning("get_files_last_commit_failed", error=str(exc))
        return {}
    if proc.returncode != 0:
        return {}

    current_sha: str | None = None
    current_ts: int = 0
    for raw_line in stdout.decode("utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "|" in line and len(line.split("|", 1)[0]) >= 7 and " " not in line:
            sha_part, _, ts_part = line.partition("|")
            try:
                current_ts = int(ts_part)
                current_sha = sha_part
            except ValueError:
                current_sha = None
                current_ts = 0
            continue
        if current_sha is None:
            continue
        if line in targets and line not in result:
            result[line] = (current_sha, current_ts)
            if len(result) == len(targets):
                break
    return result


def _ts_to_dt(unix_ts: int) -> Any:
    """Unix 时间戳 → tz-aware datetime（UTC）。"""
    return datetime.fromtimestamp(unix_ts, tz=dt_timezone.utc)


async def update_write_progress(repository_id: str, total: int, processed: int) -> None:
    """Update Qdrant write progress in database."""
    await Repository.objects.filter(id=repository_id).aupdate(
        index_write_total=total,
        index_write_processed=processed,
    )


# 索引子阶段常量（前端用作 overall_stage 显示文案）
class IndexStage:
    CLONING = "克隆仓库中..."
    COMPARING_HEAD = "对比远端 commit..."
    LOADING_HASHES = "加载本地文件 hash..."
    COMPUTING_DIFF = "计算变更文件..."
    SCANNING_FILES = "扫描仓库文件..."
    PARSING_FILES = "解析文件中..."
    EMBEDDING = "生成向量中..."
    WRITING_VECTORS = "写入向量库..."
    # contract：按文件批 _flush_batch 模式下，PARSING / EMBEDDING / WRITING 在每个
    # batch 内会快速来回切换（一个 1000 文件的仓库可能产生 100+ 次切换），UI 上
    # 会显得"stage 文案在乱跳"。INDEXING_FILES 是一个稳定的复合文案，覆盖整个
    # 按文件批的索引主循环，把内部 embed/upsert 细节藏在统一节奏背后。
    INDEXING_FILES = "索引文件中..."
    BUILDING_GRAPH = "构建代码图谱..."
    FINALIZING = "收尾中..."
    COMPLETED = "完成"


# 解析 git clone --progress 的 stderr 行，例如：
#   "Receiving objects:  50% (617/1234), 1.23 MiB | 500 KiB/s"
_CLONE_RECEIVING_RE = re.compile(r"Receiving objects:\s+(\d{1,3})%")


async def update_index_stage(repository_id: str, stage: str) -> None:
    """更新当前索引阶段（用于前端实时展示）。

    Stage 仅用于 UI 文案，写入失败（如非法 repository_id、DB 临时不可用）不应
    中断索引主流程，仅记录 warning。
    """
    try:
        await Repository.objects.filter(id=repository_id).aupdate(index_stage=stage)
    except Exception as exc:
        logger.warning(
            "update_index_stage_failed",
            repository_id=repository_id,
            stage=stage,
            error=str(exc),
        )


# implementation-02：图谱进度节流常量。
# 与 ``_extract_and_write_graph`` 既有循环节奏对齐（line 2347
# ``if index % GRAPH_YIELD_EVERY == 0``）；helper 函数体内**不二次节流**，
# 节流责任在 callsite——保 helper 语义简单可单测。
GRAPH_YIELD_EVERY = 25


async def update_graph_progress(
    repository_id: str,
    *,
    stage: str = "",
    current_file: str = "",
    processed: int = 0,
    total: int = 0,
) -> None:
    """图谱构建进度上报 helper（与 update_index_stage / update_current_indexing_file 解耦）。

    implementation-02：按 callsite 节流（``GRAPH_YIELD_EVERY=25``）
    写 4 字段——``graph_stage`` / ``current_graph_file`` /
    ``graph_files_processed`` / ``graph_files_total``。**helper 函数体内不
    二次节流**，每次调用即写库；与 ``update_index_stage`` 同 try/except
    模板，写失败仅记录 warning。

    CONTEXT 决议（Grey Area 1 strong-consistency 口径）：4 入参一律全写 4
    字段——避免"上次的 stage 残留"bug。若 caller 仅传 ``stage``，则
    ``current_graph_file`` / ``graph_files_processed`` / ``graph_files_total``
    也会被默认值（``""`` / ``0`` / ``0``）覆盖。reset/terminal 写入由
    ``services/graph_builder.py`` 的 helper 单独负责，与本函数职责分离。
    """
    logger.info(
        "graph_progress_update",
        repository_id=repository_id,
        stage=stage,
        current_file=current_file,
        processed=processed,
        total=total,
    )
    try:
        await Repository.objects.filter(id=repository_id).aupdate(
            graph_stage=stage,
            current_graph_file=current_file,
            graph_files_processed=processed,
            graph_files_total=total,
        )
    except Exception as exc:
        logger.warning(
            "update_graph_progress_failed",
            repository_id=repository_id,
            stage=stage,
            current_file=current_file,
            processed=processed,
            total=total,
            error=str(exc),
        )


# 文件级断点续传：累积约 64 个 chunks 触发一次 embed → upsert → flush FileIndex
# 阈值的取舍：
#   - 偏小（如 16）：失败重试更"细"，丢失工作量更少；但 embed API 调用次数变多
#   - 偏大（如 256）：减少 API 调用 / 提升吞吐；但失败重试时丢失更多文件
# 当前选 64：单次 embed 调用控制在 ~64 chunks，约 1-2 秒一批；失败重试丢失通常 ≤ 64 chunks 的工作量
FILE_BATCH_CHUNK_THRESHOLD = 64


logger = structlog.get_logger(__name__)


def _build_upsert_failure_message(
    *,
    representative_file: str,
    batch_no: int,
    total_batches: int,
    batch_size: int,
    total_points: int,
) -> str:
    return (
        "写入向量库失败或超时: "
        f"file={representative_file}, "
        f"batch {batch_no}/{total_batches}, "
        f"batch_size={batch_size}, "
        f"total_points={total_points}; "
        "see prior 'upsert_vectors_*_failed' log for low-level Qdrant error"
    )


def _build_embedding_text(chunk: CodeChunk) -> str:
    """构建用于 embedding 的增强文本，包含上下文信息。"""
    parts = [chunk.context_header]
    if chunk.imports:
        parts.append(f"Imports: {chunk.imports[:300]}")
    if chunk.module_docstring:
        parts.append(f"Module: {chunk.module_docstring[:200]}")
    if chunk.sibling_signatures:
        parts.append(f"Siblings: {chunk.sibling_signatures[:200]}")
    parts.append(chunk.content)
    return "\n".join(parts)


class GitDiffError(Exception):
    """git diff 操作失败时抛出。"""


class DiffAction(Enum):
    """Action to take for a file during incremental sync."""

    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    SKIP = "skip"
    RENAME = "rename"


@dataclass
class FileDiff:
    """Represents a file difference for incremental indexing."""

    file_path: str
    action: DiffAction
    old_hash: str | None = None
    new_hash: str | None = None
    old_path: str | None = None


async def _get_head_sha(repo_path: str) -> str:
    """获取仓库当前 HEAD 的 commit SHA。"""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        "HEAD",
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    if proc.returncode != 0:
        raise GitDiffError("git rev-parse HEAD failed")
    return stdout.decode().strip()


async def _is_shallow_clone(repo_path: str) -> bool:
    """检查仓库是否为 shallow clone。"""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        "--is-shallow-repository",
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    return stdout.decode().strip() == "true"


async def _fetch_commit(repo_path: str, sha: str, proxy_url: str | None = None) -> bool:
    """尝试 fetch 指定 commit 到浅克隆仓库。失败返回 False。"""
    cmd: list[str] = ["git"]
    if proxy_url:
        cmd.extend(["-c", f"http.proxy={proxy_url}"])
    cmd.extend(["fetch", "--depth=1", "origin", sha])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=60.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return False
    return proc.returncode == 0


async def _unshallow_repo(repo_path: str, proxy_url: str | None = None) -> bool:
    """补齐浅克隆的完整历史（commit 历史索引前置，BL-01）。best-effort，失败返回 False。

    生产索引路径用 ``git clone --depth 1`` 创建浅克隆，其上 ``git log`` 仅能看到 HEAD 一个
    commit；若直接在浅克隆上跑 commit 历史索引（``index_commits`` 读 git log），历史 commit
    永远索引不到，且跨索引运行会静默丢失中间 commit（违反 T-25-09「绝不丢 commit」）。

    这里在 commit 历史索引前 ``git fetch --unshallow origin`` 把当前分支历史补全。注意本地裸
    镜像（``repo_mirror``）同样是 ``--depth 1`` 浅快照，无完整历史可复用，故只能就地 unshallow
    这份临时克隆。整段 best-effort：超时 / 失败仅记 warning 返回 False，由调用方决定是否继续
    （commit 索引随后按浅克隆降级，绝不阻断既有索引 success 终态）。
    """
    cmd: list[str] = ["git"]
    if proxy_url:
        cmd.extend(["-c", f"http.proxy={proxy_url}"])
    cmd.extend(["fetch", "--unshallow", "origin"])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
    except asyncio.TimeoutError:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
        logger.warning("commit_index_unshallow_timeout", repo_path=repo_path)
        return False
    if proc.returncode != 0:
        logger.warning(
            "commit_index_unshallow_failed",
            stderr=stderr.decode(errors="ignore")[:200],
        )
        return False
    return True


async def _get_merge_base(repo_path: str, base_ref: str, feature_ref: str) -> str:
    """计算两个分支的 merge-base SHA。"""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "merge-base",
        base_ref,
        feature_ref,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
    if proc.returncode != 0:
        raise GitDiffError(f"git merge-base failed: {stderr.decode()}")
    return stdout.decode().strip()


async def _fetch_branch(repo_path: str, branch_name: str, proxy_url: str | None = None) -> bool:
    """Fetch 单个分支引用到本地（不检出）。"""
    cmd: list[str] = ["git"]
    if proxy_url:
        cmd.extend(["-c", f"http.proxy={proxy_url}"])
    cmd.extend(["fetch", "--depth=1", "origin", f"{branch_name}:refs/remotes/origin/{branch_name}"])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=60.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return False
    return proc.returncode == 0


async def _deepen_for_merge_base(
    repo_path: str,
    base_ref: str,
    feature_ref: str,
    proxy_url: str | None = None,
) -> str:
    """渐进加深 shallow clone 以获取可靠的 merge-base。

    尝试 deepen=50 → deepen=200 → unshallow，最多 3 次。
    失败时回退到 base branch tip-to-tip diff。
    """
    for depth in [50, 200, None]:
        cmd: list[str] = ["git"]
        if proxy_url:
            cmd.extend(["-c", f"http.proxy={proxy_url}"])
        if depth:
            cmd.extend(["fetch", f"--deepen={depth}", "origin"])
        else:
            cmd.extend(["fetch", "--unshallow", "origin"])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=120.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            continue

        try:
            return await _get_merge_base(repo_path, base_ref, feature_ref)
        except GitDiffError:
            continue

    # 全部失败，回退到 base branch 的 tip SHA（tip-to-tip diff）
    logger.warning("merge_base_fallback_to_tip", base=base_ref, feature=feature_ref)
    proc = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        f"refs/remotes/origin/{base_ref}",
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    if proc.returncode == 0:
        return stdout.decode().strip()
    raise GitDiffError(f"无法获取 merge-base 也无法解析 {base_ref} 的 HEAD")


def _parse_git_diff_output(output: str) -> list[FileDiff]:
    """解析 git diff --name-status --find-renames 输出为 FileDiff 列表。"""
    diffs: list[FileDiff] = []
    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        status_code = parts[0]
        if status_code == "A":
            diffs.append(FileDiff(parts[1], DiffAction.ADD))
        elif status_code == "M":
            diffs.append(FileDiff(parts[1], DiffAction.UPDATE))
        elif status_code == "D":
            diffs.append(FileDiff(parts[1], DiffAction.DELETE))
        elif status_code.startswith("R"):
            old_path, new_path = parts[1], parts[2]
            similarity = int(status_code[1:]) if len(status_code) > 1 else 100
            if similarity == 100:
                diffs.append(FileDiff(new_path, DiffAction.RENAME, old_path=old_path))
            else:
                # 内容变更的 rename：拆为 DELETE + ADD
                diffs.append(FileDiff(old_path, DiffAction.DELETE))
                diffs.append(FileDiff(new_path, DiffAction.ADD))
    return diffs


def _parse_numstat_output(output: str) -> tuple[int, int]:
    """解析 git diff --numstat -z 输出，汇总 (lines_added, lines_deleted)。

    implementation（与 _parse_git_diff_output 并列，绝不改其函数体）。

    -z 模式每条记录形如 ``added\\tdeleted\\t<path>\\0``；rename 时为
    ``added\\tdeleted\\t\\0<old>\\0<new>\\0``（path 字段为空，须额外消费 old/new
    两个 NUL 路径字段）。二进制文件 added/deleted 为 ``-``，该文件计 0（不累加，
    区别于真实 0）。解析不出数字的脏记录跳过（不抛错），保持鲁棒。

    Args:
        output: ``git diff --numstat -z`` 的 stdout 文本（已 decode）。

    Returns:
        tuple[int, int]: (新增行数汇总, 删除行数汇总)，均 >= 0。
    """
    total_added = 0
    total_deleted = 0
    tokens = output.split("\0")
    i = 0
    n = len(tokens)
    while i < n:
        token = tokens[i]
        if not token:
            i += 1
            continue
        parts = token.split("\t")
        if len(parts) < 3:
            # 非预期格式 / 脏记录，跳过不抛错
            i += 1
            continue
        added_str, deleted_str, path = parts[0], parts[1], parts[2]
        # rename：path 字段为空 → 后随 old/new 两个独立 NUL 字段，消费掉避免污染
        if path == "":
            i += 2
        # 二进制文件 added/deleted 输出 "-" → 该文件计 0（不累加）
        if added_str != "-" and deleted_str != "-":
            try:
                total_added += int(added_str)
                total_deleted += int(deleted_str)
            except ValueError:
                # 前两列非数字的脏记录跳过
                pass
        i += 1
    return total_added, total_deleted


def _build_summary_text(files_added: int, files_modified: int, files_deleted: int) -> str:
    """生成人可读的差异摘要文本。"""
    parts: list[str] = []
    if files_added:
        parts.append(f"新增 {files_added} 文件")
    if files_modified:
        parts.append(f"修改 {files_modified} 文件")
    if files_deleted:
        parts.append(f"删除 {files_deleted} 文件")
    if not parts:
        return "无变更"
    return f"本次增量：{'、'.join(parts)}"


class IndexerService:
    """Service for indexing repository code into vector database."""

    def __init__(self, repository_id: str):
        from django.conf import settings

        self.repository_id = repository_id
        # 默认启用 ast_aware 精细切片（符号驱动）；可经 settings.CHUNKING_MODE
        # 回退 "fixed"。改切片策略后需重新索引方能对存量 chunk 生效。
        self.parser = CodeParser(
            chunking_mode=getattr(settings, "CHUNKING_MODE", "ast_aware"),
        )
        # 图谱抽取与写入服务（双轨架构 - per contract）
        self._graph_extractor = None  # 延迟初始化
        self._graph_writer = None
        # implementation（per contract / contract）：累积本次索引会话每次 _upsert_chunk_registry_batch
        # 返回的 point_id 列表；_extract_and_write_graph 末尾一次性传给
        # `code_relations.tasks.enqueue_edge_build(...)` 触发 6 EdgeBuilder + payload sync，
        # 并在调用后清空。set 去重避免同一 chunk 多次 flush 重复进 builder 输入。
        self._session_dirty_chunk_ids: set[uuid.UUID] = set()
        # implementation single-parse：缓存向量轨 parse_file_dual 产出的 ExtractionBundle
        # （rel_path → bundle），供图谱轨 _extract_and_write_graph 复用，消除每文件二次解析。
        # 缓存 miss 时图谱轨自行解析兜底；实例级（一次索引一个 IndexerService），无需跨方法清理。
        self._session_graph_bundles: dict[str, Any] = {}

    def _init_graph_services(self):
        """延迟初始化图谱抽取与写入服务（避免循环导入）。"""
        if self._graph_extractor is None:
            from codegraph.services.graph_writer import GraphWriter
            from codegraph.services.orchestrator import GraphExtractor

            self._graph_extractor = GraphExtractor()
            self._graph_writer = GraphWriter()

    async def _should_build_graph(self, history_id: str | None) -> bool:
        """implementation-02 / work item-03：图谱构建双重判断 + SKIPPED 写入。

        在 4 处 `_extract_and_write_graph` callsite 之前调用，
        以 `settings.ENABLE_CODEGRAPH AND Repository.auto_build_graph_enabled` 双重判断
        决定是否跳过图谱构建。跳过时：

        1. 发 structlog 事件 `graph_build_skipped`，
           `reason ∈ {feature_flag_disabled, auto_build_graph_disabled}`。
        2. 若 `history_id` 可解析（显式传入或 fallback 命中 RUNNING IndexHistory）→
           写 `IndexHistory.graph_build_status = SKIPPED`（复用
           `code_relations.lifecycle._update_history` helper，异常自动隔离）。
        3. 返回 `False`，调用方应跳过 `_extract_and_write_graph`。

        `history_id` 为 None 时 fallback：查该 repo 最近 RUNNING 的 IndexHistory.id
        （与 `_extract_and_write_graph` 末尾 hook line 2165 同模式）。

        Args:
            history_id: 显式 IndexHistory 行 ID；None 时走 fallback 查 RUNNING。

        Returns:
            True 表示双重判断通过，调用方继续构建图谱；False 表示已跳过 + 已记录状态。
        """
        from django.conf import settings

        from code_relations.lifecycle import _update_history
        from repositories.models import (
            GraphBuildStatus,
            IndexHistory,
            IndexHistoryStatus,
        )

        repo = await Repository.objects.filter(id=self.repository_id).afirst()
        if repo is None:
            logger.warning(
                "graph_build_skipped",
                repository_id=str(self.repository_id),
                reason="repository_not_found",
                history_id=history_id,
            )
            return False

        global_enabled = bool(getattr(settings, "ENABLE_CODEGRAPH", False))
        repo_enabled = bool(repo.auto_build_graph_enabled)

        if global_enabled and repo_enabled:
            return True

        # 全局 flag 优先（更高 severity；先 disable 全局再看 per-repo 才合逻辑）
        reason = "feature_flag_disabled" if not global_enabled else "auto_build_graph_disabled"

        # history_id fallback：未显式透传时取最近 RUNNING（与 line 2165 同模式）
        resolved_history_id = history_id
        if resolved_history_id is None:
            resolved_history_id = await sync_to_async(
                lambda: IndexHistory.objects.filter(
                    repository_id=self.repository_id,
                    status=IndexHistoryStatus.RUNNING,
                )
                .order_by("-created_at")
                .values_list("id", flat=True)
                .first()
            )()

        logger.info(
            "graph_build_skipped",
            repository_id=str(self.repository_id),
            reason=reason,
            history_id=str(resolved_history_id) if resolved_history_id else None,
        )

        if resolved_history_id is not None:
            await _update_history(resolved_history_id, graph_build_status=GraphBuildStatus.SKIPPED)

        return False

    async def _acreate_auto_graph_history(self) -> GraphBuildHistory:
        """创建 auto_after_index 的 RUNNING GraphBuildHistory，去重并发重复行。

        4 处 index 路径（full / branch / git_diff / incremental）在并发索引同一仓库
        时，曾各自 ``acreate`` 出多条 RUNNING 行（已观测到同毫秒内 2 条）。多余的
        RUNNING 行一旦其后台任务随进程重启丢失，就成了永久挡住 rebuild 的幽灵。

        本 helper 在 Repository 行锁内先查是否已存在 RUNNING 的 auto_after_index
        行：存在则复用，不再新建；否则创建。``select_for_update`` 在支持的后端
        （PostgreSQL）下串行化并发索引任务，SQLite 下为安全 no-op（写事务本身串行）。
        """
        from django.db import transaction

        def _locked_get_or_create() -> GraphBuildHistory:
            with transaction.atomic():
                Repository.objects.select_for_update().filter(
                    id=self.repository_id
                ).first()
                existing = (
                    GraphBuildHistory.objects.filter(
                        repository_id=self.repository_id,
                        status=GraphBuildHistoryStatus.RUNNING,
                        trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX,
                    )
                    .order_by("-started_at")
                    .first()
                )
                if existing is not None:
                    return existing
                return GraphBuildHistory.objects.create(
                    repository_id=self.repository_id,
                    status=GraphBuildHistoryStatus.RUNNING,
                    trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX,
                )

        return await sync_to_async(_locked_get_or_create)()

    async def run_full_index(
        self,
        repo_path: str,
        *,
        branch_name: str | None = None,
    ) -> dict[str, Any]:
        """Run full indexing for a repository.

        contract 重构（2026-05）：从"一次性 parse-all → embed-all → upsert-all"模式
        改造为"按文件批 _flush_batch"模式，与 run_git_diff_index 保持节奏一致。

        - 每攒满 ``FILE_BATCH_CHUNK_THRESHOLD`` chunks 即触发一次 embed → upsert →
          写 FileIndex 锚点 → 清缓冲区。
        - 启动时优先查 FileIndex 已写的 (file_path, file_hash)，本次扫描命中且
          hash 不变的文件视为"已索引"，**直接 skip parse 与 embed**。
        - 进度计数走文件级口径：``indexed_files_processed / indexed_files_total``。
          中断后再次进入此函数时 processed 从已 skip 数起步，百分比自然续接，
          不归零（详见 ``_compute_index_progress``）。

        Args:
            repo_path: Path to the cloned repository
            branch_name: 分支名称，非空时在 payload 中注入分支元数据

        Returns:
            Result dict with status and statistics
        """
        logger.info(
            "starting_full_index",
            repository_id=self.repository_id,
            repo_path=repo_path,
        )

        try:
            dimension_setting = await SystemSetting.objects.filter(
                key=SettingKeys.EMBEDDING_DIMENSION
            ).afirst()
            vector_size = int(dimension_setting.value) if dimension_setting else 1024

            hybrid_enabled = await self._is_hybrid_enabled()

            await qdrant_create_collection(self.repository_id, vector_size, hybrid=hybrid_enabled)

            if branch_name:
                await qdrant_create_branch_payload_index(
                    QdrantService.get_collection_name(self.repository_id)
                )

            await update_index_stage(self.repository_id, IndexStage.SCANNING_FILES)
            # fail-closed 排除过滤（EXCL-02）：预取单一匹配器（async 加载），把相对
            # 仓库根路径判定注入同步 scan_directory，被排除文件从源头不进 files。
            exclusion_matcher = await build_matcher_for_repo(self.repository_id)
            files = scan_directory(repo_path, is_excluded_rel=exclusion_matcher.is_excluded)
            logger.info("files_scanned", count=len(files))

            # 续传锚点：上次中断时 _flush_batch 已写入的 (file_path → file_hash)
            await update_index_stage(self.repository_id, IndexStage.LOADING_HASHES)
            stored_records: dict[str, str] = {
                fp: fh
                async for fp, fh in FileIndex.objects.filter(
                    repository_id=self.repository_id,
                ).values_list("file_path", "file_hash")
            }

            total_files = len(files)
            await update_current_indexing_file(
                self.repository_id,
                file_path="",
                processed=0,
                total=total_files,
            )

            # 预扫文件 hash + 决定 skip 名单（hash 命中 stored_records 视作已索引）
            # 注：scan_directory 仅按目录名 + 扩展名白名单 + 排除匹配器过滤（**不应用
            # .gitignore**，PF-04 修正）；被排除文件已在上面 scan_directory 阶段经
            # is_excluded_rel 剔除，files 即"应被索引集"。
            file_hashes_local: dict[str, str] = {}
            files_to_process: list[tuple[str, str, str]] = []  # (abs_path, rel_path, hash)
            skipped_resume = 0
            for abs_path in files:
                rel_path = os.path.relpath(abs_path, repo_path)
                fh = compute_file_hash(abs_path)
                file_hashes_local[rel_path] = fh
                if stored_records.get(rel_path) == fh:
                    skipped_resume += 1
                    continue
                files_to_process.append((abs_path, rel_path, fh))

            if skipped_resume > 0:
                logger.info(
                    "full_index_resume_skipped",
                    repository_id=self.repository_id,
                    skipped=skipped_resume,
                    remaining=len(files_to_process),
                    total=total_files,
                )

            # 文件级进度从"已 skip 数"起步 — 中断续传时百分比不归零
            await update_current_indexing_file(
                self.repository_id,
                file_path="",
                processed=skipped_resume,
                total=total_files,
            )

            # 没有需要处理的文件（要么仓库为空，要么所有文件已索引完成）
            if not files_to_process:
                await update_index_progress(self.repository_id, 0, 0)
                # 即便没有新文件，仍需走 graph + summary 兜底；但若总文件数也是 0
                # 则按"空仓库"短路
                if total_files == 0:
                    return {
                        "status": "success",
                        "files_processed": 0,
                        "chunks_indexed": 0,
                        "added": 0,
                    }

            # contract：解析阶段也用稳定的"索引文件中..."文案；整体百分比不再由
            # 文件 parse 计数直接驱动到 100%，而是在得到 chunk 总量后切到
            # embedding/upsert 的真实进度。
            await update_index_stage(self.repository_id, IndexStage.INDEXING_FILES)

            file_payloads: list[tuple[str, str, list[CodeChunk]]] = []
            processed_files_total = skipped_resume  # 已 skip 也计入文件处理数
            for abs_path, rel_path, file_hash in files_to_process:
                processed_files_total += 1
                await update_current_indexing_file(
                    self.repository_id,
                    file_path=rel_path,
                    processed=processed_files_total,
                )
                chunks, _bundle = self.parser.parse_file_dual(
                    abs_path, base_path=repo_path, repository_id=self.repository_id
                )
                if _bundle is not None:
                    self._session_graph_bundles[rel_path] = _bundle
                file_payloads.append((rel_path, file_hash, chunks))

            # 一次性批量查 commit 信息（避免每次 flush 都 spawn git log）
            last_commit_map = await get_files_last_commit(
                repo_path,
                [rel for rel, _, _ in file_payloads],
            )

            total_chunks = sum(len(chunks) for _, _, chunks in file_payloads)
            if total_chunks > 0:
                await update_index_progress(self.repository_id, total_chunks, 0)
                await update_write_progress(self.repository_id, total_chunks, 0)

            # 文件级 batch：累积到 FILE_BATCH_CHUNK_THRESHOLD 即触发一次 flush
            pending_chunks: list[CodeChunk] = []
            pending_files: list[tuple[str, str]] = []  # (rel_path, hash)
            processed_chunks_total = 0
            chunks_indexed_total = 0  # 实际 upsert 到 qdrant 的 chunk 数

            async def _flush_batch() -> None:
                """把 pending_chunks 一次性 embed + upsert + 写 FileIndex 锚点。

                注：``processed_files_total`` 在主循环 parse 时已递增过，本函数
                不再二次累加；FileIndex 的写入才是续传锚点的真正落地动作。
                """
                nonlocal processed_chunks_total, chunks_indexed_total
                if not pending_files:
                    return

                # 空 chunks batch（仅空文件）也要落 FileIndex，避免下次再 parse
                if not pending_chunks:
                    for fp, fh in pending_files:
                        commit_info = last_commit_map.get(fp)
                        defaults: dict[str, Any] = {"file_hash": fh}
                        if commit_info:
                            defaults["last_commit_sha"] = commit_info[0]
                            defaults["last_commit_authored_at"] = _ts_to_dt(commit_info[1])
                        await FileIndex.objects.aupdate_or_create(
                            repository_id=self.repository_id,
                            file_path=fp,
                            defaults=defaults,
                        )
                    pending_files.clear()
                    return

                # contract：embed 阶段用 batch 末尾文件作为"代表文件"持续推进 UI；
                # 不切 stage，让外层"索引文件中..."文案保持稳定
                rep_file = pending_files[-1][0]
                await update_current_indexing_file(
                    self.repository_id,
                    file_path=rep_file,
                )

                texts = [_build_embedding_text(c) for c in pending_chunks]
                embeddings = await EmbeddingService.generate_embeddings_batch(texts)

                sparse_vectors: list[dict] | None = None
                if hybrid_enabled:
                    sparse_vectors = await sync_to_async(self._generate_sparse_vectors)(texts)

                points, registry_rows = self._build_points(
                    pending_chunks,
                    embeddings,
                    sparse_vectors,
                    hybrid_enabled,
                    repository_id=self.repository_id,
                    branch_name=branch_name,
                    is_base_branch=branch_name is not None,
                )

                # upsert 失败必须 raise，否则 FileIndex 锚点错误地标"已完成"
                # 导致下次续传跳过这批文件 → 数据永久丢失。upsert_vectors 返回 False 含义：
                # Qdrant 业务异常 / 网络异常（含 timeout）已被记录但未恢复。
                upsert_batch_size = 100
                total_batches = (len(points) + upsert_batch_size - 1) // upsert_batch_size
                for i in range(0, len(points), upsert_batch_size):
                    batch_no = i // upsert_batch_size + 1
                    batch = points[i : i + upsert_batch_size]
                    # contract：stage 文案以"全局 chunk 进度"为口径（processed_chunks_total
                    # 累加发生在 upsert 成功之后，这里预报"本批写入完后"的累计值，
                    # 避免文案显示落后一拍 / 永远卡在 1/1 的误导）。
                    chunks_after_this_batch = processed_chunks_total + min(
                        i + upsert_batch_size,
                        len(points),
                    )
                    await update_index_stage(
                        self.repository_id,
                        f"写入向量库... ({chunks_after_this_batch}/{total_chunks} chunks)",
                    )
                    logger.debug(
                        "qdrant_upsert_batch_start",
                        repository_id=self.repository_id,
                        representative_file=rep_file,
                        batch_no=batch_no,
                        total_batches=total_batches,
                        batch_size=len(batch),
                        total_points=len(points),
                    )
                    ok = await qdrant_upsert_vectors(self.repository_id, batch)
                    if not ok:
                        message = _build_upsert_failure_message(
                            representative_file=rep_file,
                            batch_no=batch_no,
                            total_batches=total_batches,
                            batch_size=len(batch),
                            total_points=len(points),
                        )
                        logger.error(
                            "qdrant_upsert_batch_failed",
                            repository_id=self.repository_id,
                            representative_file=rep_file,
                            batch_no=batch_no,
                            total_batches=total_batches,
                            batch_size=len(batch),
                            total_points=len(points),
                        )
                        raise RuntimeError(message)
                    logger.debug(
                        "qdrant_upsert_batch_complete",
                        repository_id=self.repository_id,
                        representative_file=rep_file,
                        batch_no=batch_no,
                        total_batches=total_batches,
                        batch_size=len(batch),
                        total_points=len(points),
                    )

                # Qdrant upsert 全部成功 → 同步写 ChunkRegistry（contract / contract 强一致）
                _registry_results = await self._upsert_chunk_registry_batch(registry_rows)
                # implementation（per contract）：累积 dirty chunk_id，
                # _extract_and_write_graph 末尾一次性 enqueue_edge_build
                self._session_dirty_chunk_ids.update(
                    uuid.UUID(point_id) for point_id, _changed in _registry_results
                )

                # upsert 成功 → 立即 flush FileIndex（文件级断点续传锚点）
                for fp, fh in pending_files:
                    commit_info = last_commit_map.get(fp)
                    defaults = {"file_hash": fh}
                    if commit_info:
                        defaults["last_commit_sha"] = commit_info[0]
                        defaults["last_commit_authored_at"] = _ts_to_dt(commit_info[1])
                    await FileIndex.objects.aupdate_or_create(
                        repository_id=self.repository_id,
                        file_path=fp,
                        defaults=defaults,
                    )

                processed_chunks_total += len(pending_chunks)
                chunks_indexed_total += len(points)
                # 兼容性：保持 chunks 计数同步更新，方便老 UI / 监控读
                await update_index_progress(
                    self.repository_id, total_chunks, processed_chunks_total
                )
                await update_write_progress(
                    self.repository_id, total_chunks, processed_chunks_total
                )

                pending_chunks.clear()
                pending_files.clear()

            # 主循环：已完成 parse → 按 chunk batch embed/upsert → flush FileIndex。
            # FileIndex 的写入仍是续传锚点；parse 完但未 flush 的文件下次会重做。
            for rel_path, file_hash, chunks in file_payloads:
                pending_chunks.extend(chunks)
                pending_files.append((rel_path, file_hash))

                if len(pending_chunks) >= FILE_BATCH_CHUNK_THRESHOLD:
                    await _flush_batch()

            # 末批 flush（哪怕只有空文件 / chunk 数不足阈值）
            if pending_files:
                await _flush_batch()

            logger.info(
                "indexing_complete",
                repository_id=self.repository_id,
                chunks_indexed=chunks_indexed_total,
                files_processed=processed_files_total,
                skipped_resume=skipped_resume,
                hybrid=hybrid_enabled,
            )

            # 创建/更新 RepositoryBranchIndex 记录并传播 stale
            if branch_name:
                await self._update_branch_index_record(
                    repo_path=repo_path,
                    branch_name=branch_name,
                    is_base_branch=True,
                    points_count=chunks_indexed_total,
                )

            # contract：主向量轨完成 → 立刻持久化"已索引"元数据。
            # 这步关键：后续 graph + summary 阶段调 LLM 可能很慢或中断（autoreload
            # / 服务重启 / OOM），但仓库的"新鲜度"元数据已经落地，
            # 用户能立刻看到 Hash 新鲜度卡片显示 fresh。
            await persist_vector_track_complete(self.repository_id, repo_path)

            # 图谱轨写入（失败不影响"已索引"状态）
            # implementation-02：双重判断后再决定是否构图（CONTEXT 决议留 implementation
            # 薄壳形态——判断在调用方层而非 _extract_and_write_graph 函数体内部）。
            # run_full_index 无 history_id 形参，_should_build_graph 走 fallback 查 RUNNING。
            await update_index_stage(self.repository_id, IndexStage.BUILDING_GRAPH)
            # files 来自 scan_directory(repo_path) 是绝对路径；图谱要求相对路径，
            # 否则 DB 里 file_path 会变成 /var/folders/.../friday_index_xxx/...
            # 这种 tmp 前缀，导致前端代码图谱定位/调用关系全部对不上。
            graph_file_paths = [os.path.relpath(p, repo_path) for p in files]
            if await self._should_build_graph(None):
                # implementation-01..05：auto_after_index 路径写
                # GraphBuildHistory 行；薄壳 `_extract_and_write_graph` 不感知
                # history（保 success criterion byte-equivalent），由 callsite 外层 wrap。
                # 仍在 indexer 主任务（index-{repo_id}）内运行——不切新 task。
                gbh = await self._acreate_auto_graph_history()
                # implementation-01：auto_after_index 路径入口 reset
                # Repository 5 字段（与 manual 路径 build_graph_for_repository
                # 入口对齐——保 view 层读 Repository.graph_* 字段统一）。
                await reset_repository_graph_progress(self.repository_id)
                # security mitigation-5：示范切换 plan 02 update_graph_progress stub helper
                # （implementation 才落字段写入，本 phase 仅 structlog 通路验证）。
                await update_graph_progress(
                    self.repository_id,
                    stage="building_graph",
                    processed=0,
                    total=len(graph_file_paths),
                )
                try:
                    stats = await self._extract_and_write_graph(
                        repo_path=repo_path,
                        file_paths=graph_file_paths,
                        repository_id=self.repository_id,
                        # base 全量索引：硬传 ""，保 base chunk_id/图谱行字节不变（Pitfall 4）。
                        # 本路径无本次 IndexHistory.id 在 scope，history_id=None 走 lifecycle fallback。
                        branch_name="",
                        history_id=None,
                    )
                    stats = stats or {}
                    gbh.status = GraphBuildHistoryStatus.COMPLETED
                    gbh.files_total = len(graph_file_paths)
                    gbh.files_processed = stats.get("files_processed", 0)
                    gbh.files_failed = stats.get("files_failed", 0)
                    gbh.symbols_count = stats.get("total_symbols", 0)
                    gbh.imports_count = stats.get("total_imports", 0)
                    gbh.calls_count = stats.get("total_calls", 0)
                    gbh.endpoints_count = stats.get("total_endpoints", 0)
                    gbh.finished_at = timezone.now()
                    await gbh.asave(
                        update_fields=[
                            "status",
                            "files_total",
                            "files_processed",
                            "files_failed",
                            "symbols_count",
                            "imports_count",
                            "calls_count",
                            "endpoints_count",
                            "finished_at",
                        ]
                    )
                    # implementation-01：成功终态写 Repository。
                    await mark_repository_graph_terminal(
                        self.repository_id,
                        status=RepositoryGraphStatus.COMPLETED,
                        stage="完成",
                        current_file="",
                        files_processed=stats.get("files_processed", 0),
                        files_total=len(graph_file_paths),
                    )
                except Exception as exc:
                    gbh.status = GraphBuildHistoryStatus.FAILED
                    gbh.error_message = str(exc)[:1000]
                    gbh.finished_at = timezone.now()
                    await gbh.asave(update_fields=["status", "error_message", "finished_at"])
                    # implementation-01：失败终态写 Repository（保留
                    # 最后写入的 current_graph_file，CONTEXT 失败路径决议）。
                    await mark_repository_graph_terminal(
                        self.repository_id,
                        status=RepositoryGraphStatus.FAILED,
                        stage="",
                    )
                    logger.warning(
                        "extract_and_write_graph_failed",
                        repository_id=self.repository_id,
                        exc_info=True,
                    )
                    # contract 不变量：图谱失败不阻塞向量轨 INDEXED；不 raise

            # implementation (per contract): 异步构建仓库摘要索引，失败不回滚索引
            await update_index_stage(self.repository_id, IndexStage.FINALIZING)
            try:
                from codegraph.services.repo_summary_builder import RepoSummaryBuilder

                await RepoSummaryBuilder.build(repository_id=self.repository_id)
            except Exception:
                logger.warning(
                    "repo_summary_build_failed",
                    repository_id=self.repository_id,
                    exc_info=True,
                )

            # PageIndex 事实层刷新（零 LLM）：能力树节点 payload 的事实分面/
            # api_domains 随索引完成重算；失败不回滚索引。
            await self._refresh_tree_facts()

            # EXCL-03（Plan 24-02，BL-01）：敏感文件检测**不再**在此后台派发。
            # 早前在此把检测协程经后台 runner 投递去遍历 repo_path，而上层
            # ``clone_and_index_repository`` 在 ``finally`` 中 ``shutil.rmtree(temp_dir)``——
            # 二者形成竞态，后台遍历几乎必然撞上已删除/正被删除的临时克隆目录 → 静默漏报全部
            # 密钥。检测改由 ``clone_and_index_repository`` 在删除 temp_dir **之前**同步触发
            # （只读 + 全局有界），确保读到真实克隆文件。详见模块级 ``_run_sensitive_detection``。

            return {
                "status": "success",
                "files_processed": total_files,
                "chunks_indexed": chunks_indexed_total,
                "added": total_files,  # 全量索引所有文件视为新增（向后兼容契约）
            }

        except Exception as e:
            logger.error(
                "indexing_failed",
                repository_id=self.repository_id,
                error=str(e),
            )
            raise

    async def _refresh_tree_facts(self) -> None:
        """PageIndex 事实层刷新：树节点 payload 的分面/API 域随索引重算（零 LLM）。

        仅当仓库已有能力树时执行；失败不冒泡（不阻塞索引 INDEXED 终态）。
        """
        try:
            from codegraph.services.repo_index_tree import RepoIndexTreeBuilder
            from repositories.facet_service import FacetService
            from repositories.models import Repository

            repo = await Repository.objects.filter(id=self.repository_id).afirst()
            if repo is None or not repo.ai_summary_tree:
                return
            await FacetService.refresh_fact_facets(self.repository_id)
            await RepoIndexTreeBuilder.refresh_facts(self.repository_id)
        except Exception:
            logger.warning(
                "tree_facts_refresh_failed",
                repository_id=self.repository_id,
                exc_info=True,
            )

    async def _update_branch_index_record(
        self,
        *,
        repo_path: str,
        branch_name: str,
        is_base_branch: bool,
        points_count: int,
    ) -> None:
        """创建/更新 RepositoryBranchIndex 记录，base 分支索引后触发 overlay stale 传播。"""
        head_sha = await _get_head_sha(repo_path)
        await RepositoryBranchIndex.objects.aupdate_or_create(
            repository_id=self.repository_id,
            branch_name=branch_name,
            defaults={
                "is_base_branch": is_base_branch,
                "head_sha": head_sha,
                "last_indexed_commit_sha": head_sha,
                "last_indexed_at": timezone.now(),
                "is_stale": False,
                "status": BranchIndexStatus.INDEXED,
                "effective_chunks_count": points_count,
                "collection_name": QdrantService.get_collection_name(self.repository_id),
            },
        )

        if is_base_branch:
            stale_count = await RepositoryBranchIndex.objects.filter(
                repository_id=self.repository_id,
                is_base_branch=False,
            ).aupdate(is_stale=True)
            if stale_count:
                logger.info(
                    "overlays_marked_stale",
                    repository_id=self.repository_id,
                    count=stale_count,
                )

    async def run_branch_index(
        self,
        repo_path: str,
        branch_name: str,
        repository: Repository,
    ) -> dict[str, Any]:
        """功能分支 overlay 索引：merge-base + diff → overlay collection。

        无差异时标记 inherited_from_base，不创建 overlay。

        Args:
            repo_path: 克隆仓库路径
            branch_name: 功能分支名称
            repository: 仓库 ORM 实例

        Returns:
            Result dict with status/stats

        Raises:
            BranchOverlayLimitExceeded: overlay 数量超过硬上限
            GitDiffError: git 操作失败
        """
        base_branch = repository.default_branch

        # overlay 硬上限检查
        overlay_count = (
            await RepositoryBranchIndex.objects.filter(
                repository=repository,
                is_base_branch=False,
            )
            .exclude(status=BranchIndexStatus.INHERITED)
            .acount()
        )
        if overlay_count >= MAX_OVERLAY_COLLECTIONS_PER_REPO:
            raise BranchOverlayLimitExceeded(
                f"仓库 {repository.name} 已有 {overlay_count} 个 overlay collection，"
                f"超过上限 {MAX_OVERLAY_COLLECTIONS_PER_REPO}"
            )

        # fetch feature branch
        await _fetch_branch(repo_path, branch_name, repository.proxy_url)

        # 获取 merge-base
        is_shallow = await _is_shallow_clone(repo_path)
        feature_ref = f"origin/{branch_name}"
        if is_shallow:
            merge_base_sha = await _deepen_for_merge_base(
                repo_path,
                base_branch,
                feature_ref,
                repository.proxy_url,
            )
        else:
            merge_base_sha = await _get_merge_base(repo_path, base_branch, feature_ref)

        # 获取 feature HEAD SHA
        proc = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            feature_ref,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode != 0:
            raise GitDiffError(f"无法解析 {feature_ref} 的 HEAD")
        feature_head = stdout.decode().strip()

        # git diff
        diff_proc = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            "--name-status",
            "--find-renames",
            merge_base_sha,
            feature_head,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        diff_stdout, diff_stderr = await asyncio.wait_for(diff_proc.communicate(), timeout=30.0)
        if diff_proc.returncode != 0:
            raise GitDiffError(f"git diff failed: {diff_stderr.decode()}")

        diffs = _parse_git_diff_output(diff_stdout.decode())

        # 无差异 → inherited_from_base
        if not diffs:
            await RepositoryBranchIndex.objects.aupdate_or_create(
                repository=repository,
                branch_name=branch_name,
                defaults={
                    "status": BranchIndexStatus.INHERITED,
                    "merge_base_sha": merge_base_sha,
                    "is_base_branch": False,
                    "is_stale": False,
                    "head_sha": feature_head,
                },
            )
            logger.info(
                "branch_inherited_from_base", branch=branch_name, repository=repository.name
            )
            return {"status": "inherited", "diff_files": 0}

        # 有差异 → 创建/确保 overlay collection
        collection_name = get_overlay_collection_name(str(repository.id), branch_name)
        dimension_setting = await SystemSetting.objects.filter(
            key=SettingKeys.EMBEDDING_DIMENSION,
        ).afirst()
        vector_size = int(dimension_setting.value) if dimension_setting else 1024
        hybrid_enabled = await self._is_hybrid_enabled()

        await qdrant_create_collection_by_name(collection_name, vector_size, hybrid=hybrid_enabled)
        await sync_to_async(QdrantService.create_branch_payload_index)(collection_name)

        # checkout feature branch 文件
        checkout_proc = await asyncio.create_subprocess_exec(
            "git",
            "checkout",
            feature_ref,
            "--",
            ".",
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(checkout_proc.communicate(), timeout=60.0)

        # 仅索引 ADD / UPDATE 文件
        files_to_index = [d for d in diffs if d.action in (DiffAction.ADD, DiffAction.UPDATE)]
        # ME-02：分支 overlay 与全量/增量同口径应用排除过滤，从源头剔除被排除文件，
        # 避免 `server/.env` 等被排除文件写入 overlay collection（fail-closed）。
        branch_exclusion_matcher = await build_matcher_for_repo(self.repository_id)
        files_to_index = [
            d for d in files_to_index if not branch_exclusion_matcher.is_excluded(d.file_path)
        ]
        points: list[dict] = []

        if files_to_index:
            all_chunks: list[CodeChunk] = []
            for diff in files_to_index:
                full_path = os.path.join(repo_path, diff.file_path)
                if os.path.exists(full_path):
                    chunks, _bundle = self.parser.parse_file_dual(
                        full_path, base_path=repo_path, repository_id=self.repository_id
                    )
                    if _bundle is not None:
                        self._session_graph_bundles[diff.file_path] = _bundle
                    all_chunks.extend(chunks)

            if all_chunks:
                texts_to_embed = [_build_embedding_text(chunk) for chunk in all_chunks]
                embeddings = await EmbeddingService.generate_embeddings_batch(texts_to_embed)

                sparse_vectors: list[dict] | None = None
                if hybrid_enabled:
                    sparse_vectors = await sync_to_async(self._generate_sparse_vectors)(
                        texts_to_embed
                    )

                points, registry_rows = self._build_points(
                    all_chunks,
                    embeddings,
                    sparse_vectors,
                    hybrid_enabled,
                    repository_id=self.repository_id,
                    branch_name=branch_name,
                    is_base_branch=False,
                )

                # upsert to overlay collection
                batch_size = 100
                for i in range(0, len(points), batch_size):
                    batch = points[i : i + batch_size]
                    await qdrant_upsert_vectors_by_name(collection_name, batch)

                # Qdrant upsert 全部成功 → 同步写 ChunkRegistry（contract / contract 强一致）
                _registry_results = await self._upsert_chunk_registry_batch(registry_rows)
                # implementation（per contract）：累积 dirty chunk_id，
                # _extract_and_write_graph 末尾一次性 enqueue_edge_build
                self._session_dirty_chunk_ids.update(
                    uuid.UUID(point_id) for point_id, _changed in _registry_results
                )

        # 记录 BranchFileIndex
        branch_index, _ = await RepositoryBranchIndex.objects.aupdate_or_create(
            repository=repository,
            branch_name=branch_name,
            defaults={
                "is_base_branch": False,
                "head_sha": feature_head,
                "merge_base_sha": merge_base_sha,
                "last_indexed_commit_sha": feature_head,
                "last_indexed_at": timezone.now(),
                "is_stale": False,
                "status": BranchIndexStatus.INDEXED,
                "effective_chunks_count": len(points),
                "collection_name": collection_name,
            },
        )

        await BranchFileIndex.objects.filter(branch_index=branch_index).adelete()
        file_index_objs = [
            BranchFileIndex(
                branch_index=branch_index,
                file_path=d.file_path,
                change_type=d.action.value,
            )
            for d in diffs
        ]
        if file_index_objs:
            await BranchFileIndex.objects.abulk_create(file_index_objs)

        logger.info(
            "branch_overlay_index_complete",
            branch=branch_name,
            repository=repository.name,
            diff_files=len(diffs),
            indexed_files=len(files_to_index),
            chunks=len(points),
        )

        # 图谱轨写入
        # implementation-02：双重判断 gating（run_branch_index 无 history_id 形参，
        # _should_build_graph 走 fallback 查 RUNNING）。
        if files_to_index and await self._should_build_graph(None):
            graph_files = [d.file_path for d in files_to_index]
            # implementation-02：先按 deleted_file_paths 清图谱孤儿数据
            # （Symbol / ImportEdge / Endpoint 三件套），再写新图谱避免孤儿过渡态。
            deleted_file_paths = [d.file_path for d in diffs if d.action == DiffAction.DELETE]
            if deleted_file_paths:
                self._init_graph_services()
                if self._graph_writer is not None:
                    try:
                        # contract H-1：feature overlay 删除孤儿必须带 branch_name，
                        # 否则会误删 base 图谱行（run_branch_index 必为 feature 分支）。
                        await self._graph_writer.adelete_for_files(
                            str(self.repository_id),
                            deleted_file_paths,
                            branch_name=_resolve_write_branch(repository, branch_name),
                        )
                    except Exception:
                        logger.warning(
                            "graph_orphan_cleanup_failed",
                            repository_id=str(self.repository_id),
                            deleted_count=len(deleted_file_paths),
                            exc_info=True,
                        )
            # implementation-01..05：auto_after_index 路径写
            # GraphBuildHistory（与 callsite #1 共用模板）。
            gbh = await self._acreate_auto_graph_history()
            # implementation-01：入口 reset Repository 5 字段。
            await reset_repository_graph_progress(self.repository_id)
            try:
                # contract：feature overlay 索引，归一化分支名后透传（==base 仍归 ""）。
                # run_branch_index 无本次 IndexHistory.id 在 scope，history_id=None 走 fallback。
                stats = await self._extract_and_write_graph(
                    repo_path=repo_path,
                    file_paths=graph_files,
                    repository_id=self.repository_id,
                    branch_name=_resolve_write_branch(repository, branch_name),
                    history_id=None,
                )
                stats = stats or {}
                gbh.status = GraphBuildHistoryStatus.COMPLETED
                gbh.files_total = len(graph_files)
                gbh.files_processed = stats.get("files_processed", 0)
                gbh.files_failed = stats.get("files_failed", 0)
                gbh.symbols_count = stats.get("total_symbols", 0)
                gbh.imports_count = stats.get("total_imports", 0)
                gbh.calls_count = stats.get("total_calls", 0)
                gbh.endpoints_count = stats.get("total_endpoints", 0)
                gbh.finished_at = timezone.now()
                await gbh.asave(
                    update_fields=[
                        "status",
                        "files_total",
                        "files_processed",
                        "files_failed",
                        "symbols_count",
                        "imports_count",
                        "calls_count",
                        "endpoints_count",
                        "finished_at",
                    ]
                )
                # implementation-01：成功终态写 Repository。
                await mark_repository_graph_terminal(
                    self.repository_id,
                    status=RepositoryGraphStatus.COMPLETED,
                    stage="完成",
                    current_file="",
                    files_processed=stats.get("files_processed", 0),
                    files_total=len(graph_files),
                )
            except Exception as exc:
                gbh.status = GraphBuildHistoryStatus.FAILED
                gbh.error_message = str(exc)[:1000]
                gbh.finished_at = timezone.now()
                await gbh.asave(update_fields=["status", "error_message", "finished_at"])
                # implementation-01：失败终态写 Repository（保留
                # 最后写入的 current_graph_file，CONTEXT 失败路径决议）。
                await mark_repository_graph_terminal(
                    self.repository_id,
                    status=RepositoryGraphStatus.FAILED,
                    stage="",
                )
                logger.warning(
                    "extract_and_write_graph_failed",
                    repository_id=self.repository_id,
                    exc_info=True,
                )
                # contract 不变量：图谱失败不阻塞向量轨 INDEXED；不 raise

        return {
            "status": "indexed",
            "diff_files": len(diffs),
            "indexed_files": len(files_to_index),
            "chunks_indexed": len(points),
        }

    async def _ensure_collection(self) -> None:
        """确保 Qdrant collection 存在，不存在则创建。"""
        dimension_setting = await SystemSetting.objects.filter(
            key=SettingKeys.EMBEDDING_DIMENSION
        ).afirst()
        vector_size = int(dimension_setting.value) if dimension_setting else 1024
        hybrid_enabled = await self._is_hybrid_enabled()
        await qdrant_create_collection(self.repository_id, vector_size, hybrid=hybrid_enabled)

    async def run_git_diff_index(
        self,
        repo_path: str,
        from_sha: str,
        to_sha: str,
        *,
        branch_name: str | None = None,
        is_base_branch: bool = False,
        history_id: str | None = None,
    ) -> dict[str, Any]:
        """基于 git diff 的增量索引。

        Args:
            repo_path: 克隆仓库路径
            from_sha: 上次索引的 commit SHA
            to_sha: 当前 HEAD SHA
            branch_name: 分支名称，非空时在 payload 中注入分支元数据
            is_base_branch: 是否为 base 分支
            history_id: 可选的 IndexHistory 记录 ID。给定时会在拿到 git diff 后
                立刻把 from_sha / to_sha / files_added / files_modified /
                files_deleted / changed_files / summary_text 写回该记录，
                让"索引历史"列表中的 RUNNING 行可以实时显示文件增删改统计。

        Returns:
            Result dict with status and statistics

        Raises:
            GitDiffError: git diff 命令执行失败
        """
        logger.info(
            "starting_git_diff_index",
            repository_id=self.repository_id,
            from_sha=from_sha,
            to_sha=to_sha,
        )

        await self._ensure_collection()

        # 执行 git diff
        await update_index_stage(self.repository_id, IndexStage.COMPUTING_DIFF)
        proc = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            "--name-status",
            "--find-renames",
            from_sha,
            to_sha,
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        if proc.returncode != 0:
            raise GitDiffError(f"git diff failed: {stderr.decode()}")

        diffs = _parse_git_diff_output(stdout.decode())

        # 提早把 stats / changed_files 写入 IndexHistory：让前端在索引仍在 RUNNING
        # 时就能看到本次增量的"X 新增 / Y 修改 / Z 删除"和具体文件列表，
        # 而不必等到 indexing 整体完成。
        added_file_paths = [d.file_path for d in diffs if d.action == DiffAction.ADD]
        modified_file_paths = [d.file_path for d in diffs if d.action == DiffAction.UPDATE]
        deleted_file_paths = [d.file_path for d in diffs if d.action == DiffAction.DELETE]

        # implementation（Pitfall 6）：行级 diff 采集，三态落库。
        # 在既有 --name-status 之后对同一对 SHA 追加 numstat（已 fetch 对象的 diff
        # 极廉价）。三态：numstat 成功 → 真实值（含真实 0，二进制文件在解析函数内
        # 计 0）；returncode≠0 / 超时 / 解析异常 → None（绝不写 0），降级写
        # lines_diff_fallback structlog warning 且不抛错、不阻断索引。
        # 全量索引（run_full_index）根本不走本函数 → 字段保持 default=None（天然 null）。
        # 口径（Open Question 1）：numstat 失败即写 null 的诚实降级，本函数内不主动
        # 调 _deepen_for_merge_base 重试（加深作后续优化）。
        lines_added: int | None = None
        lines_deleted: int | None = None
        try:
            numstat_proc = await asyncio.create_subprocess_exec(
                "git",
                "diff",
                "--numstat",
                "-z",
                "--find-renames",
                from_sha,
                to_sha,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            numstat_out, _ = await asyncio.wait_for(numstat_proc.communicate(), timeout=30.0)
            if numstat_proc.returncode == 0:
                lines_added, lines_deleted = _parse_numstat_output(numstat_out.decode())
            else:
                logger.warning(
                    "lines_diff_fallback",
                    reason="numstat_returncode",
                    returncode=numstat_proc.returncode,
                    repository_id=self.repository_id,
                )
        except Exception as exc:  # noqa: BLE001 —— 诚实降级，不阻断索引
            logger.warning(
                "lines_diff_fallback",
                reason="numstat_exception",
                error=str(exc),
                repository_id=self.repository_id,
            )
            lines_added = lines_deleted = None

        if history_id:
            from repositories.models import IndexHistory

            await IndexHistory.objects.filter(id=history_id).aupdate(
                from_sha=from_sha,
                to_sha=to_sha,
                files_added=len(added_file_paths),
                files_modified=len(modified_file_paths),
                files_deleted=len(deleted_file_paths),
                changed_files={
                    "added": added_file_paths,
                    "modified": modified_file_paths,
                    "deleted": deleted_file_paths,
                },
                summary_text=_build_summary_text(
                    len(added_file_paths),
                    len(modified_file_paths),
                    len(deleted_file_paths),
                ),
                # 三态：成功为真实值（含 0），失败/全量为 None（不可计算，前端显示 "—"）
                lines_added=lines_added,
                lines_deleted=lines_deleted,
            )

        if not diffs:
            logger.info("no_changes_detected", repository_id=self.repository_id)
            return {
                "status": "success",
                "added": 0,
                "updated": 0,
                "deleted": 0,
                "renamed": 0,
                "added_files": [],
                "modified_files": [],
                "deleted_files": [],
            }

        stats: dict[str, int] = {"added": 0, "updated": 0, "deleted": 0, "renamed": 0}

        # 处理删除：收敛到统一入口 purge_file（PF-03 + PF-05）——一次清净 Qdrant
        # 主+overlay / FileIndex / ChunkRegistry(+ChunkEdge) / codegraph，消除
        # 「只删 Qdrant 不删 FileIndex/ChunkRegistry」的孤儿残留。
        for diff in diffs:
            if diff.action == DiffAction.DELETE:
                await purge_file(self.repository_id, diff.file_path)
                stats["deleted"] += 1

        # 处理 rename（仅元数据更新）
        for diff in diffs:
            if diff.action == DiffAction.RENAME and diff.old_path:
                await qdrant_update_file_path(self.repository_id, diff.old_path, diff.file_path)
                stats["renamed"] += 1

        # 处理新增和修改
        files_to_index = [d for d in diffs if d.action in (DiffAction.ADD, DiffAction.UPDATE)]
        if files_to_index:
            # === 文件级断点续传：用 FileIndex hash 过滤已成功完成的文件 ===
            # 上次中断时已成功 upsert 完成的文件会在 FileIndex 中留下 hash 记录，
            # 重试时如果 working dir 中文件 hash 与之相同 → 跳过 embedding，避免浪费。
            await update_index_stage(self.repository_id, IndexStage.LOADING_HASHES)
            stored_hashes: dict[str, str] = {
                fp: fh
                async for fp, fh in FileIndex.objects.filter(
                    repository_id=self.repository_id
                ).values_list("file_path", "file_hash")
            }

            # 一次性 parse 所有未跳过的文件，便于事先得到准确的 total_chunks 给 UI 进度条
            # contract：用 INDEXING_FILES 统一文案，避免 _flush_batch 内部 stage 切换抖动
            await update_index_stage(self.repository_id, IndexStage.INDEXING_FILES)
            await update_current_indexing_file(
                self.repository_id,
                file_path="",
                processed=0,
                total=len(files_to_index),
            )
            file_payloads: list[tuple[Any, str, list[CodeChunk]]] = []  # (diff, hash, chunks)
            skipped_resume_count = 0
            for parse_idx, diff in enumerate(files_to_index, start=1):
                await update_current_indexing_file(
                    self.repository_id,
                    file_path=diff.file_path,
                    processed=parse_idx,
                )
                full_path = os.path.join(repo_path, diff.file_path)
                # isfile 而非 exists：git diff 的变更条目可能是 submodule（gitlink）
                # 或已变成目录的路径，exists 对目录也为 True，会让下方 compute_file_hash
                # 用 open() 读目录抛 [Errno 21] Is a directory，导致整个索引失败。
                if not os.path.isfile(full_path):
                    continue
                current_hash = compute_file_hash(full_path)
                if stored_hashes.get(diff.file_path) == current_hash:
                    # 上次已成功 upsert，且文件没再变 → 跳过
                    skipped_resume_count += 1
                    if diff.action == DiffAction.UPDATE:
                        stats["updated"] += 1
                    else:
                        stats["added"] += 1
                    continue
                chunks, _bundle = self.parser.parse_file_dual(
                    full_path, base_path=repo_path, repository_id=self.repository_id
                )
                if _bundle is not None:
                    self._session_graph_bundles[diff.file_path] = _bundle
                file_payloads.append((diff, current_hash, chunks))

            # 批量查询变更文件各自的最近 commit（一次 git log 调用），供 FileIndex 写入
            last_commit_map = await get_files_last_commit(
                repo_path,
                [diff.file_path for diff, _, _ in file_payloads],
            )

            if skipped_resume_count > 0:
                logger.info(
                    "files_skipped_by_file_index_resume",
                    repository_id=self.repository_id,
                    count=skipped_resume_count,
                )

            total_chunks = sum(len(c) for _, _, c in file_payloads)
            if total_chunks > 0:
                await update_index_progress(self.repository_id, total_chunks, 0)
                await update_write_progress(self.repository_id, total_chunks, 0)

            # 文件级 batch：累积到 FILE_BATCH_CHUNK_THRESHOLD 触发一次
            # embed → upsert → flush FileIndex（保证文件级原子性）
            pending_chunks: list[CodeChunk] = []
            pending_files: list[tuple[str, str]] = []  # (file_path, file_hash)
            processed_chunks_total = 0
            hybrid_enabled_cache: bool | None = None

            async def _flush_batch() -> None:
                nonlocal processed_chunks_total, hybrid_enabled_cache
                if not pending_chunks:
                    # 仍可能有"空文件"待 flush（无 chunks 但需要记 FileIndex）
                    for fp, fh in pending_files:
                        commit_info = last_commit_map.get(fp)
                        defaults = {"file_hash": fh}
                        if commit_info:
                            defaults["last_commit_sha"] = commit_info[0]
                            defaults["last_commit_authored_at"] = _ts_to_dt(commit_info[1])
                        await FileIndex.objects.aupdate_or_create(
                            repository_id=self.repository_id,
                            file_path=fp,
                            defaults=defaults,
                        )
                    pending_files.clear()
                    return

                if hybrid_enabled_cache is None:
                    hybrid_enabled_cache = await self._is_hybrid_enabled()
                hybrid_enabled = hybrid_enabled_cache

                # contract：不切 stage，让外层稳定文案保持不变
                texts = [_build_embedding_text(c) for c in pending_chunks]
                embeddings = await EmbeddingService.generate_embeddings_batch(texts)

                sparse_vectors: list[dict] | None = None
                if hybrid_enabled:
                    sparse_vectors = await sync_to_async(self._generate_sparse_vectors)(texts)

                points, registry_rows = self._build_points(
                    pending_chunks,
                    embeddings,
                    sparse_vectors,
                    hybrid_enabled,
                    repository_id=self.repository_id,
                    branch_name=branch_name,
                    is_base_branch=is_base_branch,
                )

                # upsert 失败必须 raise（详见 run_full_index._flush_batch 的同款注释）
                upsert_batch_size = 100
                total_batches = (len(points) + upsert_batch_size - 1) // upsert_batch_size
                representative_file = pending_files[-1][0] if pending_files else "<unknown>"
                for i in range(0, len(points), upsert_batch_size):
                    batch_no = i // upsert_batch_size + 1
                    batch = points[i : i + upsert_batch_size]
                    # contract：以全局 chunk 进度为 stage 口径（见 run_full_index._flush_batch
                    # 同款注释）。预报"本批写入完后"的累计值，避免文案永远 1/1。
                    chunks_after_this_batch = processed_chunks_total + min(
                        i + upsert_batch_size,
                        len(points),
                    )
                    await update_index_stage(
                        self.repository_id,
                        f"写入向量库... ({chunks_after_this_batch}/{total_chunks} chunks)",
                    )
                    logger.debug(
                        "qdrant_upsert_batch_start",
                        repository_id=self.repository_id,
                        representative_file=representative_file,
                        batch_no=batch_no,
                        total_batches=total_batches,
                        batch_size=len(batch),
                        total_points=len(points),
                    )
                    ok = await qdrant_upsert_vectors(self.repository_id, batch)
                    if not ok:
                        message = _build_upsert_failure_message(
                            representative_file=representative_file,
                            batch_no=batch_no,
                            total_batches=total_batches,
                            batch_size=len(batch),
                            total_points=len(points),
                        )
                        logger.error(
                            "qdrant_upsert_batch_failed",
                            repository_id=self.repository_id,
                            representative_file=representative_file,
                            batch_no=batch_no,
                            total_batches=total_batches,
                            batch_size=len(batch),
                            total_points=len(points),
                        )
                        raise RuntimeError(message)
                    logger.debug(
                        "qdrant_upsert_batch_complete",
                        repository_id=self.repository_id,
                        representative_file=representative_file,
                        batch_no=batch_no,
                        total_batches=total_batches,
                        batch_size=len(batch),
                        total_points=len(points),
                    )

                # Qdrant upsert 全部成功 → 同步写 ChunkRegistry（contract / contract 强一致）
                _registry_results = await self._upsert_chunk_registry_batch(registry_rows)
                # implementation（per contract）：累积 dirty chunk_id，
                # _extract_and_write_graph 末尾一次性 enqueue_edge_build
                self._session_dirty_chunk_ids.update(
                    uuid.UUID(point_id) for point_id, _changed in _registry_results
                )

                # upsert 成功 → 立即 flush FileIndex（文件级断点续传锚点）
                for fp, fh in pending_files:
                    commit_info = last_commit_map.get(fp)
                    defaults = {"file_hash": fh}
                    if commit_info:
                        defaults["last_commit_sha"] = commit_info[0]
                        defaults["last_commit_authored_at"] = _ts_to_dt(commit_info[1])
                    await FileIndex.objects.aupdate_or_create(
                        repository_id=self.repository_id,
                        file_path=fp,
                        defaults=defaults,
                    )

                processed_chunks_total += len(pending_chunks)
                await update_index_progress(
                    self.repository_id, total_chunks, processed_chunks_total
                )
                await update_write_progress(
                    self.repository_id, total_chunks, processed_chunks_total
                )

                pending_chunks.clear()
                pending_files.clear()

            for diff, file_hash, chunks in file_payloads:
                # UPDATE 路径需要先删除该文件的旧向量再写入新的（文件级幂等）
                if diff.action == DiffAction.UPDATE:
                    await qdrant_delete_by_file_path(self.repository_id, diff.file_path)
                    stats["updated"] += 1
                else:
                    stats["added"] += 1

                pending_chunks.extend(chunks)
                pending_files.append((diff.file_path, file_hash))

                if len(pending_chunks) >= FILE_BATCH_CHUNK_THRESHOLD:
                    await _flush_batch()

            # flush 最后一批
            if pending_chunks or pending_files:
                await _flush_batch()

        logger.info(
            "git_diff_indexing_complete",
            repository_id=self.repository_id,
            stats=stats,
        )
        # 让 return value 也带上变更文件列表，与 run_incremental_index 保持一致
        # （便于 clone_and_index_repository 末尾持久化 changed_files）
        stats_with_files = {
            **stats,
            "added_files": added_file_paths,
            "modified_files": modified_file_paths,
            "deleted_files": deleted_file_paths,
        }

        # 注：FileIndex 已在 _flush_batch 内按文件批增量写入（断点续传锚点），
        # 此处不再做循环末统一更新，避免重复 IO。

        # 更新 RepositoryBranchIndex 记录
        if branch_name:
            total_points = sum(stats.get(k, 0) for k in ("added", "updated"))
            await self._update_branch_index_record(
                repo_path=repo_path,
                branch_name=branch_name,
                is_base_branch=is_base_branch,
                points_count=total_points,
            )

        # contract：主向量轨完成 → 立刻持久化"已索引"元数据（详见 run_full_index 同款注释）
        await persist_vector_track_complete(self.repository_id, repo_path)

        # 图谱轨写入（失败不影响"已索引"状态）
        # implementation-02：双重判断 gating（git_diff 路径已有 history_id 形参）
        graph_files = [d.file_path for d in files_to_index]
        if graph_files and await self._should_build_graph(history_id):
            await update_index_stage(self.repository_id, IndexStage.BUILDING_GRAPH)
            # implementation-02：先按 deleted_file_paths 清孤儿（git_diff 路径
            # 的 deleted_file_paths 已在 line ~1210 提早计算好）。
            # contract H-1：孤儿删除与图谱写入必须用同一归一化分支，否则 feature
            # 分支删除文件会误删 base 图谱行。提前归一化，复用于删除与写入两处。
            _repo_for_branch = await Repository.objects.filter(id=self.repository_id).afirst()
            _write_branch = (
                _resolve_write_branch(_repo_for_branch, branch_name)
                if _repo_for_branch is not None
                else ("" if (branch_name is None or is_base_branch) else branch_name)
            )
            if deleted_file_paths:
                self._init_graph_services()
                if self._graph_writer is not None:
                    try:
                        await self._graph_writer.adelete_for_files(
                            str(self.repository_id),
                            deleted_file_paths,
                            branch_name=_write_branch,
                        )
                    except Exception:
                        logger.warning(
                            "graph_orphan_cleanup_failed",
                            repository_id=str(self.repository_id),
                            deleted_count=len(deleted_file_paths),
                            exc_info=True,
                        )
            # implementation-01..05：auto_after_index 路径写
            # GraphBuildHistory（与 callsite #1 / #2 共用模板）。
            gbh = await self._acreate_auto_graph_history()
            # implementation-01：入口 reset Repository 5 字段。
            await reset_repository_graph_progress(self.repository_id)
            try:
                # contract：复用上方已归一化的 _write_branch（H-1：删除与写入同分支）；
                # 透传本次 IndexHistory.id（history_id 形参）。
                stats = await self._extract_and_write_graph(
                    repo_path=repo_path,
                    file_paths=graph_files,
                    repository_id=self.repository_id,
                    branch_name=_write_branch,
                    history_id=history_id,
                )
                stats = stats or {}
                gbh.status = GraphBuildHistoryStatus.COMPLETED
                gbh.files_total = len(graph_files)
                gbh.files_processed = stats.get("files_processed", 0)
                gbh.files_failed = stats.get("files_failed", 0)
                gbh.symbols_count = stats.get("total_symbols", 0)
                gbh.imports_count = stats.get("total_imports", 0)
                gbh.calls_count = stats.get("total_calls", 0)
                gbh.endpoints_count = stats.get("total_endpoints", 0)
                gbh.finished_at = timezone.now()
                await gbh.asave(
                    update_fields=[
                        "status",
                        "files_total",
                        "files_processed",
                        "files_failed",
                        "symbols_count",
                        "imports_count",
                        "calls_count",
                        "endpoints_count",
                        "finished_at",
                    ]
                )
                # implementation-01：成功终态写 Repository。
                await mark_repository_graph_terminal(
                    self.repository_id,
                    status=RepositoryGraphStatus.COMPLETED,
                    stage="完成",
                    current_file="",
                    files_processed=stats.get("files_processed", 0),
                    files_total=len(graph_files),
                )
            except Exception as exc:
                gbh.status = GraphBuildHistoryStatus.FAILED
                gbh.error_message = str(exc)[:1000]
                gbh.finished_at = timezone.now()
                await gbh.asave(update_fields=["status", "error_message", "finished_at"])
                # implementation-01：失败终态写 Repository。
                await mark_repository_graph_terminal(
                    self.repository_id,
                    status=RepositoryGraphStatus.FAILED,
                    stage="",
                )
                logger.warning(
                    "extract_and_write_graph_failed",
                    repository_id=self.repository_id,
                    exc_info=True,
                )
                # contract 不变量：图谱失败不阻塞向量轨 INDEXED；不 raise

        return {"status": "success", **stats_with_files}

    async def run_incremental_index(
        self,
        repo_path: str,
        *,
        branch_name: str | None = None,
        is_base_branch: bool = False,
        history_id: str | None = None,
    ) -> dict[str, Any]:
        """Run incremental indexing for a repository.

        Args:
            repo_path: Path to the cloned repository
            branch_name: 分支名称，非空时在 payload 中注入分支元数据
            is_base_branch: 是否为基础分支
            history_id: 可选的 IndexHistory 记录 ID，给定时会在 hash 比较出
                差异后立刻把 stats / changed_files 写回该记录，让"索引历史"
                列表中的 RUNNING 行可实时显示文件增删改统计。

        Returns:
            Result dict with status and statistics
        """
        logger.info(
            "starting_incremental_index",
            repository_id=self.repository_id,
        )

        try:
            await self._ensure_collection()
            # DB 级文件去重——从 FileIndex 查询已索引文件的 hash，替代 Qdrant hash 比较
            await update_index_stage(self.repository_id, IndexStage.LOADING_HASHES)
            stored_records = {
                fp: fh
                async for fp, fh in FileIndex.objects.filter(
                    repository_id=self.repository_id
                ).values_list("file_path", "file_hash")
            }
            stored_hashes: dict[str, str] = stored_records

            # Scan local files and compute hashes
            await update_index_stage(self.repository_id, IndexStage.SCANNING_FILES)
            # fail-closed 排除过滤（EXCL-02）：被排除文件不进 local_hashes，使其在
            # _compute_diff 中既不算 ADD 也不算 UPDATE（存量清理留 Phase 23）。
            exclusion_matcher = await build_matcher_for_repo(self.repository_id)
            files = scan_directory(repo_path, is_excluded_rel=exclusion_matcher.is_excluded)
            local_hashes: dict[str, str] = {}
            for file_path in files:
                relative_path = os.path.relpath(file_path, repo_path)
                local_hashes[relative_path] = compute_file_hash(file_path)

            # Compute diff
            await update_index_stage(self.repository_id, IndexStage.COMPUTING_DIFF)
            diffs = self._compute_diff(stored_hashes, local_hashes)

            # 提早把 stats / changed_files 写入 IndexHistory（与 git_diff 路径一致）
            if history_id:
                from repositories.models import IndexHistory

                pre_added = [d.file_path for d in diffs if d.action == DiffAction.ADD]
                pre_modified = [d.file_path for d in diffs if d.action == DiffAction.UPDATE]
                pre_deleted = [d.file_path for d in diffs if d.action == DiffAction.DELETE]
                await IndexHistory.objects.filter(id=history_id).aupdate(
                    files_added=len(pre_added),
                    files_modified=len(pre_modified),
                    files_deleted=len(pre_deleted),
                    changed_files={
                        "added": pre_added,
                        "modified": pre_modified,
                        "deleted": pre_deleted,
                    },
                    summary_text=_build_summary_text(
                        len(pre_added), len(pre_modified), len(pre_deleted)
                    ),
                )

            stats = {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}

            # Process deletions：收敛到统一入口 purge_file（PF-03 + PF-05）。
            # 历史 bug：本路径原先只调 qdrant_delete_by_file_path，不删 FileIndex/
            # ChunkRegistry，留下孤儿（PF-03）。改调 purge_file 一次清净五面（含
            # overlay = PF-05）；下方 FileIndex 删除循环随之移除（已由 purge_file 覆盖）。
            for diff in diffs:
                if diff.action == DiffAction.DELETE:
                    await purge_file(self.repository_id, diff.file_path)
                    stats["deleted"] += 1
                elif diff.action == DiffAction.SKIP:
                    stats["skipped"] += 1

            # Process additions and updates
            files_to_index = [
                diff for diff in diffs if diff.action in (DiffAction.ADD, DiffAction.UPDATE)
            ]

            if files_to_index:
                # 文件级断点续传：解析每个文件并按 FILE_BATCH_CHUNK_THRESHOLD 分批
                # embed → upsert → flush FileIndex（与 run_git_diff_index 同节奏）。
                # 注：本路径已用 hash 比较过 stored_hashes，因此自然跳过未变文件，
                # 不再需要额外的 FileIndex 过滤。
                # contract：用 INDEXING_FILES 统一文案，避免内部 stage 切换抖动
                await update_index_stage(self.repository_id, IndexStage.INDEXING_FILES)
                await update_current_indexing_file(
                    self.repository_id,
                    file_path="",
                    processed=0,
                    total=len(files_to_index),
                )
                file_payloads: list[tuple[Any, str, list[CodeChunk]]] = []
                for parse_idx, diff in enumerate(files_to_index, start=1):
                    await update_current_indexing_file(
                        self.repository_id,
                        file_path=diff.file_path,
                        processed=parse_idx,
                    )
                    full_path = os.path.join(repo_path, diff.file_path)
                    # isfile 而非 exists：防御 submodule / 目录路径混入，避免
                    # compute_file_hash 用 open() 读目录抛 [Errno 21] Is a directory。
                    if not os.path.isfile(full_path):
                        continue
                    file_hash = local_hashes.get(diff.file_path) or compute_file_hash(full_path)
                    chunks, _bundle = self.parser.parse_file_dual(
                        full_path, base_path=repo_path, repository_id=self.repository_id
                    )
                    if _bundle is not None:
                        self._session_graph_bundles[diff.file_path] = _bundle
                    file_payloads.append((diff, file_hash, chunks))

                # 批量查最近 commit
                last_commit_map_inc = await get_files_last_commit(
                    repo_path,
                    [diff.file_path for diff, _, _ in file_payloads],
                )

                total_chunks = sum(len(c) for _, _, c in file_payloads)
                if total_chunks > 0:
                    await update_index_progress(self.repository_id, total_chunks, 0)
                    await update_write_progress(self.repository_id, total_chunks, 0)

                pending_chunks: list[CodeChunk] = []
                pending_files: list[tuple[str, str]] = []
                processed_chunks_total = 0
                hybrid_enabled_cache: bool | None = None

                async def _flush_batch_inc() -> None:
                    nonlocal processed_chunks_total, hybrid_enabled_cache
                    if not pending_chunks:
                        for fp, fh in pending_files:
                            ci = last_commit_map_inc.get(fp)
                            defaults = {"file_hash": fh}
                            if ci:
                                defaults["last_commit_sha"] = ci[0]
                                defaults["last_commit_authored_at"] = _ts_to_dt(ci[1])
                            await FileIndex.objects.aupdate_or_create(
                                repository_id=self.repository_id,
                                file_path=fp,
                                defaults=defaults,
                            )
                        pending_files.clear()
                        return

                    if hybrid_enabled_cache is None:
                        hybrid_enabled_cache = await self._is_hybrid_enabled()
                    hybrid_enabled = hybrid_enabled_cache

                    # contract：不切 stage，保持外层 INDEXING_FILES 稳定文案
                    texts = [_build_embedding_text(c) for c in pending_chunks]
                    embeddings = await EmbeddingService.generate_embeddings_batch(texts)
                    sparse_vectors: list[dict] | None = None
                    if hybrid_enabled:
                        sparse_vectors = await sync_to_async(self._generate_sparse_vectors)(texts)
                    points, registry_rows = self._build_points(
                        pending_chunks,
                        embeddings,
                        sparse_vectors,
                        hybrid_enabled,
                        repository_id=self.repository_id,
                        branch_name=branch_name,
                        is_base_branch=is_base_branch,
                    )
                    # upsert 失败必须 raise（详见 run_full_index._flush_batch 的同款注释）
                    upsert_batch_size = 100
                    total_batches = (len(points) + upsert_batch_size - 1) // upsert_batch_size
                    representative_file = pending_files[-1][0] if pending_files else "<unknown>"
                    for i in range(0, len(points), upsert_batch_size):
                        batch_no = i // upsert_batch_size + 1
                        batch = points[i : i + upsert_batch_size]
                        # contract：以全局 chunk 进度为 stage 口径（见 run_full_index._flush_batch
                        # 同款注释）。预报"本批写入完后"的累计值，避免文案永远 1/1。
                        chunks_after_this_batch = processed_chunks_total + min(
                            i + upsert_batch_size,
                            len(points),
                        )
                        await update_index_stage(
                            self.repository_id,
                            f"写入向量库... ({chunks_after_this_batch}/{total_chunks} chunks)",
                        )
                        logger.debug(
                            "qdrant_upsert_batch_start",
                            repository_id=self.repository_id,
                            representative_file=representative_file,
                            batch_no=batch_no,
                            total_batches=total_batches,
                            batch_size=len(batch),
                            total_points=len(points),
                        )
                        ok = await qdrant_upsert_vectors(self.repository_id, batch)
                        if not ok:
                            message = _build_upsert_failure_message(
                                representative_file=representative_file,
                                batch_no=batch_no,
                                total_batches=total_batches,
                                batch_size=len(batch),
                                total_points=len(points),
                            )
                            logger.error(
                                "qdrant_upsert_batch_failed",
                                repository_id=self.repository_id,
                                representative_file=representative_file,
                                batch_no=batch_no,
                                total_batches=total_batches,
                                batch_size=len(batch),
                                total_points=len(points),
                            )
                            raise RuntimeError(message)
                        logger.debug(
                            "qdrant_upsert_batch_complete",
                            repository_id=self.repository_id,
                            representative_file=representative_file,
                            batch_no=batch_no,
                            total_batches=total_batches,
                            batch_size=len(batch),
                            total_points=len(points),
                        )
                    # Qdrant upsert 全部成功 → 同步写 ChunkRegistry（contract / contract 强一致）
                    _registry_results = await self._upsert_chunk_registry_batch(registry_rows)
                    # implementation（per contract）：累积 dirty chunk_id
                    self._session_dirty_chunk_ids.update(
                        uuid.UUID(point_id) for point_id, _changed in _registry_results
                    )

                    for fp, fh in pending_files:
                        ci = last_commit_map_inc.get(fp)
                        defaults = {"file_hash": fh}
                        if ci:
                            defaults["last_commit_sha"] = ci[0]
                            defaults["last_commit_authored_at"] = _ts_to_dt(ci[1])
                        await FileIndex.objects.aupdate_or_create(
                            repository_id=self.repository_id,
                            file_path=fp,
                            defaults=defaults,
                        )
                    processed_chunks_total += len(pending_chunks)
                    await update_index_progress(
                        self.repository_id, total_chunks, processed_chunks_total
                    )
                    await update_write_progress(
                        self.repository_id, total_chunks, processed_chunks_total
                    )
                    pending_chunks.clear()
                    pending_files.clear()

                for diff, file_hash, chunks in file_payloads:
                    if diff.action == DiffAction.UPDATE:
                        await qdrant_delete_by_file_path(self.repository_id, diff.file_path)
                        stats["updated"] += 1
                    else:
                        stats["added"] += 1

                    pending_chunks.extend(chunks)
                    pending_files.append((diff.file_path, file_hash))

                    if len(pending_chunks) >= FILE_BATCH_CHUNK_THRESHOLD:
                        await _flush_batch_inc()

                if pending_chunks or pending_files:
                    await _flush_batch_inc()

            logger.info(
                "incremental_indexing_complete",
                repository_id=self.repository_id,
                stats=stats,
            )

            # 已移除文件的 FileIndex 记录已由上方 purge_file 删净（PF-03），此处不再重复。
            # 兜底：理论上不会进入（_flush_batch_inc 已 flush），但保留以防遗漏（noop）
            for diff in diffs:
                if diff.action in (DiffAction.ADD, DiffAction.UPDATE):
                    new_hash = local_hashes.get(diff.file_path, "")
                    if new_hash:
                        await FileIndex.objects.aupdate_or_create(
                            repository_id=self.repository_id,
                            file_path=diff.file_path,
                            defaults={"file_hash": new_hash},
                        )

            # contract：主向量轨完成 → 立刻持久化"已索引"元数据（详见 run_full_index 同款注释）
            await persist_vector_track_complete(self.repository_id, repo_path)

            # 图谱轨写入（失败不影响"已索引"状态）
            # implementation-02：双重判断 gating（incremental 路径已有 history_id 形参）
            if files_to_index and await self._should_build_graph(history_id):
                await update_index_stage(self.repository_id, IndexStage.BUILDING_GRAPH)
                graph_files = [d.file_path for d in files_to_index]
                # implementation-02：先按 deleted_file_paths 清孤儿。
                # 注：purge_file 已覆盖 codegraph 删除；此块保留以维持分支归一化语义
                # （_write_branch 精确单分支删除），与 purge_file 幂等不冲突——重复
                # adelete_for_files 为 no-op。
                deleted_file_paths = [d.file_path for d in diffs if d.action == DiffAction.DELETE]
                # contract H-1：孤儿删除与图谱写入必须用同一归一化分支，否则 feature
                # 分支删除文件会误删 base 图谱行。提前归一化，复用于删除与写入两处。
                _repo_for_branch = await Repository.objects.filter(id=self.repository_id).afirst()
                _write_branch = (
                    _resolve_write_branch(_repo_for_branch, branch_name)
                    if _repo_for_branch is not None
                    else ("" if (branch_name is None or is_base_branch) else branch_name)
                )
                if deleted_file_paths:
                    self._init_graph_services()
                    if self._graph_writer is not None:
                        try:
                            await self._graph_writer.adelete_for_files(
                                str(self.repository_id),
                                deleted_file_paths,
                                branch_name=_write_branch,
                            )
                        except Exception:
                            logger.warning(
                                "graph_orphan_cleanup_failed",
                                repository_id=str(self.repository_id),
                                deleted_count=len(deleted_file_paths),
                                exc_info=True,
                            )
                # implementation-01..05：auto_after_index 路径写
                # GraphBuildHistory（与 callsite #1 / #2 / #3 共用模板）。
                gbh = await self._acreate_auto_graph_history()
                # implementation-01：入口 reset Repository 5 字段
                # （置于 update_graph_progress 之前——后者会覆盖 graph_stage
                # 为 "building_graph"，最终生效）。
                await reset_repository_graph_progress(self.repository_id)
                # security mitigation-5：示范切换 plan 02 update_graph_progress stub helper
                # （implementation 才落字段写入，本 phase 仅 structlog 通路验证）。
                await update_graph_progress(
                    self.repository_id,
                    stage="building_graph",
                    processed=0,
                    total=len(graph_files),
                )
                try:
                    # contract：复用上方已归一化的 _write_branch（H-1：删除与写入同分支）；
                    # 透传本次 IndexHistory.id（history_id 形参）。
                    stats = await self._extract_and_write_graph(
                        repo_path=repo_path,
                        file_paths=graph_files,
                        repository_id=self.repository_id,
                        branch_name=_write_branch,
                        history_id=history_id,
                    )
                    stats = stats or {}
                    gbh.status = GraphBuildHistoryStatus.COMPLETED
                    gbh.files_total = len(graph_files)
                    gbh.files_processed = stats.get("files_processed", 0)
                    gbh.files_failed = stats.get("files_failed", 0)
                    gbh.symbols_count = stats.get("total_symbols", 0)
                    gbh.imports_count = stats.get("total_imports", 0)
                    gbh.calls_count = stats.get("total_calls", 0)
                    gbh.endpoints_count = stats.get("total_endpoints", 0)
                    gbh.finished_at = timezone.now()
                    await gbh.asave(
                        update_fields=[
                            "status",
                            "files_total",
                            "files_processed",
                            "files_failed",
                            "symbols_count",
                            "imports_count",
                            "calls_count",
                            "endpoints_count",
                            "finished_at",
                        ]
                    )
                    # implementation-01：成功终态写 Repository。
                    await mark_repository_graph_terminal(
                        self.repository_id,
                        status=RepositoryGraphStatus.COMPLETED,
                        stage="完成",
                        current_file="",
                        files_processed=stats.get("files_processed", 0),
                        files_total=len(graph_files),
                    )
                except Exception as exc:
                    gbh.status = GraphBuildHistoryStatus.FAILED
                    gbh.error_message = str(exc)[:1000]
                    gbh.finished_at = timezone.now()
                    await gbh.asave(update_fields=["status", "error_message", "finished_at"])
                    # implementation-01：失败终态写 Repository。
                    await mark_repository_graph_terminal(
                        self.repository_id,
                        status=RepositoryGraphStatus.FAILED,
                        stage="",
                    )
                    logger.warning(
                        "extract_and_write_graph_failed",
                        repository_id=self.repository_id,
                        exc_info=True,
                    )
                    # contract 不变量：图谱失败不阻塞向量轨 INDEXED；不 raise

            # implementation (per contract): 异步构建仓库摘要索引，失败不回滚索引
            await update_index_stage(self.repository_id, IndexStage.FINALIZING)
            try:
                from codegraph.services.repo_summary_builder import RepoSummaryBuilder

                await RepoSummaryBuilder.build(repository_id=self.repository_id)
            except Exception:
                logger.warning(
                    "repo_summary_build_failed",
                    repository_id=self.repository_id,
                    exc_info=True,
                )

            # contract（方案 A）：contract — 返回变更文件路径列表，供调用方持久化到 IndexHistory
            added_file_paths = [d.file_path for d in diffs if d.action == DiffAction.ADD]
            modified_file_paths = [d.file_path for d in diffs if d.action == DiffAction.UPDATE]
            deleted_file_paths = [d.file_path for d in diffs if d.action == DiffAction.DELETE]

            # PageIndex 增量分层刷新：
            # 1. 树结构层——diff 映射到节点 stale 标记，阈值触发异步重建（claude code）
            # 2. 事实层——节点 payload 事实字段零 LLM 重算
            try:
                from codegraph.services.tree_freshness import apply_index_delta

                await apply_index_delta(
                    self.repository_id,
                    added_file_paths + modified_file_paths + deleted_file_paths,
                )
            except Exception:
                logger.warning(
                    "tree_freshness_apply_failed",
                    repository_id=self.repository_id,
                    exc_info=True,
                )
            await self._refresh_tree_facts()

            return {
                "status": "success",
                **stats,
                "added_files": added_file_paths,
                "modified_files": modified_file_paths,
                "deleted_files": deleted_file_paths,
            }

        except Exception as e:
            logger.error(
                "incremental_indexing_failed",
                repository_id=self.repository_id,
                error=str(e),
            )
            raise

    def _compute_diff(
        self,
        stored_hashes: dict[str, str],
        local_hashes: dict[str, str],
    ) -> list[FileDiff]:
        """Compute diff between stored and local files."""
        diffs = []

        # Check local files against stored
        for file_path, local_hash in local_hashes.items():
            if file_path not in stored_hashes:
                diffs.append(FileDiff(file_path, DiffAction.ADD, new_hash=local_hash))
            elif stored_hashes[file_path] != local_hash:
                diffs.append(
                    FileDiff(
                        file_path,
                        DiffAction.UPDATE,
                        old_hash=stored_hashes[file_path],
                        new_hash=local_hash,
                    )
                )
            else:
                diffs.append(FileDiff(file_path, DiffAction.SKIP))

        # Check for deleted files
        for file_path in stored_hashes:
            if file_path not in local_hashes:
                diffs.append(
                    FileDiff(file_path, DiffAction.DELETE, old_hash=stored_hashes[file_path])
                )

        return diffs

    @staticmethod
    async def _is_hybrid_enabled() -> bool:
        """检查是否启用 hybrid search。

        默认 True：未配置 setting 时即视为启用，避免索引侧建出"单匿名 dense
        向量"老格式 collection 与检索侧"默认带 sparse"行为脱节（历史 bug：
        老 collection 上 hybrid_search 走到 Qdrant 会 400 "Not existing
        vector name: sparse"，被 except 静默吞掉返回 0 结果）。
        """
        setting = await SystemSetting.objects.filter(key=SettingKeys.HYBRID_SEARCH_ENABLED).afirst()
        return setting.value == "true" if setting else True

    @staticmethod
    def _generate_sparse_vectors(texts: list[str]) -> list[dict]:
        """生成 BM25 稀疏向量（同步方法，需要 sync_to_async 调用）。"""
        from services.sparse_encoder import SparseEncoderService

        return SparseEncoderService.encode_batch(texts)

    async def _extract_and_write_graph(
        self,
        repo_path: str,
        file_paths: list[str],
        repository_id: str,
        *,
        branch_name: str = "",
        history_id: str | None = None,
        skip_unchanged: bool = False,
    ) -> dict[str, Any]:
        """对指定文件列表执行图谱抽取并写入 Django ORM（双轨架构图谱轨）。

        该方法在向量轨写入（Qdrant upsert）完成后调用，对每个 tree-sitter
        支持的文件进行 AST 解析 + 四维抽取 + 批量入库。

        per contract: 图谱抽取失败不阻塞向量轨。单个文件失败仅记 warning。
        per contract: 复用 CodeParser 的 tree-sitter parser 获取能力（同一棵 AST）。

        Args:
            repo_path: 克隆仓库的本地路径
            file_paths: 需要抽取图谱的文件路径列表（相对路径）
            repository_id: 仓库 UUID 字符串
            branch_name: 写入侧归一化后的分支名（contract）。``""``=base 路径，
                feature 分支为归一化后的分支名。透传给 ``GraphWriter.write_bundle``
                与 ``enqueue_edge_build_for_history``，使图谱行/边带正确分支维度。
            history_id: 关联的 IndexHistory 行 ID（contract / Pitfall 3）。非 None
                时 lifecycle hook **直接用透传值**，跳过「查最近 RUNNING IndexHistory」
                fallback（避免多分支并发误取错行）；None 时保留 fallback 向后兼容。

        Returns:
            dict: {"files_processed": N, "files_failed": N, "symbols": N, ...}
        """
        from django.conf import settings

        from codegraph.extractors.base import FileContext
        from codegraph.extractors.registry import (
            BACKEND_REGISTRY,
            EXTRACTOR_REGISTRY,
            TreeSitterExtractor,
            get_extractor,
        )
        from services.code_parser import TREESITTER_LANGUAGES

        # Feature flag 门控（per NYQUIST 维度 8: 配置可控）
        if not getattr(settings, "ENABLE_CODEGRAPH", False):
            logger.debug("codegraph_disabled_by_feature_flag")
            return {"files_processed": 0, "files_failed": 0, "reason": "disabled"}

        # 延迟初始化图谱服务
        self._init_graph_services()
        graph_extractor = self._graph_extractor
        graph_writer = self._graph_writer
        if graph_extractor is None or graph_writer is None:
            logger.warning("graph_services_unavailable", repository_id=repository_id)
            return {"files_processed": 0, "files_failed": 0, "reason": "unavailable"}

        stats: dict[str, Any] = {
            "files_processed": 0,
            "files_failed": 0,
            "total_symbols": 0,
            "total_imports": 0,
            "total_calls": 0,
            "total_endpoints": 0,
        }

        # Vue SFC 专用抽取器（单例，避免每文件实例化）。注册缺失则降级为 None，
        # 循环里 is_vue 分支会安全跳过（不阻塞其它语言图谱抽取）。
        vue_extractor = get_extractor("vue")

        # 防御性 normalize：调用方可能传入绝对路径（如全量索引早期版本直接传
        # scan_directory 结果），统一转为相对 repo_path 的相对路径再入库，
        # 避免 DB 里 file_path 出现 /var/folders/.../friday_index_xxx/... 这种 tmp 前缀。
        normalized_file_paths: list[str] = []
        repo_path_abs = os.path.abspath(repo_path)
        for fp in file_paths:
            if os.path.isabs(fp):
                try:
                    rel = os.path.relpath(fp, repo_path_abs)
                except ValueError:
                    # 不在 repo_path 下（跨盘符），保留原值，让 _detect_language_from_path
                    # 等下游逻辑自然处理；通常不会发生。
                    rel = fp
                normalized_file_paths.append(rel)
            else:
                normalized_file_paths.append(fp)
        file_paths = normalized_file_paths

        total_graph_files = len(file_paths)
        # 每处理 GRAPH_YIELD_EVERY 个文件主动让出事件循环 + 上报 stage，
        # 避免 background_runner 长时间独占 loop / SQLite 写锁导致 ASGI
        # 接口集体 "待处理"。
        GRAPH_YIELD_EVERY = 25

        # 预查询 endpoint RAG 写入所需参数（循环后批量处理）
        _all_endpoints_with_sigs: list[tuple[Any, str]] = []
        try:
            _repo_obj = await Repository.objects.filter(id=repository_id).afirst()
            _endpoint_rag_repo_name: str = _repo_obj.name if _repo_obj else ""
            _endpoint_rag_hybrid: bool = await self._is_hybrid_enabled()
        except Exception:
            _endpoint_rag_repo_name = ""
            _endpoint_rag_hybrid = False

        # 图谱文件级断点（GraphFileIndex）：skip_unchanged=True 时载入该分支已写入
        # 图谱的 {file_path: file_hash}，循环内 hash 命中即跳过（进程/Pod 重启续跑）。
        # 无论是否 skip_unchanged，write_bundle 成功后都 upsert，供未来续跑使用。
        from repositories.models import GraphFileIndex as _GraphFileIndex

        _graph_done: dict[str, str] = {}
        if skip_unchanged:
            try:
                _graph_done = {
                    fp: fh
                    async for fp, fh in _GraphFileIndex.objects.filter(
                        repository_id=repository_id,
                        branch_name=branch_name,
                    ).values_list("file_path", "file_hash")
                }
            except Exception as _gfi_exc:  # noqa: BLE001
                logger.warning(
                    "graph_checkpoint_load_failed",
                    repository_id=repository_id,
                    error=str(_gfi_exc),
                )
                _graph_done = {}

        for index, file_path in enumerate(file_paths, start=1):
            if index % GRAPH_YIELD_EVERY == 0 or index == total_graph_files:
                await update_index_stage(
                    self.repository_id,
                    f"构建代码图谱... {index}/{total_graph_files}",
                )
                await update_current_indexing_file(
                    self.repository_id,
                    file_path=file_path,
                )
                # 让 ASGI 线程池有机会处理 HTTP 请求 / SQLite 写锁释放窗口
                await asyncio.sleep(0)

            full_path = os.path.join(repo_path, file_path)
            if not os.path.exists(full_path) or not os.path.isfile(full_path):
                continue

            # 确定语言
            language = self._detect_language_from_path(file_path)
            if not language:
                continue
            # Vue SFC 走专用 VueExtractor（SFC 预拆分 + 对 <script> 块复用 TS/TSX
            # backend），不参与整文件 tree-sitter 解析 —— 否则 <template>/<style>
            # 会污染 TS AST。因此 vue 不受 TREESITTER_LANGUAGES 守卫约束。
            is_vue = language == "vue"
            if is_vue and vue_extractor is None:
                # VueExtractor 未注册（理论上不会发生）→ 跳过，避免 None.extract 崩溃。
                continue
            if not is_vue:
                if language not in TREESITTER_LANGUAGES:
                    # 非 tree-sitter 支持的语言，跳过图谱抽取
                    continue
                # 部分 tree-sitter 语言（如 json）参与向量轨 AST chunking，但
                # 不参与图谱抽取（无 symbol/import/call/endpoint 概念，未注册
                # BACKEND_REGISTRY）。提前过滤避免 `get_backend` 每文件刷
                # `backend_not_found` / `no_backend_for_language` 噪声 warning。
                if language not in BACKEND_REGISTRY:
                    continue

            # 文件大小过滤（per RESEARCH.md §H.2: MAX_FILE_BYTES = 5MB）
            file_size = os.path.getsize(full_path)
            MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB
            if file_size > MAX_FILE_BYTES:
                logger.warning(
                    "graph_extraction_skipped_file_too_large",
                    file_path=file_path,
                    size_bytes=file_size,
                )
                continue

            # 读取源文件内容
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
            except Exception as e:
                logger.warning(
                    "graph_extraction_read_failed",
                    file_path=file_path,
                    error=str(e),
                )
                stats["files_failed"] += 1
                continue

            # 跳过空文件和纯二进制文件（已在上层 filtered，此处兜底）
            if not source.strip():
                continue

            # 图谱断点：hash 未变且已写入图谱 → 跳过（续跑场景免重复抽取/写库）。
            _file_hash = hashlib.sha256(
                source.encode("utf-8", "replace")
            ).hexdigest()
            if skip_unchanged and _graph_done.get(file_path) == _file_hash:
                stats["files_processed"] += 1
                continue

            # AST 解析 + 四维抽取 + 写入（per contract: 单文件失败不阻塞）
            try:
                # 构建 FileContext
                module_path = file_path.replace("/", ".").replace(".py", "")
                ctx = FileContext(
                    file_path=file_path,
                    language=language,
                    repository_id=repository_id,
                    module_path=module_path,
                )

                # implementation single-parse：向量轨 parse_file_dual 已为图谱支持的非 Vue
                # 语言缓存同源 bundle —— 命中即复用，消除每文件二次解析；miss（Vue /
                # 未缓存 / graph_builder 单独调用）走原解析兜底，保证功能不破坏。
                cached_bundle = self._session_graph_bundles.get(file_path)
                if cached_bundle is not None:
                    bundle = cached_bundle
                elif is_vue:
                    # Vue SFC：用 VueExtractor 先拆 SFC，再对首个 <script> 块复用
                    # TS/TSX backend 抽取（行号偏移还原 + setup 宏 + template 反向引用）。
                    bundle = vue_extractor.extract(file_path, source, ctx)
                else:
                    # 与 single-parse 缓存来源（unified_extraction 走
                    # get_extractor(language).extract）保持同一 extract(file_path,
                    # source, ctx) 入口：CodeParser 的 tree-sitter parser 对
                    # typescript 用的是 JavaScript grammar，会丢失 interface/type/
                    # enum 等 TS 专属符号。运行时 volar 经 register_backend 把
                    # javascript / jsx 注入 BACKEND_REGISTRY（故能通过上方
                    # BACKEND_REGISTRY 守卫），但二者无专用 LanguageExtractor
                    # （EXTRACTOR_REGISTRY 未注册）——退到通用 TreeSitterExtractor
                    # 直抽，避免被整体跳过丢符号 + 刷 extractor_not_found 噪声。
                    extractor: Any
                    if language in EXTRACTOR_REGISTRY:
                        extractor = get_extractor(language)
                    else:
                        extractor = TreeSitterExtractor()
                    if extractor is None:
                        continue
                    bundle = extractor.extract(file_path, source, ctx)

                # 批量入库（contract：透传归一化分支名，base 路径 branch_name="" 字节不变）
                result = await graph_writer.write_bundle(
                    repository_id, bundle, branch_name=branch_name
                )

                stats["files_processed"] += 1
                stats["total_symbols"] += result.get("symbols", 0)
                stats["total_imports"] += result.get("imports", 0)
                stats["total_calls"] += result.get("calls", 0)
                stats["total_endpoints"] += result.get("endpoints", 0)

                # 图谱断点锚点：write_bundle 提交成功后才登记，保证 DB 一致性
                # （崩溃在 write 后、upsert 前 → 续跑重做该文件，幂等安全）。
                try:
                    await _GraphFileIndex.objects.aupdate_or_create(
                        repository_id=repository_id,
                        branch_name=branch_name,
                        file_path=file_path,
                        defaults={"file_hash": _file_hash},
                    )
                except Exception as _gfi_w_exc:  # noqa: BLE001
                    logger.debug(
                        "graph_checkpoint_write_failed",
                        file_path=file_path,
                        error=str(_gfi_w_exc),
                    )

                # 收集当前文件 endpoint（含 best-effort symbol signature）
                for _ep in bundle.endpoints:
                    _handler_func = _ep.handler_name.rsplit(".", 1)[-1]
                    _sym = next(
                        (s for s in bundle.symbols if s.name == _handler_func),
                        None,
                    )
                    _all_endpoints_with_sigs.append((_ep, _sym.signature if _sym else ""))

                # 条件追加 Go interface implementation 抽取
                # 仅当 gopls backend 已启用 + 当前文件为 Go + 有 symbol 时触发
                if (
                    language == "go"
                    and getattr(settings, "GOPLS_BACKEND_ENABLED", False)
                    and bundle.symbols
                ):
                    try:
                        from pathlib import Path as _Path  # noqa: PLC0415

                        from codegraph.lsp.gopls_interface import (  # noqa: PLC0415
                            extract_interface_implementations,
                        )

                        workspace_root_path = _Path(repo_path)
                        impl_data = extract_interface_implementations(
                            workspace_root=workspace_root_path,
                            interface_symbols=bundle.symbols,
                        )
                        if impl_data:
                            logger.info(
                                "gopls_interface_extracted",
                                file_path=file_path,
                                impl_count=len(impl_data),
                            )
                            stats.setdefault("total_interface_impls", 0)
                            stats["total_interface_impls"] += len(impl_data)
                    except Exception as _impl_exc:  # noqa: BLE001
                        logger.warning(
                            "gopls_interface_extract_failed",
                            file_path=file_path,
                            error=str(_impl_exc),
                        )

            except Exception as e:
                logger.warning(
                    "graph_extraction_failed",
                    file_path=file_path,
                    error=str(e),
                )
                stats["files_failed"] += 1
                # 不重新抛出 —— 图谱失败不影响向量轨（contract）

        if stats["files_processed"] > 0:
            logger.info(
                "graph_extraction_batch_complete",
                repository_id=repository_id,
                processed=stats["files_processed"],
                failed=stats["files_failed"],
                symbols=stats["total_symbols"],
                imports=stats["total_imports"],
                calls=stats["total_calls"],
                endpoints=stats["total_endpoints"],
            )

        # 图谱轨完成后批量写 endpoint RAG 文档（失败不阻塞）
        if _all_endpoints_with_sigs and _endpoint_rag_repo_name:
            await self._write_endpoint_rag_docs(
                endpoints_with_sigs=_all_endpoints_with_sigs,
                repo_name=_endpoint_rag_repo_name,
                hybrid_enabled=_endpoint_rag_hybrid,
            )

        # implementation hook（per contract / contract）+ implementation lifecycle 切换：
        # 图谱写完后触发 6 EdgeBuilder + payload 一跳快照同步；改走
        # `code_relations.lifecycle.enqueue_edge_build_for_history` 外部 wrapper
        # 把 IndexHistory.graph_build_status 状态机接入（running → completed/failed/skipped）。
        # tasks.py 公共 API `enqueue_edge_build` 不被修改（per plan frozen 约束）。
        # 异常隔离：任何失败 catch + structlog warning，不抛回 indexer。
        try:
            from asgiref.sync import sync_to_async

            from code_relations.lifecycle import enqueue_edge_build_for_history
            from repositories.models import IndexHistory, IndexHistoryStatus

            dirty = sorted(self._session_dirty_chunk_ids)
            self._session_dirty_chunk_ids.clear()
            # contract / Pitfall 3：history_id 透传优先。形参非 None 时直接用透传值，
            # 跳过下方「查最近 RUNNING IndexHistory」fallback —— 避免多分支并发索引时
            # fallback 取错行，把 feature 的 edge_count 回写到 base 的 IndexHistory。
            running_history: uuid.UUID | str | None
            if history_id is not None:
                running_history = history_id
            else:
                # 向后兼容 fallback：调用栈未透传 history_id 时，取该 repo 最近 RUNNING
                # 的 IndexHistory 行作为 lifecycle 写入目标；找不到则降级透传 None。
                running_history = await sync_to_async(
                    lambda: IndexHistory.objects.filter(
                        repository_id=repository_id,
                        status=IndexHistoryStatus.RUNNING,
                    )
                    .order_by("-created_at")
                    .values_list("id", flat=True)
                    .first()
                )()
                # implementation 时序修复：查不到 RUNNING 行（主流程可能已把本次 IndexHistory
                # 标 completed/failed）时，退取最近一条 IndexHistory 作为 lifecycle 回写目标，
                # 避免 history_id=None 致使边建好却不回写 edge_count/graph_build_status
                # （旧 bug：前端 GraphRAG 卡因此误显示「0 语义边」）。
                if running_history is None:
                    running_history = await sync_to_async(
                        lambda: IndexHistory.objects.filter(
                            repository_id=repository_id,
                        )
                        .order_by("-created_at")
                        .values_list("id", flat=True)
                        .first()
                    )()
            # implementation（Pitfall A / Pitfall 7）：per-run delta 回填。
            # 把本次 write_bundle 累加出的 symbols/imports/calls/endpoints 新增数
            # 写入 running_history 指向的 IndexHistory 行。
            #
            # 为什么用 running_history 而非 history_id 形参（Pitfall A）：
            #   run_full_index 与 run_branch_index 透传 history_id=None，若直接用
            #   形参，全量/分支索引的 *_added 永远写不进；running_history 含 fallback
            #   （history_id 透传优先 → 查最近 RUNNING → 最近一条 IndexHistory），与
            #   下方 lifecycle 回写 edge_count 用同一来源，保证 per-run delta 与累计
            #   落到同一 IndexHistory 行。
            # 语义对立（Pitfall 7）：这 4 个 *_added 是「本次索引新增」（per-run
            #   delta，取自本次 stats 累加），与 lifecycle 写的 edge_count（全表累计
            #   快照）落同一行但语义相反，绝不可互相串用。
            # running_history 为 None（无任何 IndexHistory 可挂）时跳过回填，保持鲁棒。
            if running_history is not None:
                await IndexHistory.objects.filter(id=running_history).aupdate(
                    symbols_added=stats["total_symbols"],
                    imports_added=stats["total_imports"],
                    calls_added=stats["total_calls"],
                    endpoints_added=stats["total_endpoints"],
                )

            if dirty:
                await enqueue_edge_build_for_history(
                    str(repository_id), dirty, running_history, branch_name=branch_name
                )
                stats["edge_build_enqueued"] = True
                stats["dirty_chunk_count"] = len(dirty)
            else:
                stats["edge_build_enqueued"] = False
        except Exception as exc:
            logger.warning(
                "code_relations_hook_failed",
                repository_id=str(repository_id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            stats["edge_build_enqueued"] = False

        # 图谱 Symbol 写完 + 向量轨 Qdrant chunk 已就绪 → 回填
        # Symbol.chunk_id 持久化绑定（「一套 AST 双供」的关联落地，取代运行时行号 bisect）。
        # 异常隔离：绑定是优化项，失败仅 warning 不阻塞索引主流程。
        try:
            from code_relations.symbol_chunk_binding import backfill_symbol_chunk_ids

            bound = await backfill_symbol_chunk_ids(str(repository_id))
            stats["symbols_bound_to_chunks"] = bound
        except Exception as exc:
            logger.warning(
                "symbol_chunk_backfill_hook_failed",
                repository_id=str(repository_id),
                error=str(exc),
                error_type=type(exc).__name__,
            )

        # 整库 raw 写完后，对整库构建解析上下文（SymbolIndex +
        # python/frontend/go resolver）回填 CallEdge.callee_symbol/callee_file/
        # is_cross_file。创建索引与手动重建均经本函数 → 一处接入两路径覆盖。
        # 异常隔离：回填是优化项，失败仅 warning 不阻塞索引主流程（contract）。
        try:
            from asgiref.sync import sync_to_async

            from codegraph.resolver.wiring import backfill_symbol_resolution

            resolve_stats = await sync_to_async(backfill_symbol_resolution)(
                str(repository_id), repo_path
            )
            stats["calls_resolved"] = resolve_stats.get("resolved", 0)
        except Exception as exc:
            logger.warning(
                "symbol_resolution_wire_failed",
                repository_id=str(repository_id),
                error=str(exc),
                error_type=type(exc).__name__,
            )

        return stats

    async def _write_endpoint_rag_docs(
        self,
        *,
        endpoints_with_sigs: list[tuple[Any, str]],
        repo_name: str,
        hybrid_enabled: bool,
    ) -> None:
        """为已抽取的 endpoints 生成 api_endpoint.md 并写入 Qdrant。

        失败只记 warning，不阻塞图谱轨（per work item 容错原则）。
        """
        try:
            from services.endpoint_rag_writer import write_endpoint_rag_docs

            count = await write_endpoint_rag_docs(
                endpoints_with_sigs=endpoints_with_sigs,
                repository_id=self.repository_id,
                repo_name=repo_name,
                hybrid_enabled=hybrid_enabled,
            )
            logger.debug(
                "endpoint_rag_docs_written",
                repository_id=self.repository_id,
                count=count,
            )
        except Exception:
            logger.warning(
                "endpoint_rag_docs_write_failed",
                repository_id=self.repository_id,
                exc_info=True,
            )

    @staticmethod
    def _detect_language_from_path(file_path: str) -> str | None:
        """从文件扩展名检测编程语言（CodeParser 的简化版）。"""
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        _EXT_LANG_MAP = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "tsx": "typescript",
            "go": "go",
            "css": "css",
            "html": "html",
            "json": "json",
            # Vue SFC：图谱轨经 VueExtractor 专用路径抽取（SFC 预拆分 + TS backend），
            # 不走整文件 tree-sitter（见 _extract_and_write_graph 内 is_vue 分支）。
            "vue": "vue",
        }
        return _EXT_LANG_MAP.get(ext)

    async def _upsert_chunk_registry_batch(
        self,
        registry_rows: list[ChunkRegistryRow],
    ) -> list[tuple[str, bool]]:
        """同步写入 ChunkRegistry —— uuid5 chunk_id 同源 + content_hash 变化追踪。

        per contract / contract / contract + contract / contract / contract 修复：
        - **整批包在一次 `sync_to_async` + `transaction.atomic`**（contract）：partial
          failure 全部回滚，消除 ChunkRegistry 与 Qdrant 的「前 N 行已写、后续未写」
          中间态；同时把 N 次 thread-context 切换降到 1 次。
        - **`get_or_create` 在同一 atomic 内读旧 hash + 决策是否 update**（contract）：
          消除原先 `_fetch_old_content_hash` → `update_or_create` 两次 sync_to_async
          之间的 TOCTOU race。`select_for_update()` 在 SQLite 上退化为 no-op（单进程
          atomic 已足够），在 Postgres 上提供行级锁，多 worker 场景下也安全。
        - **入参用 `ChunkRegistryRow` TypedDict**（contract）：implementation EdgeBuilder
          误传 `chunkid` / `contenthash` 等错拼字段 mypy 静态拦截，运行期不再 KeyError。

        返回 `list[tuple[str, bool]]` 每行 `(point_id, content_hash_changed)`：
        `content_hash_changed=True` 表示同 chunk_id 但内容变化（implementation 据此决定
        是否重新 embed；本 phase 仅返回不消费）。

        在 Qdrant upsert 全部成功之后调用；本方法内部抛错时 atomic 整批回滚，
        保证 Qdrant ↔ ChunkRegistry 强一致（contract 语义）。
        """
        results = await self._bulk_upsert_registry_atomic(registry_rows)

        if results:
            changed_count = sum(1 for _, c in results if c)
            logger.info(
                "chunk_registry_upsert_batch",
                repository_id=self.repository_id,
                total=len(results),
                content_hash_changed=changed_count,
            )

        return results

    @staticmethod
    @sync_to_async
    def _bulk_upsert_registry_atomic(
        registry_rows: list[ChunkRegistryRow],
    ) -> list[tuple[str, bool]]:
        """ChunkRegistry 同步写入的真正实现：单次 sync_to_async + 单个 atomic。

        独立 staticmethod 而非闭包 / 内嵌函数，避开 closure 延迟绑定 + 让 mypy 拿到
        清晰签名；逻辑见 `_upsert_chunk_registry_batch` 文档。
        """
        from django.db import transaction

        from code_relations.models import ChunkRegistry

        results: list[tuple[str, bool]] = []
        with transaction.atomic():
            for row in registry_rows:
                cid = row["chunk_id"]
                new_hash = row["content_hash"]
                # select_for_update：Postgres 行锁、SQLite 退化为 no-op（无害）；
                # 单 atomic 内 read-modify-write 不再跨 sync_to_async 边界，杜绝
                # contract 描述的「A 读旧 hash → 别人插入 → B update_or_create 误判
                # created=False 且 old_hash=None → 漏标 content_hash_changed」race。
                obj, created = ChunkRegistry.objects.select_for_update().get_or_create(
                    chunk_id=cid,
                    defaults={
                        "content_hash": new_hash,
                        "repository_id": row["repository_id"],
                        "file_path": row["file_path"],
                        "chunk_index": row["chunk_index"],
                        # contract：分支隔离维度。PK 仍是 chunk_id，feature chunk_id
                        # 已天然不同（分支命名空间），get_or_create 不跨分支覆盖 base。
                        "branch_name": row["branch_name"],
                        # 行号回填（IDX-02）：1-based 闭区间，可为 None（历史/非 AST 回退）。
                        "line_start": row["line_start"],
                        "line_end": row["line_end"],
                    },
                )

                content_hash_changed = (not created) and obj.content_hash != new_hash
                # 行号位移（重切分导致 chunk 上下移）必须更新，否则 25-02 file:line
                # 反查命中错位区间；额外纳入「仅行号变」判定，避免 hash/路径未变时漏更新。
                line_changed = not created and (
                    obj.line_start != row["line_start"] or obj.line_end != row["line_end"]
                )
                if (
                    content_hash_changed
                    or line_changed
                    or (
                        not created
                        and (
                            obj.file_path != row["file_path"]
                            or obj.chunk_index != row["chunk_index"]
                        )
                    )
                ):
                    obj.content_hash = new_hash
                    obj.file_path = row["file_path"]
                    obj.chunk_index = row["chunk_index"]
                    obj.line_start = row["line_start"]
                    obj.line_end = row["line_end"]
                    obj.save(
                        update_fields=[
                            "content_hash",
                            "file_path",
                            "chunk_index",
                            "line_start",
                            "line_end",
                            "updated_at",
                        ]
                    )

                results.append((str(cid), bool(content_hash_changed)))

        return results

    @staticmethod
    def _build_points(
        chunks: list[CodeChunk],
        embeddings: list[list[float] | None],
        sparse_vectors: list[dict] | None,
        hybrid: bool,
        *,
        repository_id: str,
        branch_name: str | None = None,
        is_base_branch: bool = False,
    ) -> tuple[list[dict], list[ChunkRegistryRow]]:
        """构建 Qdrant points + ChunkRegistry rows，支持 hybrid 和非 hybrid 模式。

        Pitfall 1（contract / contract）：point_id 走 `generate_chunk_id(repo_id, file_path,
        chunk_index)` 确定性 uuid5，**完全替代** uuid4 随机生成。同 (repo_id,
        file_path, chunk_index) 三元组的 chunk 重切分仍命中同 chunk_id（同源稳定）。

        chunk_index 规则：每个 file_path 内独立计数器，从 0 起按 chunks 列表出现
        次序递增；**即使 embedding=None**（跳过 point 写入）chunk_index 仍递增，
        保证「同 chunk 在重切分中始终拿到同一 chunk_id」。

        Returns:
            (points, registry_rows) 元组：
            - points: 与原行为兼容，含 dict[id/vector/payload]
            - registry_rows: 仅 embedding 非 None 的 chunk 入列，每行含
              {chunk_id: UUID, content_hash: str, repository_id: str,
               file_path: str, chunk_index: int}，调用方在 Qdrant upsert 成功后
              送进 `_upsert_chunk_registry_batch` 同步写入 ChunkRegistry。
        """
        file_chunk_counter: dict[str, int] = {}
        points: list[dict] = []
        registry_rows: list[ChunkRegistryRow] = []

        # contract / Critical 1 根因修复：归一化写入侧分支。base 路径（branch_name
        # 为 None 或 is_base_branch）→ ""，使 generate_chunk_id 走 base 命名空间字节
        # 不变（293 golden 不回归）；feature → 分支命名空间 chunk_id，与 base 天然不同，
        # ChunkRegistry PK 不再跨分支碰撞覆盖。
        _norm_branch = "" if (branch_name is None or is_base_branch) else branch_name

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_index = file_chunk_counter.get(chunk.file_path, 0)
            file_chunk_counter[chunk.file_path] = chunk_index + 1

            if embedding is None:
                continue

            chunk_id = generate_chunk_id(repository_id, chunk.file_path, chunk_index, _norm_branch)
            content_hash = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()

            payload: dict[str, Any] = {
                "file_path": chunk.file_path,
                "file_hash": chunk.file_hash,
                "language": chunk.language,
                "node_type": chunk.node_type,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "content": chunk.content,
                "context_header": chunk.context_header,
            }

            if branch_name is not None:
                payload["branch_name"] = branch_name
                payload["is_base_branch"] = is_base_branch

            if hybrid and sparse_vectors and i < len(sparse_vectors):
                from qdrant_client.http.models import SparseVector

                sparse = sparse_vectors[i]
                vector: Any = {
                    "dense": embedding,
                    "sparse": SparseVector(
                        indices=sparse["indices"],
                        values=sparse["values"],
                    ),
                }
            else:
                vector = embedding

            points.append(
                {
                    "id": str(chunk_id),
                    "vector": vector,
                    "payload": payload,
                }
            )
            registry_rows.append(
                {
                    "chunk_id": chunk_id,
                    "content_hash": content_hash,
                    "repository_id": repository_id,
                    "file_path": chunk.file_path,
                    "chunk_index": chunk_index,
                    "branch_name": _norm_branch,
                    # 行号回填（IDX-02）：直接取 CodeChunk 既有 1-based 闭区间属性，
                    # 与上方写入 Qdrant payload 的 start_line/end_line 同源，保证
                    # payload 与 ChunkRegistry 行号一致。per D-02。
                    "line_start": chunk.start_line,
                    "line_end": chunk.end_line,
                }
            )

        return points, registry_rows


def _detection_only_paths(index_result: dict[str, Any]) -> list[str] | None:
    """从 index_result 推导敏感检测的扫描范围（HI-01）。

    - 增量 / git_diff 结果带 ``added_files`` / ``modified_files`` 列表 → 仅扫本次新增/修改
      文件（避免每次增量全仓重扫）。删除文件不需扫描（已不在磁盘）。
    - 全量索引结果不带这些列表 → 返回 ``None`` 表示整仓扫描。
    """
    if "added_files" in index_result or "modified_files" in index_result:
        changed: list[str] = []
        changed.extend(index_result.get("added_files") or [])
        changed.extend(index_result.get("modified_files") or [])
        return changed
    return None


async def _run_sensitive_detection(
    repository_id: str, temp_dir: str, index_result: dict[str, Any]
) -> None:
    """EXCL-03（BL-01/HI-01）：在临时克隆目录删除**之前**同步触发敏感文件检测。

    必须在 ``clone_and_index_repository`` 的 ``finally`` 执行 ``shutil.rmtree(temp_dir)``
    之前 await 完成——检测器只读 + 全局有界（见 ``sensitive_detect``），await 它保证遍历的是
    真实克隆文件而非已删除/空目录（修复后台派发与 rmtree 的竞态）。

    全量索引扫全仓；增量/diff 仅扫本次变更文件。整段 best-effort，任何异常仅记 warning，
    绝不阻断索引 success 终态（DOMAIN §9 D-04 fail-safe，T-24-05）。
    """
    try:
        from services.sensitive_detect import detect_sensitive_files

        only_paths = _detection_only_paths(index_result)
        # 增量路径但本次无新增/修改文件 → 无需检测，直接返回。
        if only_paths is not None and not only_paths:
            return
        await detect_sensitive_files(repository_id, temp_dir, only_paths=only_paths)
    except Exception:
        logger.warning(
            "sensitive_detect_failed",
            repository_id=repository_id,
            exc_info=True,
        )


async def _run_commit_index(repository_id: str, repo_path: str) -> None:
    """IDX-01（25-04）：在临时克隆目录删除**之前**同步触发 commit 历史索引。

    与 ``_run_sensitive_detection`` 同款时序与 fail-safe 范式（BL-01 修复经验）：必须在
    ``clone_and_index_repository`` 的 ``finally`` 执行 ``shutil.rmtree(temp_dir)`` 之前 await
    完成——``index_commits`` 需读真实克隆的 git 历史（git log / diff-tree），await 它保证读到
    的是真实克隆目录而非已删除/空目录（绝不后台派发去遍历一个即将被删除的目录）。

    全量与增量索引均流经此挂接点（``index_commits`` 内部按 ``commit_index_boundary_sha``
    边界自行区分首轮/增量）。整段 best-effort，任何异常仅记 warning，commit 索引失败/缺供应商
    绝不阻断既有索引 success 终态（对齐 D-04/T-25-12，与 ``_run_sensitive_detection`` 同契约）。
    """
    try:
        from services.commit_index import index_commits

        result = await index_commits(repository_id, repo_path)
        logger.info(
            "commit_index_completed",
            repository_id=repository_id,
            indexed=result.get("indexed"),
            head=result.get("head"),
        )
    except Exception as e:
        logger.warning(
            "commit_index_dispatch_failed",
            repository_id=repository_id,
            error=str(e),
        )


async def _run_sdd_detect(repository_id: str, repo_path: str) -> None:
    """SDD-01（48-01）：在临时克隆目录删除**之前**同步触发 SDD 仓库检测。

    与 ``_run_sensitive_detection`` / ``_run_commit_index`` 同款时序与 fail-safe 范式
    （BL-01 修复经验）：必须在 ``clone_and_index_repository`` 的 ``finally`` 执行
    ``shutil.rmtree(temp_dir)`` 之前 await 完成——检测器纯文件系统探测仓库根 ``openspec/``
    （见 ``services.sdd_detect``），await 它保证探测的是真实克隆目录而非已删除/空目录。

    整段 best-effort，任何异常仅记 warning ``sdd_detect_dispatch_failed``，**绝不重抛、
    绝不阻断索引 success 终态**（对齐 D-04/T-25-12，与 ``_run_sensitive_detection`` /
    ``_run_commit_index`` 同契约）。
    """
    try:
        from services.sdd_detect import detect_and_tag_sdd

        await detect_and_tag_sdd(repository_id, repo_path)
    except Exception as e:
        logger.warning(
            "sdd_detect_dispatch_failed",
            repository_id=repository_id,
            error=str(e),
        )


async def _run_modifies_chunk_reconcile(repository_id: str) -> None:
    """HDIFF-02：base 索引完成后对账失效过期 MODIFIES_CHUNK 边。

    目标分支演进 / 文件重索引后，旧的 diff→chunk 关联当年成立但当前已过期；本钩子
    把指向已过期 chunk 版本的活跃 MODIFIES_CHUNK 边 ``invalid_at`` 置位（置位不删除，
    历史可追溯）。与 ``_run_sensitive_detection`` / ``_run_commit_index`` 同款
    best-effort fail-safe（整段 try/except，失败仅 warning，绝不阻断索引 success
    终态，对齐 D-04/T-25-12）。
    """
    try:
        from django.utils import timezone

        from knowledge.modifies_chunk import areconcile_modifies_chunk_edges

        invalidated = await areconcile_modifies_chunk_edges(
            repository_id, invalid_at=timezone.now()
        )
        logger.info(
            "modifies_chunk_reconcile_completed",
            repository_id=repository_id,
            invalidated=invalidated,
        )
    except Exception as e:
        logger.warning(
            "modifies_chunk_reconcile_failed",
            repository_id=repository_id,
            error=str(e),
        )


async def _run_research_stale_invalidation(repository_id: str) -> None:
    """RESEARCH-03：base 索引完成后把该仓关联 PartialPlan 置 stale（融合前需重跑）。

    仓库重索引（commit 变化）使既有调研产物过期：经 ``ResearchService.invalidate_for_repo``
    把该 repository 关联且 valid 的 PartialPlan 置 ``valid=False`` + 对应 RepoResearchTask
    →stale。与 ``_run_modifies_chunk_reconcile`` 同款 best-effort fail-safe（整段
    try/except，失败仅 warning，**绝不抛、绝不阻断索引 success 终态**，对齐 D-04/Phase 24/25）。
    """
    try:
        from delivery.services import ResearchService

        invalidated = await ResearchService().invalidate_for_repo(repository_id)
        logger.info(
            "research_stale_invalidation_completed",
            repository_id=repository_id,
            invalidated=invalidated,
        )
    except Exception as e:
        logger.warning(
            "research_stale_invalidation_failed",
            repository_id=repository_id,
            error=str(e),
        )


async def clone_and_index_repository(
    repository_id: str,
    *,
    history_id: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Clone repository and run indexing.

    This is the main entry point for indexing a repository.

    Args:
        repository_id: 仓库 ID
        history_id: 可选的 IndexHistory 记录 ID，完成时更新状态
        branch: 可选的功能分支名称，非空时走 overlay 索引路径
    """
    from services.git_credentials import aresolve_git_token

    async def get_repository_data():
        """Fetch repository and extract all needed data in async context."""
        repo = await Repository.objects.aget(id=repository_id)
        # 统一经凭证解析器取 token（Phase 26 REPO-01）：per-repo 显式 token 优先，
        # 无则按 host 命中实例凭证池；缺凭证返回 None（保留下游既有缺凭证报错）。
        token = await aresolve_git_token(repo)
        return {
            "repository": repo,
            "git_url": repo.git_url,
            "proxy_url": repo.proxy_url,
            "token": token,
        }

    async def update_repository_status(repo, status, error=None, last_indexed_at=None):
        await repo.arefresh_from_db()
        repo.index_status = status
        repo.index_error = error
        if last_indexed_at:
            repo.last_indexed_at = last_indexed_at
        update_fields = ["index_status", "index_error"]
        if last_indexed_at:
            update_fields.append("last_indexed_at")
        await repo.asave(update_fields=update_fields)

    try:
        repo_data = await get_repository_data()
    except Repository.DoesNotExist:
        return {"status": "error", "message": "Repository not found"}

    repository = repo_data["repository"]
    git_url = repo_data["git_url"]
    proxy_url = repo_data["proxy_url"]
    token = repo_data["token"]

    # Update status to indexing
    await update_repository_status(repository, IndexStatus.INDEXING)
    await update_index_stage(repository_id, IndexStage.CLONING)

    temp_dir = None
    try:
        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix="friday_index_")

        # Build authenticated URL if needed
        # 使用 oauth2:<token>@host 形式：GitLab project token 必须放在密码位置，
        # GitHub/Gitea 也都接受任意用户名 + token 作为密码。
        git_url = build_authenticated_git_url(git_url, token)

        # Clone using git
        # --progress 启用 stderr 进度输出（即使没有 tty）；我们后台读 stderr 解析
        # "Receiving objects: NN%" 实时把 stage 更新为"克隆仓库中... NN%"，
        # 让前端长时间 clone 也能看到进度数字而不是死板的"克隆仓库中..."。
        clone_cmd = ["git", "clone", "--depth", "1", "--progress"]
        if not branch:
            clone_cmd.extend(["--single-branch", "--branch", repository.default_branch])

        # Add proxy if configured
        if proxy_url:
            clone_cmd.extend(["-c", f"http.proxy={proxy_url}"])

        clone_cmd.extend([git_url, temp_dir])

        proc = await asyncio.create_subprocess_exec(
            *clone_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _stream_clone_progress() -> bytes:
            """读 stderr，解析 'Receiving objects: NN%' 并 update stage。

            返回完整 stderr bytes（用于失败时报错），同时把进度记录到 DB。
            """
            assert proc.stderr is not None
            collected = bytearray()
            last_pct = -1
            buffer = b""
            while True:
                chunk = await proc.stderr.read(256)
                if not chunk:
                    break
                collected.extend(chunk)
                buffer += chunk
                # git --progress 用 \r 分隔进度刷新，按 \r/\n 切片即可
                while True:
                    idx_r = buffer.find(b"\r")
                    idx_n = buffer.find(b"\n")
                    candidates = [i for i in (idx_r, idx_n) if i != -1]
                    if not candidates:
                        break
                    cut = min(candidates)
                    line = buffer[:cut].decode("utf-8", errors="ignore")
                    buffer = buffer[cut + 1 :]
                    # 形如 "Receiving objects:  50% (617/1234), 1.23 MiB | 500 KiB/s"
                    m = _CLONE_RECEIVING_RE.search(line)
                    if m:
                        pct = int(m.group(1))
                        # 只在百分比真实变化时写 DB（≤101 次写入，可控）
                        if pct != last_pct:
                            last_pct = pct
                            await update_index_stage(repository_id, f"克隆仓库中... {pct}%")
            return bytes(collected)

        try:
            stderr_bytes = await asyncio.wait_for(_stream_clone_progress(), timeout=300.0)
            await proc.wait()
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            raise Exception("Git clone timed out after 300s")
        except asyncio.CancelledError:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            raise
        if proc.returncode != 0:
            raise Exception(f"Git clone failed: {stderr_bytes.decode(errors='ignore')}")

        # Run indexing - pass repository_id instead of repository object
        indexer = IndexerService(repository_id)

        head_sha: str | None = None
        last_sha: str | None = None
        fallback_reason: str | None = None

        if branch:
            # 功能分支 overlay 索引路径
            index_result = await indexer.run_branch_index(temp_dir, branch, repository)
        else:
            # 现有 base branch 索引路径
            base_branch = repository.default_branch

            # 获取当前 HEAD SHA
            await update_index_stage(repository_id, IndexStage.COMPARING_HEAD)
            head_sha = await _get_head_sha(temp_dir)

            # 决定索引路径：git diff > 文件哈希比较 > 全量
            last_sha = repository.last_indexed_commit_sha

            # 先检查 collection 是否有数据；如果为空则必须走全量索引
            await update_index_stage(repository_id, IndexStage.LOADING_HASHES)
            stored_hashes = await qdrant_get_stored_file_hashes(repository_id)
            collection_has_data = bool(stored_hashes)

            # 全量索引路径在拿到 head_sha 之后立刻把 to_sha 写入 IndexHistory，
            # 让"索引历史"列表的 RUNNING 行能展示当前目标 commit
            # （增删改 stats 在全量路径无意义，保持 0）
            if history_id and head_sha:
                from repositories.models import IndexHistory as _IH

                await _IH.objects.filter(id=history_id).aupdate(to_sha=head_sha)

            if last_sha and collection_has_data:
                # 尝试 git diff 增量路径
                fetch_ok = await _fetch_commit(temp_dir, last_sha, proxy_url)
                if fetch_ok:
                    try:
                        index_result = await indexer.run_git_diff_index(
                            temp_dir,
                            last_sha,
                            head_sha,
                            branch_name=base_branch,
                            is_base_branch=True,
                            history_id=history_id,
                        )
                    except GitDiffError as e:
                        logger.warning("git_diff_failed_fallback", error=str(e))
                        fallback_reason = f"git diff 失败: {e}"
                        is_shallow = await _is_shallow_clone(temp_dir)
                        if is_shallow:
                            logger.info("shallow_clone_fallback_to_full_index")
                            index_result = await indexer.run_full_index(
                                temp_dir,
                                branch_name=base_branch,
                            )
                        else:
                            index_result = await indexer.run_incremental_index(
                                temp_dir,
                                branch_name=base_branch,
                                is_base_branch=True,
                                history_id=history_id,
                            )
                else:
                    logger.warning("fetch_commit_failed_fallback", sha=last_sha)
                    fallback_reason = f"git fetch {last_sha} 失败"
                    is_shallow = await _is_shallow_clone(temp_dir)
                    if is_shallow:
                        logger.info("shallow_clone_fallback_to_full_index")
                        index_result = await indexer.run_full_index(
                            temp_dir,
                            branch_name=base_branch,
                        )
                    else:
                        index_result = await indexer.run_incremental_index(
                            temp_dir,
                            branch_name=base_branch,
                            is_base_branch=True,
                            history_id=history_id,
                        )
            elif collection_has_data:
                checkpoint_count = await FileIndex.objects.filter(
                    repository_id=repository_id,
                ).acount()
                if checkpoint_count > 0:
                    logger.info(
                        "partial_index_checkpoint_resume_to_full_index",
                        repository_id=repository_id,
                        checkpoint_files=checkpoint_count,
                    )
                    fallback_reason = "检测到未完成索引 checkpoint，按断点续传继续全量索引"
                    index_result = await indexer.run_full_index(
                        temp_dir,
                        branch_name=base_branch,
                    )
                else:
                    logger.warning(
                        "orphan_collection_without_checkpoint_rebuild",
                        repository_id=repository_id,
                    )
                    await sync_to_async(QdrantService.delete_collection)(repository_id)
                    fallback_reason = "collection 存在但无 FileIndex checkpoint，清理后全量重建"
                    index_result = await indexer.run_full_index(
                        temp_dir,
                        branch_name=base_branch,
                    )
            else:
                if last_sha:
                    logger.info(
                        "collection_empty_fallback_to_full_index",
                        repository_id=repository_id,
                        last_sha=last_sha,
                    )
                    fallback_reason = "collection 为空，回退到全量索引"
                index_result = await indexer.run_full_index(
                    temp_dir,
                    branch_name=base_branch,
                )

            # base 路径：更新 last_indexed_commit_sha
            now = timezone.now()
            await Repository.objects.filter(id=repository_id).aupdate(
                last_indexed_commit_sha=head_sha,
                remote_head_sha=head_sha or "",
                remote_head_checked_at=now,
                behind_commits=0,
                behind_commits_calculated_at=now,
            )

        # Update repository status
        if not branch:
            await update_repository_status(
                repository,
                IndexStatus.INDEXED,
                last_indexed_at=timezone.now(),
            )
            await update_index_stage(repository_id, IndexStage.COMPLETED)
        # contract：清空文件级实时进度（保留 total/processed 计数用于结束态展示）
        await update_current_indexing_file(repository_id, file_path="")

        # 更新 IndexHistory 状态为完成
        if history_id:
            from repositories.models import IndexHistory, IndexHistoryStatus

            history_update: dict[str, Any] = {
                "status": IndexHistoryStatus.COMPLETED,
                "finished_at": timezone.now(),
            }

            if branch:
                # 分支索引路径：从 index_result 提取分支相关信息
                history_update["summary_text"] = (
                    f"分支 {branch}: {index_result.get('status', 'unknown')}"
                    f"（diff {index_result.get('diff_files', 0)} 文件）"
                )
            else:
                # base 路径：从 index_result 提取统计信息
                files_added = index_result.get("added", 0)
                files_modified = index_result.get("updated", 0)
                files_deleted = index_result.get("deleted", 0)
                history_update["to_sha"] = head_sha
                history_update["files_added"] = files_added
                history_update["files_modified"] = files_modified
                history_update["files_deleted"] = files_deleted
                history_update["summary_text"] = _build_summary_text(
                    files_added,
                    files_modified,
                    files_deleted,
                )
                # contract（方案 A）：contract — 持久化变更文件路径列表到 IndexHistory.changed_files
                history_update["changed_files"] = {
                    "added": index_result.get("added_files", []),
                    "modified": index_result.get("modified_files", []),
                    "deleted": index_result.get("deleted_files", []),
                }
                if last_sha:
                    history_update["from_sha"] = last_sha
                if fallback_reason:
                    history_update["error_message"] = f"[fallback] {fallback_reason}"

            await IndexHistory.objects.filter(id=history_id).aupdate(**history_update)

        # EXCL-03（BL-01/HI-01）：在 finally 删除 temp_dir 之前同步触发敏感文件检测。
        # 仅对 base 索引路径执行（功能分支 overlay 不在本阶段检测范围内）；全量扫全仓、
        # 增量/diff 仅扫变更文件。best-effort，绝不阻断索引终态。
        if not branch:
            await _run_sensitive_detection(repository_id, temp_dir, index_result)
            # IDX-01（25-04）：base 索引（全量+增量）完成、rmtree 之前 best-effort 摄取 commit
            # 历史（读真实克隆的 git 历史）；失败仅 warning，绝不阻断索引 success（T-25-12）。
            # BL-01：生产克隆是 `git clone --depth 1` 浅克隆，其 git log 只见 HEAD —— commit
            # 历史索引前先 best-effort 补齐完整历史，否则历史 commit 永远索引不到并跨运行丢失。
            if await _is_shallow_clone(temp_dir):
                await _unshallow_repo(temp_dir, proxy_url)
            await _run_commit_index(repository_id, temp_dir)
            # HDIFF-02：base 重索引完成后对账失效过期 MODIFIES_CHUNK 边（置位不删，
            # best-effort，绝不阻断索引 success）。功能分支 overlay 不触发对账，
            # 与上方 base-only 钩子一致。
            await _run_modifies_chunk_reconcile(repository_id)
            # RESEARCH-03（39-04）：base 重索引完成后把过期 PartialPlan 置 stale（融合前重跑）。
            # 纯 DB 操作（不读克隆目录），放在对账钩子之后；best-effort，绝不阻断索引 success。
            # 功能分支 overlay 不触发，与上方 base-only 钩子一致。
            await _run_research_stale_invalidation(repository_id)
            # SDD-01（48-01）：base 索引完成、rmtree 之前 best-effort 探测仓库根 openspec/，
            # 命中则标记 facets[methodology]=SDD。纯 os.path.isdir 探测真实克隆目录；失败仅
            # warning，绝不阻断索引 success。功能分支 overlay 不触发，与上方 base-only 钩子一致。
            await _run_sdd_detect(repository_id, temp_dir)

        return index_result

    except Exception as e:
        logger.error(
            "clone_and_index_failed",
            repository_id=repository_id,
            error=str(e),
        )

        # contract：检查主向量轨是否已完成。若已完成（persist_vector_track_complete
        # 写过 status=INDEXED），说明失败发生在 graph/summary 后置阶段——
        # 仓库的核心索引数据已就绪，搜索完全可用。这种情况下：
        #   - Repository.index_status 保持 INDEXED（不覆盖回 FAILED）
        #   - 只把本次 IndexHistory 标 FAILED，方便用户在历史中看到后置阶段失败
        # 反之主向量轨未完成，按原逻辑标 FAILED。
        try:
            current_repo = await Repository.objects.aget(id=repository_id)
            main_track_done = current_repo.index_status == IndexStatus.INDEXED
        except Exception:
            main_track_done = False

        if main_track_done:
            logger.warning(
                "post_main_track_failure_treated_as_indexed",
                repository_id=repository_id,
                error=str(e),
            )
            await update_index_stage(repository_id, "")
            await update_current_indexing_file(repository_id, file_path="")
        else:
            await update_repository_status(repository, IndexStatus.FAILED, error=str(e))
            await update_index_stage(repository_id, "")
            await update_current_indexing_file(repository_id, file_path="")

        # 更新 IndexHistory 状态为失败（无论主向量轨是否完成，本次 run 都没正常收尾）
        if history_id:
            from repositories.models import IndexHistory, IndexHistoryStatus

            await IndexHistory.objects.filter(id=history_id).aupdate(
                status=IndexHistoryStatus.FAILED,
                finished_at=timezone.now(),
                error_message=str(e)[:2000],
            )

        return {"status": "error", "message": str(e)}

    finally:
        # Clean up temp directory
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
