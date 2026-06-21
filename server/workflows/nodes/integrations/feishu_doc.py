"""飞书文档生成节点。

把上游节点产出的 Markdown（如技术方案、需求整理结果等）一键生成为飞书云文档。
复用 `FeishuDocClient`（与 human_approval(mode=plan_feishu) 建方案文档同一套能力），凭证优先取项目级
飞书 App，其次回退系统级配置；目标 folder 优先取节点配置，否则取项目 feishu_doc_folder_token。
"""

from typing import Any

from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node


@register_node
class FeishuDocCreateNode(BaseNode):
    """飞书文档生成节点

    将 Markdown 内容生成为飞书云文档，输出文档链接，便于后续推送/审阅。
    """

    node_type = "feishu_doc_create"
    display_name = "飞书文档生成"
    description = "把 Markdown（技术方案等）生成为飞书云文档"
    icon = "file-text"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "title": "文档标题",
                "description": "支持模板变量，如 {{nodes.fetch_work_item.name}}",
            },
            "content": {
                "type": "string",
                "title": "文档内容 (Markdown)",
                "description": "支持模板变量，如 {{nodes.generate_plan.plan_markdown}}",
            },
            "folder_token": {
                "type": "string",
                "title": "目标文件夹 Token",
                "description": "留空则使用项目配置的飞书文档文件夹",
                "default": "",
            },
        },
        "required": ["title", "content"],
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="default", label="成功", port_type=PortType.OBJECT),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config

        title = context.render_template(config.get("title", "")).strip()
        content = context.render_template(config.get("content", ""))
        folder_token_override = context.render_template(config.get("folder_token", "")).strip()

        if not title or not content:
            return NodeResult(
                status="failed",
                error="文档标题和内容不能为空",
                next_handle="error",
            )

        project = await self._resolve_project(context)
        if project is None:
            return NodeResult(
                status="failed",
                error="无法解析所属项目，无法创建飞书文档",
                next_handle="error",
            )

        folder_token = folder_token_override or (
            getattr(project, "feishu_doc_folder_token", None) or ""
        )
        if not folder_token:
            return NodeResult(
                status="failed",
                error="未配置飞书文档文件夹 Token（节点配置或项目设置）",
                next_handle="error",
            )

        try:
            from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project

            client = await create_feishu_doc_client_for_project(project)
            result = await client.create_document(
                title=title,
                folder_token=folder_token,
                content=content,
            )
            return NodeResult(
                status="completed",
                output={
                    "success": True,
                    "document_id": result.get("document_id", ""),
                    "document_url": result.get("url", ""),
                    "title": title,
                },
                next_handle="default",
            )
        except Exception as e:
            return NodeResult(
                status="failed",
                error=f"创建飞书文档失败: {e}",
                next_handle="error",
            )

    async def _resolve_project(self, context: ExecutionContext) -> Any:
        """从工作流执行记录解析所属项目。"""
        if not context.workflow_execution:
            return None
        try:
            from workflows.models import WorkflowExecution

            we = await WorkflowExecution.objects.select_related("workflow__project").aget(
                id=context.workflow_execution.id
            )
            return we.workflow.project if we.workflow else None
        except Exception:
            return None
