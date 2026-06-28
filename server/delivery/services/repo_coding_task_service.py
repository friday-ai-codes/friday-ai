"""RepoCodingTaskService —— RepoCodingTask 的唯一写入入口（Phase 44-03，INV-6）。

承载 v0.8 多仓 wave 编码「操作态脊柱」的子任务级状态机与拓扑调度落库（DOMAIN §6/§14），
对齐 ``ResearchService`` 单一写入范式：所有 ``RepoCodingTask`` 建表 / 状态推进 / wave 写入
**只经本 service**，模型层零业务方法，旁路写由 INV-6 grep 守护断言。

- ``create_tasks_for_plan``：消费 44-02 ``build_repo_waves`` / ``build_repo_dep_edges`` 的
  分层结果，为每仓建 ``RepoCodingTask``（幂等 ``get_or_create``，resume / 重入安全），
  写入 ``wave`` 并在**同步块内**用 ``depends_on.set(...)`` 连仓级 DAG 边。
- ``mark_running`` / ``mark_done`` / ``mark_failed`` / ``mark_blocked``：子任务级状态推进。
  ``mark_done`` / ``mark_blocked`` 用**条件更新 + 影响行数判定**保重复 callback no-op
  （WAVE-02 幂等语义）；``mark_blocked`` 承载下游阻断（``error={"reason":"upstream_failed"}``）。

所有 ORM 写经 ``sync_to_async`` 桥接（禁止 async 上下文裸 ORM）；M2M 写须在同步块内做，
避免 async lazy 访问。本 service **不** dispatch 容器、**不**做拓扑分层（那是 44-02
纯函数职责）——只管状态 / 落库 / 连边。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from delivery.models import RepoCodingTask, RepoCodingTaskStatus

logger = structlog.get_logger(__name__)

__all__ = ["RepoCodingTaskService"]


class RepoCodingTaskService:
    """RepoCodingTask 状态与落库唯一入口（INV-6 精神）。"""

    async def create_tasks_for_plan(
        self,
        artifact_version: Any,
        repo_waves: dict[str, int],
        repo_dep_edges: dict[str, list[str]],
    ) -> dict[str, RepoCodingTask]:
        """为每仓建 RepoCodingTask（status=pending, attempt=0），幂等并连 depends_on 边。

        消费 44-02 拓扑分层结果：``repo_waves`` 为 ``{repository_id: wave}``，
        ``repo_dep_edges`` 为 ``{repository_id: [dep_repository_id, ...]}``（仓级 DAG 边）。
        以 ``get_or_create(plan_version, repository_id)`` 保证幂等（resume / 重入不重建），
        已存在则按需回填 ``wave``；depends_on M2M 边在**同步块内** ``set(...)``（避免 async
        lazy 访问）。返回 ``{repository_id: task}`` 便于调用方按仓索引。
        """
        return await self._create_tasks_sync(artifact_version, repo_waves, repo_dep_edges)

    @sync_to_async
    def _create_tasks_sync(
        self,
        artifact_version: Any,
        repo_waves: dict[str, int],
        repo_dep_edges: dict[str, list[str]],
    ) -> dict[str, RepoCodingTask]:
        # D-51-1：SDD 仓（Repository.facets.methodology=="SDD"，Phase 48 检测器大写写入）
        # 首次消费 follow_openspec（v0.8 预留位）。facets 在同步块内按标量 *_id 查（async 安全），
        # 绝不裸 lazy-FK（D-51-6）。lazy import 防 import 环。
        from repositories.models import Repository

        tasks: dict[str, RepoCodingTask] = {}
        for repo_id, wave in repo_waves.items():
            facets = Repository.objects.filter(id=repo_id).values_list("facets", flat=True).first()
            is_sdd = (facets or {}).get("methodology") == "SDD"
            task, created = RepoCodingTask.objects.get_or_create(
                artifact_version=artifact_version,
                repository_id=repo_id,
                defaults={
                    "status": RepoCodingTaskStatus.PENDING,
                    "wave": wave,
                    "attempt": 0,
                    "follow_openspec": is_sdd,
                },
            )
            # 已存在且 wave / follow_openspec 漂移 → 合并到同一 save 回填（幂等：相等则不写）。
            if not created:
                update_fields: list[str] = []
                if task.wave != wave:
                    task.wave = wave
                    update_fields.append("wave")
                if task.follow_openspec != is_sdd:
                    task.follow_openspec = is_sdd
                    update_fields.append("follow_openspec")
                if update_fields:
                    task.save(update_fields=[*update_fields, "updated_at"])
            tasks[repo_id] = task

        # depends_on 仓级 DAG 边：同步块内 set(...)（仅连同 plan_version 下已建 task）。
        for repo_id, dep_repo_ids in repo_dep_edges.items():
            task = tasks.get(repo_id)
            if task is None:
                continue
            dep_tasks = [tasks[d] for d in dep_repo_ids if d in tasks]
            task.depends_on.set(dep_tasks)
        return tasks

    async def mark_running(self, task: RepoCodingTask, subagent_session: Any) -> int:
        """task.status→running，回填 subagent_session 外键（首发 dispatch 后）。

        条件更新仅 pending→running（与 ``mark_done`` / ``mark_blocked`` 同范式）：并发 / 重复
        dispatch 下，仅首个 claim 影响 1 行，其余 no-op（影响 0 行）。返回影响行数，便于调用方
        据此判定是否真正建容器（派发副作用幂等保护，WAVE-02）。
        """
        return await self._mark_running_sync(task, subagent_session)

    @sync_to_async
    def _mark_running_sync(self, task: RepoCodingTask, subagent_session: Any) -> int:
        # 条件更新：仅 pending→running；影响行数 0 → no-op（重复 / 并发 dispatch 天然幂等）。
        return RepoCodingTask.objects.filter(
            id=task.id, status=RepoCodingTaskStatus.PENDING
        ).update(
            status=RepoCodingTaskStatus.RUNNING,
            subagent_session=subagent_session,
            updated_at=timezone.now(),
        )

    async def mark_done(self, task: RepoCodingTask) -> None:
        """task.status→done（条件更新幂等：仅 running→done，重复 callback no-op）。"""
        await self._mark_done_sync(task)

    @sync_to_async
    def _mark_done_sync(self, task: RepoCodingTask) -> int:
        # 条件更新：仅 running→done；影响行数 0 → no-op（已 done / 非 running 不报错）。
        return RepoCodingTask.objects.filter(
            id=task.id, status=RepoCodingTaskStatus.RUNNING
        ).update(status=RepoCodingTaskStatus.DONE, updated_at=timezone.now())

    async def mark_failed(self, task: RepoCodingTask, error: Any) -> None:
        """task.status→failed，error JSON 落库（非 dict 包成 {"message": str}）。"""
        await self._mark_failed_sync(task, error)

    @sync_to_async
    def _mark_failed_sync(self, task: RepoCodingTask, error: Any) -> None:
        task.status = RepoCodingTaskStatus.FAILED
        task.error = error if isinstance(error, dict) else {"message": str(error)}
        task.save(update_fields=["status", "error", "updated_at"])

    async def mark_blocked(self, task: RepoCodingTask, upstream_ids: list[str]) -> None:
        """下游阻断（WAVE-02）：仅 pending→failed + error 标 upstream_failed。

        条件更新仅作用于 ``status=pending`` 的 task（影响行数 0 → no-op）：已运行 / 终态的
        task 不强翻，避免覆盖在途结果。``error={"reason":"upstream_failed","upstream":[...]}``
        承载上游失败导致的不 dispatch 语义。
        """
        await self._mark_blocked_sync(task, upstream_ids)

    @sync_to_async
    def _mark_blocked_sync(self, task: RepoCodingTask, upstream_ids: list[str]) -> int:
        return RepoCodingTask.objects.filter(
            id=task.id, status=RepoCodingTaskStatus.PENDING
        ).update(
            status=RepoCodingTaskStatus.FAILED,
            error={"reason": "upstream_failed", "upstream": upstream_ids},
            updated_at=timezone.now(),
        )

    async def mark_gate_blocked(self, task: RepoCodingTask, reason: str, spec_status: str) -> int:
        """编码前置 gate 拦截唯一写入入口（D-51-3 / INV-6）：仅 pending→failed + 结构化 error。

        条件更新仅作用于 ``status=pending`` 的 task（影响行数 0 → no-op）：已运行 / 终态的
        task 不强翻，避免覆盖在途结果；重复拦截同一已 blocked task 亦 no-op（幂等）。
        ``error={"reason":<reason>, "spec_status":<status|missing>}`` 如实标注阻断原因
        （``reason`` 形如 "spec_not_approved" / gate 异常路径 "gate_error"，由调用方 51-02 传入），
        对齐既有 ``mark_blocked`` 条件更新范式。返回影响行数。
        """
        return await self._mark_gate_blocked_sync(task, reason, spec_status)

    @sync_to_async
    def _mark_gate_blocked_sync(self, task: RepoCodingTask, reason: str, spec_status: str) -> int:
        return RepoCodingTask.objects.filter(
            id=task.id, status=RepoCodingTaskStatus.PENDING
        ).update(
            status=RepoCodingTaskStatus.FAILED,
            error={"reason": reason, "spec_status": spec_status},
            updated_at=timezone.now(),
        )

    async def record_produced_artifacts(self, task: RepoCodingTask, artifacts: dict) -> None:
        """produced_artifacts 写库唯一入口（ARTIFACT-01，INV-6，幂等覆盖写）。

        提取发生在 ``mark_done`` **之后**（task 已 done），故**不加** status guard——
        用无条件 ``filter(id=...).update()`` 覆盖写：重复写同产物等价 no-op（幂等），写库与
        状态解耦（Pitfall 4：若误加 ``status=RUNNING`` guard，done 仓影响 0 行写不进）。
        用 ``.objects.filter().update()`` 而非 ``task.produced_artifacts=...; task.save()``，
        既被既有 INV-6 grep 守护正向覆盖，又避开字段级旁路写盲区（D-14）。
        """
        await self._record_produced_artifacts_sync(task, artifacts)

    @sync_to_async
    def _record_produced_artifacts_sync(self, task: RepoCodingTask, artifacts: dict) -> int:
        # 无 status guard（提取在 mark_done 后，task 已 done）；覆盖式幂等。
        return RepoCodingTask.objects.filter(id=task.id).update(
            produced_artifacts=artifacts,
            updated_at=timezone.now(),
        )
