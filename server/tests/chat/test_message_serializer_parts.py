"""parts contract：MessageSerializer 暴露 parts + finalize 落库强同源。

测试矩阵（contract 测试要求 3 条）：
1. test_serializer_exposes_parts_field
2. test_persist_message_keeps_content_and_parts_in_sync
3. test_persist_legacy_path_when_collector_empty_falls_back_to_content_only
"""

from __future__ import annotations

import uuid

import pytest

from chat.finalize import finalize_conversation
from chat.models import Conversation, Message
from chat.serializers import ConversationMessageSerializer


@pytest.mark.django_db
def test_serializer_exposes_parts_field() -> None:
    from projects.models import Space

    project = Space.objects.create(name="p")
    conv = Conversation.objects.create(space=project, title="t")
    msg = Message.objects.create(
        conversation=conv,
        role=Message.Role.ASSISTANT,
        content="hi",
        parts=[
            {"type": "text", "id": "p1", "index": 0, "text": "hi", "state": "done"},
        ],
    )

    data = ConversationMessageSerializer(msg).data
    assert "parts" in data
    assert isinstance(data["parts"], list)
    assert data["parts"][0]["type"] == "text"
    assert data["parts"][0]["text"] == "hi"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_persist_message_keeps_content_and_parts_in_sync() -> None:
    """传入 parts 时：finalize 用 PartsCollector 派生 content + tool_calls，
    Message.parts / .content / .tool_calls 严格三同源（parts persistence contract）。"""
    from agents.models import AgentSession
    from projects.models import Space

    project = await Space.objects.acreate(name="p")
    conv = await Conversation.objects.acreate(space=project, title="t")
    agent_session = await AgentSession.objects.acreate(
        session_id=f"s-{uuid.uuid4().hex[:8]}",
        status=AgentSession.Status.RUNNING,
    )

    msg_id = uuid.uuid4()
    parts = [
        {"type": "text", "id": "p1", "index": 0, "text": "Hello ", "state": "done"},
        {
            "type": "image",
            "id": "p-img",
            "index": 1,
            "mime_type": "image/png",
            "size_bytes": 128,
            "width": None,
            "height": None,
            "detail": "auto",
            "storage_ref": "chat_images/p-img.png",
            "source_url": "",
            "alt_text": "截图",
        },
        {
            "type": "tool_use",
            "id": "p2",
            "index": 2,
            "tool_call_id": "tc-1",
            "name": "search",
            "input": {"q": "x"},
            "status": "done",
            "result": "found",
            "batch_id": None,
        },
        {"type": "text", "id": "p3", "index": 3, "text": "world!", "state": "done"},
    ]

    # final_content 入参故意写错（"WRONG"），strict 同源应把它覆盖为
    # parts 中 text part 拼接（"Hello world!"）。
    await finalize_conversation(
        conversation=conv,
        assistant_msg_id=msg_id,
        final_content="WRONG",
        accumulated_thinking=[],
        tool_calls=[],
        result_metadata={"status": "completed"},
        agent_session=agent_session,
        session_id=agent_session.session_id,
        model="m",
        user_message="hi",
        notification_user_id=None,
        publish_title_event=False,
        parts=parts,
    )

    msg = await Message.objects.aget(id=msg_id)
    # 三同源契约
    assert msg.parts == parts
    assert msg.content == "Hello world!"
    assert msg.tool_calls is not None
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0]["id"] == "tc-1"
    assert msg.tool_calls[0]["name"] == "search"
    assert msg.tool_calls[0]["result"] == "found"
    assert msg.tool_calls[0]["status"] == "done"
    # parts_schema_version 写入 metadata
    assert msg.metadata.get("parts_schema_version") == 2
    assert msg.metadata.get("image_count") == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_persist_legacy_path_when_collector_empty_falls_back_to_content_only() -> None:
    """parts=None / [] 时（如 deep_analysis BarrierManager 回灌路径）：
    legacy 兼容 —— 仍按入参 final_content + tool_calls 写库，不报错。"""
    from agents.models import AgentSession
    from projects.models import Space

    project = await Space.objects.acreate(name="p")
    conv = await Conversation.objects.acreate(space=project, title="t")
    agent_session = await AgentSession.objects.acreate(
        session_id=f"s-{uuid.uuid4().hex[:8]}",
        status=AgentSession.Status.RUNNING,
    )

    msg_id = uuid.uuid4()
    legacy_tool_calls = [
        {"id": "tc-legacy", "name": "deep_analysis", "input": {}, "result": "deep result"},
    ]

    await finalize_conversation(
        conversation=conv,
        assistant_msg_id=msg_id,
        final_content="legacy content",
        accumulated_thinking=[],
        tool_calls=legacy_tool_calls,
        result_metadata={"status": "completed"},
        agent_session=agent_session,
        session_id=agent_session.session_id,
        model="m",
        user_message="hi",
        notification_user_id=None,
        publish_title_event=False,
        parts=None,
    )

    msg = await Message.objects.aget(id=msg_id)
    # legacy 入参原样落库
    assert msg.content == "legacy content"
    assert msg.tool_calls == legacy_tool_calls
    # parts 字段是 default []（hydrate adapter 在前端合成）
    assert msg.parts == []
    # parts_schema_version 仍写入 metadata（schema versioning 前向兼容）
    assert msg.metadata.get("parts_schema_version") == 1
