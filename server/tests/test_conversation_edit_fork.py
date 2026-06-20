from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status

from chat.models import Conversation, Message
from projects.models import Project


@pytest.fixture
def project(db):
    return Project.objects.create(name="Fork Project", description="edit fork tests")


@pytest.fixture
def source_conversation(db, project):
    return Conversation.objects.create(
        project=project,
        title="原始对话",
        model="claude-test",
    )


def _message(
    conversation: Conversation,
    role: str,
    content: str,
    offset_seconds: int,
    **overrides,
) -> Message:
    message = Message.objects.create(
        conversation=conversation,
        role=role,
        content=content,
        **overrides,
    )
    Message.objects.filter(id=message.id).update(
        created_at=timezone.now() + timedelta(seconds=offset_seconds),
    )
    message.refresh_from_db()
    return message


@pytest.mark.django_db(transaction=True)
def test_fork_user_message_copies_only_prior_history(api_client, source_conversation):
    first_user = _message(
        source_conversation,
        Message.Role.USER,
        "第一问",
        1,
        metadata={"source": "seed"},
        parts=[{"type": "text", "id": "p1", "index": 0, "text": "第一问", "state": "done"}],
    )
    assistant = _message(
        source_conversation,
        Message.Role.ASSISTANT,
        "第一答",
        2,
        tool_calls=[{"id": "call_1", "name": "search", "input": {"q": "x"}}],
        tool_call_id="call_1",
        metadata={"thinking": "ok"},
        parts=[{"type": "text", "id": "p2", "index": 0, "text": "第一答", "state": "done"}],
    )
    target = _message(source_conversation, Message.Role.USER, "第二问", 3)
    later = _message(source_conversation, Message.Role.ASSISTANT, "第二答", 4)

    response = api_client.post(
        f"/api/chat/conversations/{source_conversation.id}/messages/{target.id}/fork/",
        {"content": "  编辑后的第二问  "},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["id"] != str(source_conversation.id)
    assert response.data["space_id"] == str(source_conversation.project_id)
    assert response.data["model"] == "claude-test"
    assert response.data["title"] == "原始对话"
    assert [m["content"] for m in response.data["messages"]] == ["第一问", "第一答"]

    forked = Conversation.objects.get(id=response.data["id"])
    assert forked.project_id == source_conversation.project_id
    assert forked.model == source_conversation.model

    forked_messages = list(Message.objects.filter(conversation=forked).order_by("created_at"))
    assert len(forked_messages) == 2
    assert forked_messages[0].id != first_user.id
    assert forked_messages[0].role == first_user.role
    assert forked_messages[0].content == first_user.content
    assert forked_messages[0].metadata == first_user.metadata
    assert forked_messages[0].parts == first_user.parts
    assert forked_messages[1].id != assistant.id
    assert forked_messages[1].tool_calls == assistant.tool_calls
    assert forked_messages[1].tool_call_id == assistant.tool_call_id

    assert list(
        Message.objects.filter(conversation=source_conversation)
        .order_by("created_at")
        .values_list("id", flat=True)
    ) == [first_user.id, assistant.id, target.id, later.id]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("role", [Message.Role.ASSISTANT, Message.Role.TOOL, Message.Role.SYSTEM])
def test_fork_rejects_non_user_target(api_client, source_conversation, role):
    target = _message(source_conversation, role, "不能作为编辑目标", 1)

    response = api_client.post(
        f"/api/chat/conversations/{source_conversation.id}/messages/{target.id}/fork/",
        {"content": "新内容"},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert Conversation.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_fork_rejects_empty_content(api_client, source_conversation):
    target = _message(source_conversation, Message.Role.USER, "旧内容", 1)

    response = api_client.post(
        f"/api/chat/conversations/{source_conversation.id}/messages/{target.id}/fork/",
        {"content": "   "},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert Conversation.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_fork_rejects_cross_conversation_message(api_client, source_conversation, project):
    other = Conversation.objects.create(project=project, title="另一个对话")
    target = _message(other, Message.Role.USER, "其他对话消息", 1)

    response = api_client.post(
        f"/api/chat/conversations/{source_conversation.id}/messages/{target.id}/fork/",
        {"content": "新内容"},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert Conversation.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_fork_deleted_or_missing_conversation_returns_404(api_client, source_conversation):
    target = _message(source_conversation, Message.Role.USER, "旧内容", 1)
    source_conversation.is_deleted = True
    source_conversation.save(update_fields=["is_deleted"])

    response = api_client.post(
        f"/api/chat/conversations/{source_conversation.id}/messages/{target.id}/fork/",
        {"content": "新内容"},
        format="json",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert Conversation.objects.filter(is_deleted=False).count() == 0
