"""ResearchService —— RepoResearchTask / PartialPlan 的唯一写入入口（Phase 39-02，INV-6）。

承载 v0.7 编排「map 段」子任务级状态机与可靠恢复规则（DOMAIN §6/§14），对齐
``PlanSessionService`` / ``TechnicalPlanService`` 单一写入范式：

- ``create_tasks_for_session``：为需深入仓建 ``RepoResearchTask``（幂等，resume 安全）。
- ``mark_running`` / ``mark_done`` / ``mark_failed``：子任务级状态推进。
- ``record_partial``：写结构化 §7 ``PartialPlan``（content + content_hash）并置 done。
- ``retry_task``（RESEARCH-02）：单仓重试隔离——仅复位该 failed task + attempt+1，
  **绝不触碰其他 task / session.status**。
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
    def _create_tasks_sync(
        self, session: Any, deep_repos: list[dict]
    ) -> list[RepoResearchTask]:
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
        """单仓重试隔离（RESEARCH-02）：仅 failed task → pending + attempt+1。

        以 ``filter(id, status=failed).update(status=pending, attempt=F+1)`` 条件更新，
        影响行数 != 1 → ``raise ValueError``（非 failed 不可重试，镜像 PlanSessionService
        条件更新 + 断言范式）。**绝不触碰其他 task / 不改 session.status**。
        """
        return await self._retry_task_sync(task)

    @sync_to_async
    def _retry_task_sync(self, task: RepoResearchTask) -> RepoResearchTask:
        updated = RepoResearchTask.objects.filter(
            id=task.id, status=RepoResearchTaskStatus.FAILED
        ).update(
            status=RepoResearchTaskStatus.PENDING,
            attempt=F("attempt") + 1,
            updated_at=timezone.now(),
        )
        if updated != 1:
            raise ValueError(
                f"RepoResearchTask {task.id} 非 failed 态不可重试（当前 status={task.status}）"
            )
        task.refresh_from_db()
        return task

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
        invalidated = PartialPlan.objects.filter(
            research_task_id__in=task_ids, valid=True
        ).update(valid=False, invalidated_reason="repo_reindexed")
        if invalidated:
            # 仅把有 valid partial 被失效的 task 置 stale（已 stale 重复 update 幂等无害）
            stale_task_ids = list(
                PartialPlan.objects.filter(
                    research_task_id__in=task_ids, valid=False
                ).values_list("research_task_id", flat=True)
            )
            RepoResearchTask.objects.filter(id__in=stale_task_ids).update(
                status=RepoResearchTaskStatus.STALE, updated_at=timezone.now()
            )
        return invalidated
