"""Fetch space information node."""

import structlog
from jsonpath_ng.exceptions import JsonPathParserError
from jsonpath_ng.ext import parse

from projects.models import Space
from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger(__name__)


@register_node
class FetchSpaceInfoNode(BaseNode):
    """获取空间信息节点

    根据空间 ID 或飞书项目 Key 查询空间信息，
    可选择性获取仓库列表、飞书配置、Claude 配置等。
    """

    node_type = "fetch_space_info"
    display_name = "获取空间信息"
    description = "根据空间标识获取空间配置信息，包括仓库、飞书配置等"
    icon = "folder-search"
    category = NodeCategory.ACTION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "space_identifier": {
                "type": "string",
                "title": "空间标识",
                "description": "空间 ID 或飞书项目 Key，支持模板变量",
            },
            "identifier_type": {
                "type": "string",
                "title": "标识类型",
                "enum": ["auto", "id", "feishu_project_key"],
                "default": "auto",
                "description": "auto 会自动检测，优先尝试 UUID",
            },
            "include_repositories": {
                "type": "boolean",
                "title": "获取仓库列表",
                "description": "包含空间关联的所有代码仓库",
                "default": True,
            },
            "include_feishu_config": {
                "type": "boolean",
                "title": "获取飞书配置",
                "description": "包含飞书集成配置信息",
                "default": False,
            },
            "include_claude_config": {
                "type": "boolean",
                "title": "获取 Claude 配置",
                "description": "包含 Claude API 配置信息",
                "default": False,
            },
            "include_webhook_token": {
                "type": "boolean",
                "title": "获取 Webhook Token",
                "description": "包含飞书 Webhook Token",
                "default": False,
            },
        },
        "required": ["space_identifier"],
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT, required=False)]
    outputs = [
        NodePort(
            name="default",
            label="空间信息",
            port_type=PortType.OBJECT,
            schema={
                "type": "object",
                "properties": {
                    "space_id": {"type": "string", "description": "空间 ID"},
                    "space_name": {"type": "string", "description": "空间名称"},
                    "description": {"type": "string", "description": "空间描述"},
                    "feishu_project_key": {"type": "string", "description": "飞书项目 Key"},
                    "created_at": {"type": "string", "description": "创建时间"},
                    "updated_at": {"type": "string", "description": "更新时间"},
                    "repositories": {
                        "type": "array",
                        "description": "仓库列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "仓库 ID"},
                                "name": {"type": "string", "description": "仓库名称"},
                                "git_url": {"type": "string", "description": "Git URL"},
                                "git_platform": {"type": "string", "description": "Git 平台"},
                                "default_branch": {"type": "string", "description": "默认分支"},
                                "description": {"type": "string", "description": "仓库描述"},
                            },
                        },
                    },
                    "repository_count": {"type": "integer", "description": "仓库数量"},
                    "primary_repository_id": {"type": "string", "description": "主仓库 ID"},
                    "feishu_config": {
                        "type": "object",
                        "description": "飞书配置",
                        "properties": {
                            "project_key": {"type": "string"},
                            "plugin_id": {"type": "string"},
                            "user_key": {"type": "string"},
                            "has_plugin_secret": {"type": "boolean"},
                            "is_configured": {"type": "boolean"},
                        },
                    },
                    "claude_config": {
                        "type": "object",
                        "description": "Claude 配置",
                        "properties": {
                            "has_api_key": {"type": "boolean"},
                            "base_url": {"type": "string"},
                            "is_configured": {"type": "boolean"},
                        },
                    },
                    "webhook_token": {"type": "string", "description": "Webhook Token"},
                },
            },
        ),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config

        # 获取原始配置值
        raw_identifier = config.get("space_identifier", "")
        identifier_type = config.get("identifier_type", "auto")
        include_repositories = config.get("include_repositories", True)
        include_feishu_config = config.get("include_feishu_config", False)
        include_claude_config = config.get("include_claude_config", False)
        include_webhook_token = config.get("include_webhook_token", False)

        # 解析空间标识：支持模板变量 {{}} 和 JSONPath $
        space_identifier = self._resolve_value(raw_identifier, context)

        if not space_identifier:
            return NodeResult(
                status="failed",
                error="空间标识不能为空",
                next_handle="error",
            )

        logger.info(
            "fetch_space_info_start",
            space_identifier=space_identifier,
            identifier_type=identifier_type,
        )

        try:
            # 查找空间
            space = await self._find_space(space_identifier, identifier_type)

            if not space:
                return NodeResult(
                    status="failed",
                    error=f"未找到空间: {space_identifier}",
                    next_handle="error",
                )

            # 构建输出
            output = await self._build_output(
                space,
                include_repositories=include_repositories,
                include_feishu_config=include_feishu_config,
                include_claude_config=include_claude_config,
                include_webhook_token=include_webhook_token,
            )

            # 注册仓库列表为全局变量，供下游节点使用
            if include_repositories and "repositories" in output:
                await context.aset_global_variable(
                    key="repositories",
                    name="空间仓库列表",
                    value=output["repositories"],
                    desc="空间关联的代码仓库对象列表",
                    required=False,
                )

            logger.info(
                "fetch_space_info_completed",
                space_id=str(space.id),
                space_name=space.name,
            )

            return NodeResult(
                status="completed",
                output=output,
                next_handle="default",
            )

        except Exception as e:
            logger.error("fetch_space_info_failed", error=str(e))
            return NodeResult(
                status="failed",
                error=f"获取空间信息失败: {e!s}",
                next_handle="error",
            )

    async def _find_space(self, identifier: str, identifier_type: str) -> Space | None:
        """查找空间"""
        import uuid as uuid_mod

        if identifier_type == "auto":
            # 先尝试 UUID
            try:
                uuid_mod.UUID(identifier)
                space = await Space.objects.filter(id=identifier).afirst()
                if space:
                    return space
            except ValueError:
                pass
            # 再尝试飞书项目 Key
            return await Space.objects.filter(feishu_project_key=identifier).afirst()

        elif identifier_type == "id":
            return await Space.objects.filter(id=identifier).afirst()

        elif identifier_type == "feishu_project_key":
            return await Space.objects.filter(feishu_project_key=identifier).afirst()

        return None

    async def _build_output(
        self,
        space: Space,
        include_repositories: bool,
        include_feishu_config: bool,
        include_claude_config: bool,
        include_webhook_token: bool,
    ) -> dict:
        """构建输出数据"""
        output: dict = {
            "space_id": str(space.id),
            "space_name": space.name,
            "description": space.description or "",
            "feishu_project_key": space.feishu_project_key or "",
            "created_at": space.created_at.isoformat() if space.created_at else None,
            "updated_at": space.updated_at.isoformat() if space.updated_at else None,
        }

        # 仓库列表
        if include_repositories:
            repositories = []
            async for repo in space.repositories.filter(is_deleted=False):
                repo_info = {
                    "id": str(repo.id),
                    "name": repo.name,
                    "git_url": repo.git_url,
                    "git_platform": repo.git_platform,
                    "default_branch": repo.default_branch,
                    "description": repo.overview_text,
                    "index_status": getattr(repo, "index_status", None),
                }
                repositories.append(repo_info)
            output["repositories"] = repositories
            output["repository_count"] = len(repositories)
            # 便捷字段：第一个仓库的 ID（常用场景）
            if repositories:
                output["primary_repository_id"] = repositories[0]["id"]

        # 飞书配置
        if include_feishu_config:
            output["feishu_config"] = {
                "project_key": space.feishu_project_key or "",
                "plugin_id": space.feishu_plugin_id or "",
                "user_key": space.feishu_user_key or "",
                "has_plugin_secret": bool(space.feishu_plugin_secret_encrypted),
                "is_configured": space.has_feishu_config(),
            }

        # implementation（contract/contract）：Space.claude_* 字段硬删；
        # include_claude_config flag 保留为向后兼容 stub（始终返回未配置状态）。
        # 调用方应改用 include_provider_config（implementation+ 引入新字段读 ProviderCredential）。
        if include_claude_config:
            output["claude_config"] = {
                "has_api_key": False,
                "base_url": "",
                "is_configured": False,
            }

        # Webhook Token
        if include_webhook_token:
            output["webhook_token"] = space.feishu_webhook_token or ""

        return output

    def _resolve_value(self, raw_value: str, context: ExecutionContext) -> str:
        """解析值：支持模板变量 {{}} 和 JSONPath $

        注意：此方法不涉及 DB 操作，纯 CPU 计算，可安全在 async 上下文中同步调用。

        Args:
            raw_value: 原始配置值
            context: 执行上下文

        Returns:
            解析后的字符串值
        """
        if not raw_value:
            return ""

        raw_value = raw_value.strip()

        # 1. 模板变量语法 {{...}}
        if "{{" in raw_value and "}}" in raw_value:
            return context.render_template(raw_value)

        # 2. JSONPath 语法 $...
        if raw_value.startswith("$"):
            # 获取输入数据
            input_data = context.input_data
            if not input_data:
                # 尝试从上游节点获取
                for node_id, output in context.previous_outputs.items():
                    if output:
                        input_data = output
                        break

            if not input_data:
                logger.warning("jsonpath_no_input_data", path=raw_value)
                return ""

            try:
                jsonpath_expr = parse(raw_value)
                matches = jsonpath_expr.find(input_data)
                if matches:
                    value = matches[0].value
                    # 确保返回字符串
                    return str(value) if value is not None else ""
                else:
                    logger.warning("jsonpath_no_match", path=raw_value)
                    return ""
            except JsonPathParserError as e:
                logger.error("jsonpath_parse_error", path=raw_value, error=str(e))
                return ""

        # 3. 直接返回原始值
        return raw_value
