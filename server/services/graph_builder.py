"""implementation-01 — 顶层 Graph 构建服务。

将"图谱构建"从 indexer 内部 private method 抽出为一等公民 service：

- 入口：``build_graph_for_repository(repository_id, *, trigger, history_id=None) -> GraphBuildResult``
- 串行流程：锁 Repository → 取/建 ``GraphBuildHistory(RUNNING)`` →
  ``GraphWriter.adelete_for_files`` 前置删除孤儿 → 复用 ``IndexerService._extract_and_write_graph``
  薄壳 → 转 ``COMPLETED`` 落计数 / ``FAILED`` 落 error_message。
- 不读 ``settings.ENABLE_CODEGRAPH``（view 层 403 拦截，service 假定调用方已通过 flag）。
- 不读 ``Repository.auto_build_graph_enabled``（手动 REST 是用户 explicit intent，
  per-repo 开关只控 indexer 自动衔接路径）。
- 三 trigger 一视同仁（manual / auto_after_index / webhook），全部写
  ``GraphBuildHistory`` 供 list endpoint 审计。

设计动机详见 ``project docs`` 与 work item。
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from repositories.models import (
    BranchFileIndex,
    FileIndex,
    GraphBuildHistory,
    GraphBuildHistoryStatus,
    GraphBuildHistoryTrigger,
    Repository,
    RepositoryBranchIndex,
    RepositoryGraphStatus,
)

__all__ = [
    "GraphBuildResult",
    "build_graph_for_repository",
    "reset_repository_graph_progress",
    "mark_repository_graph_terminal",
    "prepare_repo_workdir_async",
]


logger = structlog.get_logger(__name__)


# trigger 字符串到枚举的合法集合：未知 trigger 兜底为 MANUAL，避免
# 调用方笔误导致 history 写入失败。三态 manual / auto_after_index / webhook，
# 其中 webhook 当前仅占位。
_KNOWN_TRIGGERS: frozenset[str] = frozenset({
    GraphBuildHistoryTrigger.MANUAL.value,
    GraphBuildHistoryTrigger.AUTO_AFTER_INDEX.value,
    GraphBuildHistoryTrigger.WEBHOOK.value,
})


@dataclass(frozen=True)
class GraphBuildResult:
    """``build_graph_for_repository`` 返回值——与 ``GraphBuildHistory`` 字段口径对齐。

    末位追加新字段保字段位置兼容（与 ``CleanupReport`` 同模式）。
    完成时调用方可一次性 ``asdict(result)`` 写 history 行。
    """

    status: str
    files_total: int = 0
    files_processed: int = 0
    files_failed: int = 0
    symbols_count: int = 0
    imports_count: int = 0
    calls_count: int = 0
    endpoints_count: int = 0
    duration_seconds: float = 0.0
    error_message: str = ""


def _acquire_repo_lock(repository_id: str) -> Repository:
    """获取仓库 DB 行级排他锁（与 ``_acquire_index_lock`` 同模式）。

    用 ``select_for_update()``（默认 ``skip_locked=False``，与 indexer 现有锁互补——
    indexer 走 ``skip_locked=True`` 静默 skip 重复触发，graph_builder 走默认阻塞等待，
    保证 manual REST 调用方拿到确定性结果）。

    Note：SQLite 下 ``select_for_update`` 是 no-op；真正的进程间排他来自
    ``background_runner`` 同名任务的 cancel 语义。本锁在 Postgres 部署下提供
    "同一 repo 不会被两个 graph_build 任务并发抢"的硬保证。

    Raises:
        Repository.DoesNotExist: 仓库不存在或已软删除。
    """
    with transaction.atomic():
        return Repository.objects.select_for_update().get(
            id=repository_id, is_deleted=False,
        )


_acquire_repo_lock_async = sync_to_async(_acquire_repo_lock)


async def _collect_file_paths(
    repository_id: str, *, branch_name: str = "",
) -> list[str]:
    """收集待重建文件的 ``file_path`` 列表（前置孤儿删除 + 抽取入参）。

    base 路径（``branch_name == ""``）取全量 ``FileIndex`` —— 与历史行为字节不变
    （向后兼容验收点）。feature 路径取该分支 ``BranchFileIndex`` 的 diff 文件，
    对齐图谱 overlay 合并语义（feature 只覆盖 diff 文件，其余继承 base）。该分支
    尚无 overlay 索引记录（``RepositoryBranchIndex`` 缺失）时返回空列表——无可
    重建文件，主流程随后写 COMPLETED + 计数 0。
    """
    if not branch_name:
        return [
            fi.file_path
            async for fi in FileIndex.objects.filter(
                repository_id=repository_id,
            ).only("file_path")
        ]

    branch_index = await RepositoryBranchIndex.objects.filter(
        repository_id=repository_id, branch_name=branch_name,
    ).afirst()
    if branch_index is None:
        return []
    return [
        bfi.file_path
        async for bfi in BranchFileIndex.objects.filter(
            branch_index=branch_index,
        ).only("file_path")
    ]


# 手动 rebuild 路径没有 indexer 主流程那个还活着的 temp_dir（indexer.py:2933
# 的 mkdtemp 在 finally 已 rmtree），所以必须自己 clone。否则
# `_extract_and_write_graph` 拿到的 repo_path（默认 `REPO_CLONE_DIR/<repo_id>/`，
# 一个从来不会被任何流程写入的目录）下不存在任何文件，1716 次 `os.path.exists`
# 全部 False，循环空转，counts=0 但状态被误标 COMPLETED。
@contextlib.asynccontextmanager
async def prepare_repo_workdir_async(
    repository_id: str,
    *,
    branch: str | None = None,
) -> AsyncIterator[str]:
    """Clone repo 的指定分支到临时目录供 graph 抽取使用；退出时清理。

    Args:
        repository_id: 仓库 UUID。
        branch: 可选 clone 目标分支（contract）。``None``/``""`` 时 clone
            ``repo.default_branch`` —— 与历史行为字节不变（向后兼容）；非空时
            clone 该 feature 分支（manual REST 按分支重建）。

    Yields:
        临时目录的绝对路径，作为 `repo_path` 传给 `_extract_and_write_graph`。

    Raises:
        Repository.DoesNotExist: 仓库不存在或已软删除。
        RuntimeError: ``git clone`` 失败或超时（被 graph_builder 主 try/except
            转为 ``GraphBuildHistory.status=FAILED + error_message``）。
    """
    from repositories.views import build_authenticated_git_url
    from services.git_credentials import resolve_git_token_sync

    @sync_to_async
    def _fetch_repo_clone_params() -> tuple[str, str | None, str | None, str]:
        repo = (
            Repository.objects.filter(id=repository_id, is_deleted=False).first()
        )
        if repo is None:
            raise Repository.DoesNotExist(
                f"Repository {repository_id} not found or deleted"
            )
        # 统一经凭证解析器取 token（Phase 26 REPO-01）：per-repo 优先，
        # 无则按 host 命中实例凭证池。本函数已是 @sync_to_async 同步上下文，用同步入口。
        token: str | None = resolve_git_token_sync(repo)
        return repo.git_url, repo.proxy_url, token, repo.default_branch

    git_url, proxy_url, token, default_branch = await _fetch_repo_clone_params()

    if not git_url:
        raise RuntimeError(
            f"repository {repository_id} 缺少 git_url，无法 clone 构建图谱"
        )

    auth_url = build_authenticated_git_url(git_url, token)

    # contract：传 branch 时 clone 该 feature 分支，否则回退 default_branch
    # （不传 → 字节不变向后兼容）。
    clone_branch = branch or default_branch

    temp_dir = tempfile.mkdtemp(prefix="friday_graph_")
    try:
        clone_cmd: list[str] = [
            "git",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            clone_branch,
        ]
        if proxy_url:
            clone_cmd.extend(["-c", f"http.proxy={proxy_url}"])
        clone_cmd.extend([auth_url, temp_dir])

        proc = await asyncio.create_subprocess_exec(
            *clone_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            _, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=300.0
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            raise RuntimeError("graph build clone 超时 (300s)") from exc

        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode(errors="ignore").strip()
            raise RuntimeError(
                f"graph build clone 失败: {stderr_text[:500] or '(no stderr)'}"
            )

        logger.info(
            "graph_build_clone_completed",
            repository_id=repository_id,
            branch=clone_branch,
            temp_dir=temp_dir,
        )
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


async def reset_repository_graph_progress(repository_id: str) -> None:
    """implementation-01：build_graph 入口 reset Repository 5 字段。

    与 ``update_graph_progress`` 共享 try/except 容错模板——写失败仅 warning，
    不阻塞 build_graph 主流程（CONTEXT 决议：进度字段属"显示用"非"业务核心"）。

    5 字段归位：
    - ``graph_build_status`` → ``RUNNING``
    - ``graph_stage`` → ``"前置清理..."``（首阶段文案，后续 helper 会覆盖）
    - ``current_graph_file`` → ``""``
    - ``graph_files_processed`` / ``graph_files_total`` → ``0``

    （``graph_last_built_at`` 不在 reset 时刷新，保留上次终态时间戳直到本次
    构建终止；终态 helper 负责更新。）
    """
    try:
        await Repository.objects.filter(id=repository_id).aupdate(
            graph_build_status=RepositoryGraphStatus.RUNNING,
            graph_stage="前置清理...",
            current_graph_file="",
            graph_files_processed=0,
            graph_files_total=0,
        )
    except Exception as exc:
        logger.warning(
            "reset_repository_graph_progress_failed",
            repository_id=repository_id,
            error=str(exc),
        )


async def mark_repository_graph_terminal(
    repository_id: str,
    *,
    status: str,
    stage: str = "",
    current_file: str | None = None,
    files_processed: int | None = None,
    files_total: int | None = None,
) -> None:
    """implementation-01：build_graph 终态 + ``graph_last_built_at=now()``。

    ``current_file`` / ``files_processed`` / ``files_total`` 显式传 ``None``
    时**不动**对应字段——CONTEXT Grey Area 1 失败路径决议：失败时保留最后
    写入的 ``current_graph_file`` 便于排查"卡在哪个文件"。

    Args:
        repository_id: 仓库 UUID。
        status: 终态 ``RepositoryGraphStatus`` 之一（``COMPLETED`` /
            ``FAILED`` / ``CANCELLED``）。
        stage: 阶段文案；成功传 ``"完成"``，失败传 ``""`` 或具体错误简述。
        current_file: ``None`` 时不动该字段；传 ``""`` 时显式清空。
        files_processed / files_total: ``None`` 时不动；显式传值则覆盖。
    """
    update_kwargs: dict[str, Any] = {
        "graph_build_status": status,
        "graph_stage": stage,
        "graph_last_built_at": timezone.now(),
    }
    if current_file is not None:
        update_kwargs["current_graph_file"] = current_file
    if files_processed is not None:
        update_kwargs["graph_files_processed"] = files_processed
    if files_total is not None:
        update_kwargs["graph_files_total"] = files_total
    try:
        await Repository.objects.filter(id=repository_id).aupdate(**update_kwargs)
    except Exception as exc:
        logger.warning(
            "mark_repository_graph_terminal_failed",
            repository_id=repository_id,
            status=status,
            error=str(exc),
        )


async def build_graph_for_repository(
    repository_id: str,
    *,
    trigger: str,
    history_id: str | None = None,
    branch: str | None = None,
    skip_unchanged: bool = False,
) -> GraphBuildResult:
    """顶层 graph 构建入口（work item-01 / work item-02 / contract）。

    Args:
        repository_id: 仓库 UUID 字符串。
        trigger: 触发来源（``manual`` / ``auto_after_index`` / ``webhook``）。
        history_id: 可选 ``GraphBuildHistory`` 行 ID；为 ``None`` 时 service 自创建
            RUNNING 行，非 ``None`` 时复用调用方已创建的 RUNNING 行（manual REST 与
            ``auto_after_index`` 路径——view/indexer 先建行再透传 id）。
        branch: 可选目标分支（contract）。``None``/``""``/``==base`` 经
            ``_resolve_write_branch`` 归一化为 ``""``（base 路径，clone default_branch +
            全量 FileIndex + 图谱行 branch_name=""，**字节不变向后兼容**）；feature 分支
            归一化后按该分支 clone、仅取该分支 diff 文件重建、图谱行打该分支 branch_name，
            并写 ``GraphBuildHistory.branch_name``。

    Returns:
        ``GraphBuildResult``：含 status / counts / duration / error_message 全字段。

    Raises:
        Repository.DoesNotExist: 仓库不存在或已软删除（history 已先标 FAILED）。
        Exception: 抽取或写入异常时已写 ``history.status=FAILED + error_message`` 后透传,
            让 ``background_runner`` worker 拿到异常以便外层观测/日志。
    """
    from services.indexer import IndexerService, _resolve_write_branch

    start = time.perf_counter()
    normalized_trigger = trigger if trigger in _KNOWN_TRIGGERS else (
        GraphBuildHistoryTrigger.MANUAL.value
    )

    # contract：入口集中归一化 branch（复用 indexer 的 _resolve_write_branch，
    # base 来源 = base_branch or default_branch）。None/""/==base → ""，feature → 原样。
    # 取不到 repo（不存在/已软删）时归一化为 ""——随后 _acquire_repo_lock_async 会
    # 抛 DoesNotExist 把 history 标 FAILED，归一化值此时已无影响。
    repo_for_branch = await Repository.objects.filter(
        id=repository_id, is_deleted=False,
    ).afirst()
    normalized_branch = (
        _resolve_write_branch(repo_for_branch, branch)
        if repo_for_branch is not None
        else ""
    )

    if history_id is None:
        history = await GraphBuildHistory.objects.acreate(
            repository_id=repository_id,
            trigger_type=normalized_trigger,
            status=GraphBuildHistoryStatus.RUNNING,
            branch_name=normalized_branch,
        )
    else:
        history = await GraphBuildHistory.objects.aget(id=history_id)
        # service 层统一写 history.branch_name（view 只透传 branch，不分叉 history
        # 创建逻辑）。立即持久化，保证 base 之外的 early-failure 路径也留有分支记录。
        if history.branch_name != normalized_branch:
            history.branch_name = normalized_branch
            await history.asave(update_fields=["branch_name"])

    logger.info(
        "graph_build_started",
        repository_id=repository_id,
        trigger=trigger,
        history_id=str(history.id),
    )

    # implementation-01：入口 reset Repository 5 字段
    # （graph_build_status=RUNNING / 计数归零 / current_file 清空）。
    await reset_repository_graph_progress(repository_id)

    try:
        try:
            # 行级锁防并发触发（select_for_update 在 Postgres 提供硬保证，SQLite no-op）；
            # 锁定的 Repository 实例字段已被 prepare_repo_workdir_async 内部独立查询替代，
            # 此处仅借助锁副作用，故不再绑定到变量。
            await _acquire_repo_lock_async(repository_id)
        except Repository.DoesNotExist:
            raise

        file_paths = await _collect_file_paths(
            repository_id, branch_name=normalized_branch,
        )

        from codegraph.services.graph_writer import GraphWriter

        graph_writer = GraphWriter()
        # skip_unchanged（断点续跑）时**跳过**前置全量删除：保留崩溃前已写入的
        # 图谱数据，配合 GraphFileIndex 跳过已完成文件，实现文件级断点恢复。
        # 非续跑（手动 rebuild / 全新构建）时：前置删全量孤儿 + 清空 GraphFileIndex
        # 断点，保证是一次真正的全量重建。
        if not skip_unchanged and file_paths:
            try:
                await graph_writer.adelete_for_files(
                    repository_id, file_paths, branch_name=normalized_branch,
                )
            except Exception as exc:
                # 前置删除失败不阻塞主流程（与 implementation-01 异常隔离同模式）；
                # 后续薄壳写入若与孤儿键冲突会再次报错并走主 try/except 路径。
                logger.warning(
                    "graph_pre_delete_failed",
                    repository_id=repository_id,
                    file_count=len(file_paths),
                    error=str(exc),
                )
        if not skip_unchanged:
            # 清空旧断点：全量重建从零登记，避免上一轮断点导致本轮误跳过。
            try:
                from repositories.models import GraphFileIndex

                await GraphFileIndex.objects.filter(
                    repository_id=repository_id, branch_name=normalized_branch,
                ).adelete()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "graph_checkpoint_reset_failed",
                    repository_id=repository_id,
                    error=str(exc),
                )

        indexer = IndexerService(repository_id=repository_id)

        # work item-01：手动 / webhook rebuild 路径自带 clone（indexer 主流程
        # 的 temp_dir 在 indexer 出口已 rmtree，graph_builder 重启时拿不到磁盘
        # 上的源文件）。auto_after_index 路径不走 build_graph_for_repository，
        # 不会重复 clone。clone 失败抛 RuntimeError，由外层 except 写
        # GraphBuildHistory.status=FAILED + error_message。
        async with prepare_repo_workdir_async(
            repository_id, branch=normalized_branch or None,
        ) as repo_path:
            # branch_name 透传使图谱行/边带正确分支维度（feature 不污染 base）。
            # history_id 维持默认 fallback：此处的 ``history`` 是 GraphBuildHistory，
            # 而 _extract_and_write_graph 的 history_id 形参是 IndexHistory.id（驱动
            # enqueue_edge_build_for_history → IndexHistory.graph_build_status），二者
            # 不同源；传 GraphBuildHistory.id 会指向不存在的 IndexHistory 行。保持不传
            # 即维持现有 manual REST 行为字节不变（见 SUMMARY 偏离记录）。
            stats: dict[str, Any] = await indexer._extract_and_write_graph(
                repo_path=repo_path,
                file_paths=file_paths,
                repository_id=repository_id,
                branch_name=normalized_branch,
                skip_unchanged=skip_unchanged,
            )

        files_total = len(file_paths)
        files_processed = int(stats.get("files_processed", 0))
        files_failed = int(stats.get("files_failed", 0))
        symbols_count = int(stats.get("total_symbols", 0))
        imports_count = int(stats.get("total_imports", 0))
        calls_count = int(stats.get("total_calls", 0))
        endpoints_count = int(stats.get("total_endpoints", 0))

        history.status = GraphBuildHistoryStatus.COMPLETED
        history.files_total = files_total
        history.files_processed = files_processed
        history.files_failed = files_failed
        history.symbols_count = symbols_count
        history.imports_count = imports_count
        history.calls_count = calls_count
        history.endpoints_count = endpoints_count
        history.finished_at = timezone.now()
        history.error_message = ""
        await history.asave(
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
                "error_message",
            ],
        )

        # implementation-01：成功出口写 Repository 终态
        # （status=COMPLETED / stage="完成" / current_file="" / counts /
        # graph_last_built_at=now）。
        await mark_repository_graph_terminal(
            repository_id,
            status=RepositoryGraphStatus.COMPLETED,
            stage="完成",
            current_file="",
            files_processed=files_processed,
            files_total=files_total,
        )

        # 图谱构建完成 → 主动刷新 Galaxy 文件缓存（refresh_repo 内部吞掉所有
        # 异常，失败时下次请求的签名对比仍会自动重建，不影响主流程）。
        from codegraph.galaxy.cache import GalaxyGraphCache

        # 🚨 必须从**包根**导入：``services.code_graph`` 的 ``__init__.py`` 是 curated
        # barrel，直连包内 ``cache`` 子模块正是它要挡住的架构违规（红线连钩子自己也不
        # 例外，否则那道守护测试形同虚设）。函数内 lazy import 同时避开模块级循环依赖。
        from services.code_graph import invalidate_repository

        await sync_to_async(GalaxyGraphCache.refresh_repo)(repository_id)

        # Symbol/CallEdge 抽取完成 → 驱逐本 worker 的内存符号图（Phase 121 / GRAPH-01）。
        # ⚠️ 这**只是优化，不是正确性保证**：钩子只对**本 worker** 生效，多 worker
        # 部署下其余进程里的旧图仍然只能靠取图时的**签名**复校发现陈旧——因此
        # ``GraphService._get_graph_sync`` 里那道签名比对**不可删除**。
        # 失效自身的异常在 ``invalidate_repository`` 内部吞掉，不反噬图谱构建。
        await sync_to_async(invalidate_repository)(repository_id)

        # Phase 125 / D-03：社区重建只 enqueue，⛔ 钩子内不内联 Louvain。
        try:
            from services.community_enqueue import enqueue_community_rebuild

            await enqueue_community_rebuild(
                str(repository_id),
                branch_name=normalized_branch or "",
            )
        except Exception:  # noqa: BLE001 — best-effort，不反噬图谱构建
            pass

        duration = time.perf_counter() - start
        logger.info(
            "graph_build_completed",
            repository_id=repository_id,
            trigger=trigger,
            history_id=str(history.id),
            duration_seconds=duration,
            files_total=files_total,
            files_processed=files_processed,
            files_failed=files_failed,
            symbols_count=symbols_count,
            imports_count=imports_count,
            calls_count=calls_count,
            endpoints_count=endpoints_count,
        )

        return GraphBuildResult(
            status=GraphBuildHistoryStatus.COMPLETED,
            files_total=files_total,
            files_processed=files_processed,
            files_failed=files_failed,
            symbols_count=symbols_count,
            imports_count=imports_count,
            calls_count=calls_count,
            endpoints_count=endpoints_count,
            duration_seconds=duration,
            error_message="",
        )
    except Exception as exc:
        duration = time.perf_counter() - start
        # error_message 截断 1000（CONTEXT specifics：与 GraphBuildHistory.error_message
        # TextField 长度宽口径配合，仅截断业务上限保 UI 单行展示）。
        truncated_error = str(exc)[:1000]
        try:
            history.status = GraphBuildHistoryStatus.FAILED
            history.error_message = truncated_error
            history.finished_at = timezone.now()
            await history.asave(
                update_fields=["status", "error_message", "finished_at"],
            )
        except Exception as save_exc:
            # history 写失败仅告警，主异常仍透传——避免吞掉真正的根因。
            logger.warning(
                "graph_build_history_save_failed",
                repository_id=repository_id,
                history_id=str(history.id),
                error=str(save_exc),
            )

        # implementation-01：异常出口写 Repository 终态
        # （status=FAILED / stage="" / graph_last_built_at=now）。
        # current_file / files_processed / files_total 传 None **不动**——
        # CONTEXT Grey Area 1 失败路径决议：保留最后写入的 current_graph_file
        # 便于排查"卡在哪个文件"。
        await mark_repository_graph_terminal(
            repository_id,
            status=RepositoryGraphStatus.FAILED,
            stage="",
        )

        logger.error(
            "graph_build_failed",
            repository_id=repository_id,
            trigger=trigger,
            history_id=str(history.id),
            duration_seconds=duration,
            error=str(exc),
            exc_info=True,
        )
        raise
