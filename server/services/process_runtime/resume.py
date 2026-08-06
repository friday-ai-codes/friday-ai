"""入口无关的共享 engine 续驱 helper（Chassis v2 · P2，泛化自 plan resume driver）。

供工作流节点 / chat 工具 / 回调消费者三处复用同一份续驱逻辑（落「底层续驱 engine 同源、
不造两套」）。``ProcessEngine`` 由调用方传入（绝不在此新建第二个 engine 工厂）；helper 只负责
入口无关的 advance 续驱与「重挂起」短路。

设计要点：
- **engine 纯度（INV-6）**：状态只经 ``engine.session_service.transition`` 转移，helper 绝不
  直接写 ``session.status`` / ``current_stage``。
- **fail-soft / 防死循环**：advance 步数超过 ``max_steps`` 时经 ``transition(session, "fail")``
  标记失败并返回，不死循环。
- **挂起短路**：``waiting_clarification``（仍有未答澄清）/ ``waiting_event``（仍有在途调研）
  立即短路返回，等用户作答 / 容器回调后再次 resume 推进。
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["adrive_convergence_session_to_pause_or_terminal"]


async def adrive_convergence_session_to_pause_or_terminal(
    engine: Any, session: Any, *, max_steps: int = 20
) -> Any:
    """续驱 ConvergenceSession 到「重挂起短路点」或终态 ``{DONE, FAILED}`` 后返回该 session。

    入口无关：调用方传入已构造的 engine 与待续驱的 ``ConvergenceSession``。helper 反复
    ``engine.advance`` + 重读状态，直到：

    - session 到达终态 ``{DONE, FAILED}`` → 返回该 session。
    - ``waiting_clarification`` 且仍有未答 ``Clarification`` → 短路返回（保护澄清 HITL）。
    - ``waiting_event`` 且仍有在途调研 → 短路返回（等下一次容器回调）。
    - advance 步数超过 ``max_steps`` → 经 ``transition(session, "fail")`` 标记失败并返回。

    ⭐ **蓝图会话一律 no-op**（116-01，与 ``blueprint_resume.py:132-143`` 对称）：见函数体
    首个 if 块的论证。⛔ **只挡蓝图会话** —— 本文件是旧链共享面（``plan_deepen`` 等非蓝图
    调用方也走它），不得顺手加别的 ``process_type`` 判断。
    """
    # 函数内懒 import：resume.py 是旧链共享面，⛔ 不在模块级依赖 blueprint_resume。
    from services.process_runtime.blueprint_resume import BLUEPRINT_PROCESS_TYPE

    if str(getattr(session, "process_type", "")) == BLUEPRINT_PROCESS_TYPE:
        # 旧续驱器的 waiting_clarification 短路判据是 ClarificationService().ahas_pending，
        # 对蓝图会话恒 False ⇒ 三个 pausable stage 一个都短路不了，self-loop 会被推到
        # max_steps 落 advance_step_limit FAILED。宁可 no-op：调用方传错 driver 是 bug，
        # 不是「该会话该失败」。（116-01，与 blueprint_resume.py:132-143 对称）
        logger.warning(
            "wrong_driver_for_blueprint_session",
            category="caller",
            component="process_runtime",
            session_id=str(getattr(session, "id", "")),
            process_type=str(getattr(session, "process_type", "")),
        )
        return session

    from services.process_runtime.drive_lease import asession_drive_lease

    # ⭐ 租约包住**整个循环**而不是逐步获取：逐步获取会在两步之间留出空隙，别的驱动器正好
    # 挤进来接着推，于是同一会话被两个驱动器交替推进（比并发跑同一步更难排查）。
    # 循环里的 `engine.advance` 会命中租约的可重入分支，不会自己再抢一次。
    async with asession_drive_lease(getattr(session, "id", None), reason="drive_loop") as ok:
        if not ok:
            # 别人正在驱动同一会话：本次原地返回。⛔ 这不是错误路径 —— 多入口触发续驱是
            # 常态（回调 barrier / 动作端点 / 僵尸扫描），谁抢到谁推进即可。
            return session
        return await _adrive_locked(engine, session, max_steps=max_steps)


async def _adrive_locked(engine: Any, session: Any, *, max_steps: int) -> Any:
    """续驱循环本体：调用方**必须**已持有会话驱动租约。"""
    from delivery.models import ConvergenceSession, ConvergenceSessionStatus
    from delivery.services import ClarificationService
    from services.process_runtime import aall_research_tasks_terminal

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
            return await ConvergenceSession.objects.aget(id=session.id)

        # clarifying 在途短路（保护澄清 HITL）：仍有未答澄清 → 不再 advance。
        if (
            session.status == ConvergenceSessionStatus.WAITING_CLARIFICATION
            and await ClarificationService().ahas_pending(session.id)
        ):
            return session

        # researching 在途短路：仍有在途调研 → 等下一次容器回调，不再 advance。
        if (
            session.status == ConvergenceSessionStatus.WAITING_EVENT
            and not await aall_research_tasks_terminal(session.id)
        ):
            return session

        await engine.advance(session)
        session = await ConvergenceSession.objects.aget(id=session.id)

    return session
