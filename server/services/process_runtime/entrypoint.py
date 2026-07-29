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
    extra_evidence: list[dict] | None = None,
    mode: str = "",
    feature_segments: list[dict] | None = None,
    feature_meta: dict | None = None,
) -> ConvergenceSession:
    """按 technical_plan process 的 stage_state 形态建 ``ConvergenceSession``（多入口共用）。

    ``entrypoint`` 合法性（workflow|chat|mcp|webhook|tool_invoke）由 create_session 既有校验。
    INV-2：chat 入口传 ``work_item=None`` 即「自然语言需求」显式标记。
    ``extra_evidence``（UNIFY-02）：调用方补充的编排输入证据（如 repository analysis
    summary），写入 ``decomposition.extra_evidence``，merge 阶段消费；不提供则不写键
    （既有会话形态与其他入口零扰动）。

    ``mode`` / ``feature_segments`` / ``feature_meta``：feature list 入口专用。
    ``mode="feature_list"`` 开启「功能点新增/改造分类 + 强制仓库确认」链路；
    ``feature_segments`` 为 feature 树展平后的功能点列表（形如 ``{"title","module","layer"}``），
    非空时 decompose 直接采用、不再走 LLM 拆分；``feature_meta`` 存取数溯源元信息
    （``project_id`` / ``source`` 等，供后续查询做归属校验与展示）。三者均**仅在非空时写键**
    ——不提供时会话形态与既有入口逐字一致。
    """
    from delivery.services import ConvergenceSessionService

    decomposition: dict[str, Any] = {
        "requirement_text": requirement_text,
        "include_repos": include_repos or [],
    }
    if extra_evidence:
        decomposition["extra_evidence"] = extra_evidence
    if mode:
        decomposition["mode"] = mode
    if feature_segments:
        decomposition["feature_segments"] = feature_segments
    if feature_meta:
        decomposition["feature_meta"] = feature_meta

    return await ConvergenceSessionService().create_session(
        "technical_plan",
        entrypoint,
        work_item=work_item,
        stage_state={"decomposition": decomposition},
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
    force_confirm: bool = False,
) -> ProcessEngine:
    """注入 technical_plan 真实 adapters 构造 ``ProcessEngine``（多入口共用同一构造）。

    ``node_execution_id`` 仅工作流入口传（调研容器回调 resume 钥匙）；``skip_clarification``
    为 True 时注入 no-clarify policy（MCP 单次同步入口 best-effort 直推、不发交互澄清）。

    ``force_confirm``（feature list 入口）：注入确定性确认题组装器，落实「哪怕路由十分确定
    也要让用户确认关联仓库」的产品约束——组装器在 ``ClarifyAdapter`` 内**先于 policy** 执行，
    首轮必发确认题，第二轮起自动回落默认 policy（组装器按轮次短路）。与 ``skip_clarification``
    互斥——同时为真时 ``skip_clarification`` 优先（显式要求不发交互澄清的调用方不应被打断）。
    """
    from delivery.services import ConvergenceSessionService
    from services.process_runtime import (
        ArchitectMergeAdapter,
        ClarifyAdapter,
        DeliveryKnowledgeRecallAdapter,
        FeatureChangeClassifyAdapter,
        ProcessEngine,
        RepoRouterV2Adapter,
        ResearchDispatchAdapter,
    )
    from services.process_runtime.feature_confirm_questions import (
        build_feature_confirm_questions,
    )

    if skip_clarification:
        clarify = ClarifyAdapter(policy=_no_clarify)
    elif force_confirm:
        # 只注入组装器、不换 policy：组装器先于 policy 执行保证首轮必问，第二轮起组装器
        # 返回空 → 回落默认 policy（此时路由已被用户确认，通常直接放行进调研）。
        clarify = ClarifyAdapter(question_builder=build_feature_confirm_questions)
    else:
        clarify = ClarifyAdapter()
    deps = SimpleNamespace(
        router=RepoRouterV2Adapter(),
        recall=DeliveryKnowledgeRecallAdapter(),
        research=ResearchDispatchAdapter(node_execution_id=node_execution_id),
        merge=ArchitectMergeAdapter(),
        clarify=clarify,
        # classify 只在 decomposition.mode == "feature_list" 时被 stage handler 调用；
        # 其余入口穿过 classify stage 时不触碰它（见 _h_classify 的 pass-through）。
        classify=FeatureChangeClassifyAdapter(),
    )
    return ProcessEngine(
        session_service=session_service or ConvergenceSessionService(),
        deps=deps,
    )


def build_blueprint_engine(
    *, session_service: Any = None, node_execution_id: str = ""
) -> ProcessEngine:
    """注入 ``technical_blueprint`` 四个蓝图 adapter 构造 ``ProcessEngine``（Phase 112-05）。

    engine 工厂在本仓集中于本模块（与 ``resume.py`` docstring「绝不在此新建第二个 engine
    工厂」的纪律同调）：``blueprint_resume`` 缺省 engine 时 lazy import 本函数，不再造第二
    个工厂点。

    deps 属性名单与 ``builtin_processes`` 七个 ``_h_bp_*`` handler 的 ``getattr`` 取名
    **逐字一致**（``spec_gate`` / ``route`` / ``research`` / ``confirm_gate``）——名单漂移会
    让 handler 恒 pass-through，即「注册了但永远空转」的静默失败。

    ``node_execution_id`` 仅工作流入口传（调研容器回调 resume 钥匙）。两条链互不污染：
    本工厂不含 technical_plan 的 router/recall/merge/clarify/classify，
    ``build_orchestration_engine`` 也不含蓝图 adapter。
    """
    from delivery.services import ConvergenceSessionService
    from services.process_runtime.blueprint_confirm_gate import BlueprintConfirmGateAdapter
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter
    from services.process_runtime.blueprint_route import BlueprintRouteAdapter
    from services.process_runtime.blueprint_spec_gate import BlueprintSpecGateAdapter
    from services.process_runtime.engine import ProcessEngine

    deps = SimpleNamespace(
        spec_gate=BlueprintSpecGateAdapter(),
        route=BlueprintRouteAdapter(),
        research=BlueprintResearchAdapter(node_execution_id=node_execution_id),
        confirm_gate=BlueprintConfirmGateAdapter(),
    )
    return ProcessEngine(
        session_service=session_service or ConvergenceSessionService(),
        deps=deps,
    )


# 纯追加纪律（既有 __all__ 行一字不动）：新工厂追加进导出面。
__all__ += ["build_blueprint_engine"]
