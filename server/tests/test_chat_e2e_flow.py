"""对话全流程端到端集成测试。

验证对话系统从创建到历史记录加载的完整流程：
1. 创建对话 -> 201 + 有效 conversation 对象
2. SSE 流式发送消息 -> text_delta + message_complete 事件
3. 工具调用事件 -> tool_use_start + tool_use_result 正确传递
4. 中断流程 -> interrupt API + message_complete(status=interrupted)
5. 历史记录加载 -> GET 对话详情返回完整消息列表
6. Keepalive -> SSE 注释行正确发送

使用 Django AsyncClient + mock ConversationService.send_message_stream。
mock 策略：patch ConversationService.send_message_stream 替换为返回预定义事件的
async generator，验证从 HTTP 请求到 SSE 响应的完整链路。

注意：StreamingHttpResponse 是惰性的（async generator 在 response 被迭代时才执行），
因此必须在 patch 上下文内消费 streaming_content。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from django.test import AsyncClient

from agents.core.events import (
    KEEPALIVE,
    MESSAGE_COMPLETE,
    TEXT_DELTA,
    TOOL_USE_RESULT,
    TOOL_USE_START,
    AgentEvent,
)
from chat.models import Conversation, Message
from projects.models import Space

# ============================================================================
# 辅助函数
# ============================================================================


async def _read_streaming_body(resp) -> str:
    """读取 StreamingHttpResponse 的完整响应体。

    Django StreamingHttpResponse 无 .content 属性，
    需要通过异步迭代 streaming_content 读取。
    """
    chunks: list[str] = []
    async for chunk in resp:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(chunk)
    return "".join(chunks)


def _make_mock_stream(events: list[AgentEvent]):
    """创建 mock send_message_stream 静态方法。

    返回一个可被 async for 迭代的 async generator 工厂函数，
    签名匹配 ConversationService.send_message_stream。
    """

    async def mock_send_message_stream(
        conversation_id: str,
        content: str,
        role: str = "developer",
        notification_user_id: str | None = None,
        force_deep_analysis: bool = False,
        feishu_doc_id: str = "",
        project_context_line: str | None = None,
        search_branch: str | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        for event in events:
            yield event

    return mock_send_message_stream


def _parse_sse_data_lines(body: str) -> list[dict]:
    """从 SSE 响应体中提取所有 data 行并解析为 JSON。"""
    data_lines = [line for line in body.split("\n") if line.startswith("data: ")]
    return [json.loads(line[len("data: ") :]) for line in data_lines]


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def test_project(db):
    """创建测试项目（无仓库依赖）。"""
    return await Space.objects.acreate(
        name="E2E Test Space",
        description="端到端测试用项目",
    )


@pytest.fixture
async def conversation(db, test_project):
    """创建测试对话。"""
    return await Conversation.objects.acreate(
        space=test_project,
        title="测试对话",
    )


# ============================================================================
# Test 1: 创建对话
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestConversationCreation:
    """对话创建端到端测试。"""

    async def test_create_conversation_success(self, test_project):
        """POST /api/chat/conversations/ 携带 space_id 返回 201。"""
        client = AsyncClient()
        resp = await client.post(
            "/api/chat/conversations/",
            data={"space_id": str(test_project.id)},
            content_type="application/json",
        )

        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["space_id"] == str(test_project.id)
        assert "title" in data

    async def test_create_conversation_invalid_project(self):
        """无效 space_id 返回 400。"""
        client = AsyncClient()
        resp = await client.post(
            "/api/chat/conversations/",
            data={"space_id": "00000000-0000-0000-0000-000000000000"},
            content_type="application/json",
        )

        assert resp.status_code == 400


# ============================================================================
# Test 2: SSE 流式回复
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestSSEStreamFlow:
    """SSE 流式回复端到端测试。"""

    async def test_stream_returns_event_stream_content_type(self, conversation):
        """流式端点返回 Content-Type: text/event-stream。"""
        mock_events = [
            AgentEvent(type=TEXT_DELTA, data={"text": "你好"}),
            AgentEvent(type=MESSAGE_COMPLETE, data={"status": "completed"}),
        ]

        with patch(
            "chat.conversation_service.ConversationService.send_message_stream",
            new=_make_mock_stream(mock_events),
        ):
            client = AsyncClient()
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "你好"},
                content_type="application/json",
            )
            # 必须在 patch 上下文内消费 streaming 响应
            await _read_streaming_body(resp)

        assert resp["Content-Type"] == "text/event-stream"

    async def test_stream_text_delta_events(self, conversation):
        """SSE 流包含正确格式的 text_delta data 行。"""
        mock_events = [
            AgentEvent(type=TEXT_DELTA, data={"text": "Hello"}),
            AgentEvent(type=TEXT_DELTA, data={"text": " World"}),
            AgentEvent(type=MESSAGE_COMPLETE, data={"status": "completed"}),
        ]

        with patch(
            "chat.conversation_service.ConversationService.send_message_stream",
            new=_make_mock_stream(mock_events),
        ):
            client = AsyncClient()
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "测试"},
                content_type="application/json",
            )
            body = await _read_streaming_body(resp)

        payloads = _parse_sse_data_lines(body)
        text_deltas = [p for p in payloads if p.get("type") == "text_delta"]

        assert len(text_deltas) == 2
        assert text_deltas[0]["text"] == "Hello"
        assert text_deltas[1]["text"] == " World"

    async def test_stream_message_complete_event(self, conversation):
        """SSE 流末尾包含 message_complete 事件。"""
        mock_events = [
            AgentEvent(type=TEXT_DELTA, data={"text": "回复内容"}),
            AgentEvent(type=MESSAGE_COMPLETE, data={"status": "completed"}),
        ]

        with patch(
            "chat.conversation_service.ConversationService.send_message_stream",
            new=_make_mock_stream(mock_events),
        ):
            client = AsyncClient()
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "测试"},
                content_type="application/json",
            )
            body = await _read_streaming_body(resp)

        payloads = _parse_sse_data_lines(body)
        assert payloads[-1]["type"] == "message_complete"

    async def test_stream_tool_use_events(self, conversation):
        """SSE 流正确传递 tool_use_start + tool_use_result 事件。"""
        mock_events = [
            AgentEvent(
                type=TOOL_USE_START,
                data={
                    "tool_name": "search_code",
                    "tool_call_id": "tc_001",
                    "arguments": {"query": "test"},
                },
            ),
            AgentEvent(
                type=TOOL_USE_RESULT,
                data={
                    "tool_call_id": "tc_001",
                    "result": "Found 3 matches",
                    "is_error": False,
                },
            ),
            AgentEvent(type=MESSAGE_COMPLETE, data={"status": "completed"}),
        ]

        with patch(
            "chat.conversation_service.ConversationService.send_message_stream",
            new=_make_mock_stream(mock_events),
        ):
            client = AsyncClient()
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "搜索代码"},
                content_type="application/json",
            )
            body = await _read_streaming_body(resp)

        payloads = _parse_sse_data_lines(body)
        types = [p["type"] for p in payloads]
        assert "tool_use_start" in types
        assert "tool_use_result" in types

    async def test_stream_keepalive(self, conversation):
        """SSE 流包含 ': keepalive' 注释行。"""
        mock_events = [
            AgentEvent(type=KEEPALIVE, data={}),
            AgentEvent(type=TEXT_DELTA, data={"text": "内容"}),
            AgentEvent(type=MESSAGE_COMPLETE, data={"status": "completed"}),
        ]

        with patch(
            "chat.conversation_service.ConversationService.send_message_stream",
            new=_make_mock_stream(mock_events),
        ):
            client = AsyncClient()
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "测试"},
                content_type="application/json",
            )
            body = await _read_streaming_body(resp)

        # SSE 注释行格式: ": keepalive\n\n"
        assert ": keepalive" in body


# ============================================================================
# Test 3: 中断流程
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestInterruptFlow:
    """中断流程端到端测试。"""

    @pytest.mark.skip(
        reason=(
            "OBSOLETE: chat.conversation_service._active_runners 已在 v17.0 LangGraph "
            "编排迁移后移除。中断机制改走 OrchestrationRun + interrupt()，"
            "本测试基于旧 SDKAgentRunner 直接管理 runner 字典的契约。"
            "后续随 chat 中断流程的重构补一组新的 graph-driven 用例。"
        )
    )
    async def test_interrupt_active_conversation(self, conversation):
        """注册 mock runner 后 POST interrupt API 返回 200 并调用 interrupt()。"""
        from chat.conversation_service import _active_runners  # type: ignore[attr-defined]

        mock_runner = AsyncMock()
        mock_runner.interrupt = AsyncMock()

        conv_id_str = str(conversation.id)
        _active_runners[conv_id_str] = mock_runner

        try:
            client = AsyncClient()
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/interrupt/",
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "interrupted"
            mock_runner.interrupt.assert_awaited_once()
        finally:
            _active_runners.pop(conv_id_str, None)

    async def test_interrupt_no_active_conversation(self, conversation):
        """无活跃 runner 时 POST interrupt API 返回 404。"""
        client = AsyncClient()
        resp = await client.post(
            f"/api/chat/conversations/{conversation.id}/interrupt/",
        )

        assert resp.status_code == 404

    @pytest.mark.skip(
        reason=(
            "OBSOLETE: 同 test_interrupt_active_conversation —— _active_runners 全局字典"
            "已被 OrchestrationRun + LangGraph interrupt 替代。"
        )
    )
    async def test_resume_after_interrupt(self, conversation):
        """中断对话后重新发送消息，新 SSE 流正常启动（contract）。"""
        from chat.conversation_service import _active_runners  # type: ignore[attr-defined]

        # Phase: 中断
        mock_runner = AsyncMock()
        mock_runner.interrupt = AsyncMock()
        conv_id_str = str(conversation.id)
        _active_runners[conv_id_str] = mock_runner

        client = AsyncClient()
        resp = await client.post(
            f"/api/chat/conversations/{conversation.id}/interrupt/",
        )
        assert resp.status_code == 200
        mock_runner.interrupt.assert_awaited_once()
        _active_runners.pop(conv_id_str, None)

        # Phase: 恢复 — 新消息流正常
        resume_events = [
            AgentEvent(type=TEXT_DELTA, data={"text": "恢复回复"}),
            AgentEvent(type=MESSAGE_COMPLETE, data={"status": "completed"}),
        ]
        with patch(
            "chat.conversation_service.ConversationService.send_message_stream",
            new=_make_mock_stream(resume_events),
        ):
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "继续对话"},
                content_type="application/json",
            )
            body = await _read_streaming_body(resp)

        assert resp.status_code == 200
        payloads = _parse_sse_data_lines(body)
        assert any(p.get("type") == "text_delta" for p in payloads)
        assert any(p.get("type") == "message_complete" for p in payloads)
        # 验证恢复回复内容正确
        text_deltas = [p for p in payloads if p.get("type") == "text_delta"]
        assert text_deltas[0]["text"] == "恢复回复"

    async def test_interrupted_message_status_persisted(self, conversation):
        """被中断消息 metadata.status='interrupted'，后续消息独立记录（contract）。"""
        from asgiref.sync import sync_to_async

        # Phase: 中断场景 — mock stream 创建 interrupted 消息
        async def mock_interrupted_stream(
            conversation_id: str,
            content: str,
            role: str = "developer",
            notification_user_id: str | None = None,
            force_deep_analysis: bool = False,
            feishu_doc_id: str = "",
            project_context_line: str | None = None,
            search_branch: str | None = None,
        ) -> AsyncGenerator[AgentEvent, None]:
            await Message.objects.acreate(
                conversation_id=conversation_id,
                role=Message.Role.USER,
                content=content,
            )
            yield AgentEvent(type=TEXT_DELTA, data={"text": "部分回复"})
            await Message.objects.acreate(
                conversation_id=conversation_id,
                role=Message.Role.ASSISTANT,
                content="部分回复",
                metadata={"status": "interrupted"},
            )
            yield AgentEvent(type=MESSAGE_COMPLETE, data={"status": "interrupted"})

        with patch(
            "chat.conversation_service.ConversationService.send_message_stream",
            new=mock_interrupted_stream,
        ):
            client = AsyncClient()
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "第一条消息"},
                content_type="application/json",
            )
            await _read_streaming_body(resp)

        # Phase: 恢复场景 — mock stream 创建 completed 消息
        async def mock_resumed_stream(
            conversation_id: str,
            content: str,
            role: str = "developer",
            notification_user_id: str | None = None,
            force_deep_analysis: bool = False,
            feishu_doc_id: str = "",
            project_context_line: str | None = None,
            search_branch: str | None = None,
        ) -> AsyncGenerator[AgentEvent, None]:
            await Message.objects.acreate(
                conversation_id=conversation_id,
                role=Message.Role.USER,
                content=content,
            )
            yield AgentEvent(type=TEXT_DELTA, data={"text": "完整回复"})
            await Message.objects.acreate(
                conversation_id=conversation_id,
                role=Message.Role.ASSISTANT,
                content="完整回复",
                metadata={"status": "completed"},
            )
            yield AgentEvent(type=MESSAGE_COMPLETE, data={"status": "completed"})

        with patch(
            "chat.conversation_service.ConversationService.send_message_stream",
            new=mock_resumed_stream,
        ):
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "第二条消息"},
                content_type="application/json",
            )
            await _read_streaming_body(resp)

        # 验证 DB 中消息状态
        messages = await sync_to_async(
            lambda: list(
                Message.objects.filter(
                    conversation=conversation,
                    role=Message.Role.ASSISTANT,
                ).order_by("created_at")
            )
        )()

        assert len(messages) == 2
        assert messages[0].metadata["status"] == "interrupted"
        assert messages[0].content == "部分回复"
        assert messages[1].metadata["status"] == "completed"
        assert messages[1].content == "完整回复"

    @pytest.mark.skip(
        reason=(
            "OBSOLETE: 同 test_interrupt_active_conversation —— _active_runners 全局字典"
            "已被 OrchestrationRun + LangGraph interrupt 替代。"
        )
    )
    async def test_duplicate_interrupt_idempotent(self, conversation):
        """重复中断请求不导致异常（幂等性）（contract）。"""
        from chat.conversation_service import _active_runners  # type: ignore[attr-defined]

        mock_runner = AsyncMock()
        mock_runner.interrupt = AsyncMock()
        conv_id_str = str(conversation.id)
        _active_runners[conv_id_str] = mock_runner

        try:
            client = AsyncClient()

            # 第一次中断
            resp1 = await client.post(
                f"/api/chat/conversations/{conversation.id}/interrupt/",
            )
            assert resp1.status_code == 200

            # 第二次中断（runner 仍在 _active_runners 中）
            resp2 = await client.post(
                f"/api/chat/conversations/{conversation.id}/interrupt/",
            )
            assert resp2.status_code == 200

            # 两次均成功调用 interrupt()，无异常
            assert mock_runner.interrupt.await_count == 2
        finally:
            _active_runners.pop(conv_id_str, None)


# ============================================================================
# Test 4: 历史记录加载
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestHistoryLoading:
    """历史记录加载端到端测试。"""

    async def test_load_conversation_with_messages(self, conversation):
        """GET 对话详情返回完整消息列表。"""
        # 手动创建消息记录
        await Message.objects.acreate(
            conversation=conversation,
            role=Message.Role.USER,
            content="你好，这是测试消息",
        )
        await Message.objects.acreate(
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            content="你好！我是 AI 助手。",
        )

        client = AsyncClient()
        resp = await client.get(
            f"/api/chat/conversations/{conversation.id}/",
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "你好，这是测试消息"
        assert data["messages"][1]["role"] == "assistant"
        assert data["messages"][1]["content"] == "你好！我是 AI 助手。"


# ============================================================================
# Test 5: 对话持久化验证
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestMessagePersistence:
    """对话持久化端到端测试（contract）。"""

    async def test_message_persistence_after_stream(self, conversation):
        """SSE 流结束后 user + assistant Message 记录正确持久化。

        mock send_message_stream 内部手动创建 Message 记录，
        模拟真实 service 的持久化行为，验证流结束后 DB 中有完整消息。
        """

        async def mock_stream_with_persistence(
            conversation_id: str,
            content: str,
            role: str = "developer",
            notification_user_id: str | None = None,
            force_deep_analysis: bool = False,
            feishu_doc_id: str = "",
            project_context_line: str | None = None,
            search_branch: str | None = None,
        ) -> AsyncGenerator[AgentEvent, None]:
            # 保存 user message（模拟真实 service 行为）
            await Message.objects.acreate(
                conversation_id=conversation_id,
                role=Message.Role.USER,
                content=content,
            )
            yield AgentEvent(type=TEXT_DELTA, data={"text": "AI 回复内容"})
            # 保存 assistant message（模拟真实 service 行为）
            await Message.objects.acreate(
                conversation_id=conversation_id,
                role=Message.Role.ASSISTANT,
                content="AI 回复内容",
            )
            yield AgentEvent(
                type=MESSAGE_COMPLETE,
                data={
                    "status": "completed",
                    "final_answer": "AI 回复内容",
                    "session_id": "sess_001",
                },
            )

        with patch(
            "chat.conversation_service.ConversationService.send_message_stream",
            new=mock_stream_with_persistence,
        ):
            client = AsyncClient()
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "你好"},
                content_type="application/json",
            )
            # 必须在 patch 上下文内消费 streaming 响应
            body = await _read_streaming_body(resp)

        # 验证 SSE 响应包含预期事件
        payloads = _parse_sse_data_lines(body)
        assert any(p.get("type") == "message_complete" for p in payloads)

        # 验证 DB 持久化：应有 user + assistant 两条消息
        from asgiref.sync import sync_to_async

        messages = await sync_to_async(
            lambda: list(
                Message.objects.filter(conversation=conversation).order_by(
                    "created_at"
                )
            )
        )()

        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "你好"
        assert messages[1].role == "assistant"
        assert messages[1].content == "AI 回复内容"

    async def test_conversation_list_returns_conversations(self, test_project):
        """GET /api/chat/conversations/ 返回已创建的对话列表。"""
        # 创建 2 个对话
        await Conversation.objects.acreate(
            space=test_project, title="对话 A"
        )
        await Conversation.objects.acreate(
            space=test_project, title="对话 B"
        )

        client = AsyncClient()
        resp = await client.get("/api/chat/conversations/")

        assert resp.status_code == 200
        data = resp.json()
        titles = [c["title"] for c in data]
        assert "对话 A" in titles
        assert "对话 B" in titles


# ============================================================================
# Test 6: 错误处理验证
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestErrorHandling:
    """错误处理端到端测试（contract）。"""

    async def test_stream_error_event(self, conversation):
        """SSE 流中包含 error 事件时格式正确。"""
        from agents.core.events import ERROR as ERROR_TYPE

        mock_events = [
            AgentEvent(
                type=ERROR_TYPE,
                data={"message": "Provider error", "code": "llm_error"},
            ),
            AgentEvent(
                type=MESSAGE_COMPLETE,
                data={"status": "error"},
            ),
        ]

        with patch(
            "chat.conversation_service.ConversationService.send_message_stream",
            new=_make_mock_stream(mock_events),
        ):
            client = AsyncClient()
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "触发错误"},
                content_type="application/json",
            )
            body = await _read_streaming_body(resp)

        assert resp["Content-Type"] == "text/event-stream"
        payloads = _parse_sse_data_lines(body)
        error_events = [p for p in payloads if p.get("type") == "error"]
        assert len(error_events) >= 1
        assert error_events[0]["message"] == "Provider error"
        assert error_events[0]["code"] == "llm_error"

    async def test_stream_service_exception_returns_error(self, conversation):
        """send_message_stream 抛异常时返回 SSE error 事件而非 500。

        views.py _stream_events 捕获 Exception 并 yield error 事件，
        因此响应仍是 200 text/event-stream，包含错误信息。
        """

        async def mock_raise_exception(
            conversation_id: str,
            content: str,
            role: str = "developer",
        ) -> AsyncGenerator[AgentEvent, None]:
            raise Exception("LLM service unavailable")
            # 使其成为 async generator（unreachable yield）
            yield AgentEvent(type=TEXT_DELTA, data={})  # type: ignore[unreachable]

        with patch(
            "chat.conversation_service.ConversationService.send_message_stream",
            new=mock_raise_exception,
        ):
            client = AsyncClient()
            resp = await client.post(
                f"/api/chat/conversations/{conversation.id}/stream/",
                data={"content": "触发异常"},
                content_type="application/json",
            )
            body = await _read_streaming_body(resp)

        # 响应是 200 text/event-stream（异常在 generator 内被捕获）
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/event-stream"
        payloads = _parse_sse_data_lines(body)
        error_events = [p for p in payloads if p.get("type") == "error"]
        assert len(error_events) >= 1
        assert "服务内部错误" in error_events[0]["message"]

    async def test_stream_nonexistent_conversation_returns_404(self):
        """POST 不存在的对话 ID 返回 404。"""
        client = AsyncClient()
        resp = await client.post(
            "/api/chat/conversations/00000000-0000-0000-0000-000000000000/stream/",
            data={"content": "你好"},
            content_type="application/json",
        )

        assert resp.status_code == 404
