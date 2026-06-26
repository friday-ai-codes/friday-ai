"""LLM 调用数据采集守护测试（RATE-02 / SLA-03 / SLA-04）。

覆盖（72-02）：
- ``CallSource`` 枚举含 LOGGING-SPEC §4.1 全部 22 值 + ``normalize`` 兜底。
- ``call_source`` contextvar set/get/use_call_source 作用域恢复。
- ``arecord_llm_usage``（run 可选）落行 + user 从 Phase 71 contextvars 取 +
  写库失败 best-effort 不反噬。
- ``parse_upstream_status`` 只取数值上游码（429/529）。
- chat_runner / langchain_runner 的 astream 落 ModelUsageRecord（call_source /
  TTFT / input·output token / 上游 429 单列）。
- compat/chat 入口 ``use_call_source`` 上下文内 call_source 正确传播。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import structlog
from langchain_core.messages import AIMessageChunk

from agents.call_source import (
    CallSource,
    get_call_source,
    set_call_source,
    use_call_source,
)
from interactions.ledger import arecord_llm_usage, parse_upstream_status
from interactions.models import InteractionRun, ModelUsageRecord

# LOGGING-SPEC §4.1 权威 27 值（照抄，作为完整性守护基准；
# v0.15.0 Phase 80 新增 ``memory_distill``；v0.16.0 Phase 86 新增 ``ide_hook_distill``；
# v0.16.0 Phase 87 新增 ``board_split``；v0.16.0 Phase 88 新增 ``repo_verify_container`` /
# ``repo_association``）。
_EXPECTED_CALL_SOURCES = {
    "chat",
    "chat_compat_openai",
    "chat_compat_anthropic",
    "workflow_agent_node",
    "workflow_prompt_node",
    "workflow_variable_extractor",
    "workflow_coding_container",
    "plan_merge",
    "plan_spec_generation",
    "aux_title",
    "aux_sensitive_llm",
    "aux_screenshot_vision",
    "aux_knowledge_grader",
    "aux_corpus_tree",
    "aux_repo_router",
    "aux_crawl",
    "repo_summary_container",
    "deep_analysis_container",
    "sdk_agent_task",
    "provider_health_probe",
    "embedding",
    "reranker",
    "memory_distill",
    "ide_hook_distill",
    "board_split",
    "repo_verify_container",
    "repo_association",
}


# ===========================================================================
# Task 1：CallSource 枚举 + contextvar 传播
# ===========================================================================


class TestCallSourceEnum:
    def test_enum_has_all_22_values(self) -> None:
        """枚举必须完整覆盖 LOGGING-SPEC §4.1 的 27 值，多一个少一个都失败。

        历史名保留（test_enum_has_all_22_values）；v0.15.0 Phase 80 新增
        ``memory_distill`` 后基准升至 23 值；v0.16.0 Phase 86 新增
        ``ide_hook_distill`` 后升至 24 值；v0.16.0 Phase 87 新增 ``board_split`` 后升至 25 值；
        v0.16.0 Phase 88 新增 ``repo_verify_container`` / ``repo_association`` 后升至 27 值。
        """
        assert {member.value for member in CallSource} == _EXPECTED_CALL_SOURCES
        assert len(_EXPECTED_CALL_SOURCES) == 27

    def test_normalize_valid_value(self) -> None:
        assert CallSource.normalize("chat") == "chat"
        assert CallSource.normalize(CallSource.WORKFLOW_AGENT_NODE) == "workflow_agent_node"
        assert CallSource.normalize("CHAT") == "chat"  # 大小写不敏感

    def test_normalize_bogus_falls_back_to_default(self) -> None:
        assert CallSource.normalize("bogus") == "unknown"
        assert CallSource.normalize(None) == "unknown"
        assert CallSource.normalize("bogus", default="chat") == "chat"


class TestCallSourceContextVar:
    def test_get_returns_none_when_unset(self) -> None:
        assert get_call_source() is None

    def test_use_call_source_sets_and_restores(self) -> None:
        assert get_call_source() is None
        with use_call_source("chat"):
            assert get_call_source() == "chat"
            with use_call_source(CallSource.AUX_TITLE):
                assert get_call_source() == "aux_title"
            # 内层退出后恢复外层
            assert get_call_source() == "chat"
        # 全部退出后恢复 None
        assert get_call_source() is None

    def test_use_call_source_normalizes_bogus(self) -> None:
        with use_call_source("not-a-real-source"):
            assert get_call_source() == "unknown"

    def test_set_call_source_returns_token(self) -> None:
        import contextvars

        token = set_call_source("chat")
        try:
            assert get_call_source() == "chat"
            assert isinstance(token, contextvars.Token)
        finally:
            # 清理：恢复，避免泄漏到后续测试
            from agents.call_source import _call_source_var

            _call_source_var.reset(token)
        assert get_call_source() is None


# ===========================================================================
# Task 1：parse_upstream_status
# ===========================================================================


class TestParseUpstreamStatus:
    def test_status_code_attr(self) -> None:
        exc = SimpleNamespace(status_code=429)
        assert parse_upstream_status(exc) == 429  # type: ignore[arg-type]

    def test_overloaded_529(self) -> None:
        exc = SimpleNamespace(status_code=529)
        assert parse_upstream_status(exc) == 529  # type: ignore[arg-type]

    def test_response_status_code(self) -> None:
        exc = SimpleNamespace(response=SimpleNamespace(status_code=503))
        assert parse_upstream_status(exc) == 503  # type: ignore[arg-type]

    def test_no_status_returns_none(self) -> None:
        assert parse_upstream_status(RuntimeError("boom")) is None

    def test_invalid_status_returns_none(self) -> None:
        exc = SimpleNamespace(status_code="not-an-int")
        assert parse_upstream_status(exc) is None  # type: ignore[arg-type]


# ===========================================================================
# Task 1：arecord_llm_usage（run 可选 + best-effort）
# ===========================================================================


@pytest.mark.django_db(transaction=True)
class TestArecordLlmUsage:
    async def test_records_runless_row(self) -> None:
        """run=None 也能独立成行（非 MCP 的 LLM 调用，per RATE-02）。"""
        record = await arecord_llm_usage(
            run=None,
            call_source="chat",
            provider="anthropic",
            model="claude-sonnet-4-5",
            prompt_tokens=10,
            completion_tokens=5,
            ttft_ms=123,
            source="chat",
        )
        assert record is not None
        assert record.run_id is None
        assert record.call_source == "chat"
        assert record.prompt_tokens == 10
        assert record.completion_tokens == 5
        assert record.total_tokens == 15  # 缺省按 input+output 兜底
        assert record.ttft_ms == 123
        assert record.source == "chat"

    async def test_user_id_from_contextvars_when_omitted(self) -> None:
        """user_id 缺省从 Phase 71 contextvars 取（无则 system）。"""
        structlog.contextvars.bind_contextvars(user_id="42")
        try:
            record = await arecord_llm_usage(
                call_source="chat",
                provider="anthropic",
                model="m",
            )
        finally:
            structlog.contextvars.unbind_contextvars("user_id")
        assert record is not None
        assert record.user_id == "42"

    async def test_user_id_defaults_to_system(self) -> None:
        structlog.contextvars.clear_contextvars()
        record = await arecord_llm_usage(
            call_source="chat", provider="anthropic", model="m"
        )
        assert record is not None
        assert record.user_id == "system"

    async def test_run_bound_row_backward_compatible(self) -> None:
        """run 仍可传 InteractionRun 实例（MCP 路径向后兼容）。"""
        run = await InteractionRun.objects.acreate(source="mcp")
        record = await arecord_llm_usage(
            run=run,
            call_source="aux_title",
            provider="anthropic",
            model="m",
        )
        assert record is not None
        assert record.run_id == run.id

    async def test_upstream_429_single_column(self) -> None:
        """上游 429 单列写 upstream_status_code + failure_type（per SLA-03）。"""
        record = await arecord_llm_usage(
            call_source="chat",
            provider="anthropic",
            model="m",
            upstream_status_code=429,
            failure_type="429",
        )
        assert record is not None
        assert record.upstream_status_code == 429
        assert record.failure_type == "429"

    async def test_write_failure_is_best_effort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """写库异常 → 返回 None + warning，不抛（best-effort，T-72-02-05）。"""

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("db down")

        monkeypatch.setattr(ModelUsageRecord.objects, "create", _boom)
        result = await arecord_llm_usage(
            call_source="chat", provider="anthropic", model="m"
        )
        assert result is None

    async def test_bogus_call_source_normalized(self) -> None:
        """非法 call_source 经 normalize 受控（T-72-02-03）。"""
        record = await arecord_llm_usage(
            call_source="totally-bogus", provider="anthropic", model="m"
        )
        assert record is not None
        assert record.call_source == "unknown"


# ===========================================================================
# Task 2：runner astream 埋点 + compat/chat call_source 传播
# ===========================================================================


def _make_bound_model(chunks: list[AIMessageChunk]):
    async def _astream(_messages: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
        for chunk in chunks:
            yield chunk

    return SimpleNamespace(astream=_astream)


@pytest.mark.django_db(transaction=True)
class TestChatRunnerUsageRecording:
    async def test_chat_runner_records_usage_with_ttft(self) -> None:
        """chat_runner 流式结束落一行 ModelUsageRecord(call_source=chat, ttft 非空,
        input/output token 正确)。"""
        from agents.chat_runner import ChatAnthropicRunner, ChatRunnerConfig

        config = ChatRunnerConfig(
            system_prompt="x",
            model="claude-sonnet-4-5",
            space_id="",  # 空 space → 不触发 Repository ORM 查询
            session_id="s1",
            conversation_id="",
            api_key="sk-test",
        )
        runner = ChatAnthropicRunner(config)
        bound_model = _make_bound_model(
            [
                AIMessageChunk(content="你"),
                AIMessageChunk(
                    content="好",
                    response_metadata={"usage": {"input_tokens": 10, "output_tokens": 2}},
                ),
            ]
        )
        fake_model = MagicMock()
        fake_model.bind_tools.return_value = bound_model

        with (
            patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
            patch("agents.chat_runner._build_tool_specs", return_value={}),
            patch(
                "agents.chat_runner._load_history_messages",
                new=_async_return([]),
            ),
        ):
            _events = [event async for event in runner.stream("你好")]

        record = await ModelUsageRecord.objects.filter(call_source="chat").afirst()
        assert record is not None
        assert record.prompt_tokens == 10
        assert record.completion_tokens == 2
        assert record.ttft_ms is not None
        assert record.source == "chat"

    async def test_chat_runner_records_upstream_status_on_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """注入上游 429 异常 → upstream_status_code=429 + failure_type 记 429。"""
        from agents.chat_runner import ChatAnthropicRunner, ChatRunnerConfig

        config = ChatRunnerConfig(
            system_prompt="x",
            model="claude-sonnet-4-5",
            space_id="",
            session_id="s1",
            conversation_id="",
            api_key="sk-test",
        )
        runner = ChatAnthropicRunner(config)

        class _UpstreamError(Exception):
            status_code = 429

        async def _astream_raises(_messages: list[object]):
            raise _UpstreamError("rate limited")
            yield  # pragma: no cover — 使其成为 async generator

        bound_model = SimpleNamespace(astream=_astream_raises)
        fake_model = MagicMock()
        fake_model.bind_tools.return_value = bound_model

        with (
            patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
            patch("agents.chat_runner._build_tool_specs", return_value={}),
            patch(
                "agents.chat_runner._load_history_messages",
                new=_async_return([]),
            ),
        ):
            _events = [event async for event in runner.stream("你好")]

        record = await ModelUsageRecord.objects.filter(
            upstream_status_code=429
        ).afirst()
        assert record is not None
        assert record.failure_type == "429"
        assert record.call_source == "chat"


@pytest.mark.django_db(transaction=True)
class TestLangChainRunnerUsageRecording:
    async def test_langchain_runner_records_usage(self) -> None:
        """langchain_runner 的 astream 落一行 ModelUsageRecord(call_source 默认
        workflow_agent_node, input/output token 正确)。"""
        from agents.langchain_runner import (
            LangChainAgentRunner,
            LangChainRunnerConfig,
        )
        from services.provider_config import ProviderType, ResolvedProviderConfig

        resolved = ResolvedProviderConfig(
            provider_type=ProviderType.ANTHROPIC,
            api_key="sk-fake",
            base_url="https://api.anthropic.com",
            source="system",
        )
        config = LangChainRunnerConfig(resolved=resolved, model="claude-x", session_id="s")
        runner = LangChainAgentRunner(config)

        async def _astream(_messages: list[object]):
            yield AIMessageChunk(content="答案")
            yield AIMessageChunk(
                content="",
                usage_metadata={
                    "input_tokens": 7,
                    "output_tokens": 3,
                    "total_tokens": 10,
                },
            )

        fake_model = SimpleNamespace(astream=_astream)

        with patch.object(LangChainAgentRunner, "_build_model", return_value=fake_model):
            _events = [event async for event in runner.stream("问题")]

        record = await ModelUsageRecord.objects.filter(
            call_source="workflow_agent_node"
        ).afirst()
        assert record is not None
        assert record.prompt_tokens == 7
        assert record.completion_tokens == 3


class TestCompatChatCallSourcePropagation:
    def test_use_call_source_compat_openai(self) -> None:
        with use_call_source(CallSource.CHAT_COMPAT_OPENAI):
            assert get_call_source() == "chat_compat_openai"

    def test_use_call_source_compat_anthropic(self) -> None:
        with use_call_source(CallSource.CHAT_COMPAT_ANTHROPIC):
            assert get_call_source() == "chat_compat_anthropic"

    def test_use_call_source_chat(self) -> None:
        with use_call_source(CallSource.CHAT):
            assert get_call_source() == "chat"


# ===========================================================================
# helpers
# ===========================================================================


def _async_return(value: object):
    """构造一个 await 后返回 value 的 AsyncMock 替身（用于 patch async helper）。"""
    from unittest.mock import AsyncMock

    return AsyncMock(return_value=value)
