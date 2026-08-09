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
    QUEUE_BLUEPRINT,
    QUEUE_CHARTER,
    QUEUE_SCAN,
    QUEUE_CRAWL_INGEST,
    QUEUE_DISPATCH,
    QUEUE_DOC_SYNC,
    QUEUE_FEATURE_PARSE,
    QUEUE_GRAPH,
    QUEUE_INDEX,
    QUEUE_MAINTENANCE,
    QUEUE_PAGE_INDEX,
    QUEUE_REPO_SUMMARY,
)

logger = structlog.get_logger(__name__)


@app.task(name="durable_index", queue=QUEUE_INDEX)
async def durable_index(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """代码索引 durable 任务（procrastinate 包壳，委托共用任务体）。

    显式 ``name="durable_index"`` 与 ``backends.defer`` 的裸名查找
    （``app.tasks.get("durable_index")``）是同一 single source of truth（Phase 60
    CR-01 教训）。keyword-only 形参与 payload 契约逐字一致，下游
    ``DurableTaskService.defer("durable_index", {...})`` 经 ``defer_async(**payload)``
    展开传入。``initiated_by_user_id``（CTX-02）显式形参消费 payload 同名键并转发给
    任务体，使 procrastinate 后端也能在 worker 入口 bind 发起用户（不传零回归）。
    """
    from durable.tasks_impl import run_index

    return await run_index(
        repository_id=repository_id,
        history_id=history_id,
        branch=branch,
        trigger=trigger,
        initiated_by_user_id=initiated_by_user_id,
    )


@app.task(name="durable_graph", queue=QUEUE_GRAPH)
async def durable_graph(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
    initiated_by_user_id: str | None = None,
) -> Any:
    """代码图谱构建 durable 任务（procrastinate 包壳，委托共用任务体）。"""
    from durable.tasks_impl import run_graph

    return await run_graph(
        repository_id=repository_id,
        history_id=history_id,
        branch=branch,
        trigger=trigger,
        initiated_by_user_id=initiated_by_user_id,
    )


@app.task(name="durable_page_index", queue=QUEUE_PAGE_INDEX)
async def durable_page_index(**payload: Any) -> dict[str, Any]:
    """页面级索引 durable 任务（占位包壳，委托共用任务体）。"""
    from durable.tasks_impl import run_page_index

    return await run_page_index(**payload)


@app.task(name="durable_repo_summary", queue=QUEUE_REPO_SUMMARY)
async def durable_repo_summary(
    *, repository_id: str, initiated_by_user_id: str | None = None
) -> dict[str, Any]:
    """仓库 AI 描述派发 durable 任务（procrastinate 包壳，委托共用任务体）。

    durable job 只负责"可靠地发起一次 repo_summary 派发"（创建 session + 投递到 Runner），
    重活在 Runner 容器内执行。这样建仓/手动触发的派发不再随 server 重启丢失。
    幂等：入队点带 ``idempotency_key=f"summary:{repo_id}"``，同仓在途只一份。
    ``initiated_by_user_id``（CTX-02）显式形参消费 payload 同名键并转发（不传零回归）。
    """
    from durable.tasks_impl import run_repo_summary

    return await run_repo_summary(
        repository_id=repository_id, initiated_by_user_id=initiated_by_user_id
    )


@app.task(name="durable_doc_sync_pull", queue=QUEUE_DOC_SYNC)
async def durable_doc_sync_pull(
    *,
    file_token: str = "",
    event_id: str = "",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """飞书→Friday 文档回拉 durable 任务（procrastinate 包壳，委托共用任务体）。

    镜像 ``durable_index`` 包壳：显式 ``name="durable_doc_sync_pull"`` 与 ``backends.defer``
    裸名查找（``app.tasks.get("durable_doc_sync_pull")``）同源；payload 仅
    ``file_token`` / ``event_id``（**绝不落正文/token 明文**），经 ``defer_async(**payload)``
    展开传入。``file_token`` 即飞书 docx 的 ``feishu_document_id``。``initiated_by_user_id``
    （CTX-02）显式形参消费 payload 同名键并转发给任务体，worker 入口据此 re-bind 发起用户
    （未映射 / 不传 → ``system``）。
    """
    from durable.tasks_impl import run_doc_sync_pull

    return await run_doc_sync_pull(
        file_token=file_token,
        event_id=event_id,
        initiated_by_user_id=initiated_by_user_id,
    )


@app.task(name="durable_doc_sync_push", queue=QUEUE_DOC_SYNC)
async def durable_doc_sync_push(
    *,
    doc_id: str = "",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """Friday→飞书 文档 block 级增量推送 durable 任务（procrastinate 包壳，委托共用任务体）。

    镜像 ``durable_doc_sync_pull`` 包壳：显式 ``name="durable_doc_sync_push"`` 与 ``backends.defer``
    裸名查找同源；payload 仅 ``doc_id``（ProjectDoc 主键，**绝不**落正文/token 明文），经
    ``defer_async(**payload)`` 展开传入。入队点 ``lock=docsync-{feishu_document_id}``（与
    83-02 pull / 83-06 poll 对同一文档同值 → pull/push/poll 全串行）+ ``run_at=now+DEBOUNCE``
    合并窗口内多次写。``initiated_by_user_id``（CTX-02）显式形参消费 payload 同名键并转发，
    worker 入口据此 re-bind 发起用户（未映射 / 不传 → ``system``）。
    """
    from durable.tasks_impl import run_doc_sync_push

    return await run_doc_sync_push(
        doc_id=doc_id,
        initiated_by_user_id=initiated_by_user_id,
    )


@app.task(name="durable_crawl_ingest", queue=QUEUE_CRAWL_INGEST)
async def durable_crawl_ingest(**payload: Any) -> dict[str, Any]:
    """爬取批次入库 durable 任务（procrastinate 包壳，委托共用任务体）。

    逐字镜像 ``durable_page_index`` 包壳：显式 ``name="durable_crawl_ingest"`` 与
    ``backends.defer`` 裸名查找（``app.tasks.get("durable_crawl_ingest")``）同源；payload
    仅 ``batch_id`` / ``concurrency``，经 ``defer_async(**payload)`` 展开传入。
    """
    from durable.tasks_impl import run_crawl_ingest

    return await run_crawl_ingest(**payload)


@app.task(name="feature_list_parse_start", queue=QUEUE_FEATURE_PARSE)
async def feature_list_parse_start(
    *,
    project_id: str,
    draft_id: str,
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """feature list 解析父任务（procrastinate 包壳，委托共用任务体）。

    显式 ``name="feature_list_parse_start"`` 与 ``backends.defer`` 裸名查找同源；payload
    仅 ``project_id`` / ``draft_id``（原文落在 FeatureListDraft.source_text，不入 payload）。
    """
    from durable.tasks_impl import run_feature_list_parse_start

    return await run_feature_list_parse_start(
        project_id=project_id,
        draft_id=draft_id,
        initiated_by_user_id=initiated_by_user_id,
    )


@app.task(name="feature_list_parse_module", queue=QUEUE_FEATURE_PARSE)
async def feature_list_parse_module(
    *,
    project_id: str,
    draft_id: str,
    module_index: int,
    attempt: int = 0,
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """feature list 逐模块解析子任务（procrastinate 包壳，委托共用任务体）。

    入队点带 ``lock=featparse-slot-{k}`` 控并发；429 退回队列由任务体 re-defer（attempt+1
    + schedule_at 退避）。
    """
    from durable.tasks_impl import run_feature_list_parse_module

    return await run_feature_list_parse_module(
        project_id=project_id,
        draft_id=draft_id,
        module_index=module_index,
        attempt=attempt,
        initiated_by_user_id=initiated_by_user_id,
    )


@app.task(name="durable_blueprint_resume", queue=QUEUE_BLUEPRINT)
async def durable_blueprint_resume(
    *,
    session_id: str,
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """蓝图编排续驱 durable 任务（procrastinate 包壳，委托共用任务体）。

    显式 ``name="durable_blueprint_resume"`` 与 ``backends.defer`` 的裸名查找同源；
    payload 仅 ``session_id``（澄清正文 / 方案内容一律不进 payload）。入队点带
    ``lock=blueprint-resume-{session_id}``：同会话的多次动作串行驱动（doing 并发锁），
    ⛔ 不带 ``idempotency_key``——去重会吃掉「驱动进行中又来一次人工动作」的触发。
    ``initiated_by_user_id``（CTX-02）显式形参消费 payload 同名键并转发给任务体。
    """
    from durable.tasks_impl import run_blueprint_resume

    return await run_blueprint_resume(
        session_id=session_id,
        initiated_by_user_id=initiated_by_user_id,
    )


@app.task(name="durable_runner_dispatch", queue=QUEUE_DISPATCH)
async def durable_runner_dispatch(
    *,
    session_id: str,
    attempt: int = 0,
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """runner 派发 durable 任务（procrastinate 包壳，委托共用任务体）。

    显式 ``name="durable_runner_dispatch"`` 与 ``backends.defer`` 的裸名查找同源；
    payload 仅 ``session_id`` / ``attempt``（凭证 / prompt 正文一律不进 payload——
    任务体从 ``last_output["dispatch"]`` 快照重建并从权威源 rehydrate 凭证）。
    入队点 ``lock=dispatch-{session_id}``（同 session 派发串行，任务体的状态守卫
    判据因此无并发窗口）、⛔ 不带 ``idempotency_key``——同 session 的合法重派发
    （rejected 重排 / 断连恢复 / stranded 扫描）不能被 todo 去重吃掉，防重的职责在
    任务体状态守卫（终态 / active assignment → no-op）。
    ``initiated_by_user_id``（CTX-02）显式形参消费 payload 同名键并转发给任务体。
    """
    from durable.tasks_impl import run_runner_dispatch

    return await run_runner_dispatch(
        session_id=session_id,
        attempt=attempt,
        initiated_by_user_id=initiated_by_user_id,
    )


@app.task(name="durable_charter_draft", queue=QUEUE_CHARTER)
async def durable_charter_draft(
    *,
    repository_id: str,
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """仓库章程 AI 起草 durable 任务（procrastinate 包壳，委托共用任务体）。

    summary 成功回写后入队；任务体内调 ``adraft_charter``（P11 保护）。
    幂等：入队点 ``idempotency_key=f"charter:{repo_id}"``。
    ``initiated_by_user_id``（CTX-02）显式形参消费 payload 同名键并转发。
    """
    from durable.tasks_impl import run_charter_draft

    return await run_charter_draft(
        repository_id=repository_id,
        initiated_by_user_id=initiated_by_user_id,
    )



@app.task(name="durable_semgrep_scan", queue=QUEUE_SCAN)
async def durable_semgrep_scan(
    *,
    repository_id: str,
    mr_key: str = "",
    source_sha: str = "",
    target_sha: str = "",
    branch_name: str = "",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """Semgrep diff-aware 扫描 durable 任务（procrastinate 包壳）。

    入队点 ``QUEUE_SCAN`` + ``idempotency_key=semgrep:{repo}:{mr_key}`` +
    ``lock=scan-slot-*``。业务语义 fail-open：超时/CLI 失败返回含 ``error_code``
    的 dict，不阻断建 MR。MR 文案回填钩子留给 127-04。
    """
    from durable.tasks_impl import run_semgrep_scan

    return await run_semgrep_scan(
        repository_id=repository_id,
        mr_key=mr_key,
        source_sha=source_sha,
        target_sha=target_sha,
        branch_name=branch_name,
        initiated_by_user_id=initiated_by_user_id,
    )


@app.task(name="durable_community_rebuild", queue=QUEUE_GRAPH)
async def durable_community_rebuild(
    *,
    repository_id: str,
    branch_name: str = "",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """符号社区 Louvain 重建 durable 任务（procrastinate 包壳）。

    边/图构建完成后入队；任务体内经 ``get_graph_service`` 取图后
    ``rebuild_communities``（D-03）。幂等：
    ``idempotency_key=f"community:{repo_id}:{branch}"``。
    ``initiated_by_user_id``（CTX-02）显式形参消费 payload 同名键并转发。
    """
    from durable.tasks_impl import run_community_rebuild

    return await run_community_rebuild(
        repository_id=repository_id,
        branch_name=branch_name,
        initiated_by_user_id=initiated_by_user_id,
    )


@app.task(name="durable_process_rebuild", queue=QUEUE_GRAPH)
async def durable_process_rebuild(
    *,
    repository_id: str,
    branch_name: str = "",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """执行流 ProcessTrace 重建 durable 任务（procrastinate 包壳）。

    社区重建成功后链式入队；任务体内经 ``get_graph_service`` 取图后
    ``rebuild_processes``（D-03）。幂等：
    ``idempotency_key=f"process:{repo_id}:{branch}"``。
    ``initiated_by_user_id``（CTX-02）显式形参消费 payload 同名键并转发。
    """
    from durable.tasks_impl import run_process_rebuild

    return await run_process_rebuild(
        repository_id=repository_id,
        branch_name=branch_name,
        initiated_by_user_id=initiated_by_user_id,
    )


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

    缺口背景（31u 后已收窄）：派发链已 durable 化（``QUEUE_DISPATCH`` + re-defer
    backoff + 任务体状态守卫），coding 在内的所有 task_type 的重派由
    ``arecover_stranded_dispatch_sessions``（apscheduler 保险丝）统一覆盖——守卫
    （终态 / active assignment → no-op）防重复容器 / 重复 commit。本周期任务保留
    repo_summary 维度的业务收敛（旧会话标 TIMEOUT + 起新会话刷新仓库状态），
    详见 ``recover_stranded_summaries``。
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
    queue=QUEUE_MAINTENANCE,
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
