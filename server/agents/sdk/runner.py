"""SDKAgentRunner：封装 Claude Agent SDK 的核心运行模块。
通过 query 驱动完整对话循环，将 SDK 流式事件转换为 AgentEvent，
并通过 asyncio.Queue 桥接 SSE generator。
"""
from __future__ import annotations
import asyncio
import os
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator, Literal
import structlog
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query
from agents.core.events import ERROR, KEEPALIVE, MESSAGE_COMPLETE, AgentEvent
from agents.core.result import AgentResult
from agents.sdk.event_adapter import EventAdapter
from agents.sdk.hooks import create_post_tool_use_hook
from agents.sdk.mcp_adapter import build_allowed_tools, create_chat_tools_mcp_server
logger = structlog.get_logger(__name__)
_SDK_SHUTDOWN_ERROR_MARKERS = (
 "ProcessTransport is not ready for writing",
 "Tool permission stream closed before response received",
 "Stream closed",
)
def _unwrap_exception(exc: BaseException) -> str:
 """从 ExceptionGroup 等嵌套异常中提取可读的错误信息。"""
 if isinstance(exc, BaseExceptionGroup):
 parts = [str(exc)]
 for sub in exc.exceptions:
 parts.append(f" Caused by: {type(sub).__name__}: {sub}")
 return "\n".join(parts)
 return str(exc)
def _is_sdk_shutdown_race(error_msg: str) -> bool:
 """判断是否为 SDK/CLI 关闭阶段的已知传输竞态错误。"""
 return any(marker in error_msg for marker in _SDK_SHUTDOWN_ERROR_MARKERS)
@contextmanager
def clean_claude_env -> Generator[dict[str, str], None, None]:
 """临时移除 os.environ 中所有 CLAUDE 前缀的环境变量。
 SDK 内部通过 {**os.environ, **options.env} 构建子进程环境，
 无法通过 options.env 删除已有 key，因此必须在调用前从 os.environ 中移除。
 Yields:
 被移除的环境变量字典
 """
 saved: dict[str, str] = {}
 for key in list(os.environ):
 if key.startswith("CLAUDE") or key == "CLAUDECODE" or key == "ANTHROPIC_AUTH_TOKEN":
 saved[key] = os.environ.pop(key)
 try:
 yield saved
 finally:
 os.environ.update(saved)
@dataclass
class SdkRunnerConfig:
 """SDKAgentRunner 配置。
 封装 SDK 运行所需的全部参数。
 Attributes:
 system_prompt: 系统提示词
 model: 模型标识（如 "sonnet"、"claude-sonnet-4-5"）
 space_id: 空间 UUID，用于 MCP 工具过滤和 AgentSession 关联
 session_id: 会话 ID，用于日志和事件元数据
 max_turns: 最大对话轮数
 timeout_seconds: 全局超时（秒），超时后强制终止 SDK Task
 permission_mode: SDK 权限模式
 queue_maxsize: 事件队列最大容量
 heartbeat_timeout: 心跳超时（秒），超时后发送 keepalive
 agent_session: 可选的 AgentSession 实例，用于 Hook 持久化
 max_thinking_tokens: extended thinking token 上限，None 使用 CLI 默认值（adaptive 模式）
 max_budget_usd: 单次对话预算上限（美元），None 表示不限制
 """
 system_prompt: str
 model: str
 space_id: str
 session_id: str
 conversation_id: str = ""
 api_key: str = ""
 api_base_url: str = ""
 max_turns: int = 15
 timeout_seconds: float = 600.0 # 10 分钟
 permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = (
 "bypassPermissions"
 )
 queue_maxsize: int = 200
 # 15 秒间隔低于主流浏览器（Chrome/Firefox/Safari）默认的网络超时阈值
 # （通常 60-120 秒），确保长对话不因浏览器超时而断连
 heartbeat_timeout: float = 15.0
 agent_session: Any = field(default=None) # AgentSession | None
 max_thinking_tokens: int | None = None
 max_budget_usd: float | None = None
class SDKAgentRunner:
 """Claude Agent SDK 运行器。
 通过 query(include_partial_messages=True) 驱动完整对话循环，
 将 SDK StreamEvent 转换为 AgentEvent，通过 asyncio.Queue 桥接
 SSE generator。
 用法：
 config = SdkRunnerConfig(...)
 runner = SDKAgentRunner(config)
 async for event in runner.stream("用户消息"):
 # 处理 AgentEvent
 result = runner.result # 获取最终结果
 """
 def __init__(self, config: SdkRunnerConfig) -> None:
 self._config = config
 self._result: AgentResult | None = None
 self._sdk_task: asyncio.Task[None] | None = None
 @property
 def result(self) -> AgentResult | None:
 """流结束后获取最终结果。"""
 return self._result
 async def interrupt(self) -> None:
 """中断正在运行的 SDK 任务。
 安全地取消 asyncio.Task，已完成的任务会被忽略。
 """
 if self._sdk_task and not self._sdk_task.done:
 self._sdk_task.cancel
 logger.info(
 "sdk_task_interrupted",
 session_id=self._config.session_id,
 )
 @staticmethod
 def _extract_usage(message: Any) -> dict[str, int]:
 """从 ResultMessage 提取 token 用量。
 尝试从 SDK 的 model_usage / modelUsage 属性提取汇总数据。
 """
 usage: dict[str, int] = {}
 # 尝试获取 model_usage（Python 命名风格）或 modelUsage（JS 风格）
 model_usage = getattr(message, "model_usage", None) or getattr(message, "modelUsage", None)
 if model_usage and isinstance(model_usage, dict):
 total_input = 0
 total_output = 0
 for _model_name, entry in model_usage.items:
 if isinstance(entry, dict):
 total_input += entry.get("inputTokens", 0) or entry.get("input_tokens", 0)
 total_output += entry.get("outputTokens", 0) or entry.get("output_tokens", 0)
 else:
 # entry 可能是 dataclass / namedtuple
 total_input += getattr(entry, "input_tokens", 0) or getattr(
 entry, "inputTokens", 0
 )
 total_output += getattr(entry, "output_tokens", 0) or getattr(
 entry, "outputTokens", 0
 )
 usage["input_tokens"] = total_input
 usage["output_tokens"] = total_output
 return usage
 async def stream(self, prompt: str) -> AsyncGenerator[AgentEvent, None]:
 """运行 SDK 并流式 yield AgentEvent。
 Args:
 prompt: 用户输入消息
 Yields:
 AgentEvent 实例（包含 text_delta、tool_use_start 等事件）
 """
 # 1. API key（由调用方注入）
 api_key = self._config.api_key
 if not api_key:
 raise ValueError("SdkRunnerConfig.api_key 不能为空")
 # 2. 事件队列（提前创建，MCP server 需要引用 event_callback）
 event_queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue(
 maxsize=self._config.queue_maxsize
 )
 async def event_callback(event: AgentEvent) -> None:
 """Hook 事件回调：将事件放入队列。"""
 try:
 event_queue.put_nowait(event)
 except asyncio.QueueFull:
 pass
 # 3. 构建 MCP server 和 allowed_tools（space_id/conversation_id/event_callback 自动注入）
 mcp_server = create_chat_tools_mcp_server(
 space_id=self._config.space_id,
 conversation_id=self._config.conversation_id,
 event_callback=event_callback,
 )
 allowed_tools = await build_allowed_tools(self._config.space_id)
 # 4. 构建 hooks（仅在有 session 时启用）
 hooks_config: dict[str, list[HookMatcher]] | None = None
 session = self._config.agent_session
 if session is not None:
 hooks_config = {
 "PostToolUse": [
 HookMatcher(
 matcher="*",
 hooks=[create_post_tool_use_hook(session, event_callback=event_callback)],
 ),
 ],
 }
 # 5. 构建 ClaudeAgentOptions
 # 按官方文档 (https://code.claude.com/docs/en/env-vars)，通过环境变量配置：
 # - ANTHROPIC_API_KEY: 覆盖 Claude 订阅认证
 # - ANTHROPIC_BASE_URL: 覆盖默认 API endpoint（用于 proxy/gateway）
 # --bare: 跳过 hooks/LSP 等，auth 严格使用 ANTHROPIC_API_KEY
 # setting_sources=: 生成 --setting-sources ""，阻止加载 ~/.claude/settings.json
 # （settings.json 的 env 段会注入 ANTHROPIC_AUTH_TOKEN/ANTHROPIC_BASE_URL 覆盖我们的值）
 # 不传 settings 参数（与 --setting-sources "" 组合时会导致 auth 失败）
 env_vars: dict[str, str] = {
 "ANTHROPIC_API_KEY": api_key,
 }
 if self._config.api_base_url:
 env_vars["ANTHROPIC_BASE_URL"] = self._config.api_base_url
 # 优先使用系统安装的 CLI，避免 bundled CLI 的 ProcessTransport bug
 import shutil
 system_cli = shutil.which("claude")
 options_kwargs: dict[str, Any] = {
 "system_prompt": self._config.system_prompt,
 "model": self._config.model,
 "permission_mode": self._config.permission_mode,
 "max_turns": self._config.max_turns,
 "include_partial_messages": True,
 "mcp_servers": {"chat-tools": mcp_server},
 "allowed_tools": allowed_tools,
 "disallowed_tools": [
 "Read", "Write", "Edit", "MultiEdit",
 "Bash", "Glob", "Grep", "LS",
 "WebFetch", "WebSearch",
 "TodoRead", "TodoWrite",
 ],
 "env": env_vars,
 "hooks": hooks_config,
 "setting_sources":,
 "extra_args": {"bare": None},
 }
 if system_cli:
 options_kwargs["cli_path"] = system_cli
 if self._config.max_thinking_tokens is not None:
 options_kwargs["max_thinking_tokens"] = self._config.max_thinking_tokens
 if self._config.max_budget_usd is not None:
 options_kwargs["max_budget_usd"] = self._config.max_budget_usd
 options = ClaudeAgentOptions(**options_kwargs)
 # 6. 事件适配器
 adapter = EventAdapter(
 model=self._config.model,
 session_id=self._config.session_id,
 )
 # 7. 在独立 Task 中运行 SDK
 accumulated_text: list[str] =
 async def make_prompt_stream(content: str) -> AsyncIterator[dict[str, Any]]:
 """将 string prompt 包装为 AsyncIterator。
 SDK 的 query 在 string prompt 模式下，会先阻塞等待 result 再消费消息流，
 导致所有 stream_event 被缓冲、最后一次性返回。
 使用 AsyncIterable prompt 模式时，SDK 将 stream_input 放入后台任务，
 立即开始消费消息流，实现真正的实时流式。
 """
 yield {
 "type": "user",
 "session_id": "",
 "message": {"role": "user", "content": content},
 "parent_tool_use_id": None,
 }
 async def run_sdk -> None:
 """运行 SDK query 并将事件放入队列。"""
 try:
 with clean_claude_env:
 async for message in query(
 prompt=make_prompt_stream(prompt), options=options
 ):
 events = adapter.adapt(message)
 for event in events:
 # 累积文本用于中断时保留部分内容
 if event.type == "text_delta":
 accumulated_text.append(event.data.get("text", ""))
 try:
 event_queue.put_nowait(event)
 except asyncio.QueueFull:
 pass
 # 检测 ResultMessage，构建 AgentResult（含 cost 数据）
 if hasattr(message, "result") and not hasattr(message, "event"):
 result_text = str(message.result) if message.result else ""
 cost_usd = getattr(message, "total_cost_usd", None) or 0
 usage = self._extract_usage(message)
 self._result = AgentResult(
 output=,
 status="completed",
 final_answer=result_text,
 usage=usage,
 metadata={"cost_usd": cost_usd},
 )
 # query 正常结束但没有检测到 ResultMessage 时，用累积文本构建结果
 if self._result is None and accumulated_text:
 self._result = AgentResult(
 output=,
 status="completed",
 final_answer="".join(accumulated_text),
 metadata={"cost_usd": 0, "fallback_result": True},
 )
 except asyncio.CancelledError:
 logger.info(
 "sdk_task_cancelled",
 session_id=self._config.session_id,
 )
 # 保留已生成的部分内容
 partial_text = "".join(accumulated_text)
 self._result = AgentResult(
 output=,
 status="interrupted",
 final_answer=partial_text,
 metadata={"cost_usd": 0},
 )
 # 向队列发送 message_complete 事件，通知前端中断已完成
 try:
 event_queue.put_nowait(
 AgentEvent(
 type=MESSAGE_COMPLETE,
 data={
 "status": "interrupted",
 "usage": {},
 "model": self._config.model,
 },
 )
 )
 except asyncio.QueueFull:
 pass
 except Exception as e:
 error_msg = _unwrap_exception(e)
 partial_text = "".join(accumulated_text)
 # 已生成最终结果后，忽略 SDK 关闭阶段竞态错误，避免将成功会话误标记为 error
 if _is_sdk_shutdown_race(error_msg) and self._result is not None:
 logger.warning(
 "sdk_shutdown_race_ignored_after_result",
 session_id=self._config.session_id,
 error=error_msg,
 )
 return
 # SDK 关闭阶段已知竞态：尽量回退到已输出文本，避免用户看到整段报错
 if _is_sdk_shutdown_race(error_msg):
 logger.warning(
 "sdk_shutdown_race_recovered_with_partial",
 session_id=self._config.session_id,
 partial_text_len=len(partial_text),
 error=error_msg,
 )
 if partial_text:
 self._result = AgentResult(
 output=,
 status="completed",
 final_answer=partial_text,
 metadata={
 "cost_usd": 0,
 "fallback_result": True,
 "recovered_from_sdk_shutdown_race": True,
 },
 )
 try:
 event_queue.put_nowait(
 AgentEvent(
 type=MESSAGE_COMPLETE,
 data={
 "result": partial_text,
 "status": "completed",
 "usage": {},
 "model": self._config.model,
 },
 )
 )
 except asyncio.QueueFull:
 pass
 return
 logger.error(
 "sdk_runner_error",
 session_id=self._config.session_id,
 error_type=type(e).__name__,
 error=error_msg,
 )
 try:
 error_events = adapter.adapt_error(e)
 for event in error_events:
 event_queue.put_nowait(event)
 except asyncio.QueueFull:
 pass
 self._result = AgentResult(
 output=,
 status="error",
 error=error_msg,
 )
 finally:
 try:
 event_queue.put_nowait(None) # 哨兵
 except asyncio.QueueFull:
 pass
 task = asyncio.create_task(run_sdk)
 self._sdk_task = task
 # 8. yield 事件（带心跳，timeout_seconds=0 表示无超时）
 try:
 no_timeout = self._config.timeout_seconds <= 0
 loop = asyncio.get_event_loop
 deadline = 0.0 if no_timeout else loop.time + self._config.timeout_seconds
 while True:
 if not no_timeout:
 remaining = deadline - loop.time
 if remaining <= 0:
 task.cancel
 timeout_min = int(self._config.timeout_seconds / 60)
 timeout_msg = f"AI 回复超时（已等待 {timeout_min} 分钟）"
 # task.cancel 只是调度取消，CancelledError 处理器不会立即执行，
 # 必须在此处设置 _result，否则调用方检查 result 时仍为 None
 if self._result is None:
 partial_text = "".join(accumulated_text)
 self._result = AgentResult(
 output=,
 status="error",
 error=timeout_msg,
 final_answer=partial_text,
 metadata={"cost_usd": 0, "timeout": True},
 )
 yield AgentEvent(
 type=ERROR,
 data={
 "message": timeout_msg,
 "error_code": "SDK_TIMEOUT",
 "timeout_seconds": self._config.timeout_seconds,
 },
 )
 break
 wait_timeout = min(self._config.heartbeat_timeout, remaining)
 else:
 wait_timeout = self._config.heartbeat_timeout
 try:
 event = await asyncio.wait_for(
 event_queue.get,
 timeout=wait_timeout,
 )
 except TimeoutError:
 yield AgentEvent(type=KEEPALIVE, data={})
 continue
 if event is None:
 break
 yield event
 except GeneratorExit:
 # SSE 连接断开 — Task 继续运行，确保消息落库
 logger.info(
 "sse_disconnected_sdk",
 session_id=self._config.session_id,
 )
