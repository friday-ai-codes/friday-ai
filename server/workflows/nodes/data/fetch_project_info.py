"""Fetch project information node."""
import structlog
from asgiref.sync import sync_to_async
from jsonpath_ng.exceptions import JsonPathParserError
from jsonpath_ng.ext import parse
from projects.models import Project
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
class FetchProjectInfoNode(BaseNode):
 """获取项目信息节点
 根据项目 ID 或飞书项目 Key 查询项目信息，
 可选择性获取仓库列表、飞书配置、Claude 配置等。
 """
 node_type = "fetch_project_info"
 display_name = "获取项目信息"
 description = "根据项目标识获取项目配置信息，包括仓库、飞书配置等"
 icon = "folder-search"
 category = NodeCategory.ACTION
 config_schema = {
 "type": "object",
 "properties": {
 "project_identifier": {
 "type": "string",
 "title": "项目标识",
 "description": "项目 ID 或飞书项目 Key，支持模板变量",
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
 "description": "包含项目关联的所有代码仓库",
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
 "required": ["project_identifier"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT, required=False)]
 outputs = [
 NodePort(
 name="default",
 label="项目信息",
 port_type=PortType.OBJECT,
 schema={
 "type": "object",
 "properties": {
 "project_id": {"type": "string", "description": "项目 ID"},
 "project_name": {"type": "string", "description": "项目名称"},
 "description": {"type": "string", "description": "项目描述"},
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
 raw_identifier = config.get("project_identifier", "")
 identifier_type = config.get("identifier_type", "auto")
 include_repositories = config.get("include_repositories", True)
 include_feishu_config = config.get("include_feishu_config", False)
 include_claude_config = config.get("include_claude_config", False)
 include_webhook_token = config.get("include_webhook_token", False)
 # 解析项目标识：支持模板变量 {{}} 和 JSONPath $
 project_identifier = await self._resolve_value_async(raw_identifier, context)
 if not project_identifier:
 return NodeResult(
 status="failed",
 error="项目标识不能为空",
 next_handle="error",
 )
 logger.info(
 "fetch_project_info_start",
 project_identifier=project_identifier,
 identifier_type=identifier_type,
 )
 try:
 # 查找项目
 project = await self._find_project(project_identifier, identifier_type)
 if not project:
 return NodeResult(
 status="failed",
 error=f"未找到项目: {project_identifier}",
 next_handle="error",
 )
 # 构建输出
 output = await self._build_output(
 project,
 include_repositories=include_repositories,
 include_feishu_config=include_feishu_config,
 include_claude_config=include_claude_config,
 include_webhook_token=include_webhook_token,
 )
 # 注册仓库列表为全局变量，供下游节点使用
 if include_repositories and "repositories" in output:
 await sync_to_async(context.set_global_variable, thread_sensitive=True)(
 key="repositories",
 name="项目仓库列表",
 value=output["repositories"],
 desc="项目关联的代码仓库对象列表",
 required=False,
 )
 logger.info(
 "fetch_project_info_completed",
 project_id=str(project.id),
 project_name=project.name,
 )
 return NodeResult(
 status="completed",
 output=output,
 next_handle="default",
 )
 except Exception as e:
 logger.error("fetch_project_info_failed", error=str(e))
 return NodeResult(
 status="failed",
 error=f"获取项目信息失败: {e!s}",
 next_handle="error",
 )
 async def _find_project(self, identifier: str, identifier_type: str) -> Project | None:
 """查找项目"""
 def _query:
 # 自动检测类型
 if identifier_type == "auto":
 # 先尝试 UUID
 try:
 import uuid
 uuid.UUID(identifier)
 project = Project.objects.filter(id=identifier).first
 if project:
 return project
 except ValueError:
 pass
 # 再尝试飞书项目 Key
 return Project.objects.filter(feishu_project_key=identifier).first
 elif identifier_type == "id":
 return Project.objects.filter(id=identifier).first
 elif identifier_type == "feishu_project_key":
 return Project.objects.filter(feishu_project_key=identifier).first
 return None
 return await sync_to_async(_query, thread_sensitive=True)
 async def _build_output(
 self,
 project: Project,
 include_repositories: bool,
 include_feishu_config: bool,
 include_claude_config: bool,
 include_webhook_token: bool,
 ) -> dict:
 """构建输出数据"""
 def _build:
 output = {
 "project_id": str(project.id),
 "project_name": project.name,
 "description": project.description or "",
 "feishu_project_key": project.feishu_project_key or "",
 "created_at": project.created_at.isoformat if project.created_at else None,
 "updated_at": project.updated_at.isoformat if project.updated_at else None,
 }
 # 仓库列表
 if include_repositories:
 repositories =
 for repo in project.repositories.filter(is_deleted=False):
 repo_info = {
 "id": str(repo.id),
 "name": repo.name,
 "git_url": repo.git_url,
 "git_platform": repo.git_platform,
 "default_branch": repo.default_branch,
 "description": repo.description or "",
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
 "project_key": project.feishu_project_key or "",
 "plugin_id": project.feishu_plugin_id or "",
 "user_key": project.feishu_user_key or "",
 "has_plugin_secret": bool(project.feishu_plugin_secret_encrypted),
 "is_configured": project.has_feishu_config,
 }
 # Claude 配置
 if include_claude_config:
 output["claude_config"] = {
 "has_api_key": bool(project.claude_api_key_encrypted),
 "base_url": project.claude_base_url or "",
 "is_configured": bool(project.claude_api_key_encrypted),
 }
 # Webhook Token
 if include_webhook_token:
 output["webhook_token"] = project.feishu_webhook_token or ""
 return output
 return await sync_to_async(_build, thread_sensitive=True)
 async def _resolve_value_async(self, raw_value: str, context: ExecutionContext) -> str:
 """异步解析值：支持模板变量 {{}} 和 JSONPath $"""
 return await sync_to_async(self._resolve_value, thread_sensitive=True)(raw_value, context)
 def _resolve_value(self, raw_value: str, context: ExecutionContext) -> str:
 """解析值：支持模板变量 {{}} 和 JSONPath $
 Args:
 raw_value: 原始配置值
 context: 执行上下文
 Returns:
 解析后的字符串值
 """
 if not raw_value:
 return ""
 raw_value = raw_value.strip
 # 1. 模板变量语法 {{...}}
 if "{{" in raw_value and "}}" in raw_value:
 return context.render_template(raw_value)
 # 2. JSONPath 语法 $...
 if raw_value.startswith("$"):
 # 获取输入数据
 input_data = context.input_data
 if not input_data:
 # 尝试从上游节点获取
 for node_id, output in context.previous_outputs.items:
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
