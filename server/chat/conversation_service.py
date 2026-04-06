"""ConversationService — 对话系统核心业务逻辑。
封装对话的 CRUD 操作和发送消息流程（SDKAgentRunner 调用）。
所有方法为 async staticmethod，支持 Django async ORM。
"""
from __future__ import annotations
import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any
import structlog
from django.utils import timezone
# 触发 @tool 注册，确保 chat_tools 中定义的工具在 ToolRegistry 中可用
import agents.tools.chat_tools # noqa: F401
from agents.core.events import (
 KEEPALIVE,
 MESSAGE_COMPLETE,
 TEXT_DELTA,
 THINKING,
 TITLE_GENERATED,
 TOOL_USE_RESULT,
 TOOL_USE_START,
 AgentEvent,
)
from agents.models import AgentSession, ToolCallLog
from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
from chat.models import Conversation, Message
from chat.services import aget_setting_value
from repositories.models import Repository
from services.provider_config import ProviderConfigError, ProviderConfigService
from system.models import SettingKeys
logger = structlog.get_logger(__name__)
# ============================================================================
# Active Runner 注册表（内存级，用于 interrupt API 查找）
# ============================================================================
_active_runners: dict[str, SDKAgentRunner] = {}
def _bare_tool_name(name: str) -> str:
 if name.startswith("mcp__"):
 parts = name.split("__", 2)
 if len(parts) == 3:
 return parts[2]
 return name
def get_active_runner(conversation_id: str) -> SDKAgentRunner | None:
 """获取对话的活跃 runner（供 interrupt API 调用）。
 Args:
 conversation_id: 对话 UUID 字符串
 Returns:
 活跃的 SDKAgentRunner 实例，无活跃对话时返回 None
 """
 return _active_runners.get(conversation_id)
# ============================================================================
# 角色化 System Prompt
# ============================================================================
ROLE_PROMPTS: dict[str, str] = {
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
def _build_system_prompt(
 project_name: str,
 project_id: str,
 role: str = "developer",
) -> str:
 """构建角色化 system prompt。
 根据用户选择的角色生成差异化的 system prompt，
 影响 AI 的回答风格、关注点和术语级别。
 Args:
 project_name: 项目名称
 project_id: 项目 UUID（供工具调用时使用）
 role: 用户角色（developer/pm/designer/qa/general），无效值回退 general
 Returns:
 完整的 system prompt 字符串
 """
 role_prompt = ROLE_PROMPTS.get(role, ROLE_PROMPTS["general"])
 return (
 f"{role_prompt}\n\n"
 f"当前项目：{project_name}\n\n"
 f"你有两种策略应对用户问题：\n\n"
 f"策略一 - 快速检索（定位代码、查看文件、简单问答）：\n"
 f" 调用 search_repository_code / browse_file_content 等工具搜索向量库\n"
 f" 根据需要灵活调用，但要有目的性，避免无方向地反复搜索同一内容\n"
 f" 信息足够时立即回答，不要为了全面而过度检索\n\n"
 f"策略二 - 深度分析（梳理架构、跨模块分析、复杂代码追踪）：\n"
 f" 先用 RAG 搜索掌握基本上下文，辅助判断是否确实需要深度分析\n"
 f" 然后调用 deep_analysis(task_description=...) 启动 Claude Code 分析\n"
 f" deep_analysis 会花较长时间执行，必须等待结果返回后再回答\n"
 f" 不要在 deep_analysis 执行期间调用其他工具\n\n"
 f"根据问题复杂度自主选择策略。\n"
 f"不要在回复中描述工具操作（禁止「让我搜索一下」等叙述），直接调用工具然后回答。\n"
 f"不要重复浏览同一个文件。如果信息已足够，直接给出回答。\n"
 f"用中文回答。\n"
 )
async def _get_tool_names(project_id: str) -> list[str]:
 """根据项目仓库索引状态返回可用工具列表。
 有已索引仓库：注入全部 6 个工具（3 个新检索工具 + 3 个已有项目工具）
 无仓库或未索引：仅注入 get_project_overview（基础信息）
 """
 base_tools = ["get_project_overview"]
 full_tools = base_tools + [
 "browse_file_content",
 "list_project_structure",
 "search_repository_code",
 "list_project_repositories",
 "get_repository_info",
 ]
 has_indexed = await Repository.objects.filter(
 projects__id=project_id,
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
class ConversationService:
 """对话系统业务逻辑服务。"""
 @staticmethod
 async def create_conversation(
 project_id: str,
 title: str = "新对话",
 model: str = "",
 ) -> Conversation:
 """创建新对话。
 Args:
 project_id: 项目 UUID
 title: 对话标题
 model: LLM 模型 ID（为空时运行时使用系统默认）
 Returns:
 新创建的 Conversation 实例
 """
 conversation = await Conversation.objects.acreate(
 project_id=project_id,
 title=title,
 model=model,
 )
 logger.info(
 "conversation_created",
 conversation_id=str(conversation.id),
 project_id=project_id,
 title=title,
 )
 return conversation
 @staticmethod
 async def send_message_stream(
 conversation_id: str,
 content: str,
 role: str = "developer",
 notification_user_id: str | None = None,
 ) -> AsyncGenerator[AgentEvent, None]:
 """流式发送消息，通过 SDKAgentRunner 驱动对话。
 SDKAgentRunner 在独立 asyncio.Task 中运行 SDK，通过 Queue 与
 generator 通信。SSE 断线后 Task 继续运行至完成，确保消息落库。
 Args:
 conversation_id: 对话 UUID
 content: 用户消息内容
 role: 用户角色
 Yields:
 AgentEvent 实例
 """
 from chat.title_service import generate_title, should_generate_title
 # 获取对话
 conversation = await Conversation.objects.select_related("project").aget(
 id=conversation_id,
 is_deleted=False,
 )
 # 保存 user 消息
 await Message.objects.acreate(
 conversation=conversation,
 role=Message.Role.USER,
 content=content,
 )
 # 预生成 assistant 消息 ID
 assistant_msg_id = uuid.uuid4
 # 解析 API key
 try:
 resolved = await ProviderConfigService.aresolve(
 conversation=conversation,
 project=conversation.project,
 )
 except ProviderConfigError as e:
 raise ValueError(str(e)) from e
 api_key = resolved.api_key
 # model 解析：对话级 > 系统级
 system_model = await aget_setting_value(SettingKeys.ANTHROPIC_MODEL) or ""
 model = conversation.model or system_model
 # 构建配置
 session_id = f"chat-{conversation.id}-{uuid.uuid4.hex[:8]}"
 project_name = conversation.project.name
 project_id = str(conversation.project_id)
 # 创建 AgentSession（用于 Hook 持久化）
 agent_session = await AgentSession.objects.acreate(
 session_id=session_id,
 project=conversation.project,
 user=None, # chat 路径暂无真实 user，字段允许 null
 status=AgentSession.Status.RUNNING,
 metadata={
 "conversation_id": str(conversation.id),
 "notification_user_id": notification_user_id or "",
 },
 )
 # Budget 配置：从系统设置读取
 budget_str = await aget_setting_value(SettingKeys.MAX_BUDGET_USD)
 max_budget_usd = float(budget_str) if budget_str else None
 config = SdkRunnerConfig(
 system_prompt=_build_system_prompt(project_name, project_id, role=role),
 model=model,
 project_id=project_id,
 session_id=session_id,
 conversation_id=str(conversation.id),
 api_key=api_key,
 api_base_url=resolved.base_url,
 max_turns=30,
 timeout_seconds=0,
 agent_session=agent_session,
 max_budget_usd=max_budget_usd,
 )
 runner = SDKAgentRunner(config)
 # 注册 active runner（用于 interrupt API 查找）
 conv_id_str = str(conversation.id)
 _active_runners[conv_id_str] = runner
 detached_finalizer = False
 # 流式 yield 事件，拦截 message_complete 补充字段，累积 thinking / tool calls
 accumulated_thinking: list[str] =
 tool_calls_by_id: dict[str, dict[str, Any]] = {}
 deep_analysis_started = False
 deep_analysis_tool_id = ""
 deep_analysis_tool_name = "deep_analysis"
 deep_analysis_tool_input: dict[str, Any] = {}
 deep_analysis_final_answer = ""
 pending_message_complete: AgentEvent | None = None
 async def wait_for_deep_analysis_result -> tuple[Any | None, str | None, str | None]:
 from subagent.models import SubAgentSession, TaskResult
 while True:
 target_session = None
 async for candidate in SubAgentSession.objects.filter(
 task_type=SubAgentSession.TaskType.EXPLORE,
 ).order_by("-id"):
 output = candidate.last_output or {}
 if (
 isinstance(output, dict)
 and output.get("source") == "chat_deep_analysis"
 and output.get("conversation_id") == conv_id_str
 ):
 target_session = candidate
 break
 if target_session is None:
 await asyncio.sleep(1)
 continue
 if target_session.status in {
 SubAgentSession.Status.PENDING,
 SubAgentSession.Status.RUNNING,
 }:
 await asyncio.sleep(2)
 continue
 if target_session.status == SubAgentSession.Status.COMPLETED:
 result = await TaskResult.objects.filter(session=target_session).afirst
 if result:
 text = result.text_output or ""
 if not text and result.raw_output:
 text = str(result.raw_output)[:3000]
 return target_session, text, None
 return target_session, None, "深度分析已完成，但未找到结果输出"
 error_msg = getattr(target_session, "failure_reason", "") or target_session.status
 return target_session, None, f"深度分析失败：{error_msg}"
 async def wait_for_runner_result -> Any | None:
 while runner.result is None:
 sdk_task = getattr(runner, "_sdk_task", None)
 if sdk_task is not None and sdk_task.done:
 break
 await asyncio.sleep(0.2)
 return runner.result
 async def finalize_conversation(publish_title_event: bool) -> list[AgentEvent]:
 final_events: list[AgentEvent] =
 deep_analysis_session = None
 result = await wait_for_runner_result
 final_content = (result.final_answer if result else None) or ""
 if deep_analysis_started:
 (
 deep_analysis_session,
 deep_text,
 deep_error,
 ) = await wait_for_deep_analysis_result
 deep_result_text = deep_text or deep_error or "深度分析未返回结果"
 nonlocal deep_analysis_final_answer
 deep_analysis_final_answer = deep_result_text
 final_content = deep_result_text
 if deep_analysis_tool_id:
 tool_calls_by_id[deep_analysis_tool_id] = {
 "id": deep_analysis_tool_id,
 "name": deep_analysis_tool_name,
 "input": deep_analysis_tool_input,
 "result": deep_result_text[:2000],
 "status": "done",
 }
 # 更新 AgentSession 最终状态（不依赖 SDK Stop hook）
 try:
 session_status = AgentSession.Status.ERROR
 if result and result.status == "completed":
 session_status = AgentSession.Status.COMPLETED
 elif result and result.status == "interrupted":
 session_status = AgentSession.Status.SUSPENDED
 await AgentSession.objects.filter(id=agent_session.id).aupdate(
 status=session_status,
 final_answer=final_content,
 updated_at=timezone.now,
 )
 except Exception:
 logger.exception(
 "agent_session_finalize_failed",
 conversation_id=str(conversation.id),
 session_id=session_id,
 )
 # 构建 metadata：注入 cost、token 用量和 thinking
 msg_metadata: dict[str, Any] = {
 "session_id": session_id,
 "model": model,
 "status": result.status if result else "unknown",
 }
 if result and result.metadata:
 msg_metadata["cost_usd"] = result.metadata.get("cost_usd", 0)
 if result and result.usage:
 msg_metadata["input_tokens"] = result.usage.get("input_tokens", 0)
 msg_metadata["output_tokens"] = result.usage.get("output_tokens", 0)
 if accumulated_thinking:
 msg_metadata["thinking"] = "".join(accumulated_thinking)
 if deep_analysis_started:
 msg_metadata["deep_analysis_session_id"] = deep_analysis_session.session_id if deep_analysis_session else ""
 if deep_analysis_session and isinstance(deep_analysis_session.last_output, dict):
 logs = deep_analysis_session.last_output.get("logs")
 if isinstance(logs, list) and logs:
 msg_metadata["deep_analysis_logs"] = logs
 tool_calls_data = list(tool_calls_by_id.values) or None
 # 保存 assistant 消息（幂等：避免断流后台收尾与前台正常流重复写入）
 if not await Message.objects.filter(id=assistant_msg_id).aexists:
 await Message.objects.acreate(
 id=assistant_msg_id,
 conversation=conversation,
 role=Message.Role.ASSISTANT,
 content=final_content,
 tool_calls=tool_calls_data,
 metadata=msg_metadata,
 )
 # 更新对话时间
 await Conversation.objects.filter(id=conversation.id).aupdate(
 updated_at=timezone.now,
 )
 # 检查是否需要生成标题
 if await should_generate_title(str(conversation.id)):
 title = await generate_title(str(conversation.id), content)
 if title and publish_title_event:
 final_events.append(
 AgentEvent(
 type=TITLE_GENERATED,
 data={"title": title},
 )
 )
 logger.info(
 "stream_message_sent",
 conversation_id=str(conversation.id),
 session_id=session_id,
 status=result.status if result else "unknown",
 )
 if deep_analysis_started:
 try:
 from .push_service import ChatPushService
 await ChatPushService.anotify_deep_analysis_complete(
 user_id=notification_user_id,
 conversation_id=str(conversation.id),
 conversation_title=conversation.title,
 answer_preview=final_content,
 )
 except Exception:
 logger.exception(
 "deep_analysis_push_notify_failed",
 conversation_id=str(conversation.id),
 session_id=session_id,
 )
 _active_runners.pop(conv_id_str, None)
 return final_events
 try:
 async for event in runner.stream(content):
 if event.type == KEEPALIVE:
 yield event
 continue
 event_tool_name = _bare_tool_name(str(event.data.get("tool_name", "") or ""))
 if event.type == THINKING:
 thinking_text = event.data.get("thinking", "")
 if thinking_text:
 accumulated_thinking.append(thinking_text)
 elif event.type == TOOL_USE_START:
 tool_id = str(event.data.get("tool_call_id", "") or "")
 if tool_id and tool_id not in tool_calls_by_id:
 tool_calls_by_id[tool_id] = {
 "id": tool_id,
 "name": event.data.get("tool_name", ""),
 "input": event.data.get("input", {}) or {},
 "result": None,
 "status": "done",
 }
 if event_tool_name == "deep_analysis":
 deep_analysis_started = True
 deep_analysis_tool_id = tool_id
 deep_analysis_tool_name = str(event.data.get("tool_name", "") or "deep_analysis")
 deep_analysis_tool_input = event.data.get("input", {}) or {}
 elif event.type == TOOL_USE_RESULT:
 tool_id = str(event.data.get("tool_call_id", "") or "")
 if tool_id:
 entry = tool_calls_by_id.setdefault(
 tool_id,
 {
 "id": tool_id,
 "name": event.data.get("tool_name", ""),
 "input": event.data.get("input", {}) or {},
 "result": None,
 "status": "done",
 },
 )
 if event.data.get("tool_name"):
 entry["name"] = event.data.get("tool_name", "")
 if event.data.get("input"):
 entry["input"] = event.data.get("input", {}) or {}
 if "result" in event.data:
 entry["result"] = event.data.get("result")
 elif event.type == MESSAGE_COMPLETE:
 # 补充前端契约要求的字段
 result = runner.result
 event.data.setdefault("usage", result.usage if result else {})
 event.data.setdefault("status", result.status if result else "completed")
 event.data.setdefault("iterations", 0)
 event.data.setdefault("model", model)
 # 补充 FeishuBotService 消费所需的字段
 event.data.setdefault("session_id", session_id)
 event.data.setdefault("final_answer", result.final_answer if result else "")
 event.data.setdefault(
 "cost_usd",
 result.metadata.get("cost_usd", 0) if result and result.metadata else 0,
 )
 if deep_analysis_started:
 pending_message_complete = event
 continue
 if deep_analysis_started:
 if event.type in {TEXT_DELTA, THINKING, TOOL_USE_START, TOOL_USE_RESULT, MESSAGE_COMPLETE}:
 if not (event.type == TOOL_USE_START and event_tool_name == "deep_analysis"):
 continue
 yield event
 if deep_analysis_started:
 _deep_session, deep_text, deep_error = await wait_for_deep_analysis_result
 deep_result_text = deep_text or deep_error or "深度分析未返回结果"
 deep_analysis_final_answer = deep_result_text
 if deep_analysis_tool_id:
 tool_calls_by_id[deep_analysis_tool_id] = {
 "id": deep_analysis_tool_id,
 "name": deep_analysis_tool_name,
 "input": deep_analysis_tool_input,
 "result": deep_result_text[:1000],
 "status": "done",
 }
 yield AgentEvent(
 type=TOOL_USE_RESULT,
 data={
 "tool_name": deep_analysis_tool_name,
 "tool_call_id": deep_analysis_tool_id,
 "success": deep_error is None,
 "input": deep_analysis_tool_input,
 "result": deep_result_text[:1000],
 },
 )
 completion_event = pending_message_complete or AgentEvent(type=MESSAGE_COMPLETE, data={})
 completion_event.data.setdefault("usage", runner.result.usage if runner.result else {})
 completion_event.data["status"] = "completed" if deep_error is None else "error"
 completion_event.data["model"] = model
 completion_event.data["session_id"] = session_id
 completion_event.data["final_answer"] = deep_result_text
 completion_event.data["result"] = deep_result_text
 yield completion_event
 for title_event in await finalize_conversation(publish_title_event=True):
 yield title_event
 except GeneratorExit:
 detached_finalizer = True
 logger.info(
 "sse_disconnected",
 conversation_id=str(conversation_id),
 session_id=session_id,
 )
 asyncio.create_task(finalize_conversation(publish_title_event=False))
 return
 finally:
 if not detached_finalizer:
 _active_runners.pop(conv_id_str, None)
 logger.debug(
 "active_runner_cleaned",
 conversation_id=conv_id_str,
 session_id=session_id,
 runner_result_status=runner.result.status if runner.result else "no_result",
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
 """返回对话当前运行态，用于刷新/回访后恢复执行状态。"""
 from subagent.models import SubAgentSession
 active_runner = get_active_runner(conversation_id)
 runtime: dict[str, Any] = {
 "conversation_id": conversation_id,
 "active": active_runner is not None,
 "mode": "chat" if active_runner is not None else None,
 "status": "running" if active_runner is not None else None,
 "session_id": "",
 "task_description": "",
 "progress_message": "",
 "progress_percent": None,
 "logs":,
 }
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
 if latest_deep_session.status in {
 SubAgentSession.Status.PENDING,
 SubAgentSession.Status.RUNNING,
 }:
 runtime.update(
 {
 "active": True,
 "mode": "deep_analysis",
 "status": latest_deep_session.status,
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
 )
 elif runtime["mode"] is None:
 runtime.update(
 {
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
 )
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
