"""编码遇阻 HITL 测试（Phase 47，HITL-01a）。

覆盖：
- CallbackClient.report_question 发起 question 帧（payload 对齐 server QuestionPayloadSerializer）
- ask_user_and_wait：取 answer.json 回答 / 超时 default 续跑 / 超时无 default 抛 QuestionTimeout
- build_ask_user_mcp_server 向后兼容（无 callback_url → None）
"""

import json
from unittest.mock import AsyncMock

import pytest

from core.question_loop import (
    QuestionTimeout,
    ask_user_and_wait,
    build_ask_user_mcp_server,
)
from integrations import CallbackClient


class _DummyResponse:
    def raise_for_status(self):
        return None


def _capturing_client(sink: list):
    class _DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, _url, json, headers, timeout):
            sink.append(json)
            return _DummyResponse()

    return _DummyClient


class TestReportQuestion:
    """CallbackClient.report_question —— type=question 帧 + payload 对齐 serializer。"""

    @pytest.mark.asyncio
    async def test_report_question_standalone_returns_true(self, mock_config):
        mock_config.callback_url = ""
        mock_config.callback_token = ""
        client = CallbackClient(mock_config)
        result = await client.report_question("怎么处理这个冲突？", options=["A", "B"])
        assert result is True

    @pytest.mark.asyncio
    async def test_report_question_posts_question_frame(self, mock_config, monkeypatch):
        sent: list = []
        monkeypatch.setattr(
            "integrations.callback.httpx.AsyncClient", _capturing_client(sent)
        )
        mock_config.callback_url = "http://localhost:8000/api"
        mock_config.callback_token = "tok"
        client = CallbackClient(mock_config)

        result = await client.report_question(
            question="用哪个数据库迁移策略？",
            options=["在线迁移", "停机迁移"],
            context="表 user 加字段",
            code_snippet="ALTER TABLE user ...",
            default_option="在线迁移",
            timeout_minutes=15,
        )

        assert result is True
        assert len(sent) == 1
        body = sent[0]
        assert body["type"] == "question"
        assert body["session_id"] == mock_config.task_id
        payload = body["payload"]
        # 键名严格对齐 server QuestionPayloadSerializer
        assert set(payload.keys()) == {
            "question",
            "options",
            "context",
            "code_snippet",
            "default_option",
            "timeout_minutes",
        }
        assert payload["question"] == "用哪个数据库迁移策略？"
        assert payload["options"] == ["在线迁移", "停机迁移"]
        assert payload["default_option"] == "在线迁移"
        assert payload["timeout_minutes"] == 15

    @pytest.mark.asyncio
    async def test_report_question_http_error_failsoft(self, mock_config, monkeypatch):
        import httpx

        class _FailingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def post(self, *a, **k):
                raise httpx.ConnectError("boom")

        monkeypatch.setattr("integrations.callback.httpx.AsyncClient", _FailingClient)
        mock_config.callback_url = "http://localhost:8000/api"
        mock_config.callback_token = "tok"
        client = CallbackClient(mock_config)

        result = await client.report_question("q?")
        assert result is False


class TestAskUserAndWait:
    """ask_user_and_wait —— 取回答 / 超时 default / 超时 raise。"""

    @pytest.mark.asyncio
    async def test_returns_answer_from_volume(self, tmp_path):
        (tmp_path / "answer.json").write_text(
            json.dumps({"question_id": "q1", "answer": "用方案A"}), encoding="utf-8"
        )
        callback = AsyncMock()
        answer = await ask_user_and_wait(
            callback,
            "选哪个方案？",
            protocol_dir=str(tmp_path),
            poll_interval_s=0.0,
        )
        assert answer == "用方案A"
        callback.report_question.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_timeout_with_default_returns_default(self, tmp_path):
        callback = AsyncMock()
        # _now 递增越过 deadline；_sleep no-op
        ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0])

        def _now():
            try:
                return next(ticks)
            except StopIteration:
                return 100.0

        answer = await ask_user_and_wait(
            callback,
            "选哪个方案？",
            default_option="方案B",
            timeout_minutes=1,
            protocol_dir=str(tmp_path),
            poll_interval_s=0.0,
            _now=_now,
            _sleep=AsyncMock(),
        )
        assert answer == "方案B"

    @pytest.mark.asyncio
    async def test_timeout_without_default_raises(self, tmp_path):
        callback = AsyncMock()
        ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0])

        def _now():
            try:
                return next(ticks)
            except StopIteration:
                return 100.0

        with pytest.raises(QuestionTimeout):
            await ask_user_and_wait(
                callback,
                "选哪个方案？",
                default_option="",
                timeout_minutes=1,
                protocol_dir=str(tmp_path),
                poll_interval_s=0.0,
                _now=_now,
                _sleep=AsyncMock(),
            )


class TestBuildAskUserMcpServer:
    """build_ask_user_mcp_server 向后兼容。"""

    def test_none_when_standalone(self, mock_config):
        mock_config.callback_url = ""
        callback = AsyncMock()
        assert build_ask_user_mcp_server(mock_config, callback) is None

    def test_built_when_callback_configured(self, mock_config):
        mock_config.callback_url = "http://localhost:8000/api"
        callback = AsyncMock()
        server = build_ask_user_mcp_server(mock_config, callback)
        assert server is not None
