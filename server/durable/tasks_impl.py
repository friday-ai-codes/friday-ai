"""durable 业务任务体（与 procrastinate 无关的纯任务实现）。

本模块定义 index / graph / page_index 三个任务体，**对 procrastinate 零直接依赖**：
- procrastinate 路径经 ``durable.tasks`` 的 ``@app.task`` 包壳 import 本模块委托；
- in-process fallback 路径经 ``durable.handlers`` 的 ``**payload`` 展开 adapter
  import 本模块委托。

两后端共用同一任务体，是消除研究 Pitfall 1（双后端入参不一致）的关键：所有任务体
统一用 **keyword-only 形参**对齐 payload 键，调用方一律 ``**payload`` 展开传入，使
procrastinate ``defer_async(**payload)`` 与 in-process ``handler(**payload)`` 入参一致。

service 函数一律在**函数体内局部 import**，保持注册期（@app.task 收集）轻量、零
重依赖加载。
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def run_index(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """代码索引任务体：克隆并索引仓库。

    复用既有 ``services.indexer.clone_and_index_repository``，进度 / 结果仍写
    IndexHistory，FileIndex 的 hash checkpoint 逻辑零改动（幂等真值源在 service 内）。
    ``trigger`` 仅承载入队点语义、本任务体不转发（History 已在入队点创建）。
    """
    from services.indexer import clone_and_index_repository

    return await clone_and_index_repository(repository_id, history_id=history_id, branch=branch)


async def run_graph(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
) -> Any:
    """代码图谱构建任务体。

    复用既有 ``services.graph_builder.build_graph_for_repository``，结果写
    GraphBuildHistory，GraphFileIndex checkpoint（skip_unchanged）沿用 service 默认
    行为、本任务体不传 ``skip_unchanged``。
    """
    from services.graph_builder import build_graph_for_repository

    return await build_graph_for_repository(
        repository_id, trigger=trigger, history_id=history_id, branch=branch
    )


async def run_crawl_ingest(*, batch_id: str, concurrency: int = 3) -> dict[str, Any]:
    """爬取批次入库任务体（Phase 62-01，CRAWL-01）：薄封装既有天然幂等的摄取编排。

    按 ``batch_id`` 从 ``IngestRun``（DB 唯一真相源）重建待处理规格——**不在 payload 落
    凭证 / 三元组**（payload 仅 batch_id / concurrency）。处理该批 ``status`` ∈
    {QUEUED, RUNNING, FAILED, STOPPED} 的行（**排除 COMPLETED**，保证重复执行 / 断点恢复
    不重做已完成行），先批量置 ``RUNNING`` 再有界并发逐行 ``ingest_from_urls``。

    at-least-once 幂等由被封装的 ``ingest_from_urls`` 内核承载（三元组 upsert / 文档
    content_hash / MR diff aarchive_exists），终态 status 由 ``ingest_from_refs`` 写
    COMPLETED/FAILED；本任务体重复执行不产生重复 WorkItem/Document/Archive。单行异常
    try/except 隔离 + structlog warning，不阻断整批。
    """
    import asyncio

    from asgiref.sync import sync_to_async

    from delivery.models import IngestRun
    from delivery.services.ingest_orchestrator import ingest_from_urls
    from delivery.services.json_ingest import clamp_concurrency

    active_statuses = [
        IngestRun.Status.QUEUED,
        IngestRun.Status.RUNNING,
        IngestRun.Status.FAILED,
        IngestRun.Status.STOPPED,
    ]

    @sync_to_async
    def _load_active_runs() -> list[IngestRun]:
        # list() 强制求值脱离异步上下文；后续仅读已加载的标量属性（无隐式同步查询）。
        return list(
            IngestRun.objects.filter(batch_id=batch_id, status__in=active_statuses)
        )

    runs = await _load_active_runs()
    if not runs:
        return {"status": "ok", "batch_id": batch_id, "count": 0}

    run_ids = [run.id for run in runs]

    @sync_to_async
    def _mark_running() -> None:
        IngestRun.objects.filter(id__in=run_ids).update(status=IngestRun.Status.RUNNING)

    await _mark_running()

    sem = asyncio.Semaphore(clamp_concurrency(concurrency))

    async def _one(run: IngestRun) -> None:
        async with sem:
            try:
                # ingest_from_urls 内部解析 board_url→三元组→ingest_from_refs，已天然
                # 幂等；终态 status 由其写回。单行异常隔离，不阻断整批。
                await ingest_from_urls(str(run.id), run.board_url, run.mr_url)
            except Exception:
                logger.warning(
                    "crawl_ingest_run_failed",
                    run_id=str(run.id),
                    batch_id=batch_id,
                    exc_info=True,
                )

    await asyncio.gather(*(_one(run) for run in runs), return_exceptions=True)
    return {"status": "ok", "batch_id": batch_id, "count": len(runs)}


async def run_page_index(*, target_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """页面级索引占位任务体（Phase 62 接入实际 ingest）。

    当前仅记一条 debug 后返回恒等 dict，**不做任何写库 / 外部副作用**——重复执行
    恒等返回、零副作用即天然幂等（per CONTEXT「占位 handler + 幂等测试，实际接入留
    Phase 62」）。
    """
    logger.debug("durable_page_index_noop", target_id=target_id, extra=kwargs or None)
    return {"status": "noop", "target_id": target_id}
