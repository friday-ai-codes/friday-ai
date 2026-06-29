"""HumanTaskService —— HumanTask 唯一写入入口 + 统一待办投影（Chassis v2 · P8）。

把"我需要处理什么"收敛为单一查询入口，对齐 ``ClarificationService`` /
``ArtifactService`` 的单一写入范式（INV-6 精神）：

写入（仅经本 service 改 HumanTask）：
- ``open_task``：开一条待办（``dedup_key`` 幂等：命中已有 open 行即返回，不重复开）。
- ``resolve`` / ``skip`` / ``expire`` / ``reassign``：状态机 + 转派语义（超时由 ``aexpire_due``
  批量处理）。

投影 / 物化（不旁路既有事实源）：
- ``list_inbox``：返回统一 ``HumanTaskView`` 列表 = 物化的原生 HumanTask 行（risk_ack /
  takeover 等）∪ 按需投影的既有点状待办：
  - 待答 ``Clarification`` → ``clarification``
  - ``NodeExecution.status=waiting_approval`` → ``approval``
  - ``ReactionExecution.status=failed`` → ``reaction_retry``
  投影是查询时**只读聚合**（不复制权威状态）；已被物化（dedup_key 命中）的来源不再重复投影。

async 纪律：所有 ORM 经 ``sync_to_async`` / async 查询；跨 app 读取（workflows）用
``.values()`` 标量取，规避 async 上下文裸 lazy-FK。观测 best-effort，绝不反噬主流程。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from delivery.models import (
    Clarification,
    HumanTask,
    HumanTaskScope,
    HumanTaskStatus,
    HumanTaskType,
)

logger = structlog.get_logger(__name__)

__all__ = ["HumanTaskService", "HumanTaskView"]


@dataclass
class HumanTaskView:
    """统一待办呈现值对象（物化行 + 投影行共用形态，序列化器/前端只认它）。"""

    id: str
    task_type: str
    scope: str
    subject_id: str
    status: str
    source: str  # "materialized" | "projection"
    source_signal: str = ""
    assignee_user_id: str | None = None
    assignee_role: str | None = None
    artifact_version_id: str | None = None
    due_at: str | None = None
    created_at: str | None = None
    resolved_at: str | None = None
    resolution: dict[str, Any] = field(default_factory=dict)
    # 呈现辅助字段（标题 / 详情 / 类型相关元数据），仅用于 UI，不参与事实
    title: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt is not None else None


class HumanTaskService:
    """HumanTask 落库 / 状态变更唯一入口 + 统一待办投影。"""

    # ── 写入：原生待办开 / 流转（INV-6 单一入口） ────────────────────────────

    async def open_task(
        self,
        *,
        task_type: str,
        scope: str,
        subject_id: str,
        assignee_user_id: str | None = None,
        assignee_role: str | None = None,
        source_signal: str = "",
        artifact_ref: Any = None,
        due_at: Any = None,
        dedup_key: str = "",
        resolution: dict[str, Any] | None = None,
    ) -> HumanTask:
        """开一条人类待办（``dedup_key`` 幂等：命中已有 open 行即返回，不重复开）。"""
        if task_type not in HumanTaskType.values:
            raise ValueError(f"非法 task_type={task_type!r}")
        if scope not in HumanTaskScope.values:
            raise ValueError(f"非法 scope={scope!r}")
        started = time.perf_counter()
        task, created = await self._open_task_sync(
            task_type,
            scope,
            str(subject_id),
            assignee_user_id,
            assignee_role,
            source_signal,
            artifact_ref,
            due_at,
            dedup_key,
            resolution or {},
        )
        self._safe_log(
            "human_task_opened" if created else "human_task_open_deduped",
            category="caller",
            component="human_task_service",
            human_task_id=str(task.id),
            task_type=task_type,
            scope=scope,
            created=created,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return task

    @sync_to_async
    def _open_task_sync(
        self,
        task_type: str,
        scope: str,
        subject_id: str,
        assignee_user_id: str | None,
        assignee_role: str | None,
        source_signal: str,
        artifact_ref: Any,
        due_at: Any,
        dedup_key: str,
        resolution: dict[str, Any],
    ) -> tuple[HumanTask, bool]:
        if dedup_key:
            existing = HumanTask.objects.filter(
                dedup_key=dedup_key, status=HumanTaskStatus.OPEN
            ).first()
            if existing is not None:
                return existing, False
        task = HumanTask.objects.create(
            task_type=task_type,
            scope=scope,
            subject_id=subject_id,
            assignee_user_id=assignee_user_id,
            assignee_role=assignee_role,
            source_signal=source_signal or "",
            artifact_ref=artifact_ref,
            due_at=due_at,
            dedup_key=dedup_key or "",
            resolution=resolution,
        )
        return task, True

    async def resolve(
        self, task_or_id: Any, resolution: dict[str, Any] | None = None
    ) -> HumanTask | None:
        """处理完成：status=done + resolved_at + 写 resolution（幂等：仅 open 行可处理）。"""
        return await self._transition(
            task_or_id, HumanTaskStatus.DONE, resolution=resolution, event="human_task_resolved"
        )

    async def skip(
        self, task_or_id: Any, *, reason: str = ""
    ) -> HumanTask | None:
        """跳过：status=skipped（reason 写入 resolution.skip_reason）。"""
        return await self._transition(
            task_or_id,
            HumanTaskStatus.SKIPPED,
            resolution={"skip_reason": reason} if reason else None,
            event="human_task_skipped",
        )

    async def expire(self, task_or_id: Any) -> HumanTask | None:
        """超时：status=expired。"""
        return await self._transition(
            task_or_id, HumanTaskStatus.EXPIRED, event="human_task_expired"
        )

    async def _transition(
        self,
        task_or_id: Any,
        to_status: str,
        *,
        resolution: dict[str, Any] | None = None,
        event: str = "human_task_transition",
    ) -> HumanTask | None:
        task_id = getattr(task_or_id, "id", task_or_id)
        updated = await self._transition_sync(task_id, to_status, resolution)
        self._safe_log(
            event,
            category="caller",
            component="human_task_service",
            human_task_id=str(task_id),
            to_status=to_status,
            applied=updated,
        )
        return await HumanTask.objects.filter(id=task_id).afirst()

    @sync_to_async
    def _transition_sync(
        self, task_id: Any, to_status: str, resolution: dict[str, Any] | None
    ) -> bool:
        # 幂等条件更新：仅 open 行可流转；并发竞态下重复操作 no-op。
        fields: dict[str, Any] = {
            "status": to_status,
            "resolved_at": timezone.now(),
        }
        if resolution is not None:
            fields["resolution"] = resolution
        updated = HumanTask.objects.filter(
            id=task_id, status=HumanTaskStatus.OPEN
        ).update(**fields)
        return updated == 1

    async def reassign(
        self,
        task_or_id: Any,
        *,
        assignee_user_id: str | None = None,
        assignee_role: str | None = None,
    ) -> HumanTask | None:
        """转派：改 assignee_user_id / assignee_role（仅 open 行）。"""
        task_id = getattr(task_or_id, "id", task_or_id)
        await self._reassign_sync(task_id, assignee_user_id, assignee_role)
        self._safe_log(
            "human_task_reassigned",
            category="caller",
            component="human_task_service",
            human_task_id=str(task_id),
        )
        return await HumanTask.objects.filter(id=task_id).afirst()

    @sync_to_async
    def _reassign_sync(
        self, task_id: Any, assignee_user_id: str | None, assignee_role: str | None
    ) -> bool:
        updated = HumanTask.objects.filter(
            id=task_id, status=HumanTaskStatus.OPEN
        ).update(
            assignee_user_id=assignee_user_id,
            assignee_role=assignee_role,
        )
        return updated == 1

    async def aexpire_due(self, *, now: Any = None) -> int:
        """批量把过期（due_at < now）的 open 待办置 expired（超时兜底语义）。返回受影响行数。"""
        return await self._expire_due_sync(now or timezone.now())

    @sync_to_async
    def _expire_due_sync(self, now: Any) -> int:
        return HumanTask.objects.filter(
            status=HumanTaskStatus.OPEN, due_at__isnull=False, due_at__lt=now
        ).update(status=HumanTaskStatus.EXPIRED, resolved_at=now)

    # ── 查询：统一待办收件箱（物化行 ∪ 投影行） ──────────────────────────────

    async def list_inbox(
        self,
        *,
        assignee_user_id: str | None = None,
        include_projections: bool = True,
        project_id: str | None = None,
    ) -> list[HumanTaskView]:
        """返回统一待办列表（"我需要处理什么"）。

        - ``assignee_user_id``：仅过滤**物化** HumanTask（投影类待办无 assignee，恒纳入，
          因为审批 / 失败反应 / 澄清通常面向当值处理者）；传 None 返回全部 open 物化行。
        - ``include_projections``：是否叠加投影（澄清 / 审批 / 失败反应）。
        - ``project_id``：限定某项目维度的待办。当前 ``HumanTask`` 与各投影源（Clarification /
          NodeExecution / ReactionExecution）均为工作区级、**不携带项目归属**，无法可靠归属到
          具体项目；为避免把**全局待办**误塞进项目作战室（修 #10：空项目不该出现别处的待办），
          传 ``project_id`` 时只返回**能确证属于该项目**的待办——当前无此链路即返回空列表。
          待 AI 产物（方案/澄清/工作项）绑定项目落地后，再在此按项目归属补充投影来源。
        """
        # 项目维度：在建立"待办↔项目"归属链路前，按 fail-closed 返回空，杜绝全局待办泄漏到项目。
        if project_id is not None:
            return []

        views: list[HumanTaskView] = []
        materialized_keys: set[str] = set()
        for view, dedup_key in await self._materialized_views(assignee_user_id):
            views.append(view)
            if dedup_key:
                materialized_keys.add(dedup_key)

        if include_projections:
            views.extend(await self._project_clarifications(materialized_keys))
            views.extend(await self._project_approvals(materialized_keys))
            views.extend(await self._project_failed_reactions(materialized_keys))

        # 统一按 created_at 倒序（None 垫底）
        views.sort(key=lambda v: v.created_at or "", reverse=True)
        return views

    @sync_to_async
    def _materialized_views(
        self, assignee_user_id: str | None
    ) -> list[tuple[HumanTaskView, str]]:
        qs = HumanTask.objects.filter(status=HumanTaskStatus.OPEN)
        if assignee_user_id is not None:
            qs = qs.filter(assignee_user_id=assignee_user_id)
        out: list[tuple[HumanTaskView, str]] = []
        for t in qs.order_by("-created_at"):
            out.append(
                (
                    HumanTaskView(
                        id=str(t.id),
                        task_type=t.task_type,
                        scope=t.scope,
                        subject_id=t.subject_id,
                        status=t.status,
                        source="materialized",
                        source_signal=t.source_signal,
                        assignee_user_id=t.assignee_user_id,
                        assignee_role=t.assignee_role,
                        artifact_version_id=(
                            str(t.artifact_ref_id) if t.artifact_ref_id else None
                        ),
                        due_at=_iso(t.due_at),
                        created_at=_iso(t.created_at),
                        resolved_at=_iso(t.resolved_at),
                        resolution=t.resolution or {},
                    ),
                    t.dedup_key,
                )
            )
        return out

    @sync_to_async
    def _project_clarifications(self, skip_keys: set[str]) -> list[HumanTaskView]:
        """投影待答澄清（存在 answered_at IS NULL 子题，或无子题未答容器）为 clarification 待办。

        以澄清轮次容器为待办单元；标题取首个未答子题文案，detail 携 session / 轮次 / 待答数。
        """
        views: list[HumanTaskView] = []
        # 结构化轮：含未答子题的容器
        container_ids = set(
            Clarification.objects.filter(
                questions__answered_at__isnull=True
            ).values_list("id", flat=True)
        )
        # 防御性：无子题且未答的旧容器（ahas_pending 兜底分支）
        childless = set(
            Clarification.objects.filter(
                answered_at__isnull=True, questions__isnull=True
            ).values_list("id", flat=True)
        )
        for clar in Clarification.objects.filter(
            id__in=container_ids | childless
        ).order_by("-created_at"):
            dedup = f"clarification:{clar.id}"
            if dedup in skip_keys:
                continue
            pending_questions = list(
                clar.questions.filter(answered_at__isnull=True)
                .order_by("order")
                .values("id", "question", "qtype", "options", "recommended")
            )
            title = (
                pending_questions[0]["question"]
                if pending_questions
                else (clar.question or "待答澄清")
            )
            views.append(
                HumanTaskView(
                    id=dedup,
                    task_type=HumanTaskType.CLARIFICATION,
                    scope=HumanTaskScope.PROCESS_SESSION,
                    subject_id=str(clar.session_id),
                    status=HumanTaskStatus.OPEN,
                    source="projection",
                    source_signal="clarification.asked",
                    created_at=_iso(clar.created_at),
                    title=title,
                    detail={
                        "clarification_id": str(clar.id),
                        "session_id": str(clar.session_id),
                        "round_no": clar.round_no,
                        "pending_count": len(pending_questions),
                        "questions": [
                            {**q, "id": str(q["id"])} for q in pending_questions
                        ],
                    },
                )
            )
        return views

    @sync_to_async
    def _project_approvals(self, skip_keys: set[str]) -> list[HumanTaskView]:
        """投影 NodeExecution.status=waiting_approval 为 approval 待办（只读跨 app 读取）。"""
        from workflows.models import NodeExecution, NodeExecutionStatus

        views: list[HumanTaskView] = []
        rows = NodeExecution.objects.filter(
            status=NodeExecutionStatus.WAITING_APPROVAL
        ).values(
            "id",
            "created_at",
            "node__name",
            "workflow_execution_id",
            "workflow_execution__workflow__name",
        )
        for r in rows:
            dedup = f"approval:{r['id']}"
            if dedup in skip_keys:
                continue
            views.append(
                HumanTaskView(
                    id=dedup,
                    task_type=HumanTaskType.APPROVAL,
                    scope=HumanTaskScope.WORKFLOW_EXECUTION,
                    subject_id=str(r["workflow_execution_id"]),
                    status=HumanTaskStatus.OPEN,
                    source="projection",
                    source_signal="approval.requested",
                    created_at=_iso(r["created_at"]),
                    title=r.get("node__name") or "待审批节点",
                    detail={
                        "node_execution_id": str(r["id"]),
                        "workflow_execution_id": str(r["workflow_execution_id"]),
                        "workflow_name": r.get("workflow_execution__workflow__name") or "",
                    },
                )
            )
        return views

    @sync_to_async
    def _project_failed_reactions(self, skip_keys: set[str]) -> list[HumanTaskView]:
        """投影 ReactionExecution.status=failed 为 reaction_retry 待办（只读跨 app 读取）。"""
        from workflows.models import ReactionExecution, ReactionExecutionStatus

        views: list[HumanTaskView] = []
        rows = ReactionExecution.objects.filter(
            status=ReactionExecutionStatus.FAILED
        ).values(
            "id",
            "triggered_at",
            "triggered_signal",
            "last_error",
            "attempts",
            "workflow_execution_id",
            "reaction__target_type",
        )
        for r in rows:
            dedup = f"reaction_retry:{r['id']}"
            if dedup in skip_keys:
                continue
            views.append(
                HumanTaskView(
                    id=dedup,
                    task_type=HumanTaskType.REACTION_RETRY,
                    scope=HumanTaskScope.WORKFLOW_EXECUTION,
                    subject_id=str(r["workflow_execution_id"]),
                    status=HumanTaskStatus.OPEN,
                    source="projection",
                    source_signal=r.get("triggered_signal") or "node.failed",
                    created_at=_iso(r["triggered_at"]),
                    title=(r.get("reaction__target_type") or "失败反应") + " 投递失败",
                    detail={
                        "reaction_execution_id": str(r["id"]),
                        "workflow_execution_id": str(r["workflow_execution_id"]),
                        "target_type": r.get("reaction__target_type") or "",
                        "attempts": r.get("attempts") or 0,
                        "last_error": (r.get("last_error") or "")[:500],
                    },
                )
            )
        return views

    @staticmethod
    def _safe_log(event: str, **fields: Any) -> None:
        """best-effort 结构化生命周期埋点（绝不反噬业务，AGENTS.md 观测约束）。"""
        try:
            logger.info(event, **fields)
        except Exception:  # noqa: BLE001 — 观测失败吞掉，绝不阻断主流程
            pass
