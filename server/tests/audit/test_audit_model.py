"""AuditEvent 模型层单测 —— append-only 守护 + 字段默认值。

覆盖 AUDIT-01 / AUDIT-04 的模型层约束：
1. 创建成功（全字段）
2. 更新已有记录抛 ValueError（append-only）
3. 删除抛 ValueError（append-only）
4. before/after JSONField 默认空 dict
5. timestamp 自动填充
6. actor FK nullable（系统事件）
"""

import pytest
from django.contrib.auth import get_user_model

from audit.models import AuditEvent

User = get_user_model()


@pytest.mark.django_db
class TestAuditEventCreate:
    """测试 AuditEvent 创建。"""

    def test_create_with_all_fields(self, db):
        """全字段创建成功。"""
        user = User.objects.create_user(username="auditor", password="testpass123")
        event = AuditEvent.objects.create(
            actor=user,
            actor_display="auditor",
            actor_type="user",
            action="user.created",
            target_type="User",
            target_id=str(user.pk),
            before={},
            after={"username": "auditor"},
            source=AuditEvent.Source.API,
            ip_address="127.0.0.1",
            user_agent="TestAgent/1.0",
        )
        assert event.pk is not None
        assert event.action == "user.created"
        assert event.target_type == "User"
        assert event.target_id == str(user.pk)
        assert event.actor == user
        assert event.after == {"username": "auditor"}

    def test_jsonfield_defaults_to_empty_dict(self, db):
        """before/after JSONField 默认为 {}。"""
        event = AuditEvent.objects.create(
            action="system.startup",
            target_type="System",
            target_id="0",
        )
        assert event.before == {}
        assert event.after == {}

    def test_timestamp_auto_set(self, db):
        """timestamp 由 auto_now_add 自动填充。"""
        event = AuditEvent.objects.create(
            action="test.event",
            target_type="Test",
            target_id="1",
        )
        assert event.timestamp is not None

    def test_actor_nullable_for_system_events(self, db):
        """系统事件 actor 为 NULL —— FK nullable 允许。"""
        event = AuditEvent.objects.create(
            actor=None,
            actor_display="",
            actor_type="system",
            action="scheduler.cleanup",
            target_type="RepoExclusionRule",
            target_id="42",
            source=AuditEvent.Source.SCHEDULER,
        )
        assert event.actor is None
        assert event.actor_type == "system"
        assert event.pk is not None


@pytest.mark.django_db
class TestAuditEventAppendOnly:
    """测试 AuditEvent append-only 守护。"""

    def test_update_existing_raises_value_error(self, db):
        """更新已有记录抛 ValueError —— append-only。"""
        event = AuditEvent.objects.create(
            action="user.created",
            target_type="User",
            target_id="1",
        )
        event_id = event.pk
        event.action = "user.modified"
        with pytest.raises(ValueError, match="append-only"):
            event.save()

        # 原记录未被修改
        original = AuditEvent.objects.get(pk=event_id)
        assert original.action == "user.created"

    def test_delete_raises_value_error(self, db):
        """删除抛 ValueError —— append-only。"""
        event = AuditEvent.objects.create(
            action="user.created",
            target_type="User",
            target_id="1",
        )
        with pytest.raises(ValueError, match="append-only"):
            event.delete()

        # 记录仍然存在
        assert AuditEvent.objects.filter(pk=event.pk).exists()
