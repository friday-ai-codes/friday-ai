"""AI Variable Extractor Node - Extract variables from text using AI."""
import json
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
logger = structlog.get_logger(__name__)
# AI 提取提示词模板
EXTRACTION_PROMPT_TEMPLATE = """请从以下文本中提取指定的变量信息。
需要提取的变量：
{variable_definitions}
文本内容：
---
{input_text}
---
{additional_prompt}
请严格按照以下 JSON 格式返回提取结果：
```json
{{
 "variables": {{
 "variableKey": "提取的值",
 ...
 }},
 "extraction_notes": {{
 "variableKey": "提取说明或未能提取的原因"
 }}
}}
```
注意：
1. 如果某个变量无法从文本中提取，请在 extraction_notes 中说明原因，variables 中不要包含该 key
2. 提取的值应该尽量保持原文中的表述
3. 确保返回的是有效的 JSON 格式"""
@register_node
class AIVariableExtractorNode(BaseNode):
 """AI 变量提取节点
 使用 AI 从非结构化文本中智能提取变量。
 适用于从自然语言描述中提取结构化信息。
 """
 node_type = "ai_variable_extractor"
 display_name = "AI 变量提取"
 description = "使用 AI 从文本中智能提取变量"
 icon = "sparkles"
 category = NodeCategory.AI
 execution_mode = "server_local"
 config_schema = {
 "type": "object",
 "properties": {
 "input_source": {
 "type": "string",
 "title": "输入来源",
 "description": "输入文本的来源路径，如 $.data.content 或直接的模板字符串",
 "default": "",
 },
 "variables": {
 "type": "array",
 "title": "目标变量",
 "description": "要提取的变量定义列表",
 "items": {
 "type": "object",
 "properties": {
 "key": {
 "type": "string",
 "title": "变量标识符",
 "description": "在模板中引用时使用的 key",
 "pattern": "^[a-zA-Z_][a-zA-Z0-9_]*$",
 },
 "name": {
 "type": "string",
 "title": "显示名称",
 "description": "变量的中文名称",
 },
 "desc": {
 "type": "string",
 "title": "提取描述",
 "description": "指导 AI 如何提取该变量的描述（必填）",
 },
 "required": {
 "type": "boolean",
 "title": "是否必填",
 "description": "如果为 true，提取失败时节点将报错",
 "default": False,
 },
 },
 "required": ["key", "name", "desc"],
 },
 },
 "additional_prompt": {
 "type": "string",
 "title": "额外指导",
 "description": "给 AI 的额外提取指导（选填）",
 "default": "",
 },
 "model": {
 "type": "string",
 "title": "模型",
 "description": "使用的 LLM 模型",
 "default": "",
 },
 # 高级设置
 "max_thinking_tokens": {
 "type": "integer",
 "title": "最大思考 Token 数",
 "description": "Claude 扩展思考的 token 上限，仅 Claude 模型支持。留空使用默认值",
 "minimum": 1024,
 "maximum": 128000,
 },
 "max_budget_usd": {
 "type": "number",
 "title": "预算上限 (USD)",
 "description": "单次调用的美元成本上限，留空不限制",
 "minimum": 0.01,
 "maximum": 100.0,
 },
 },
 "required": ["variables"],
 }
 inputs = [
 NodePort(
 name="text",
 label="文本输入",
 port_type=PortType.STRING,
 required=True,
 description="要提取变量的文本内容",
 )
 ]
 outputs = [
 NodePort(
 name="variables",
 label="提取结果",
 port_type=PortType.OBJECT,
 description="提取的变量摘要",
 )
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """执行 AI 变量提取"""
 config = context.node_config
 variables_config = config.get("variables", )
 additional_prompt = config.get("additional_prompt", "")
 model = config.get("model", "")
 input_source = config.get("input_source", "")
 max_thinking_tokens: int | None = config.get("max_thinking_tokens")
 if not variables_config:
 return NodeResult(
 status="completed",
 output={"variables": {}, "message": "无目标变量定义"},
 )
 # 获取输入文本
 input_text = self._get_input_text(context, input_source)
 if not input_text:
 return NodeResult(
 status="failed",
 error="无输入文本",
 )
 # 构建变量定义描述
 variable_definitions = "\n".join(
 f"- {v['key']} ({v['name']}): {v['desc']}" for v in variables_config
 )
 # 构建完整提示词
 prompt = EXTRACTION_PROMPT_TEMPLATE.format(
 variable_definitions=variable_definitions,
 input_text=input_text,
 additional_prompt=additional_prompt,
 )
 try:
 # 调用 AI
 response, usage = await self._call_llm(
 prompt=prompt,
 model=model,
 context=context,
 max_thinking_tokens=max_thinking_tokens,
 )
 # 解析响应
 extracted_data = self._parse_ai_response(response)
 if not extracted_data:
 return NodeResult(
 status="failed",
 error="AI 响应解析失败",
 output={"raw_response": response},
 )
 extracted_variables = extracted_data.get("variables", {})
 extraction_notes = extracted_data.get("extraction_notes", {})
 # 注册提取的变量
 registered_variables: dict[str, dict] = {}
 errors: list[str] =
 for var_config in variables_config:
 key = var_config["key"]
 name = var_config["name"]
 desc = var_config.get("desc", "")
 required = var_config.get("required", False)
 if key in extracted_variables:
 value = extracted_variables[key]
 # 注册全局变量
 context.set_global_variable(
 key=key,
 name=name,
 value=value,
 desc=desc,
 required=required,
 )
 registered_variables[key] = {
 "name": name,
 "value": value,
 }
 logger.info(
 "ai_variable_extracted",
 key=key,
 name=name,
 )
 else:
 # 变量未提取到
 note = extraction_notes.get(key, "未能从文本中提取")
 if required:
 errors.append(f"必填变量 '{name}' ({key}) 提取失败: {note}")
 else:
 logger.warning(
 "ai_variable_not_extracted",
 key=key,
 name=name,
 note=note,
 )
 if errors:
 return NodeResult(
 status="failed",
 error="; ".join(errors),
 output={
 "variables": registered_variables,
 "errors": errors,
 "usage": usage,
 },
 )
 return NodeResult(
 status="completed",
 output={
 "variables": registered_variables,
 "count": len(registered_variables),
 "usage": usage,
 "message": f"成功提取 {len(registered_variables)} 个变量",
 },
 )
 except Exception as e:
 logger.error("ai_variable_extraction_failed", error=str(e))
 return NodeResult(
 status="failed",
 error=f"AI 提取失败: {e}",
 )
 def _get_input_text(self, context: ExecutionContext, input_source: str) -> str:
 """获取输入文本"""
 # 如果指定了 input_source，使用模板渲染
 if input_source:
 # 如果是 JSONPath 格式，尝试从输入数据提取
 if input_source.startswith("$."):
 from jsonpath_ng import parse
 try:
 jsonpath_expr = parse(input_source)
 # 从输入数据或上游输出中查找
 data = context.input_data
 if not data:
 for output in context.previous_outputs.values:
 if output:
 data = output
 break
 if data:
 matches = jsonpath_expr.find(data)
 if matches:
 return str(matches[0].value)
 except Exception:
 pass
 # 尝试作为模板渲染
 return context.render_template(input_source)
 # 默认从输入数据获取
 input_data = context.input_data
 if isinstance(input_data, str):
 return input_data
 # 尝试获取常见的文本字段
 if isinstance(input_data, dict):
 for key in ["text", "content", "description", "body", "message"]:
 if key in input_data:
 return str(input_data[key])
 # 如果都没有，序列化整个对象
 return json.dumps(input_data, ensure_ascii=False, indent=2)
 # 从上游节点获取
 for output in context.previous_outputs.values:
 if isinstance(output, str):
 return output
 if isinstance(output, dict):
 for key in ["text", "content", "response", "description"]:
 if key in output:
 return str(output[key])
 return ""
 def _parse_ai_response(self, response: str) -> dict | None:
 """解析 AI 响应"""
 try:
 # 尝试提取 JSON 块
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
 except json.JSONDecodeError:
 logger.warning("ai_response_parse_failed", response=response[:500])
 return None
 async def _call_llm(
 self,
 prompt: str,
 model: str,
 context: ExecutionContext,
 max_thinking_tokens: int | None = None,
 ) -> tuple[str, dict]:
 """调用 LLM 服务"""
 import httpx
 from services.claude_config import aget_claude_config
 # 获取项目配置
 project = None
 if context.workflow_execution:
 from workflows.models import WorkflowExecution
 we = await WorkflowExecution.objects.select_related(
 "workflow__project"
 ).aget(id=context.workflow_execution.id)
 if we.workflow:
 project = we.workflow.project
 config = await aget_claude_config(project)
 # 如果未指定模型，从配置中获取
 resolved_model = model or config.model
 if not resolved_model:
 raise ValueError("未配置默认模型，请在系统设置或项目设置中配置默认模型")
 api_key = config.api_key
 base_url = config.base_url or "https://api.anthropic.com"
 if not api_key:
 raise ValueError("未配置 Anthropic API Key")
 base_url = base_url.rstrip("/")
 async with httpx.AsyncClient as client:
 payload: dict = {
 "model": resolved_model,
 "max_tokens": 4096,
 "messages": [{"role": "user", "content": prompt}],
 }
 # Extended thinking 支持：当 max_thinking_tokens 有值且为 Claude 模型时启用
 if max_thinking_tokens and resolved_model.startswith("claude"):
 payload["thinking"] = {
 "type": "enabled",
 "budget_tokens": max_thinking_tokens,
 }
 # Anthropic API 要求 thinking 模式下 temperature 必须为 1
 payload["temperature"] = 1
 else:
 payload["temperature"] = 0.3 # 低温度保证提取稳定性
 response = await client.post(
 f"{base_url}/v1/messages",
 headers={
 "x-api-key": api_key,
 "anthropic-version": "2023-06-01",
 "content-type": "application/json",
 },
 json=payload,
 timeout=120,
 )
 if response.status_code != 200:
 raise Exception(f"API 错误: {response.status_code} - {response.text}")
 data = response.json
 content = data.get("content", )
 text = content[0].get("text", "") if content else ""
 usage = {
 "input_tokens": data.get("usage", {}).get("input_tokens", 0),
 "output_tokens": data.get("usage", {}).get("output_tokens", 0),
 }
 return text, usage
