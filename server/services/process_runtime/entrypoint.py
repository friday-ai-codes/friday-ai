"""process_runtime.entrypoint —— 多入口共用的薄编排 helper（Chassis v2 · P2）。

抽出工作流节点 / chat 工具 / MCP delegate 共用的「建 ConvergenceSession + 构建 ProcessEngine」
薄抽象（落「底层 engine 复用、不造两套」）：

- ``start_orchestration``：薄包 ``ConvergenceSessionService.create_session``，按 technical_plan
  process 的 ``stage_state`` 形态建 ``ConvergenceSession``（initial_stage 由注册定义决定）。
- ``build_orchestration_engine``：注入 technical_plan 的真实 adapters（router/recall/research/
  merge/clarify）构造 ``ProcessEngine``，多入口共用同一 engine 构造（同一 engine、同一 stage 图）。

helper **不驱动** ``engine.advance``——驱动是入口私有（工作流走 waiting_event、chat 走 interrupt /
fire-and-forget）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from delivery.models import ConvergenceSession
    from services.process_runtime.engine import ProcessEngine

__all__ = ["start_orchestration", "build_orchestration_engine"]


def _no_clarify(session: Any) -> tuple[bool, str, list]:
    """no-clarify policy（MCP 单次同步入口注入）：恒判不需澄清，编排直通调研。"""
    return False, "", []


async def start_orchestration(
    entrypoint: str,
    requirement_text: str,
    *,
    work_item: Any = None,
    created_by: Any = None,
    include_repos: list[str] | None = None,
    conversation_id: Any = None,
    node_execution_id: Any = None,
    initiated_by_user_id: str = "",
) -> ConvergenceSession:
    """按 technical_plan process 的 stage_state 形态建 ``ConvergenceSession``（多入口共用）。

    ``entrypoint`` 合法性（workflow|chat|mcp|webhook|tool_invoke）由 create_session 既有校验。
    INV-2：chat 入口传 ``work_item=None`` 即「自然语言需求」显式标记。
    """
    from delivery.services import ConvergenceSessionService

    return await ConvergenceSessionService().create_session(
        "technical_plan",
        entrypoint,
        work_item=work_item,
        stage_state={
            "decomposition": {
                "requirement_text": requirement_text,
                "include_repos": include_repos or [],
            }
        },
        created_by=created_by,
        conversation_id=conversation_id,
        node_execution_id=node_execution_id,
        initiated_by_user_id=initiated_by_user_id,
    )


def build_orchestration_engine(
    *,
    session_service: Any = None,
    node_execution_id: str = "",
    skip_clarification: bool = False,
) -> ProcessEngine:
    """注入 technical_plan 真实 adapters 构造 ``ProcessEngine``（多入口共用同一构造）。

    ``node_execution_id`` 仅工作流入口传（调研容器回调 resume 钥匙）；``skip_clarification``
    为 True 时注入 no-clarify policy（MCP 单次同步入口 best-effort 直推、不发交互澄清）。
    """
    from delivery.services import ConvergenceSessionService
    from services.process_runtime import (
        ArchitectMergeAdapter,
        ClarifyAdapter,
        DeliveryKnowledgeRecallAdapter,
        ProcessEngine,
        RepoRouterV2Adapter,
        ResearchDispatchAdapter,
    )

    clarify = ClarifyAdapter(policy=_no_clarify) if skip_clarification else ClarifyAdapter()
    deps = SimpleNamespace(
        router=RepoRouterV2Adapter(),
        recall=DeliveryKnowledgeRecallAdapter(),
        research=ResearchDispatchAdapter(node_execution_id=node_execution_id),
        merge=ArchitectMergeAdapter(),
        clarify=clarify,
    )
    return ProcessEngine(
        session_service=session_service or ConvergenceSessionService(),
        deps=deps,
    )
