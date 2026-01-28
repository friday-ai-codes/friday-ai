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
logger = structlog.get_logger
# 预设字段映射：用户友好名称 -> 飞书字段 key
PRESET_FIELD_MAPPING = {
 "description": "description", # 需求描述
 "prd_url": "field_prd_url", # 需求文档链接
 "tech_doc_url": "field_tech_doc", # 技术方案文档链接
 "priority": "priority", # 优先级
 "assignee": "assignee", # 负责人
 "due_date": "due_date", # 截止日期
 "story_point": "story_point", # 故事点
}
@register_node
class FetchWorkItemNode(BaseNode):
 """获取工作项详情节点
 从飞书获取工作项详细信息，提取指定字段，
 并可设置为全局参数供后续节点使用。
 """
 node_type = "fetch_work_item"
 display_name = "获取工作项详情"
 description = "从飞书获取工作项详情，提取关键字段"
 icon = "download"
 category = NodeCategory.INTEGRATION
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
 "enum": ["story", "task", "bug", "epic", "feature"],
 "default": "story",
 },
 "extract_fields": {
 "type": "array",
 "title": "提取字段",
 "description": "要提取的字段列表",
 "items": {
 "type": "string",
 "enum": list(PRESET_FIELD_MAPPING.keys),
 },
 "default": ["description", "prd_url", "tech_doc_url"],
 },
 "set_global_params": {
 "type": "boolean",
 "title": "设置为全局参数",
 "description": "将提取的字段设置为全局参数，供后续节点通过 {{global.xxx}} 引用",
 "default": True,
 },
 "include_project_info": {
 "type": "boolean",
 "title": "包含项目信息",
 "description": "在输出中包含项目 ID 和名称",
 "default": True,
 },
 "include_repositories": {
 "type": "boolean",
 "title": "包含仓库信息",
 "description": "获取并包含项目关联的代码仓库列表",
 "default": True,
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
 description="上游节点输出，可包含 work_item_id",
 ),
 ]
 outputs = [
 NodePort(
 name="default",
 label="工作项详情",
 port_type=PortType.OBJECT,
 description="包含工作项信息和提取的字段",
 ),
 NodePort(
 name="error",
 label="失败",
 port_type=PortType.OBJECT,
 description="获取失败时的错误信息",
 ),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """获取工作项详情并提取字段"""
 config = context.node_config
 # 解析配置
 work_item_id_str = context.render_template(config.get("work_item_id", ""))
 work_item_type = config.get("work_item_type", "story")
 extract_fields = config.get("extract_fields", ["description", "prd_url", "tech_doc_url"])
 set_global_params = config.get("set_global_params", True)
 include_project_info = config.get("include_project_info", True)
 include_repositories = config.get("include_repositories", True)
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
 # 获取项目信息
 project = await self._get_project(context)
 if not project:
 return NodeResult(
 status="failed",
 error="无法获取项目信息，请确保工作流关联了项目",
 next_handle="error",
 )
 project_key = context.get_input("project_key", "") or context.get_trigger_data("project_key", "")
 if not project_key:
 project_key = project.feishu_project_key or ""
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
 # 构建输出
 output: dict[str, Any] = {
 "work_item_id": work_item.id,
 "work_item_name": work_item.name,
 "work_item_type": work_item.work_item_type,
 "status": work_item.status,
 "project_key": project_key,
 }
 # 提取预设字段
 extracted_fields: dict[str, Any] = {}
 for field_name in extract_fields:
 feishu_field_key = PRESET_FIELD_MAPPING.get(field_name, field_name)
 if field_name == "description":
 # 描述已经在 work_item.description 中解析
 extracted_fields[field_name] = work_item.description
 else:
 # 从 fields 字典中获取
 field_value = work_item.fields.get(feishu_field_key)
 extracted_fields[field_name] = self._parse_field_value(field_value)
 output["extracted_fields"] = extracted_fields
 output.update(extracted_fields) # 也在顶层输出
 # 包含项目信息
 if include_project_info:
 output["project_id"] = str(project.id)
 output["project_name"] = project.name
 # 获取仓库信息
 if include_repositories:
 repositories = await self._get_repositories(project)
 output["repositories"] = repositories
 # 设置全局参数
 if set_global_params:
 global_params = {
 "work_item_id": work_item.id,
 "work_item_name": work_item.name,
 "work_item_type": work_item.work_item_type,
 "project_key": project_key,
 }
 global_params.update(extracted_fields)
 if include_project_info:
 global_params["project_id"] = str(project.id)
 global_params["project_name"] = project.name
 if include_repositories:
 global_params["repositories"] = repositories
 context.update_global_params(global_params)
 logger.info(
 "work_item_fetched",
 work_item_id=work_item.id,
 work_item_name=work_item.name,
 extracted_fields=list(extracted_fields.keys),
 )
 return NodeResult(
 status="completed",
 output=output,
 next_handle="default",
 )
 except Exception as e:
 logger.error(
 "fetch_work_item_failed",
 work_item_id=work_item_id,
 error=str(e),
 )
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 async def _get_project(self, context: ExecutionContext):
 """获取关联的项目"""
 # 从 workflow_execution 获取 workflow，再获取 project
 if context.workflow_execution:
 workflow = context.workflow_execution.workflow
 if workflow:
 return workflow.project
 return None
 async def _get_repositories(self, project) -> list[dict]:
 """获取项目关联的仓库列表"""
 try:
 repositories =
 for repo in project.repositories.filter(is_active=True):
 repositories.append({
 "id": str(repo.id),
 "name": repo.name,
 "git_url": repo.git_url,
 "description": repo.description or "",
 "default_branch": repo.default_branch,
 })
 return repositories
 except Exception as e:
 logger.warning("get_repositories_failed", error=str(e))
 return
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
 content = rich_content.get("content", )
 texts =
 for block in content:
 if block.get("type") == "paragraph":
 for node in block.get("content", ):
 if node.get("type") == "text":
 texts.append(node.get("text", ""))
 return "".join(texts)
