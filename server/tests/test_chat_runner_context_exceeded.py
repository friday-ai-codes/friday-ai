"""Phase Plan — chat_runner.py SSE code 集成契约测试。
覆盖：chat 对话路径触发 ContextWindowExceededError 时，SSE ERROR event 的
顶层含 ``code: "context_window_exceeded"``，nested ``data`` 含 5 字段
（estimated_tokens / max_tokens / exceeded_by / model / recommended_actions）
且 ``recommended_actions`` 是长度 3 的列表（trim_prompt / switch_model / cleanup_history）。
同时覆盖 V4 ASVS Information Disclosure：logger.warning 不得泄漏 api_key /
api_base_url 等凭证字段。
Test fixtures 风格与 ``tests/test_chat_runner.py`` 对齐：共用 ``_make_config`` +
``patch.object(ChatAnthropicRunner, "_build_model")`` seam +
``patch("agents.chat_runner._build_tool_specs", return_value={})``。
"""
from __future__ import annotations
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
import pytest
from agents.chat_runner import ChatAnthropicRunner, ChatRunnerConfig
from agents.core.events import ERROR
from agents.langchain_runner import ContextWindowExceededError
def _make_config -> ChatRunnerConfig:
 """与 ``tests/test_chat_runner.py:_make_config`` 对齐（api_key="sk-test" 便于
 Test B 断言 log 不含 "sk-test"）。"""
 return ChatRunnerConfig(
 system_prompt="你是测试助手",
 model="claude-sonnet-4-5",
 space_id="proj-1",
 session_id="sess-1",
 # conversation fixture omitted
 api_key="sk-test",
 )
class _RaiseContextExceeded:
 """monkeypatch seam：替换 ``_check_chat_context_window``，第一次被调用即抛
 ``ContextWindowExceededError``（不进 astream）。
 保持 callable 签名 ``(*args, **kwargs) -> None`` 兼容 keyword-only 参数。
 """
 def __init__(self, message: str) -> None:
 self.message = message
 def __call__(self, *args: Any, **kwargs: Any) -> None:
 raise ContextWindowExceededError(self.message)
@pytest.mark.asyncio
async def test_chat_runner_context_exceeded_emits_structured_sse_error(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """Behavior A：标准 langchain_runner 消息格式 → event.code + event.data 5 字段 + 3 actions。"""
 runner = ChatAnthropicRunner(_make_config)
 msg = (
 "context too long: 200000 tokens > budget 150000 "
 "(max_input=128000, max_output=22000, buffer=800)"
 )
 # 替换 _check_chat_context_window —— 第一次 turn 即抛 ContextWindowExceededError
 monkeypatch.setattr(
 "agents.chat_runner._check_chat_context_window",
 _RaiseContextExceeded(msg),
 )
 fake_model = MagicMock
 # bind_tools.astream 不应被调到（check 在 astream 前抛错），但保留空实现兜底
 fake_model.bind_tools.return_value = SimpleNamespace(astream=lambda _m: iter)
 with (
 patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
 patch("agents.chat_runner._build_tool_specs", return_value={}),
 ):
 events = [event async for event in runner.stream("hi")]
 error_events = [e for e in events if e.type == ERROR]
 assert len(error_events) == 1
 data = error_events[0].data
 # 顶层字段（Pitfall 8 硬锁 — 前端 stores/chat.ts:work-item 读 event.code / event.data）
 assert data["code"] == "context_window_exceeded"
 assert data["message"] == msg
 # nested data 的 5 字段
 inner = data["data"]
 assert inner["estimated_tokens"] == 200000
 assert inner["max_tokens"] == 150000
 assert inner["exceeded_by"] == 50000
 assert inner["model"] == "claude-sonnet-4-5"
 # recommended_actions 必为 3 条，id 顺序固定
 actions = inner["recommended_actions"]
 assert isinstance(actions, list)
 assert len(actions) == 3
 assert [a["id"] for a in actions] == ["trim_prompt", "switch_model", "cleanup_history"]
 # 每条 action 必含 label / action_type / target
 for action in actions:
 assert "label" in action
 assert "action_type" in action
 assert "target" in action
 # 具体目标契约（work item §Fix 1 锁定）
 by_id = {a["id"]: a for a in actions}
 assert by_id["trim_prompt"]["action_type"] == "navigate"
 assert by_id["trim_prompt"]["target"] == "/prompts/"
 assert by_id["switch_model"]["action_type"] == "navigate"
 assert by_id["switch_model"]["target"] == "settings.model"
 assert by_id["cleanup_history"]["action_type"] == "dialog"
 assert by_id["cleanup_history"]["target"] == "CleanupDialog"
@pytest.mark.asyncio
async def test_chat_runner_context_exceeded_logger_no_credential_leak(
 monkeypatch: pytest.MonkeyPatch,
 caplog: pytest.LogCaptureFixture,
) -> None:
 """Behavior B：logger.warning 日志不得出现 api_key / api_base_url 字段（V4 ASVS
 Information Disclosure；T- / T- mitigation 证据）。"""
 runner = ChatAnthropicRunner(_make_config)
 msg = "context too long: 100 tokens > budget 50 (max_input=200, max_output=100, buffer=50)"
 monkeypatch.setattr(
 "agents.chat_runner._check_chat_context_window",
 _RaiseContextExceeded(msg),
 )
 fake_model = MagicMock
 fake_model.bind_tools.return_value = SimpleNamespace(astream=lambda _m: iter)
 with (
 patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
 patch("agents.chat_runner._build_tool_specs", return_value={}),
 ):
 _ = [event async for event in runner.stream("hi")]
 # 合并所有 log record message —— structlog 在 pytest 下亦会走 stdlib logging bridge
 log_text = " ".join(r.getMessage for r in caplog.records)
 assert "sk-test" not in log_text
 assert "api_base_url" not in log_text
