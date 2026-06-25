"""chat.finalize.finalize_conversation 单元测试。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from agents.core.events import TITLE_GENERATED
from agents.models import AgentSession
from chat.models import Conversation, Message


@pytest.mark.django_db(transaction=True)
class TestFinalizeConversation:
    """finalize_conversation() 收尾逻辑测试。"""

    @pytest.fixture
    async def setup_data(self, project):
        conversation = await Conversation.objects.acreate(
            space=project,
            title="test conv",
            model="claude-sonnet-4-5",
        )
        session_id = f"chat-{conversation.id}-abc12345"
        agent_session = await AgentSession.objects.acreate(
            session_id=session_id,
            space=project,
            status=AgentSession.Status.RUNNING,
            metadata={"conversation_id": str(conversation.id)},
        )
        return conversation, agent_session, session_id

    async def test_creates_assistant_message(self, setup_data):
        from chat.finalize import finalize_conversation

        conversation, agent_session, session_id = setup_data
        msg_id = uuid.uuid4()

        with (
            patch("chat.title_service.should_generate_title", new=AsyncMock(return_value=False)),
            patch("chat.title_service.generate_title", new=AsyncMock(return_value=None)),
        ):
            await finalize_conversation(
                conversation=conversation,
                assistant_msg_id=msg_id,
                final_content="Hello from AI",
                accumulated_thinking=["thinking step 1"],
                tool_calls=[{"id": "tc1", "name": "search", "input": {}, "result": "ok", "status": "done"}],
                result_metadata={"status": "completed", "cost_usd": 0.01},
                agent_session=agent_session,
                session_id=session_id,
                model="claude-sonnet-4-5",
                user_message="Hi",
            )

        msg = await Message.objects.aget(id=msg_id)
        assert msg.role == Message.Role.ASSISTANT
        assert msg.content == "Hello from AI"
        assert msg.metadata["session_id"] == session_id
        assert msg.metadata["model"] == "claude-sonnet-4-5"
        assert msg.metadata["cost_usd"] == 0.01
        assert msg.metadata["thinking"] == "thinking step 1"
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1

    async def test_is_idempotent(self, setup_data):
        """barrier 多次 resume 时 finalize_conversation 同一 assistant_msg_id 必须能多次安全调用，
        且最后一次 final_content 落库（chat/finalize.py:88-92 显式 update 终态）。

        历史变更：早期实现"内容相同则跳过"的幂等语义已废弃；现在按"barrier 终态覆写"语义，
        因为只有 barrier 完成的最后一次调用才掌握权威 final_content。
        """
        from chat.finalize import finalize_conversation

        conversation, agent_session, session_id = setup_data
        msg_id = uuid.uuid4()

        await Message.objects.acreate(
            id=msg_id,
            conversation=conversation,
            role=Message.Role.ASSISTANT,
            content="Already saved",
        )

        with (
            patch("chat.title_service.should_generate_title", new=AsyncMock(return_value=False)),
            patch("chat.title_service.generate_title", new=AsyncMock(return_value=None)),
        ):
            # 多次调用不应抛异常（幂等：同一 msg_id 反复 finalize 不会创建重复消息）
            for _ in range(3):
                await finalize_conversation(
                    conversation=conversation,
                    assistant_msg_id=msg_id,
                    final_content="Different content",
                    accumulated_thinking=[],
                    tool_calls=[],
                    result_metadata={"status": "completed"},
                    agent_session=agent_session,
                    session_id=session_id,
                    model="claude-sonnet-4-5",
                    user_message="Hi",
                )

        # 同一 msg_id 在 DB 中始终只有一行（无重复 INSERT）
        count = await Message.objects.filter(id=msg_id).acount()
        assert count == 1

        msg = await Message.objects.aget(id=msg_id)
        assert msg.content == "Different content"

    async def test_updates_agent_session_status(self, setup_data):
        from chat.finalize import finalize_conversation

        conversation, agent_session, session_id = setup_data
        msg_id = uuid.uuid4()

        with (
            patch("chat.title_service.should_generate_title", new=AsyncMock(return_value=False)),
            patch("chat.title_service.generate_title", new=AsyncMock(return_value=None)),
        ):
            await finalize_conversation(
                conversation=conversation,
                assistant_msg_id=msg_id,
                final_content="Done",
                accumulated_thinking=[],
                tool_calls=[],
                result_metadata={"status": "completed"},
                agent_session=agent_session,
                session_id=session_id,
                model="claude-sonnet-4-5",
                user_message="Hi",
            )

        await agent_session.arefresh_from_db()
        assert agent_session.status == AgentSession.Status.COMPLETED

    async def test_interrupted_status_maps_to_suspended(self, setup_data):
        from chat.finalize import finalize_conversation

        conversation, agent_session, session_id = setup_data
        msg_id = uuid.uuid4()

        with (
            patch("chat.title_service.should_generate_title", new=AsyncMock(return_value=False)),
            patch("chat.title_service.generate_title", new=AsyncMock(return_value=None)),
        ):
            await finalize_conversation(
                conversation=conversation,
                assistant_msg_id=msg_id,
                final_content="Interrupted",
                accumulated_thinking=[],
                tool_calls=[],
                result_metadata={"status": "interrupted"},
                agent_session=agent_session,
                session_id=session_id,
                model="claude-sonnet-4-5",
                user_message="Hi",
            )

        await agent_session.arefresh_from_db()
        assert agent_session.status == AgentSession.Status.SUSPENDED

    async def test_generates_title_and_returns_event(self, setup_data):
        from chat.finalize import finalize_conversation

        conversation, agent_session, session_id = setup_data
        msg_id = uuid.uuid4()

        with (
            patch("chat.title_service.should_generate_title", new=AsyncMock(return_value=True)),
            patch("chat.title_service.generate_title", new=AsyncMock(return_value="Generated Title")),
        ):
            events = await finalize_conversation(
                conversation=conversation,
                assistant_msg_id=msg_id,
                final_content="Response",
                accumulated_thinking=[],
                tool_calls=[],
                result_metadata={"status": "completed"},
                agent_session=agent_session,
                session_id=session_id,
                model="claude-sonnet-4-5",
                user_message="Hi",
                publish_title_event=True,
            )

        assert len(events) == 1
        assert events[0].type == TITLE_GENERATED
        assert events[0].data["title"] == "Generated Title"

    async def test_persists_deep_analysis_sessions(self, setup_data):
        """完成态把本消息引用到的深度分析子会话日志按会话落库（历史可还原）。"""
        from chat.finalize import finalize_conversation
        from subagent.models import SubAgentSession

        conversation, agent_session, session_id = setup_data
        msg_id = uuid.uuid4()

        deep_logs = [
            {"type": "tool_call", "content": "Read({\"file_path\": \"x.py\"})", "ts": 1},
            {"type": "result", "content": "cost=$0.02", "ts": 2},
        ]
        await SubAgentSession.objects.acreate(
            session_id="deep-abc123def456",
            main_session=agent_session,
            task_type=SubAgentSession.TaskType.EXPLORE,
            status=SubAgentSession.Status.COMPLETED,
            last_output={
                "source": "chat_deep_analysis",
                "task_description": "分析入口",
                "logs": deep_logs,
            },
        )

        with (
            patch("chat.title_service.should_generate_title", new=AsyncMock(return_value=False)),
            patch("chat.title_service.generate_title", new=AsyncMock(return_value=None)),
        ):
            await finalize_conversation(
                conversation=conversation,
                assistant_msg_id=msg_id,
                final_content="分析完成",
                accumulated_thinking=[],
                tool_calls=[
                    {
                        "id": "tc1",
                        "name": "mcp__chat-tools__deep_analysis",
                        "input": {"task_description": "分析入口"},
                        "result": "{\"data\": {\"session_id\": \"deep-abc123def456\"}}",
                        "status": "done",
                    }
                ],
                result_metadata={"status": "completed"},
                agent_session=agent_session,
                session_id=session_id,
                model="claude-sonnet-4-5",
                user_message="分析一下",
            )

        msg = await Message.objects.aget(id=msg_id)
        sessions = msg.metadata.get("deep_analysis_sessions")
        assert sessions is not None
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "deep-abc123def456"
        assert sessions[0]["task_description"] == "分析入口"
        assert len(sessions[0]["logs"]) == 2

    async def test_persists_doc_summary(self, setup_data):
        """飞书文档摘要落库到 metadata.docSummary（刷新回显文档摘要卡）。"""
        from chat.finalize import finalize_conversation

        conversation, agent_session, session_id = setup_data
        msg_id = uuid.uuid4()
        doc_summary = {
            "type": "summary",
            "title": "产品需求文档",
            "wordCount": 1024,
            "preview": "本文档介绍...",
            "truncated": False,
            "truncatedLength": 1024,
        }

        with (
            patch("chat.title_service.should_generate_title", new=AsyncMock(return_value=False)),
            patch("chat.title_service.generate_title", new=AsyncMock(return_value=None)),
        ):
            await finalize_conversation(
                conversation=conversation,
                assistant_msg_id=msg_id,
                final_content="已读取文档",
                accumulated_thinking=[],
                tool_calls=[],
                result_metadata={"status": "completed"},
                agent_session=agent_session,
                session_id=session_id,
                model="claude-sonnet-4-5",
                user_message="读一下这个文档",
                doc_summary=doc_summary,
            )

        msg = await Message.objects.aget(id=msg_id)
        assert msg.metadata.get("docSummary") == doc_summary

    async def test_persists_degraded_flag(self, setup_data):
        """降级回答标记落库到 metadata.degraded（刷新回显降级提示）。"""
        from chat.finalize import finalize_conversation

        conversation, agent_session, session_id = setup_data
        msg_id = uuid.uuid4()

        with (
            patch("chat.title_service.should_generate_title", new=AsyncMock(return_value=False)),
            patch("chat.title_service.generate_title", new=AsyncMock(return_value=None)),
        ):
            await finalize_conversation(
                conversation=conversation,
                assistant_msg_id=msg_id,
                final_content="部分回答",
                accumulated_thinking=[],
                tool_calls=[],
                result_metadata={
                    "status": "completed",
                    "degraded": True,
                    "degraded_reason": "达到最大轮数",
                },
                agent_session=agent_session,
                session_id=session_id,
                model="claude-sonnet-4-5",
                user_message="Hi",
            )

        msg = await Message.objects.aget(id=msg_id)
        assert msg.metadata.get("degraded") is True
        assert msg.metadata.get("degraded_reason") == "达到最大轮数"

    async def test_no_deep_sessions_when_not_referenced(self, setup_data):
        """tool_calls / parts 中没有 deep-xxxx 引用时不挂载 deep_analysis_sessions。"""
        from chat.finalize import finalize_conversation

        conversation, agent_session, session_id = setup_data
        msg_id = uuid.uuid4()

        with (
            patch("chat.title_service.should_generate_title", new=AsyncMock(return_value=False)),
            patch("chat.title_service.generate_title", new=AsyncMock(return_value=None)),
        ):
            await finalize_conversation(
                conversation=conversation,
                assistant_msg_id=msg_id,
                final_content="普通回复",
                accumulated_thinking=[],
                tool_calls=[],
                result_metadata={"status": "completed"},
                agent_session=agent_session,
                session_id=session_id,
                model="claude-sonnet-4-5",
                user_message="Hi",
            )

        msg = await Message.objects.aget(id=msg_id)
        assert "deep_analysis_sessions" not in (msg.metadata or {})

    async def test_no_title_event_when_publish_disabled(self, setup_data):
        from chat.finalize import finalize_conversation

        conversation, agent_session, session_id = setup_data
        msg_id = uuid.uuid4()

        with (
            patch("chat.title_service.should_generate_title", new=AsyncMock(return_value=True)),
            patch("chat.title_service.generate_title", new=AsyncMock(return_value="Generated Title")),
        ):
            events = await finalize_conversation(
                conversation=conversation,
                assistant_msg_id=msg_id,
                final_content="Response",
                accumulated_thinking=[],
                tool_calls=[],
                result_metadata={"status": "completed"},
                agent_session=agent_session,
                session_id=session_id,
                model="claude-sonnet-4-5",
                user_message="Hi",
                publish_title_event=False,
            )

        assert len(events) == 0
