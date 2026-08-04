"""僵尸蓝图会话周期恢复扫描（116 事故修复）。

事故形状：作答后的续驱在 HTTP 请求内跑，进程重启 / 请求被杀把它连根带走 ——
线程早已答完（无 open+blocking 线程），会话却永远停在 ``waiting_clarification``，
没有任何回调会再碰它。本文件锁三条判据：

1. 滞留的挂起态会话被重驱（``recovered`` 口径 = 重驱后 ``(status, stage)`` 变化）；
2. **人审接管的蓝图一律跳过**（推进权归 approve/reject，重驱会在人审面上凭空开澄清）；
3. 未到滞留窗口的会话不进扫描面（刚更新过的会话可能正在被别处驱动）。

驱动器本体（pause 短路 / 步数上限）由既有用例覆盖，此处一律以桩替代。
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from django.utils import timezone

from delivery.models import (
    Artifact,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
)
from delivery.services import ArtifactService
from services.process_runtime import blueprint_resume
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _make_artifact():
    return await ArtifactService().create(
        "technical_plan", make_blueprint(), created_by_user_id="tester"
    )


async def _make_session(
    *,
    status: str = ConvergenceSessionStatus.WAITING_CLARIFICATION,
    stage: str = "spec_gate",
    artifact=None,
) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        status=status,
        current_stage=stage,
        current_artifact_version_id=getattr(artifact, "current_version_id", None),
    )


def _stale_now() -> object:
    """扫描注入的「现在」：把所有刚建的会话推成已滞留（auto_now 无法回拨）。"""
    return timezone.now() + timedelta(minutes=blueprint_resume._STALL_WAITING_MINUTES + 5)


async def test_stalled_waiting_session_gets_redriven(monkeypatch) -> None:
    """1. 滞留的 waiting_clarification 会话被重驱，(status, stage) 变化计入 recovered。"""
    artifact = await _make_artifact()
    await _make_session(artifact=artifact)

    async def _fake_drive(engine, target):
        target.status = ConvergenceSessionStatus.RUNNING
        target.current_stage = "repo_plan"
        return target

    monkeypatch.setattr(
        blueprint_resume, "adrive_blueprint_session_to_pause_or_terminal", _fake_drive
    )
    monkeypatch.setattr(
        blueprint_resume, "_afeedback_chat_barrier_if_any", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        blueprint_resume, "_aresume_workflow_node_if_any", AsyncMock(return_value=None)
    )

    counts = await blueprint_resume.arecover_stalled_blueprint_sessions(now=_stale_now())

    assert counts["scanned"] == 1
    assert counts["recovered"] == 1
    assert counts["skipped_human_owned"] == 0
    # 非恒真对照：重驱后无变化 ⇒ unchanged（pause 短路的合法等待形状）
    session2 = await _make_session(artifact=artifact)

    async def _noop_drive(engine, target):
        return target

    monkeypatch.setattr(
        blueprint_resume, "adrive_blueprint_session_to_pause_or_terminal", _noop_drive
    )
    counts2 = await blueprint_resume.arecover_stalled_blueprint_sessions(now=_stale_now())
    assert counts2["unchanged"] >= 1
    assert session2.id is not None  # 显式消费，防未用变量


async def test_human_owned_blueprint_is_skipped(monkeypatch) -> None:
    """2. 蓝图已被人审接管（pending_review 及之后）⇒ 跳过，绝不重驱。"""
    artifact = await _make_artifact()
    await Artifact.objects.filter(id=artifact.id).aupdate(blueprint_status="pending_review")
    await _make_session(artifact=artifact)

    drive = AsyncMock()
    monkeypatch.setattr(blueprint_resume, "adrive_blueprint_session_to_pause_or_terminal", drive)

    counts = await blueprint_resume.arecover_stalled_blueprint_sessions(now=_stale_now())

    assert counts["scanned"] == 1
    assert counts["skipped_human_owned"] == 1
    assert counts["recovered"] == 0
    drive.assert_not_awaited()


async def test_fresh_sessions_are_not_scanned(monkeypatch) -> None:
    """3. 未到滞留窗口的会话不进扫描面（可能正被别处驱动，绝不双跑）。"""
    artifact = await _make_artifact()
    await _make_session(artifact=artifact)

    drive = AsyncMock()
    monkeypatch.setattr(blueprint_resume, "adrive_blueprint_session_to_pause_or_terminal", drive)

    counts = await blueprint_resume.arecover_stalled_blueprint_sessions(now=timezone.now())

    assert counts["scanned"] == 0
    drive.assert_not_awaited()
