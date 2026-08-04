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
        return await clone_and_index_repository(repository_id, history_id=history_id, branch=branch)


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
            return list(IngestRun.objects.filter(batch_id=batch_id, status__in=active_statuses))

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


async def run_doc_sync_pull(
    *,
    file_token: str = "",
    event_id: str = "",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """飞书→Friday 文档回拉任务体（SYNC-01）：worker 入口 bind 发起用户后委托 DocSyncService.pull。

    ``file_token`` 即飞书 docx 的 ``feishu_document_id``。worker 用干净 contextvars 不自动
    传播，必须经 ``bind_task_context`` 显式 re-bind 发起用户（未映射 / 不传 → ``system``）；
    ``component="doc_sync"`` 标注观测组件（LOGGING-SPEC）。``DocSyncService.pull`` 自身
    best-effort fail-soft（归档 / broken / 回拉失败均不抛回事件主流程），本壳不再额外吞异常。
    """
    from initiatives.services.doc_sync_service import DocSyncService

    with bind_task_context(
        user_id=initiated_by_user_id or "system",
        source="durable",
        component="doc_sync",
    ):
        return await DocSyncService().pull(
            file_token=file_token,
            event_id=event_id,
            initiated_by_user_id=initiated_by_user_id,
        )


async def run_doc_sync_push(
    *,
    doc_id: str = "",
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """Friday→飞书 文档 block 级增量推送任务体（SYNC-02）：worker 入口 bind 发起用户后委托 push。

    ``doc_id`` 为 ProjectDoc 主键。worker 用干净 contextvars 不自动传播，必须经
    ``bind_task_context`` 显式 re-bind 发起用户（未映射 / 不传 → ``system``）；
    ``component="doc_sync"`` 标注观测组件。``DocSyncService.push`` 自身 best-effort fail-soft
    （归档 / broken / 无 document_id / 无渲染器 / 外呼失败均不抛回钩子主流程），本壳不再额外吞异常。
    """
    from initiatives.services.doc_sync_service import DocSyncService

    with bind_task_context(
        user_id=initiated_by_user_id or "system",
        source="durable",
        component="doc_sync",
    ):
        return await DocSyncService().push(
            doc_id=doc_id,
            initiated_by_user_id=initiated_by_user_id,
        )


# feature list 逐模块解析的 429 退避重试上限与退避基数（秒）。
_FEATURE_PARSE_MAX_ATTEMPTS = 6
_FEATURE_PARSE_BACKOFF_BASE = 5


def _feature_parse_backoff_seconds(attempt: int) -> float:
    """429 指数退避（含轻量抖动），上限 60s。"""
    import random

    delay = min(60.0, _FEATURE_PARSE_BACKOFF_BASE * (2**attempt))
    return delay + random.uniform(0, delay * 0.2)


async def run_feature_list_parse_start(
    *,
    project_id: str,
    draft_id: str,
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """feature list 解析父任务：Step0 出模块外壳，再 fan-out 逐模块子任务并发解析。

    模块解析失败不整体失败：出模块阶段失败（无 Provider / 无结构）才置草稿 failed；
    单模块失败由子任务隔离。``initiated_by_user_id`` worker 入口 re-bind 发起用户。
    """
    from initiatives.services.feature_list_draft_service import (
        FeatureListDraftService,
    )
    from initiatives.services.feature_list_import import (
        FeatureListParseError,
        agenerate_module_outline,
    )

    service = FeatureListDraftService()
    with bind_task_context(
        user_id=initiated_by_user_id, source="durable", component="feature_list_draft"
    ):
        draft = await service.aget_by_id(draft_id)
        if draft is None:
            return {"status": "skipped", "reason": "draft_not_found", "draft_id": draft_id}
        source_text = draft.source_text or ""
        try:
            outline = await agenerate_module_outline(project_id, source_text)
        except FeatureListParseError as exc:
            await service.afail(draft_id, str(exc))
            logger.info(
                "feature_list_parse_start_failed",
                project_id=str(project_id),
                draft_id=draft_id,
                reason="outline",
            )
            return {"status": "failed", "reason": "outline", "draft_id": draft_id}

        result = await service.aset_outline(draft_id, outline)
        if result is None:
            return {"status": "skipped", "reason": "draft_gone", "draft_id": draft_id}
        _snapshot, count = result

        from durable.concurrency import afeature_parse_lock
        from durable.queues import QUEUE_FEATURE_PARSE
        from durable.service import DurableTaskService

        for idx in range(count):
            lock = await afeature_parse_lock(f"{draft_id}:{idx}")
            await DurableTaskService.defer(
                "feature_list_parse_module",
                {
                    "project_id": str(project_id),
                    "draft_id": str(draft_id),
                    "module_index": idx,
                    "attempt": 0,
                },
                queue=QUEUE_FEATURE_PARSE,
                lock=lock,
                idempotency_key=f"featparse:{draft_id}:{idx}",
                initiated_by_user_id=initiated_by_user_id,
            )
        logger.info(
            "feature_list_parse_start_dispatched",
            project_id=str(project_id),
            draft_id=draft_id,
            module_count=count,
        )
        return {"status": "dispatched", "draft_id": draft_id, "module_count": count}


async def run_feature_list_parse_module(
    *,
    project_id: str,
    draft_id: str,
    module_index: int,
    attempt: int = 0,
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """feature list 逐模块解析子任务：解析单模块功能点，429 退回队列指数退避重试。

    并发由入队点 ``lock=featparse-slot-{k}`` 控（同 lock 串行、超限留 todo）。429 达重试上限
    或非限流错误 → 该模块置 failed（不拖垮其余模块）。``initiated_by_user_id`` worker 入口 re-bind。
    """
    import datetime

    from initiatives.services.feature_list_draft_service import (
        FeatureListDraftService,
        slice_module_text,
    )
    from initiatives.services.feature_list_import import (
        FeatureListParseError,
        agenerate_module_features,
    )

    service = FeatureListDraftService()
    with bind_task_context(
        user_id=initiated_by_user_id, source="durable", component="feature_list_draft"
    ):
        draft = await service.aget_by_id(draft_id)
        if draft is None:
            return {"status": "skipped", "reason": "draft_gone", "draft_id": draft_id}
        mods = (draft.tree or {}).get("modules", []) if isinstance(draft.tree, dict) else []
        if not (0 <= module_index < len(mods)):
            return {"status": "skipped", "reason": "index_out_of_range"}
        mod = mods[module_index]
        slice_text = slice_module_text(
            draft.source_text or "", mod.get("line_start"), mod.get("line_end")
        )

        await service.aset_module_running(draft_id, module_index)
        try:
            features = await agenerate_module_features(project_id, slice_text)
        except FeatureListParseError as exc:
            upstream = getattr(exc, "upstream_status", None)
            if upstream == 429 and attempt < _FEATURE_PARSE_MAX_ATTEMPTS:
                await service.aset_module_pending(draft_id, module_index)
                delay = _feature_parse_backoff_seconds(attempt)
                run_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
                    seconds=delay
                )
                from durable.concurrency import afeature_parse_lock
                from durable.queues import QUEUE_FEATURE_PARSE
                from durable.service import DurableTaskService

                lock = await afeature_parse_lock(f"{draft_id}:{module_index}")
                await DurableTaskService.defer(
                    "feature_list_parse_module",
                    {
                        "project_id": str(project_id),
                        "draft_id": str(draft_id),
                        "module_index": module_index,
                        "attempt": attempt + 1,
                    },
                    queue=QUEUE_FEATURE_PARSE,
                    lock=lock,
                    run_at=run_at,
                    initiated_by_user_id=initiated_by_user_id,
                )
                logger.info(
                    "feature_list_parse_module_requeued",
                    project_id=str(project_id),
                    draft_id=draft_id,
                    module_index=module_index,
                    attempt=attempt + 1,
                    delay_s=round(delay, 1),
                )
                return {"status": "requeued", "module_index": module_index, "attempt": attempt + 1}
            await service.awrite_module(draft_id, module_index, failed=True)
            logger.info(
                "feature_list_parse_module_failed",
                project_id=str(project_id),
                draft_id=draft_id,
                module_index=module_index,
                upstream_status=upstream,
            )
            return {"status": "failed", "module_index": module_index}

        await service.awrite_module(draft_id, module_index, features=features)

        # 预热该模块各功能点的详情结构化缓存（best-effort）：实现「解析时就生成好、
        # 点开详情秒开、不再每次结构化」。失败不影响模块解析成功。
        try:
            from initiatives.services.feature_detail_service import (
                feature_detail_service,
            )

            sources = [f["source"] for f in features if f.get("source")]
            if sources:
                await feature_detail_service.awarm(project_id, sources)
        except Exception:  # noqa: BLE001 — 预热绝不反噬模块解析
            logger.warning(
                "feature_detail_warm_dispatch_failed",
                draft_id=draft_id,
                module_index=module_index,
                exc_info=True,
            )

        return {
            "status": "ok",
            "module_index": module_index,
            "feature_count": len(features),
        }


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
            logger.info("durable_page_index_skipped", target_id=target_id, reason="hash_unchanged")
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


# runner 派发 re-defer 退避：5s 起步、指数翻倍、300s 封顶。
_DISPATCH_BACKOFF_BASE = 5
_DISPATCH_BACKOFF_CAP = 300


def _dispatch_backoff_seconds(attempt: int) -> int:
    """无 runner / 无空槽时的 re-defer 退避秒数（5 * 2**attempt，封顶 300s）。"""
    try:
        current = max(0, int(attempt))
    except (TypeError, ValueError):
        current = 0
    return min(_DISPATCH_BACKOFF_BASE * (2**current), _DISPATCH_BACKOFF_CAP)


async def run_runner_dispatch(
    *,
    session_id: str,
    attempt: int = 0,
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """runner 派发任务体（31u）：可靠地发起一次派发（守卫 + 快照重建 + 标签匹配 + 退避）。

    形状照 ``run_blueprint_resume``：``bind_task_context(source="durable")``、恒不抛、
    异常文本过 ``redact_secrets_in_text``。语义四步：

    1. **幂等守卫（状态检查而不是禁止重派）**：session 查无 → skipped(not_found)；
       终态（completed/error/timeout/cancelled）→ skipped(terminal)；已有
       assigned/running assignment → skipped(active_assignment)——已在跑 / 已派出时
       绝不起第二个容器（防重复 push commit）。守卫 + 入队点 ``lock=dispatch-{session_id}``
       同会话串行，使判据无并发窗口。
    2. 从 ``last_output["dispatch"]`` 快照重建 DispatchTask（凭证由
       ``_rehydrate_dispatch_credentials`` 从权威源重解析 / 重铸）；快照缺失 →
       skipped(no_snapshot) + warning（理论不可达：``dispatch()`` 先持久化后入队）。
    3. ``_try_assign``：成功 → dispatched；失败（无匹配 runner / 无空槽）→ **re-defer
       backoff**（attempt+1 + run_at，5s 起步 300s 封顶）→ requeued。⛔ 不设 attempt
       上限——链条由守卫终结（session 终态 / 被取消后下一跳 no-op），300s 封顶的
       空转成本可忽略。
    4. 观测：终跳记 ``runner_dispatch_job_completed``（caller）；re-defer 那跳记
       ``runner_dispatch_requeued``（sampling——周期性 tick 不刷 caller 面）；失败兜底
       ``runner_dispatch_job_failed``（warning，error 已脱敏）。
    """
    import time

    from common.logging import redact_secrets_in_text

    started = time.perf_counter()
    with bind_task_context(user_id=initiated_by_user_id, source="durable"):
        try:
            from runners.dispatcher import (
                TERMINAL_SESSION_STATUSES,
                arebuild_dispatch_task_from_session,
                get_dispatcher,
            )
            from subagent.models import SubAgentSession

            dispatcher = get_dispatcher()
            session = await SubAgentSession.objects.filter(session_id=session_id).afirst()
            if session is None:
                result: dict[str, Any] = {"status": "skipped", "reason": "not_found"}
            elif str(session.status) in TERMINAL_SESSION_STATUSES:
                result = {"status": "skipped", "reason": "terminal"}
            elif await dispatcher._has_active_assignment(session_id):
                result = {"status": "skipped", "reason": "active_assignment"}
            else:
                task = await arebuild_dispatch_task_from_session(session)
                if task is None:
                    logger.warning(
                        "runner_dispatch_snapshot_missing",
                        category="caller",
                        component="runners",
                        initiated_by_user_id=initiated_by_user_id or "system",
                        session_id=session_id,
                    )
                    result = {"status": "skipped", "reason": "no_snapshot"}
                elif await dispatcher._try_assign(task):
                    result = {"status": "dispatched"}
                else:
                    # 无匹配 runner / 无空槽 → 按退避 re-defer；runner 恢复后到点自动派出。
                    import datetime

                    from durable.queues import QUEUE_DISPATCH
                    from durable.service import DurableTaskService

                    delay = _dispatch_backoff_seconds(attempt)
                    run_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
                        seconds=delay
                    )
                    await DurableTaskService.defer(
                        "durable_runner_dispatch",
                        {"session_id": session_id, "attempt": attempt + 1},
                        queue=QUEUE_DISPATCH,
                        lock=f"dispatch-{session_id}",
                        run_at=run_at,
                        initiated_by_user_id=initiated_by_user_id,
                    )
                    logger.info(
                        "runner_dispatch_requeued",
                        category="sampling",
                        component="runners",
                        session_id=session_id,
                        attempt=attempt + 1,
                        delay_s=delay,
                    )
                    return {"status": "requeued", "attempt": attempt + 1}

            logger.info(
                "runner_dispatch_job_completed",
                category="caller",
                component="runners",
                initiated_by_user_id=initiated_by_user_id or "system",
                session_id=session_id,
                task_type=str(getattr(session, "task_type", "") or ""),
                status=result["status"],
                reason=result.get("reason", ""),
                attempt=attempt,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            return result
        except Exception as exc:  # noqa: BLE001 — 任务体恒不抛：状态在库里，可由重派/恢复扫描重试
            logger.warning(
                "runner_dispatch_job_failed",
                category="caller",
                component="runners",
                initiated_by_user_id=initiated_by_user_id or "system",
                session_id=session_id,
                attempt=attempt,
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            return {"status": "failed", "session_id": session_id}


async def run_blueprint_resume(
    *,
    session_id: str,
    initiated_by_user_id: str | None = None,
) -> dict[str, Any]:
    """蓝图编排续驱任务体（116 队列化）：把会话驱动到下一个挂起点或终态。

    作答 / 确认门动作端点只落库 + 入队本任务（「已受理」语义）——驱动不再在 HTTP
    请求内跑，请求被杀 / 进程重启不再能吞掉续驱（Postgres 路径由 procrastinate 持久化，
    重启后 worker 接着跑；in-process fallback 配合周期恢复扫描兜底）。

    委托 ``services.process_runtime.blueprint_resume.arun_blueprint_resume``（驱动 +
    chat barrier / 工作流节点两个入口回灌 hook 的共同出口）。任务体自身恒不抛：
    驱动失败记 warning 并如实返回，交给下一次动作或恢复扫描重试，⛔ 不进 procrastinate
    的自动重试（蓝图 stage 内含 LLM 调用，盲目重试代价高且驱动本身幂等可续）。
    """
    from services.process_runtime.blueprint_resume import arun_blueprint_resume

    with bind_task_context(user_id=initiated_by_user_id, source="durable"):
        return await arun_blueprint_resume(
            session_id, initiated_by_user_id=initiated_by_user_id or "system"
        )
