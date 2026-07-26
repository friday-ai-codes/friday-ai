"""classify stage 行为测试（feature list 方案编排扩展点）。

守两件事：

1. **INV-A 既有链路零扰动**：非 ``feature_list`` 会话穿过 classify 时不得调 deps、不得产
   stage_state——飞书 / 对话 / MCP 三条既有入口都靠这条保持行为不变。
2. feature_list 会话正常落分类结果并推进到 clarify。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
)
from delivery.services import ConvergenceSessionService
from services.process_runtime import ProcessEngine


async def _make_session(stage_state: dict | None = None) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="classify",
        stage_state=stage_state or {},
    )


def _classifier(result: dict) -> AsyncMock:
    classifier = AsyncMock()
    classifier.classify = AsyncMock(return_value=result)
    return classifier


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_non_feature_list_session_passes_through_without_touching_deps() -> None:
    """INV-A：普通会话穿过 classify 不调分类器、不写 stage_state。"""
    session = await _make_session({"decomposition": {"requirement_text": "做个功能"}})
    classifier = _classifier({"items": [{"key": "m::a"}]})
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(),
        deps=SimpleNamespace(classify=classifier),
    )

    await engine.advance(session)

    classifier.classify.assert_not_awaited()
    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "clarify"
    assert "classification" not in (reloaded.stage_state or {})


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_missing_classify_dep_passes_through() -> None:
    """deps 未注入 classify（旧构造）时 pass-through，不得 AttributeError。"""
    session = await _make_session({"decomposition": {"mode": "feature_list"}})
    engine = ProcessEngine(session_service=ConvergenceSessionService(), deps=SimpleNamespace())

    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "clarify"
    assert "classification" not in (reloaded.stage_state or {})


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_deps_none_passes_through() -> None:
    """deps 整体为 None 时同样 pass-through（engine 可无依赖构造）。"""
    session = await _make_session({"decomposition": {"mode": "feature_list"}})
    engine = ProcessEngine(session_service=ConvergenceSessionService(), deps=None)

    await engine.advance(session)

    assert (await ConvergenceSession.objects.aget(id=session.id)).current_stage == "clarify"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_feature_list_session_persists_classification_and_emits_event() -> None:
    """feature_list 会话调分类器、落 stage_state.classification、发分类事件。"""
    session = await _make_session({"decomposition": {"mode": "feature_list"}})
    classification = {
        "items": [{"key": "m::a", "change_type": "modify", "evidence_files": ["a.py"]}],
        "summary": {"new": 0, "modify": 1, "unclear": 0},
        "evidence_hits": 3,
    }
    classifier = _classifier(classification)
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(),
        deps=SimpleNamespace(classify=classifier),
    )
    spy = AsyncMock()
    engine.session_service._emit_event = spy

    await engine.advance(session)

    classifier.classify.assert_awaited_once()
    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "clarify"
    assert reloaded.classification == classification

    emitted = [
        call
        for call in spy.call_args_list
        if call.args and call.args[0] == "technical_plan.feature.classified"
    ]
    assert len(emitted) == 1
    assert emitted[0].args[2] == {
        "summary": {"new": 0, "modify": 1, "unclear": 0},
        "evidence_hits": 3,
    }


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_classifier_exception_lands_failed_not_crash() -> None:
    """分类器抛异常时经 engine 通用兜底落 failed，不冒泡到调用方。"""
    session = await _make_session({"decomposition": {"mode": "feature_list"}})
    classifier = AsyncMock()
    classifier.classify = AsyncMock(side_effect=RuntimeError("boom"))
    engine = ProcessEngine(
        session_service=ConvergenceSessionService(),
        deps=SimpleNamespace(classify=classifier),
    )

    await engine.advance(session)

    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.status == "failed"
    assert reloaded.error.get("stage") == "classify"
