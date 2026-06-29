"""看板拆分 AI 会话工具（BOARD-01，87-03）。

``split_feature_list_to_boards``：AI 会话可调的「feature list → 子看板」工具，委托
:class:`BoardSplitService`——与工作流节点 ``BoardSplitNode`` 共用同一服务（单一编排收口，
绝不两套实现）。多源输入（飞书链接 / 粘贴文本 / 上传文件正文），逐 feature 建子看板 +
关联项目跟踪 + 落 link + 父子降级。
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.tools.base import ToolResult, tool
from initiatives.services.board_split_service import BoardSplitService
from projects.models import Space

logger = structlog.get_logger(__name__)


async def _aresolve_bound_project(conversation_id: str | None) -> Any:
    """由会话反查 bound_project（Project 实例）；未绑/不存在返回 None（fail-soft）。"""
    if not conversation_id:
        return None
    try:
        from chat.models import Conversation
        from initiatives.models import Project

        row = await (
            Conversation.objects.filter(id=conversation_id)
            .values("bound_project_id")
            .afirst()
        )
        if not row or not row.get("bound_project_id"):
            return None
        return await Project.objects.filter(id=row["bound_project_id"]).afirst()
    except Exception:  # noqa: BLE001 — 反查失败回退按 space 解析，不阻断拆分
        return None


@tool(
    name="split_feature_list_to_boards",
    description=(
        "把 feature list 拆成飞书子看板：每个功能点建一个子看板工作项、关联项目跟踪，"
        "父子关系类型缺失时自动降级（建看板但不挂父子）。支持飞书文档链接 / 粘贴文本 / "
        "上传文件正文三种输入源。"
    ),
    category="FEISHU",
    parameters={
        "type": "object",
        "properties": {
            "space_id": {
                "type": "string",
                "description": "Friday 空间（Space）ID，用于获取飞书凭证与关联项目",
            },
            "feature_list_url": {
                "type": "string",
                "description": "feature list 飞书文档链接/ID（可选）",
            },
            "feature_list_text": {
                "type": "string",
                "description": "粘贴的 feature list 文本（可选）",
            },
            "uploaded_text": {
                "type": "string",
                "description": "上传文件（md）正文（可选）",
            },
            "work_item_type": {
                "type": "string",
                "description": "子看板工作项类型",
                "default": "story",
            },
            "conversation_id": {
                "type": "string",
                "description": "会话 UUID (auto-injected)",
            },
        },
        "required": ["space_id", "conversation_id"],
    },
)
async def split_feature_list_to_boards(
    space_id: str,
    conversation_id: str,
    feature_list_url: str | None = None,
    feature_list_text: str | None = None,
    uploaded_text: str | None = None,
    work_item_type: str = "story",
) -> ToolResult:
    """feature list → 子看板（委托 BoardSplitService，与工作流节点共用）。

    Args:
        space_id: Friday 空间 ID。
        feature_list_url: 飞书文档链接/ID（可选）。
        feature_list_text: 粘贴文本（可选）。
        uploaded_text: 上传文件正文（可选）。
        work_item_type: 子看板工作项类型（默认 story）。

    Returns:
        ToolResult：成功时 ``output.data`` 含 created/degraded_parent_child/hint/feature_count。
    """
    log = logger.bind(space_id=space_id, work_item_type=work_item_type)

    if not (feature_list_url or feature_list_text or uploaded_text):
        return ToolResult(
            success=False,
            error="未提供任何 feature list 输入源（飞书链接 / 粘贴文本 / 上传文件）",
        )

    try:
        space = await Space.objects.aget(id=space_id)
    except Space.DoesNotExist:
        log.warning("space_not_found")
        return ToolResult(success=False, error=f"空间不存在: {space_id}")

    # #5 Part A：优先把拆出的工作项关联到「当前对话所绑定的项目」（而非按 space 猜首个项目）。
    bound_project = await _aresolve_bound_project(conversation_id)

    try:
        service = BoardSplitService()
        proposal = await service.propose_split(
            space=space,
            uploaded_text=uploaded_text,
            feishu_url=feature_list_url,
            pasted_text=feature_list_text,
        )
        result = await service.create_boards(
            space=space,
            proposal=proposal,
            work_item_type=work_item_type,
            project=bound_project,
        )
    except Exception as e:
        log.error("split_feature_list_to_boards_failed", error=str(e))
        return ToolResult(success=False, error=f"看板拆分失败: {e}")

    log.info(
        "split_feature_list_to_boards_completed",
        created_count=len(result["created"]),
        failed_count=len(result["failures"]),
        degraded_parent_child=result["degraded_parent_child"],
    )
    return ToolResult(
        success=True,
        output={
            "data": {
                "created": result["created"],
                "failures": result["failures"],
                "degraded_parent_child": result["degraded_parent_child"],
                "hint": result["hint"],
                "feature_count": result["feature_count"],
            },
        },
    )
