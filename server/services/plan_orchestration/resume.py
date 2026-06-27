"""入口无关的共享 engine 续驱 helper（RESUME-01 步骤 1，地基）。

抽自 ``workflows/nodes/ai/plan_research.py:142-167`` 与
``agents/tools/plan_research_tools.py:124-153`` 两处逐行同构的 advance 循环，供
工作流节点 / chat 工具 / 回调消费者三处复用同一份续驱逻辑（落 CONTEXT「底层续驱
engine 的逻辑同源、不造两套」）。

设计要点：
- **入口无关**：engine 由调用方传入（绝不在此新建第二个 engine 工厂），helper 只负责
  入口无关的 advance 续驱与「重挂起」短路；入口私有的挂起 marker 映射
  （``NodeResult``/``ToolResult``）仍由各入口自己保留，对齐 ``entrypoint.py``
  docstring「驱动是入口私有」的精神。
- **engine 纯度（INV-6）**：状态只经 ``engine.session_service.transition`` 转移，
  helper 绝不直接写 ``session.status``。
- **fail-soft / 防死循环（T-43-DOS-LOOP）**：advance 步数超过 ``max_steps`` 时经
  ``transition(session, "fail")`` 标记失败并返回，不死循环。
"""

from __future__ import annotations

from typing import Any


async def adrive_plan_session_to_pause_or_terminal(
    engine: Any, session: Any, *, max_steps: int = 20
) -> Any:
    """续驱 PlanSession 到「重挂起短路点」或终态 ``{DONE, FAILED}`` 后返回该 session。

    入口无关：调用方传入已构造的 engine（工作流入口带 node_execution_id、chat 入口不带）
    与待续驱的 ``PlanSession``。helper 反复 ``engine.advance`` + 重读状态，直到：

    - session 到达终态 ``{DONE, FAILED}`` → 返回该 session。
    - session 处于 ``CLARIFYING`` 且仍有未答 ``Clarification``（``answered_at`` 为空）→
      立即短路返回（保护澄清 HITL，等价于节点/工具 ``_maybe_suspend`` 的 clarifying
      分支，不再 advance，等用户作答后由入口私有挂起逻辑 / 再次 resume 推进）。
    - session 处于 ``RESEARCHING`` 且仍有在途调研（``aall_research_tasks_terminal`` 为
      False）→ 立即短路返回（等下一次容器回调，不再 advance）。
    - advance 步数超过 ``max_steps`` → 经 ``transition(session, "fail")`` 标记失败并返回。

    状态只经 ``engine.session_service.transition`` 转移，绝不直接写 ``session.status``。
    """
    # 函数内 lazy import 规避 import 环（resume → models / barrel）
    from delivery.models import PlanSession, PlanSessionStatus
    from delivery.services import ClarificationService
    from services.plan_orchestration import aall_research_tasks_terminal

    terminal = {PlanSessionStatus.DONE, PlanSessionStatus.FAILED}
    steps = 0
    while session.status not in terminal:
        steps += 1
        if steps > max_steps:
            # 防死循环：经 service transition 标记 fail（照搬 analog fail 分支，不直接写 status）
            await engine.session_service.transition(
                session,
                "fail",
                error={"reason": "advance_step_limit", "steps": steps},
            )
            return await PlanSession.objects.aget(id=session.id)

        # clarifying 在途短路（BLOCKER 修复，保护澄清 HITL）：pending 谓词收口到 service 统一
        # ahas_pending（兼容旧单题行 + 新结构化子题，T-90-03-04），与节点/工具 _maybe_suspend
        # 行为等价——否则 engine 在 needs_clarification 时保持 clarifying→clarifying 自挂起，
        # helper 不短路会一路 advance 到 max_steps 被错误 FAILED，回归澄清 HITL。
        if (
            session.status == PlanSessionStatus.CLARIFYING
            and await ClarificationService().ahas_pending(session.id)
        ):
            return session

        # researching 在途短路：仍有在途调研 → 等下一次容器回调，不再 advance
        if (
            session.status == PlanSessionStatus.RESEARCHING
            and not await aall_research_tasks_terminal(session.id)
        ):
            return session

        await engine.advance(session)
        session = await PlanSession.objects.aget(id=session.id)

    return session
