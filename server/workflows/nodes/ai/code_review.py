"""AI Code Review node - multi-dimensional code review agent.
Reads MR information from upstream AICodingNode output, fetches diffs via
GitPlatformClient, runs AI review covering code quality, security, and plan
compliance, then sends a Feishu notification card with the summary.
Architecture decision: Inherits AIAgentBaseNode for config_schema and helper
methods, but overrides execute entirely because:
1. Needs per-MR independent review (loop of Agent calls)
2. Needs async diff fetching (get_user_prompt is sync)
3. Needs post-review aggregation + Feishu notification
"""
import json
import re
import time
from typing import Any, ClassVar
import structlog
from agents.core.context import AgentContext
from agents.core.loop import AgentConfig, AgentLoop
from agents.core.result import AgentResult
from common.encryption import decrypt_value
from repositories.models import Repository
from services.git_platform import MRDiffResult, get_git_platform_client
from workflows.nodes.ai.base_agent import AIAgentBaseNode
from workflows.nodes.base import (
 ExecutionContext,
 NodePort,
 NodeResult,
 PortType,
)
from workflows.nodes.registry import register_node
logger = structlog.get_logger(__name__)
# 单个 MR diff 总字符数上限（避免超出 LLM 上下文窗口）
_MAX_DIFF_CHARS = 100000
# 审查系统 prompt
REVIEW_SYSTEM_PROMPT = """你是一位资深代码审查专家。你需要从三个维度审查代码变更：
1. 代码质量：可读性、可维护性、最佳实践、潜在 bug、错误处理
2. 安全性：SQL 注入、XSS、敏感信息泄露、权限问题、依赖安全
3. 方案符合度：代码变更是否忠实实现了技术方案中的任务
输出格式为 JSON，结构如下：
{
 "repository": "仓库名",
 "summary": "审查摘要（一两句话概括）",
 "dimensions": {
 "code_quality": {
 "issues": [
 {
 "severity": "critical|warning|info",
 "description": "问题描述",
 "file": "文件路径",
 "line": "行号（可选，可为空字符串）",
 "suggestion": "建议修改"
 }
 ]
 },
 "security": {
 "issues":
 },
 "plan_compliance": {
 "issues":
 }
 }
}
severity 说明：
- critical: 必须修复，阻塞合入（严重 bug、安全漏洞、关键功能缺失）
- warning: 建议修复（代码异味、潜在问题、非最佳实践）
- info: 改进建议（风格优化、文档补充、次要改进）
注意：
- 每个维度的 issues 数组可以为空（表示该维度无问题）
- 只输出 JSON，不要输出其他内容
- 如果无法评估方案符合度（缺少方案数据），plan_compliance.issues 设为空数组
"""
def _extract_json_from_text(text: str) -> dict[str, Any] | None:
 """从 Agent 输出文本中提取 JSON 块。
 支持纯 JSON 或被 markdown 代码块包裹的 JSON。
 Args:
 text: Agent 输出的原始文本
 Returns:
 解析后的 dict，解析失败返回 None
 """
 if not text:
 return None
 # 尝试直接解析
 try:
 return json.loads(text)
 except json.JSONDecodeError:
 pass
 # 尝试从 markdown 代码块中提取
 pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
 matches = re.findall(pattern, text, re.DOTALL)
 for match in matches:
 try:
 return json.loads(match)
 except json.JSONDecodeError:
 continue
 # 尝试提取 { ... } 块（贪婪匹配最外层大括号）
 brace_match = re.search(r"\{[\s\S]*\}", text)
 if brace_match:
 try:
 return json.loads(brace_match.group)
 except json.JSONDecodeError:
 pass
 return None
def _count_issues(report: dict[str, Any]) -> tuple[int, dict[str, int]]:
 """统计审查报告中的 issue 数量和严重度分布。
 Args:
 report: 单个 MR 的审查报告
 Returns:
 (总数, {"critical": N, "warning": N, "info": N})
 """
 breakdown: dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
 dimensions = report.get("dimensions", {})
 for dim_data in dimensions.values:
 if not isinstance(dim_data, dict):
 continue
 for issue in dim_data.get("issues", ):
 severity = issue.get("severity", "info")
 if severity in breakdown:
 breakdown[severity] += 1
 else:
 breakdown["info"] += 1
 total = sum(breakdown.values)
 return total, breakdown
def _truncate_diff(diff_text: str, max_chars: int = _MAX_DIFF_CHARS) -> tuple[str, bool]:
 """截断过长的 diff 文本。
 Args:
 diff_text: 完整 diff 文本
 max_chars: 最大字符数
 Returns:
 (截断后文本, 是否被截断)
 """
 if len(diff_text) <= max_chars:
 return diff_text, False
 return diff_text[:max_chars] + "\n\n[diff 内容过长已截断]", True
@register_node
class AICodeReviewNode(AIAgentBaseNode):
 """AI 代码审查节点。
 从上游 AICodingNode 的输出中读取 MR 信息，通过 GitPlatformClient
 获取每个 MR 的代码变更（diff），使用 AI Agent 从代码质量、安全性、
 方案符合度三个维度进行审查，输出结构化审查报告。
 Flow:
 1. 从 coding_result 输入端口提取 merge_requests 列表
 2. 从 plan 输入端口提取技术方案数据（可选）
 3. 逐 MR 获取 diff + AI 审查
 4. 汇总所有子报告
 5. 发送飞书通知卡片
 6. 返回 NodeResult
 """
 node_type: ClassVar[str] = "ai_code_review"
 display_name: ClassVar[str] = "AI 代码审查"
 description: ClassVar[str] = "AI 多维度代码审查"
 icon: ClassVar[str] = "search-code"
 config_schema: ClassVar[dict[str, Any]] = {
 "type": "object",
 "properties": {
 **AIAgentBaseNode.config_schema["properties"],
 "max_iterations": {
 "type": "integer",
 "title": "最大迭代次数",
 "description": "Agent 审查迭代上限",
 "default": 30,
 "minimum": 1,
 "maximum": 100,
 },
 },
 "required":,
 }
 inputs: ClassVar[list[NodePort]] = [
 NodePort(
 name="coding_result",
 label="编码结果",
 port_type=PortType.OBJECT,
 required=True,
 description="上游 AICodingNode 的输出（含 MR 信息）",
 ),
 NodePort(
 name="plan",
 label="技术方案",
 port_type=PortType.OBJECT,
 required=False,
 description="上游技术方案数据（用于方案符合度审查）",
 ),
 ]
 outputs: ClassVar[list[NodePort]] = [
 NodePort(
 name="default",
 label="审查结果",
 port_type=PortType.OBJECT,
 description="审查结果",
 schema={
 "type": "object",
 "properties": {
 "review_report": {
 "type": "object",
 "description": "结构化审查报告",
 },
 "issues_count": {
 "type": "integer",
 "description": "问题总数",
 },
 "severity_breakdown": {
 "type": "object",
 "description": "按严重度分类统计",
 },
 "approved": {
 "type": "boolean",
 "description": "是否通过审查",
 },
 },
 },
 ),
 NodePort(
 name="error",
 label="错误",
 port_type=PortType.OBJECT,
 description="失败时的错误信息",
 ),
 ]
 # ===== Hook 方法（保持接口一致性，虽然 execute 不调用它们） =====
 def get_system_prompt(self, context: ExecutionContext) -> str:
 """Return system prompt for code review."""
 return REVIEW_SYSTEM_PROMPT
 def get_user_prompt(self, context: ExecutionContext) -> str:
 """Return user prompt for code review.
 注意：实际审查中 execute 直接构建 per-MR prompt，
 此方法仅为满足 AIAgentBaseNode 抽象接口。
 """
 return "请审查以下代码变更。"
 def get_enabled_tools(self, context: ExecutionContext) -> list[str] | None:
 """审查无需外部工具。"""
 return
 def get_max_iterations(self, context: ExecutionContext) -> int:
 """Return max iterations for review agent."""
 value: int = context.node_config.get("max_iterations", 30)
 return value
 # ===== 覆写 execute =====
 async def execute(self, context: ExecutionContext) -> NodeResult:
 """执行 AI 代码审查节点。
 覆写 AIAgentBaseNode.execute，实现逐 MR 独立审查 + 汇总 + 飞书通知。
 """
 config = context.node_config
 start_time = time.monotonic
 log = logger.bind(
 execution_id=context.execution_id,
 node_id=context.node_id,
 )
 # 1. 提取上游数据
 coding_result = context.get_input("coding_result")
 if not coding_result or not isinstance(coding_result, dict):
 return NodeResult(
 status="failed",
 error="缺少编码结果数据（coding_result 输入端口为空）",
 next_handle="error",
 )
 merge_requests: list[dict[str, Any]] = coding_result.get("merge_requests", )
 if not merge_requests:
 return NodeResult(
 status="failed",
 error="编码结果中无 merge_requests 数据",
 next_handle="error",
 )
 # 可选的技术方案数据
 plan_data = context.get_input("plan")
 plan_title: str = ""
 execution_plan: list[dict[str, Any]] =
 if isinstance(plan_data, dict):
 plan_title = plan_data.get("title", "")
 execution_plan = plan_data.get("execution_plan", )
 if not plan_title:
 plan_title = "代码审查"
 log.info(
 "code_review_start",
 mr_count=len(merge_requests),
 has_plan=bool(execution_plan),
 )
 try:
 # 2. 准备 Agent 基础设施
 project = await self._get_project(context)
 user = await self._get_user(context)
 model: str = config.get("model", "")
 use_custom_api: bool = config.get("use_custom_api", False)
 api_base_url: str = config.get("api_base_url", "")
 api_key: str = config.get("api_key", "")
 max_iterations = self.get_max_iterations(context)
 provider = await self._get_provider(
 project, model, use_custom_api, api_base_url, api_key
 )
 # 3. 逐 MR 审查
 mr_reviews: list[dict[str, Any]] =
 review_errors: list[str] =
 for mr_info in merge_requests:
 mr_id: str = mr_info.get("mr_id", "")
 repository_id: str = mr_info.get("repository_id", "")
 repository_name: str = mr_info.get("repository_name", "")
 mr_url: str = mr_info.get("mr_url", "")
 if not mr_id or not repository_id:
 review_errors.append(
 f"MR 数据不完整: mr_id={mr_id}, repository_id={repository_id}"
 )
 continue
 log.info(
 "reviewing_mr",
 mr_id=mr_id,
 repository_name=repository_name,
 )
 # 3a. 获取仓库和 diff
 diff_result = await self._fetch_mr_diff(
 repository_id=repository_id,
 mr_id=mr_id,
 log=log,
 )
 if diff_result is None or not diff_result.success:
 error_msg = (
 diff_result.error if diff_result else "无法获取仓库信息"
 )
 review_errors.append(
 f"{repository_name} MR#{mr_id}: {error_msg}"
 )
 continue
 # 3b. 构建审查 prompt
 user_prompt = self._build_review_prompt(
 repository_name=repository_name,
 mr_url=mr_url,
 diff_result=diff_result,
 execution_plan=execution_plan,
 repository_id=repository_id,
 )
 # 3c. 调用 Agent 执行审查
 session_id = f"review-{context.execution_id}-{context.node_id}-{mr_id}"
 agent_context = AgentContext(
 session_id=session_id,
 project_id=project.id if project else 0,
 user_id=user.id if user else 0,
 )
 agent_config = AgentConfig(
 system_prompt=REVIEW_SYSTEM_PROMPT,
 max_iterations=max_iterations,
 tool_names=, # 审查不需要工具
 )
 loop = AgentLoop(
 config=agent_config,
 context=agent_context,
 provider=provider,
 )
 try:
 result: AgentResult = await loop.run(user_prompt)
 except Exception as e:
 log.warning(
 "mr_review_agent_error",
 mr_id=mr_id,
 repository_name=repository_name,
 error=str(e),
 )
 review_errors.append(
 f"{repository_name} MR#{mr_id}: Agent 执行失败 - {e}"
 )
 continue
 # 3d. 解析 Agent 输出
 review_data = self._parse_review_output(
 result=result,
 repository_name=repository_name,
 mr_id=mr_id,
 mr_url=mr_url,
 log=log,
 )
 mr_reviews.append(review_data)
 # 4. 汇总审查报告
 total_issues = 0
 total_breakdown: dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
 for review in mr_reviews:
 count, breakdown = _count_issues(review)
 total_issues += count
 for severity in total_breakdown:
 total_breakdown[severity] += breakdown.get(severity, 0)
 approved = total_breakdown["critical"] == 0
 # 构建最终报告
 review_report: dict[str, Any] = {
 "summary": self._build_review_summary(
 approved=approved,
 total_issues=total_issues,
 total_breakdown=total_breakdown,
 mr_count=len(mr_reviews),
 errors=review_errors,
 ),
 "mr_reviews": mr_reviews,
 "conclusion": "approved" if approved else "rejected",
 }
 duration = round(time.monotonic - start_time, 1)
 log.info(
 "code_review_complete",
 approved=approved,
 total_issues=total_issues,
 severity_breakdown=total_breakdown,
 mr_reviewed=len(mr_reviews),
 errors=len(review_errors),
 duration_seconds=duration,
 )
 # 5. 发送飞书通知
 await self._send_review_notification(
 context=context,
 approved=approved,
 issues_count=total_issues,
 severity_breakdown=total_breakdown,
 plan_title=plan_title,
 mr_count=len(mr_reviews),
 log=log,
 )
 # 6. 构建输出
 output: dict[str, Any] = {
 "review_report": review_report,
 "issues_count": total_issues,
 "severity_breakdown": total_breakdown,
 "approved": approved,
 "reviewed_mrs": [
 {
 "mr_id": r.get("mr_id", ""),
 "repository_name": r.get("repository", ""),
 "mr_url": r.get("mr_url", ""),
 "issues_count": _count_issues(r)[0],
 }
 for r in mr_reviews
 ],
 "review_duration_seconds": duration,
 "reviewer_model": model,
 }
 if review_errors:
 output["review_errors"] = review_errors
 return NodeResult(
 status="completed",
 output=output,
 next_handle="default",
 )
 except Exception as e:
 log.exception("code_review_error", error=str(e))
 return NodeResult(
 status="failed",
 error=str(e),
 next_handle="error",
 )
 # ------------------------------------------------------------------
 # diff 获取
 # ------------------------------------------------------------------
 async def _fetch_mr_diff(
 self,
 repository_id: str,
 mr_id: str,
 log: Any,
 ) -> MRDiffResult | None:
 """获取 MR 的 diff 数据。
 Args:
 repository_id: 仓库 UUID
 mr_id: MR 编号
 log: 绑定了上下文的 logger
 Returns:
 MRDiffResult 或 None（仓库不存在时）
 """
 try:
 repository = await Repository.objects.select_related(
 "credential"
 ).filter(
 id=repository_id, is_deleted=False
 ).afirst
 if not repository:
 log.warning("review_repository_not_found", repository_id=repository_id)
 return None
 credential = repository.credential
 if not credential or not credential.encrypted_token:
 log.warning(
 "review_no_credential",
 repository_id=repository_id,
 repository_name=repository.name,
 )
 return MRDiffResult(success=False, error="仓库未配置访问凭证")
 token = decrypt_value(credential.encrypted_token)
 client = get_git_platform_client(repository, token)
 return await client.get_merge_request_diff(mr_id)
 except Exception as e:
 log.error(
 "review_diff_fetch_error",
 repository_id=repository_id,
 mr_id=mr_id,
 error=str(e),
 )
 return MRDiffResult(success=False, error=str(e))
 # ------------------------------------------------------------------
 # prompt 构建
 # ------------------------------------------------------------------
 def _build_review_prompt(
 self,
 repository_name: str,
 mr_url: str,
 diff_result: MRDiffResult,
 execution_plan: list[dict[str, Any]],
 repository_id: str,
 ) -> str:
 """构建单个 MR 的审查 prompt。
 Args:
 repository_name: 仓库名
 mr_url: MR 链接
 diff_result: diff 获取结果
 execution_plan: 技术方案执行计划
 repository_id: 仓库 ID（用于匹配方案任务）
 Returns:
 用户 prompt 字符串
 """
 parts: list[str] =
 # 审查目标
 parts.append(
 f"## 审查目标\n\n"
 f"仓库: {repository_name}\n"
 f"MR: {mr_url}"
 )
 # diff 内容
 diff_sections: list[str] =
 for f in diff_result.files:
 file_label = f.new_path
 if f.new_file:
 file_label += " (新文件)"
 elif f.deleted_file:
 file_label += " (已删除)"
 elif f.renamed_file:
 file_label += f" (重命名自 {f.old_path})"
 diff_sections.append(f"### {file_label}\n```diff\n{f.diff}\n```")
 diff_content = "\n\n".join(diff_sections)
 diff_content, was_truncated = _truncate_diff(diff_content)
 if was_truncated or diff_result.truncated:
 diff_content += "\n\n**注意：部分 diff 内容因过大已被截断，请基于可见内容进行审查。**"
 parts.append(f"## 代码变更 (Diff)\n\n{diff_content}")
 # 技术方案（如有）
 if execution_plan:
 # 提取对应仓库的任务
 repo_tasks = [
 task for task in execution_plan
 if task.get("repository_id") == repository_id
 ]
 if repo_tasks:
 task_lines: list[str] =
 for i, task in enumerate(repo_tasks, 1):
 task_name = task.get("name", f"任务 {i}")
 task_desc = task.get("description", "")
 task_lines.append(f"{i}. **{task_name}**: {task_desc}")
 parts.append(
 "## 技术方案任务\n\n"
 "以下是该仓库应实现的任务，请逐任务检查代码是否忠实实现：\n\n"
 + "\n".join(task_lines)
 )
 else:
 parts.append(
 "## 技术方案\n\n"
 "未找到该仓库对应的方案任务，方案符合度维度设为空。"
 )
 else:
 parts.append(
 "## 技术方案\n\n"
 "无上游技术方案数据，方案符合度维度设为空。"
 )
 parts.append("请按照要求输出 JSON 格式的审查报告。")
 return "\n\n".join(parts)
 # ------------------------------------------------------------------
 # 输出解析
 # ------------------------------------------------------------------
 def _parse_review_output(
 self,
 result: AgentResult,
 repository_name: str,
 mr_id: str,
 mr_url: str,
 log: Any,
 ) -> dict[str, Any]:
 """解析 Agent 输出为结构化审查子报告。
 Args:
 result: AgentResult
 repository_name: 仓库名
 mr_id: MR 编号
 mr_url: MR 链接
 log: 绑定了上下文的 logger
 Returns:
 审查子报告 dict
 """
 # 默认空报告
 empty_report: dict[str, Any] = {
 "repository": repository_name,
 "mr_id": mr_id,
 "mr_url": mr_url,
 "summary": "审查未能生成有效报告",
 "dimensions": {
 "code_quality": {"issues": },
 "security": {"issues": },
 "plan_compliance": {"issues": },
 },
 }
 if result.status != "completed" or not result.final_answer:
 log.warning(
 "review_agent_incomplete",
 mr_id=mr_id,
 status=result.status,
 )
 return empty_report
 parsed = _extract_json_from_text(result.final_answer)
 if parsed is None:
 log.warning(
 "review_json_parse_failed",
 mr_id=mr_id,
 output_length=len(result.final_answer),
 )
 return empty_report
 # 确保必要字段存在
 parsed.setdefault("repository", repository_name)
 parsed["mr_id"] = mr_id
 parsed["mr_url"] = mr_url
 parsed.setdefault("summary", "")
 parsed.setdefault("dimensions", {})
 # 确保三个维度都存在
 dims = parsed["dimensions"]
 for dim_key in ("code_quality", "security", "plan_compliance"):
 if dim_key not in dims:
 dims[dim_key] = {"issues": }
 elif not isinstance(dims[dim_key], dict):
 dims[dim_key] = {"issues": }
 elif "issues" not in dims[dim_key]:
 dims[dim_key]["issues"] =
 return parsed
 # ------------------------------------------------------------------
 # 汇总
 # ------------------------------------------------------------------
 def _build_review_summary(
 self,
 approved: bool,
 total_issues: int,
 total_breakdown: dict[str, int],
 mr_count: int,
 errors: list[str],
 ) -> str:
 """构建审查总结文本。"""
 status = "通过" if approved else "未通过"
 parts = [
 f"代码审查{status}。",
 f"共审查 {mr_count} 个 MR，发现 {total_issues} 个问题。",
 f"Critical: {total_breakdown['critical']}，"
 f"Warning: {total_breakdown['warning']}，"
 f"Info: {total_breakdown['info']}。",
 ]
 if errors:
 parts.append(f"有 {len(errors)} 个 MR 审查失败。")
 return " ".join(parts)
 # ------------------------------------------------------------------
 # 飞书通知
 # ------------------------------------------------------------------
 async def _send_review_notification(
 self,
 context: ExecutionContext,
 approved: bool,
 issues_count: int,
 severity_breakdown: dict[str, int],
 plan_title: str,
 mr_count: int,
 log: Any,
 ) -> None:
 """发送飞书审查结果通知卡片。"""
 chat_id = context.render_template(
 context.node_config.get("chat_id", "")
 )
 if not chat_id:
 log.warning("review_notification_no_chat_id")
 return
 try:
 from feishu.cards.code_review_card import build_code_review_card
 card = build_code_review_card(
 approved=approved,
 issues_count=issues_count,
 severity_breakdown=severity_breakdown,
 plan_title=plan_title,
 document_url="", # 暂无文档系统集成
 mr_count=mr_count,
 )
 # 获取 project 飞书配置
 if not context.workflow_execution:
 log.warning("review_notification_no_workflow_execution")
 return
 from workflows.models import WorkflowExecution
 we = await WorkflowExecution.objects.select_related(
 "workflow__project"
 ).aget(id=context.workflow_execution.id)
 project = we.workflow.project if we.workflow else None
 if not project:
 log.warning("review_notification_no_project")
 return
 from agents.tools.feishu_doc_tools import (
 create_feishu_doc_client_for_project,
 )
 from services.feishu_im import FeishuIMClient
 doc_client = await create_feishu_doc_client_for_project(project)
 im_client = FeishuIMClient(
 app_id=doc_client.app_id,
 app_secret=doc_client.app_secret,
 )
 await im_client.send_card(
 receive_id=chat_id,
 receive_id_type="chat_id",
 card=card,
 )
 log.info(
 "review_card_sent",
 chat_id=chat_id,
 approved=approved,
 issues_count=issues_count,
 )
 except Exception as e:
 # 卡片发送失败不阻塞主流程
 log.warning("review_card_send_failed", error=str(e))
