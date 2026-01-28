"""AI Coding Dispatcher node for analyzing requirements and creating coding tasks."""
import json
from typing import Any
import httpx
import structlog
from workflows.models.coding_task import CodingTask, CodingTaskStatus
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
@register_node
class AICodingDispatcherNode(BaseNode):
 """AI 编码指派器节点
 分析需求文档，判断涉及哪些代码仓库，
 为每个仓库生成编码任务 Prompt 并创建 CodingTask 记录。
 """
 node_type = "ai_coding_dispatcher"
 display_name = "AI 编码指派器"
 description = "分析需求并为涉及的仓库创建编码任务"
 icon = "git-branch"
 category = NodeCategory.AI
 config_schema = {
 "type": "object",
 "properties": {
 "analysis_model": {
 "type": "string",
 "title": "分析模型",
 "description": "用于需求分析的 LLM 模型",
 "enum": [
 "claude-3-opus-20240229",
 "claude-3-5-sonnet-20241022",
 "claude-3-sonnet-20240229",
 "gpt-4",
 "gpt-4-turbo",
 ],
 "default": "claude-3-5-sonnet-20241022",
 },
 "max_tasks": {
 "type": "integer",
 "title": "最大任务数",
 "description": "单次最多创建的编码任务数量",
 "minimum": 1,
 "maximum": 20,
 "default": 5,
 },
 "task_granularity": {
 "type": "string",
 "title": "任务粒度",
 "description": "任务拆分的粒度",
 "enum": ["fine", "medium", "coarse"],
 "default": "medium",
 },
 "include_tests": {
 "type": "boolean",
 "title": "包含测试任务",
 "description": "是否为每个实现任务生成对应的测试任务",
 "default": True,
 },
 "auto_assign_repos": {
 "type": "boolean",
 "title": "自动分配仓库",
 "description": "AI 自动判断任务应该在哪个仓库实现",
 "default": True,
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
 label="任务列表",
 port_type=PortType.OBJECT,
 description="创建的编码任务列表",
 ),
 NodePort(
 name="error",
 label="失败",
 port_type=PortType.OBJECT,
 description="处理失败时的错误信息",
 ),
 ]
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """分析需求并创建编码任务"""
 config = context.node_config
 # 解析配置
 analysis_model = config.get("analysis_model", "claude-3-5-sonnet-20241022")
 max_tasks = config.get("max_tasks", 5)
 task_granularity = config.get("task_granularity", "medium")
 include_tests = config.get("include_tests", True)
 auto_assign_repos = config.get("auto_assign_repos", True)
 try:
 # 从全局参数获取需求信息
 prd_url = context.get_global_param("prd_url", "")
 description = context.get_global_param("description", "")
 tech_doc_url = context.get_global_param("tech_doc_url", "")
 work_item_name = context.get_global_param("work_item_name", "")
 repositories = context.get_global_param("repositories", )
 if not description and not prd_url:
 return NodeResult(
 status="failed",
 error="缺少需求信息，请确保上游节点已设置 description 或 prd_url 全局参数",
 next_handle="error",
 )
 if not repositories:
 return NodeResult(
 status="failed",
 error="缺少仓库信息，请确保项目已关联代码仓库",
 next_handle="error",
 )
 # 抓取需求文档内容
 prd_content = ""
 if prd_url:
 prd_content = await self._fetch_document(prd_url)
 tech_doc_content = ""
 if tech_doc_url:
 tech_doc_content = await self._fetch_document(tech_doc_url)
 # 构建分析 Prompt
 analysis_prompt = self._build_analysis_prompt(
 work_item_name=work_item_name,
 description=description,
 prd_content=prd_content,
 tech_doc_content=tech_doc_content,
 repositories=repositories,
 task_granularity=task_granularity,
 max_tasks=max_tasks,
 include_tests=include_tests,
 auto_assign_repos=auto_assign_repos,
 )
 # 调用 LLM 分析
 analysis_result = await self._call_llm(
 prompt=analysis_prompt,
 model=analysis_model,
 context=context,
 )
 # 解析 LLM 输出
 tasks_data = self._parse_analysis_result(analysis_result)
 # 创建 CodingTask 记录
 created_tasks = await self._create_coding_tasks(
 tasks_data=tasks_data,
 repositories=repositories,
 context=context,
 )
 logger.info(
 "coding_tasks_created",
 task_count=len(created_tasks),
 work_item_name=work_item_name,
 )
 return NodeResult(
 status="completed",
 output={
 "tasks": [
 {
 "id": str(task.id),
 "name": task.name,
 "repository_id": str(task.repository_id),
 "status": task.status,
 }
 for task in created_tasks
 ],
 "task_count": len(created_tasks),
 "analysis_model": analysis_model,
 },
 next_handle="default",
 )
 except Exception as e:
 logger.error("coding_dispatcher_failed", error=str(e))
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 async def _fetch_document(self, url: str) -> str:
 """抓取文档内容
 支持常见文档平台的内容提取。
 """
 if not url:
 return ""
 try:
 async with httpx.AsyncClient as client:
 response = await client.get(url, timeout=30, follow_redirects=True)
 if response.status_code != 200:
 logger.warning("fetch_document_failed", url=url, status=response.status_code)
 return ""
 content_type = response.headers.get("content-type", "")
 if "text/html" in content_type:
 # 简单提取文本，实际使用时可以集成更完善的 HTML 解析
 return self._extract_text_from_html(response.text)
 elif "application/json" in content_type:
 return json.dumps(response.json, ensure_ascii=False, indent=2)
 else:
 return response.text[:50000] # 限制长度
 except Exception as e:
 logger.warning("fetch_document_error", url=url, error=str(e))
 return ""
 def _extract_text_from_html(self, html: str) -> str:
 """从 HTML 中提取文本（简化版）"""
 import re
 # 移除 script 和 style 标签
 html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
 html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
 # 移除所有 HTML 标签
 text = re.sub(r"<[^>]+>", " ", html)
 # 清理多余空白
 text = re.sub(r"\s+", " ", text)
 return text.strip[:30000] # 限制长度
 def _build_analysis_prompt(
 self,
 work_item_name: str,
 description: str,
 prd_content: str,
 tech_doc_content: str,
 repositories: list[dict],
 task_granularity: str,
 max_tasks: int,
 include_tests: bool,
 auto_assign_repos: bool,
 ) -> str:
 """构建需求分析 Prompt"""
 granularity_desc = {
 "fine": "细粒度：每个小功能点一个任务",
 "medium": "中粒度：每个功能模块一个任务",
 "coarse": "粗粒度：整体实现一个任务",
 }
 repos_desc = "\n".join([
 f"- {repo['name']}: {repo.get('description', '无描述')} (默认分支: {repo.get('default_branch', 'main')})"
 for repo in repositories
 ])
 prompt = f"""你是一个专业的软件架构师和项目经理。请分析以下需求，并创建编码任务。
## 需求信息
**需求名称**: {work_item_name}
**需求描述**:
{description}
"""
 if prd_content:
 prompt += f"""**需求文档内容**:
{prd_content[:10000]}
"""
 if tech_doc_content:
 prompt += f"""**技术方案文档**:
{tech_doc_content[:10000]}
"""
 prompt += f"""## 可用代码仓库
{repos_desc}
## 任务拆分要求
- 粒度: {granularity_desc.get(task_granularity, '中粒度')}
- 最多创建 {max_tasks} 个任务
- {'需要包含测试任务' if include_tests else '不需要单独的测试任务'}
- {'AI 自动判断每个任务应该在哪个仓库实现' if auto_assign_repos else '用户将手动分配仓库'}
## 请输出 JSON 格式的任务列表
```json
{{
 "analysis_summary": "需求分析摘要",
 "tasks": [
 {{
 "name": "任务名称（简洁描述）",
 "description": "任务详细描述",
 "repository_name": "目标仓库名称",
 "prompt": "发送给 AI 编码助手的完整 Prompt，包含：\\n1. 任务背景\\n2. 具体实现要求\\n3. 技术约束\\n4. 验收标准",
 "priority": 1,
 "is_test_task": false,
 "dependencies":
 }}
 ]
}}
```
注意：
1. prompt 字段非常重要，需要包含足够的上下文让 AI 编码助手能够独立完成任务
2. 每个任务应该是可以独立实现的
3. 如果任务有依赖关系，在 dependencies 中列出依赖的任务名称
4. priority 数字越小优先级越高
"""
 return prompt
 async def _call_llm(
 self,
 prompt: str,
 model: str,
 context: ExecutionContext,
 ) -> str:
 """调用 LLM 进行需求分析"""
 import os
 project = await self._get_project(context)
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
 "temperature": 0.3, # 低温度以获得更一致的输出
 "system": "你是一个专业的软件架构师，擅长需求分析和任务拆分。请始终以有效的 JSON 格式输出。",
 "messages": [{"role": "user", "content": prompt}],
 },
 timeout=180,
 )
 if response.status_code != 200:
 raise Exception(f"LLM API 错误: {response.status_code} - {response.text}")
 data = response.json
 content = data.get("content", )
 return content[0].get("text", "") if content else ""
 def _parse_analysis_result(self, result: str) -> list[dict]:
 """解析 LLM 分析结果"""
 try:
 # 尝试提取 JSON
 if "```json" in result:
 start = result.find("```json") + 7
 end = result.find("```", start)
 json_str = result[start:end].strip
 elif "```" in result:
 start = result.find("```") + 3
 end = result.find("```", start)
 json_str = result[start:end].strip
 else:
 json_str = result.strip
 data = json.loads(json_str)
 return data.get("tasks", )
 except json.JSONDecodeError as e:
 logger.error("parse_analysis_result_failed", error=str(e))
 raise ValueError(f"无法解析 LLM 输出: {e}")
 async def _create_coding_tasks(
 self,
 tasks_data: list[dict],
 repositories: list[dict],
 context: ExecutionContext,
 ) -> list[CodingTask]:
 """创建 CodingTask 记录"""
 from repositories.models import Repository
 # 构建仓库名称到 ID 的映射
 repo_name_to_id = {repo["name"]: repo["id"] for repo in repositories}
 created_tasks =
 workflow_execution = context.workflow_execution
 if not workflow_execution:
 raise ValueError("缺少 workflow_execution 上下文")
 for task_data in tasks_data:
 repo_name = task_data.get("repository_name", "")
 repo_id = repo_name_to_id.get(repo_name)
 if not repo_id:
 # 如果找不到匹配的仓库，使用第一个
 if repositories:
 repo_id = repositories[0]["id"]
 else:
 continue
 try:
 repository = await Repository.objects.aget(id=repo_id)
 except Repository.DoesNotExist:
 logger.warning("repository_not_found", repo_id=repo_id)
 continue
 coding_task = await CodingTask.objects.acreate(
 workflow_execution=workflow_execution,
 repository=repository,
 name=task_data.get("name", "未命名任务"),
 prompt=task_data.get("prompt", ""),
 description=task_data.get("description", ""),
 status=CodingTaskStatus.PENDING,
 metadata={
 "priority": task_data.get("priority", 99),
 "is_test_task": task_data.get("is_test_task", False),
 "dependencies": task_data.get("dependencies", ),
 },
 )
 created_tasks.append(coding_task)
 return created_tasks
 async def _get_project(self, context: ExecutionContext):
 """获取关联的项目"""
 if context.workflow_execution:
 workflow = context.workflow_execution.workflow
 if workflow:
 return workflow.project
 return None
