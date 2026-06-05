"""SDKAgentRunner 中断机制测试。

验证用户点击"停止生成"后：
1. runner.stream() 最终 yield message_complete(status=interrupted) 事件
2. runner.result 包含部分文本和 interrupted 状态
3. runner._sdk_task 被正确取消

使用 asyncio.Event 控制 mock SDK generator 的暂停/恢复。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agents.core.events import MESSAGE_COMPLETE, AgentEvent
from agents.core.result import AgentResult
from agents.sdk.runner import SDKAgentRunner, SdkRunnerConfig

# ============================================================================
# 测试配置工厂
# ============================================================================

def _make_config(**overrides: Any) -> SdkRunnerConfig:
    """创建测试用 SdkRunnerConfig。"""
    defaults = {
        "system_prompt": "你是测试助手",
        "model": "test-model",
        "space_id": "test-project-id",
        "session_id": "test-session-id",
        "api_key": "test-api-key",
        "max_turns": 5,
        "timeout_seconds": 10.0,
        "queue_maxsize": 50,
        "heartbeat_timeout": 2.0,
    }
    defaults.update(overrides)
    return SdkRunnerConfig(**defaults)


# ============================================================================
# Mock SDK query generator
# ============================================================================


async def _slow_sdk_generator(
    hang_event: asyncio.Event,
    text_chunks: list[str] | None = None,
) -> AsyncGenerator[Any, None]:
    """模拟 SDK query() 的 async generator。

    先 yield 几个 text_delta 事件，然后在 hang_event 处挂起，
    直到被 cancel 或 hang_event 被 set。

    Args:
        hang_event: 控制 generator 挂起的事件
        text_chunks: 要 yield 的文本片段列表
    """
    chunks = text_chunks or ["Hello", " World", "!"]
    for chunk in chunks:
        # 构造 SDK StreamEvent（有 event 属性）
        yield SimpleNamespace(event={
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": chunk},
        })
        await asyncio.sleep(0.01)  # 模拟流式延迟

    # 挂起，等待 cancel 或 event set
    await hang_event.wait()


# ============================================================================
# 测试类
# ============================================================================


class TestInterruptMechanism:
    """SDKAgentRunner 中断机制测试套件。"""

    @pytest.mark.asyncio
    async def test_interrupt_yields_message_complete(self) -> None:
        """中断后 stream() 最终 yield message_complete(status=interrupted) 事件。"""
        hang_event = asyncio.Event()
        config = _make_config()

        async def mock_query(**kwargs: Any) -> AsyncGenerator[Any, None]:
            async for item in _slow_sdk_generator(hang_event, ["你好", "世界"]):
                yield item

        with (
            patch("agents.sdk.runner.query", side_effect=mock_query),
            patch("agents.sdk.runner.create_chat_tools_mcp_server", return_value=MagicMock()),
            patch("agents.sdk.runner.build_allowed_tools", return_value=[]),
        ):
            runner = SDKAgentRunner(config)
            events: list[AgentEvent] = []

            async def collect_events() -> None:
                async for event in runner.stream("测试"):
                    events.append(event)

            task = asyncio.create_task(collect_events())

            # 等待一些事件被 yield
            await asyncio.sleep(0.15)

            # 触发中断
            await runner.interrupt()

            # 等待 stream 结束
            await asyncio.wait_for(task, timeout=5.0)

        # 验证：最后一个非 keepalive 事件是 message_complete
        non_keepalive = [e for e in events if e.type != "keepalive"]
        assert len(non_keepalive) > 0, "应该有事件被 yield"

        last_event = non_keepalive[-1]
        assert last_event.type == MESSAGE_COMPLETE, (
            f"最后一个事件应是 message_complete，实际是 {last_event.type}"
        )
        assert last_event.data.get("status") == "interrupted", (
            f"message_complete 的 status 应为 interrupted，实际是 {last_event.data.get('status')}"
        )

    @pytest.mark.asyncio
    async def test_interrupt_preserves_partial_text(self) -> None:
        """中断后 runner.result.final_answer 包含已发送的部分文本。"""
        hang_event = asyncio.Event()
        text_chunks = ["部分", "内容", "保留"]
        config = _make_config()

        async def mock_query(**kwargs: Any) -> AsyncGenerator[Any, None]:
            async for item in _slow_sdk_generator(hang_event, text_chunks):
                yield item

        with (
            patch("agents.sdk.runner.query", side_effect=mock_query),
            patch("agents.sdk.runner.create_chat_tools_mcp_server", return_value=MagicMock()),
            patch("agents.sdk.runner.build_allowed_tools", return_value=[]),
        ):
            runner = SDKAgentRunner(config)

            async def consume_stream() -> None:
                async for _ in runner.stream("测试"):
                    pass

            task = asyncio.create_task(consume_stream())
            await asyncio.sleep(0.15)

            await runner.interrupt()
            await asyncio.wait_for(task, timeout=5.0)

        # 验证 result
        result = runner.result
        assert result is not None, "中断后 result 不应为 None"
        assert result.status == "interrupted", f"状态应为 interrupted，实际 {result.status}"
        assert result.final_answer is not None, "final_answer 不应为 None"
        # 部分文本应包含已 yield 的内容
        for chunk in text_chunks:
            assert chunk in result.final_answer, (
                f"final_answer 应包含 '{chunk}'，实际: '{result.final_answer}'"
            )

    @pytest.mark.asyncio
    async def test_interrupt_sets_result_status(self) -> None:
        """中断后 runner.result.status == 'interrupted'。"""
        hang_event = asyncio.Event()
        config = _make_config()

        async def mock_query(**kwargs: Any) -> AsyncGenerator[Any, None]:
            async for item in _slow_sdk_generator(hang_event):
                yield item

        with (
            patch("agents.sdk.runner.query", side_effect=mock_query),
            patch("agents.sdk.runner.create_chat_tools_mcp_server", return_value=MagicMock()),
            patch("agents.sdk.runner.build_allowed_tools", return_value=[]),
        ):
            runner = SDKAgentRunner(config)

            async def consume_stream() -> None:
                async for _ in runner.stream("测试"):
                    pass

            task = asyncio.create_task(consume_stream())
            await asyncio.sleep(0.15)

            await runner.interrupt()
            await asyncio.wait_for(task, timeout=5.0)

        result = runner.result
        assert result is not None
        assert result.status == "interrupted"
        assert isinstance(result, AgentResult)

    @pytest.mark.asyncio
    async def test_interrupt_sdk_task_done(self) -> None:
        """中断后 runner._sdk_task 为 done 状态。"""
        hang_event = asyncio.Event()
        config = _make_config()

        async def mock_query(**kwargs: Any) -> AsyncGenerator[Any, None]:
            async for item in _slow_sdk_generator(hang_event):
                yield item

        with (
            patch("agents.sdk.runner.query", side_effect=mock_query),
            patch("agents.sdk.runner.create_chat_tools_mcp_server", return_value=MagicMock()),
            patch("agents.sdk.runner.build_allowed_tools", return_value=[]),
        ):
            runner = SDKAgentRunner(config)

            async def consume_stream() -> None:
                async for _ in runner.stream("测试"):
                    pass

            task = asyncio.create_task(consume_stream())
            await asyncio.sleep(0.15)

            await runner.interrupt()
            await asyncio.wait_for(task, timeout=5.0)

        # SDK task 应该已完成
        assert runner._sdk_task is not None
        assert runner._sdk_task.done(), "中断后 _sdk_task 应为 done 状态"
