"""Plan generation and revision nodes."""
import json
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
class GeneratePlanNode(BaseNode):
 """生成技术方案节点
 基于需求分析结果，生成详细的技术实现方案。
 对应原 Task 系统的 PLANNING 状态。
 """
 node_type = "generate_plan"
 display_name = "生成方案"
 description = "基于需求生成详细的技术实现方案"
 icon = "clipboard-list"
 category = NodeCategory.AI
 config_schema = {
 "type": "object",
 "properties": {
 "requirements": {
 "type": "string",
 "title": "需求描述",
 "description": "需求内容或需求分析结果，支持模板变量",
 },
 "codebase_info": {
 "type": "string",
 "title": "代码库信息",
 "description": "项目结构、技术栈等信息",
 "default": "",
 },
 "constraints": {
 "type": "string",
 "title": "约束条件",
 "description": "技术限制、时间限制等",
 "default": "",
 },
 "detail_level": {
 "type": "string",
 "title": "详细程度",
 "enum": ["brief", "standard", "detailed"],
 "default": "standard",
 },
 "include_tests": {
 "type": "boolean",
 "title": "包含测试方案",
 "default": True,
 },
 "model": {
 "type": "string",
 "title": "模型",
 "default": "gpt-4",
 },
 "repositories": {
 "oneOf": [
 {
 "type": "array",
 "title": "仓库列表",
 "description": "目标仓库列表，用于分配任务",
 "items": {"type": "string"},
 },
 {
 "type": "string",
 "title": "仓库引用",
 "description": "模板变量如 {{global.repositories}}",
 },
 ],
 },
 "codebase_context": {
 "type": "string",
 "title": "代码库上下文",
 "description": "从 ContextRetrievalNode 获取的相关代码上下文，支持模板变量",
 "default": "",
 },
 },
 "required": ["requirements"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="方案", port_type=PortType.OBJECT),
 NodePort(name="error", label="失败", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 requirements = context.render_template(config.get("requirements", ""))
 codebase_info = context.render_template(config.get("codebase_info", ""))
 constraints = context.render_template(config.get("constraints", ""))
 detail_level = config.get("detail_level", "standard")
 include_tests = config.get("include_tests", True)
 # Handle repositories - can be array or template string
 repositories_config = config.get("repositories", )
 if isinstance(repositories_config, str):
 rendered_repos = context.render_template(repositories_config)
 try:
 repositories: list[dict[str, Any]] = json.loads(rendered_repos) if rendered_repos else
 except json.JSONDecodeError:
 repositories =
 else:
 repositories = repositories_config if repositories_config else
 # Handle codebase_context - template string
 codebase_context = context.render_template(config.get("codebase_context", ""))
 if not requirements:
 return NodeResult(
 status="failed",
 error="需求描述不能为空",
 next_handle="error",
 )
 try:
 prompt = self._build_plan_prompt(
 requirements,
 codebase_info,
 constraints,
 detail_level,
 include_tests,
 repositories=repositories,
 codebase_context=codebase_context,
 )
 plan_result = await self._call_llm(prompt, config.get("model", "gpt-4"))
 return NodeResult(
 status="completed",
 output={
 "plan": plan_result,
 "plan_markdown": plan_result.get("markdown", ""),
 "files_to_modify": plan_result.get("files", ),
 "estimated_changes": plan_result.get("estimated_changes", 0),
 },
 next_handle="default",
 )
 except Exception as e:
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 def _build_plan_prompt(
 self,
 requirements: str,
 codebase_info: str,
 constraints: str,
 detail_level: str,
 include_tests: bool,
 repositories: list[dict[str, Any]] | None = None,
 codebase_context: str = "",
 ) -> str:
 """构建方案生成提示词"""
 prompt = f"""请基于以下需求，生成详细的技术实现方案：
## 需求
{requirements}
"""
 if codebase_info:
 prompt += f"""## 代码库信息
{codebase_info}
"""
 if constraints:
 prompt += f"""## 约束条件
{constraints}
"""
 if repositories:
 repos_desc = "\n".join(
 [
 f"- {repo.get('name', 'unknown')}: {repo.get('description', '无描述')} (ID: {repo.get('id', '')})"
 for repo in repositories
 ]
 )
 prompt += f"""## 可用代码仓库
{repos_desc}
"""
 if codebase_context:
 prompt += f"""## 相关代码上下文
以下是从各仓库检索到的相关代码，请参考这些代码来设计技术方案：
{codebase_context}
"""
 detail_instructions = {
 "brief": "请提供简要的实现思路，重点关注关键步骤。",
 "standard": "请提供标准详细程度的方案，包含主要实现步骤和注意事项。",
 "detailed": "请提供非常详细的方案，包括具体代码结构、函数签名、数据流等。",
 }
 prompt += f"""## 要求
{detail_instructions.get(detail_level, detail_instructions["standard"])}
请包含：
1. 实现概述
2. 详细步骤（按顺序）
3. 需要修改/创建的文件列表
4. 关键代码示例
5. 潜在问题和解决方案
"""
 if include_tests:
 prompt += "6. 测试方案（单元测试、集成测试）\n"
 return prompt
 async def _call_llm(self, prompt: str, model: str) -> dict:
 """调用 LLM 服务"""
 return {
 "markdown": "# 技术方案\n\n[Placeholder]",
 "overview": "实现概述",
 "steps":,
 "files":,
 "code_examples":,
 "potential_issues":,
 "test_plan": {},
 "estimated_changes": 0,
 }
@register_node
class RevisePlanNode(BaseNode):
 """修订技术方案节点
 根据反馈修改已有的技术方案。
 """
 node_type = "revise_plan"
 display_name = "修订方案"
 description = "根据反馈修改技术实现方案"
 icon = "edit-3"
 category = NodeCategory.AI
 config_schema = {
 "type": "object",
 "properties": {
 "original_plan": {
 "type": "string",
 "title": "原方案",
 "description": "原始技术方案内容，支持模板变量",
 },
 "feedback": {
 "type": "string",
 "title": "反馈意见",
 "description": "需要修改的内容或改进建议",
 },
 "preserve_structure": {
 "type": "boolean",
 "title": "保持结构",
 "description": "是否保持原方案的整体结构",
 "default": True,
 },
 "model": {
 "type": "string",
 "title": "模型",
 "default": "gpt-4",
 },
 },
 "required": ["original_plan", "feedback"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="修订方案", port_type=PortType.OBJECT),
 NodePort(name="error", label="失败", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 original_plan = context.render_template(config.get("original_plan", ""))
 feedback = context.render_template(config.get("feedback", ""))
 preserve_structure = config.get("preserve_structure", True)
 if not original_plan or not feedback:
 return NodeResult(
 status="failed",
 error="原方案和反馈意见不能为空",
 next_handle="error",
 )
 try:
 prompt = self._build_revision_prompt(original_plan, feedback, preserve_structure)
 revised_result = await self._call_llm(prompt, config.get("model", "gpt-4"))
 return NodeResult(
 status="completed",
 output={
 "revised_plan": revised_result,
 "plan_markdown": revised_result.get("markdown", ""),
 "changes_made": revised_result.get("changes", ),
 "revision_count": context.input_data.get("revision_count", 0) + 1,
 },
 next_handle="default",
 )
 except Exception as e:
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 def _build_revision_prompt(self, original: str, feedback: str, preserve_structure: bool) -> str:
 """构建方案修订提示词"""
 prompt = f"""请根据反馈修改以下技术方案：
## 原方案
{original}
## 反馈意见
{feedback}
## 要求
"""
 if preserve_structure:
 prompt += "请保持原方案的整体结构，只修改需要改进的部分。\n"
 else:
 prompt += "可以根据需要重新组织方案结构。\n"
 prompt += """
请输出：
1. 修订后的完整方案
2. 修改点说明（哪些地方做了改动）
"""
 return prompt
 async def _call_llm(self, prompt: str, model: str) -> dict:
 """调用 LLM 服务"""
 return {
 "markdown": "# 修订后的技术方案\n\n[Placeholder]",
 "changes":,
 }
