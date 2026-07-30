"""BlueprintLifecycleService —— 蓝图 11 态状态变更唯一写入入口（Phase 111，INV-6）。

镜像 ``convergence_session_service`` 的单点收口范式（转移表守卫 + CAS 原子更新 +
best-effort 事件）：

- **字段级分工（INV-6，RESEARCH P2）**：本 service 是 ``Artifact.blueprint_status``
  字段与 ``BlueprintThread`` / ``BlueprintThreadMessage`` / ``BlueprintReviewer``
  三表的唯一生产 writer；``ArtifactService`` 仍是 Artifact **行创建/版本/status**
  的唯一 writer。旁路写由 ``test_blueprint_inv6_guard`` 源码扫描锁死。
- **转移表（DESIGN §4.2 全部合法边，"" 空串 = v0/未进入状态机，[*] 入口）**：

  ====================  ==========================================================
  from                  to
  ====================  ==========================================================
  ""                    researching
  researching           drafting | needs_clarification | failed | superseded
  drafting              needs_clarification | ai_reviewing | failed | superseded
  ai_reviewing          needs_clarification | drafting | pending_review
  needs_clarification   researching | drafting | ai_reviewing
  pending_review        drafting | confirmed | superseded
  confirmed             implementing | drafting | superseded
  implementing          implemented | drafting
  implemented           archived
  failed                researching（人工重试，LIFE-03）
  archived              （终态，无出边）
  superseded            （终态，无出边）
  ====================  ==========================================================

- **守卫**：``pending_review → confirmed`` 要求无 open+blocking 线程（LIFE-02）——
  守卫查询、CAS 更新与评审人 upsert 在同一 ``transaction.atomic()`` 内，杜绝
  check-then-act 窗口与「状态已变但名单缺人」的半成功（MN-01/MN-02）；
  进入 ``needs_clarification`` 时 ``return_status`` 必须 ∈ {researching, drafting,
  ai_reviewing}（缺省取 from_status；持久承载走 BlueprintThread.return_stage 由调用
  方写，本 service 只校验与透传进事件 payload——RESEARCH A4，不给 Artifact 加列）。
- **事件 best-effort（RESEARCH P3）**：``ConvergenceSessionEvent.session`` 是非空
  FK——``session`` 参数可空，无 session 时只打 structlog（warning 级，让「零 DB 留痕
  的转移」可被发现）不落事件行；事件持久化整体 try/except 吞掉，观测绝不反噬业务。
  绝不给 event 模型加字段。
- **P10 备注**：「一项目一份活跃蓝图」的唯一性守卫由 Phase 112 的创建入口负责，
  本 service 不做（Artifact 无 project FK，项目归属只在 content.meta.project_id）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from delivery.models import (
    Artifact,
    BlueprintReviewer,
    BlueprintStatus,
    BlueprintThread,
    BlueprintThreadMessage,
    ThreadAuthorType,
    ThreadKind,
    ThreadSeverity,
    ThreadStatus,
)
from delivery.services.event_taxonomy import EVENT_BLUEPRINT_STATUS_TRANSITIONED

logger = structlog.get_logger(__name__)

__all__ = ["BlueprintLifecycleService", "ConcurrentBlueprintTransitionError"]


class ConcurrentBlueprintTransitionError(RuntimeError):
    """并发/陈旧蓝图状态转移被拒（镜像 convergence WR-01）。

    ``transition`` 以「DB 行 ``blueprint_status`` == 预期 from_status」为条件原子
    更新；条件不满足（影响行数 != 1）即说明 DB 行已被并发/陈旧推进改写或行不
    存在——拒绝盲写覆盖，抛本异常。
    """


# needs_clarification 的合法恢复目标（DESIGN §4.1-3「回到原状态」三向恢复）
_CLARIFICATION_RETURN_TARGETS: frozenset[str] = frozenset(
    {
        BlueprintStatus.RESEARCHING,
        BlueprintStatus.DRAFTING,
        BlueprintStatus.AI_REVIEWING,
    }
)

# DESIGN §4.2 状态机全部合法边（"" 空串 = v0/未进入状态机，[*] 入口）
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "": {BlueprintStatus.RESEARCHING},
    BlueprintStatus.RESEARCHING: {
        BlueprintStatus.DRAFTING,
        BlueprintStatus.NEEDS_CLARIFICATION,
        BlueprintStatus.FAILED,
        BlueprintStatus.SUPERSEDED,
    },
    BlueprintStatus.DRAFTING: {
        BlueprintStatus.NEEDS_CLARIFICATION,
        BlueprintStatus.AI_REVIEWING,
        BlueprintStatus.FAILED,
        BlueprintStatus.SUPERSEDED,
    },
    BlueprintStatus.AI_REVIEWING: {
        BlueprintStatus.NEEDS_CLARIFICATION,
        BlueprintStatus.DRAFTING,
        BlueprintStatus.PENDING_REVIEW,
    },
    BlueprintStatus.NEEDS_CLARIFICATION: {
        BlueprintStatus.RESEARCHING,
        BlueprintStatus.DRAFTING,
        BlueprintStatus.AI_REVIEWING,
    },
    BlueprintStatus.PENDING_REVIEW: {
        BlueprintStatus.DRAFTING,
        BlueprintStatus.CONFIRMED,
        BlueprintStatus.SUPERSEDED,
    },
    BlueprintStatus.CONFIRMED: {
        BlueprintStatus.IMPLEMENTING,
        BlueprintStatus.DRAFTING,
        BlueprintStatus.SUPERSEDED,
    },
    BlueprintStatus.IMPLEMENTING: {
        BlueprintStatus.IMPLEMENTED,
        BlueprintStatus.DRAFTING,
    },
    BlueprintStatus.IMPLEMENTED: {BlueprintStatus.ARCHIVED},
    # failed → researching 人工重试（LIFE-03）
    BlueprintStatus.FAILED: {BlueprintStatus.RESEARCHING},
    # 显式终态：无出边（LIFE-03）
    BlueprintStatus.ARCHIVED: set(),
    BlueprintStatus.SUPERSEDED: set(),
}

# BlueprintThread.return_stage 字段 max_length（超长截断而非抛，避免澄清线程因恢复
# 目标串过长开不出来——规格门是 fail-closed 点，开不出线程等于静默放行）。
_MAX_RETURN_STAGE_CHARS = 16


class BlueprintLifecycleService:
    """蓝图状态变更唯一入口（INV-6 精神）。"""

    async def transition(
        self,
        artifact: Artifact,
        to_status: str,
        *,
        initiated_by_user_id: str,
        acting_user: Any = None,
        session: Any = None,
        return_status: str | None = None,
    ) -> Artifact:
        """**状态唯一变更入口**：查转移表守卫并 CAS 推进 ``blueprint_status``。

        - 非法转移 ``raise ValueError``（状态不变、DB 不写）。
        - ``to_status == needs_clarification``：``return_status`` 缺省取 from_status，
          必须 ∈ {researching, drafting, ai_reviewing}；其它目标态传入 ``return_status``
          一律忽略并清空（记 warning），不进事件 payload。
        - ``to_status == confirmed``：存在 open+blocking 线程即拒绝（LIFE-02）；
          ``acting_user`` 非空时自动 upsert 进 BlueprintReviewer 名单（首插留痕）。
          守卫、CAS、upsert 三步同事务，任一失败整体回滚。
        - 并发冲突 ``raise ConcurrentBlueprintTransitionError``。
        - 每次转移 best-effort 记事件：structlog caller 事件必打；``session`` 非空
          时才落 ConvergenceSessionEvent 行（失败吞掉只 warning）。
        """
        started = time.monotonic()
        from_status = artifact.blueprint_status
        allowed = _ALLOWED_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise ValueError(
                f"非法蓝图状态转移：{from_status or '<未进入状态机>'} → {to_status}；"
                f"合法目标={sorted(allowed)}"
            )

        if to_status == BlueprintStatus.NEEDS_CLARIFICATION:
            if return_status is None:
                return_status = from_status
            if return_status not in _CLARIFICATION_RETURN_TARGETS:
                raise ValueError(
                    f"非法 needs_clarification 恢复目标 return_status={return_status!r}；"
                    f"合法值={sorted(_CLARIFICATION_RETURN_TARGETS)}"
                )
        elif return_status is not None:
            # 其它目标态没有「恢复目标」语义：显式清空，未校验的任意值不得混进事件
            # payload 污染 115 时间线的语义（MN-03）。
            logger.warning(
                "blueprint_return_status_ignored",
                category="caller",
                component="process_runtime",
                artifact_id=str(artifact.id),
                to_status=to_status,
                return_status=return_status,
                initiated_by_user_id=initiated_by_user_id,
            )
            return_status = None

        await self._apply_transition_sync(
            artifact,
            from_status=from_status,
            to_status=to_status,
            acting_user=acting_user,
        )

        await self._record_transition_event(
            artifact,
            from_status=from_status,
            to_status=to_status,
            initiated_by_user_id=initiated_by_user_id,
            return_status=return_status,
            session=session,
            started=started,
        )
        return artifact

    async def add_reviewer(
        self, artifact: Artifact, user: Any, first_action: str
    ) -> BlueprintReviewer:
        """手动增补评审人（LIFE-02 后半「名单可手动增补」）。

        ``aget_or_create`` 同款 upsert：已在名单则原样返回（first_action 不覆盖）。
        """
        reviewer, _created = await BlueprintReviewer.objects.aget_or_create(
            artifact=artifact,
            user=user,
            defaults={"first_action": first_action},
        )
        return reviewer

    @sync_to_async
    def _apply_transition_sync(
        self,
        artifact: Artifact,
        *,
        from_status: str,
        to_status: str,
        acting_user: Any = None,
    ) -> None:
        """守卫查询 + CAS 原子更新 + 评审人 upsert **同一事务**。

        - confirm 守卫（open+blocking 线程）与 CAS 同事务：check-then-act 窗口收敛，
          期间新建的阻塞线程不再被漏挡（MN-01）。
        - CAS：以 ``blueprint_status == from_status`` 为前置条件（防 TOCTOU）。
          ``Artifact.updated_at`` 是 auto_now 字段，``.update()`` 绕过 auto_now——
          必须显式带上。
        - 评审人 upsert 与状态更新同事务：upsert 失败连状态一起回滚，杜绝「DB 已
          confirmed、名单却缺人，调用方还收到异常」的不一致（MN-02）。
          ``get_or_create`` 保证 ``first_action`` 只在首插写入（重复确认不覆盖）。

        成功后（事务提交）同步内存对象字段。
        """
        with transaction.atomic():
            if to_status == BlueprintStatus.CONFIRMED:
                has_open_blocking = BlueprintThread.objects.filter(
                    artifact=artifact,
                    status=ThreadStatus.OPEN,
                    blocking=True,
                ).exists()
                if has_open_blocking:
                    raise ValueError("存在未解决的阻塞澄清线程，蓝图不可确认")

            updated = Artifact.objects.filter(id=artifact.id, blueprint_status=from_status).update(
                blueprint_status=to_status, updated_at=timezone.now()
            )
            if updated != 1:
                raise ConcurrentBlueprintTransitionError(
                    f"并发/陈旧蓝图状态转移被拒：artifact={artifact.id} "
                    f"expected_from={from_status or '<未进入状态机>'} to={to_status}"
                    "（DB 行 blueprint_status 已被并发推进改写或行不存在）"
                )

            # LIFE-02：确认类动作自动入评审人名单。
            if to_status == BlueprintStatus.CONFIRMED and acting_user is not None:
                BlueprintReviewer.objects.get_or_create(
                    artifact=artifact,
                    user=acting_user,
                    defaults={"first_action": "final_approve"},
                )
        artifact.blueprint_status = to_status

    async def _record_transition_event(
        self,
        artifact: Artifact,
        *,
        from_status: str,
        to_status: str,
        initiated_by_user_id: str,
        return_status: str | None,
        session: Any,
        started: float,
    ) -> None:
        """转移事件（best-effort，RESEARCH P3）：structlog caller 事件必打；
        ``session`` 非空才落 ConvergenceSessionEvent 行，失败吞掉绝不阻断转移。"""
        logger.info(
            "blueprint_status_transitioned",
            category="caller",
            component="process_runtime",
            artifact_id=str(artifact.id),
            from_status=from_status,
            to_status=to_status,
            initiated_by_user_id=initiated_by_user_id,
            return_status=return_status,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        if session is None:
            # LIFE-01「可追溯」：无 session 时转移零 DB 留痕，只能翻日志——用 warning
            # 让这种调用（后台重试 / 管理命令）可被发现并在 112+ 编排层补上 session。
            logger.warning(
                "blueprint_transition_without_session",
                category="caller",
                component="process_runtime",
                artifact_id=str(artifact.id),
                from_status=from_status,
                to_status=to_status,
                initiated_by_user_id=initiated_by_user_id,
            )
            return
        from delivery.services.convergence_session_service import ConvergenceSessionService

        try:
            await ConvergenceSessionService().aemit_event(
                EVENT_BLUEPRINT_STATUS_TRANSITIONED,
                session,
                {
                    "artifact_id": str(artifact.id),
                    "from_status": from_status,
                    "to_status": to_status,
                    "initiated_by_user_id": initiated_by_user_id,
                    "return_status": return_status,
                },
            )
        except Exception as exc:  # noqa: BLE001 — best-effort：事件持久化失败绝不阻断转移
            logger.warning(
                "blueprint_transition_event_persist_failed",
                artifact_id=str(artifact.id),
                to_status=to_status,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # 线程写入（Phase 112-02 追加）：BlueprintThread / Message 的唯一 writer。
    # 规格门（ai_clarification）与确认门（repo_confirmation，112-05）共用同一套 API；
    # adapter 侧一律零 ORM 写（INV-6），只经下列四个方法开/答/解线程。
    # 观测规范：日志只记 thread_id / kind / 计数等标量与关联键，**澄清问题与回答正文
    # 绝不进日志**（T-112-08）。
    # ------------------------------------------------------------------

    async def ahas_open_blocking_threads(
        self, artifact: Artifact, *, kind: str | None = None
    ) -> bool:
        """是否存在未解决的阻塞线程（复用 confirm 守卫同款查询形）。

        ``kind`` 非空时再按线程种类过滤——规格门只关心 ``ai_clarification``、确认门
        只关心 ``repo_confirmation``，互不误挡；不传则等价于 LIFE-02 守卫的全量口径
        （112-05 的 ``blueprint_resume`` 判 pause 用）。
        """
        queryset = BlueprintThread.objects.filter(
            artifact=artifact,
            status=ThreadStatus.OPEN,
            blocking=True,
        )
        if kind:
            queryset = queryset.filter(kind=kind)
        return await queryset.aexists()

    async def aunresolved_blocker_count(self, artifact: Artifact) -> int:
        """未决 BLOCKER finding 计数（``kind=ai_review_finding`` 且 ``severity=blocker``
        且 ``status ∈ {open, answered}`` 的线程数）。

        **仅供报告**（114-03 的 ``unresolved`` 快照、114-05 的人审呈现），**绝不用于
        confirm 守卫判定**——守卫必须在 ``_apply_transition_sync`` 的 ``transaction.atomic()``
        内完成（见 :meth:`_has_confirm_blockers_sync`），事务外查一次就是 TOCTOU。
        """
        return await BlueprintThread.objects.filter(
            artifact=artifact,
            kind=ThreadKind.AI_REVIEW_FINDING,
            severity=ThreadSeverity.BLOCKER,
            status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED],
        ).acount()

    async def open_thread(
        self,
        artifact: Artifact,
        *,
        kind: str,
        blocking: bool,
        question: str,
        options: list | None = None,
        initiated_by_user_id: str = "system",
        created_on_version: Any = None,
        anchor: dict | None = None,
        return_stage: str = "",
        severity: str = "",
    ) -> BlueprintThread:
        """开一条线程并同事务写入首条 AI 提问消息。

        - ``kind`` 必须 ∈ ``ThreadKind.values``，否则 ``raise ValueError``（DB 不写）。
        - 线程行与首条消息在同一 ``transaction.atomic``：杜绝「有线程无问题」的半截
          线程——那会让 HITL 侧看到一条空白阻塞线程且永远答不了。
        - ``return_stage`` 超 ``max_length=16`` 截断并记 warning（开不出线程 = 规格门
          静默放行，宁可截断也不抛）。
        - ``severity`` ∈ ``ThreadSeverity.values``（``blocker`` / ``warning`` / ``info``）
          或空串；非法值 ``raise ValueError``（与 ``kind`` 同款，DB 不写）。
          ``BlueprintThread.severity`` 字段自 111-02 起已存在，本形参**零 migration**；
          默认空串使 112/113 现存全部调用逐字等价。
        - ⭐ **不变式**：``kind == ThreadKind.AI_REVIEW_FINDING`` 时强制
          ``blocking == (severity == ThreadSeverity.BLOCKER)``——错配即 ``raise ValueError``。
          理由：``pending_review → confirmed`` 的事务内守卫（``_apply_transition_sync``）
          只认 ``open + blocking``；若 ``severity=blocker`` 却 ``blocking=False``，带未决
          BLOCKER 的蓝图会被人审放行；若 ``severity=warning`` 却 ``blocking=True``，警告
          会把蓝图钉死。两者必须同源。
        """
        if kind not in ThreadKind.values:
            raise ValueError(f"非法线程 kind={kind!r}；合法值={sorted(ThreadKind.values)}")

        sev = str(severity or "")
        if sev and sev not in ThreadSeverity.values:
            raise ValueError(
                f"非法线程 severity={severity!r}；合法值={sorted(ThreadSeverity.values)} 或空串"
            )
        if kind == ThreadKind.AI_REVIEW_FINDING and bool(blocking) != (
            sev == ThreadSeverity.BLOCKER
        ):
            raise ValueError(
                "ai_review_finding 线程必须满足 blocking == (severity == 'blocker')："
                f"当前 severity={sev!r} blocking={bool(blocking)}"
            )

        stage = str(return_stage or "")
        if len(stage) > _MAX_RETURN_STAGE_CHARS:
            logger.warning(
                "blueprint_thread_return_stage_truncated",
                category="caller",
                component="blueprint_lifecycle",
                artifact_id=str(artifact.id),
                kind=kind,
                original_length=len(stage),
            )
            stage = stage[:_MAX_RETURN_STAGE_CHARS]

        thread = await self._open_thread_sync(
            artifact,
            kind=kind,
            blocking=bool(blocking),
            question=str(question or ""),
            options=list(options or []),
            initiated_by_user_id=initiated_by_user_id or "system",
            created_on_version=created_on_version,
            anchor=anchor,
            return_stage=stage,
            severity=sev,
        )
        logger.info(
            "blueprint_thread_opened",
            category="caller",
            component="blueprint_lifecycle",
            artifact_id=str(artifact.id),
            kind=kind,
            blocking=bool(blocking),
            severity=sev,
            initiated_by_user_id=initiated_by_user_id or "system",
            thread_id=str(thread.id),
            option_count=len(options or []),
        )
        return thread

    async def record_answer(
        self,
        thread: BlueprintThread,
        *,
        body: str,
        author: Any = None,
        author_type: str = ThreadAuthorType.HUMAN,
        initiated_by_user_id: str = "system",
    ) -> BlueprintThreadMessage:
        """追加一条消息，并把 ``open`` 线程推到 ``answered``（幂等，不回退终态）。

        已是 ``answered`` / ``resolved`` / ``dismissed`` 的线程只追加消息、状态不变——
        重复作答不得把已解决线程拉回待处理，否则规格门会被同一问题反复挡住。
        """
        message = await self._record_answer_sync(
            thread,
            body=str(body or ""),
            author=author,
            author_type=author_type,
        )
        logger.info(
            "blueprint_thread_answered",
            category="caller",
            component="blueprint_lifecycle",
            thread_id=str(thread.id),
            kind=thread.kind,
            author_type=author_type,
            initiated_by_user_id=initiated_by_user_id or "system",
        )
        return message

    async def resolve_thread(
        self,
        thread: BlueprintThread,
        *,
        resolution: str = "",
        initiated_by_user_id: str = "system",
        dismissed: bool = False,
    ) -> BlueprintThread:
        """收尾线程：置 ``resolved``（或 ``dismissed``）；终态重复调用为幂等 no-op。

        ``resolution`` 非空时同事务追加一条 AI 结论消息（线程模型无结论字段，结论正文
        落消息流；结构化留痕由调用方写进蓝图 ``decision_log``）。
        """
        target = ThreadStatus.DISMISSED if dismissed else ThreadStatus.RESOLVED
        changed = await self._resolve_thread_sync(
            thread, target=target, resolution=str(resolution or "")
        )
        logger.info(
            "blueprint_thread_resolved",
            category="caller",
            component="blueprint_lifecycle",
            thread_id=str(thread.id),
            kind=thread.kind,
            to_status=thread.status,
            changed=changed,
            initiated_by_user_id=initiated_by_user_id or "system",
        )
        return thread

    @sync_to_async
    def _open_thread_sync(
        self,
        artifact: Artifact,
        *,
        kind: str,
        blocking: bool,
        question: str,
        options: list,
        initiated_by_user_id: str,
        created_on_version: Any,
        anchor: dict | None,
        return_stage: str,
        severity: str,
    ) -> BlueprintThread:
        """线程行 + 首条 AI 消息同事务落库（半截线程不可接受）。"""
        with transaction.atomic():
            thread = BlueprintThread.objects.create(
                artifact=artifact,
                created_on_version=created_on_version,
                anchor=anchor,
                kind=kind,
                severity=severity,
                blocking=blocking,
                options=options,
                status=ThreadStatus.OPEN,
                return_stage=return_stage,
                initiated_by_user_id=initiated_by_user_id,
            )
            BlueprintThreadMessage.objects.create(
                thread=thread,
                author_type=ThreadAuthorType.AI,
                body=question,
            )
            return thread

    @sync_to_async
    def _record_answer_sync(
        self,
        thread: BlueprintThread,
        *,
        body: str,
        author: Any,
        author_type: str,
    ) -> BlueprintThreadMessage:
        """消息追加 + open→answered 推进同事务（状态推进以 DB 现值为条件，防回退）。"""
        with transaction.atomic():
            message = BlueprintThreadMessage.objects.create(
                thread=thread,
                author_type=author_type,
                author=author,
                body=body,
            )
            updated = BlueprintThread.objects.filter(id=thread.id, status=ThreadStatus.OPEN).update(
                status=ThreadStatus.ANSWERED, updated_at=timezone.now()
            )
            if updated == 1:
                thread.status = ThreadStatus.ANSWERED
            return message

    @sync_to_async
    def _resolve_thread_sync(
        self, thread: BlueprintThread, *, target: str, resolution: str
    ) -> bool:
        """终态化线程（幂等）：仅 open/answered 可被推进，返回是否真的改了状态。"""
        with transaction.atomic():
            updated = BlueprintThread.objects.filter(
                id=thread.id, status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED]
            ).update(status=target, updated_at=timezone.now())
            if updated != 1:
                # 已是终态：保留首次结论，不覆盖、不追加噪声消息。
                fresh = BlueprintThread.objects.filter(id=thread.id).values("status").first()
                if fresh:
                    thread.status = fresh["status"]
                return False
            thread.status = target
            if resolution:
                BlueprintThreadMessage.objects.create(
                    thread=thread,
                    author_type=ThreadAuthorType.AI,
                    body=resolution,
                )
            return True

    # ------------------------------------------------------------------
    # 确认门动作（Phase 112-05 追加）：五动作 + indirect 升级深调研的单点收口。
    #
    # 视图层零 ORM 写（INV-6）：REST 只做透传，action 白名单、角色枚举、快照定位、
    # 重调研规则表全部在本层。快照（结构化仓库清单）承载在
    # ``BlueprintThread(kind=repo_confirmation).options``，整段读改写单条线程行。
    #
    # **动作不推进 stage**：advance 由视图层的 ``blueprint_resume.aresume_after_gate_action``
    # 在动作持久化之后触发（confirm 在 alock 之后），本层只落库。
    # ------------------------------------------------------------------

    async def apply_gate_action(
        self,
        artifact: Artifact,
        *,
        thread: BlueprintThread,
        action: str,
        payload: dict | None = None,
        acting_user: Any = None,
        initiated_by_user_id: str = "system",
        session: Any = None,
    ) -> dict:
        """五动作单点收口，返回**形状恒定**的结果 dict。

        Returns:
            ``{"requires_research": bool, "repository_id": str | None, "thread_id": str,
            "ready_to_lock": bool, "blocked_reason": str}``——调用方无需判分支。

        重调研规则表（``requires_research`` 的确定判据，SC-4）：

        ==================== ============================================================
        action               是否重调研
        ==================== ============================================================
        ``add_repo``         **是**（新仓无任何 fitness）→ ``create_tasks_for_session``
        ``remove_repo``      否（只收窄仓库集，既有结论不失效）
        ``reclassify_role``  仅 ``indirect → direct``（需要容器级 fitness）→ ``mark_stale``
        ``edit_responsibility`` 仅 ``payload["rerun"] is True``（职责文本变化是否改变调研
                             范围无法机械判定 → 不猜）→ ``mark_stale``
        ``confirm``          否（走锁定路径）
        ==================== ============================================================

        ``requires_research=True`` 的动作**同时**做两件写入，缺一即断链：① 快照该仓打
        ``pending_research=True``（112-04 的增量 dispatch 从这里读）；② 该仓
        ``RepoResearchTask`` 落到可派发态（``PENDING`` / ``STALE``，均在 112-04 的
        ``_DISPATCHABLE_STATUSES`` 内）。两处写入均经 ``ResearchService`` 公开方法。

        非法 ``action`` / 缺 ``repository_id`` / 非法角色 / 仓不在快照内一律
        ``raise ValueError(<GATE_ERROR_* 码>)``，视图据码分层回 400 / 404。
        """
        started = time.monotonic()
        if action not in GATE_ACTIONS:
            raise ValueError(GATE_ERROR_UNKNOWN_ACTION)
        body = payload if isinstance(payload, dict) else {}
        thread_id = str(getattr(thread, "id", ""))
        decided_by = str(initiated_by_user_id or "system")
        result: dict[str, Any] = {
            "requires_research": False,
            "repository_id": None,
            "thread_id": thread_id,
            "ready_to_lock": False,
            "blocked_reason": "",
        }

        if action == "confirm":
            snapshot = await self._aload_gate_options(thread_id)
            if not [e for e in snapshot if e.get("removed") is not True]:
                raise ValueError(GATE_ERROR_EMPTY_SNAPSHOT)
            if await self.ahas_open_blocking_threads(artifact, kind=ThreadKind.AI_CLARIFICATION):
                # LIFE-02 同款语义：未决阻塞澄清线程在，确认不予受理（视图回 409）。
                result["blocked_reason"] = "pending_clarification"
            else:
                result["ready_to_lock"] = True
                await self._arecord_gate_note(
                    thread, body="用户确认当前仓库集与职责。", author=acting_user
                )
            await self._emit_gate_action(
                session, action=action, repository_id="", thread_id=thread_id
            )
            self._log_gate_action(
                action=action,
                artifact=artifact,
                thread_id=thread_id,
                repository_id="",
                requires_research=False,
                initiated_by_user_id=decided_by,
                started=started,
                blocked_reason=result["blocked_reason"],
            )
            return result

        repository_id = str(body.get("repository_id") or "").strip()
        if not repository_id:
            raise ValueError(GATE_ERROR_MISSING_REPOSITORY)
        result["repository_id"] = repository_id

        role = str(body.get("role") or "").strip().lower()
        if action == "add_repo" and not role:
            role = "direct"
        if action in ("add_repo", "reclassify_role") and role not in GATE_ROLES:
            raise ValueError(GATE_ERROR_INVALID_ROLE)
        confidence = str(body.get("confidence") or "").strip().lower() or "low"

        if action == "add_repo" and not await self._ais_repo_in_blueprint_scope(
            session, thread_id, repository_id
        ):
            # 越界一律回中性 404（与「仓不存在」同码）：URL 里的 artifact 必须约束 body
            # 里的 repository_id，否则任意登录用户可把全库任意仓挂进任意蓝图并起容器。
            raise ValueError(GATE_ERROR_REPOSITORY_NOT_FOUND)

        outcome = await self._apply_gate_snapshot_sync(
            thread_id,
            action=action,
            repository_id=repository_id,
            role=role,
            responsibility=str(body.get("responsibility") or "")[:_MAX_GATE_TEXT_CHARS],
            reason=str(body.get("reason") or "")[:_MAX_GATE_REASON_CHARS],
            confidence=confidence,
            rerun=body.get("rerun") is True,
            decided_by=decided_by,
        )
        if outcome["error"]:
            raise ValueError(outcome["error"])
        requires_research = bool(outcome["requires_research"])
        result["requires_research"] = requires_research

        if requires_research:
            # 视图**不同步等容器**：这里只把 task 置为可派发态，容器由续驱经
            # ``_h_bp_repo_research`` 的增量 dispatch 起（起容器 ≠ 等容器）。
            await self._aensure_research_dispatchable(
                session, repository_id, action=action, confidence=confidence
            )

        await self._arecord_gate_note(
            thread,
            body=_gate_note_text(action, repository_id=repository_id, outcome=outcome),
            author=acting_user,
        )
        await self._emit_gate_action(
            session, action=action, repository_id=repository_id, thread_id=thread_id
        )
        self._log_gate_action(
            action=action,
            artifact=artifact,
            thread_id=thread_id,
            repository_id=repository_id,
            requires_research=requires_research,
            initiated_by_user_id=decided_by,
            started=started,
            blocked_reason="",
        )
        return result

    async def aupgrade_repo_research(
        self,
        artifact: Artifact,
        *,
        repository_id: str,
        acting_user: Any = None,
        initiated_by_user_id: str = "system",
        session: Any = None,
    ) -> dict:
        """第七个动作端点的 service 收口：把 indirect 候选升级为深调研（FLOW-04）。

        快照该仓标 ``pending_research=True`` + ``role_suggestion="direct"`` → 留痕 →
        emit → 调 112-04 的 ``BlueprintResearchAdapter.aupgrade_to_deep``（lazy import，
        避免 delivery → process_runtime 的模块级环）。容器不在本方法内等待，后续增量
        派发由 ``_h_bp_repo_research`` 承担。

        Returns:
            ``{"upgraded": bool, "repository_id": str, "already_running": bool}``——
            ``upgraded is False`` 表示依赖不可用（视图回 503）；``already_running is True``
            表示该仓调研本就在途（``mark_stale`` 按 WR-01 只动已终态 task、dispatch 白名单
            也跳过在途 task），此次调用**没有重开容器**，端点如实告知而不是假装已重开；
            仓不在快照内 / 门未开一律 ``raise ValueError``（视图回 404）。
        """
        started = time.monotonic()
        repository_id = str(repository_id or "").strip()
        if not repository_id:
            raise ValueError(GATE_ERROR_MISSING_REPOSITORY)
        thread = await self.aload_gate_thread(artifact)
        if thread is None:
            raise ValueError(GATE_ERROR_GATE_NOT_OPEN)
        decided_by = str(initiated_by_user_id or "system")

        outcome = await self._apply_gate_snapshot_sync(
            str(thread.id),
            action=GATE_ACTION_UPGRADE_RESEARCH,
            repository_id=repository_id,
            role="direct",
            responsibility="",
            reason="",
            confidence="low",
            rerun=False,
            decided_by=decided_by,
        )
        if outcome["error"]:
            raise ValueError(outcome["error"])

        await self._arecord_gate_note(
            thread,
            body=f"用户将仓库 {repository_id} 升级为深调研。",
            author=acting_user,
        )
        await self._emit_gate_action(
            session,
            action=GATE_ACTION_UPGRADE_RESEARCH,
            repository_id=repository_id,
            thread_id=str(thread.id),
        )

        upgraded = False
        if session is not None:
            from services.process_runtime.blueprint_research_adapter import (
                BlueprintResearchAdapter,
            )

            upgraded = bool(
                await BlueprintResearchAdapter().aupgrade_to_deep(session, repository_id)
            )
        already_running = upgraded and await self._ais_research_in_flight(session, repository_id)
        self._log_gate_action(
            action=GATE_ACTION_UPGRADE_RESEARCH,
            artifact=artifact,
            thread_id=str(thread.id),
            repository_id=repository_id,
            requires_research=True,
            initiated_by_user_id=decided_by,
            started=started,
            blocked_reason="" if upgraded else "upgrade_unavailable",
        )
        return {
            "upgraded": upgraded,
            "repository_id": repository_id,
            "already_running": already_running,
        }

    @staticmethod
    @sync_to_async
    def _ais_research_in_flight(session: Any, repository_id: str) -> bool:
        """该仓调研是否仍在途（``RUNNING``）——在途即本次升级没有也不该重开容器。"""
        from delivery.models import RepoResearchTask, RepoResearchTaskStatus

        try:
            return RepoResearchTask.objects.filter(
                session_id=getattr(session, "id", None),
                repository_id=repository_id,
                status=RepoResearchTaskStatus.RUNNING,
            ).exists()
        except Exception:  # noqa: BLE001 — 非法 uuid 等一律按「不在途」处理
            return False

    async def aload_gate_thread(self, artifact: Artifact) -> BlueprintThread | None:
        """取该蓝图仍在受理中的确认门线程（``open`` / ``answered``），无则 ``None``。"""
        return await (
            BlueprintThread.objects.filter(
                artifact=artifact,
                kind=ThreadKind.REPO_CONFIRMATION,
                status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED],
            )
            .order_by("-created_at")
            .afirst()
        )

    async def _aload_gate_options(self, thread_id: str) -> list[dict]:
        options = await (
            BlueprintThread.objects.filter(id=thread_id).values_list("options", flat=True).afirst()
        )
        if not isinstance(options, list):
            return []
        return [item for item in options if isinstance(item, dict)]

    async def _aensure_research_dispatchable(
        self, session: Any, repository_id: str, *, action: str, confidence: str
    ) -> None:
        """让该仓 ``RepoResearchTask`` 落到可派发态（一律经 ``ResearchService`` 公开方法）。

        无 ``session``（调用方未提供会话上下文）时只保留快照标记：标记持久化在库里，
        下一次续驱仍可闭环，绝不因此抛错让动作失败。
        """
        if session is None:
            logger.warning(
                "blueprint_gate_research_dispatch_skipped_no_session",
                category="caller",
                component="blueprint_lifecycle",
                repository_id=repository_id,
                action=action,
            )
            return
        from delivery.services.research_service import ResearchService

        service = ResearchService()
        task_id = None
        if action != "add_repo":
            task_id = await self._afind_research_task_id(session, repository_id)
        if task_id is None:
            await service.create_tasks_for_session(
                session, [{"repository_id": repository_id, "routed_confidence": confidence}]
            )
        else:
            # STALE 已在 112-04 的 _DISPATCHABLE_STATUSES 内；mark_stale 只动已终态 task。
            await service.mark_stale([task_id])

    async def _ais_repo_in_blueprint_scope(
        self, session: Any, thread_id: str, repository_id: str
    ) -> bool:
        """``add_repo`` 的范围白名单（与 ``blueprint_route._resolve_repository_ids`` 同源）。

        范围来源四条并集：① 路由候选（``stage_state["routing"].candidates``）②
        显式 ``include_repos``（顶层或 ``blueprint`` 段）③ ``work_item.space`` 的仓集合
        ④ 确认门快照里已有的仓。**并集为空 → 拒绝**（fail-closed）：范围解析不出来时
        放行等于没有范围，正是本条要堵的口子。
        """
        try:
            scope = await self._acollect_blueprint_scope_ids(session, thread_id)
        except Exception as exc:  # noqa: BLE001 — 范围读失败按越界处理（fail-closed）
            logger.warning(
                "blueprint_gate_scope_resolve_failed",
                category="caller",
                component="blueprint_lifecycle",
                repository_id=repository_id,
                error=str(exc),
            )
            return False
        return bool(scope) and str(repository_id) in scope

    @staticmethod
    @sync_to_async
    def _acollect_blueprint_scope_ids(session: Any, thread_id: str) -> set[str]:
        ids: set[str] = set()
        state = getattr(session, "stage_state", None)
        if isinstance(state, dict):
            routing = state.get("routing")
            if isinstance(routing, dict):
                for candidate in routing.get("candidates") or []:
                    if isinstance(candidate, dict) and candidate.get("repository_id"):
                        ids.add(str(candidate["repository_id"]))
            includes = list(state.get("include_repos") or [])
            blueprint_state = state.get("blueprint")
            if isinstance(blueprint_state, dict):
                includes += list(blueprint_state.get("include_repos") or [])
            ids.update(str(item) for item in includes if item)

        work_item_id = getattr(session, "work_item_id", None)
        if work_item_id is not None:
            from delivery.models import WorkItem

            work_item = WorkItem.objects.select_related("space").filter(id=work_item_id).first()
            if work_item is not None and work_item.space is not None:
                ids.update(
                    str(rid) for rid in work_item.space.repositories.values_list("id", flat=True)
                )

        options = (
            BlueprintThread.objects.filter(id=thread_id).values_list("options", flat=True).first()
        )
        for item in options or []:
            if isinstance(item, dict) and item.get("repository_id"):
                ids.add(str(item["repository_id"]))
        return ids

    @staticmethod
    @sync_to_async
    def _afind_research_task_id(session: Any, repository_id: str) -> Any:
        from delivery.models import RepoResearchTask

        try:
            return (
                RepoResearchTask.objects.filter(
                    session_id=getattr(session, "id", None), repository_id=repository_id
                )
                .values_list("id", flat=True)
                .first()
            )
        except Exception:  # noqa: BLE001 — 非法 uuid 等一律按「无 task」处理
            return None

    @sync_to_async
    def _apply_gate_snapshot_sync(
        self,
        thread_id: str,
        *,
        action: str,
        repository_id: str,
        role: str,
        responsibility: str,
        reason: str,
        confidence: str,
        rerun: bool,
        decided_by: str,
    ) -> dict:
        """确认门快照的**唯一 mutator**：整段读改写单条线程行（同事务，避免半截状态）。

        重调研规则表在此单点实现（``requires_research`` 的判据），``reclassify_role``
        需要「改判前的角色」才能判定，故必须在同一事务内先读后写。
        """
        with transaction.atomic():
            row = BlueprintThread.objects.select_for_update().filter(id=thread_id).first()
            if row is None:
                return _gate_outcome(GATE_ERROR_GATE_NOT_OPEN)
            raw = row.options if isinstance(row.options, list) else []
            entries = [item for item in raw if isinstance(item, dict)]
            index = next(
                (
                    i
                    for i, item in enumerate(entries)
                    if str(item.get("repository_id") or "") == repository_id
                ),
                None,
            )

            if action == "add_repo":
                repo = _lookup_gate_repository(repository_id)
                if repo is None:
                    return _gate_outcome(GATE_ERROR_REPOSITORY_NOT_FOUND)
                if index is None:
                    entries.append(
                        _new_gate_entry(repository_id, getattr(repo, "name", ""), role, confidence)
                    )
                    index = len(entries) - 1
            elif index is None:
                return _gate_outcome(GATE_ERROR_REPO_NOT_IN_SNAPSHOT)

            entry = entries[index]
            before = _gate_entry_view(entry)
            requires_research = False

            if action == "add_repo":
                entry["role_suggestion"] = role
                entry["removed"] = False
                entry["pending_research"] = True
                entry["confidence"] = entry.get("confidence") or confidence
                requires_research = True
            elif action == "remove_repo":
                entry["removed"] = True
                entry["remove_reason"] = reason
                # 仅收窄仓库集：既有结论不失效，不触发重调研。
                entry["pending_research"] = False
            elif action == "reclassify_role":
                previous = str(entry.get("role_suggestion") or "")
                entry["role_suggestion"] = role
                # 深调研结论是轻量合成的超集：只有 indirect→direct 需要容器级 fitness。
                requires_research = previous == "indirect" and role == "direct"
                if requires_research:
                    entry["pending_research"] = True
            elif action == "edit_responsibility":
                entry["responsibility"] = responsibility
                # 职责文本是否改变调研范围无法机械判定 → 不猜，只认调用方显式 rerun。
                requires_research = bool(rerun)
                if requires_research:
                    entry["pending_research"] = True
            else:  # GATE_ACTION_UPGRADE_RESEARCH
                entry["role_suggestion"] = "direct"
                entry["pending_research"] = True
                requires_research = True

            after = _gate_entry_view(entry)
            actions = entry.get("actions")
            if not isinstance(actions, list):
                actions = []
            actions.append(
                {
                    "action": action,
                    "before": before,
                    "after": after,
                    "decided_at": timezone.now().isoformat(),
                    "decided_by": decided_by,
                }
            )
            entry["actions"] = actions
            BlueprintThread.objects.filter(id=thread_id).update(
                options=entries, updated_at=timezone.now()
            )
            return _gate_outcome(
                "", requires_research=requires_research, before=before, after=after
            )

    async def _arecord_gate_note(
        self, thread: BlueprintThread, *, body: str, author: Any = None
    ) -> BlueprintThreadMessage:
        """确认门留痕消息：**只追加消息、绝不推进线程状态**。

        与 :meth:`record_answer` 的区别是关键：确认门线程必须保持 ``open`` 直到
        ``confirm`` 收尾——一旦被推到 ``answered``，``ahas_open_blocking_threads``
        （只认 ``open``）会判为无门，``open_gate`` 就会再开第二条确认门线程，
        续驱的 pause 判据也会失守。
        """
        return await self._append_thread_message_sync(thread, body=str(body or ""), author=author)

    @sync_to_async
    def _append_thread_message_sync(
        self, thread: BlueprintThread, *, body: str, author: Any
    ) -> BlueprintThreadMessage:
        return BlueprintThreadMessage.objects.create(
            thread=thread,
            author_type=ThreadAuthorType.HUMAN,
            author=author,
            body=body,
        )

    async def _emit_gate_action(
        self, session: Any, *, action: str, repository_id: str, thread_id: str
    ) -> None:
        """确认门动作事件（best-effort；payload 只含 action / id，不含职责正文）。

        走 ``ConvergenceSessionService.aemit_event`` 而不是裸建 ORM 行：裸建要自己拼
        ``work_item=session.work_item_id``，依赖它恰好是软 UUID 字段——改成真 FK 就会
        静默 warning 后丢事件；且给事件统一加字段时只有一处要改。
        """
        if session is None:
            return
        from delivery.services.convergence_session_service import ConvergenceSessionService
        from delivery.services.event_taxonomy import EVENT_BLUEPRINT_CONFIRMATION_ACTION

        try:
            await ConvergenceSessionService().aemit_event(
                EVENT_BLUEPRINT_CONFIRMATION_ACTION,
                session,
                {
                    "action": action,
                    "repository_id": repository_id,
                    "thread_id": thread_id,
                },
            )
        except Exception as exc:  # noqa: BLE001 — 观测绝不反噬确认门动作
            logger.warning(
                "blueprint_gate_action_event_persist_failed",
                category="caller",
                component="blueprint_lifecycle",
                action=action,
                error=str(exc),
            )

    @staticmethod
    def _log_gate_action(
        *,
        action: str,
        artifact: Artifact,
        thread_id: str,
        repository_id: str,
        requires_research: bool,
        initiated_by_user_id: str,
        started: float,
        blocked_reason: str,
    ) -> None:
        logger.info(
            "blueprint_gate_action_applied",
            category="caller",
            component="blueprint_lifecycle",
            artifact_id=str(getattr(artifact, "id", "")),
            thread_id=thread_id,
            action=action,
            repository_id=repository_id,
            requires_research=requires_research,
            blocked_reason=blocked_reason,
            initiated_by_user_id=initiated_by_user_id,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )


# ══════════════════════════════════════════════════════════════════════════
# 确认门动作常量与纯函数（Phase 112-05 追加；纯追加纪律 → 不改既有 __all__ 行）
# ══════════════════════════════════════════════════════════════════════════

# 五动作白名单（视图只透传，白名单归一在 service 层，T-112-23）
GATE_ACTIONS: tuple[str, ...] = (
    "confirm",
    "remove_repo",
    "add_repo",
    "reclassify_role",
    "edit_responsibility",
)
# 第七个动作端点（upgrade-research）走 aupgrade_repo_research，不进五动作白名单
GATE_ACTION_UPGRADE_RESEARCH = "upgrade_research"
GATE_ROLES: tuple[str, ...] = ("direct", "indirect")

# 错误码（视图据码分层回状态码：*_NOT_FOUND / NOT_IN_SNAPSHOT / GATE_NOT_OPEN → 404，其余 400）
GATE_ERROR_UNKNOWN_ACTION = "unknown_action"
GATE_ERROR_MISSING_REPOSITORY = "missing_repository_id"
GATE_ERROR_INVALID_ROLE = "invalid_role"
GATE_ERROR_EMPTY_SNAPSHOT = "empty_snapshot"
GATE_ERROR_REPOSITORY_NOT_FOUND = "repository_not_found"
GATE_ERROR_REPO_NOT_IN_SNAPSHOT = "repository_not_in_snapshot"
GATE_ERROR_GATE_NOT_OPEN = "gate_not_open"

GATE_NOT_FOUND_ERRORS: frozenset[str] = frozenset(
    {
        GATE_ERROR_REPOSITORY_NOT_FOUND,
        GATE_ERROR_REPO_NOT_IN_SNAPSHOT,
        GATE_ERROR_GATE_NOT_OPEN,
    }
)

_MAX_GATE_TEXT_CHARS = 2000
_MAX_GATE_REASON_CHARS = 500
_GATE_ENTRY_VIEW_KEYS = ("role_suggestion", "responsibility", "removed", "pending_research")

__all__ += [
    "GATE_ACTIONS",
    "GATE_ACTION_UPGRADE_RESEARCH",
    "GATE_ROLES",
    "GATE_NOT_FOUND_ERRORS",
    "GATE_ERROR_UNKNOWN_ACTION",
    "GATE_ERROR_MISSING_REPOSITORY",
    "GATE_ERROR_INVALID_ROLE",
    "GATE_ERROR_EMPTY_SNAPSHOT",
    "GATE_ERROR_REPOSITORY_NOT_FOUND",
    "GATE_ERROR_REPO_NOT_IN_SNAPSHOT",
    "GATE_ERROR_GATE_NOT_OPEN",
]


def _gate_outcome(
    error: str,
    *,
    requires_research: bool = False,
    before: dict | None = None,
    after: dict | None = None,
) -> dict:
    return {
        "error": error,
        "requires_research": requires_research,
        "before": before or {},
        "after": after or {},
    }


def _gate_entry_view(entry: dict) -> dict:
    """decision_log 的 before/after 视图（只取会被动作改动的四个键，正文按需截断）。"""
    return {
        key: (
            str(entry.get(key) or "")[:_MAX_GATE_REASON_CHARS]
            if key == "responsibility"
            else entry.get(key)
        )
        for key in _GATE_ENTRY_VIEW_KEYS
    }


def _new_gate_entry(repository_id: str, repository_name: str, role: str, confidence: str) -> dict:
    """``add_repo`` 的快照占位条目：``fitness`` 留空（尚无任何调研结论）。"""
    return {
        "repository_id": repository_id,
        "repository_name": str(repository_name or ""),
        "role_suggestion": role,
        "responsibility": "",
        "confidence": confidence,
        "fitness": None,
        "current_state_summary": "",
        "routing_evidence": {},
        "pending_research": True,
        "removed": False,
        "actions": [],
    }


def _lookup_gate_repository(repository_id: str) -> Any:
    """按 id 取仓（非法 uuid / 不存在一律 ``None`` → 视图回 404）。"""
    from repositories.models import Repository

    try:
        return Repository.objects.filter(id=repository_id).first()
    except Exception:  # noqa: BLE001 — 非法 uuid 触发的 ValidationError 一律按「不存在」
        return None


def _gate_note_text(action: str, *, repository_id: str, outcome: dict) -> str:
    """留痕文案（只含 action 与 id，不回显职责正文——正文已在快照里）。"""
    after = outcome.get("after") or {}
    if action == "remove_repo":
        return f"用户移除仓库 {repository_id}。"
    if action == "add_repo":
        return f"用户手动补充仓库 {repository_id}（角色 {after.get('role_suggestion')}），将触发该仓调研。"
    if action == "reclassify_role":
        return f"用户将仓库 {repository_id} 改判为 {after.get('role_suggestion')}。"
    if action == "edit_responsibility":
        return f"用户修改了仓库 {repository_id} 的职责描述。"
    return f"用户对仓库 {repository_id} 执行了 {action}。"
