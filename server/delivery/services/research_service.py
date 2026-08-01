"""ResearchService —— RepoResearchTask / PartialPlan 的唯一写入入口（Phase 39-02，INV-6）。

承载 v0.7 编排「map 段」子任务级状态机与可靠恢复规则（DOMAIN §6/§14），对齐
``PlanSessionService`` / ``TechnicalPlanService`` 单一写入范式：

- ``create_tasks_for_session``：为需深入仓建 ``RepoResearchTask``（幂等，resume 安全）。
- ``mark_running`` / ``mark_done`` / ``mark_failed``：子任务级状态推进。
- ``record_partial``：写结构化 §7 ``PartialPlan``（content + content_hash）并置 done。
- ``retry_task``（RESEARCH-02）：单仓重试隔离——仅复位该 failed task + attempt+1，
  **绝不触碰其他 task / session.status**。
- ``bump_attempt``：纯派发计数自增（不改 status、不绑 stage 名），供自实现重试上界的
  调用方（蓝图链 ``repo_research``）记账。
- ``invalidate_for_repo``（RESEARCH-03）：仓库重索引时把关联 valid PartialPlan 置失效 +
  对应 RepoResearchTask→stale，可重入幂等。

``content_hash`` 为**本地** ``sha256(canonical JSON sort_keys)``，不 import knowledge
（INV-3 边界）。所有 ORM 写经 ``sync_to_async`` 桥接（禁止 async 上下文裸 ORM）。本 service
**不** dispatch 容器、**不**做 filter（那是 39-03 adapter 职责）——只管状态/落库。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db.models import F
from django.utils import timezone

from delivery.models import PartialPlan, RepoResearchTask, RepoResearchTaskStatus

logger = structlog.get_logger(__name__)

__all__ = ["ResearchService"]


class ResearchService:
    """RepoResearchTask / PartialPlan 状态与落库唯一入口（INV-6 精神）。"""

    async def create_tasks_for_session(
        self, session: Any, deep_repos: list[dict]
    ) -> list[RepoResearchTask]:
        """为每个需深入仓建 RepoResearchTask（status=pending, attempt=0），幂等。

        ``deep_repos`` 每项形如 ``{"repository_id": str, "routed_confidence": str}``；
        以 ``get_or_create(session, repository_id)`` 保证幂等（resume / 重入不重建），
        返回创建/取到的 task 列表。
        """
        return await self._create_tasks_sync(session, deep_repos)

    @sync_to_async
    def _create_tasks_sync(self, session: Any, deep_repos: list[dict]) -> list[RepoResearchTask]:
        tasks: list[RepoResearchTask] = []
        for item in deep_repos:
            repository_id = item.get("repository_id")
            if not repository_id:
                continue
            task, _created = RepoResearchTask.objects.get_or_create(
                session=session,
                repository_id=repository_id,
                defaults={
                    "status": RepoResearchTaskStatus.PENDING,
                    "routed_confidence": item.get("routed_confidence", "") or "",
                    "attempt": 0,
                },
            )
            tasks.append(task)
        return tasks

    async def mark_running(self, task: RepoResearchTask, subagent_session: Any) -> None:
        """task.status→running，回填 subagent_session 外键。"""
        await self._mark_running_sync(task, subagent_session)

    @sync_to_async
    def _mark_running_sync(self, task: RepoResearchTask, subagent_session: Any) -> None:
        task.status = RepoResearchTaskStatus.RUNNING
        task.subagent_session = subagent_session
        task.save(update_fields=["status", "subagent_session", "updated_at"])

    async def mark_done(self, task: RepoResearchTask) -> None:
        """task.status→done。"""
        await self._mark_done_sync(task)

    @sync_to_async
    def _mark_done_sync(self, task: RepoResearchTask) -> None:
        task.status = RepoResearchTaskStatus.DONE
        task.save(update_fields=["status", "updated_at"])

    async def mark_failed(self, task: RepoResearchTask, error: Any) -> None:
        """task.status→failed，error JSON 落库（非 dict 包成 {"message": str}）。"""
        await self._mark_failed_sync(task, error)

    @sync_to_async
    def _mark_failed_sync(self, task: RepoResearchTask, error: Any) -> None:
        task.status = RepoResearchTaskStatus.FAILED
        task.error = error if isinstance(error, dict) else {"message": str(error)}
        task.save(update_fields=["status", "error", "updated_at"])

    async def record_partial(self, task: RepoResearchTask, content: dict) -> PartialPlan:
        """写结构化 §7 PartialPlan（content + content_hash, valid=True）并置 task done。

        ``content_hash`` = sha256 of canonical JSON（sort_keys, ensure_ascii=False），本地算，
        对齐 PlanVersion content_hash 由 service 算的范式（不 import knowledge）。
        """
        content_hash = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return await self._record_partial_sync(task, content, content_hash)

    @sync_to_async
    def _record_partial_sync(
        self, task: RepoResearchTask, content: dict, content_hash: str
    ) -> PartialPlan:
        partial = PartialPlan.objects.create(
            research_task=task,
            content=content,
            content_hash=content_hash,
            valid=True,
        )
        task.status = RepoResearchTaskStatus.DONE
        task.save(update_fields=["status", "updated_at"])
        return partial

    async def retry_task(self, task: RepoResearchTask) -> RepoResearchTask:
        """单仓重试/复位隔离（RESEARCH-02/03）：failed 或 stale task → pending + attempt+1。

        IN-01 守护：
        - **session 状态前置校验**：仅当所属 ``PlanSession`` 仍在 ``researching`` 才允许
          重试/复位——否则会在已 ``merging``/``done`` 的 session 下挂回 ``pending`` 任务，
          制造「已推进 session 下挂 pending 子任务」的状态不一致；非 researching → ``raise``.
        - **stale 复位入口**：``stale`` 任务（重索引失效，RESEARCH-03）与 ``failed`` 对等
          可复位 pending 重派（融合前重跑），不再无恢复路径。

        以 ``filter(id, status__in=[failed, stale]).update(status=pending, attempt=F+1)``
        条件更新，影响行数 != 1 → ``raise ValueError``（非 failed/stale 不可重试，镜像
        PlanSessionService 条件更新 + 断言范式）。**绝不触碰其他 task / 不改 session.status**。
        """
        return await self._retry_task_sync(task)

    @sync_to_async
    def _retry_task_sync(self, task: RepoResearchTask) -> RepoResearchTask:
        from delivery.models import ConvergenceSession

        # session 状态前置校验（IN-01）：仅 research stage 可重试/复位
        current_stage = (
            ConvergenceSession.objects.filter(id=task.session_id)
            .values_list("current_stage", flat=True)
            .first()
        )
        if current_stage != "research":
            raise ValueError(
                f"RepoResearchTask {task.id} 所属 ConvergenceSession 非 research stage"
                f"（current_stage={current_stage}），不可重试/复位"
            )
        updated = RepoResearchTask.objects.filter(
            id=task.id,
            status__in=[RepoResearchTaskStatus.FAILED, RepoResearchTaskStatus.STALE],
        ).update(
            status=RepoResearchTaskStatus.PENDING,
            attempt=F("attempt") + 1,
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise ValueError(
                f"RepoResearchTask {task.id} 非 failed/stale 态不可重试（当前 status={task.status}）"
            )
        task.refresh_from_db()
        return task

    async def bump_attempt(self, task: RepoResearchTask) -> int:
        """派发计数自增（**只动 ``attempt``，不改 status / 不校验 stage**）。

        与 :meth:`retry_task` 的分工：``retry_task`` 是「复位并重试」，硬绑 ``research``
        stage 名与 failed/stale 前置；本方法只是「这个 task 又被派了一次容器」的记账，
        供调用方自行实现派发次数上界（蓝图链 stage 名为 ``repo_research``，复用
        ``retry_task`` 会恒 raise）。返回自增后的 ``attempt``（更新失败返 -1）。
        """
        return await self._bump_attempt_sync(task)

    @sync_to_async
    def _bump_attempt_sync(self, task: RepoResearchTask) -> int:
        updated = RepoResearchTask.objects.filter(id=task.id).update(
            attempt=F("attempt") + 1, updated_at=timezone.now()
        )
        if updated != 1:
            return -1
        attempt = (
            RepoResearchTask.objects.filter(id=task.id).values_list("attempt", flat=True).first()
        )
        task.attempt = int(attempt or 0)
        return task.attempt

    async def mark_stale(self, task_ids: list) -> int:
        """澄清回答后置指定 RepoResearchTask → stale + 其 valid PartialPlan 失效（CLARIFY-01）。

        与 ``invalidate_for_repo``（按 repo 重索引，reason=repo_reindexed）区别：本方法按
        **指定 task_ids**（澄清 affected_partials）置 stale，``invalidated_reason="clarification"``，
        使其满足 §14「stale 须重跑后才满足 barrier」——由 researching 重派（ResearchDispatchAdapter
        的 DISPATCHABLE 含 stale）。**只触指定 task，绝不动其他**；已 stale 幂等跳过。
        返回失效 PartialPlan 计数。

        WR-01 安全前置：仅把**已终态**（done/failed）的 affected 任务置 stale 重跑——
        正 ``running``/``pending`` 的在途任务**不**置 stale（让其自然完成）。否则会出现：
        running 任务被置 stale → researching 对同仓重派第二个容器；而原在途容器的晚到
        完成回调进入 ``_aload_research_task`` 时因 task 已 stale（终态判定）被静默丢弃——
        同仓双容器 + 丢弃一份结果。让在途任务自然完成可避免重复派发与结果丢弃；其结果
        正常落库后若仍需失效，可由后续重索引/再澄清按需处理。
        """
        return await self._mark_stale_sync(task_ids)

    @sync_to_async
    def _mark_stale_sync(self, task_ids: list) -> int:
        if not task_ids:
            return 0
        # WR-01：只对已终态（done/failed）的 affected 任务置 stale 重跑，跳过在途
        # （running/pending）任务——避免对在途容器同仓双派 + 晚到回调结果被静默丢弃。
        terminal_ids = list(
            RepoResearchTask.objects.filter(
                id__in=task_ids,
                status__in=[
                    RepoResearchTaskStatus.DONE,
                    RepoResearchTaskStatus.FAILED,
                ],
            ).values_list("id", flat=True)
        )
        if not terminal_ids:
            return 0
        invalidated = PartialPlan.objects.filter(
            research_task_id__in=terminal_ids, valid=True
        ).update(valid=False, invalidated_reason="clarification")
        RepoResearchTask.objects.filter(id__in=terminal_ids).update(
            status=RepoResearchTaskStatus.STALE, updated_at=timezone.now()
        )
        return invalidated

    async def invalidate_for_repo(self, repository_id: str) -> int:
        """重索引 stale 失效（RESEARCH-03）：repository 关联 valid PartialPlan→失效 + task→stale。

        找该 repository 的 RepoResearchTask → 其 valid=True 的 PartialPlan
        ``update(valid=False, invalidated_reason="repo_reindexed")``，对应 task
        ``update(status=stale)``；返回失效 PartialPlan 计数。可重入幂等（已 invalid/stale 不二次改）。
        """
        return await self._invalidate_for_repo_sync(repository_id)

    @sync_to_async
    def _invalidate_for_repo_sync(self, repository_id: str) -> int:
        task_ids = list(
            RepoResearchTask.objects.filter(repository_id=repository_id).values_list(
                "id", flat=True
            )
        )
        if not task_ids:
            return 0
        invalidated = PartialPlan.objects.filter(research_task_id__in=task_ids, valid=True).update(
            valid=False, invalidated_reason="repo_reindexed"
        )
        if invalidated:
            # 仅把有 valid partial 被失效的 task 置 stale（已 stale 重复 update 幂等无害）
            stale_task_ids = list(
                PartialPlan.objects.filter(research_task_id__in=task_ids, valid=False).values_list(
                    "research_task_id", flat=True
                )
            )
            RepoResearchTask.objects.filter(id__in=stale_task_ids).update(
                status=RepoResearchTaskStatus.STALE, updated_at=timezone.now()
            )
        return invalidated
