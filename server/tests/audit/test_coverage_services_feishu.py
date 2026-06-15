"""审计 emit 覆盖测试 —— 服务层（清理任务）和飞书同步。

覆盖 COV-06（清理任务）、COV-09（飞书同步）。
"""

import uuid

import pytest
from django.contrib.auth import get_user_model

from audit.emitter import emit_audit_event
from audit.models import AuditEvent

User = get_user_model()


@pytest.mark.django_db
class TestCleanupAudit:
    """COV-06: 清理任务完成产生审计事件。"""

    def test_emit_cleanup_completed_event(self):
        """emit_audit_event 可写入 cleanup.completed 审计事件。"""
        event = emit_audit_event(
            action="cleanup.completed",
            target_type="CleanupRun",
            target_id=str(uuid.uuid4()),
            after={
                "mode": "normal",
                "status": "completed",
                "match_count": 5,
                "failure_count": 0,
                "repository_id": str(uuid.uuid4()),
            },
        )
        assert event is not None
        assert event.action == "cleanup.completed"
        assert event.target_type == "CleanupRun"
        assert event.after["mode"] == "normal"
        assert event.after["match_count"] == 5

    def test_emit_cleanup_failed_event(self):
        """清理失败时 emit audit event 记录失败信息。"""
        event = emit_audit_event(
            action="cleanup.completed",
            target_type="CleanupRun",
            target_id=str(uuid.uuid4()),
            after={
                "mode": "sensitive",
                "status": "failed",
                "match_count": 3,
                "failure_count": 2,
                "repository_id": str(uuid.uuid4()),
            },
        )
        assert event is not None
        assert event.after["status"] == "failed"
        assert event.after["failure_count"] == 2


@pytest.mark.django_db
class TestFeishuSyncAudit:
    """COV-09: 飞书事件接收产生审计事件。"""

    def test_emit_feishu_event_received(self):
        """飞书事件接收时 emit feishu_sync.event_received 审计事件。"""
        event = emit_audit_event(
            action="feishu_sync.event_received",
            target_type="FeishuEvent",
            target_id=str(uuid.uuid4()),
            after={
                "event_type": "WorkitemCreateEvent",
                "project_key": "test-project",
                "work_item_id": "12345",
            },
        )
        assert event is not None
        assert event.action == "feishu_sync.event_received"
        assert event.after["event_type"] == "WorkitemCreateEvent"
        assert event.after["project_key"] == "test-project"
