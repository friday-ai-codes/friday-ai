"""AI Technical Plan Node for generating structured technical plans.
This node generates technical plans from requirements using LLM,
validates them against TechnicalPlanSchema, and writes back to Feishu.
"""
import json
import os
from typing import Any
import httpx
import structlog
from feishu.client import FeishuAPIError, create_feishu_client_for_project
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
from workflows.nodes.registry import register_node
from workflows.schemas.technical_plan import (
 TECHNICAL_PLAN_JSON_SCHEMA,
 validate_technical_plan,
)
logger = structlog.get_logger
@register_node
class TechnicalPlanNode(BaseNode):
 """AI 技术方案生成节点
 基于需求信息和项目上下文，调用 LLM 生成结构化的技术方案。
 支持将方案回填到飞书工作项字段并自动流转状态。
 """
 node_type = "ai_technical_plan"
 display_name = "AI 技术方案"
 description = "基于需求生成结构化的技术实现方案，支持飞书回填"
 icon = "file-text"
 category = NodeCategory.AI
 config_schema = {
 "type": "object",
 "properties": {
 "model": {
 "type": "string",
 "title": "模型",
 "description": "用于生成技术方案的 LLM 模型",
 "enum": [
 "claude-opus-4-5-20251101",
 "claude-sonnet-4-5-20251101",
 "claude-haiku-4-5-20251001",
 "claude-3-opus-20240229",
 "claude-3-5-sonnet-20241022",
 "claude-3-sonnet-20240229",
 "gpt-4",
 "gpt-4-turbo",
 ],
 "default": "claude-3-5-sonnet-20241022",
 },
 "detail_level": {
 "type": "string",
 "title": "详细程度",
 "description": "技术方案的详细程度",
 "enum": ["brief", "standard", "detailed"],
 "default": "standard",
 },
 "include_tests": {
 "type": "boolean",
 "title": "包含测试方案",
 "description": "是否在方案中包含测试策略",
 "default": True,
 },
 "feishu_field_key": {
 "type": "string",
 "title": "飞书字段 Key",
 "description": "技术方案回填的字段 Key",
 "default": "",
 },
 "auto_transition_status": {
 "type": "boolean",
 "title": "自动流转状态",
 "description": "回填成功后自动流转到待审核",
 "default": True,
 },
 "target_status": {
 "type": "string",
 "title": "目标状态",
 "description": "自动流转的目标状态名称",
 "default": "待审核",
 },
 },
 }
 inputs = [
 NodePort(
 name="default",
 label="输入",
 port_type=PortType.OBJECT,
 required=False,
 description="上游节点输出，通常包含需求信息",
 ),
 ]
 outputs = [
 NodePort(
 name="default",
 label="技术方案",
 port_type=PortType.OBJECT,
 description="生成的技术方案",
 ),
 NodePort(
 name="error",
 label="失败",
 port_type=PortType.OBJECT,
 description="处理失败时的错误信息",
 ),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """生成技术方案并回填到飞书"""
 config = context.node_config
 # 解析配置
 model = config.get("model", "claude-3-5-sonnet-20241022")
 detail_level = config.get("detail_level", "standard")
 include_tests = config.get("include_tests", True)
 feishu_field_key = config.get("feishu_field_key", "")
 auto_transition_status = config.get("auto_transition_status", True)
 target_status = config.get("target_status", "待审核")
 try:
 # 从全局参数获取需求信息
 work_item_name = context.get_global_param("work_item_name", "")
 description = context.get_global_param("description", "")
 prd_url = context.get_global_param("prd_url", "")
 repositories = context.get_global_param("repositories", )
 # 飞书上下文
 project_key = context.get_global_param("project_key", "")
 work_item_id = context.get_global_param("work_item_id", 0)
 work_item_type = context.get_global_param("work_item_type", "story")
 if not description and not work_item_name:
 return NodeResult(
 status="failed",
 error="缺少需求信息，请确保上游节点已设置 description 或 work_item_name 全局参数",
 next_handle="error",
 )
 # 获取项目信息
 project = await self._get_project(context)
 # 构建 prompt
 prompt = self._build_plan_prompt(
 work_item_name=work_item_name,
 description=description,
 prd_url=prd_url,
 repositories=repositories,
 detail_level=detail_level,
 include_tests=include_tests,
 )
 # 调用 LLM 生成方案
 llm_response = await self._call_llm(
 prompt=prompt,
 model=model,
 project=project,
 )
 # 解析 LLM 输出
 plan_data = self._parse_llm_response(llm_response)
 # 验证方案结构
 is_valid, error_msg = validate_technical_plan(plan_data)
 if not is_valid:
 return NodeResult(
 status="failed",
 error=f"技术方案验证失败: {error_msg}",
 next_handle="error",
 )
 # 转换为 Markdown
 plan_markdown = self._plan_to_markdown(plan_data)
 # 飞书回填
 feishu_writeback_success = False
 status_transition_success = False
 if feishu_field_key and project_key and work_item_id:
 try:
 feishu_client = create_feishu_client_for_project(project)
 # 写入字段
 await feishu_client.update_field(
 project_key=project_key,
 work_item_id=work_item_id,
 work_item_type=work_item_type,
 field_key=feishu_field_key,
 field_value=plan_markdown,
 )
 feishu_writeback_success = True
 logger.info(
 "feishu_field_updated",
 work_item_id=work_item_id,
 field_key=feishu_field_key,
 )
 # 自动流转状态
 if auto_transition_status:
 try:
 await feishu_client.transition_status(
 project_key=project_key,
 work_item_id=work_item_id,
 work_item_type=work_item_type,
 target_status_name=target_status,
 )
 status_transition_success = True
 logger.info(
 "feishu_status_transitioned",
 work_item_id=work_item_id,
 target_status=target_status,
 )
 except Exception as e:
 logger.warning(
 "feishu_status_transition_failed",
 work_item_id=work_item_id,
 error=str(e),
 )
 except FeishuAPIError as e:
 logger.error(
 "feishu_writeback_failed",
 work_item_id=work_item_id,
 error=str(e),
 )
 return NodeResult(
 status="failed",
 error=f"飞书回填失败: {e}",
 next_handle="error",
 )
 except ValueError as e:
 # 项目未配置飞书集成
 logger.warning(
 "feishu_not_configured",
 error=str(e),
 )
 return NodeResult(
 status="completed",
 output={
 "plan": plan_data,
 "plan_markdown": plan_markdown,
 "task_count": len(plan_data.get("execution_plan", )),
 "feishu_writeback": feishu_writeback_success,
 "status_transition": status_transition_success,
 },
 next_handle="default",
 )
 except Exception as e:
 logger.error("technical_plan_generation_failed", error=str(e))
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 def _build_plan_prompt(
 self,
 work_item_name: str,
 description: str,
 prd_url: str,
 repositories: list[dict[str, Any]],
 detail_level: str,
 include_tests: bool,
 ) -> str:
 """构建技术方案生成 Prompt"""
 detail_instructions = {
 "brief": "请提供简要的技术方案，重点关注关键实现步骤。",
 "standard": "请提供标准详细程度的技术方案，包含主要实现步骤、文件变更和注意事项。",
 "detailed": "请提供非常详细的技术方案，包括具体代码结构、函数签名、数据流、边界情况处理等。",
 }
 repos_desc = ""
 if repositories:
 repos_desc = "\n".join(
 [
 f"- {repo.get('name', 'unknown')}: {repo.get('description', '无描述')} (ID: {repo.get('id', '')})"
 for repo in repositories
 ]
 )
 # JSON Schema 描述
 schema_json = json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, ensure_ascii=False, indent=2)
 prompt = f"""你是一个专业的软件架构师。请基于以下需求，生成结构化的技术实现方案。
## 需求信息
**需求名称**: {work_item_name}
**需求描述**:
{description}
"""
 if prd_url:
 prompt += f"**需求文档链接**: {prd_url}\n\n"
 if repos_desc:
 prompt += f"""## 可用代码仓库
{repos_desc}
"""
 prompt += f"""## 输出要求
{detail_instructions.get(detail_level, detail_instructions["standard"])}
{"请在方案中包含测试策略。" if include_tests else ""}
请严格按照以下 JSON Schema 格式输出技术方案：
```json
{schema_json}
```
## 注意事项
1. execution_plan 中的每个任务必须包含 repository_id 和 repository_name
2. branch_strategy 必须是 feature/hotfix/release 之一
3. coding_instruction 应该包含足够详细的编码指令，让 AI 编码助手能够独立完成
4. 如果任务有依赖关系，在 dependencies 中列出依赖的任务 ID
请直接输出 JSON，不要包含其他内容。
"""
 return prompt
 async def _call_llm(
 self,
 prompt: str,
 model: str,
 project: Any,
 ) -> str:
 """调用 LLM 生成技术方案"""
 # 获取 API key
 api_key = None
 if project and hasattr(project, "anthropic_api_key"):
 api_key = project.anthropic_api_key
 if not api_key:
 api_key = os.environ.get("ANTHROPIC_API_KEY")
 if not api_key:
 raise ValueError("未配置 Anthropic API Key")
 async with httpx.AsyncClient as client:
 response = await client.post(
 "https://api.anthropic.com/v1/messages",
 headers={
 "x-api-key": api_key,
 "anthropic-version": "2023-06-01",
 "content-type": "application/json",
 },
 json={
 "model": model,
 "max_tokens": 8192,
 "temperature": 0.3,
 "system": "你是一个专业的软件架构师，擅长技术方案设计。请始终以有效的 JSON 格式输出。",
 "messages": [{"role": "user", "content": prompt}],
 },
 timeout=180,
 )
 if response.status_code != 200:
 raise Exception(f"LLM API 错误: {response.status_code} - {response.text}")
 data = response.json
 content = data.get("content", )
 return content[0].get("text", "") if content else ""
 def _parse_llm_response(self, response: str) -> dict[str, Any]:
 """解析 LLM 响应为字典"""
 try:
 # 尝试提取 JSON
 if "```json" in response:
 start = response.find("```json") + 7
 end = response.find("```", start)
 json_str = response[start:end].strip
 elif "```" in response:
 start = response.find("```") + 3
 end = response.find("```", start)
 json_str = response[start:end].strip
 else:
 json_str = response.strip
 return json.loads(json_str)
 except json.JSONDecodeError as e:
 logger.error("parse_llm_response_failed", error=str(e))
 raise ValueError(f"无法解析 LLM 输出: {e}")
 def _plan_to_markdown(self, plan: dict[str, Any]) -> str:
 """Convert technical plan to human-readable Markdown"""
 md = f"# {plan.get('title', '技术方案')}\n\n"
 md += f"{plan.get('summary', '')}\n\n"
 # 项目信息
 projects = plan.get("projects", )
 if projects:
 md += "## 涉及项目\n\n"
 for proj in projects:
 md += f"- {proj.get('name', 'Unknown')} ({proj.get('repository_count', 0)} 个仓库)\n"
 md += "\n"
 # 执行计划
 md += "## 执行计划\n\n"
 for i, task in enumerate(plan.get("execution_plan", ), 1):
 md += f"### {i}. {task.get('name', '未命名任务')}\n\n"
 md += f"- **仓库**: {task.get('repository_name', '未指定')}\n"
 md += f"- **分支策略**: {task.get('branch_strategy', 'feature')}\n"
 if task.get("description"):
 md += f"- **描述**: {task.get('description')}\n"
 if task.get("estimated_hours"):
 md += f"- **预估工时**: {task.get('estimated_hours')} 小时\n"
 # 文件变更
 files = task.get("files", )
 if files:
 md += "\n**涉及文件**:\n"
 for f in files:
 action_icon = {"create": "+", "modify": "~", "delete": "-"}.get(
 f.get("action", "modify"), "~"
 )
 md += f" - [{action_icon}] `{f.get('path', '')}`"
 if f.get("description"):
 md += f": {f.get('description')}"
 md += "\n"
 # 编码指令
 if task.get("coding_instruction"):
 md += f"\n**编码指令**:\n\n{task.get('coding_instruction')}\n"
 md += "\n"
 # 风险和假设
 risks = plan.get("risks", )
 if risks:
 md += "## 风险\n\n"
 for risk in risks:
 md += f"- {risk}\n"
 md += "\n"
 assumptions = plan.get("assumptions", )
 if assumptions:
 md += "## 假设\n\n"
 for assumption in assumptions:
 md += f"- {assumption}\n"
 md += "\n"
 # 元数据
 md += "---\n\n"
 md += f"**任务总数**: {plan.get('total_tasks', len(plan.get('execution_plan', )))}\n"
 if plan.get("estimated_total_hours"):
 md += f"**预估总工时**: {plan.get('estimated_total_hours')} 小时\n"
 if plan.get("created_at"):
 md += f"**创建时间**: {plan.get('created_at')}\n"
 return md
 async def _get_project(self, context: ExecutionContext) -> Any:
 """获取关联的项目"""
 if context.workflow_execution:
 workflow = context.workflow_execution.workflow
 if workflow:
 return workflow.project
 return None
