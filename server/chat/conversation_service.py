"""ConversationService — 对话系统 facade 层。
封装对话的 CRUD 操作和 graph 驱动的消息流程。
send_message_stream 通过 LangGraph graph 驱动会话，
核心编排语义由 orchestration.graph 承载。
所有方法为 async staticmethod，支持 Django async ORM。
"""
from __future__ import annotations
import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any, Final
import structlog
# 触发 @tool 注册，确保 chat_tools 中定义的工具在 ToolRegistry 中可用
import agents.tools.chat_tools # noqa: F401
from agents.core.events import (
 DOC_ERROR,
 DOC_SUMMARY,
 ERROR,
 KEEPALIVE,
 MESSAGE_COMPLETE,
 AgentEvent,
)
from agents.models import ToolCallLog
from chat.models import Conversation, Message
from orchestration.graph import get_compiled_graph
from orchestration.models import OrchestrationRun
from orchestration.runner_registry import unregister_runner
from prompts.keys import PromptSlugs
from prompts.services import render_prompt
from repositories.models import Repository
from services.feishu_doc import (
 DocumentNotFoundError,
 FeishuDocAPIError,
 PermissionDeniedError,
 truncate_doc_content,
)
logger = structlog.get_logger(__name__)
def _bare_tool_name(name: str) -> str:
 if name.startswith("mcp__"):
 parts = name.split("__", 2)
 if len(parts) == 3:
 return parts[2]
 return name
# ============================================================================
# 角色化 System Prompt
# ============================================================================
ROLE_PROMPTS: Final[dict[str, str]] = {
 "developer": (
 "你是一名资深开发工程师助手。回答问题时关注代码细节、技术实现方案和最佳实践。"
 "使用专业技术术语，提供代码示例和具体的文件路径引用。"
 "分析问题时从架构设计、性能影响和可维护性角度出发。"
 ),
 "pm": (
 "你是一名项目经理助手。回答问题时关注项目进度、风险评估和资源依赖关系。"
 "使用业务术语，避免过多技术细节。"
 "以要点和时间线形式组织回答，突出影响和优先级。"
 ),
 "designer": (
 "你是一名设计师助手。回答问题时关注用户交互流程、视觉一致性和用户体验。"
 "关注界面布局、信息层级和操作流畅度。"
 "从用户视角分析问题，提供交互优化建议。"
 ),
 "qa": (
 "你是一名 QA 工程师助手。回答问题时关注测试覆盖、边界条件和潜在缺陷模式。"
 "分析代码时识别可能的异常路径、数据验证漏洞和并发问题。"
 "提供具体的测试用例建议和回归测试策略。"
 ),
 "general": (
 "你是一名全能项目助手。根据问题性质平衡技术细节和业务概览。"
 "灵活调整回答深度，简单问题简洁回答，复杂问题详细分析。"
 ),
}
VALID_ROLES = frozenset(ROLE_PROMPTS.keys)
# Phase Task 7: role → slug 映射，用于 _build_system_prompt 分发到 render_prompt
ROLE_SLUG_MAP: Final[dict[str, str]] = {
 "developer": PromptSlugs.CHAT_SYSTEM_DEVELOPER,
 "pm": PromptSlugs.CHAT_SYSTEM_PM,
 "designer": PromptSlugs.CHAT_SYSTEM_DESIGNER,
 "qa": PromptSlugs.CHAT_SYSTEM_QA,
 "general": PromptSlugs.CHAT_SYSTEM_GENERAL,
}
# Phase Task 1: 抽取 _build_system_prompt 内的 fragment 为模块级 Final[str]
# 字节级无损从原函数局部变量复制而来，供 0002 data migration 跨 app import 作为 seed。
# 重构后 _build_system_prompt 的拼接结果与迁移前字节级一致（由 test_role_prompt.py 10 用例保证）。
_STRATEGY_DEEP_ANALYSIS: Final[str] = (
 "用户已开启「深度分析」模式 —— 真正的代码分析由远程 Claude Code 容器完成，\n"
 "你的角色是「路由器 / 派单员」：定位相关仓库 → 一次性并行下发分析任务。\n\n"
 "工作流（严格按顺序）：\n"
 " 1. 调用 list_space_repositories 拿到所有可用仓库的清单与简介；\n"
 " 如果问题关键词指向不明，可用 1-2 次 search_repository_code 缩小到候选仓库\n"
 " （仅用于「这些仓库里哪些跟问题相关」的判断，不用来拼凑答案）\n"
 " 2. 识别出与问题相关的 N 个仓库（N ≥ 1，常见 1-3）\n"
 " 3. 在同一轮回复里**并行**emit N 个 deep_analysis 调用 ——\n"
 " 每个调用绑定一个相关仓库的 repository_id 与一段聚焦的 task_description。\n"
 " 系统会**并行 dispatch N 个 Claude Code 容器**同时分析，效率最高。\n"
 " 4. 所有 deep_analysis 结果回灌后，基于结果汇总作答；除非用户继续追问，否则不再调任何工具。\n\n"
 "硬约束：\n"
 " - RAG 工具（search_repository_code / browse_file_content / list_space_structure）\n"
 " **只能用来「定位哪些仓库相关」**，绝不允许用它们拼凑代码细节作为最终答案。\n"
 " - **必须并行 dispatch**：识别出 N 个相关仓库后，同一轮一次性 emit N 个 deep_analysis；\n"
 " 严禁串行（emit 1 个 → 等结果 → 再 emit 1 个）。\n"
 " - **宁可多开**：拿不准某个仓库是否相关时，多开一个 deep_analysis 也不要漏 ——\n"
 " Claude Code 容器是并行的，多开一个的成本远小于错过相关代码。\n"
 " - **找到就 dispatch**：识别出相关仓库后**立刻** dispatch，不要再做 RAG 验证。\n"
 " - 跨仓库的「为什么 A 跳到 B」类问题，必须同时对 A 和 B 都开 deep_analysis。\n"
)
_STRATEGY_DEFAULT: Final[str] = (
 "回答策略 - 快速检索（定位代码、查看文件、问答、分析、架构梳理）：\n"
 " 调用 search_repository_code / browse_file_content / list_space_structure 等工具搜索向量库与代码\n"
 " 根据需要灵活组合调用，但要有目的性，避免无方向地反复搜索同一内容\n"
 " 信息足够时立即回答，不要为了全面而过度检索\n\n"
 "约束：\n"
 " 本模式下不要主动调用 deep_analysis —— 只有用户在前端显式开启「深度分析」开关\n"
 " 时，系统才会暴露并启用该工具；当前未开启，请用上面的检索工具完成回答。\n"
)
_SEARCH_USAGE_RULES: Final[str] = (
 "\nsearch_repository_code 使用规范（重要 - 用错会一直拿不到结果）：\n"
 " 向量 + BM25 混合搜索对**单一概念的精准 query** 效果最好，对**多概念关键词堆**效果灾难性差。\n\n"
 " ✅ 正确用法（一次搜一个概念，分多次调用）：\n"
 " - search_repository_code(query='studyRoom') # 找入口模块\n"
 " - search_repository_code(query='wrongBook') # 找目标模块\n"
 " - search_repository_code(query='entrance') # 找跳转参数\n"
 " - search_repository_code(query='UserService') # 找类\n"
 " - search_repository_code(query='POST /api/login') # 找接口\n\n"
 " ❌ 错误用法（被系统观察到的真实失败 case）：\n"
 " - search_repository_code(query='studyRoom views classroom report floor friends shareRoom')\n"
 " ↑ 9 个关键词混搜：embedding 信号被稀释、BM25 没有文件能同时高分匹配这么多词 → 0 结果\n"
 " - search_repository_code(query='书房 入口 跳转 错题本')\n"
 " ↑ 多个中文概念混搜：同样会 0 结果\n"
 " - search_repository_code(query='页面跳转')\n"
 " ↑ 太泛的描述词、没有具体符号名 → 召回质量差\n\n"
 " 调优建议：\n"
 " - 优先用**代码层符号**（驼峰命名、文件路径片段、API 路径、类名）做 query\n"
 " - 中文需求先拆成 1-3 个英文 / 拼音关键词分别搜，再合并理解\n"
 " - 0 结果时**不要原样重试**，按返回的 ⚠️ 诊断提示调整\n"
 " - 想要更宽召回时把 min_score 降到 0.3 或更低\n"
)
_CODING_GUIDANCE: Final[str] = (
 "\n编码任务识别：\n"
 " 当用户描述了具体的代码变更需求（如「帮我实现...」「修改...功能」「添加...接口」「重构...」），\n"
 " 你应该调用 create_coding_plan 工具生成结构化技术方案，而非直接给出代码片段。\n"
 " 技术方案包含：① 影响文件列表（文件路径 + 变更类型：新增/修改/删除）② 分步实现步骤。\n"
 " 用户确认方案后才会在 Runner 容器中执行编码。\n"
 " 用户要求调整方案时，调用 update_coding_plan 更新方案内容。\n"
 " 不要同时使用 deep_analysis 和 create_coding_plan -- 它们是不同场景：\n"
 " - deep_analysis：分析理解代码（只读）\n"
 " - create_coding_plan：执行代码变更（写入）\n"
)
_TOOL_BUDGET_RULES: Final[str] = (
 "\n工具调用预算（重要 - 系统层硬约束）：\n"
 " - 你最多有约 50 次工具调用机会（每完成一轮 LLM↔工具来回扣 1）。\n"
 " - 每个工具结果末尾会附 `[预算: X/Y 轮 | ...]`，请把它当作"
 "「还能调几次」的决策信号。\n"
 " - 同一个文件最多被 browse_file_content 调用 3 次，第 4 次起系统会直接拒绝。\n"
 " - 完全相同参数的同一工具第 2 次起会被去重命中（返回上次结果 + 警告），\n"
 " 出现去重命中说明你正在原地打转，必须立刻换思路而非再调一次。\n"
 " - 剩余 ≤ 5 轮时收束作答；剩余 ≤ 1 轮时系统会强制不提供工具，\n"
 " 所以请在还有余量时主动给答案，不要等到被强制收束。\n"
 " - 如果当前信息不足以完整作答，直接说「基于已检索内容，可以确认 X、Y；\n"
 " Z 部分需要进一步访问 ABC 文件」也比无脑循环检索强。\n"
)
_ENDING_RULES: Final[str] = (
 "不要在回复中描述工具操作（禁止「让我搜索一下」等叙述），直接调用工具然后回答。\n"
 "不要重复浏览同一个文件。如果信息已足够，直接给出回答。\n"
 "用中文回答。\n"
)
async def _build_system_prompt(
 project_name: str,
 project_id: str,
 role: str = "developer",
 *,
 force_deep_analysis: bool = False,
 project_context_line: str = "",
) -> str:
 """构建角色化 system prompt（异步版，Phase Task 7 fragment 化）。
 Phase: 每个 fragment 独立从 Prompt Center 渲染 + fallback 双轨，
 条件拼接逻辑保留在 Python 层（不进 Jinja2 控制流 DSL）。
 结尾规则 _ENDING_RULES 保留 Python 字面量(非可运营 Prompt)，不占用 slug。
 Args:
 project_name: 空间名称
 project_id: 空间 UUID（供工具调用时使用）
 role: 用户角色（developer/pm/designer/qa/general），无效值回退 general
 force_deep_analysis: 用户开启了深度分析开关，强制走策略二
 Returns:
 完整的 system prompt 字符串
 """
 # 1. 角色 fragment
 role_slug = ROLE_SLUG_MAP.get(role, PromptSlugs.CHAT_SYSTEM_GENERAL)
 role_fallback = ROLE_PROMPTS.get(role, ROLE_PROMPTS["general"])
 role_fragment = await render_prompt(
 role_slug,
 project_id=project_id,
 variables={},
 fallback=role_fallback,
 )
 # 2. 策略 fragment（条件分支保留 Python 层，防并行调两个 strategy slug）
 if force_deep_analysis:
 strategy_slug = PromptSlugs.CHAT_STRATEGY_DEEP_ANALYSIS
 strategy_fallback = _STRATEGY_DEEP_ANALYSIS
 else:
 strategy_slug = PromptSlugs.CHAT_STRATEGY_DEFAULT
 strategy_fallback = _STRATEGY_DEFAULT
 strategy_fragment = await render_prompt(
 strategy_slug,
 project_id=project_id,
 variables={},
 fallback=strategy_fallback,
 )
 # 3. 编码指引 fragment（无条件）
 coding_guidance_fragment = await render_prompt(
 PromptSlugs.CHAT_CODING_GUIDANCE,
 project_id=project_id,
 variables={},
 fallback=_CODING_GUIDANCE,
 )
 # 4. 组装（结尾规则 _ENDING_RULES、预算约束 _TOOL_BUDGET_RULES、检索工具
 # 使用规范 _SEARCH_USAGE_RULES 都保持 Python 字面量 — 与代码硬约束语义
 # 强耦合（如 _ChatToolBudget 的 max_turns、search_repository_code 的
 # min_score 默认值），不适合外置成可运营 Prompt（一旦在 Prompt Center
 # 里被改坏，模型会"以为"配置是另一套）。
 # 装配顺序：角色 → 策略 → 编码 → 检索用法 → 预算 → 结尾。
 # 检索用法放在策略之后是因为它和"如何调用 RAG"强相关。
 project_line = project_context_line or f"当前空间：{project_name}"
 return (
 f"{role_fragment}\n\n"
 f"{project_line}\n\n"
 f"{strategy_fragment}\n"
 f"{coding_guidance_fragment}\n"
 f"{_SEARCH_USAGE_RULES}\n"
 f"{_TOOL_BUDGET_RULES}\n"
 f"{_ENDING_RULES}"
 )
async def _get_tool_names(space_id: str) -> list[str]:
 """根据项目仓库索引状态返回可用工具列表。
 有已索引仓库：注入全部工具（检索工具 + 项目工具 + 编码工具）
 无仓库或未索引：仅注入 get_space_overview（基础信息）
 """
 base_tools = ["get_space_overview"]
 full_tools = base_tools + [
 "browse_file_content",
 "list_space_structure",
 "search_repository_code",
 "list_space_repositories",
 "get_repository_info",
 "create_coding_plan",
 "update_coding_plan",
 ]
 has_indexed = await Repository.objects.filter(
 projects__id=space_id,
 index_status="indexed",
 is_deleted=False,
 ).aexists
 return full_tools if has_indexed else base_tools
def _coerce_reference_item(
 tool_name: str,
 result_output: dict[str, Any],
 fallback_repo: str,
) -> dict[str, Any] | None:
 path = str(
 result_output.get("path")
 or result_output.get("file_path")
 or result_output.get("file")
 or ""
 )
 line_start = result_output.get("line_start") or result_output.get("start_line")
 line_end = result_output.get("line_end") or result_output.get("end_line")
 summary = str(
 result_output.get("summary")
 or result_output.get("snippet")
 or result_output.get("content_preview")
 or result_output.get("text")
 or ""
 ).strip
 if not (path or summary):
 return None
 line = ""
 if line_start and line_end:
 line = f"L{line_start}-L{line_end}"
 elif line_start:
 line = f"L{line_start}"
 return {
 "repository": fallback_repo,
 "path": path,
 "line": line,
 "tool_name": tool_name,
 "summary": summary[:160],
 }
def _extract_reference_candidates(tool_name: str, arguments: dict[str, Any], result_output: Any) -> list[dict[str, Any]]:
 repo = str(
 arguments.get("repository")
 or arguments.get("repository_name")
 or arguments.get("repo")
 or "项目上下文"
 )
 items: list[dict[str, Any]] =
 if isinstance(result_output, dict):
 candidate = _coerce_reference_item(tool_name, result_output, repo)
 if candidate:
 items.append(candidate)
 for key in ("results", "items", "matches"):
 values = result_output.get(key)
 if not isinstance(values, list):
 continue
 for value in values[:5]:
 if isinstance(value, dict):
 candidate = _coerce_reference_item(tool_name, value, repo)
 if candidate:
 items.append(candidate)
 elif isinstance(result_output, list):
 for value in result_output[:5]:
 if isinstance(value, dict):
 candidate = _coerce_reference_item(tool_name, value, repo)
 if candidate:
 items.append(candidate)
 return items
async def extract_reference_summaries(session_id: str, limit: int = 5) -> list[dict[str, Any]]:
 """Summarize tool-call outputs for compact card-friendly references."""
 if not session_id:
 return
 references: list[dict[str, Any]] =
 seen: set[tuple[str, str, str]] = set
 logs = ToolCallLog.objects.filter(
 session__session_id=session_id,
 result_success=True,
 ).order_by("started_at")
 async for log in logs:
 for item in _extract_reference_candidates(log.tool_name, log.arguments or {}, log.result_output):
 key = (item["repository"], item["path"], item["line"])
 if key in seen:
 continue
 seen.add(key)
 references.append(item)
 if len(references) >= limit:
 return references
 return references
async def _handle_waiting_state(
 *,
 state: dict[str, Any],
 orch_run: OrchestrationRun,
 graph_config: dict[str, Any],
 conversation: Conversation,
 assistant_msg_id: uuid.UUID,
 agent_session: Any,
 session_id: str,
 model: str,
 content: str,
 notification_user_id: str | None,
 conv_id_str: str,
 do_finalize: Any,
) -> None:
 """处理 graph interrupt WAITING 状态：更新 OrchestrationRun + 注册 BarrierManager barrier。
 barrier 满足后由 _on_barrier_complete 回调执行 graph resume + finalize_conversation 落库。
 """
 from langgraph.types import Command
 from orchestration.barrier import get_barrier_manager
 await OrchestrationRun.objects.filter(id=orch_run.id).aupdate(
 status=OrchestrationRun.Status.WAITING,
 phase="waiting",
 )
 blocking_tasks = state.get("blocking_tasks", )
 async def _on_barrier_complete(results: list[dict[str, Any]]) -> None:
 """barrier 满足后：resume graph + finalize。"""
 try:
 graph_for_resume = await get_compiled_graph
 final_state: dict[str, Any] = {}
 async for chunk in graph_for_resume.astream(
 Command(resume=results),
 config=graph_config,
 stream_mode=["custom", "values"],
 version="v2",
 ):
 if chunk["type"] == "values":
 final_state = chunk["data"]
 await OrchestrationRun.objects.filter(id=orch_run.id).aupdate(
 status=OrchestrationRun.Status.COMPLETED,
 phase=final_state.get("phase", "completed"),
 )
 await do_finalize(
 conversation=conversation,
 assistant_msg_id=assistant_msg_id,
 final_content=final_state.get("final_answer", ""),
 accumulated_thinking=final_state.get("accumulated_thinking", ),
 tool_calls=final_state.get("tool_calls", ),
 result_metadata=final_state.get("result_metadata", {}),
 agent_session=agent_session,
 session_id=session_id,
 model=model,
 user_message=content,
 notification_user_id=notification_user_id,
 publish_title_event=True,
 )
 logger.info(
 "barrier_resume_finalized",
 conversation_id=conv_id_str,
 session_id=session_id,
 )
 except Exception:
 logger.exception(
 "barrier_resume_error",
 conversation_id=conv_id_str,
 session_id=session_id,
 )
 await OrchestrationRun.objects.filter(id=orch_run.id).aupdate(
 status=OrchestrationRun.Status.ERROR,
 phase="error",
 )
 await Conversation.objects.filter(id=conversation.id).aupdate(
 status=Conversation.Status.ERROR,
 )
 # 写入兜底错误消息，避免前端只显示 placeholder 而没有任何反馈
 try:
 from chat.models import Message
 error_reason = ""
 for r in results:
 if not r.get("success"):
 error_reason = r.get("error", "")
 break
 if not await Message.objects.filter(id=assistant_msg_id).aexists:
 await Message.objects.acreate(
 id=assistant_msg_id,
 conversation=conversation,
 role=Message.Role.ASSISTANT,
 content=error_reason or "深度分析任务执行失败，请稍后重试。",
 metadata={
 "session_id": session_id,
 "model": model,
 "status": "error",
 },
 )
 except Exception:
 logger.exception(
 "barrier_resume_error_message_failed",
 conversation_id=conv_id_str,
 )
 async def _on_barrier_progress(completed: int, total: int) -> None:
 logger.info(
 "barrier_task_progress",
 conversation_id=conv_id_str,
 completed_count=completed,
 total_count=total,
 )
 barrier = get_barrier_manager
 await barrier.register(
 run_id=str(orch_run.run_id),
 thread_id=conv_id_str,
 tasks=blocking_tasks,
 graph_config=graph_config,
 on_complete=_on_barrier_complete,
 on_progress=_on_barrier_progress,
 )
 logger.info(
 "graph_waiting_barrier_registered",
 conversation_id=conv_id_str,
 blocking_task_count=len(blocking_tasks),
 )
def _build_message_complete_event(
 *,
 final_content: str,
 result_metadata: dict[str, Any],
 model: str,
 session_id: str,
) -> AgentEvent:
 """构建兜底 MESSAGE_COMPLETE 事件，确保前端能收到最终正文。"""
 payload: dict[str, Any] = {
 "final_answer": final_content,
 "result": final_content,
 "status": result_metadata.get("status", "completed"),
 "model": model,
 "session_id": session_id,
 "usage": {
 "input_tokens": result_metadata.get("input_tokens", 0),
 "output_tokens": result_metadata.get("output_tokens", 0),
 },
 }
 if "cost_usd" in result_metadata:
 payload["cost_usd"] = result_metadata.get("cost_usd", 0)
 return AgentEvent(type=MESSAGE_COMPLETE, data=payload)
class ConversationService:
 """对话系统业务逻辑服务。"""
 @staticmethod
 async def create_conversation(
 space_id: str,
 title: str = "新对话",
 model: str = "",
 ) -> Conversation:
 """创建新对话。
 Args:
 space_id: 空间 UUID
 title: 对话标题
 model: LLM 模型 ID（为空时运行时使用系统默认）
 Returns:
 新创建的 Conversation 实例
 """
 conversation = await Conversation.objects.acreate(
 project_id=space_id,
 title=title,
 model=model,
 )
 logger.info(
 "conversation_created",
 conversation_id=str(conversation.id),
 space_id=space_id,
 title=title,
 )
 return conversation
 @staticmethod
 async def _fetch_doc_for_context(
 project: Any,
 doc_id: str,
 ) -> tuple[str | None, AgentEvent]:
 """读取飞书文档并返回 (markdown_content, sse_event)。
 成功时返回 (markdown, doc_summary_event)。
 失败时返回 (None, doc_error_event)。
 """
 from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project
 try:
 client = await create_feishu_doc_client_for_project(project)
 except ValueError as e:
 return None, AgentEvent(
 type=DOC_ERROR,
 data={"error_type": "not_configured", "message": str(e)},
 )
 try:
 markdown, _blocks = await client.get_document_content(doc_id)
 # 提取标题：取第一个非空行，去掉 # 前缀
 lines = [ln.strip for ln in markdown.split("\n") if ln.strip]
 title = lines[0].lstrip("# ").strip if lines else "飞书文档"
 word_count = len(markdown)
 preview = "\n".join(lines[:3])
 markdown, was_truncated = truncate_doc_content(markdown)
 return markdown, AgentEvent(
 type=DOC_SUMMARY,
 data={
 "doc_title": title,
 "word_count": word_count,
 "preview": preview,
 "truncated": was_truncated,
 "truncated_length": len(markdown) if was_truncated else word_count,
 },
 )
 except PermissionDeniedError as e:
 return None, AgentEvent(
 type=DOC_ERROR,
 data={"error_type": "permission_denied", "message": str(e)},
 )
 except DocumentNotFoundError as e:
 return None, AgentEvent(
 type=DOC_ERROR,
 data={"error_type": "not_found", "message": str(e)},
 )
 except FeishuDocAPIError as e:
 logger.warning("feishu_doc_read_failed", doc_id=doc_id, error=str(e))
 return None, AgentEvent(
 type=DOC_ERROR,
 data={"error_type": "unknown", "message": str(e)},
 )
 @staticmethod
 async def send_message_stream(
 conversation_id: str,
 content: str,
 role: str = "developer",
 notification_user_id: str | None = None,
 force_deep_analysis: bool = False,
 feishu_doc_id: str = "",
 project_context_line: str | None = None,
 search_branch: str | None = None,
 ) -> AsyncGenerator[AgentEvent, None]:
 """流式发送消息 — 通过 LangGraph graph 驱动。
 签名保持不变，内部改为：
 1. 保存 user 消息
 2. 构建 SDK 配置
 3. 创建 OrchestrationRun
 4. 在独立 Task 中运行 graph.astream，通过 Queue 桥接事件
 5. yield 事件（带 keepalive 心跳）
 6. graph 完成后调用 finalize_conversation 落库
 """
 # lazy import 避免循环依赖（config.py 导入本模块的 _build_system_prompt）
 from chat.config import build_sdk_config
 from chat.finalize import finalize_conversation as do_finalize
 conversation = await Conversation.objects.select_related("project").aget(
 id=conversation_id,
 is_deleted=False,
 )
 await Message.objects.acreate(
 conversation=conversation,
 role=Message.Role.USER,
 content=content,
 )
 # 对话进入进行中状态
 conversation.status = Conversation.Status.RUNNING
 await conversation.asave(update_fields=["status"])
 # 飞书文档预处理（per: 读取成功即自动注入上下文）
 doc_context_prefix = ""
 if feishu_doc_id:
 doc_markdown, doc_event = await ConversationService._fetch_doc_for_context(
 conversation.project, feishu_doc_id,
 )
 yield doc_event # 推送 doc_summary 或 doc_error
 if doc_markdown:
 doc_title = doc_event.data.get("doc_title", "飞书文档")
 doc_context_prefix = (
 f"\n\n---\n## 参考文档：{doc_title}\n\n"
 f"{doc_markdown}\n---\n\n"
 )
 assistant_msg_id = uuid.uuid4
 sdk_config, agent_session = await build_sdk_config(
 conversation,
 role=role,
 notification_user_id=notification_user_id,
 force_deep_analysis=force_deep_analysis,
 project_context_line=project_context_line,
 )
 session_id = sdk_config.session_id
 model = sdk_config.model
 conv_id_str = str(conversation.id)
 orch_run = await OrchestrationRun.objects.acreate(
 conversation=conversation,
 thread_id=conv_id_str,
 status=OrchestrationRun.Status.RUNNING,
 phase=OrchestrationRun.Phase.PLANNING,
 )
 branch_for_tools = (search_branch or "").strip or None
 graph_config: dict[str, Any] = {
 "configurable": {
 "thread_id": conv_id_str,
 "conversation_id": conv_id_str,
 "api_key": sdk_config.api_key,
 "api_base_url": sdk_config.api_base_url,
 "model": model,
 "session_id": session_id,
 "system_prompt": sdk_config.system_prompt,
 "space_id": sdk_config.space_id,
 "role": role,
 "agent_session_id": str(agent_session.id),
 "notification_user_id": notification_user_id or "",
 "max_budget_usd": sdk_config.max_budget_usd,
 "default_search_branch": branch_for_tools,
 # 必须把开关透到 graph_config —— executing_node 会用 cfg 重新构造
 # ChatRunnerConfig，少传这个字段会让 _get_tool_names 拿不到
 # deep_analysis 工具，前端开了「深度分析」却始终走不到远程 runner。
 "force_deep_analysis": sdk_config.force_deep_analysis,
 }
 }
 graph = await get_compiled_graph
 event_queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue(maxsize=200)
 graph_state_holder: dict[str, Any] = {}
 async def _run_graph -> None:
 """在独立 Task 中运行 graph，SSE 断连后仍继续执行。"""
 try:
 final_state: dict[str, Any] = {}
 async for chunk in graph.astream(
 {"user_message": doc_context_prefix + content, "run_id": str(orch_run.run_id)},
 config=graph_config,
 stream_mode=["custom", "values"],
 version="v2",
 ):
 if chunk["type"] == "custom":
 event_data = chunk["data"]
 event = AgentEvent(
 type=event_data["type"],
 data=event_data.get("data", {}),
 )
 try:
 event_queue.put_nowait(event)
 except asyncio.QueueFull:
 pass
 elif chunk["type"] == "values":
 final_state = chunk["data"]
 graph_state_holder.update(final_state)
 except Exception as exc:
 logger.exception(
 "graph_run_error",
 conversation_id=conv_id_str,
 session_id=session_id,
 )
 graph_state_holder["phase"] = "error"
 graph_state_holder["result_metadata"] = {"status": "error"}
 try:
 event_queue.put_nowait(
 AgentEvent(type=ERROR, data={"message": str(exc)}),
 )
 except asyncio.QueueFull:
 pass
 finally:
 try:
 event_queue.put_nowait(None) # 哨兵：通知消费循环 graph 结束
 except asyncio.QueueFull:
 pass
 graph_task = asyncio.create_task(_run_graph)
 detached_finalizer = False
 message_complete_seen = False
 try:
 # 事件消费循环（带 keepalive 心跳）
 while True:
 try:
 event = await asyncio.wait_for(
 event_queue.get, timeout=15.0,
 )
 except TimeoutError:
 yield AgentEvent(type=KEEPALIVE, data={})
 continue
 if event is None:
 break
 if event.type == MESSAGE_COMPLETE:
 message_complete_seen = True
 event.data.setdefault("model", model)
 event.data.setdefault("session_id", session_id)
 yield event
 # graph 完成，等待 Task 清理
 await graph_task
 state = graph_state_holder
 phase = state.get("phase", "")
 if phase == "waiting":
 # graph interrupt — blocking tasks 等待中
 await _handle_waiting_state(
 state=state,
 orch_run=orch_run,
 graph_config=graph_config,
 conversation=conversation,
 assistant_msg_id=assistant_msg_id,
 agent_session=agent_session,
 session_id=session_id,
 model=model,
 content=content,
 notification_user_id=notification_user_id,
 conv_id_str=conv_id_str,
 do_finalize=do_finalize,
 )
 else:
 # 正常完成 / 错误
 final_content = state.get("final_answer", "")
 accumulated_thinking = state.get("accumulated_thinking", )
 tool_calls = state.get("tool_calls", )
 result_metadata = state.get("result_metadata", {})
 is_error = state.get("phase") == "error"
 await OrchestrationRun.objects.filter(id=orch_run.id).aupdate(
 status=OrchestrationRun.Status.ERROR if is_error else OrchestrationRun.Status.COMPLETED,
 phase=state.get("phase", OrchestrationRun.Phase.COMPLETED),
 )
 final_events = await do_finalize(
 conversation=conversation,
 assistant_msg_id=assistant_msg_id,
 final_content=final_content,
 accumulated_thinking=accumulated_thinking,
 tool_calls=tool_calls,
 result_metadata=result_metadata,
 agent_session=agent_session,
 session_id=session_id,
 model=model,
 user_message=content,
 notification_user_id=notification_user_id,
 publish_title_event=True,
 )
 if not message_complete_seen:
 yield _build_message_complete_event(
 final_content=final_content,
 result_metadata=result_metadata,
 model=model,
 session_id=session_id,
 )
 for title_event in final_events:
 yield title_event
 except GeneratorExit:
 detached_finalizer = True
 logger.info(
 "sse_disconnected",
 conversation_id=conv_id_str,
 session_id=session_id,
 )
 async def _background_finalize -> None:
 """后台等待 graph 完成并执行收尾。"""
 try:
 await graph_task
 state = graph_state_holder
 phase = state.get("phase", "")
 if phase == "waiting":
 await _handle_waiting_state(
 state=state,
 orch_run=orch_run,
 graph_config=graph_config,
 conversation=conversation,
 assistant_msg_id=assistant_msg_id,
 agent_session=agent_session,
 session_id=session_id,
 model=model,
 content=content,
 notification_user_id=notification_user_id,
 conv_id_str=conv_id_str,
 do_finalize=do_finalize,
 )
 else:
 is_error = state.get("phase") == "error"
 await OrchestrationRun.objects.filter(id=orch_run.id).aupdate(
 status=OrchestrationRun.Status.ERROR if is_error else OrchestrationRun.Status.COMPLETED,
 phase=state.get("phase", OrchestrationRun.Phase.COMPLETED),
 )
 await do_finalize(
 conversation=conversation,
 assistant_msg_id=assistant_msg_id,
 final_content=state.get("final_answer", ""),
 accumulated_thinking=state.get("accumulated_thinking", ),
 tool_calls=state.get("tool_calls", ),
 result_metadata=state.get("result_metadata", {}),
 agent_session=agent_session,
 session_id=session_id,
 model=model,
 user_message=content,
 notification_user_id=notification_user_id,
 publish_title_event=False,
 )
 except Exception:
 logger.exception(
 "background_finalize_error",
 conversation_id=conv_id_str,
 )
 await Conversation.objects.filter(id=conversation.id).aupdate(
 status=Conversation.Status.ERROR,
 )
 asyncio.create_task(_background_finalize)
 return
 finally:
 if not detached_finalizer:
 unregister_runner(conv_id_str)
 logger.debug(
 "conversation_facade_completed",
 conversation_id=conv_id_str,
 session_id=session_id,
 )
 @staticmethod
 async def list_conversations -> list[Conversation]:
 """返回未删除对话列表，按 updated_at 降序。"""
 return [
 c async for c in Conversation.objects.filter(
 is_deleted=False,
 ).order_by("-updated_at")
 ]
 @staticmethod
 async def get_conversation_with_messages(
 conversation_id: str,
 ) -> dict[str, Any]:
 """返回对话详情 + 全部历史消息。
 Args:
 conversation_id: 对话 UUID
 Returns:
 包含 conversation 和 messages 的 dict
 Raises:
 Conversation.DoesNotExist: 对话不存在或已删除
 """
 conversation = await Conversation.objects.aget(
 id=conversation_id,
 is_deleted=False,
 )
 messages = [
 msg async for msg in Message.objects.filter(
 conversation=conversation,
 ).order_by("created_at")
 ]
 return {
 "conversation": conversation,
 "messages": messages,
 }
 @staticmethod
 async def get_conversation_runtime(
 conversation_id: str,
 ) -> dict[str, Any]:
 """返回对话当前运行态 — 从 OrchestrationRun DB 读取真实 phase/status。"""
 from datetime import timedelta
 from django.utils import timezone
 from subagent.models import SubAgentSession
 terminal_statuses = {
 OrchestrationRun.Status.COMPLETED,
 OrchestrationRun.Status.ERROR,
 OrchestrationRun.Status.INTERRUPTED,
 }
 from uuid import UUID
 try:
 conv_uuid = UUID(conversation_id)
 except ValueError:
 conv_uuid = conversation_id
 orch_run = await OrchestrationRun.objects.filter(
 conversation_id=conv_uuid,
 ).order_by("-created_at").afirst
 is_active = False
 orch_phase: str | None = None
 orch_status: str | None = None
 orch_run_id = ""
 task_progress: dict[str, int] | None = None
 if orch_run is not None:
 if orch_run.status in terminal_statuses:
 is_active = False
 elif (
 orch_run.status in {OrchestrationRun.Status.RUNNING, OrchestrationRun.Status.WAITING}
 and orch_run.created_at < timezone.now - timedelta(hours=1)
 ):
 # 超时窗口：running/waiting 超 1 小时 → 视为 error，auto-close
 await OrchestrationRun.objects.filter(id=orch_run.id).aupdate(
 status=OrchestrationRun.Status.ERROR,
 phase=OrchestrationRun.Phase.ERROR,
 )
 is_active = False
 orch_status = OrchestrationRun.Status.ERROR
 else:
 is_active = True
 if orch_status is None:
 orch_status = orch_run.status
 orch_phase = orch_run.phase
 orch_run_id = str(orch_run.run_id)
 progress_meta = orch_run.metadata.get("progress") if isinstance(orch_run.metadata, dict) else None
 if isinstance(progress_meta, dict):
 task_progress = {
 "completed": progress_meta.get("completed", 0),
 "total": progress_meta.get("total", 0),
 }
 # 从 phase 推导向后兼容 mode
 mode: str | None = None
 if is_active:
 mode = "chat"
 # SSE 单向无状态，浏览器刷新会让前端流式渲染全部丢失。executing_node 把
 # 实时累积态写到 orch_run.metadata['streaming_snapshot']（详见
 # orchestration.graph._StreamingSnapshot）。仅在 is_active=True 时透传 —
 # 完成态由前端走 hydrateMessages 路径渲染 final assistant message，再读
 # snapshot 会导致 bubble 重影。
 streaming_snapshot: dict[str, Any] | None = None
 if is_active and orch_run is not None and isinstance(orch_run.metadata, dict):
 snap = orch_run.metadata.get("streaming_snapshot")
 if isinstance(snap, dict):
 streaming_snapshot = snap
 runtime: dict[str, Any] = {
 "conversation_id": conversation_id,
 "active": is_active,
 "mode": mode,
 "status": orch_status,
 "orchestration_run_id": orch_run_id,
 "phase": orch_phase,
 "task_progress": task_progress,
 "session_id": "",
 "task_description": "",
 "progress_message": "",
 "progress_percent": None,
 "logs":,
 "coding_session": None,
 "streaming_snapshot": streaming_snapshot,
 }
 # deep_analysis 会话信息（向后兼容）
 latest_deep_session = None
 async for candidate in SubAgentSession.objects.filter(
 task_type=SubAgentSession.TaskType.EXPLORE,
 main_session__metadata__conversation_id=conversation_id,
 ).order_by("-id"):
 output = candidate.last_output or {}
 if isinstance(output, dict) and output.get("source") == "chat_deep_analysis":
 latest_deep_session = candidate
 break
 if latest_deep_session is not None:
 output = latest_deep_session.last_output or {}
 progress = output.get("progress", {}) if isinstance(output, dict) else {}
 logs = output.get("logs", ) if isinstance(output, dict) else
 deep_info = {
 "session_id": latest_deep_session.session_id,
 "task_description": output.get("task_description", "")
 if isinstance(output, dict)
 else "",
 "progress_message": progress.get("message", "")
 if isinstance(progress, dict)
 else "",
 "progress_percent": progress.get("progress")
 if isinstance(progress, dict)
 else None,
 "logs": logs if isinstance(logs, list) else,
 }
 if latest_deep_session.status in {
 SubAgentSession.Status.PENDING,
 SubAgentSession.Status.RUNNING,
 }:
 runtime.update(
 {
 "active": True,
 "mode": "deep_analysis",
 "status": latest_deep_session.status,
 **deep_info,
 }
 )
 else:
 # 终态：ERROR / TIMEOUT / CANCELLED / COMPLETED
 runtime.update(
 {
 **deep_info,
 "deep_analysis_status": latest_deep_session.status,
 "deep_analysis_error": latest_deep_session.failure_reason
 or latest_deep_session.last_error
 or "",
 }
 )
 # 如果 deep analysis 已失败但主流程还在 waiting，
 # 将 active 设为 False 避免前端无限轮询
 if (
 latest_deep_session.status
 in {
 SubAgentSession.Status.ERROR,
 SubAgentSession.Status.TIMEOUT,
 SubAgentSession.Status.CANCELLED,
 }
 and orch_run
 and orch_run.status == OrchestrationRun.Status.WAITING
 ):
 is_active = False
 runtime["active"] = False
 runtime["status"] = latest_deep_session.status
 if runtime.get("mode") is None:
 runtime["mode"] = "deep_analysis"
 # CodingSession 运行态检测 (Phase)
 from chat.models import CodingSession
 coding_session = await CodingSession.objects.filter(
 conversation_id=conversation_id,
 status__in=[CodingSession.Status.RUNNING, CodingSession.Status.AWAITING_CONFIRMATION],
 ).order_by("-created_at").afirst
 if coding_session is not None:
 runtime["active"] = True
 runtime["mode"] = "coding"
 runtime["coding_session"] = {
 "id": str(coding_session.id),
 "status": coding_session.status,
 "tech_plan": coding_session.tech_plan,
 "affected_files": coding_session.affected_files,
 "branch_name": coding_session.branch_name,
 "confirmation_step": coding_session.confirmation_step,
 "suggested_commit_message": coding_session.suggested_commit_message,
 "suggested_pr_title": coding_session.suggested_pr_title,
 "suggested_pr_description": coding_session.suggested_pr_description,
 "conflict_check_result": coding_session.conflict_check_result or None,
 "diff_summary": coding_session.diff_summary or None,
 }
 # Phase: 从 SubAgentSession.last_output 获取编码中间产出（per, ）
 if coding_session.subagent_session_id:
 subagent_session = await SubAgentSession.objects.filter(
 id=coding_session.subagent_session_id,
 ).afirst
 if subagent_session and isinstance(subagent_session.last_output, dict):
 coding_progress = subagent_session.last_output.get("coding_progress")
 if coding_progress and isinstance(coding_progress, dict):
 runtime["coding_session"]["coding_progress"] = {
 "modified_files": coding_progress.get("modified_files", ),
 "recent_tool_calls": coding_progress.get("recent_tool_calls", ),
 "updated_at": coding_progress.get("updated_at", ""),
 }
 else:
 # 检查是否有刚完成/失败的 CodingSession（最近 5 分钟内）
 recent_cutoff = timezone.now - timedelta(minutes=5)
 recent_coding = await CodingSession.objects.filter(
 conversation_id=conversation_id,
 status__in=[CodingSession.Status.COMPLETED, CodingSession.Status.FAILED],
 updated_at__gte=recent_cutoff,
 ).order_by("-updated_at").afirst
 if recent_coding is not None:
 runtime["coding_session"] = {
 "id": str(recent_coding.id),
 "status": recent_coding.status,
 "pr_url": recent_coding.pr_url,
 "branch_name": recent_coding.branch_name,
 "error_message": recent_coding.error_message,
 "affected_files": recent_coding.affected_files,
 }
 return runtime
 @staticmethod
 async def delete_conversation(conversation_id: str) -> None:
 """软删除对话。
 Args:
 conversation_id: 对话 UUID
 Raises:
 Conversation.DoesNotExist: 对话不存在或已删除
 """
 updated = await Conversation.objects.filter(
 id=conversation_id,
 is_deleted=False,
 ).aupdate(is_deleted=True)
 if updated == 0:
 raise Conversation.DoesNotExist(
 f"对话不存在或已删除: {conversation_id}"
 )
 logger.info(
 "conversation_deleted",
 conversation_id=conversation_id,
 )
