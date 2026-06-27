"""共享 MCP delegate 核心（UNIFY-03）——MCP 入口归一到统一编排底座。

把 MCP 工具的「方案生成」从各自确定性 seam 收口到 ``plan_orchestration`` 统一编排：
建 ``PlanSession``（entrypoint=workflow）→ ``build_orchestration_engine(skip_clarification=True)``
→ ``adrive`` 续驱到终态/挂起 → 取 canonical ``PlanVersion.content``（§7 MergedPlan）→ 终态/
挂起映射为 ``DelegateResult``。**绝不在 MCP 层重写拆分/路由/调研/融合**（只调共享 helper，落
CONTEXT「最大化复用，严禁重复造」）。

挂起态语义（Open Q1 决议）：MCP 入口注入「跳过交互澄清」policy（best-effort 用现有上下文），
编排若仍挂起 ``RESEARCHING``/``CLARIFYING``（容器在途、MCP 无 resume 通路）则返回
``status="partial"`` + ``session``（调用方据 ``session.id`` 后续经会话/工作流续推）。

**async ORM 防裸 lazy-FK**：全程用 ``current_plan_version`` 标量 / ``afirst``，绝不裸访问
``session`` 的同步 lazy-FK。观测：进出口 best-effort 埋点（category=caller、component=
mcp_tools、duration_ms、status）；编排内部 LLM/召回埋点由 plan_orchestration adapters 承担
（call_source 链路完整，无需 MCP 层重复赋值）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["DelegateResult", "delegate_plan_orchestration"]


@dataclass(frozen=True)
class DelegateResult:
    """MCP delegate 编排结果（终态/挂起统一外形）。

    - ``session``：底层 ``PlanSession``（调用方取 ``session.id`` 作 partial 续推钥匙 / 落库锚）。
    - ``status``：``completed`` | ``partial`` | ``failed``（映射自 PlanSession 终态/挂起态）。
    - ``content``：canonical §7 ``MergedPlan`` content（DONE 取 ``PlanVersion.content``；
      partial best-effort 当前版本或 ``{}``；failed 恒 ``{}``）。
    - ``plan_version_id``：canonical ``PlanVersion.id``（无则 None）。
    - ``markdown``：``render_merged_plan_markdown(content)`` 结构化渲染（复用 94-01 共享 helper）。
    """

    session: Any
    status: str
    content: dict
    plan_version_id: str | None
    markdown: str


async def _load_canonical(session: Any) -> tuple[str | None, dict, str]:
    """best-effort 取 session 当前 canonical content + 渲染 markdown（async 防裸 lazy-FK）。

    用 ``current_plan_version`` 标量 + ``afirst`` 取 ``PlanVersion``；content 非 dict 时回退
    ``{}`` / 空串（防御性，对齐 render/merged_plan fail-safe）。
    """
    from delivery.models import PlanVersion
    from services.plan_orchestration import render_merged_plan_markdown

    pv_id = str(session.current_plan_version) if session.current_plan_version else None
    if not pv_id:
        return None, {}, ""
    pv = await PlanVersion.objects.filter(id=pv_id).afirst()
    if pv is None or not isinstance(pv.content, dict):
        return pv_id, {}, ""
    return pv_id, pv.content, render_merged_plan_markdown(pv.content)


async def delegate_plan_orchestration(
    *,
    requirement_text: str,
    work_item: Any = None,
    include_repos: list[str] | None = None,
    created_by: Any = None,
) -> DelegateResult:
    """delegate 到 ``plan_orchestration`` 统一编排，产 canonical MergedPlan/PlanVersion。

    流程（仅调共享 helper，绝不在 MCP 层重写编排）：
    ``start_orchestration(entrypoint="workflow")`` → ``build_orchestration_engine(
    skip_clarification=True)`` → ``adrive_plan_session_to_pause_or_terminal`` → 终态/挂起映射。

    终态/挂起映射（mirror ``plan_research._map_terminal``）：
    - ``DONE`` → ``status="completed"``，取 ``PlanVersion.content`` + 渲染 markdown。
    - ``RESEARCHING``/``CLARIFYING``（仍挂起，MCP 无 resume 通路）→ ``status="partial"``，
      best-effort 当前 canonical content（通常 {}）+ ``session`` 供续推。
    - ``FAILED`` → ``status="failed"``，content={}。
    """
    from delivery.models import PlanSessionStatus
    from services.plan_orchestration import (
        adrive_plan_session_to_pause_or_terminal,
        build_orchestration_engine,
        start_orchestration,
    )

    started_at = time.perf_counter()
    try:
        logger.info(
            "mcp_plan_delegate_started",
            category="caller",
            component="mcp_tools",
            include_repo_count=len(include_repos or []),
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
        pass

    session = await start_orchestration(
        entrypoint="workflow",
        requirement_text=requirement_text,
        work_item=work_item,
        created_by=created_by,
        include_repos=include_repos,
    )
    engine = build_orchestration_engine(skip_clarification=True)
    session = await adrive_plan_session_to_pause_or_terminal(engine, session)

    if session.status == PlanSessionStatus.DONE:
        pv_id, content, markdown = await _load_canonical(session)
        result = DelegateResult(
            session=session,
            status="completed",
            content=content,
            plan_version_id=pv_id,
            markdown=markdown,
        )
    elif session.status == PlanSessionStatus.FAILED:
        result = DelegateResult(
            session=session,
            status="failed",
            content={},
            plan_version_id=None,
            markdown="",
        )
    else:
        # RESEARCHING / CLARIFYING 仍挂起（容器在途 / MCP 无 resume 通路）→ partial best-effort。
        pv_id, content, markdown = await _load_canonical(session)
        result = DelegateResult(
            session=session,
            status="partial",
            content=content,
            plan_version_id=pv_id,
            markdown=markdown,
        )

    try:
        duration_ms = max(int((time.perf_counter() - started_at) * 1000), 0)
        logger.info(
            "mcp_plan_delegate_completed",
            category="caller",
            component="mcp_tools",
            duration_ms=duration_ms,
            status=result.status,
            session_id=str(session.id),
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
        pass

    return result
