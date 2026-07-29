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

- **守卫**：``pending_review → confirmed`` 要求无 open+blocking 线程（LIFE-02）；
  进入 ``needs_clarification`` 时 ``return_status`` 必须 ∈ {researching, drafting,
  ai_reviewing}（缺省取 from_status；持久承载走 BlueprintThread.return_stage 由调用
  方写，本 service 只校验与透传进事件 payload——RESEARCH A4，不给 Artifact 加列）。
- **事件 best-effort（RESEARCH P3）**：``ConvergenceSessionEvent.session`` 是非空
  FK——``session`` 参数可空，无 session 时只打 structlog 不落事件行；事件持久化
  整体 try/except 吞掉，观测绝不反噬业务。绝不给 event 模型加字段。
- **P10 备注**：「一项目一份活跃蓝图」的唯一性守卫由 Phase 112 的创建入口负责，
  本 service 不做（Artifact 无 project FK，项目归属只在 content.meta.project_id）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from delivery.models import (
    Artifact,
    BlueprintReviewer,
    BlueprintStatus,
    BlueprintThread,
    ConvergenceSessionEvent,
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
          必须 ∈ {researching, drafting, ai_reviewing}。
        - ``to_status == confirmed``：存在 open+blocking 线程即拒绝（LIFE-02）；
          ``acting_user`` 非空时自动 upsert 进 BlueprintReviewer 名单（首插留痕）。
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

        if to_status == BlueprintStatus.CONFIRMED:
            has_open_blocking = await BlueprintThread.objects.filter(
                artifact=artifact,
                status=ThreadStatus.OPEN,
                blocking=True,
            ).aexists()
            if has_open_blocking:
                raise ValueError("存在未解决的阻塞澄清线程，蓝图不可确认")

        await self._apply_transition_sync(artifact, from_status=from_status, to_status=to_status)

        # LIFE-02：确认类动作自动入评审人名单；aget_or_create 保证 first_action 只在
        # 首插写入（重复确认不覆盖）。
        if to_status == BlueprintStatus.CONFIRMED and acting_user is not None:
            await BlueprintReviewer.objects.aget_or_create(
                artifact=artifact,
                user=acting_user,
                defaults={"first_action": "final_approve"},
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
        self, artifact: Artifact, *, from_status: str, to_status: str
    ) -> None:
        """以 ``blueprint_status == from_status`` 为前置条件的 CAS 原子更新（防 TOCTOU）。

        ``Artifact.updated_at`` 是 auto_now 字段，``.update()`` 绕过 auto_now——必须
        显式带上。成功后同步内存对象字段。
        """
        updated = Artifact.objects.filter(id=artifact.id, blueprint_status=from_status).update(
            blueprint_status=to_status, updated_at=timezone.now()
        )
        if updated != 1:
            raise ConcurrentBlueprintTransitionError(
                f"并发/陈旧蓝图状态转移被拒：artifact={artifact.id} "
                f"expected_from={from_status or '<未进入状态机>'} to={to_status}"
                "（DB 行 blueprint_status 已被并发推进改写或行不存在）"
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
