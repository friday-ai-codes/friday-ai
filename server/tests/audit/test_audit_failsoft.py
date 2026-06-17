"""AuditService fail-soft + 入口强制脱敏测试（AUDIT-02，SC-3 / SC-4）。

覆盖 emit 吞异常不冒泡 + audit.emit_failed warning / 主操作不受影响 /
async aemit fail-soft / 入口强制脱敏（DB 无明文终极防线）。
"""

import json

import pytest
from structlog.testing import capture_logs

from audit.models import AuditEvent
from audit.services.audit_service import AuditService


@pytest.mark.django_db
def test_emit_swallows_exception(monkeypatch):
    """create 抛异常 → emit 返回 None 不冒泡，记 audit.emit_failed warning。"""

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(AuditEvent.objects, "create", _boom)
    with capture_logs() as cap:
        result = AuditService.emit(action="member.created", target_type="user")
    assert result is None
    warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
    assert "audit.emit_failed" in warnings


@pytest.mark.django_db
def test_main_op_not_blocked(monkeypatch):
    """主操作 + emit 失败：emit 失败绝不影响主操作返回值。"""

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(AuditEvent.objects, "create", _boom)

    def main_op() -> str:
        result = "computed"
        AuditService.emit(action="credential.deleted", after={"x": 1})
        return result

    assert main_op() == "computed"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_aemit_failsoft(monkeypatch):
    """create 抛异常 → await aemit 不冒泡。"""

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(AuditEvent.objects, "create", _boom)
    # 不应 raise
    await AuditService.aemit(action="pat.revoked")


@pytest.mark.django_db
def test_redaction_enforced_at_entry():
    """入口强制脱敏：调用方传明文 → 落库脱敏，DB 整行 JSON 无明文。"""
    AuditService.emit(
        action="credential.updated",
        before={"access_token": "PLAINTEXT_SECRET_VALUE"},
    )
    event = AuditEvent.objects.get(action="credential.updated")
    assert event.before["access_token"] == "[已脱敏]"
    serialized = json.dumps(
        {"before": event.before, "after": event.after, "metadata": event.metadata},
        default=str,
    )
    assert "PLAINTEXT_SECRET_VALUE" not in serialized
