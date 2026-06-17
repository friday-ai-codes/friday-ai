"""AuditService fail-soft + 入口强制脱敏测试（AUDIT-02，SC-3 / SC-4）。

覆盖 emit 吞异常不冒泡 + audit.emit_failed warning / 主操作不受影响 /
async aemit fail-soft / 入口强制脱敏（DB 无明文终极防线）。
"""

import json

import pytest
from django.db import connection
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


@pytest.mark.django_db
def test_emit_db_failure_does_not_poison_outer_transaction(monkeypatch):
    """MEDIUM-3：emit 内 create 触发真实 DB 错误时，savepoint 兜底不污染外层事务。

    django_db 测试本身运行在外层事务里。若 create 失败未被 savepoint 隔离，会把外层
    事务标记为 broken，后续任意 ORM 调用将抛 TransactionManagementError。本测试用一条
    会触发 NOT NULL 约束失败的原始 INSERT 模拟真实 DB 级失败，验证 emit 后外层事务仍可用。
    """

    def _bad_insert(*args, **kwargs):
        # 仅给 id、缺 NOT NULL 列 → 触发真实 DB 级 IntegrityError（非纯 Python 异常）
        with connection.cursor() as cur:
            cur.execute("INSERT INTO audit_event (id) VALUES ('poison-probe')")

    monkeypatch.setattr(AuditEvent.objects, "create", _bad_insert)
    AuditService.emit(action="member.created", target_type="user")

    # 若外层事务被污染，这条 SELECT 会抛 TransactionManagementError
    assert AuditEvent.objects.count() == 0


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
