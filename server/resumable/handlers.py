"""索引 / 图谱构建的恢复 handler。

每个 handler 从 ``ResumableTask.payload`` 重建最小参数，经 ``submit_resumable``
重新派发后台任务。续跑依赖底层 checkpoint 跳过已完成文件：

- 索引：复用 ``FileIndex``（file_path + file_hash）跳过已 upsert 的文件。
- 图谱：复用 ``GraphFileIndex`` 跳过 hash 未变、已写入图谱的文件。
"""

from __future__ import annotations

import structlog
from django.utils import timezone

from resumable.models import ResumableTask, ResumableTaskKind
from resumable.service import submit_resumable

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 索引
# ---------------------------------------------------------------------------


async def _run_index_resume(
    repository_id: str, branch: str | None, trigger: str
) -> object:
    """恢复路径：新建一条 RUNNING IndexHistory 并续跑索引（FileIndex 跳过已完成）。"""
    from repositories.models import (
        IndexHistory,
        IndexHistoryStatus,
        IndexStatus,
        Repository,
        TriggerType,
    )
    from services.indexer import clone_and_index_repository

    trigger_value = trigger if trigger in TriggerType.values else TriggerType.MANUAL

    await Repository.objects.filter(id=repository_id).aupdate(
        index_status=IndexStatus.INDEXING,
        index_error=None,
    )
    history = await IndexHistory.objects.acreate(
        repository_id=repository_id,
        trigger_type=trigger_value,
        status=IndexHistoryStatus.RUNNING,
        started_at=timezone.now(),
    )
    return await clone_and_index_repository(
        repository_id,
        history_id=str(history.id),
        branch=branch,
    )


def resume_index(task: ResumableTask) -> None:
    payload = task.payload or {}
    repository_id = str(payload.get("repository_id") or task.target_id)
    branch = payload.get("branch")
    trigger = payload.get("trigger", "manual")

    submit_resumable(
        kind=ResumableTaskKind.INDEX,
        target_id=repository_id,
        payload=payload,
        name=f"index-{repository_id}",
        coro_factory=lambda: _run_index_resume(repository_id, branch, trigger),
    )


# ---------------------------------------------------------------------------
# 图谱
# ---------------------------------------------------------------------------


async def _run_graph_resume(
    repository_id: str, branch: str | None, trigger: str
) -> object:
    """恢复路径：续跑图谱构建，跳过已写入文件（skip_unchanged=True）。

    续跑会新建一条 GraphBuildHistory；先把该仓库残留的 RUNNING 历史行标记为
    FAILED（superseded），避免重启后留下永远转圈的僵尸历史。
    """
    from django.utils import timezone

    from repositories.models import GraphBuildHistory, GraphBuildHistoryStatus
    from services.graph_builder import build_graph_for_repository

    await GraphBuildHistory.objects.filter(
        repository_id=repository_id,
        status=GraphBuildHistoryStatus.RUNNING,
    ).aupdate(
        status=GraphBuildHistoryStatus.FAILED,
        finished_at=timezone.now(),
        error_message="构建在进程重启后被自动续跑取代（superseded by resume）。",
    )

    return await build_graph_for_repository(
        repository_id,
        trigger=trigger or "auto_after_index",
        branch=branch,
        skip_unchanged=True,
    )


def resume_graph(task: ResumableTask) -> None:
    payload = task.payload or {}
    repository_id = str(payload.get("repository_id") or task.target_id)
    branch = payload.get("branch")
    trigger = payload.get("trigger", "manual")

    submit_resumable(
        kind=ResumableTaskKind.GRAPH,
        target_id=repository_id,
        payload=payload,
        name=f"graph-build-{repository_id}",
        coro_factory=lambda: _run_graph_resume(repository_id, branch, trigger),
    )


def register_default_handlers() -> None:
    """注册索引 / 图谱恢复 handler（由 resumable.apps.ready 调用）。"""
    from resumable.recovery import register_handler

    register_handler(ResumableTaskKind.INDEX, resume_index)
    register_handler(ResumableTaskKind.GRAPH, resume_graph)
