"""会话内切换空间 — service + PATCH 接口行为。

覆盖：
- switch_space 成功：更新 project + 落库 role=system 的 space_switch 标记消息
- 切到相同空间：no-op，不落库
- 目标空间不存在：ValueError / PATCH 400
- 切回 null（通用对话）
- PATCH space_id：completed（frozen）态允许（与 title 同等待遇）；running 态 400
"""

from __future__ import annotations

import pytest
from asgiref.sync import async_to_sync
from rest_framework import status

from chat.conversation_service import ConversationService
from chat.models import Conversation, Message
from projects.models import Space


@pytest.fixture
def space_a(db):
    return Space.objects.create(name="空间A", description="space switch tests")


@pytest.fixture
def space_b(db):
    return Space.objects.create(name="空间B", description="space switch tests")


@pytest.fixture
def conversation(db, space_a):
    return Conversation.objects.create(
        space=space_a,
        title="切换空间测试",
        model="claude-test",
    )


def _url(conv_id) -> str:
    return f"/api/chat/conversations/{conv_id}/"


# ============================================================================
# Service 层
# ============================================================================


@pytest.mark.django_db(transaction=True)
def test_switch_space_updates_project_and_records_marker(conversation, space_a, space_b):
    message = async_to_sync(ConversationService.switch_space)(conversation, str(space_b.id))

    conversation.refresh_from_db()
    assert conversation.space_id == space_b.id

    assert message is not None
    assert message.role == Message.Role.SYSTEM
    assert "空间B" in message.content
    assert message.metadata["type"] == "space_switch"
    assert message.metadata["from_space_id"] == str(space_a.id)
    assert message.metadata["from_space_name"] == "空间A"
    assert message.metadata["to_space_id"] == str(space_b.id)
    assert message.metadata["to_space_name"] == "空间B"


@pytest.mark.django_db(transaction=True)
def test_switch_space_same_space_is_noop(conversation, space_a):
    message = async_to_sync(ConversationService.switch_space)(conversation, str(space_a.id))

    assert message is None
    assert Message.objects.filter(conversation=conversation).count() == 0
    conversation.refresh_from_db()
    assert conversation.space_id == space_a.id


@pytest.mark.django_db(transaction=True)
def test_switch_space_to_none_unbinds(conversation):
    message = async_to_sync(ConversationService.switch_space)(conversation, None)

    conversation.refresh_from_db()
    assert conversation.space_id is None
    assert message is not None
    assert message.metadata["to_space_id"] is None
    assert "通用对话" in message.content


@pytest.mark.django_db(transaction=True)
def test_switch_space_nonexistent_raises(conversation):
    with pytest.raises(ValueError, match="空间不存在"):
        async_to_sync(ConversationService.switch_space)(
            conversation, "00000000-0000-0000-0000-000000000000"
        )
    conversation.refresh_from_db()
    assert conversation.space_id is not None


# ============================================================================
# PATCH 接口
# ============================================================================


@pytest.mark.django_db(transaction=True)
def test_patch_space_id_switches_and_returns_new_space(api_client, conversation, space_b):
    resp = api_client.patch(
        _url(conversation.id),
        data={"space_id": str(space_b.id)},
        format="json",
    )

    assert resp.status_code == status.HTTP_200_OK, resp.content
    assert resp.data["space_id"] == str(space_b.id)
    conversation.refresh_from_db()
    assert conversation.space_id == space_b.id
    marker = Message.objects.get(conversation=conversation, role=Message.Role.SYSTEM)
    assert marker.metadata["type"] == "space_switch"


@pytest.mark.django_db(transaction=True)
def test_patch_space_id_allowed_on_frozen_conversation(api_client, conversation, space_b):
    """frozen（completed）只挡 provider/model；space_id 与 title 同等待遇。"""
    Conversation.objects.filter(id=conversation.id).update(status="completed")

    resp = api_client.patch(
        _url(conversation.id),
        data={"space_id": str(space_b.id)},
        format="json",
    )

    assert resp.status_code == status.HTTP_200_OK, resp.content
    conversation.refresh_from_db()
    assert conversation.space_id == space_b.id


@pytest.mark.django_db(transaction=True)
def test_patch_space_id_rejected_while_running(api_client, conversation, space_b):
    Conversation.objects.filter(id=conversation.id).update(status="running")

    resp = api_client.patch(
        _url(conversation.id),
        data={"space_id": str(space_b.id)},
        format="json",
    )

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert resp.data["code"] == "conversation_running"
    conversation.refresh_from_db()
    assert conversation.space_id != space_b.id


@pytest.mark.django_db(transaction=True)
def test_patch_space_id_nonexistent_returns_400(api_client, conversation):
    resp = api_client.patch(
        _url(conversation.id),
        data={"space_id": "00000000-0000-0000-0000-000000000000"},
        format="json",
    )

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert "空间不存在" in resp.data["error"]


@pytest.mark.django_db(transaction=True)
def test_patch_space_id_null_unbinds(api_client, conversation):
    resp = api_client.patch(
        _url(conversation.id),
        data={"space_id": None},
        format="json",
    )

    assert resp.status_code == status.HTTP_200_OK, resp.content
    assert resp.data["space_id"] is None
    conversation.refresh_from_db()
    assert conversation.space_id is None
