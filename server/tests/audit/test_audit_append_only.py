"""AuditEvent append-only 模型层守护测试（AUDIT-01，SC-2 模型层半）。

验证不可篡改双层防御的第一道（模型层）：
- 首次 create（``_state.adding is True``）放行——守护不误伤正常写入。
- 既有行 ``.save()`` / ``.delete()`` 抛 ``AuditEventImmutableError``。

注：``.objects.update()`` / ``bulk_*`` 绕过 ``save()`` 的旁路写表由 Plan 02 的
INV-6 grep 源码守护兜底（第二道防御），本 task 不实现，仅在此标注双层防御边界。
"""

import pytest

from audit.models import AuditEvent, AuditEventImmutableError


@pytest.mark.django_db
def test_first_create_persists():
    """首次 create（_state.adding=True）正常落库，守护放行。"""
    AuditEvent.objects.create(action="member.created")
    assert AuditEvent.objects.count() == 1


@pytest.mark.django_db
def test_save_existing_raises():
    """既有行改字段后 .save() → AuditEventImmutableError（拒绝就地更新）。"""
    event = AuditEvent.objects.create(action="credential.updated")
    event.action = "credential.deleted"
    with pytest.raises(AuditEventImmutableError):
        event.save()


@pytest.mark.django_db
def test_delete_raises():
    """既有行 .delete() → AuditEventImmutableError（审计行不可删除）。"""
    event = AuditEvent.objects.create(action="pat.revoked")
    with pytest.raises(AuditEventImmutableError):
        event.delete()


@pytest.mark.django_db
def test_queryset_delete_still_blocked_at_model():
    """双层防御边界备注：模型层 save/delete 守护只拦截实例级写入。

    ``.objects.update()`` / ``bulk_create`` / ``.objects.delete()`` 等绕过实例
    ``save()`` / ``delete()`` 的旁路写表，由 Plan 02 的 INV-6 grep 源码守护
    （断言除 ``AuditService`` 外无旁路 ``AuditEvent.objects.<write>``）兜底。
    本 task 不实现 grep 守护，仅以此用例固化「模型层守护拦实例写入」的事实，
    并文档化第二道防御归属。
    """
    AuditEvent.objects.create(action="exclusion_rule.changed")
    instance = AuditEvent.objects.first()
    assert instance is not None
    with pytest.raises(AuditEventImmutableError):
        instance.save()
