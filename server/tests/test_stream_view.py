"""ChatStreamView SSE 端点集成测试。

测试 SSE 流式响应的格式、事件序列、错误处理。
ConversationService.send_message_stream 通过 mock 避免真实 LLM 调用。
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.test import AsyncClient

from agents.core.events import (
    MESSAGE_COMPLETE,
    TEXT_DELTA,
    TITLE_GENERATED,
    AgentEvent,
)
from agents.models import AgentSession
from chat.conversation_service import ConversationService
from chat.models import Conversation
from projects.models import Project
from subagent.models import SubAgentSession

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def test_project(db):
    """创建测试项目。"""
    return Project.objects.create(name="Stream Test Project")


@pytest.fixture
def conversation(db, test_project):
    """创建测试对话。"""
    return Conversation.objects.create(project=test_project, title="新对话")


# ============================================================================
# Helpers
# ============================================================================


# Mock 路径：patch ConversationService 类上的 staticmethod
MOCK_STREAM_PATH = "chat.conversation_service.ConversationService.send_message_stream"


def _apply_stream_mock(events: list[AgentEvent] | None = None):
    """创建 patch context manager，替换 send_message_stream 为 mock generator。"""
    if events is None:
        events = [
            AgentEvent(type=TEXT_DELTA, data={"text": "你"}),
            AgentEvent(type=TEXT_DELTA, data={"text": "好"}),
            AgentEvent(type=MESSAGE_COMPLETE, data={
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "status": "completed",
                "iterations": 1,
            }),
        ]

    async def mock_send_message_stream(
        conversation_id: str,
        content: str,
        role: str = "developer",
        notification_user_id: str | None = None,
        **kwargs: object,
    ):
        for event in events:
            yield event

    return patch.object(ConversationService, "send_message_stream", staticmethod(mock_send_message_stream))


def _parse_sse_events(raw_content: str) -> list[dict]:
    """从 SSE 原始内容中解析事件。"""
    events = []
    for block in raw_content.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            events.append(json.loads(block[6:]))
    return events


# ============================================================================
# ChatStreamView 测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestChatStreamView:
    """ChatStreamView SSE 端点测试。"""

    async def test_stream_returns_sse_content_type(self, conversation):
        """SSE 端点返回 text/event-stream Content-Type。"""
        client = AsyncClient()
        with _apply_stream_mock():
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "你好"},
                content_type="application/json",
            )

        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/event-stream"
        assert resp["Cache-Control"] == "no-cache"
        assert resp["X-Accel-Buffering"] == "no"

    async def test_stream_events_format(self, conversation):
        """SSE 事件格式正确：data: {json}\\n\\n。"""
        client = AsyncClient()
        with _apply_stream_mock():
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "你好"},
                content_type="application/json",
            )

            # 收集所有 streaming content
            raw_parts = []
            async for chunk in resp.streaming_content:
                text = chunk.decode() if isinstance(chunk, bytes) else chunk
                raw_parts.append(text)
        raw = "".join(raw_parts)

        events = _parse_sse_events(raw)
        assert len(events) == 3
        assert events[0]["type"] == "text_delta"
        assert events[0]["text"] == "你"
        assert events[1]["type"] == "text_delta"
        assert events[1]["text"] == "好"
        assert events[2]["type"] == "message_complete"

    async def test_stream_events_contain_message_id(self, conversation):
        """每个 SSE 事件包含 message_id 字段。"""
        client = AsyncClient()
        with _apply_stream_mock():
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "你好"},
                content_type="application/json",
            )

            raw_parts = []
            async for chunk in resp.streaming_content:
                text = chunk.decode() if isinstance(chunk, bytes) else chunk
                raw_parts.append(text)
        raw = "".join(raw_parts)

        events = _parse_sse_events(raw)
        assert all("message_id" in e for e in events)
        # 所有事件的 message_id 相同
        ids = {e["message_id"] for e in events}
        assert len(ids) == 1

    async def test_stream_conversation_not_found(self):
        """对话不存在返回 404。"""
        client = AsyncClient()
        resp = await client.post(
            "/api/chat/conversations/00000000-0000-0000-0000-000000000000/stream/",
            data={"content": "你好"},
            content_type="application/json",
        )
        assert resp.status_code == 404

    async def test_stream_missing_content(self, conversation):
        """缺少 content 返回 400。"""
        client = AsyncClient()
        resp = await client.post(
            f"/api/chat/conversations/{conversation.id}/stream/",
            data={},
            content_type="application/json",
        )
        assert resp.status_code == 400

    async def test_stream_empty_content(self, conversation):
        """content 为空返回 400。"""
        client = AsyncClient()
        resp = await client.post(
            f"/api/chat/conversations/{conversation.id}/stream/",
            data={"content": ""},
            content_type="application/json",
        )
        assert resp.status_code == 400

    async def test_stream_accepts_image_parts_without_text(self, conversation, monkeypatch):
        """有 image input_parts 时允许空 content，并透传给 ConversationService。"""
        captured: dict[str, object] = {}

        async def mock_send(
            conversation_id: str,
            content: str,
            role: str = "developer",
            notification_user_id: str | None = None,
            **kwargs: object,
        ):
            captured["content"] = content
            captured["input_parts"] = kwargs.get("input_parts")
            yield AgentEvent(type=MESSAGE_COMPLETE, data={
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "status": "completed",
                "iterations": 1,
            })

        monkeypatch.setattr(
            ConversationService,
            "send_message_stream",
            staticmethod(mock_send),
        )

        image_part = {
            "type": "image",
            "id": "p_img",
            "index": 0,
            "mime_type": "image/png",
            "size_bytes": 68,
            "storage_ref": "chat_images/example.png",
            "detail": "auto",
        }
        client = AsyncClient()
        resp = await client.post(
            f"/api/chat/conversations/{conversation.id}/stream/",
            data=json.dumps({"content": "", "input_parts": [image_part]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        raw_parts: list[str] = []
        async for chunk in resp.streaming_content:
            text = chunk.decode() if isinstance(chunk, bytes) else chunk
            raw_parts.append(text)
        assert "".join(raw_parts)
        assert captured["content"] == ""
        assert captured["input_parts"] == [image_part]

    async def test_stream_with_role(self, conversation):
        """支持传入 role 参数。"""
        client = AsyncClient()
        with _apply_stream_mock():
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "你好", "role": "pm"},
                content_type="application/json",
            )
        assert resp.status_code == 200

    async def test_stream_accepts_optional_branch(self, conversation, monkeypatch):
        """可选 branch 字段不导致 400，并传入 send_message_stream。"""

        captured: dict[str, object] = {}

        async def mock_send(
            conversation_id: str,
            content: str,
            role: str = "developer",
            notification_user_id: str | None = None,
            force_deep_analysis: bool = False,
            feishu_doc_id: str = "",
            project_context_line: str | None = None,
            search_branch: str | None = None,
        ):
            captured["search_branch"] = search_branch
            yield AgentEvent(type=MESSAGE_COMPLETE, data={
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "status": "completed",
                "iterations": 1,
            })

        monkeypatch.setattr(
            ConversationService,
            "send_message_stream",
            staticmethod(mock_send),
        )

        client = AsyncClient()
        resp = await client.post(
            f"/api/chat/conversations/{conversation.id}/stream/",
            data=json.dumps({"content": "hi", "branch": "feature/phase"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        raw_parts: list[str] = []
        async for chunk in resp.streaming_content:
            text = chunk.decode() if isinstance(chunk, bytes) else chunk
            raw_parts.append(text)
        assert "".join(raw_parts)
        assert captured.get("search_branch") == "feature/phase"

    async def test_stream_includes_title_event(self, conversation):
        """title_generated 事件包含在 SSE 流中。"""
        events = [
            AgentEvent(type=TEXT_DELTA, data={"text": "回复"}),
            AgentEvent(type=MESSAGE_COMPLETE, data={
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "status": "completed",
                "iterations": 1,
            }),
            AgentEvent(type=TITLE_GENERATED, data={"title": "测试标题"}),
        ]

        client = AsyncClient()
        with _apply_stream_mock(events):
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "你好"},
                content_type="application/json",
            )

            raw_parts = []
            async for chunk in resp.streaming_content:
                text = chunk.decode() if isinstance(chunk, bytes) else chunk
                raw_parts.append(text)
        raw = "".join(raw_parts)

        parsed = _parse_sse_events(raw)
        types = [e["type"] for e in parsed]
        assert "title_generated" in types
        title_event = next(e for e in parsed if e["type"] == "title_generated")
        assert title_event["title"] == "测试标题"

    async def test_stream_deleted_conversation_returns_404(self, conversation):
        """已删除的对话返回 404。"""
        conversation.is_deleted = True
        await conversation.asave()

        client = AsyncClient()
        resp = await client.post(
            f"/api/chat/conversations/{conversation.id}/stream/",
            data={"content": "你好"},
            content_type="application/json",
        )
        assert resp.status_code == 404


# ============================================================================
# ChatInterruptView 测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestChatInterruptView:
    """ChatInterruptView 中断端点测试。"""

    async def test_interrupt_returns_200_with_active_runner(self, conversation):
        """有活跃 runner 时返回 200。"""
        from unittest.mock import AsyncMock, MagicMock

        from orchestration.runner_registry import _active_runners

        mock_runner = MagicMock()
        mock_runner.interrupt = AsyncMock()

        conv_id_str = str(conversation.id)
        _active_runners[conv_id_str] = mock_runner

        try:
            client = AsyncClient()
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/interrupt/",
                content_type="application/json",
            )

            assert resp.status_code == 200
            data = json.loads(resp.content)
            assert data["status"] == "interrupted"
            mock_runner.interrupt.assert_awaited_once()
        finally:
            _active_runners.pop(conv_id_str, None)

    async def test_interrupt_no_active_returns_404(self, conversation):
        """无活跃 runner 时返回 404。"""
        client = AsyncClient()
        resp = await client.post(
            f"/api/chat/conversations/{conversation.id}/interrupt/",
            content_type="application/json",
        )

        assert resp.status_code == 404


@pytest.mark.django_db(transaction=True)
class TestConversationRuntimeView:
    """ConversationRuntimeView 运行态查询测试。"""

    async def test_runtime_returns_inactive_by_default(self, conversation):
        client = AsyncClient()
        resp = await client.get(f"/api/chat/conversations/{conversation.id}/runtime/")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["conversation_id"] == str(conversation.id)
        assert payload["active"] is False
        assert payload["logs"] == []

    async def test_runtime_returns_deep_analysis_snapshot(self, conversation, test_project):
        agent_session = await AgentSession.objects.acreate(
            session_id="agent-runtime-test",
            project=test_project,
            status=AgentSession.Status.RUNNING,
            metadata={"conversation_id": str(conversation.id), "source": "chat_deep_analysis"},
        )
        await SubAgentSession.objects.acreate(
            session_id="deep-runtime-test",
            main_session=agent_session,
            repo_url="https://example.com/repo.git",
            task_type=SubAgentSession.TaskType.EXPLORE,
            status=SubAgentSession.Status.RUNNING,
            last_output={
                "source": "chat_deep_analysis",
                "conversation_id": str(conversation.id),
                "task_description": "分析登录流程",
                "progress": {"message": "正在读取关键文件", "progress": 0.5},
                "logs": [
                    {"type": "tool_call", "content": "Read({\"file_path\":\"src/auth.ts\"})", "ts": 1},
                    {"type": "text", "content": "已找到登录入口。", "ts": 2},
                ],
            },
        )

        client = AsyncClient()
        resp = await client.get(f"/api/chat/conversations/{conversation.id}/runtime/")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["active"] is True
        assert payload["mode"] == "deep_analysis"
        assert payload["session_id"] == "deep-runtime-test"
        assert payload["task_description"] == "分析登录流程"
        assert payload["progress_message"] == "正在读取关键文件"
        assert payload["logs"][0]["type"] == "tool_call"

    async def test_interrupt_invalid_conversation_returns_404(self):
        """无效 UUID 对应无 runner 时返回 404。"""
        client = AsyncClient()
        resp = await client.post(
            "/api/chat/conversations/00000000-0000-0000-0000-000000000000/interrupt/",
            content_type="application/json",
        )

        assert resp.status_code == 404
        data = json.loads(resp.content)
        # owner gate（aget_for_user）先于活跃会话探测：不存在/越权统一返回「对话不存在」
        assert "对话不存在" in data["error"]
