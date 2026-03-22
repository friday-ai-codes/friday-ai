"""SDKAgentRunner 单元测试。
验证 Runner 的组装逻辑、Queue 桥接、超时控制、环境隔离、
thinking 配置、cost 提取和中断控制。
覆盖 、、、、、 需求。
"""
from __future__ import annotations
import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from agents.core.events import ERROR, TEXT_DELTA
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
def _make_config(**overrides: Any) -> Any:
 """创建带默认值的 SdkRunnerConfig。"""
 from agents.sdk.runner import SdkRunnerConfig
 defaults = {
 "system_prompt": "test",
 "model": "sonnet",
 "project_id": "proj-123",
 "session_id": "sess-001",
 "api_key": "sk-test-key",
 }
 defaults.update(overrides)
 return SdkRunnerConfig(**defaults)
def _stream_patches:
 """返回 stream 所需的公共 mock patches。"""
 return (
 patch("agents.sdk.runner.query"),
 patch("agents.sdk.runner.create_chat_tools_mcp_server"),
 patch("agents.sdk.runner.build_allowed_tools", new_callable=AsyncMock, return_value=),
 patch("agents.sdk.runner.clean_claude_env"),
 )
# ==================== 基础构造测试 ====================
async def test_runner_constructs_options -> None:
 """SDKAgentRunner 构造正确的 ClaudeAgentOptions 参数。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config(system_prompt="测试 prompt")
 runner = SDKAgentRunner(config)
 assert runner._config.system_prompt == "测试 prompt"
 assert runner._config.model == "sonnet"
 assert runner._config.max_turns == 15
 assert runner._config.timeout_seconds == 300.0
 assert runner._config.permission_mode == "bypassPermissions"
async def test_api_key_injection -> None:
 """API key 通过 SdkRunnerConfig.api_key 注入 ClaudeAgentOptions.env。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config(api_key="sk-test-key-123")
 runner = SDKAgentRunner(config)
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.return_value = AsyncIteratorMock
 async for _ in runner.stream("test prompt"):
 pass
 # 验证 query 调用中 options.env 包含 API key
 call_kwargs = mock_query.call_args
 options = call_kwargs.kwargs.get("options") or call_kwargs[1].get("options")
 assert options.env["ANTHROPIC_API_KEY"] == "sk-test-key-123"
async def test_api_key_required -> None:
 """api_key 为空时 stream 抛出 ValueError。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config(api_key="")
 runner = SDKAgentRunner(config)
 with pytest.raises(ValueError, match="api_key"):
 async for _ in runner.stream("test"):
 pass
# ==================== Thinking 配置测试 ====================
async def test_thinking_default_adaptive -> None:
 """max_thinking_tokens 默认为 None（使用 CLI 默认 adaptive thinking）。"""
 config = _make_config
 assert config.max_thinking_tokens is None
async def test_thinking_tokens_injected_when_set -> None:
 """max_thinking_tokens 设置时注入 ClaudeAgentOptions。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config(max_thinking_tokens=8000)
 runner = SDKAgentRunner(config)
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.return_value = AsyncIteratorMock
 async for _ in runner.stream("test"):
 pass
 call_kwargs = mock_query.call_args
 options = call_kwargs.kwargs.get("options") or call_kwargs[1].get("options")
 assert options.max_thinking_tokens == 8000
async def test_thinking_tokens_not_injected_when_none -> None:
 """max_thinking_tokens 为 None 时不传入 ClaudeAgentOptions（使用默认值）。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config(max_thinking_tokens=None)
 runner = SDKAgentRunner(config)
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.return_value = AsyncIteratorMock
 async for _ in runner.stream("test"):
 pass
 call_kwargs = mock_query.call_args
 options = call_kwargs.kwargs.get("options") or call_kwargs[1].get("options")
 assert options.max_thinking_tokens is None
# ==================== Cost 提取测试 ====================
async def test_cost_extraction_from_result_message -> None:
 """ResultMessage 的 total_cost_usd 被提取到 AgentResult.metadata。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config
 runner = SDKAgentRunner(config)
 result_msg = MagicMock
 result_msg.result = "回复内容"
 result_msg.total_cost_usd = 0.05
 result_msg.model_usage = {
 "claude-sonnet-4-20250514": {
 "inputTokens": 1500,
 "outputTokens": 300,
 }
 }
 del result_msg.event
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.return_value = AsyncIteratorMock([result_msg])
 async for _ in runner.stream("test"):
 pass
 assert runner.result is not None
 assert runner.result.status == "completed"
 assert runner.result.metadata["cost_usd"] == 0.05
 assert runner.result.usage["input_tokens"] == 1500
 assert runner.result.usage["output_tokens"] == 300
async def test_cost_extraction_no_cost_data -> None:
 """ResultMessage 无 cost 数据时使用默认值。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config
 runner = SDKAgentRunner(config)
 result_msg = MagicMock
 result_msg.result = "回复"
 del result_msg.event
 del result_msg.total_cost_usd
 del result_msg.model_usage
 del result_msg.modelUsage
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.return_value = AsyncIteratorMock([result_msg])
 async for _ in runner.stream("test"):
 pass
 assert runner.result is not None
 assert runner.result.metadata["cost_usd"] == 0
 assert runner.result.usage == {}
async def test_extract_usage_multiple_models -> None:
 """_extract_usage 能汇总多个模型的 token 用量。"""
 from agents.sdk.runner import SDKAgentRunner
 msg = MagicMock
 msg.model_usage = {
 "claude-sonnet-4-20250514": {"inputTokens": 1000, "outputTokens": 200},
 "claude-haiku-3": {"inputTokens": 500, "outputTokens": 100},
 }
 usage = SDKAgentRunner._extract_usage(msg)
 assert usage["input_tokens"] == 1500
 assert usage["output_tokens"] == 300
async def test_extract_usage_python_naming -> None:
 """_extract_usage 支持 Python 命名风格（input_tokens / output_tokens）。"""
 from agents.sdk.runner import SDKAgentRunner
 msg = MagicMock
 msg.model_usage = {
 "model-a": {"input_tokens": 800, "output_tokens": 150},
 }
 del msg.modelUsage
 usage = SDKAgentRunner._extract_usage(msg)
 assert usage["input_tokens"] == 800
 assert usage["output_tokens"] == 150
# ==================== Max Budget 测试 ====================
async def test_max_budget_usd_default_none -> None:
 """SdkRunnerConfig 默认 max_budget_usd 为 None。"""
 config = _make_config
 assert config.max_budget_usd is None
async def test_max_budget_usd_injected_when_set -> None:
 """max_budget_usd 设置时注入 ClaudeAgentOptions。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config(max_budget_usd=1.5)
 runner = SDKAgentRunner(config)
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.return_value = AsyncIteratorMock
 async for _ in runner.stream("test"):
 pass
 call_kwargs = mock_query.call_args
 options = call_kwargs.kwargs.get("options") or call_kwargs[1].get("options")
 assert options.max_budget_usd == 1.5
async def test_max_budget_usd_not_injected_when_none -> None:
 """max_budget_usd 为 None 时不传入 ClaudeAgentOptions。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config(max_budget_usd=None)
 runner = SDKAgentRunner(config)
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.return_value = AsyncIteratorMock
 async for _ in runner.stream("test"):
 pass
 call_kwargs = mock_query.call_args
 options = call_kwargs.kwargs.get("options") or call_kwargs[1].get("options")
 # max_budget_usd 应为 None（未设置）或不存在
 budget = getattr(options, "max_budget_usd", None)
 assert budget is None
# ==================== 中断测试 ====================
async def test_interrupt_cancels_sdk_task -> None:
 """interrupt 取消正在运行的 SDK 任务。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config(heartbeat_timeout=0.05, timeout_seconds=5.0)
 runner = SDKAgentRunner(config)
 async def slow_query(*args: Any, **kwargs: Any) -> Any:
 """模拟慢速查询。"""
 await asyncio.sleep(10)
 yield # 不会到达
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.side_effect = slow_query
 gen = runner.stream("test")
 # 启动流，等待第一个 keepalive
 first = await asyncio.wait_for(gen.__anext__, timeout=2.0)
 assert first.type == "keepalive"
 # 中断
 await runner.interrupt
 # 消费剩余事件直到流结束
 async for _ in gen:
 pass
 # 等待内部 task 完全结束
 if runner._sdk_task:
 try:
 await asyncio.wait_for(runner._sdk_task, timeout=1.0)
 except (asyncio.CancelledError, asyncio.TimeoutError):
 pass
 assert runner.result is not None
 assert runner.result.status == "interrupted"
async def test_interrupt_preserves_partial_content -> None:
 """中断后保留已生成的部分内容。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config(heartbeat_timeout=0.05)
 runner = SDKAgentRunner(config)
 async def partial_query(*args: Any, **kwargs: Any) -> Any:
 """模拟产生部分文本后挂起的查询。"""
 for text in ["Hello", " World", "!"]:
 msg = MagicMock
 msg.event = {
 "type": "content_block_delta",
 "index": 0,
 "delta": {"type": "text_delta", "text": text},
 }
 del msg.result
 yield msg
 # 模拟长时间等待
 await asyncio.sleep(10)
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.side_effect = partial_query
 gen = runner.stream("test")
 # 读取几个事件
 count = 0
 async for event in gen:
 if event.type == TEXT_DELTA:
 count += 1
 if count >= 3:
 await runner.interrupt
 break
 # 消费剩余
 async for _ in gen:
 pass
 assert runner.result is not None
 assert runner.result.status == "interrupted"
 assert runner.result.final_answer is not None
 assert "Hello World!" in runner.result.final_answer
async def test_interrupt_noop_when_no_task -> None:
 """无活跃任务时 interrupt 不报错。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config
 runner = SDKAgentRunner(config)
 # 未调用 stream，_sdk_task 为 None
 await runner.interrupt # 不应抛出异常
# ==================== 流式事件测试 ====================
async def test_stream_yields_events -> None:
 """stream 将 SDK StreamEvent 转换为 AgentEvent 并 yield。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config
 runner = SDKAgentRunner(config)
 mock_stream_event = MagicMock
 mock_stream_event.event = {
 "type": "content_block_delta",
 "index": 0,
 "delta": {"type": "text_delta", "text": "Hello"},
 }
 del mock_stream_event.result
 result_msg = MagicMock
 result_msg.result = "Done"
 result_msg.total_cost_usd = 0.01
 del result_msg.event
 del result_msg.model_usage
 del result_msg.modelUsage
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.return_value = AsyncIteratorMock([mock_stream_event, result_msg])
 events =
 async for event in runner.stream("test"):
 if event.type != "keepalive":
 events.append(event)
 assert len(events) >= 1
 assert events[0].type == TEXT_DELTA
async def test_stream_queue_bridge -> None:
 """Queue 桥接正确传递事件，哨兵值终止迭代。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config(queue_maxsize=10)
 runner = SDKAgentRunner(config)
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
 result_msg.total_cost_usd = 0
 del result_msg.event
 del result_msg.model_usage
 del result_msg.modelUsage
 messages.append(result_msg)
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.return_value = AsyncIteratorMock(messages)
 events = [e async for e in runner.stream("test") if e.type != "keepalive"]
 assert len(events) >= 5
async def test_stream_timeout -> None:
 """超时后产生 ERROR 事件。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config(timeout_seconds=0.1, heartbeat_timeout=0.05)
 runner = SDKAgentRunner(config)
 async def slow_query(*args: Any, **kwargs: Any) -> Any:
 """模拟永不结束的 SDK 查询。"""
 await asyncio.sleep(10)
 yield # 永远不会到达
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.side_effect = slow_query
 events =
 async for event in runner.stream("test"):
 events.append(event)
 if event.type == ERROR:
 break
 error_events = [e for e in events if e.type == ERROR]
 assert len(error_events) >= 1
 assert "超时" in error_events[0].data["message"]
async def test_stream_generator_exit -> None:
 """GeneratorExit（SSE 断线）不导致异常。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config
 runner = SDKAgentRunner(config)
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
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.side_effect = multi_msg_query
 gen = runner.stream("test")
 async for event in gen:
 if event.type != "keepalive":
 break
 await asyncio.sleep(0.1)
async def test_clean_env_called -> None:
 """stream 中调用 clean_claude_env 隔离环境变量。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config
 runner = SDKAgentRunner(config)
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env as mock_clean:
 mock_query.return_value = AsyncIteratorMock
 async for _ in runner.stream("test"):
 pass
 mock_clean.assert_called
async def test_stream_returns_result -> None:
 """流结束后可获取 AgentResult。"""
 from agents.sdk.runner import SDKAgentRunner
 config = _make_config
 runner = SDKAgentRunner(config)
 result_msg = MagicMock
 result_msg.result = "最终回复"
 result_msg.total_cost_usd = 0.02
 del result_msg.event
 del result_msg.model_usage
 del result_msg.modelUsage
 p_query, p_mcp, p_tools, p_env = _stream_patches
 with p_query as mock_query, p_mcp, p_tools, p_env:
 mock_query.return_value = AsyncIteratorMock([result_msg])
 async for _ in runner.stream("test"):
 pass
 assert runner.result is not None
 assert runner.result.status == "completed"
 assert runner.result.final_answer == "最终回复"
 assert runner.result.metadata["cost_usd"] == 0.02
