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
    ConvergenceSessionEvent,
    ThreadAuthorType,
    ThreadKind,
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
        try:
            await ConvergenceSessionEvent.objects.acreate(
                session=session,
                event=EVENT_BLUEPRINT_STATUS_TRANSITIONED,
                work_item=getattr(session, "work_item_id", None),
                payload={
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
    ) -> BlueprintThread:
        """开一条线程并同事务写入首条 AI 提问消息。

        - ``kind`` 必须 ∈ ``ThreadKind.values``，否则 ``raise ValueError``（DB 不写）。
        - 线程行与首条消息在同一 ``transaction.atomic``：杜绝「有线程无问题」的半截
          线程——那会让 HITL 侧看到一条空白阻塞线程且永远答不了。
        - ``return_stage`` 超 ``max_length=16`` 截断并记 warning（开不出线程 = 规格门
          静默放行，宁可截断也不抛）。
        """
        if kind not in ThreadKind.values:
            raise ValueError(f"非法线程 kind={kind!r}；合法值={sorted(ThreadKind.values)}")

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
        )
        logger.info(
            "blueprint_thread_opened",
            category="caller",
            component="blueprint_lifecycle",
            artifact_id=str(artifact.id),
            kind=kind,
            blocking=bool(blocking),
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
    ) -> BlueprintThread:
        """线程行 + 首条 AI 消息同事务落库（半截线程不可接受）。"""
        with transaction.atomic():
            thread = BlueprintThread.objects.create(
                artifact=artifact,
                created_on_version=created_on_version,
                anchor=anchor,
                kind=kind,
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
