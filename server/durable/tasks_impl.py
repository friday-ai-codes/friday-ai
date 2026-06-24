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

from common.log_context import bind_task_context

logger = structlog.get_logger(__name__)


async def run_index(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """代码索引任务体：克隆并索引仓库。

    复用既有 ``services.indexer.clone_and_index_repository``，进度 / 结果仍写
    IndexHistory，FileIndex 的 hash checkpoint 逻辑零改动（幂等真值源在 service 内）。
    ``trigger`` 仅承载入队点语义、本任务体不转发（History 已在入队点创建）。
    ``initiated_by_user_id``（CTX-02）：worker 入口重新 bind 发起用户（无则 system），
    durable worker 用干净 contextvars 不自动传播，必须显式 bind。
    """
    from services.indexer import clone_and_index_repository

    with bind_task_context(user_id=initiated_by_user_id, source="durable"):
        return await clone_and_index_repository(
            repository_id, history_id=history_id, branch=branch
        )


async def run_graph(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
    initiated_by_user_id: str | None = None,
) -> Any:
    """代码图谱构建任务体。

    复用既有 ``services.graph_builder.build_graph_for_repository``，结果写
    GraphBuildHistory，GraphFileIndex checkpoint（skip_unchanged）沿用 service 默认
    行为、本任务体不传 ``skip_unchanged``。``initiated_by_user_id`` 同 ``run_index``
    （CTX-02：worker 入口 bind 发起用户）。
    """
    from services.graph_builder import build_graph_for_repository

    with bind_task_context(user_id=initiated_by_user_id, source="durable"):
        return await build_graph_for_repository(
            repository_id, trigger=trigger, history_id=history_id, branch=branch
        )


async def run_crawl_ingest(
    *, batch_id: str, concurrency: int = 3, initiated_by_user_id: str | None = None
) -> dict[str, Any]:
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

    with bind_task_context(user_id=initiated_by_user_id, source="durable"):
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


async def run_repo_summary(
    *, repository_id: str, initiated_by_user_id: str | None = None
) -> dict[str, Any]:
    """仓库 AI 描述派发任务体：可靠地发起一次 repo_summary 派发。

    委托既有 ``summary_service.dispatch_repo_summary``（创建 SubAgentSession + 投递到
    Runner）。durable job 完成即代表"已发起派发"；重活在 Runner 容器内执行，完成回写
    由 callbacks 链路负责。仓库不存在 / 已是终态时安全跳过（幂等、防重复推送）。
    ``initiated_by_user_id`` 同 ``run_index``（CTX-02：worker 入口 bind 发起用户）。
    """
    from repositories.models import AISummaryStatus, Repository
    from repositories.summary_service import dispatch_repo_summary

    with bind_task_context(user_id=initiated_by_user_id, source="durable"):
        repo = await Repository.objects.filter(id=repository_id, is_deleted=False).afirst()
        if repo is None:
            logger.info(
                "durable_repo_summary_skipped", repository_id=repository_id, reason="not_found"
            )
            return {"status": "skipped", "reason": "not_found", "repository_id": repository_id}

        # 已完成的不重复生成（幂等）；pending/running/failed 允许（重新触发/恢复）。
        if repo.ai_summary_status == AISummaryStatus.COMPLETED:
            return {
                "status": "skipped",
                "reason": "already_completed",
                "repository_id": repository_id,
            }

        session_id = await dispatch_repo_summary(repo)
        logger.info(
            "durable_repo_summary_dispatched",
            repository_id=repository_id,
            session_id=session_id,
        )
        return {"status": "dispatched", "repository_id": repository_id, "session_id": session_id}


async def run_page_index(
    *, target_id: str | None = None, initiated_by_user_id: str | None = None, **kwargs: Any
) -> dict[str, Any]:
    """页面级索引 / 全局知识树生成任务体（Phase 62-02，PAGEIDX-01）：真实生成 + 自上次构建跳过。

    比对基线是**上一次已构建 active 快照的 ``source_hash``**（而非入队时刻传入的指纹）：

    - 算执行时刻当前全仓输入指纹 ``current = compute_source_hash()``；
    - 取上次构建基线 ``baseline = get_active_source_hash()``（无 active 快照即**首次构建**，
      返回 ``None``）；
    - 仅当存在基线且 ``baseline == current``（自上次构建以来输入未变）→ 返回 ``skipped``，
      **不调 ``build_full``**（重复执行无重复 snapshot、不重跑 LLM 聚类——研究 Pitfall 4 /
      T-62-05 DoS）；
    - 首次构建（无基线）或 ``current != baseline``（输入已变）→ 调天然幂等的
      ``CorpusTreeService.build_full()``（unassigned 兜底 + 沿用旧 pin），build_full 自身落新
      snapshot（写 ``source_hash`` 供下次比对），本任务体不旁路写库；返回值直接采用 build_full
      落库所用 ``source_hash``，避免与落库值分叉（IN-01）。

    ⚠️ 不再消费入参 ``target_hash``：入队时刻指纹与执行时刻指纹同源恒等，作基线必致恒跳过
    （CR-01）。``**kwargs`` 吞掉历史 payload 里的 ``target_hash`` 等键，向后兼容旧调用方。
    keyword-only + ``**kwargs`` 容错对齐双后端 payload 契约。
    """
    from codegraph.services.corpus_tree import CorpusTreeService

    with bind_task_context(user_id=initiated_by_user_id, source="durable"):
        current = await CorpusTreeService.compute_source_hash()
        baseline = await CorpusTreeService.get_active_source_hash()
        if baseline is not None and baseline == current:
            logger.info(
                "durable_page_index_skipped", target_id=target_id, reason="hash_unchanged"
            )
            return {"status": "skipped", "reason": "hash_unchanged", "target_id": target_id}

        result = await CorpusTreeService.build_full()
        logger.info(
            "durable_page_index_built",
            target_id=target_id,
            status=result.get("status"),
        )
        return {
            "status": result.get("status"),
            "target_id": target_id,
            "source_hash": result.get("source_hash", current),
        }
