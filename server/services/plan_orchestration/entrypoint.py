"""plan_orchestration.entrypoint —— 两入口共用的薄编排 helper（ENTRY-02）。

抽出 Phase 41 工作流节点与 Phase 42 chat 工具共用的「建 session + 构建 engine」薄抽象，
落「底层 engine 复用、不造两套」（ENTRY-02 / SC-1）：

- ``start_orchestration``：薄包 ``PlanSessionService.create_session``，按**统一 decomposition
  形态**建 ``PlanSession``。entrypoint 合法性由 create_session 既有校验（workflow|chat，否则
  ``ValueError``），helper 不重复校验。
- ``build_orchestration_engine``：注入与 Phase 41 **完全相同**的真实 adapters 构造
  ``PlanOrchestrationEngine``，工作流/chat 两入口共用同一 engine 构造（同一 engine、同一状态机）。

helper **不驱动** ``engine.advance``——驱动是入口私有（工作流走 ``waiting_event``、chat 走
interrupt / fire-and-forget），两种入口运行时不混进 helper；helper 只负责入口无关的「建会话
+ 构建 engine」。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from delivery.models import PlanSession
    from services.plan_orchestration.engine import PlanOrchestrationEngine

__all__ = ["start_orchestration", "build_orchestration_engine"]


def _no_clarify(session: Any) -> tuple[bool, str, list]:
    """no-clarify policy（Open Q1 决议 #1，MCP 单次同步入口注入）。

    MCP `create_feishu_technical_plan` 是**单次同步**入口（无 HITL resume 通路），故
    best-effort「带现有信息继续」——恒判不需澄清，使编排在 clarifying 段直通 researching，
    不发交互澄清轮。形态对齐 ``clarify_adapter.default_needs_clarification`` 返回签名
    ``(needs, question, affected_task_ids)``，可经 ``ClarifyAdapter(policy=...)`` 注入。
    """
    return False, "", []


async def start_orchestration(
    entrypoint: str,
    requirement_text: str,
    *,
    work_item: Any = None,
    created_by: Any = None,
    include_repos: list[str] | None = None,
    conversation_id: Any = None,
) -> PlanSession:
    """按统一 decomposition 形态建 ``PlanSession``（两入口共用，ENTRY-02）。

    薄包 ``PlanSessionService.create_session``：``entrypoint`` 合法性（workflow|chat）由
    create_session 既有校验（非法 ``raise ValueError``），helper 不重复校验，也不驱动 engine。
    INV-2：chat 入口传 ``work_item=None`` 即「自然语言需求」显式标记（entrypoint=chat 可追溯）。
    ``conversation_id`` 仅 chat 入口传（软引用会话，供会话列表反查 SDD spec），workflow 入口为空。
    """
    from delivery.services import PlanSessionService

    return await PlanSessionService().create_session(
        entrypoint=entrypoint,
        work_item=work_item,
        decomposition={
            "requirement_text": requirement_text,
            "include_repos": include_repos or [],
        },
        created_by=created_by,
        conversation_id=conversation_id,
    )


def build_orchestration_engine(
    *,
    session_service: Any = None,
    node_execution_id: str = "",
    skip_clarification: bool = False,
) -> PlanOrchestrationEngine:
    """注入与 Phase 41 完全相同的真实 adapters 构造 ``PlanOrchestrationEngine``（SC-1）。

    工作流/chat 两入口共用同一 engine 构造（同一 engine、同一状态机 → 入口无关一致产物）。
    ``node_execution_id`` 仅工作流入口传（CR-02 调研容器回调 resume 钥匙）；chat 入口传默认
    ``""``（chat 走既有 deep_analysis 机制 resume，不依赖 node_execution）。adapters 用函数内
    lazy import 规避 import 环（``__init__`` 在模块加载期 re-export 本模块）。

    ``skip_clarification`` 为 True 时用 ``ClarifyAdapter(policy=_no_clarify)`` 注入 no-clarify
    policy（MCP 单次同步入口 best-effort 直推、不发交互澄清，Open Q1 决议 #1）；为 False 时保持
    现状 ``ClarifyAdapter()``（工作流/chat 入口零回归）。其余 adapters 逐字不变。
    """
    from delivery.services import PlanSessionService
    from services.plan_orchestration import (
        ArchitectMergeAdapter,
        ClarifyAdapter,
        DeliveryKnowledgeRecallAdapter,
        PlanOrchestrationEngine,
        RepoRouterV2Adapter,
        ResearchDispatchAdapter,
    )

    clarify = ClarifyAdapter(policy=_no_clarify) if skip_clarification else ClarifyAdapter()
    return PlanOrchestrationEngine(
        session_service=session_service or PlanSessionService(),
        router=RepoRouterV2Adapter(),
        recall=DeliveryKnowledgeRecallAdapter(),
        research=ResearchDispatchAdapter(node_execution_id=node_execution_id),
        merge=ArchitectMergeAdapter(),
        clarify=clarify,
    )
