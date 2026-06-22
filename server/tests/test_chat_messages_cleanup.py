"""implementation Task 01 — contract DELETE /api/chat/conversations/{id}/messages/ 端点契约。

覆盖 contract 验收项：
    - DELETE ?before_id=X 硬删 before_id 之前的消息（created_at < target.created_at）
    - Ownership 校验：user 必须有 conversation.project MEMBER+ 权限
    - 缺少 before_id 参数 → 400
    - conversation 不存在 → 404
    - 跨项目越权 → 403 + audit log

Test matrix (6 cases ):
    C: DELETE 正确路径 → 200 + deleted_count=N
    D: 404 不存在 conversation
    E: 403 跨项目越权（project_a_admin_user 删 project_b 的对话）
    F: 400 缺 before_id

额外覆盖：
    G: before_id 指向不属于 conversation 的消息 → 400
    H: ownership 校验 audit log（chat.cleanup_denied_cross_project）
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from chat.models import Conversation, Message


def _url(conv_id: str, before_id: str | None = None) -> str:
    base = f"/api/chat/conversations/{conv_id}/messages/"
    if before_id is not None:
        return f"{base}?before_id={before_id}"
    return base


def _make_messages(conversation: Conversation, count: int) -> list[Message]:
    """创建 N 条消息，按 created_at 升序（依赖 Django auto_now_add）。"""
    msgs: list[Message] = []
    for i in range(count):
        msgs.append(
            Message.objects.create(
                conversation=conversation,
                role="user" if i % 2 == 0 else "assistant",
                content=f"message-{i}",
            )
        )
    return msgs


# ============================================================================
# Test C — DELETE 正确路径：硬删 before_id 之前消息 + 返回 deleted_count
# ============================================================================


@pytest.mark.django_db
def test_delete_before_id_removes_older_messages_and_returns_count(
    project_a,
    project_a_admin_user,
) -> None:
    """Behavior C：5 条消息 + before_id=第 4 条 → 删前 3 条，返回 deleted_count=3。"""
    conv = Conversation.objects.create(
        project=project_a, title="cleanup-test", created_by=project_a_admin_user
    )
    msgs = _make_messages(conv, count=5)
    before_msg = msgs[3]  # 删除 < msgs[3].created_at 即前 3 条

    client = APIClient()
    client.force_authenticate(user=project_a_admin_user)
    resp = client.delete(_url(str(conv.id), str(before_msg.id)))

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["deleted_count"] == 3
    # 实际剩余消息 = 2（msgs[3] + msgs[4]）
    remaining = list(Message.objects.filter(conversation=conv).order_by("created_at"))
    assert len(remaining) == 2
    # 保留的必须是第 4/5 条
    assert remaining[0].id == msgs[3].id
    assert remaining[1].id == msgs[4].id


# ============================================================================
# Test D — 404 conversation 不存在
# ============================================================================


@pytest.mark.django_db
def test_delete_nonexistent_conversation_returns_404(
    project_a_admin_user,
) -> None:
    """Behavior D：conversation_id 不存在 → 404。"""
    client = APIClient()
    client.force_authenticate(user=project_a_admin_user)
    resp = client.delete(_url("00000000-0000-0000-0000-000000000000", str(uuid4())))
    assert resp.status_code == 404, resp.content


# ============================================================================
# Test E — 跨用户越权：非 owner 访问他人会话 → owner gate 统一 404
# ============================================================================


@pytest.mark.django_db
def test_delete_cross_project_conversation_returns_404(
    project_a,
    project_a_admin_user,
    project_b_admin_user,
) -> None:
    """Behavior E：owner gate（ISO-04，无 superuser/项目 bypass）先于 project 403 触发。

    会话归 project_a_admin_user；project_b_admin_user 非 owner → 越权/不存在统一 404
    （不泄漏存在性），原 403 project-permission 分支被 owner gate 覆盖。
    """
    conv = Conversation.objects.create(
        project=project_a, title="owned-by-a", created_by=project_a_admin_user
    )
    msgs = _make_messages(conv, count=3)

    client = APIClient()
    client.force_authenticate(user=project_b_admin_user)
    resp = client.delete(_url(str(conv.id), str(msgs[1].id)))

    assert resp.status_code == 404, resp.content
    # 消息未被删除
    assert Message.objects.filter(conversation=conv).count() == 3


# ============================================================================
# Test F — 400 缺 before_id 参数
# ============================================================================


@pytest.mark.django_db
def test_delete_without_before_id_returns_400(
    project_a,
    project_a_admin_user,
) -> None:
    """Behavior F：缺 ?before_id= → 400。"""
    conv = Conversation.objects.create(project=project_a, title="no-param")
    _make_messages(conv, count=2)

    client = APIClient()
    client.force_authenticate(user=project_a_admin_user)
    resp = client.delete(_url(str(conv.id)))  # 不带 before_id
    assert resp.status_code == 400, resp.content
    body = resp.json()
    assert "before_id" in str(body)


# ============================================================================
# Test G — before_id 指向不属于 conversation 的消息 → 400
# ============================================================================


@pytest.mark.django_db
def test_delete_before_id_not_in_conversation_returns_400(
    project_a,
    project_a_admin_user,
) -> None:
    """Behavior G：before_id 指向其他对话的消息 → 400（防跨 conversation）。"""
    conv_a = Conversation.objects.create(
        project=project_a, title="conv-a", created_by=project_a_admin_user
    )
    _make_messages(conv_a, count=2)

    conv_b = Conversation.objects.create(
        project=project_a, title="conv-b", created_by=project_a_admin_user
    )
    conv_b_msgs = _make_messages(conv_b, count=2)

    client = APIClient()
    client.force_authenticate(user=project_a_admin_user)
    # 试图用 conv_b 的 msg id 删 conv_a 的消息
    resp = client.delete(_url(str(conv_a.id), str(conv_b_msgs[0].id)))

    assert resp.status_code == 400, resp.content
    # conv_a 的消息没被删
    assert Message.objects.filter(conversation=conv_a).count() == 2


# ============================================================================
# Test H — superuser 可以删除任何项目的对话消息
# ============================================================================


@pytest.mark.django_db
def test_delete_by_superuser_succeeds_cross_project(
    project_a,
    system_admin_user,
) -> None:
    """Behavior H：superuser 删除自己在 project_a（其非成员）下创建的会话 → 200。

    owner gate（ISO-03/04）无 superuser bypass：superuser 仅当为会话 owner 时通过；
    通过后 project ownership 校验对 superuser 豁免，故跨项目（非成员）仍可删。
    """
    conv = Conversation.objects.create(
        project=project_a, title="sys-del", created_by=system_admin_user
    )
    msgs = _make_messages(conv, count=3)

    client = APIClient()
    client.force_authenticate(user=system_admin_user)
    resp = client.delete(_url(str(conv.id), str(msgs[2].id)))
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["deleted_count"] == 2
