"""Feishu work item integration node."""

from typing import Any

import structlog

from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger()


@register_node
class FetchWorkItemNode(BaseNode):
    """获取工作项详情节点

    从飞书获取工作项完整 JSON 数据，输出供后续节点（如变量提取）使用。
    """

    node_type = "fetch_work_item"
    display_name = "获取工作项详情"
    description = "从飞书获取工作项完整 JSON 数据"
    icon = "download"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "work_item_id": {
                "type": "string",
                "title": "工作项 ID",
                "description": "工作项 ID，支持模板变量如 {{input.work_item_id}}",
                "default": "{{input.work_item_id}}",
            },
            "work_item_type": {
                "type": "string",
                "title": "工作项类型",
                "description": "飞书工作项类型",
                "enum": ["story", "task", "bug", "epic", "feature", "__auto__", ""],
                "default": "",
            },
        },
        "required": ["work_item_id"],
    }

    inputs = [
        NodePort(
            name="default",
            label="输入",
            port_type=PortType.OBJECT,
            required=False,
            description="上游节点输出，可包含 work_item_id 和 work_item_type",
        ),
    ]

    outputs = [
        NodePort(
            name="default",
            label="工作项详情",
            port_type=PortType.OBJECT,
            description="完整的工作项 JSON 数据",
            schema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "工作项 ID"},
                    "name": {"type": "string", "description": "工作项名称"},
                    "description": {"type": "string", "description": "工作项描述"},
                    "status": {"type": "string", "description": "当前状态"},
                    "project_key": {"type": "string", "description": "飞书项目 Key"},
                    "work_item_type": {"type": "string", "description": "工作项类型"},
                    "fields": {
                        "type": "array",
                        "description": "字段列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "value": {"type": "any"},
                                "raw_value": {"type": "any"},
                            },
                        },
                    },
                    "raw_fields": {"type": "object", "description": "原始字段数据"},
                    "project": {
                        "type": "object",
                        "description": "空间信息",
                        "properties": {
                            "id": {"type": "string", "description": "空间 ID"},
                            "name": {"type": "string", "description": "空间名称"},
                        },
                    },
                    "repositories": {
                        "type": "array",
                        "description": "关联仓库列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "仓库 ID"},
                                "name": {"type": "string", "description": "仓库名称"},
                                "git_url": {"type": "string", "description": "Git URL"},
                                "default_branch": {"type": "string", "description": "默认分支"},
                            },
                        },
                    },
                },
            },
        ),
        NodePort(
            name="error",
            label="失败",
            port_type=PortType.OBJECT,
            description="获取失败时的错误信息",
        ),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """获取工作项详情，输出完整 JSON"""
        config = context.node_config

        # 解析 work_item_id
        work_item_id_str = context.render_template(config.get("work_item_id", ""))

        # 验证 work_item_id
        if not work_item_id_str:
            return NodeResult(
                status="failed",
                error="工作项 ID 不能为空",
                next_handle="error",
            )

        try:
            work_item_id = int(work_item_id_str)
        except ValueError:
            return NodeResult(
                status="failed",
                error=f"工作项 ID 格式错误: {work_item_id_str}",
                next_handle="error",
            )

        # 解析 work_item_type：优先用配置，其次按真实来源回退。
        # 注意 trigger_data 结构为 {"source", "raw_payload"}，并无顶层 work_item_type，
        # 真实类型在 raw_payload.work_item_type_key（飞书自定义类型为长 ID，如
        # 658a8bde...）。历史实现直接取 trigger_data["work_item_type"] 会恒落空回退到
        # "story"，对自定义类型工作项触发 30005 WorkItem Not Found。
        work_item_type = config.get("work_item_type", "")
        if not work_item_type or work_item_type == "__auto__":
            work_item_type = (
                context.get_input("work_item_type", "")
                or context.get_trigger_data("raw_payload.work_item_type_key", "")
                or context.get_trigger_data("work_item_type", "")
                or "story"
            )

        # 获取空间信息
        project = await self._get_project(context)
        if not project:
            return NodeResult(
                status="failed",
                error="无法获取空间信息，请确保工作流关联了空间",
                next_handle="error",
            )

        # 获取 project_key
        project_key = (
            context.get_input("project_key", "")
            or context.get_trigger_data("project_key", "")
            or project.feishu_project_key
            or ""
        )

        if not project_key:
            return NodeResult(
                status="failed",
                error="无法获取飞书项目 Key",
                next_handle="error",
            )

        try:
            # 创建飞书客户端并获取工作项
            from feishu.client import create_feishu_client_for_project

            client = create_feishu_client_for_project(project)
            work_item = await client.get_work_item(
                project_key=project_key,
                work_item_id=work_item_id,
                work_item_type=work_item_type,
            )

            # 构建完整的输出 JSON
            # 结构与飞书事件触发器的 payload 类似，方便变量提取节点使用相同的 JSONPath
            output: dict[str, Any] = {
                "id": work_item.id,
                "name": work_item.name,
                "description": work_item.description,
                "status": work_item.status,
                "project_key": project_key,
                "work_item_type": work_item.work_item_type,
                # 将 fields 数组转为更易用的结构
                "fields": self._normalize_fields(work_item.fields),
                # 保留原始 fields dict 供高级用户使用
                "raw_fields": work_item.fields,
                # 空间信息
                "project": {
                    "id": str(project.id),
                    "name": project.name,
                },
                # 仓库信息
                "repositories": await self._get_repositories(project),
            }

            logger.info(
                "work_item_fetched",
                work_item_id=work_item.id,
                work_item_name=work_item.name,
                project_key=project_key,
            )

            return NodeResult(
                status="completed",
                output=output,
                next_handle="default",
            )

        except Exception as e:
            error_msg = str(e) or f"{type(e).__name__}: 飞书 API 调用失败"
            logger.error(
                "fetch_work_item_failed",
                work_item_id=work_item_id,
                error=error_msg,
                exc_info=True,
            )
            return NodeResult(
                status="failed",
                error=error_msg,
                next_handle="error",
            )

    async def _get_project(self, context: ExecutionContext):
        """获取关联的空间"""
        if context.workflow_execution:
            from workflows.models import Workflow

            workflow = await Workflow.objects.filter(
                pk=context.workflow_execution.workflow_id
            ).afirst()
            if workflow:
                from projects.models import Space

                return await Space.objects.filter(pk=workflow.space_id).afirst()
        return None

    async def _get_repositories(self, project) -> list[dict]:
        """获取空间关联的仓库列表"""
        try:
            repos = [r async for r in project.repositories.filter(is_active=True)]
            repositories = []
            for repo in repos:
                repositories.append(
                    {
                        "id": str(repo.id),
                        "name": repo.name,
                        "git_url": repo.git_url,
                        "description": repo.overview_text,
                        "default_branch": repo.default_branch,
                    }
                )
            return repositories
        except Exception as e:
            logger.warning("get_repositories_failed", error=str(e))
            return []

    def _normalize_fields(self, fields: dict[str, Any]) -> list[dict[str, Any]]:
        """将 fields dict 转换为数组格式，与飞书事件 payload 保持一致

        输出格式: [{"key": "description", "value": "..."}, ...]
        这样可以使用相同的 JSONPath: $.fields[?(@.key=='description')].value
        """
        result = []
        for key, value in fields.items():
            parsed_value = self._parse_field_value(value)
            result.append(
                {
                    "key": key,
                    "value": parsed_value,
                    "raw_value": value,  # 保留原始值
                }
            )
        return result

    def _parse_field_value(self, value: Any) -> Any:
        """解析字段值

        飞书字段值可能是复杂结构，需要提取实际值
        """
        if value is None:
            return ""

        if isinstance(value, str):
            return value

        if isinstance(value, dict):
            # 链接类型字段
            if "link" in value:
                return value["link"]
            # 用户类型字段
            if "users" in value and isinstance(value["users"], list):
                return [u.get("name", "") for u in value["users"]]
            # 选项类型字段
            if "label" in value:
                return value["label"]
            # 富文本类型
            if "content" in value:
                return self._extract_text_from_rich(value)

        if isinstance(value, list):
            # 多选类型
            return [self._parse_field_value(v) for v in value]

        return str(value)

    def _extract_text_from_rich(self, rich_content: dict) -> str:
        """从富文本中提取纯文本"""
        content = rich_content.get("content", [])
        texts = []
        for block in content:
            if block.get("type") == "paragraph":
                for node in block.get("content", []):
                    if node.get("type") == "text":
                        texts.append(node.get("text", ""))
        return "".join(texts)
