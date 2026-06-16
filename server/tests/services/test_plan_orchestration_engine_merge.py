"""engine._merge 接线测试（Phase 40-02 Task 2，§14 + engine 纯度）。

注入 **mock merge adapter**，真实 PlanSession + PlanSessionService。覆盖
pass→done / fail 首次按 back_target 回退 clarifying|researching / fail 超限→failed 终态。
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from delivery.models import PlanSession, PlanSessionEntrypoint, PlanSessionStatus
from services.plan_orchestration import PlanOrchestrationEngine

ENGINE_PATH = (
    Path(__file__).resolve().parents[2] / "services" / "plan_orchestration" / "engine.py"
)


def _merge_mock(result: dict) -> AsyncMock:
    merge = AsyncMock()
    merge.merge = AsyncMock(return_value=result)
    return merge


async def _merging_session() -> PlanSession:
    return await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.MERGING
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_merge_pass_to_done() -> None:
    """pass → merging→done。"""
    session = await _merging_session()
    merge = _merge_mock({"validation_status": "passed", "plan_version_id": "x", "attempt": 0})
    engine = PlanOrchestrationEngine(merge=merge)

    await engine.advance(session)

    assert (await PlanSession.objects.aget(id=session.id)).status == PlanSessionStatus.DONE


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_merge_fail_first_reclarify() -> None:
    """fail 首次（attempt=0, back_target=clarifying）→ merging→clarifying。"""
    session = await _merging_session()
    merge = _merge_mock(
        {"validation_status": "failed", "back_target": "clarifying", "attempt": 0}
    )
    engine = PlanOrchestrationEngine(merge=merge)

    await engine.advance(session)

    assert (await PlanSession.objects.aget(id=session.id)).status == PlanSessionStatus.CLARIFYING


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_merge_fail_first_reresearch() -> None:
    """fail 首次（attempt=0, back_target=researching）→ merging→researching。"""
    session = await _merging_session()
    merge = _merge_mock(
        {"validation_status": "failed", "back_target": "researching", "attempt": 0}
    )
    engine = PlanOrchestrationEngine(merge=merge)

    await engine.advance(session)

    assert (
        await PlanSession.objects.aget(id=session.id)
    ).status == PlanSessionStatus.RESEARCHING


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_merge_fail_exhausted_to_failed() -> None:
    """fail 超限（attempt=1）→ merging→failed，error.reason=merge_validation_exhausted。"""
    session = await _merging_session()
    merge = _merge_mock(
        {"validation_status": "failed", "back_target": "clarifying", "attempt": 1,
         "report": {"errors": [{"check": "dependency_cycle"}]}}
    )
    engine = PlanOrchestrationEngine(merge=merge)

    await engine.advance(session)

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.FAILED
    assert reloaded.error.get("reason") == "merge_validation_exhausted"


def test_merge_handler_does_not_write_status_directly() -> None:
    """源码守护：engine.py 不含直接 .status= 赋值（_merge 仅经 transition）。"""
    text = ENGINE_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\.status\s*=", text), (
        "engine 不应直接写 session.status，应只经 PlanSessionService.transition"
    )
