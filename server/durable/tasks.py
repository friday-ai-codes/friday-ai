"""durable 任务底座的 Procrastinate 任务定义（Postgres durable 路径）。

本模块由 ``DurableConfig.ready()`` 在 procrastinate 后端真正启用时 import 触发
``@app.task`` / ``@app.periodic`` 注册；SQLite / in-process fallback 路径永不
import 本模块（无 ``procrastinate.contrib.django`` app）。

适配层隔离：本模块与 ``durable.backends`` 是仅有的两处允许直接 import
procrastinate 的 durable 业务代码（见 ``tests/durable/test_no_direct_import.py``
允许清单）。业务侧入队仍只经 ``DurableTaskService``，看不见这些任务对象。
"""

from __future__ import annotations

from typing import Any

import structlog
from procrastinate.contrib.django import app

from durable.queues import (
    QUEUE_CRAWL_INGEST,
    QUEUE_GRAPH,
    QUEUE_INDEX,
    QUEUE_MAINTENANCE,
    QUEUE_PAGE_INDEX,
)

logger = structlog.get_logger(__name__)


@app.task(name="durable_index", queue=QUEUE_INDEX)
async def durable_index(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """代码索引 durable 任务（procrastinate 包壳，委托共用任务体）。

    显式 ``name="durable_index"`` 与 ``backends.defer`` 的裸名查找
    （``app.tasks.get("durable_index")``）是同一 single source of truth（Phase 60
    CR-01 教训）。keyword-only 形参与 payload 契约逐字一致，下游
    ``DurableTaskService.defer("durable_index", {...})`` 经 ``defer_async(**payload)``
    展开传入。
    """
    from durable.tasks_impl import run_index

    return await run_index(
        repository_id=repository_id,
        history_id=history_id,
        branch=branch,
        trigger=trigger,
    )


@app.task(name="durable_graph", queue=QUEUE_GRAPH)
async def durable_graph(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
) -> Any:
    """代码图谱构建 durable 任务（procrastinate 包壳，委托共用任务体）。"""
    from durable.tasks_impl import run_graph

    return await run_graph(
        repository_id=repository_id,
        history_id=history_id,
        branch=branch,
        trigger=trigger,
    )


@app.task(name="durable_page_index", queue=QUEUE_PAGE_INDEX)
async def durable_page_index(**payload: Any) -> dict[str, Any]:
    """页面级索引 durable 任务（占位包壳，委托共用任务体）。"""
    from durable.tasks_impl import run_page_index

    return await run_page_index(**payload)


@app.task(name="durable_crawl_ingest", queue=QUEUE_CRAWL_INGEST)
async def durable_crawl_ingest(**payload: Any) -> dict[str, Any]:
    """爬取批次入库 durable 任务（procrastinate 包壳，委托共用任务体）。

    逐字镜像 ``durable_page_index`` 包壳：显式 ``name="durable_crawl_ingest"`` 与
    ``backends.defer`` 裸名查找（``app.tasks.get("durable_crawl_ingest")``）同源；payload
    仅 ``batch_id`` / ``concurrency``，经 ``defer_async(**payload)`` 展开传入。
    """
    from durable.tasks_impl import run_crawl_ingest

    return await run_crawl_ingest(**payload)


@app.task(name="durable_ping", queue=QUEUE_MAINTENANCE)
async def durable_ping(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """最小可 defer 的烟囱 / 测试任务。

    用于验证"入队 → worker 消费 → 完成"整条 durable 链路通畅（postgres_queue 测试
    与运维冒烟用）。本阶段不接任何业务任务，迁移 index/graph/crawl 由 Phase 61/62 做。
    """
    logger.info("durable_ping", payload=payload)
    return {"pong": True, "payload": payload}


@app.periodic(cron="*/5 * * * *")
@app.task(
    name="recover_stranded_repo_summaries",
    queue=QUEUE_MAINTENANCE,
    queueing_lock="recover_stranded_repo_summaries",
    pass_context=True,
)
async def recover_stranded_repo_summaries(context: Any, timestamp: int) -> int:
    """周期重派搁浅的 repo_summary 会话（DURABLE 兜底，修复内存队列派发的丢失缺口）。

    与 ``retry_stalled_durable_jobs`` 同模式（``@app.periodic`` + ``queueing_lock``
    单例：DB 保证每周期只 defer 一份、todo 唯一不堆积，多副本 worker 天然单例）。

    缺口背景：index/graph 重启不丢（durable），但 summary/coding 走
    ``TaskDispatcher`` 进程内存队列，server/runner 重启即丢、``SubAgentSession``
    永卡 pending。本周期任务把搁浅的 **repo_summary**（只读、可安全重试）重新派发；
    coding 不在此自动重派（避免重复推 commit），详见 ``recover_stranded_summaries``。
    """
    from repositories.summary_service import recover_stranded_summaries

    recovered = await recover_stranded_summaries()
    logger.info(
        "recover_stranded_repo_summaries_tick",
        timestamp=timestamp,
        recovered=recovered,
    )
    return recovered


@app.periodic(cron="*/10 * * * *")
@app.task(
    name="retry_stalled_durable_jobs",
    queueing_lock="retry_stalled_durable_jobs",
    pass_context=True,
)
async def retry_stalled_durable_jobs(context: Any, timestamp: int) -> int:
    """周期单例 stalled rescue（DURABLE-03），替代 flock 与"仅启动补扫"。

    单例 leader 语义由两层叠加，**无需自写 leader 选举 / flock**：
    - ``@app.periodic``：DB 保证每个 cron 周期只 defer 一份（即便多副本 worker，
      天然单例）；
    - ``queueing_lock="retry_stalled_durable_jobs"``：同名任务在 todo 唯一，慢处理
      时也不堆积。

    stalled 判定基于 worker heartbeat（``get_stalled_jobs`` 默认
    ``seconds_since_heartbeat=30``），**绝不传 deprecated 的 ``nb_seconds``**——后者
    按固定时长判定会误杀仍在跑的慢任务（违反 CONTEXT"慢≠死"约束）。

    与 ``ProcrastinateBackend.retry_stalled`` 同算法：后者服务
    ``DurableTaskService.retry_stalled`` 的直接路径（手动 / 运维触发），本 periodic
    是多副本下持续 rescue 的 leader 路径；二者均基于 heartbeat、零 nb_seconds。
    """
    stalled_jobs = list(await app.job_manager.get_stalled_jobs())
    retried = 0
    for job in stalled_jobs:
        await app.job_manager.retry_job(job)
        retried += 1
    logger.info(
        "retry_stalled_durable_jobs_tick",
        timestamp=timestamp,
        stalled=len(stalled_jobs),
        retried=retried,
    )
    return retried
