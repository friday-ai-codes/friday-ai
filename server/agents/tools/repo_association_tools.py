"""业务↔仓库关联 AI 会话工具（REPO-01，88-04）。

``associate_repos``：AI 会话可调的「feature list → 候选关联仓库」工具，薄委托
:class:`RepoAssociationService`——与工作流节点 ``RepoAssociationNode`` 共用同一服务
（单一编排收口 INV-6，绝不两套选仓实现）。COMBINED 选仓（语义 hybrid + 活跃度 facet 降权 +
LLM 树推理），候选落 ``RepoAssociation``（proposed 态），返回候选摘要供 Agent 引导用户确认。

``space_id`` 由 MCP 适配层注入（与 ``split_feature_list_to_boards`` 同范式，LLM 不可见上下文
注入空间归属）；``initiated_by_user_id`` 透传归因（缺记 system）。
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.tools.base import ToolResult, tool
from initiatives.services.repo_association_service import RepoAssociationService
from projects.models import Space

logger = structlog.get_logger(__name__)

_COMPONENT = "repo_association"


@tool(
    name="associate_repos",
    description=(
        "基于 feature list（或 Phase 87 拆分结果）智能匹配业务最可能关联的候选仓库："
        "在空间已关联仓库范围内做语义相关度 + 仓库活跃度综合选仓，候选落库（proposed）"
        "并返回候选摘要（名/置信度/相关度/命中理由）供引导用户确认。"
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "space_id": {
                "type": "string",
                "description": "Friday 空间（Space）ID，用于限定候选仓范围与关联项目",
            },
            "features": {
                "type": "array",
                "description": (
                    "feature 列表，每项含 name（必）/ description / module（可选）；"
                    "可直接引用 Phase 87 拆分结果的 features_flat"
                ),
                "items": {"type": "object"},
            },
            "extra_instruction": {
                "type": "string",
                "description": "额外筛选/澄清要求（如只看后端仓 / 排除某仓），可选",
            },
        },
        "required": ["space_id", "features"],
    },
)
async def associate_repos(
    space_id: str,
    features: list[dict[str, Any]] | None = None,
    extra_instruction: str | None = None,
    initiated_by_user_id: Any = None,
) -> ToolResult:
    """feature list → 候选关联仓库（委托 RepoAssociationService，与工作流节点共用）。

    Args:
        space_id: Friday 空间 ID。
        features: feature 扁平列表（name/description/module）。
        extra_instruction: 额外筛选/澄清要求（可选，作 refine 约束）。
        initiated_by_user_id: 触发用户 id（审计/可观测绑定；缺记 system）。

    Returns:
        ToolResult：成功时 ``output.data`` 含 candidates/router_version/auto_selected。
    """
    log = logger.bind(space_id=space_id)
    flat = list(features or [])
    if not flat:
        return ToolResult(success=False, error="未提供任何 feature（features 为空）")

    try:
        space = await Space.objects.aget(id=space_id)
    except Space.DoesNotExist:
        log.warning("space_not_found", component=_COMPONENT, category="caller")
        return ToolResult(success=False, error=f"空间不存在: {space_id}")

    try:
        service = RepoAssociationService()
        instruction = (extra_instruction or "").strip()
        # 有额外澄清要求走 refine（并进 query 重 route），否则首发 propose；二者共用 service。
        if instruction:
            result = await service.refine(
                space=space,
                features_flat=flat,
                extra_instruction=instruction,
                initiated_by_user_id=initiated_by_user_id,
            )
        else:
            result = await service.propose(
                space=space,
                features_flat=flat,
                initiated_by_user_id=initiated_by_user_id,
            )
    except Exception as e:  # noqa: BLE001 — 选仓失败回 ToolResult（不抛进 Agent 循环）
        log.error(
            "associate_repos_failed",
            error_type=type(e).__name__,
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error=f"选仓失败: {e}")

    candidates = result.get("candidates") or []
    log.info(
        "associate_repos_completed",
        candidate_count=len(candidates),
        router_version=result.get("router_version"),
        component=_COMPONENT,
        category="caller",
    )
    return ToolResult(
        success=True,
        output={
            "data": {
                "candidates": candidates,
                "router_version": result.get("router_version"),
                "auto_selected": result.get("auto_selected"),
                "candidate_count": len(candidates),
            },
        },
    )
