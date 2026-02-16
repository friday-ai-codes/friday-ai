"""Analysis nodes for requirements and bug analysis."""
from workflows.nodes.base import (
 BaseNode,
 ExecutionContext,
 NodeCategory,
 NodePort,
 NodeResult,
 PortType,
)
class AnalyzeRequirementsNode(BaseNode):
 """需求分析节点 [未实现]
 使用 LLM 分析需求文档，提取关键信息。
 """
 node_type = "analyze_requirements"
 display_name = "需求分析"
 description = "使用 AI 分析需求，提取关键信息和技术要点"
 icon = "file-text"
 category = NodeCategory.AI
 config_schema = {
 "type": "object",
 "properties": {
 "requirements_text": {
 "type": "string",
 "title": "需求描述",
 "description": "需求内容，支持模板变量",
 },
 "context": {
 "type": "string",
 "title": "上下文信息",
 "description": "项目相关的上下文信息",
 "default": "",
 },
 "output_format": {
 "type": "string",
 "title": "输出格式",
 "enum": ["markdown", "json", "structured"],
 "default": "structured",
 },
 "model": {
 "type": "string",
 "title": "模型",
 "description": "使用的 LLM 模型",
 "default": "gpt-4",
 },
 },
 "required": ["requirements_text"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="分析结果", port_type=PortType.OBJECT),
 NodePort(name="error", label="失败", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 requirements_text = context.render_template(config.get("requirements_text", ""))
 project_context = context.render_template(config.get("context", ""))
 output_format = config.get("output_format", "structured")
 if not requirements_text:
 return NodeResult(
 status="failed",
 error="需求描述不能为空",
 next_handle="error",
 )
 try:
 # Build the analysis prompt
 prompt = self._build_analysis_prompt(requirements_text, project_context, output_format)
 # Call LLM service (placeholder - integrate with actual LLM service)
 analysis_result = await self._call_llm(prompt, config.get("model", "gpt-4"))
 return NodeResult(
 status="completed",
 output={
 "analysis": analysis_result,
 "requirements_text": requirements_text,
 "format": output_format,
 },
 next_handle="default",
 )
 except Exception as e:
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 def _build_analysis_prompt(self, requirements: str, context: str, output_format: str) -> str:
 """构建分析提示词"""
 prompt = f"""请分析以下需求，提取关键信息：
## 需求描述
{requirements}
"""
 if context:
 prompt += f"""## 项目上下文
{context}
"""
 prompt += """## 请提供以下分析：
1. 功能需求列表
2. 技术要点
3. 潜在风险和挑战
4. 估计工作量（小/中/大）
5. 建议的实现步骤
"""
 if output_format == "json":
 prompt += "\n请以 JSON 格式输出。"
 elif output_format == "structured":
 prompt += "\n请使用结构化的 Markdown 格式输出。"
 return prompt
 async def _call_llm(self, prompt: str, model: str) -> dict:
 """调用 LLM 服务"""
 raise NotImplementedError("LLM 服务集成未实现")
class AnalyzeBugNode(BaseNode):
 """Bug 分析节点 [未实现]
 使用 LLM 分析 Bug 报告，提取关键信息和可能的解决方案。
 """
 node_type = "analyze_bug"
 display_name = "Bug 分析"
 description = "使用 AI 分析 Bug，定位问题和建议修复方案"
 icon = "bug"
 category = NodeCategory.AI
 config_schema = {
 "type": "object",
 "properties": {
 "bug_description": {
 "type": "string",
 "title": "Bug 描述",
 "description": "Bug 内容描述，支持模板变量",
 },
 "error_logs": {
 "type": "string",
 "title": "错误日志",
 "description": "相关的错误日志",
 "default": "",
 },
 "reproduction_steps": {
 "type": "string",
 "title": "复现步骤",
 "default": "",
 },
 "codebase_context": {
 "type": "string",
 "title": "代码上下文",
 "description": "相关代码片段或文件路径",
 "default": "",
 },
 "model": {
 "type": "string",
 "title": "模型",
 "default": "gpt-4",
 },
 },
 "required": ["bug_description"],
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = [
 NodePort(name="default", label="分析结果", port_type=PortType.OBJECT),
 NodePort(name="error", label="失败", port_type=PortType.OBJECT),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 bug_description = context.render_template(config.get("bug_description", ""))
 error_logs = context.render_template(config.get("error_logs", ""))
 reproduction_steps = context.render_template(config.get("reproduction_steps", ""))
 codebase_context = context.render_template(config.get("codebase_context", ""))
 if not bug_description:
 return NodeResult(
 status="failed",
 error="Bug 描述不能为空",
 next_handle="error",
 )
 try:
 prompt = self._build_bug_analysis_prompt(
 bug_description, error_logs, reproduction_steps, codebase_context
 )
 analysis_result = await self._call_llm(prompt, config.get("model", "gpt-4"))
 return NodeResult(
 status="completed",
 output={
 "analysis": analysis_result,
 "bug_description": bug_description,
 "severity": analysis_result.get("severity", "unknown"),
 },
 next_handle="default",
 )
 except Exception as e:
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 def _build_bug_analysis_prompt(
 self,
 description: str,
 logs: str,
 steps: str,
 code_context: str,
 ) -> str:
 """构建 Bug 分析提示词"""
 prompt = f"""请分析以下 Bug，提供诊断和修复建议：
## Bug 描述
{description}
"""
 if logs:
 prompt += f"""## 错误日志
```
{logs}
```
"""
 if steps:
 prompt += f"""## 复现步骤
{steps}
"""
 if code_context:
 prompt += f"""## 相关代码
```
{code_context}
```
"""
 prompt += """## 请提供以下分析：
1. 问题根因分析
2. 严重程度评估（critical/high/medium/low）
3. 可能的解决方案
4. 建议的修复步骤
5. 需要注意的边界情况
"""
 return prompt
 async def _call_llm(self, prompt: str, model: str) -> dict:
 """调用 LLM 服务"""
 raise NotImplementedError("LLM 服务集成未实现")
