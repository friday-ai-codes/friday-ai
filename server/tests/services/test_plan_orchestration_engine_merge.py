"""merge stage handler 接线测试（§14 + engine 纯度）。

注入 **mock merge adapter**，真实 ConvergenceSession + ConvergenceSessionService。覆盖
pass→__done__ / fail 首次按 back_target 回退 clarify|research / fail 超限→__failed__ 终态。
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
)
from delivery.services import ConvergenceSessionService
from services.process_runtime import ProcessEngine

ENGINE_PATH = (
    Path(__file__).resolve().parents[2] / "services" / "process_runtime" / "engine.py"
)


def _engine(result: dict) -> ProcessEngine:
    merge = AsyncMock()
    merge.merge = AsyncMock(return_value=result)
    return ProcessEngine(
        session_service=ConvergenceSessionService(), deps=SimpleNamespace(merge=merge)
    )


async def _merging_session() -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="merge",
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_merge_pass_to_done() -> None:
    """pass → merge→__done__。"""
    session = await _merging_session()
    engine = _engine({"validation_status": "passed", "artifact_version_id": None, "attempt": 0})

    await engine.advance(session)

    assert (await ConvergenceSession.objects.aget(id=session.id)).status == ConvergenceSessionStatus.DONE


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_merge_fail_first_reclarify() -> None:
    """fail 首次（attempt=0, back_target=clarify）→ merge→clarify。"""
    session = await _merging_session()
    engine = _engine({"validation_status": "failed", "back_target": "clarify", "attempt": 0})

    await engine.advance(session)

    assert (await ConvergenceSession.objects.aget(id=session.id)).current_stage == "clarify"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_merge_fail_first_reresearch() -> None:
    """fail 首次（attempt=0, back_target=research）→ merge→research。"""
    session = await _merging_session()
    engine = _engine({"validation_status": "failed", "back_target": "research", "attempt": 0})

    await engine.advance(session)

    assert (await ConvergenceSession.objects.aget(id=session.id)).current_stage == "research"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_merge_fail_exhausted_to_failed() -> None:
    """fail 超限（attempt=1）→ merge→__failed__，error.reason=merge_validation_exhausted。"""
    session = await _merging_session()
    engine = _engine(
        {
            "validation_status": "failed",
            "back_target": "clarify",
            "attempt": 1,
            "report": {"errors": [{"check": "dependency_cycle"}]},
        }
    )

    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.status == ConvergenceSessionStatus.FAILED
    assert reloaded.error.get("reason") == "merge_validation_exhausted"


def test_merge_handler_does_not_write_status_directly() -> None:
    """源码守护：engine.py 不含直接 .status= 赋值（merge handler 仅经 transition）。"""
    text = ENGINE_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\.status\s*=", text), (
        "engine 不应直接写 session.status，应只经 ConvergenceSessionService.transition"
    )
