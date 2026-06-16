"""PlanSessionService 状态机测试（ORCH-02，DOMAIN §14）。

覆盖 _ALLOWED 全部合法转移 / 非法转移 raise（status 不变、DB 不写）/
create_session + resume 持久化 / fail 从任意态落 failed + error JSON。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from delivery.models import PlanSession, PlanSessionEntrypoint, PlanSessionStatus
from delivery.services import PlanSessionService
from delivery.services.plan_session_service import (
    _ALLOWED,
    ConcurrentTransitionError,
)


@sync_to_async
def _create_user(username: str):
    return get_user_model().objects.create(username=username)


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
async def test_stale_transition_rejected_concurrency() -> None:
    """WR-01：陈旧内存态推进被条件原子更新拒绝（TOCTOU 双推进防护）。

    模拟并发：另一路已把 DB 行从 decomposing 推进到 routing；持有陈旧 session
    （内存态仍 decomposing）的一方再 transition("decomposed") 必须被拒，且 DB 行
    状态不被覆盖回 routing 之外（保 resume 安全）。
    """
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.DECOMPOSING,
    )
    svc = PlanSessionService()

    # 并发/先行 advance：直接把 DB 行推进到 routing（测试内绕过 service 模拟竞态）
    await PlanSession.objects.filter(id=session.id).aupdate(status=PlanSessionStatus.ROUTING)

    # 陈旧内存态（session.status 仍 decomposing）再推进 → 条件更新影响 0 行 → 拒绝
    with pytest.raises(ConcurrentTransitionError):
        await svc.transition(session, "decomposed")

    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.ROUTING  # 未被陈旧推进覆盖


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_session_rejects_invalid_entrypoint() -> None:
    """IN-02：create_session 对非 workflow|chat 的 entrypoint 显式 raise（不静默落库）。"""
    svc = PlanSessionService()
    before = await PlanSession.objects.filter(entrypoint="bogus").acount()
    with pytest.raises(ValueError) as exc_info:
        await svc.create_session("bogus")
    assert "entrypoint" in str(exc_info.value)
    # 非法 entrypoint 在 create 前即 raise，未新增该 entrypoint 的行
    after = await PlanSession.objects.filter(entrypoint="bogus").acount()
    assert after == before


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
async def test_fail_from_failed_is_noop_preserves_first_error() -> None:
    """IN-01：已 failed 的会话再 fail 为幂等 no-op，保留首个诊断 error（不被二次覆盖）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.RESEARCHING,
    )
    svc = PlanSessionService()
    first_error = {"stage": "researching", "exc": "Timeout"}
    await svc.transition(session, "fail", error=first_error)

    # 二次 fail（不同 error）应为 no-op，首因保留
    await svc.transition(session, "fail", error={"stage": "merging", "exc": "Other"})
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.FAILED
    assert reloaded.error == first_error


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_fail_from_done_is_noop() -> None:
    """IN-01：已 done 的会话误调 fail 为 no-op，不无声回落 failed。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.DONE,
    )
    svc = PlanSessionService()
    await svc.transition(session, "fail", error={"exc": "spurious"})
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.DONE
    assert reloaded.error == {}


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_routed_persists_routing_field() -> None:
    """routed 转移把 routing payload 落 PlanSession.routing（38-02 落库通道）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.ROUTING,
    )
    svc = PlanSessionService()
    routing = {
        "candidates": [{"repo_id": "r1", "confidence": "high"}],
        "router_version": "v2",
        "auto_selected": True,
    }
    await svc.transition(session, "routed", routing=routing)
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.RECALLING
    assert reloaded.routing == routing


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_recalled_persists_recall_context_field() -> None:
    """recalled 转移把 recall_context payload 落 PlanSession.recall_context（38-03 落库通道）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.RECALLING,
    )
    svc = PlanSessionService()
    recall_context = [{"entity_id": "e1", "kind": "work_item", "title": "t", "score": 0.9}]
    await svc.transition(session, "recalled", recall_context=recall_context)
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == PlanSessionStatus.CLARIFYING
    assert reloaded.recall_context == recall_context


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_session_with_created_by_persists() -> None:
    """create_session(created_by=user) 落 created_by FK（召回权限 actor 来源）。"""
    user = await _create_user("orchestrator")
    svc = PlanSessionService()
    session = await svc.create_session(PlanSessionEntrypoint.WORKFLOW, created_by=user)
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.created_by_id == user.id


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_session_created_by_defaults_none() -> None:
    """不传 created_by 时默认 None（nullable，系统/无交互用户场景）。"""
    svc = PlanSessionService()
    session = await svc.create_session(PlanSessionEntrypoint.CHAT)
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.created_by_id is None


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
