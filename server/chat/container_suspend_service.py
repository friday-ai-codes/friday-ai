"""容器 5min 无回复挂起 / 卡片回复 resume 编排（PLAN-03，Phase 89）。

单仓编码容器遇阻等待用户（``subagent/api/callbacks.py`` 的 ``question`` 回调发飞书卡）时
注册 5min 计时；到点无回复 → finish turn → 停容器（``dispatcher.cancel``）+
``CodingSession.status=SUSPENDED`` / ``parked_at``；用户卡片回复 → 经
``chat/sdk_resume.build_resume_dispatch_env``（``SessionStore`` Redis→DB + cwd 一致 +
分片 transcript）re-dispatch ``DispatchTask`` 续跑到终态。**session 找不到 → 用应用态
（canonical 方案 + 用户回复）重灌新 session**（官方推荐兜底）。

复用约束（铁律，绝不重造 session 持久化）
========================================
- resume / miss 兜底全部经 Phase 86 ``SessionStore`` + ``build_resume_dispatch_env``
  （命中即 resume env，cwd 漂移 / 超限 / 无 transcript → 返回 ``{}`` 走应用态重灌）。
- 5min 计时经 apscheduler ``DateTrigger`` 一次性 job（已在栈，repo sync 轮询用；
  job_id 幂等 ``replace_existing``；多副本 ``DjangoJobStore`` 共享 + CAS 幂等去重）。
- 停容器经 ``runners.dispatcher.get_dispatcher().cancel(task_id)``（v0.8）。

写入收口（INV-6）+ 竞态 fail-soft
================================
- ``CodingSession.status=SUSPENDED`` / ``parked_at`` / 回 ``RUNNING`` 一律经本 service
  的 **CAS 条件 update** 写（``RUNNING/AWAITING→SUSPENDED``；``SUSPENDED/AWAITING→
  RUNNING``），已非该态即幂等短路。
- 停容器 / 计时 / resume 任一外部调用失败都吞掉（best-effort），**绝不反噬**容器回调 /
  飞书回调主流程（绝不回灌 5xx 致 runner 重试风暴）。
- 归因 ``initiated_by_user_id``（回复取 ``callback.user_open_id``，后台线程 re-bind），
  无触发用户记 ``system``；user_reply 经 ``redact_secrets_in_text`` 脱敏后并进 prompt /
  绝不明文落日志。
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from chat.session_store import WORKSPACE_CWD

if TYPE_CHECKING:
    from chat.models import CodingSession

logger = structlog.get_logger(__name__)

__all__ = ["ContainerSuspendService", "schedule_container_resume"]

_COMPONENT = "chat"

# 5min 无回复挂起默认窗口（分钟）。
DEFAULT_SUSPEND_MINUTES = 5

# apscheduler job 触发延误兜底窗口（秒）：scheduler 启动慢 / 短暂停机仍能补触发。
_MISFIRE_GRACE_SECONDS = 600


def _job_id(coding_session_id: Any) -> str:
    """一次性挂起 job 的稳定 id（幂等 replace_existing 复用同一 id）。"""
    return f"suspend-{coding_session_id}"


# ---------------------------------------------------------------------------
# apscheduler 计时载体（best-effort 单例）
# ---------------------------------------------------------------------------
_timeout_scheduler: Any = None


def _get_timeout_scheduler() -> Any:
    """惰性构建并启动一个带 ``DjangoJobStore`` 的 ``BackgroundScheduler``（best-effort）。

    job 落共享 ``DjangoJobStore``（多副本/多进程共享，去重由 jobstore + CAS 幂等兜底）；
    到点触发 :func:`_run_suspend_job`。构建 / 启动失败返回 ``None``（计时降级失效，但
    绝不反噬主流程——挂起仅是资源优化，缺失不影响功能正确性）。
    """
    global _timeout_scheduler
    if _timeout_scheduler is not None:
        return _timeout_scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from django_apscheduler.jobstores import DjangoJobStore

        scheduler = BackgroundScheduler()
        scheduler.add_jobstore(DjangoJobStore(), "default")
        scheduler.start()
        _timeout_scheduler = scheduler
        logger.info(
            "container_suspend_scheduler_started",
            component=_COMPONENT,
            category="sampling",
        )
    except Exception as exc:  # noqa: BLE001 — 计时载体不可用即降级，绝不反噬主流程
        logger.warning(
            "container_suspend_scheduler_unavailable",
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="sampling",
        )
        _timeout_scheduler = None
    return _timeout_scheduler


def _run_suspend_job(coding_session_id: str, task_id: str, initiated_by_user_id: str) -> None:
    """apscheduler job 入口（到点无回复触发挂起）。

    顶层模块函数（``DjangoJobStore`` 按模块路径序列化 job ref）。在干净后台上下文显式
    ``bind_task_context`` 重绑发起用户后跑 :meth:`ContainerSuspendService.suspend`；全段
    best-effort，异常吞掉不抛回 scheduler（绝不打断其它 job）。
    """
    import asyncio

    try:
        from common.log_context import bind_task_context

        with bind_task_context(
            user_id=initiated_by_user_id or "system",
            source="scheduler",
            component=_COMPONENT,
        ):
            asyncio.run(
                ContainerSuspendService().suspend(
                    coding_session_id=coding_session_id, task_id=task_id
                )
            )
    except Exception as exc:  # noqa: BLE001 — 挂起 job best-effort，绝不抛回 scheduler
        logger.warning(
            "container_suspend_job_error",
            coding_session_id=str(coding_session_id),
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
        )


class ContainerSuspendService:
    """容器挂起 / resume / miss 重灌写收口（INV-6）。"""

    async def arm_timeout(
        self,
        *,
        coding_session_id: Any,
        task_id: str,
        initiated_by_user_id: str = "system",
        minutes: int = DEFAULT_SUSPEND_MINUTES,
    ) -> bool:
        """容器问答发卡时注册 5min 一次性挂起 job（job_id 幂等 replace_existing）。

        到点回调 :func:`_run_suspend_job` → :meth:`suspend`。计时载体不可用 / 注册异常
        → 吞掉记 warning（best-effort），返回 ``False``，绝不反噬回调主流程。
        """
        try:
            from apscheduler.triggers.date import DateTrigger

            scheduler = _get_timeout_scheduler()
            if scheduler is None:
                return False
            run_date = timezone.now() + timedelta(minutes=minutes)
            await sync_to_async(scheduler.add_job)(
                _run_suspend_job,
                trigger=DateTrigger(run_date=run_date),
                id=_job_id(coding_session_id),
                args=[
                    str(coding_session_id),
                    str(task_id),
                    str(initiated_by_user_id or "system"),
                ],
                replace_existing=True,
                misfire_grace_time=_MISFIRE_GRACE_SECONDS,
            )
            logger.info(
                "container_suspend_armed",
                coding_session_id=str(coding_session_id),
                minutes=minutes,
                component=_COMPONENT,
                category="caller",
            )
            return True
        except Exception as exc:  # noqa: BLE001 — 计时注册 best-effort，绝不反噬回调
            logger.warning(
                "container_suspend_arm_failed",
                coding_session_id=str(coding_session_id),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return False

    async def cancel_timeout(self, *, coding_session_id: Any) -> bool:
        """用户回复时取消未触发的挂起 job（不存在 no-op，best-effort）。"""
        try:
            scheduler = _get_timeout_scheduler()
            if scheduler is None:
                return False
            await sync_to_async(scheduler.remove_job)(_job_id(coding_session_id))
            logger.info(
                "container_suspend_timer_cancelled",
                coding_session_id=str(coding_session_id),
                component=_COMPONENT,
                category="caller",
            )
            return True
        except Exception:  # noqa: BLE001 — job 不存在 / scheduler 异常均 no-op
            return False

    async def suspend(self, *, coding_session_id: Any, task_id: str) -> bool:
        """5min 无回复 → CAS RUNNING/AWAITING→SUSPENDED + 停容器 + 写 parked_at。

        - CAS 条件 update：已非 ``RUNNING/AWAITING`` 即幂等短路（防计时到点与用户回复
          / 其它终态并发双触发）。
        - 状态翻 SUSPENDED 后再 ``dispatcher.cancel``；停容器失败吞掉（状态已挂起，
          下次资源回收兜底），绝不反噬。
        """
        started = time.monotonic()
        try:
            from chat.models import CodingSession

            updated = await CodingSession.objects.filter(
                id=coding_session_id,
                status__in=[
                    CodingSession.Status.RUNNING,
                    CodingSession.Status.AWAITING_CONFIRMATION,
                ],
            ).aupdate(
                status=CodingSession.Status.SUSPENDED,
                parked_at=timezone.now(),
                updated_at=timezone.now(),
            )
            if not updated:
                # 已 SUSPENDED / 终态 → 幂等短路（竞态安全）。
                logger.info(
                    "container_suspend_skipped_not_active",
                    coding_session_id=str(coding_session_id),
                    component=_COMPONENT,
                    category="caller",
                )
                return False

            cancelled = False
            try:
                from runners.dispatcher import get_dispatcher

                cancelled = await get_dispatcher().cancel(str(task_id))
            except Exception as exc:  # noqa: BLE001 — 停容器 best-effort，状态已挂起
                logger.warning(
                    "container_suspend_cancel_failed",
                    coding_session_id=str(coding_session_id),
                    error_type=type(exc).__name__,
                    component=_COMPONENT,
                    category="caller",
                )

            logger.info(
                "container_suspended",
                coding_session_id=str(coding_session_id),
                container_cancelled=cancelled,
                duration_ms=int((time.monotonic() - started) * 1000),
                component=_COMPONENT,
                category="caller",
            )
            return True
        except Exception as exc:  # noqa: BLE001 — 挂起 best-effort，绝不反噬主流程
            logger.warning(
                "container_suspend_failed",
                coding_session_id=str(coding_session_id),
                error_type=type(exc).__name__,
                duration_ms=int((time.monotonic() - started) * 1000),
                component=_COMPONENT,
                category="caller",
            )
            return False

    async def resume(
        self,
        *,
        coding_session: CodingSession,
        user_reply: str,
        dispatch_cwd: str = WORKSPACE_CWD,
        initiated_by_user_id: str = "system",
    ) -> bool:
        """用户卡片回复 → resume 续跑到终态（session miss → 应用态重灌新 session）。

        1. CAS SUSPENDED/AWAITING→RUNNING（已非该态幂等短路，防与计时到点竞态）。
        2. ``build_resume_dispatch_env`` 命中（Redis→DB + cwd 一致 + 分片 transcript）
           → re-dispatch 携 resume env 续跑（``container_resumed``）。
        3. env 空（session miss / cwd 漂移 / 超限）→ 用 canonical 方案 + user_reply
           重灌全新 session（无 resume 标记，``container_resume_reloaded``）。

        实际 dispatch 经 ``coding_session_service.dispatch_coding_task``，其内部对 coding
        任务自带 ``build_resume_dispatch_env`` 注入（命中即续跑，空即全新）；本方法的
        env 探测仅用于区分事件 / 归因。全段 fail-soft，绝不反噬飞书回调主流程。
        """
        started = time.monotonic()
        try:
            from chat.models import CodingSession

            updated = await CodingSession.objects.filter(
                id=coding_session.id,
                status__in=[
                    CodingSession.Status.SUSPENDED,
                    CodingSession.Status.AWAITING_CONFIRMATION,
                ],
            ).aupdate(status=CodingSession.Status.RUNNING, updated_at=timezone.now())
            if not updated:
                logger.info(
                    "container_resume_skipped_not_suspended",
                    coding_session_id=str(coding_session.id),
                    component=_COMPONENT,
                    category="caller",
                )
                return False

            # dispatch 需 repository / conversation / space（async 安全：预 select_related）。
            coding_session = await CodingSession.objects.select_related(
                "repository", "conversation", "conversation__space", "coding_plan"
            ).aget(id=coding_session.id)

            from chat.sdk_resume import build_resume_dispatch_env

            resume_env = build_resume_dispatch_env(coding_session, dispatch_cwd=dispatch_cwd)
            reused_session = bool(resume_env)

            prompt = self._build_resume_prompt(coding_session, user_reply)

            from chat.coding_session_service import dispatch_coding_task

            await dispatch_coding_task(coding_session, task_type="coding", prompt=prompt)

            logger.info(
                "container_resumed" if reused_session else "container_resume_reloaded",
                coding_session_id=str(coding_session.id),
                reused_session=reused_session,
                has_user_reply=bool((user_reply or "").strip()),
                duration_ms=int((time.monotonic() - started) * 1000),
                component=_COMPONENT,
                category="caller",
            )
            return True
        except Exception as exc:  # noqa: BLE001 — resume best-effort，绝不反噬回调主流程
            logger.warning(
                "container_resume_failed",
                coding_session_id=str(getattr(coding_session, "id", "")),
                error_type=type(exc).__name__,
                duration_ms=int((time.monotonic() - started) * 1000),
                component=_COMPONENT,
                category="caller",
            )
            return False

    @staticmethod
    def _build_resume_prompt(coding_session: CodingSession, user_reply: str) -> str:
        """构建 resume 续跑 prompt：用户回复脱敏后并进受控块（不裸拼执行指令）。

        transcript 已由 resume env 还原全量上下文（命中场景），故 prompt 主要承载用户
        回复 + 续跑指令；miss 重灌场景下方案正文经容器 dispatch 项目上下文召回补齐。
        """
        from common.logging import redact_secrets_in_text

        reply = redact_secrets_in_text((user_reply or "").strip())
        return (
            "继续之前因等待你的回复而被挂起的编码任务。"
            "以下是用户对你上一轮提问的回复：\n\n"
            "<用户回复>\n"
            f"{reply}\n"
            "</用户回复>\n\n"
            "请基于该回复继续推进并完成技术方案的实现。"
        )


def schedule_container_resume(
    *, session_id: str, user_reply: str, responder_id: str = ""
) -> None:
    """容器问答卡片回复入口：后台线程取消计时 + （仅挂起态）resume 续跑。

    飞书回调须 3s 内响应，故重活经 ``_run_in_thread`` + ``bind_task_context`` 后台跑
    （归因取 ``callback.user_open_id``）。仅当 ``CodingSession`` 已 ``SUSPENDED`` 才
    re-dispatch——未挂起（容器仍存活，用户在 5min 内回复）时答复已由
    ``handle_container_answer_enhanced`` 经 answer.json / HTTP 直达活容器，绝不重复起容器。
    全段 fail-soft，绝不反噬回调。
    """
    try:
        from workflows.engine.scheduler import _run_in_thread

        _run_in_thread(
            _do_resume_async(
                session_id=session_id,
                user_reply=user_reply,
                responder_id=responder_id,
            ),
            triggered_by_id=responder_id or None,
        )
    except Exception as exc:  # noqa: BLE001 — 调度 best-effort，绝不反噬回调
        logger.warning(
            "container_resume_schedule_failed",
            session_id=str(session_id),
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
        )


async def _do_resume_async(
    *, session_id: str, user_reply: str, responder_id: str = ""
) -> None:
    """后台 resume 协程：定位 CodingSession → cancel_timeout → 仅挂起态时 resume。"""
    try:
        from chat.models import CodingSession

        coding_session = await CodingSession.objects.filter(
            subagent_session__session_id=session_id
        ).afirst()
        if coding_session is None:
            return

        service = ContainerSuspendService()
        await service.cancel_timeout(coding_session_id=str(coding_session.id))

        # 仅挂起态才 resume 续跑（未挂起 = 容器存活，答复已直达，绝不重复起容器）。
        if coding_session.status != CodingSession.Status.SUSPENDED:
            return

        await service.resume(
            coding_session=coding_session,
            user_reply=user_reply,
            initiated_by_user_id=responder_id or "system",
        )
    except Exception as exc:  # noqa: BLE001 — resume 后台 best-effort，绝不反噬回调
        logger.warning(
            "container_resume_async_failed",
            session_id=str(session_id),
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
        )
