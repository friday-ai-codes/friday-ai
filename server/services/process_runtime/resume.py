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
    """
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
