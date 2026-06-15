"""PlanSessionService 状态机测试（ORCH-02，DOMAIN §14）。

覆盖 _ALLOWED 全部合法转移 / 非法转移 raise（status 不变、DB 不写）/
create_session + resume 持久化 / fail 从任意态落 failed + error JSON。
"""

from __future__ import annotations

import pytest

from delivery.models import PlanSession, PlanSessionEntrypoint, PlanSessionStatus
from delivery.services import PlanSessionService
from delivery.services.plan_session_service import _ALLOWED


def _all_allowed_cases() -> list[tuple[str, str, str]]:
    """展开 _ALLOWED 为 (from_status, event, to_status) 参数化用例。"""
    cases: list[tuple[str, str, str]] = []
    for from_status, events in _ALLOWED.items():
        for event, to_status in events.items():
            cases.append((from_status, event, to_status))
    return cases


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize("from_status,event,to_status", _all_allowed_cases())
async def test_allowed_transitions(from_status: str, event: str, to_status: str) -> None:
    """_ALLOWED 内所有合法转移成功改 status。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=from_status,
    )
    svc = PlanSessionService()
    result = await svc.transition(session, event)
    assert result.status == to_status
    # DB 持久化一致
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == to_status


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_illegal_transition_raises_and_no_write() -> None:
    """非法转移 raise ValueError，status 未变、DB 未写。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.DECOMPOSING,
    )
    svc = PlanSessionService()
    with pytest.raises(ValueError) as exc_info:
        await svc.transition(session, "merged")  # decomposing 不允许 merged
    assert "decomposing" in str(exc_info.value)
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.DECOMPOSING


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_session_default_and_persist_intermediate() -> None:
    """create_session 默认 decomposing；transition 落 decomposition JSON + status=routing，可 resume。"""
    svc = PlanSessionService()
    session = await svc.create_session(PlanSessionEntrypoint.CHAT)
    assert session.status == PlanSessionStatus.DECOMPOSING

    decomposition = {"segments": ["frontend", "backend"], "requirement_text": "x"}
    await svc.transition(session, "decomposed", decomposition=decomposition)

    # 从 DB 重取（模拟 resume）—— status + decomposition 一致，不依赖内存态
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.ROUTING
    assert reloaded.decomposition == decomposition


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_fail_from_any_status_with_dict_error() -> None:
    """fail 从任意状态 → failed + error JSON 落库。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.RESEARCHING,
    )
    svc = PlanSessionService()
    error = {"stage": "researching", "exc": "Timeout"}
    await svc.transition(session, "fail", error=error)
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.FAILED
    assert reloaded.error == error


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_fail_wraps_non_dict_error() -> None:
    """error 传非 dict 时包成 {'message': ...}。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.MERGING,
    )
    svc = PlanSessionService()
    await svc.transition(session, "fail", error="boom")
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.FAILED
    assert reloaded.error == {"message": "boom"}
