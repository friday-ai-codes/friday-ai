"""蓝图专用 engine 续驱 helper（Phase 112-05）。

四段契约：

- **形状照 ``resume.py`` 但换 pause 判据**：``resume.py`` 的 ``waiting_clarification``
  短路绑旧编排链的澄清轮模型，与蓝图的 ``BlueprintThread`` 不匹配；改它会让旧
  ``technical_plan`` process 回归，所以新建本文件（``resume.py`` 逐字未改）。
- **旧 process 零感知**：本文件只被 ``technical_blueprint`` 链调用（确认门七动作端点、
  调研 fan-out barrier）。
- **INV-6**：状态只经 ``engine.session_service.transition`` 与
  ``BlueprintLifecycleService.transition`` 转移，helper 绝不直接写 ``session.status`` /
  ``current_stage`` / ``blueprint_status``。
- **``aresume_after_gate_action`` 是确认门动作端点的续驱入口**，best-effort：续驱失败
  绝不反噬已持久化的动作（动作 REST 仍 2xx，``pending_research`` 标记留库待下次触发）。

**pause 判据是一个合取**（``waiting_clarification`` 时）：「有 open+blocking
``BlueprintThread``」**且**「``acollect_pending_research_repos(session)`` 为空」才短路。
第二项是续驱能否闭环的关键：``repo_confirmation`` 挂起时确认门线程恒为 open+blocking，
只看线程就短路会让 ``add_repo`` / ``upgrade-research`` 后的 advance 在第一步之前被拦掉，
``research_required`` 边永远走不到（SC-4 断链）。判据函数与
``_h_bp_repo_confirmation`` 共用**同一实现**（``blueprint_confirm_gate`` 模块级），
两处漂移即断链。

**并发/幂等零新造**：跨 stage 的并发续驱由
``ConvergenceSessionService._apply_transition_sync`` 的 CAS 去重
（``filter(id, current_stage=from_stage).update()``；``updated != 1`` →
``ConcurrentTransitionError``，engine 已吞掉并记 sampling、绝不落 fail），败者那步
advance 是 no-op。**注意 self-loop 例外**：三个 pausable stage 的挂起边
（``spec_gate``/``repo_research``/``repo_confirmation`` 自环）下 ``new_stage == from_stage``，
CAS 条件对两个并发写者同时成立，去重不生效——``stage_state`` 的一致性因此不靠这把 CAS，
而靠 ``transition(stage_state_update=...)`` 在写入事务内锁行合并增量（engine 传增量、
不预合并）。容器不重开由 112-04 ``dispatch`` 的 ``_DISPATCHABLE_STATUSES`` 白名单
与 ``create_tasks_for_session`` 的 ``get_or_create`` 保证；死循环由 ``max_steps`` 兜底。
**本文件不加锁、不加字段、不加 status。**
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = [
    "BLUEPRINT_PROCESS_TYPE",
    "adrive_blueprint_session_to_pause_or_terminal",
    "aresume_after_gate_action",
    "aresume_blueprint_session",
]

# 本 helper 唯一允许驱动的 process 类型（与 builtin_processes 第三次注册同值）。
BLUEPRINT_PROCESS_TYPE = "technical_blueprint"

# 113 追加（B3）：stage → 蓝图状态映射。**只登记阶段 2/3 两个 stage**——112 注册的前七个
# stage 不在表内，一律回落 `researching`，与改动前逐字等价（`test_blueprint_status_stage_map`
# 有七条参数化等价性回归断言背书）。
#
# 值用字面量而非 `BlueprintStatus.DRAFTING`：本模块所有 Django 模型 import 都在函数内
# （lazy），模块级表拿不到那个枚举。字面量与枚举值相等（`BlueprintStatus.DRAFTING ==
# "drafting"`，TextChoices）由 `test_stage_status_table_matches_enum` 锁死，防漂移。
_STAGE_BLUEPRINT_STATUS: dict[str, str] = {
    "repo_plan": "drafting",  # == BlueprintStatus.DRAFTING
    "merge": "drafting",  # == BlueprintStatus.DRAFTING
    # 114 追加：审查 stage 期间蓝图状态为 `ai_reviewing`（映射表追加，消费方零改动）。
    "ai_review": "ai_reviewing",  # == BlueprintStatus.AI_REVIEWING
}


def _resolve_stage_status(session: Any) -> str:
    """按 ``current_stage`` 取蓝图状态；未登记的 stage（含前七个与空串）回落 researching。

    为什么必须 stage-aware：阶段 2/3 的会话每次经续驱或澄清恢复都会走
    :func:`_amap_blueprint_status`，若目标态写死 ``researching``，已产出 RepoPlan 与融合
    蓝图的会话会被一路拉回「调研中」，而澄清解除后也回到阶段 1 的状态口径 —— 用户看到
    的是「白干了」，114 拿到的状态也对不上（T-113-43）。
    """
    from delivery.models import BlueprintStatus

    stage = str(getattr(session, "current_stage", "") or "")
    return _STAGE_BLUEPRINT_STATUS.get(stage, BlueprintStatus.RESEARCHING)


def _safe_log(event: str, **fields: Any) -> None:
    """best-effort 结构化埋点（观测失败吞掉，绝不反噬业务）。"""
    try:
        logger.info(event, **fields)
    except Exception:  # noqa: BLE001 — 观测 best-effort
        pass


async def adrive_blueprint_session_to_pause_or_terminal(
    engine: Any, session: Any, *, max_steps: int = 20
) -> Any:
    """续驱蓝图会话到「重挂起短路点」或终态 ``{DONE, FAILED}`` 后返回该 session。

    短路点：

    - ``waiting_clarification`` 且**有 open+blocking ``BlueprintThread``**（``ai_clarification``
      与 ``repo_confirmation`` 两类，故不传 ``kind``）**且无待调研仓** → 短路返回。
      有待调研仓时**放行 advance**——``_h_bp_repo_confirmation`` 会把它转到
      ``repo_research``，随后 ``waiting_event`` 短路自然接管。
    - ``waiting_event`` 且仍有在途调研 → 短路返回（等下一次容器回调）。
    - advance 步数超 ``max_steps`` → 经 ``transition(session, "fail")`` 标记失败并返回。
    """
    from delivery.models import ConvergenceSession, ConvergenceSessionStatus
    from services.process_runtime import aall_research_tasks_terminal
    from services.process_runtime.blueprint_confirm_gate import (
        acollect_pending_research_repos,
    )

    if str(getattr(session, "process_type", "")) != BLUEPRINT_PROCESS_TYPE:
        # 蓝图 engine 的 deps 只有 spec_gate/route/research/confirm_gate；用它驱别的 process
        # 会让旧链 handler 取不到 deps.router 抛异常，engine 随后把那条无关会话落 FAILED。
        # 宁可 no-op：调用方传错会话是 bug，不是「该会话该失败」。
        logger.warning(
            "blueprint_resume_wrong_process_type",
            category="caller",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            process_type=str(getattr(session, "process_type", "")),
        )
        return session

    terminal = {ConvergenceSessionStatus.DONE, ConvergenceSessionStatus.FAILED}
    steps = 0
    while session.status not in terminal:
        steps += 1
        if steps > max_steps:
            await engine.session_service.transition(
                session,
                "fail",
                error={"reason": "advance_step_limit", "steps": steps},
            )
            session = await ConvergenceSession.objects.aget(id=session.id)
            await _amap_blueprint_status(session)
            return session

        if session.status == ConvergenceSessionStatus.WAITING_CLARIFICATION:
            if await _ahas_open_blocking_blueprint_threads(session) and not (
                await acollect_pending_research_repos(session)
            ):
                await _amap_blueprint_status(session)
                return session

        if session.status == ConvergenceSessionStatus.WAITING_EVENT and not (
            await aall_research_tasks_terminal(session.id)
        ):
            await _amap_blueprint_status(session)
            return session

        await engine.advance(session)
        session = await ConvergenceSession.objects.aget(id=session.id)

    await _amap_blueprint_status(session)
    return session


async def aresume_after_gate_action(
    session: Any, *, initiated_by_user_id: str, engine: Any = None
) -> Any:
    """确认门动作端点的续驱入口（**best-effort，失败绝不反噬已持久化的动作**）。

    调用方是 ``delivery/api/blueprint_gate_views.py`` 的六个改状态动作端点：动作端点只
    落库不推进 stage，本函数负责那一步 advance。整段 ``try/except`` 全兜——**helper 自己
    兜住，调用方视图不重复包**：异常只记 ``blueprint_gate_resume_failed`` 并返回传入的
    session，绝不上抛让 REST 变 5xx；``pending_research`` 标记与 task 状态都在库里，下一
    次任意确认门动作或容器回调续驱时判据仍成立，不丢事。
    """
    started = time.perf_counter()
    try:
        from .entrypoint import build_blueprint_engine

        engine = engine or build_blueprint_engine()
        session = await adrive_blueprint_session_to_pause_or_terminal(engine, session)
        _safe_log(
            "blueprint_gate_resume_completed",
            category="caller",
            component="process_runtime",
            initiated_by_user_id=initiated_by_user_id or "system",
            session_id=str(getattr(session, "id", "")),
            session_status=str(getattr(session, "status", "")),
            current_stage=str(getattr(session, "current_stage", "")),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return session
    except Exception as exc:  # noqa: BLE001 — 续驱失败绝不反噬动作（动作已持久化）
        logger.warning(
            "blueprint_gate_resume_failed",
            category="caller",
            component="process_runtime",
            initiated_by_user_id=initiated_by_user_id or "system",
            session_id=str(getattr(session, "id", "")),
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return session


async def aresume_blueprint_session(session: Any, *, engine: Any = None) -> Any:
    """调研 fan-out barrier 的续驱入口（112-04 的接线契约，函数名即契约）。

    全部 ``RepoResearchTask`` 终态后由 ``subagent/api/callbacks.py`` 的 barrier 调用；
    与 :func:`aresume_after_gate_action` 同为 best-effort（回调链绝不能因续驱异常
    把容器回调打成 5xx）。
    """
    started = time.perf_counter()
    try:
        from .entrypoint import build_blueprint_engine

        engine = engine or build_blueprint_engine()
        session = await adrive_blueprint_session_to_pause_or_terminal(engine, session)
        _safe_log(
            "blueprint_barrier_resume_completed",
            category="caller",
            component="process_runtime",
            initiated_by_user_id=str(getattr(session, "initiated_by_user_id", "") or "system"),
            session_id=str(getattr(session, "id", "")),
            session_status=str(getattr(session, "status", "")),
            current_stage=str(getattr(session, "current_stage", "")),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return session
    except Exception as exc:  # noqa: BLE001 — 回调链 best-effort
        logger.warning(
            "blueprint_barrier_resume_failed",
            category="caller",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            error=redact_secrets_in_text(str(exc)),
        )
        return session


# ── pause 判据与蓝图状态映射（均 best-effort，绝不反噬续驱）────────────────────


async def _ahas_open_blocking_blueprint_threads(session: Any) -> bool:
    """该会话蓝图是否仍有 open+blocking 线程（``ai_clarification`` + ``repo_confirmation``）。"""
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    artifact = await _aload_artifact(session)
    if artifact is None:
        return False
    try:
        return await BlueprintLifecycleService().ahas_open_blocking_threads(artifact)
    except Exception as exc:  # noqa: BLE001 — 判据读失败按「有阻塞线程」保持挂起
        # 与规格门/确认门同向 fail-closed：挂起可由下一次触发恢复，误放行不可逆
        # （DB 抖动时会把「有未决澄清线程」误判成无门而多推一步 advance）。
        logger.warning(
            "blueprint_resume_blocking_probe_failed",
            category="caller",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            error=redact_secrets_in_text(str(exc)),
        )
        return True


async def _aload_artifact(session: Any) -> Any:
    from delivery.models import ArtifactVersion

    version_id = getattr(session, "current_artifact_version_id", None)
    if not version_id:
        return None
    version = await (
        ArtifactVersion.objects.select_related("artifact").filter(id=version_id).afirst()
    )
    return getattr(version, "artifact", None)


async def _amap_blueprint_status(session: Any) -> None:
    """蓝图状态映射（CONTEXT 锁定 + B3）：**按 stage 映射**——112 注册的前七个 stage
    （阶段 0/1）全程 ``researching``，113 追加的 ``repo_plan`` / ``merge``（阶段 2/3）为
    ``drafting``；有 open+blocking 线程时派生 ``needs_clarification`` 并带
    ``return_status`` = 同一映射结果（阶段 2/3 因此恢复回本阶段而非退回阶段 1）。

    目标态由 :func:`_resolve_stage_status` 单点解析；三处取值全部走它，故新增 stage 只需
    往 :data:`_STAGE_BLUEPRINT_STATUS` 加一行。

    一律经 ``BlueprintLifecycleService.transition``（合法性与 CAS 由它保证）；非法边
    /并发冲突一律吞掉——状态映射是展示面，绝不反噬续驱主流程。
    """
    from delivery.models import BlueprintStatus
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    artifact = await _aload_artifact(session)
    if artifact is None:
        return
    lifecycle = BlueprintLifecycleService()
    initiated_by = str(getattr(session, "initiated_by_user_id", "") or "") or "system"
    stage_status = _resolve_stage_status(session)
    try:
        blocked = await lifecycle.ahas_open_blocking_threads(artifact)
        if not artifact.blueprint_status:
            # 状态机入口边只有 `"" → researching`：先补这一跳，再由下面那次 transition
            # 落到 stage 对应的目标态（阶段 2/3 即 researching → drafting，合法边）。
            await lifecycle.transition(
                artifact,
                BlueprintStatus.RESEARCHING,
                initiated_by_user_id=initiated_by,
                session=session,
            )
        target = BlueprintStatus.NEEDS_CLARIFICATION if blocked else stage_status
        if artifact.blueprint_status == target:
            return
        await lifecycle.transition(
            artifact,
            target,
            initiated_by_user_id=initiated_by,
            session=session,
            return_status=stage_status if blocked else None,
        )
    except Exception as exc:  # noqa: BLE001 — 映射 best-effort（非法边/并发冲突照常吞掉）
        logger.warning(
            "blueprint_status_map_skipped",
            category="sampling",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            artifact_id=str(getattr(artifact, "id", "")),
            error=redact_secrets_in_text(str(exc)),
        )
