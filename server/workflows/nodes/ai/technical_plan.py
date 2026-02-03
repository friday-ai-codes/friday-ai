"""AI Technical Plan node for generating structured technical plans."""
import json
from datetime import datetime
from typing import Any
import httpx
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
from workflows.schemas.technical_plan import (
 TECHNICAL_PLAN_JSON_SCHEMA,
 validate_technical_plan,
)
logger = structlog.get_logger
@register_node
class TechnicalPlanNode(BaseNode):
 """AI 技术方案节点
 根据需求文档和代码上下文生成结构化的技术方案。
 输出符合 TechnicalPlanSchema 的 JSON 结构，可被下游 CodingDispatcher 消费。
 """
 node_type = "ai_technical_plan"
 display_name = "AI 技术方案"
 description = "根据需求文档生成技术方案"
 icon = "file-code"
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
 # 模型配置
 "model": {
 "type": "string",
 "title": "模型",
 "description": "使用的 LLM 模型",
 "default": "claude-sonnet-4-20250514",
 },
 "generation_mode": {
 "type": "string",
 "title": "生成模式",
 "description": "生成技术方案的模式",
 "enum": ["full", "outline_first"],
 "default": "outline_first",
 },
 "include_file_details": {
 "type": "boolean",
 "title": "包含文件详情",
 "description": "是否在任务中包含具体文件变更信息",
 "default": True,
 },
 "max_tasks": {
 "type": "integer",
 "title": "最大任务数",
 "description": "生成的最大任务数量",
 "minimum": 1,
 "maximum": 50,
 "default": 20,
 },
 "temperature": {
 "type": "number",
 "title": "温度",
 "description": "控制输出的随机性，低温度产生更一致的结构化输出",
 "minimum": 0,
 "maximum": 1,
 "default": 0.3,
 },
 "max_retries": {
 "type": "integer",
 "title": "最大重试次数",
 "description": "Schema 验证失败时的重试次数",
 "minimum": 1,
 "maximum": 5,
 "default": 3,
 },
 },
 }
 inputs = [
 NodePort(
 name="default",
 label="输入",
 port_type=PortType.OBJECT,
 required=False,
 description="上游节点输出（如代码上下文）",
 ),
 ]
 outputs = [
 NodePort(
 name="default",
 label="技术方案",
 port_type=PortType.OBJECT,
 description="生成的技术方案对象",
 ),
 NodePort(
 name="error",
 label="失败",
 port_type=PortType.OBJECT,
 description="生成失败时的错误信息",
 ),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """执行技术方案生成"""
 config = context.node_config
 # 解析配置
 model = config.get("model", "claude-sonnet-4-20250514")
 generation_mode = config.get("generation_mode", "outline_first")
 include_file_details = config.get("include_file_details", True)
 max_tasks = config.get("max_tasks", 20)
 temperature = config.get("temperature", 0.3)
 max_retries = config.get("max_retries", 3)
 # 自定义 API 配置
 use_custom_api = config.get("use_custom_api", False)
 api_base_url = config.get("api_base_url", "")
 api_key = config.get("api_key", "")
 try:
 # 从全局参数获取需求信息
 work_item_name = context.get_global_param("work_item_name", "")
 description = context.get_global_param("description", "")
 prd_url = context.get_global_param("prd_url", "")
 repositories = context.get_global_param("repositories", )
 if not description and not prd_url:
 return NodeResult(
 status="failed",
 error="缺少需求信息，请确保已设置 description 或 prd_url 全局参数",
 next_handle="error",
 )
 if not repositories:
 return NodeResult(
 status="failed",
 error="缺少仓库信息，请确保项目已关联代码仓库",
 next_handle="error",
 )
 # 获取上游输入（代码上下文）
 upstream_input = context.input_data or {}
 code_context = upstream_input.get("code_context", "")
 # 使用重试逻辑生成技术方案
 plan_data, raw_response, attempts = await self._generate_with_retry(
 work_item_name=work_item_name,
 description=description,
 repositories=repositories,
 code_context=code_context,
 model=model,
 generation_mode=generation_mode,
 include_file_details=include_file_details,
 max_tasks=max_tasks,
 temperature=temperature,
 max_retries=max_retries,
 context=context,
 use_custom_api=use_custom_api,
 api_base_url=api_base_url,
 api_key=api_key,
 )
 logger.info(
 "technical_plan_generated",
 model=model,
 task_count=len(plan_data.get("execution_plan", )),
 attempts=attempts,
 )
 return NodeResult(
 status="completed",
 output={
 "plan": plan_data,
 "raw_response": raw_response,
 "model": model,
 "generation_mode": generation_mode,
 "attempts": attempts,
 },
 next_handle="default",
 )
 except Exception as e:
 logger.error("technical_plan_generation_failed", error=str(e), model=model)
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 async def _generate_with_retry(
 self,
 work_item_name: str,
 description: str,
 repositories: list[dict[str, Any]],
 code_context: str,
 model: str,
 generation_mode: str,
 include_file_details: bool,
 max_tasks: int,
 temperature: float,
 max_retries: int,
 context: ExecutionContext,
 use_custom_api: bool,
 api_base_url: str,
 api_key: str,
 ) -> tuple[dict[str, Any], str, int]:
 """使用重试逻辑生成技术方案
 Returns:
 tuple: (plan_data, raw_response, attempts)
 """
 last_error: str | None = None
 raw_response = ""
 for attempt in range(1, max_retries + 1):
 # 构建提示词
 prompt = self._build_generation_prompt(
 work_item_name=work_item_name,
 description=description,
 repositories=repositories,
 code_context=code_context,
 generation_mode=generation_mode,
 include_file_details=include_file_details,
 max_tasks=max_tasks,
 previous_error=last_error,
 )
 # 调用 LLM
 raw_response = await self._call_llm(
 prompt=prompt,
 model=model,
 temperature=temperature,
 context=context,
 use_custom_api=use_custom_api,
 api_base_url=api_base_url,
 api_key=api_key,
 )
 # 解析 JSON 响应
 try:
 plan_data = self._parse_json_response(raw_response)
 except ValueError as e:
 last_error = f"JSON 解析失败: {e}"
 logger.warning(
 "technical_plan_json_parse_failed",
 attempt=attempt,
 error=str(e),
 )
 continue
 # 验证 Schema
 is_valid, validation_error = validate_technical_plan(plan_data)
 if is_valid:
 return plan_data, raw_response, attempt
 last_error = f"Schema 验证失败: {validation_error}"
 logger.warning(
 "technical_plan_validation_failed",
 attempt=attempt,
 error=validation_error,
 )
 # 所有重试都失败
 raise ValueError(f"生成技术方案失败，已重试 {max_retries} 次。最后一个错误: {last_error}")
 def _build_generation_prompt(
 self,
 work_item_name: str,
 description: str,
 repositories: list[dict[str, Any]],
 code_context: str,
 generation_mode: str,
 include_file_details: bool,
 max_tasks: int,
 previous_error: str | None = None,
 ) -> str:
 """构建技术方案生成提示词"""
 # 格式化仓库信息
 repos_desc = "\n".join(
 [
 f"- ID: {repo.get('id', 'unknown')}, 名称: {repo.get('name', 'unknown')}, "
 f"描述: {repo.get('description', '无描述')}, 默认分支: {repo.get('default_branch', 'main')}"
 for repo in repositories
 ]
 )
 # 获取当前日期
 current_date = datetime.now.strftime("%Y-%m-%d")
 # 基础提示词
 prompt = f"""你是一位资深软件架构师，擅长分析需求并制定详细的技术实现方案。
## 任务
请根据以下需求信息，生成一份结构化的技术方案。方案需要包含具体的执行任务，每个任务应该：
1. 明确指定目标仓库（必须使用提供的仓库 ID 和名称）
2. 包含详细的编码指令
3. 指定分支策略（feature/hotfix/release）
4. 列出任务依赖关系
## 需求信息
**需求名称**: {work_item_name or '未命名需求'}
**需求描述**:
{description}
## 可用代码仓库
{repos_desc}
"""
 # 添加代码上下文（如果有）
 if code_context:
 prompt += f"""## 代码上下文
以下是与需求相关的现有代码信息：
{code_context[:15000]}
"""
 # 生成模式说明
 mode_instruction = ""
 if generation_mode == "outline_first":
 mode_instruction = "先概述整体架构思路，再细化每个任务。"
 else:
 mode_instruction = "直接生成完整的任务列表。"
 # 文件详情说明
 file_instruction = ""
 if include_file_details:
 file_instruction = "请为每个任务列出需要创建、修改或删除的文件。"
 else:
 file_instruction = "不需要列出具体文件变更。"
 prompt += f"""## 生成要求
- 生成模式: {mode_instruction}
- 最大任务数: {max_tasks}
- 文件详情: {file_instruction}
- 创建日期: {current_date}
## 输出格式
请严格按照以下 JSON Schema 格式输出：
```json
{json.dumps(TECHNICAL_PLAN_JSON_SCHEMA, indent=2, ensure_ascii=False)}
```
## 重要提示
1. `execution_plan` 中的每个任务必须包含 `id`、`name`、`repository_id`、`repository_name`、`branch_strategy` 字段
2. `repository_id` 和 `repository_name` 必须从上面提供的仓库列表中选择
3. `branch_strategy` 必须是 "feature"、"hotfix" 或 "release" 之一
4. `coding_instruction` 应该足够详细，让 AI 编码助手能够独立完成任务
5. 任务 ID 建议使用 "task-1"、"task-2" 这样的格式
6. 如果任务之间有依赖关系，在 `dependencies` 中列出依赖的任务 ID
请直接输出 JSON，不要添加额外的解释文字。
"""
 # 如果有之前的错误，添加错误反馈
 if previous_error:
 prompt += f"""
## 错误修正
上次生成的输出存在以下问题，请修正：
{previous_error}
请确保这次输出的 JSON 完全符合 Schema 要求。
"""
 return prompt
 async def _call_llm(
 self,
 prompt: str,
 model: str,
 temperature: float,
 context: ExecutionContext,
 use_custom_api: bool = False,
 api_base_url: str = "",
 api_key: str = "",
 ) -> str:
 """调用 LLM 生成技术方案"""
 # 如果使用自定义 API，使用 OpenAI 兼容协议
 if use_custom_api and api_base_url:
 return await self._call_openai_compatible(
 prompt, model, temperature, api_base_url, api_key
 )
 # 获取项目配置
 project = await self._get_project(context)
 # 根据模型类型选择调用方式
 if model.startswith("claude"):
 return await self._call_anthropic(prompt, model, temperature, project)
 else:
 return await self._call_openai_compatible(
 prompt, model, temperature, "https://api.openai.com/v1", ""
 )
 async def _call_anthropic(
 self,
 prompt: str,
 model: str,
 temperature: float,
 project: Any,
 ) -> str:
 """调用 Anthropic Claude API"""
 from asgiref.sync import sync_to_async
 from services.claude_config import get_claude_config
 # 使用 claude_config 服务获取配置
 config = await sync_to_async(get_claude_config)(project)
 api_key = config.api_key
 base_url = config.base_url or "https://api.anthropic.com"
 if not api_key:
 raise ValueError("未配置 Anthropic API Key，请在系统设置中配置")
 base_url = base_url.rstrip("/")
 system_prompt = (
 "你是一位资深软件架构师，擅长需求分析和技术方案设计。"
 "请始终以有效的 JSON 格式输出，不要添加额外的解释文字。"
 )
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
 "max_tokens": 16384,
 "temperature": temperature,
 "system": system_prompt,
 "messages": [{"role": "user", "content": prompt}],
 },
 timeout=300,
 )
 if response.status_code != 200:
 raise Exception(f"Anthropic API 错误: {response.status_code} - {response.text}")
 data = response.json
 content = data.get("content", )
 return content[0].get("text", "") if content else ""
 async def _call_openai_compatible(
 self,
 prompt: str,
 model: str,
 temperature: float,
 base_url: str,
 api_key: str = "",
 ) -> str:
 """调用 OpenAI 兼容 API"""
 import os
 base_url = base_url.rstrip("/")
 if not base_url.endswith("/v1"):
 base_url = f"{base_url}/v1"
 headers: dict[str, str] = {"Content-Type": "application/json"}
 # 获取 API key
 effective_api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
 if effective_api_key:
 headers["Authorization"] = f"Bearer {effective_api_key}"
 system_prompt = (
 "你是一位资深软件架构师，擅长需求分析和技术方案设计。"
 "请始终以有效的 JSON 格式输出，不要添加额外的解释文字。"
 )
 async with httpx.AsyncClient as client:
 response = await client.post(
 f"{base_url}/chat/completions",
 headers=headers,
 json={
 "model": model,
 "max_tokens": 16384,
 "temperature": temperature,
 "messages": [
 {"role": "system", "content": system_prompt},
 {"role": "user", "content": prompt},
 ],
 },
 timeout=300,
 )
 if response.status_code != 200:
 raise Exception(f"API 错误: {response.status_code} - {response.text}")
 data = response.json
 choices = data.get("choices", )
 return choices[0].get("message", {}).get("content", "") if choices else ""
 def _parse_json_response(self, response: str) -> dict[str, Any]:
 """从 LLM 响应中提取 JSON"""
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
 try:
 return json.loads(json_str)
 except json.JSONDecodeError as e:
 raise ValueError(f"无法解析 JSON: {e}")
 async def _get_project(self, context: ExecutionContext) -> Any:
 """获取关联的项目"""
 from asgiref.sync import sync_to_async
 if context.workflow_execution:
 workflow = await sync_to_async(lambda: context.workflow_execution.workflow) # type: ignore[union-attr]
 if workflow:
 return await sync_to_async(lambda: workflow.project)
 return None
