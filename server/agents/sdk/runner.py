"""SDKAgentRunner：封装 Claude Agent SDK 的核心运行模块。
通过 query 驱动完整对话循环，将 SDK 流式事件转换为 AgentEvent，
并通过 asyncio.Queue 桥接 SSE generator。
"""
from __future__ import annotations
import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator, Literal
import structlog
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query
from agents.core.events import ERROR, AgentEvent
from agents.core.result import AgentResult
from agents.sdk.event_adapter import EventAdapter
from agents.sdk.hooks import create_post_tool_use_hook, create_stop_hook
from agents.sdk.mcp_adapter import build_allowed_tools, create_chat_tools_mcp_server
logger = structlog.get_logger(__name__)
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
 if key.startswith("CLAUDE") or key == "CLAUDECODE":
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
 project_id: 项目 UUID，用于 MCP 工具过滤和 AgentSession 关联
 session_id: 会话 ID，用于日志和事件元数据
 max_turns: 最大对话轮数
 timeout_seconds: 全局超时（秒），超时后强制终止 SDK Task
 permission_mode: SDK 权限模式
 queue_maxsize: 事件队列最大容量
 heartbeat_timeout: 心跳超时（秒），超时后发送 keepalive
 agent_session: 可选的 AgentSession 实例，用于 Hook 持久化
 """
 system_prompt: str
 model: str
 project_id: str
 session_id: str
 api_key: str = ""
 max_turns: int = 15
 timeout_seconds: float = 300.0 # 5 分钟
 permission_mode: Literal["default", "acceptEdits", "plan", "bypassPermissions"] = "bypassPermissions"
 queue_maxsize: int = 200
 heartbeat_timeout: float = 15.0
 agent_session: Any = field(default=None) # AgentSession | None
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
 @property
 def result(self) -> AgentResult | None:
 """流结束后获取最终结果。"""
 return self._result
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
 # 2. 构建 MCP server 和 allowed_tools
 mcp_server = create_chat_tools_mcp_server
 allowed_tools = await build_allowed_tools(self._config.project_id)
 # 3. 事件队列
 event_queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue(
 maxsize=self._config.queue_maxsize
 )
 async def event_callback(event: AgentEvent) -> None:
 """Hook 事件回调：将事件放入队列。"""
 try:
 event_queue.put_nowait(event)
 except asyncio.QueueFull:
 pass
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
 "Stop": [
 HookMatcher(
 matcher="*",
 hooks=[create_stop_hook(session)],
 ),
 ],
 }
 # 5. 构建 ClaudeAgentOptions
 options = ClaudeAgentOptions(
 system_prompt=self._config.system_prompt,
 model=self._config.model,
 permission_mode=self._config.permission_mode,
 max_turns=self._config.max_turns,
 include_partial_messages=True,
 mcp_servers={"chat-tools": mcp_server},
 allowed_tools=allowed_tools,
 env={"ANTHROPIC_API_KEY": api_key},
 hooks=hooks_config, # type: ignore[arg-type]
 )
 # 6. 事件适配器
 adapter = EventAdapter(
 model=self._config.model,
 session_id=self._config.session_id,
 )
 # 7. 在独立 Task 中运行 SDK
 async def run_sdk -> None:
 """运行 SDK query 并将事件放入队列。"""
 try:
 with clean_claude_env:
 async for message in query(prompt=prompt, options=options):
 events = adapter.adapt(message)
 for event in events:
 try:
 event_queue.put_nowait(event)
 except asyncio.QueueFull:
 pass
 # 检测 ResultMessage，构建 AgentResult
 if hasattr(message, "result") and not hasattr(message, "event"):
 result_text = (
 str(message.result) if message.result else ""
 )
 self._result = AgentResult(
 output=,
 status="completed",
 final_answer=result_text,
 )
 except asyncio.CancelledError:
 logger.info(
 "sdk_task_cancelled",
 session_id=self._config.session_id,
 )
 self._result = AgentResult(
 output=,
 status="error",
 error="SDK 运行超时",
 )
 except Exception as e:
 logger.exception(
 "sdk_runner_error",
 session_id=self._config.session_id,
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
 error=str(e),
 )
 finally:
 try:
 event_queue.put_nowait(None) # 哨兵
 except asyncio.QueueFull:
 pass
 task = asyncio.create_task(run_sdk)
 # 8. yield 事件（带超时和心跳）
 try:
 loop = asyncio.get_event_loop
 deadline = loop.time + self._config.timeout_seconds
 while True:
 remaining = deadline - loop.time
 if remaining <= 0:
 task.cancel
 yield AgentEvent(type=ERROR, data={"message": "SDK 运行超时"})
 break
 try:
 event = await asyncio.wait_for(
 event_queue.get,
 timeout=min(self._config.heartbeat_timeout, remaining),
 )
 except TimeoutError:
 yield AgentEvent(type="keepalive", data={})
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
