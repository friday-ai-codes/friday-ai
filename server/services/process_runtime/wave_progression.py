"""入口无关的多仓 wave 编码推进 helper（Phase 44-04，WAVE-02 推进核心）。

镜像 ``research_aggregation.py``（barrier 全终态判定 + status guard 幂等）与
``resume.py``（入口无关续驱、不造两套）：把「回填当前在途终态 → 传递闭包阻断失败上游
的全部下游 → 决策出口（等待 / 派发下一 wave / 收尾）」抽成入口无关函数，供
工作流入口（plan 05 AICodingNode resume 段）先用、chat 编码入口未来复用。

设计要点：
- **入口无关 / 不造两套**：推进逻辑只读 DB 重算（不读内存态），由容器回调
  ``_schedule_workflow_resume`` 触发节点重入自驱（对齐 Phase 43 闭环，绝不新建调度
  循环 / 轮询 / 定时器）。
- **状态纯度（INV-6）**：状态回填 / 下游阻断只经 ``RepoCodingTaskService.mark_*``
  条件更新，**绝不**直接写 ``task.status``；重复回调经条件更新天然 no-op（幂等）。
- **执行顺序是 liveness 关键**：``aadvance_coding_waves`` **严格**按「① 回填 → ②
  传递闭包阻断 → ③ 决策出口」执行——阻断必须在任何 early-return 之前完成，否则未
  派发的 pending 下游永不被阻断 → ``all_terminal`` 永不触发 → 工作流死锁
  （T-44-DEADLOCK）。
- **权威字段守门（T-44-TAMPER）**：终态回填按服务端权威 ``SubAgentSession.status``
  （经 ``subagent_session_id`` 标量取），绝不信 runner 可经 progress 篡改的字段。
- **async ORM 安全**：``*_id`` 标量 / ``afirst`` / ``aexists`` / ``async for``，绝不
  在 async 上下文裸访问 lazy-FK（``task.subagent_session`` / ``task.depends_on``）。
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["acurrent_wave_all_terminal", "aadvance_coding_waves"]


async def acurrent_wave_all_terminal(plan_version_id: Any, wave: int) -> bool:
    """指定 wave 的全部 RepoCodingTask 是否都已终态（done/failed）。

    镜像 ``aall_research_tasks_terminal``——存在任一 ``pending`` / ``running`` 即非终态
    （终态含 ``failed``，**不是**仅 ``done``——失败仓永远不会 done，gate 用「全 done」会
    永挂，故 ``failed`` 也算终态，T-44-GATE）。

    **仅可对在途 RUNNING 所在的 wave 求值**：绝不对「最小 pending wave」求值用作 gate
    （未派发的 pending 下游 wave 不算「在途未终」，否则会抢先 return waiting、阻断 / dispatch
    永不可达 → 死锁）。``aadvance_coding_waves`` 的等待判定按 RUNNING 在途为准，不靠本函数；
    本函数仍导出供 barrel / 测试与 plan 05 复用。
    """
    from delivery.models import RepoCodingTask, RepoCodingTaskStatus

    pending = await RepoCodingTask.objects.filter(
        artifact_version_id=plan_version_id,
        wave=wave,
        status__in=[RepoCodingTaskStatus.PENDING, RepoCodingTaskStatus.RUNNING],
    ).aexists()
    return not pending


# SubAgentSession 终态 → RepoCodingTask 终态映射（服务端权威 status）。
# completed → done；error/timeout/cancelled → failed；pending/running → 在途（跳过，等下次回调）。
_SUBAGENT_DONE = ("completed",)
_SUBAGENT_FAILED = ("error", "timeout", "cancelled")


async def aadvance_coding_waves(plan_version_id: Any, *, service: Any = None) -> dict:
    """入口无关 wave 推进续驱：回填在途终态 → 传递闭包阻断 → 决策出口。

    返回 dict（互斥三态之一）：

    - ``{"waiting": True}``：仍有 RUNNING 在途 task，等下一次容器回调，不推进。
    - ``{"dispatch": [task, ...], "wave": n}``：无 RUNNING，存在 ``depends_on`` 全 done 的
      pending task，取其中**最小 wave** 这批返回供调用方 dispatch。
    - ``{"all_terminal": True}``：无 pending 且无 running——所有 task 已终态（含被阻断链），
      节点进入收尾。

    **执行顺序严格固定（liveness 关键，阻断必须在任何 early-return 之前完成）：**

    1. **回填（running→终态）**：遍历本 plan_version 全部 ``running`` task，按其
       ``subagent_session_id`` 标量取 ``SubAgentSession``（服务端权威 status），经
       ``service.mark_done`` / ``service.mark_failed`` 回填终态（无 subagent_session_id 或
       SubAgentSession 仍在途则跳过，等下次回调）。**不在此 step return**。
    2. **下游阻断（传递闭包 BFS/worklist）**：回填后重查全部 ``failed`` task，沿
       ``dependents`` 反向边对其**直接 / 间接**下游做多跳传播——每命中一个仍 ``pending``
       的下游即经 ``service.mark_blocked`` 标 blocked（``error.reason=upstream_failed``）并
       入队继续向其 ``dependents`` 传播，``seen`` 去重防重入。链 ``A→B→C`` 中 A failed 时
       **B 与 C 在单次 aadvance 内均被阻断**（C 不会因 ``depends_on=B`` 永不为 done 而残留
       pending → 收尾可达不死锁，T-44-DEADLOCK）。**不在此 step return**。
    3. **决策出口（阻断完成后才判定）**：a. 仍有 RUNNING 在途 → ``waiting``；
       b. 否则有 ``depends_on`` 全 done 的 pending → dispatch 最小可派发 wave；
       c. 否则（无 pending 无 running）→ ``all_terminal``。

    幂等：状态只经 service 条件更新（重复调用 no-op）；wave 全从 DB 重算（不读内存）。
    本函数不吞异常（由调用方 plan 05 包 try/except swallow），但 service 幂等保证重复安全。
    """
    from delivery.models import RepoCodingTask, RepoCodingTaskStatus

    if service is None:
        from delivery.services import RepoCodingTaskService

        service = RepoCodingTaskService()

    # ── Step 1：回填（running→终态），按服务端权威 SubAgentSession.status（T-44-TAMPER）──
    await _backfill_running_terminal(plan_version_id, service)

    # ── Step 2：下游阻断（传递闭包 BFS，必须在决策出口前做完——liveness 关键）──
    await _block_downstream_transitive(plan_version_id, service)

    # ── Step 3：决策出口（阻断完成后才判定）──
    # a. 仍有 RUNNING 在途 → 等待（等待判定 keys off RUNNING，不靠最小 pending wave）。
    running_exists = await RepoCodingTask.objects.filter(
        artifact_version_id=plan_version_id,
        status=RepoCodingTaskStatus.RUNNING,
    ).aexists()
    if running_exists:
        return {"waiting": True}

    # b. 有可派发 pending（depends_on 全 done）→ dispatch 最小可派发 wave。
    dispatchable = await _collect_dispatchable_pending(plan_version_id)
    if dispatchable:
        min_wave = min(task.wave for task in dispatchable)
        batch = [task for task in dispatchable if task.wave == min_wave]
        return {"dispatch": batch, "wave": min_wave}

    # c. 无 pending 且无 running → 收尾（被阻断链全部 blocked 后即落入此分支）。
    return {"all_terminal": True}


async def _backfill_running_terminal(plan_version_id: Any, service: Any) -> None:
    """回填 running task 终态：按服务端权威 ``SubAgentSession.status`` 经 service 标终态。"""
    from delivery.models import RepoCodingTask, RepoCodingTaskStatus
    from subagent.models import SubAgentSession

    async for task in RepoCodingTask.objects.filter(
        artifact_version_id=plan_version_id,
        status=RepoCodingTaskStatus.RUNNING,
    ):
        sid = task.subagent_session_id
        if not sid:
            # 尚未回填 subagent_session（首发 dispatch 失败 / 时序）→ 跳过，等下次回调。
            continue
        sess = await SubAgentSession.objects.filter(id=sid).afirst()
        if sess is None:
            continue
        sess_status = str(sess.status)
        if sess_status in _SUBAGENT_DONE:
            await service.mark_done(task)
            # ── ARTIFACT-01：产物提取落库（fail-soft，绝不阻塞 wave 推进 / 回调主流程）──
            # 独立 try/except 不向 _backfill_running_terminal 外冒泡：提取失败时 task 仍正确
            # done，仅 produced_artifacts 留空（下游注入段为空，零回归）。无 TaskResult →
            # 纯函数自落 {"available": False} 占位（非异常路径，T-45-04）。
            try:
                from repositories.models import Repository
                from services.process_runtime.artifact_extraction import (
                    build_produced_artifacts,
                )
                from subagent.models import TaskResult

                # async ORM 安全：复用已取出的 sess + *_id 标量 + afirst，绝不裸访问 lazy-FK。
                # 显式 -created_at 排序（最新优先）保多 TaskResult 时选取确定性（不依赖 DB 默认序）。
                tr = (
                    await TaskResult.objects.filter(session=sess)
                    .order_by("-created_at")
                    .afirst()
                )
                repo = await Repository.objects.filter(id=task.repository_id).afirst()
                repo_name = repo.name if repo else str(task.repository_id)
                artifacts = build_produced_artifacts(
                    repository_id=str(task.repository_id),
                    repository_name=repo_name,
                    task_result=tr,
                )
                await service.record_produced_artifacts(task, artifacts)
            except Exception as exc:  # noqa: BLE001 — 提取降级，不影响 done 推进
                # 仅记 task_id/error 字符串，绝不记产物正文 / token（T-45-01）。
                logger.warning(
                    "coding_artifact_extract_failed",
                    task_id=str(task.id),
                    error=str(exc),
                )
        elif sess_status in _SUBAGENT_FAILED:
            await service.mark_failed(
                task,
                {
                    "reason": "container_failed",
                    "subagent_status": sess_status,
                    "error": sess.last_error or "",
                },
            )
        # pending / running / idle → SubAgentSession 仍在途，不回填（等下次回调）。


async def _block_downstream_transitive(plan_version_id: Any, service: Any) -> None:
    """传递闭包阻断：沿 ``dependents`` 反向边把 failed 上游的全部 pending 下游标 blocked。

    BFS/worklist 多跳传播：初始 worklist=全部 failed task，弹出 ``u`` 遍历其仍 ``pending``
    的 ``dependents``，经 ``service.mark_blocked`` 标 blocked 并入队继续向下游传播，``seen``
    去重防重入。运行中 / 已终态的下游不强翻（mark_blocked 仅 pending→failed，幂等）。
    """
    from delivery.models import RepoCodingTask, RepoCodingTaskStatus

    worklist = [
        task
        async for task in RepoCodingTask.objects.filter(
            artifact_version_id=plan_version_id,
            status=RepoCodingTaskStatus.FAILED,
        )
    ]
    seen = {str(task.id) for task in worklist}

    while worklist:
        upstream = worklist.pop()
        upstream_id = str(upstream.repository_id)
        # 反查 dependents（依赖我者）中仍 pending 的下游；async for 安全迭代反向 M2M。
        async for downstream in upstream.dependents.filter(
            status=RepoCodingTaskStatus.PENDING
        ):
            await service.mark_blocked(downstream, [upstream_id])
            # downstream 现已 failed（blocked）→ 继续向其 dependents 传播（多跳传递闭包）。
            did = str(downstream.id)
            if did not in seen:
                seen.add(did)
                worklist.append(downstream)


async def _collect_dispatchable_pending(plan_version_id: Any) -> list:
    """收集 ``depends_on`` 全为 done 的 pending task（无上游 / 上游全 done 即可派发）。

    经传递闭包阻断后，残留 pending task 的上游只可能是 done / pending / running（failed
    上游已把下游阻断），故 ``depends_on.exclude(status=done).aexists()`` 为 False 即全 done。
    """
    from delivery.models import RepoCodingTask, RepoCodingTaskStatus

    dispatchable: list = []
    async for task in RepoCodingTask.objects.filter(
        artifact_version_id=plan_version_id,
        status=RepoCodingTaskStatus.PENDING,
    ):
        has_unmet = await task.depends_on.exclude(
            status=RepoCodingTaskStatus.DONE
        ).aexists()
        if not has_unmet:
            dispatchable.append(task)
    return dispatchable
