"""AI Prompt node for general LLM interactions."""
import json
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
# 默认支持的模型列表（当未配置自定义 API 时使用）
DEFAULT_MODELS = [
 "claude-sonnet-4-20250514",
 "claude-3-7-sonnet-20250219",
 "claude-3-5-sonnet-20241022",
 "claude-3-5-haiku-20241022",
 "gpt-4o",
 "gpt-4o-mini",
 "gpt-4-turbo",
]
@register_node
class AIPromptNode(BaseNode):
 """AI Prompt 节点
 通用的 LLM 交互节点，支持自定义 System Prompt 和 User Prompt。
 可用于需求分析、内容生成、数据处理等各种 AI 任务。
 支持自定义 API Base URL 和 API Key，兼容 OpenAI API 协议。
 """
 node_type = "ai_prompt"
 display_name = "AI Prompt"
 description = "通用 AI 节点，支持自定义提示词和 API 配置"
 icon = "message-square"
 category = NodeCategory.AI
 config_schema = {
 "type": "object",
 "properties": {
 # API 配置
 "use_custom_api": {
 "type": "boolean",
 "title": "使用自定义 API",
 "description": "启用后可配置自定义的 API 地址和密钥",
 "default": False,
 },
 "api_base_url": {
 "type": "string",
 "title": "API Base URL",
 "description": "自定义 API 地址，如 https://api.openai.com/v1",
 "default": "",
 },
 "api_key": {
 "type": "string",
 "title": "API Key",
 "description": "API 密钥（可为空，某些本地部署无需密钥）",
 "default": "",
 },
 # 提示词配置
 "system_prompt": {
 "type": "string",
 "title": "System Prompt",
 "description": "系统提示词，定义 AI 的角色和行为",
 "default": "你是一个专业的软件开发助手。",
 },
 "user_prompt": {
 "type": "string",
 "title": "User Prompt",
 "description": "用户提示词，支持模板变量如 {{global.description}}",
 "minLength": 1,
 },
 # 模型配置
 "model": {
 "type": "string",
 "title": "模型",
 "description": "使用的 LLM 模型",
 "default": "claude-sonnet-4-20250514",
 },
 "temperature": {
 "type": "number",
 "title": "温度",
 "description": "控制输出的随机性，0 为确定性，2 为最随机",
 "minimum": 0,
 "maximum": 2,
 "default": 0.7,
 },
 "max_tokens": {
 "type": "integer",
 "title": "最大 Token 数",
 "description": "生成的最大 token 数量",
 "minimum": 1,
 "maximum": 128000,
 "default": 4096,
 },
 "output_format": {
 "type": "string",
 "title": "输出格式",
 "description": "期望的输出格式",
 "enum": ["text", "json", "markdown"],
 "default": "text",
 },
 "json_schema": {
 "type": "object",
 "title": "JSON Schema",
 "description": "当输出格式为 JSON 时，可指定期望的结构",
 "default": {},
 },
 },
 "required": ["user_prompt"],
 }
 inputs = [
 NodePort(
 name="default",
 label="输入",
 port_type=PortType.OBJECT,
 required=False,
 description="上游节点输出，可在模板中引用",
 ),
 ]
 outputs = [
 NodePort(
 name="default",
 label="AI 响应",
 port_type=PortType.OBJECT,
 description="包含 response 和 usage 信息",
 ),
 NodePort(
 name="error",
 label="失败",
 port_type=PortType.OBJECT,
 description="调用失败时的错误信息",
 ),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """执行 AI 提示词调用"""
 config = context.node_config
 # 解析配置
 system_prompt = context.render_template(config.get("system_prompt", ""))
 user_prompt = context.render_template(config.get("user_prompt", ""))
 model = config.get("model", "claude-sonnet-4-20250514")
 temperature = config.get("temperature", 0.7)
 max_tokens = config.get("max_tokens", 4096)
 output_format = config.get("output_format", "text")
 json_schema = config.get("json_schema", {})
 # 自定义 API 配置
 use_custom_api = config.get("use_custom_api", False)
 api_base_url = config.get("api_base_url", "")
 api_key = config.get("api_key", "")
 # 验证
 if not user_prompt:
 return NodeResult(
 status="failed",
 error="User Prompt 不能为空",
 next_handle="error",
 )
 try:
 # 根据输出格式调整提示词
 formatted_user_prompt = self._format_prompt_for_output(
 user_prompt, output_format, json_schema
 )
 # 调用 LLM
 response, usage = await self._call_llm(
 system_prompt=system_prompt,
 user_prompt=formatted_user_prompt,
 model=model,
 temperature=temperature,
 max_tokens=max_tokens,
 context=context,
 use_custom_api=use_custom_api,
 api_base_url=api_base_url,
 api_key=api_key,
 )
 # 解析输出
 parsed_response = self._parse_response(response, output_format)
 logger.info(
 "ai_prompt_completed",
 model=model,
 input_tokens=usage.get("input_tokens", 0),
 output_tokens=usage.get("output_tokens", 0),
 )
 return NodeResult(
 status="completed",
 output={
 "response": parsed_response,
 "raw_response": response,
 "model": model,
 "usage": usage,
 "output_format": output_format,
 },
 next_handle="default",
 )
 except Exception as e:
 logger.error("ai_prompt_failed", error=str(e), model=model)
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 def _format_prompt_for_output(
 self, prompt: str, output_format: str, json_schema: dict
 ) -> str:
 """根据输出格式调整提示词"""
 if output_format == "json":
 schema_hint = ""
 if json_schema:
 schema_hint = f"\n\n期望的 JSON 结构:\n```json\n{json.dumps(json_schema, indent=2, ensure_ascii=False)}\n```"
 return f"{prompt}\n\n请以有效的 JSON 格式输出。{schema_hint}"
 elif output_format == "markdown":
 return f"{prompt}\n\n请使用 Markdown 格式输出。"
 return prompt
 def _parse_response(self, response: str, output_format: str) -> Any:
 """解析 LLM 响应"""
 if output_format == "json":
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
 # 如果解析失败，返回原始文本
 return {"raw": response, "parse_error": True}
 return response
 async def _call_llm(
 self,
 system_prompt: str,
 user_prompt: str,
 model: str,
 temperature: float,
 max_tokens: int,
 context: ExecutionContext,
 use_custom_api: bool = False,
 api_base_url: str = "",
 api_key: str = "",
 ) -> tuple[str, dict]:
 """调用 LLM 服务
 Returns:
 tuple: (response_text, usage_dict)
 """
 # 如果使用自定义 API，使用 OpenAI 兼容协议
 if use_custom_api and api_base_url:
 return await self._call_openai_compatible(
 system_prompt, user_prompt, model, temperature, max_tokens,
 api_base_url, api_key
 )
 # 获取项目的 API 配置
 project = await self._get_project(context)
 # 根据模型类型选择调用方式
 if model.startswith("claude"):
 return await self._call_anthropic(
 system_prompt, user_prompt, model, temperature, max_tokens, project
 )
 elif model.startswith("gpt") or model.startswith("o1") or model.startswith("o3"):
 return await self._call_openai(
 system_prompt, user_prompt, model, temperature, max_tokens, project
 )
 else:
 # 默认使用 OpenAI 兼容协议
 return await self._call_openai(
 system_prompt, user_prompt, model, temperature, max_tokens, project
 )
 async def _call_openai_compatible(
 self,
 system_prompt: str,
 user_prompt: str,
 model: str,
 temperature: float,
 max_tokens: int,
 base_url: str,
 api_key: str = "",
 ) -> tuple[str, dict]:
 """调用 OpenAI 兼容 API（支持自定义 Base URL）"""
 import httpx
 # 确保 base_url 格式正确
 base_url = base_url.rstrip("/")
 if not base_url.endswith("/v1"):
 base_url = f"{base_url}/v1"
 headers = {"Content-Type": "application/json"}
 if api_key:
 headers["Authorization"] = f"Bearer {api_key}"
 # 构建 messages，只有当 system_prompt 非空时才包含 system message
 messages =
 if system_prompt:
 messages.append({"role": "system", "content": system_prompt})
 messages.append({"role": "user", "content": user_prompt})
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"{base_url}/chat/completions",
 headers=headers,
 json={
 "model": model,
 "max_tokens": max_tokens,
 "temperature": temperature,
 "messages": messages,
 },
 timeout=120,
 )
 if response.status_code != 200:
 raise Exception(f"API 错误: {response.status_code} - {response.text}")
 data = response.json
 choices = data.get("choices", )
 text = choices[0].get("message", {}).get("content", "") if choices else ""
 usage = {
 "input_tokens": data.get("usage", {}).get("prompt_tokens", 0),
 "output_tokens": data.get("usage", {}).get("completion_tokens", 0),
 }
 return text, usage
 async def _call_anthropic(
 self,
 system_prompt: str,
 user_prompt: str,
 model: str,
 temperature: float,
 max_tokens: int,
 project,
 ) -> tuple[str, dict]:
 """调用 Anthropic Claude API"""
 import httpx
 from asgiref.sync import sync_to_async
 from services.claude_config import get_claude_config
 # 使用 claude_config 服务获取配置
 config = await sync_to_async(get_claude_config)(project)
 api_key = config.api_key
 base_url = config.base_url or "https://api.anthropic.com"
 if not api_key:
 raise ValueError("未配置 Anthropic API Key，请在系统设置中配置")
 # 确保 base_url 格式正确
 base_url = base_url.rstrip("/")
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"{base_url}/v1/messages",
 headers={
 "x-api-key": api_key,
 "anthropic-version": "2023-06-01",
 "content-type": "application/json",
 },
 json={
 "model": model,
 "max_tokens": max_tokens,
 "temperature": temperature,
 "system": system_prompt,
 "messages": [{"role": "user", "content": user_prompt}],
 },
 timeout=120,
 )
 if response.status_code != 200:
 raise Exception(f"Anthropic API 错误: {response.status_code} - {response.text}")
 data = response.json
 content = data.get("content", )
 text = content[0].get("text", "") if content else ""
 usage = {
 "input_tokens": data.get("usage", {}).get("input_tokens", 0),
 "output_tokens": data.get("usage", {}).get("output_tokens", 0),
 }
 return text, usage
 async def _call_openai(
 self,
 system_prompt: str,
 user_prompt: str,
 model: str,
 temperature: float,
 max_tokens: int,
 project,
 ) -> tuple[str, dict]:
 """调用 OpenAI API"""
 import httpx
 api_key = None
 if project and hasattr(project, "openai_api_key"):
 api_key = project.openai_api_key
 if not api_key:
 import os
 api_key = os.environ.get("OPENAI_API_KEY")
 if not api_key:
 raise ValueError("未配置 OpenAI API Key")
 async with httpx.AsyncClient as client:
 response = await client.post(
 "https://api.openai.com/v1/chat/completions",
 headers={
 "Authorization": f"Bearer {api_key}",
 "Content-Type": "application/json",
 },
 json={
 "model": model,
 "max_tokens": max_tokens,
 "temperature": temperature,
 "messages": [
 {"role": "system", "content": system_prompt},
 {"role": "user", "content": user_prompt},
 ],
 },
 timeout=120,
 )
 if response.status_code != 200:
 raise Exception(f"OpenAI API 错误: {response.status_code} - {response.text}")
 data = response.json
 choices = data.get("choices", )
 text = choices[0].get("message", {}).get("content", "") if choices else ""
 usage = {
 "input_tokens": data.get("usage", {}).get("prompt_tokens", 0),
 "output_tokens": data.get("usage", {}).get("completion_tokens", 0),
 }
 return text, usage
 async def _get_project(self, context: ExecutionContext):
 """获取关联的项目"""
 from asgiref.sync import sync_to_async
 if context.workflow_execution:
 workflow = await sync_to_async(lambda: context.workflow_execution.workflow)
 if workflow:
 return await sync_to_async(lambda: workflow.project)
 return None
