"""容器主动 emit token_usage 回调守护测试（Phase 72-03 / RATE-02 容器侧）。

覆盖 task 侧补全的 task→回调断点：
- ``CallbackClient.report_token_usage``：POST body type=token_usage + payload 字段对齐
  server serializer；可选字段非空透传；standalone 返回 True 不发 HTTP；HTTP 失败返回
  False 不抛（best-effort）。
- ``ClaudeRunner._execute_claude``：``_write_usage_data`` 后主动 emit；usage.json 仍写
  （向后兼容）；emit 抛错被吞不影响任务返回；model 解析 + ttft 富化。
- 四类容器（plan/execute/explore/repo_summary）执行路径都汇聚到 ``_execute_claude`` 的
  emit 发送点。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from core import executor as executor_module
from core.executor import ClaudeRunner
from integrations import CallbackClient

# === report_token_usage（callback client）===


class _DummyResponse:
    def raise_for_status(self) -> None:
        return None


def _make_capturing_client(sent: list[dict]) -> type:
    class _DummyClient:
        async def __aenter__(self) -> "_DummyClient":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def post(self, _url: str, json: dict, headers: dict, timeout: float):
            sent.append(json)
            return _DummyResponse()

    return _DummyClient


class _FailingClient:
    async def __aenter__(self) -> "_FailingClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object):
        raise httpx.ConnectError("boom")


@pytest.mark.asyncio
async def test_report_token_usage_standalone_returns_true(mock_config):
    """standalone 模式（无 callback_url）返回 True，不发 HTTP。"""
    mock_config.callback_url = ""
    mock_config.callback_token = ""
    client = CallbackClient(mock_config)

    result = await client.report_token_usage(
        {"input_tokens": 10, "output_tokens": 5, "model": "claude-sonnet-4-5"}
    )
    assert result is True


@pytest.mark.asyncio
async def test_report_token_usage_posts_token_usage_body(mock_config, monkeypatch):
    """enabled 模式：POST body type=token_usage，payload 含 input/output/model + 可选字段透传。"""
    sent: list[dict] = []
    monkeypatch.setattr(
        "integrations.callback.httpx.AsyncClient", _make_capturing_client(sent)
    )
    mock_config.callback_url = "http://localhost:8000/api"
    mock_config.callback_token = "test-token"
    client = CallbackClient(mock_config)

    result = await client.report_token_usage(
        {
            "input_tokens": 120,
            "output_tokens": 30,
            "cache_read_tokens": 5,
            "cache_write_tokens": 2,
            "total_cost_usd": 0.0012,
            "model": "claude-sonnet-4-5",
            "provider": "anthropic",
            "ttft_ms": 850,
        }
    )

    assert result is True
    body = sent[0]
    assert body["type"] == "token_usage"
    assert body["session_id"] == mock_config.task_id
    payload = body["payload"]
    assert payload["input_tokens"] == 120
    assert payload["output_tokens"] == 30
    assert payload["model"] == "claude-sonnet-4-5"
    assert "timestamp" in payload
    # 可选字段非空时透传
    assert payload["provider"] == "anthropic"
    assert payload["ttft_ms"] == 850


@pytest.mark.asyncio
async def test_report_token_usage_omits_empty_optional_fields(mock_config, monkeypatch):
    """可选字段缺省/空 → 不放入 body（向后兼容降级，交 server 兜底派生）。"""
    sent: list[dict] = []
    monkeypatch.setattr(
        "integrations.callback.httpx.AsyncClient", _make_capturing_client(sent)
    )
    mock_config.callback_url = "http://localhost:8000/api"
    mock_config.callback_token = "test-token"
    client = CallbackClient(mock_config)

    await client.report_token_usage(
        {"input_tokens": 1, "output_tokens": 1, "model": "m"}
    )
    payload = sent[0]["payload"]
    assert "provider" not in payload
    assert "ttft_ms" not in payload
    assert "call_source" not in payload


@pytest.mark.asyncio
async def test_report_token_usage_http_failure_returns_false(mock_config, monkeypatch):
    """HTTP 失败 → 返回 False 不抛（best-effort，不影响任务终态）。"""
    monkeypatch.setattr("integrations.callback.httpx.AsyncClient", _FailingClient)
    mock_config.callback_url = "http://localhost:8000/api"
    mock_config.callback_token = "test-token"
    client = CallbackClient(mock_config)

    result = await client.report_token_usage(
        {"input_tokens": 1, "output_tokens": 1, "model": "m"}
    )
    assert result is False


# === _resolve_usage_model ===


def test_resolve_usage_model_prefers_result_model():
    rm = MagicMock()
    rm.model = "claude-real-model"
    assert ClaudeRunner._resolve_usage_model(rm, "main") == "claude-real-model"


def test_resolve_usage_model_falls_back_to_main_model():
    rm = MagicMock()
    rm.model = None
    rm.usage = {}
    assert ClaudeRunner._resolve_usage_model(rm, "claude-sonnet-4-5") == "claude-sonnet-4-5"


def test_resolve_usage_model_hardcoded_when_unresolvable():
    rm = MagicMock()
    rm.model = None
    rm.usage = {}
    # main_model 非 str（解析失败）→ 回退原硬编码默认（零回归）
    assert ClaudeRunner._resolve_usage_model(rm, object()) == "claude-opus-4-6"


# === _execute_claude：emit + usage.json ===


class _FakeText:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeAssistant:
    def __init__(self, content: list) -> None:
        self.content = content


class _FakeResult:
    def __init__(self) -> None:
        self.usage = {"input_tokens": 120, "output_tokens": 30}
        self.result = "done"
        self.session_id = "sess-1"
        self.total_cost_usd = 0.0012
        self.subtype = "success"
        self.model = "claude-sonnet-4-5"


def _patch_sdk(monkeypatch) -> None:
    """把 SDK 消息类型与 query 替换为可控 fake。"""
    monkeypatch.setattr(executor_module, "AssistantMessage", _FakeAssistant)
    monkeypatch.setattr(executor_module, "TextBlock", _FakeText)
    monkeypatch.setattr(executor_module, "ResultMessage", _FakeResult)

    async def _fake_query(prompt, options):
        yield _FakeAssistant([_FakeText("hello")])
        yield _FakeResult()

    monkeypatch.setattr(executor_module, "query", _fake_query)

    class _FakeOptions:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(executor_module, "ClaudeAgentOptions", _FakeOptions)


def _exec_config(temp_session_dir):
    config = MagicMock()
    config.claude_api_key = "k"
    config.claude_base_url = ""
    config.claude_haiku_model = ""
    config.claude_small_model = ""
    config.claude_model = ""
    config.claude_sonnet_model = "claude-sonnet-4-5"
    config.claude_opus_model = ""
    config.claude_max_turns = 10
    config.resume_session_id = None
    config.remote_tools = []
    config.tools_endpoint = ""
    config.user_token = ""
    config.task_id = "exec-emit-001"
    config.task_mode = "execute"
    config.session_dir = temp_session_dir
    config.follow_openspec = False
    config.task_description = "do a thing"
    # _save_session 会 JSON 序列化以下字段，必须是可序列化的真实值（非 MagicMock）。
    config.git_repo_url = "git@github.com:test/repo.git"
    config.git_branch = "main"
    # 富化 provider：默认不带（getattr 取 MagicMock 会是真值，显式置空避免污染断言）
    config.claude_provider = ""
    config.provider_type = ""
    return config


@pytest.mark.asyncio
async def test_execute_claude_emits_and_writes_usage_json(
    monkeypatch, temp_workspace, temp_session_dir
):
    """_write_usage_data 写 usage.json + 主动 emit report_token_usage 一次。"""
    _patch_sdk(monkeypatch)
    config = _exec_config(temp_session_dir)
    callback = MagicMock()
    callback.report_token_usage = AsyncMock(return_value=True)

    runner = ClaudeRunner(config, temp_workspace, callback=callback)
    result = await runner._execute_claude(prompt="p", permission_mode="bypassPermissions")

    assert result["success"] is True
    # usage.json 仍写（向后兼容）
    usage_file = Path(temp_workspace) / ".friday" / "usage.json"
    assert usage_file.exists()
    import json

    usage = json.loads(usage_file.read_text())
    assert usage["input_tokens"] == 120
    assert usage["output_tokens"] == 30
    assert usage["model"] == "claude-sonnet-4-5"
    assert usage["ttft_ms"] >= 0  # 富化：捕获到首 AssistantMessage

    # 主动 emit 一次，payload 即 usage_data
    callback.report_token_usage.assert_awaited_once()
    emitted = callback.report_token_usage.await_args.args[0]
    assert emitted["input_tokens"] == 120
    assert emitted["model"] == "claude-sonnet-4-5"


@pytest.mark.asyncio
async def test_execute_claude_emit_failure_does_not_break_task(
    monkeypatch, temp_workspace, temp_session_dir
):
    """emit 抛错被 executor 吞，不影响任务成功返回（best-effort 不反噬）。"""
    _patch_sdk(monkeypatch)
    config = _exec_config(temp_session_dir)
    callback = MagicMock()
    callback.report_token_usage = AsyncMock(side_effect=RuntimeError("emit boom"))

    runner = ClaudeRunner(config, temp_workspace, callback=callback)
    result = await runner._execute_claude(prompt="p", permission_mode="bypassPermissions")

    assert result["success"] is True
    callback.report_token_usage.assert_awaited_once()
    # usage.json 仍写
    assert (Path(temp_workspace) / ".friday" / "usage.json").exists()


@pytest.mark.asyncio
async def test_execute_claude_no_callback_still_writes_usage(
    monkeypatch, temp_workspace, temp_session_dir
):
    """callback 为 None（向后兼容）：仅写 usage.json，不 emit、不报错。"""
    _patch_sdk(monkeypatch)
    config = _exec_config(temp_session_dir)

    runner = ClaudeRunner(config, temp_workspace, callback=None)
    result = await runner._execute_claude(prompt="p", permission_mode="bypassPermissions")

    assert result["success"] is True
    assert (Path(temp_workspace) / ".friday" / "usage.json").exists()


# === 四类容器执行路径全覆盖：都汇聚到 _execute_claude 的 emit 发送点 ===


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["plan", "execute", "explore", "repo_summary"])
async def test_all_container_modes_funnel_through_execute_claude(
    monkeypatch, temp_workspace, temp_session_dir, mode
):
    """plan/execute/explore/repo_summary 四类执行路径都到达 _execute_claude（emit 唯一发送点）。"""
    config = _exec_config(temp_session_dir)
    config.task_mode = mode
    runner = ClaudeRunner(config, temp_workspace, callback=None)

    spy = AsyncMock(return_value={"success": True, "output": "x"})
    monkeypatch.setattr(runner, "_execute_claude", spy)

    method = {
        "plan": runner.run_plan_mode,
        "execute": runner.run_execute_mode,
        "explore": runner.run_explore_mode,
        "repo_summary": runner.run_repo_summary_mode,
    }[mode]

    await method()

    spy.assert_awaited()
