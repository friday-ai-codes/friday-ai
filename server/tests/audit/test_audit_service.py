"""AuditService.emit / aemit 字段持久化测试（AUDIT-01 / AUDIT-02，SC-1 / SC-3）。

覆盖 sync emit 全字段落库 / actor=None / async aemit 双面一致 / occurred_at 默认填充。
"""

import uuid

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from audit.models import AuditEvent
from audit.services.audit_service import AuditService


def _make_user(username: str = "alice", *, is_superuser: bool = False):
    return get_user_model().objects.create_user(
        username=username, password="x", is_superuser=is_superuser
    )


@pytest.mark.django_db
def test_emit_persists_all_fields():
    """sync emit 全字段逐项落库正确。"""
    user = _make_user("alice")
    target_uuid = uuid.uuid4()
    AuditService.emit(
        action="member.created",
        actor=user,
        target_type="user",
        target_id=target_uuid,
        target_repr="用户 alice",
        before={"a": 1},
        after={"a": 2},
        source="web",
        metadata={"ip": "127.0.0.1"},
    )
    event = AuditEvent.objects.get(action="member.created")
    assert event.actor_id == user.id
    assert "alice" in event.actor_repr
    assert event.target_type == "user"
    assert event.target_id == str(target_uuid)
    assert event.target_repr == "用户 alice"
    assert event.before == {"a": 1}
    assert event.after == {"a": 2}
    assert event.source == "web"
    assert event.metadata == {"ip": "127.0.0.1"}
    assert event.occurred_at is not None
    assert event.recorded_at is not None


@pytest.mark.django_db
def test_emit_actor_none():
    """actor=None → actor_id is None、actor_repr 空串（系统/匿名 actor）。"""
    AuditService.emit(action="purge.started", actor=None)
    event = AuditEvent.objects.get(action="purge.started")
    assert event.actor_id is None
    assert event.actor_repr == ""


@pytest.mark.django_db
def test_emit_superuser_repr():
    """superuser actor 的 actor_repr 追加 (superuser) 标记。"""
    user = _make_user("root", is_superuser=True)
    AuditService.emit(action="role.changed", actor=user)
    event = AuditEvent.objects.get(action="role.changed")
    assert "root" in event.actor_repr
    assert "(superuser)" in event.actor_repr


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_aemit_persists():
    """async aemit 落一行且字段一致（sync_to_async 桥接 ORM）。"""
    await AuditService.aemit(action="credential.updated", source="api")
    event = await sync_to_async(AuditEvent.objects.get)(action="credential.updated")
    assert event.source == "api"
    assert event.actor_id is None


@pytest.mark.django_db
def test_emit_default_occurred_at():
    """不传 occurred_at → 自动填 now（非 None）。"""
    AuditService.emit(action="pat.created")
    event = AuditEvent.objects.get(action="pat.created")
    assert event.occurred_at is not None


@pytest.mark.django_db
def test_emit_target_id_none_stored_as_empty():
    """LOW-1：显式 target_id=None 落空串，而非字面量 "None"。"""
    AuditService.emit(action="purge.started", target_id=None)
    event = AuditEvent.objects.get(action="purge.started")
    assert event.target_id == ""


@pytest.mark.django_db
def test_emit_preserves_empty_collection_payload():
    """LOW-3：after=[] 等假值但有语义的入参被保留（不被吞成 {}）。"""
    AuditService.emit(action="member.created", before=[], after=[], metadata=[])
    event = AuditEvent.objects.get(action="member.created")
    assert event.before == []
    assert event.after == []
    assert event.metadata == []
