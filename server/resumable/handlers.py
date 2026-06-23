"""索引 / 图谱构建的恢复 handler。

迁移后 recovery 续驱也经 durable 单一入口（``DurableTaskService.defer``）：从
``ResumableTask.payload`` 重建最小参数后投递 durable 任务，不再经旧 resumable 提交路径
内联续跑。deterministic idempotency_key（``index:{repo_id}`` / ``graph:{repo_id}``）
命中在途 durable job 即去重，避免与 durable stalled rescue 双跑（T-61-04）。续跑路径
无既有 history → 传 ``history_id=None``，由任务体 service 自建 RUNNING 行。续跑依赖底层
checkpoint 跳过已完成文件：

- 索引：复用 ``FileIndex``（file_path + file_hash）跳过已 upsert 的文件。
- 图谱：复用 ``GraphFileIndex`` 跳过 hash 未变、已写入图谱的文件。

注：入队点 1-4 已改 durable，生产不再产生新的 index/graph ResumableTask 行，recovery
续驱自然枯竭；保留 handler 注册但改走 defer —— 单一驱动入口、不双跑。
"""

from __future__ import annotations

import structlog
from asgiref.sync import async_to_sync

from resumable.models import ResumableTask, ResumableTaskKind

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 索引
# ---------------------------------------------------------------------------


def resume_index(task: ResumableTask) -> None:
    """recovery 续驱索引：从 payload 重建后经 durable defer 单一入口投递（同步上下文）。"""
    from durable import QUEUE_INDEX, DurableTaskService
    from durable.concurrency import index_lock_sync

    payload = task.payload or {}
    repository_id = str(payload.get("repository_id") or task.target_id)
    branch = payload.get("branch")
    trigger = payload.get("trigger", "manual")

    async_to_sync(DurableTaskService.defer)(
        "durable_index",
        {
            "repository_id": repository_id,
            "history_id": None,
            "branch": branch,
            "trigger": trigger,
        },
        queue=QUEUE_INDEX,
        idempotency_key=f"index:{repository_id}",
        # CONC-01：索引槽位锁池（同仓恒定同槽串行，至多 N 仓并发）
        lock=index_lock_sync(repository_id),
    )


# ---------------------------------------------------------------------------
# 图谱
# ---------------------------------------------------------------------------


def resume_graph(task: ResumableTask) -> None:
    """recovery 续驱图谱：从 payload 重建后经 durable defer 单一入口投递（同步上下文）。"""
    from durable import QUEUE_GRAPH, DurableTaskService
    from durable.concurrency import graph_lock_sync

    payload = task.payload or {}
    repository_id = str(payload.get("repository_id") or task.target_id)
    branch = payload.get("branch")
    trigger = payload.get("trigger", "manual")

    async_to_sync(DurableTaskService.defer)(
        "durable_graph",
        {
            "repository_id": repository_id,
            "history_id": None,
            "branch": branch,
            "trigger": trigger,
        },
        queue=QUEUE_GRAPH,
        idempotency_key=f"graph:{repository_id}",
        # CONC-01：图谱槽位锁池（同仓恒定同槽串行，至多 N 仓并发）
        lock=graph_lock_sync(repository_id),
    )


def register_default_handlers() -> None:
    """注册索引 / 图谱恢复 handler（由 resumable.apps.ready 调用）。"""
    from resumable.recovery import register_handler

    register_handler(ResumableTaskKind.INDEX, resume_index)
    register_handler(ResumableTaskKind.GRAPH, resume_graph)
