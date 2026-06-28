"""入口无关的统一 ``ask_clarification`` helper（CLARIFY-03，编排层主动发问收口）。

编排任意点（架构师融合卡住 / 某调研容器卡住 / 工作流节点 / 对话）都能调本 helper
产出结构化澄清请求：薄封装 ``ClarificationService.create_round``，写 1 个
``delivery.Clarification`` 轮次容器 + N 个 ``ClarificationQuestion`` 子题（守 INV-6，
落库只经 service），可携带 ``origin_repo`` 标注问题来源仓。工作流与对话复用同一 helper +
同一模型，不造两套写库逻辑。

设计要点（对齐 ``resume.py`` / ``clarify_adapter.py`` 既有范式）：

- **入口无关**：本 helper 只负责「产出结构化澄清请求」这一入口无关能力——**不**驱动
  ``engine.advance``、**不**做挂起 marker、**不**碰 ``session.status``（status 只经
  ``ConvergenceSessionService.transition`` 转移）。驱动与挂起映射是各入口私有（对齐
  ``entrypoint.py`` / ``resume.py`` docstring「驱动是入口私有」的精神）。
- **INV-6 写入收口**：写入仅经 ``ClarificationService.create_round``，绝不旁路写表。
- **async 防裸 lazy-FK**：只把 ``session`` 透传给 service（service 内部已 ``sync_to_async``
  桥接），本 helper 不裸访问 ``session`` 的 lazy-FK。

**命名撞车防护（Pitfall 1，T-90-04-02）**：仓内另有同名 chat agent tool
``server/agents/tools/clarification.py:ask_clarification``（``@tool``、
``CLARIFICATION_PENDING_MARKER="ask_clarification"``），其语义完全不同——chat tool 写
``chat.ConversationIntentTrace`` 并走 LangGraph interrupt 等待对话答复，本 helper 写
``delivery.Clarification`` 轮次。两者靠**模块路径**区分
（``from services.process_runtime import ask_clarification``），**绝不**复用 / import /
改动 chat tool 资产。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from delivery.models import Clarification
    from delivery.services import ClarificationService

__all__ = ["ask_clarification"]


async def ask_clarification(
    session: Any,
    questions: list[dict[str, Any]],
    *,
    origin_repo: str | None = None,
    clarification_service: ClarificationService | None = None,
) -> Clarification | None:
    """编排层主动发问：写结构化澄清轮（薄封装 ``create_round``，INV-6）。

    Args:
        session: 归属的 ``ConvergenceSession``（透传给 service，service 内 ``sync_to_async``）。
        questions: 归一后的问题列表（``{question, type, options, recommended}`` 形态，
            见 ``ClarificationService.create_round`` / ``normalize_clarification_questions``）。
        origin_repo: 可选，标注问题来源仓（CLARIFY-03 透传到容器 + 各子题）。
        clarification_service: 可选注入（测试 / 复用既有实例）；缺省构造默认实例。

    Returns:
        新建的 ``Clarification`` 轮次容器；``questions`` 为空时返回 ``None``
        （空轮守护 WR-02，避免落成永久不可作答的 pending 容器导致无限挂起）。

    本 helper **仅**薄封装 ``create_round``：不驱动 ``engine.advance``、不挂起 marker、
    不写 ``session.status``。与 chat tool ``agents/tools/clarification.py:ask_clarification``
    同名但语义不同（见模块 docstring），靠模块路径区分，绝不复用 chat 资产。
    """
    # 函数内 lazy import 规避 import 环（process_runtime barrel → delivery.services）。
    from delivery.services import ClarificationService

    svc = clarification_service or ClarificationService()
    return await svc.create_round(session, questions, origin_repo=origin_repo)
