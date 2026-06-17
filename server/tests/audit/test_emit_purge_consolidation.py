"""v0.5 purge 埋点收口统一 AuditEvent 测试（AUDITCOV-02，SC-3）。

校验 ``run_cleanup`` 在保留既有 ``logger.info`` 结构化日志的同时，经
``_emit_purge_audit`` 把 ``purge.started`` / ``purge.completed`` 收口到 AuditService
单一写入入口（INV-6），产出 ``ACTION_PURGE_*`` AuditEvent（系统清理 actor=None）。
"""

from __future__ import annotations

import pytest

from audit.models import AuditEvent
from repositories.models import Repository
from services.purge_reconcile import run_cleanup

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.asyncio
async def test_run_cleanup_emits_started_and_completed(db) -> None:
    repo = await Repository.objects.acreate(name="purge-audit", git_url="https://example.com/p.git")
    # 显式空 paths：跳过对账，直接走 started → completed 主路径（无文件可删）。
    report = await run_cleanup(str(repo.id), mode="normal", paths=[])
    assert report.mode == "normal"

    started = await AuditEvent.objects.filter(
        action="purge.started", target_id=str(repo.id)
    ).afirst()
    completed = await AuditEvent.objects.filter(
        action="purge.completed", target_id=str(repo.id)
    ).afirst()
    assert started is not None
    assert completed is not None
    # 系统清理：actor=None + source=purge
    assert started.actor_id is None
    assert started.source == "purge"
    assert completed.metadata["mode"] == "normal"


@pytest.mark.asyncio
async def test_purge_event_target_is_repository(db) -> None:
    repo = await Repository.objects.acreate(
        name="purge-target", git_url="https://example.com/t.git"
    )
    await run_cleanup(str(repo.id), mode="normal", paths=[])
    event = await AuditEvent.objects.filter(action="purge.started", target_id=str(repo.id)).afirst()
    assert event is not None
    assert event.target_type == "repository"
