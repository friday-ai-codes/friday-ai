"""
Feishu work item operation tools for the Agent.

Provides tools for querying work item details, listing related items,
and adding comments as AI Agent identity.
"""

from datetime import datetime, timezone

import structlog

from agents.tools.base import ToolResult, tool
from projects.models import Space
from services.feishu import create_feishu_client_for_project

logger = structlog.get_logger(__name__)


@tool(
    name="get_work_item_detail",
    description="获取飞书工作项的完整详情，包括自定义字段和描述。",
    category="FEISHU",
    parameters={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "Friday 项目 ID，用于获取飞书凭证",
            },
            "work_item_id": {
                "type": "integer",
                "description": "飞书工作项 ID",
            },
            "work_item_type": {
                "type": "string",
                "description": "工作项类型（story、task、bug 等）",
                "default": "story",
            },
        },
        "required": ["project_id", "work_item_id"],
    },
)
async def get_work_item_detail(
    project_id: str,
    work_item_id: int,
    work_item_type: str = "story",
) -> ToolResult:
    """获取飞书工作项的完整详情。

    Args:
        project_id: Friday 项目 ID
        work_item_id: 飞书工作项 ID
        work_item_type: 工作项类型

    Returns:
        ToolResult with work item details including custom fields
    """
    log = logger.bind(
        project_id=project_id,
        work_item_id=work_item_id,
        work_item_type=work_item_type,
    )

    try:
        # Get project from database
        project = await Space.objects.aget(id=project_id)
    except Space.DoesNotExist:
        log.warning("project_not_found")
        return ToolResult(
            success=False,
            error=f"项目不存在: {project_id}",
        )

    try:
        client = create_feishu_client_for_project(project)
    except ValueError as e:
        log.warning("feishu_not_configured", error=str(e))
        return ToolResult(
            success=False,
            error=str(e),
        )

    try:
        work_item = await client.get_work_item(
            project_key=project.feishu_project_key or "",
            work_item_id=work_item_id,
            work_item_type=work_item_type,
        )

        log.info("work_item_fetched", work_item_name=work_item.name)

        return ToolResult(
            success=True,
            output={
                "data": {
                    "work_item": {
                        "id": work_item.id,
                        "name": work_item.name,
                        "description": work_item.description,
                        "status": work_item.status,
                        "type": work_item.work_item_type,
                        "fields": work_item.fields,
                    },
                },
                "metadata": {
                    "project_key": work_item.project_key,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        )
    except Exception as e:
        log.error("get_work_item_failed", error=str(e))
        return ToolResult(
            success=False,
            error=f"获取工作项失败: {e}",
        )


@tool(
    name="list_related_work_items",
    description="获取飞书工作项的所有关联项，包括父级、子级、阻塞项等。",
    category="FEISHU",
    parameters={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "Friday 项目 ID",
            },
            "work_item_id": {
                "type": "integer",
                "description": "飞书工作项 ID",
            },
            "work_item_type": {
                "type": "string",
                "description": "工作项类型（story、task、bug 等）",
                "default": "story",
            },
        },
        "required": ["project_id", "work_item_id"],
    },
)
async def list_related_work_items(
    project_id: str,
    work_item_id: int,
    work_item_type: str = "story",
) -> ToolResult:
    """获取工作项的所有关联关系。

    Args:
        project_id: Friday 项目 ID
        work_item_id: 飞书工作项 ID
        work_item_type: 工作项类型

    Returns:
        ToolResult with all relation types (parent, child, blocker, related)
    """
    log = logger.bind(
        project_id=project_id,
        work_item_id=work_item_id,
        work_item_type=work_item_type,
    )

    try:
        project = await Space.objects.aget(id=project_id)
    except Space.DoesNotExist:
        log.warning("project_not_found")
        return ToolResult(
            success=False,
            error=f"项目不存在: {project_id}",
        )

    try:
        client = create_feishu_client_for_project(project)
    except ValueError as e:
        log.warning("feishu_not_configured", error=str(e))
        return ToolResult(
            success=False,
            error=str(e),
        )

    try:
        relations = await client.get_work_item_relations(
            project_key=project.feishu_project_key or "",
            work_item_id=work_item_id,
            work_item_type=work_item_type,
        )

        # Extract unique relation types
        relation_types = list(set(r["relation_type"] for r in relations if r.get("relation_type")))

        log.info("relations_fetched", count=len(relations), types=relation_types)

        return ToolResult(
            success=True,
            output={
                "data": {
                    "work_item_id": work_item_id,
                    "relations": relations,
                },
                "metadata": {
                    "count": len(relations),
                    "relation_types": relation_types,
                },
            },
        )
    except Exception as e:
        log.error("get_relations_failed", error=str(e))
        return ToolResult(
            success=False,
            error=f"获取关联工作项失败: {e}",
        )


@tool(
    name="add_work_item_comment",
    description="向飞书工作项添加评论，以 AI Agent 身份发送。支持 Markdown 格式。",
    category="FEISHU",
    parameters={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "Friday 项目 ID",
            },
            "work_item_id": {
                "type": "integer",
                "description": "飞书工作项 ID",
            },
            "work_item_type": {
                "type": "string",
                "description": "工作项类型（story、task、bug 等）",
                "default": "story",
            },
            "content": {
                "type": "string",
                "description": "评论内容（支持 Markdown 格式）",
            },
            "mentions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要 @ 的用户 Key 列表（可选）",
            },
        },
        "required": ["project_id", "work_item_id", "content"],
    },
)
async def add_work_item_comment(
    project_id: str,
    work_item_id: int,
    content: str,
    work_item_type: str = "story",
    mentions: list[str] | None = None,
) -> ToolResult:
    """向工作项添加评论。

    Args:
        project_id: Friday 项目 ID
        work_item_id: 飞书工作项 ID
        content: 评论内容（Markdown 格式）
        work_item_type: 工作项类型
        mentions: 要 @ 的用户 Key 列表

    Returns:
        ToolResult with comment creation status
    """
    log = logger.bind(
        project_id=project_id,
        work_item_id=work_item_id,
        work_item_type=work_item_type,
        content_length=len(content),
        mentions=mentions,
    )

    try:
        project = await Space.objects.aget(id=project_id)
    except Space.DoesNotExist:
        log.warning("project_not_found")
        return ToolResult(
            success=False,
            error=f"项目不存在: {project_id}",
        )

    try:
        client = create_feishu_client_for_project(project)
    except ValueError as e:
        log.warning("feishu_not_configured", error=str(e))
        return ToolResult(
            success=False,
            error=str(e),
        )

    # Build comment content with mentions if provided
    final_content = content
    if mentions:
        # Prepend mentions to content
        mention_text = " ".join(f"@{user_key}" for user_key in mentions)
        final_content = f"{mention_text} {content}"

    try:
        success = await client.add_comment(
            project_key=project.feishu_project_key or "",
            work_item_id=work_item_id,
            work_item_type=work_item_type,
            content=final_content,
        )

        if success:
            log.info("comment_added")
            return ToolResult(
                success=True,
                output={
                    "data": {
                        "work_item_id": work_item_id,
                        "commented": True,
                    },
                    "metadata": {
                        "commented_at": datetime.now(timezone.utc).isoformat(),
                        "identity": "AI Agent",
                    },
                },
            )
        else:
            log.warning("comment_add_failed")
            return ToolResult(
                success=False,
                error="添加评论失败",
            )
    except Exception as e:
        log.error("add_comment_failed", error=str(e))
        return ToolResult(
            success=False,
            error=f"添加评论失败: {e}",
        )
