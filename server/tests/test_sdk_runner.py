"""SDKAgentRunner 单元测试。
验证 Runner 的组装逻辑、Queue 桥接、超时控制和环境隔离，
覆盖 、、 需求。
所有测试标记 xfail，等待 runner.py 实现。
"""
from __future__ import annotations
import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from agents.core.events import ERROR, TEXT_DELTA
async def test_runner_constructs_options -> None:
 """SDKAgentRunner 构造正确的 ClaudeAgentOptions 参数。"""
 from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
 config = SdkRunnerConfig(
 system_prompt="测试 prompt",
 model="sonnet",
 project_id="proj-123",
 session_id="sess-001",
 )
 runner = SDKAgentRunner(config)
 # 验证 config 属性正确设置
 assert runner._config.system_prompt == "测试 prompt"
 assert runner._config.model == "sonnet"
 assert runner._config.max_turns == 15
 assert runner._config.timeout_seconds == 300.0
 assert runner._config.permission_mode == "bypassPermissions"
async def test_api_key_injection -> None:
 """API key 通过 ProviderConfigService.aresolve 注入 env。"""
 from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
 config = SdkRunnerConfig(
 system_prompt="test",
 model="sonnet",
 project_id="proj-123",
 session_id="sess-001",
 )
 runner = SDKAgentRunner(config)
 mock_resolved = MagicMock
 mock_resolved.api_key = "sk-test-key-123"
 mock_resolved.provider_type = MagicMock
 with (
 patch("agents.sdk.runner.ProviderConfigService") as mock_pcs,
 patch("agents.sdk.runner.query") as mock_query,
 patch("agents.sdk.runner.create_chat_tools_mcp_server"),
 patch("agents.sdk.runner.build_allowed_tools", new_callable=AsyncMock, return_value=),
 patch("agents.sdk.runner.clean_claude_env"),
 ):
 mock_pcs.aresolve = AsyncMock(return_value=mock_resolved)
 mock_query.return_value = AsyncIteratorMock
 gen = runner.stream("test prompt")
 async for _ in gen:
 pass
 # 验证 query 调用中 options.env 包含 API key
 call_kwargs = mock_query.call_args
 options = call_kwargs.kwargs.get("options") or call_kwargs[1].get("options")
 assert options.env["ANTHROPIC_API_KEY"] == "sk-test-key-123"
async def test_stream_yields_events -> None:
 """stream 将 SDK StreamEvent 转换为 AgentEvent 并 yield。"""
 from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
 config = SdkRunnerConfig(
 system_prompt="test",
 model="sonnet",
 project_id="proj-123",
 session_id="sess-001",
 )
 runner = SDKAgentRunner(config)
 # 创建模拟 SDK 消息
 mock_stream_event = MagicMock
 mock_stream_event.event = {
 "type": "content_block_delta",
 "index": 0,
 "delta": {"type": "text_delta", "text": "Hello"},
 }
 del mock_stream_event.result
 mock_result = MagicMock
 mock_result.result = "Done"
 del mock_result.event
 with (
 patch("agents.sdk.runner.ProviderConfigService") as mock_pcs,
 patch("agents.sdk.runner.query") as mock_query,
 patch("agents.sdk.runner.create_chat_tools_mcp_server"),
 patch("agents.sdk.runner.build_allowed_tools", new_callable=AsyncMock, return_value=),
 patch("agents.sdk.runner.clean_claude_env"),
 ):
 mock_pcs.aresolve = AsyncMock(return_value=MagicMock(api_key="key"))
 mock_query.return_value = AsyncIteratorMock([mock_stream_event, mock_result])
 events =
 async for event in runner.stream("test"):
 if event.type != "keepalive":
 events.append(event)
 assert len(events) >= 1
 assert events[0].type == TEXT_DELTA
async def test_stream_queue_bridge -> None:
 """Queue 桥接正确传递事件，哨兵值终止迭代。"""
 from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
 config = SdkRunnerConfig(
 system_prompt="test",
 model="sonnet",
 project_id="proj-123",
 session_id="sess-001",
 queue_maxsize=10,
 )
 runner = SDKAgentRunner(config)
 # 模拟多个事件
 messages =
 for i in range(5):
 msg = MagicMock
 msg.event = {
 "type": "content_block_delta",
 "index": 0,
 "delta": {"type": "text_delta", "text": f"chunk{i}"},
 }
 del msg.result
 messages.append(msg)
 result_msg = MagicMock
 result_msg.result = "Done"
 del result_msg.event
 messages.append(result_msg)
 with (
 patch("agents.sdk.runner.ProviderConfigService") as mock_pcs,
 patch("agents.sdk.runner.query") as mock_query,
 patch("agents.sdk.runner.create_chat_tools_mcp_server"),
 patch("agents.sdk.runner.build_allowed_tools", new_callable=AsyncMock, return_value=),
 patch("agents.sdk.runner.clean_claude_env"),
 ):
 mock_pcs.aresolve = AsyncMock(return_value=MagicMock(api_key="key"))
 mock_query.return_value = AsyncIteratorMock(messages)
 events = [e async for e in runner.stream("test") if e.type != "keepalive"]
 # 应该收到所有文本事件 + message_complete
 assert len(events) >= 5
async def test_stream_timeout -> None:
 """5 分钟超时后产生 ERROR 事件。"""
 from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
 config = SdkRunnerConfig(
 system_prompt="test",
 model="sonnet",
 project_id="proj-123",
 session_id="sess-001",
 timeout_seconds=0.1, # 100ms 超时（测试用）
 heartbeat_timeout=0.05,
 )
 runner = SDKAgentRunner(config)
 async def slow_query(*args: Any, **kwargs: Any) -> Any:
 """模拟永不结束的 SDK 查询。"""
 await asyncio.sleep(10)
 yield # 永远不会到达
 with (
 patch("agents.sdk.runner.ProviderConfigService") as mock_pcs,
 patch("agents.sdk.runner.query", side_effect=slow_query),
 patch("agents.sdk.runner.create_chat_tools_mcp_server"),
 patch("agents.sdk.runner.build_allowed_tools", new_callable=AsyncMock, return_value=),
 patch("agents.sdk.runner.clean_claude_env"),
 ):
 mock_pcs.aresolve = AsyncMock(return_value=MagicMock(api_key="key"))
 events =
 async for event in runner.stream("test"):
 events.append(event)
 if event.type == ERROR:
 break
 error_events = [e for e in events if e.type == ERROR]
 assert len(error_events) >= 1
 assert "超时" in error_events[0].data["message"]
async def test_stream_generator_exit -> None:
 """GeneratorExit（SSE 断线）不导致 SDK Task 泄漏。"""
 from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
 config = SdkRunnerConfig(
 system_prompt="test",
 model="sonnet",
 project_id="proj-123",
 session_id="sess-001",
 )
 runner = SDKAgentRunner(config)
 # 模拟一个会产生多个事件的查询
 async def multi_msg_query(*args: Any, **kwargs: Any) -> Any:
 for _ in range(100):
 msg = MagicMock
 msg.event = {
 "type": "content_block_delta",
 "index": 0,
 "delta": {"type": "text_delta", "text": "x"},
 }
 del msg.result
 yield msg
 await asyncio.sleep(0.01)
 with (
 patch("agents.sdk.runner.ProviderConfigService") as mock_pcs,
 patch("agents.sdk.runner.query", side_effect=multi_msg_query),
 patch("agents.sdk.runner.create_chat_tools_mcp_server"),
 patch("agents.sdk.runner.build_allowed_tools", new_callable=AsyncMock, return_value=),
 patch("agents.sdk.runner.clean_claude_env"),
 ):
 mock_pcs.aresolve = AsyncMock(return_value=MagicMock(api_key="key"))
 gen = runner.stream("test")
 # 只读取一个事件就断开
 async for event in gen:
 if event.type != "keepalive":
 break
 # 不应该有未处理的异常
 await asyncio.sleep(0.1)
async def test_clean_env_called -> None:
 """stream 中调用 clean_claude_env 隔离环境变量。"""
 from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
 config = SdkRunnerConfig(
 system_prompt="test",
 model="sonnet",
 project_id="proj-123",
 session_id="sess-001",
 )
 runner = SDKAgentRunner(config)
 with (
 patch("agents.sdk.runner.ProviderConfigService") as mock_pcs,
 patch("agents.sdk.runner.query") as mock_query,
 patch("agents.sdk.runner.create_chat_tools_mcp_server"),
 patch("agents.sdk.runner.build_allowed_tools", new_callable=AsyncMock, return_value=),
 patch("agents.sdk.runner.clean_claude_env") as mock_clean,
 ):
 mock_pcs.aresolve = AsyncMock(return_value=MagicMock(api_key="key"))
 mock_query.return_value = AsyncIteratorMock
 async for _ in runner.stream("test"):
 pass
 mock_clean.assert_called
async def test_stream_returns_result -> None:
 """流结束后可获取 AgentResult。"""
 from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig
 config = SdkRunnerConfig(
 system_prompt="test",
 model="sonnet",
 project_id="proj-123",
 session_id="sess-001",
 )
 runner = SDKAgentRunner(config)
 result_msg = MagicMock
 result_msg.result = "最终回复"
 del result_msg.event
 with (
 patch("agents.sdk.runner.ProviderConfigService") as mock_pcs,
 patch("agents.sdk.runner.query") as mock_query,
 patch("agents.sdk.runner.create_chat_tools_mcp_server"),
 patch("agents.sdk.runner.build_allowed_tools", new_callable=AsyncMock, return_value=),
 patch("agents.sdk.runner.clean_claude_env"),
 ):
 mock_pcs.aresolve = AsyncMock(return_value=MagicMock(api_key="key"))
 mock_query.return_value = AsyncIteratorMock([result_msg])
 async for _ in runner.stream("test"):
 pass
 assert runner.result is not None
 assert runner.result.status == "completed"
# ==================== Helpers ====================
class AsyncIteratorMock:
 """模拟 async iterator（SDK query 返回值）。"""
 def __init__(self, items: list[Any]) -> None:
 self._items = items
 self._index = 0
 def __aiter__(self) -> AsyncIteratorMock:
 return self
 async def __anext__(self) -> Any:
 if self._index >= len(self._items):
 raise StopAsyncIteration
 item = self._items[self._index]
 self._index += 1
 return item
