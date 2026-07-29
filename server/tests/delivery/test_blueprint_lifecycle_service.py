"""BlueprintLifecycleService 11 态状态机守护（Phase 111-02 Task 2，LIFE-01/02/03）。

覆盖矩阵：

- 合法流转逐条：参数化遍历 ``_ALLOWED_TRANSITIONS`` 全部边（含 ""→researching 入口
  与 failed→researching 人工重试）。
- 非法流转 fail-loud：代表性非法边抛 ValueError 且 DB 状态未变（终态无出边）。
- needs_clarification：return_status 非法值拒绝；缺省取 from_status（经事件 payload 断言）。
- confirm 守卫：open+blocking 线程阻塞；resolved / 非 blocking 不阻塞（LIFE-02）。
- reviewer：confirm 自动入名单（first_action 首插留痕、重复确认不覆盖）；手动增补。
- CAS 并发：DB 被旁改后转移被拒（ConcurrentBlueprintTransitionError）。
- 事件 best-effort：session=None 不落行（转移仍成功）；有 session 落一行且 payload 完整。

async + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

import delivery.services.blueprint_lifecycle_service as lifecycle_module
from delivery.models import (
    Artifact,
    BlueprintReviewer,
    BlueprintStatus,
    BlueprintThread,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
    ThreadKind,
    ThreadStatus,
)
from delivery.services.blueprint_lifecycle_service import (
    _ALLOWED_TRANSITIONS,
    BlueprintLifecycleService,
    ConcurrentBlueprintTransitionError,
)

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_artifact(blueprint_status: str = "") -> Artifact:
    return await Artifact.objects.acreate(
        artifact_type="technical_plan", blueprint_status=blueprint_status
    )


async def _make_user():
    from django.contrib.auth import get_user_model

    return await get_user_model().objects.acreate(username=f"u-{uuid.uuid4().hex[:6]}")


async def _make_session() -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
    )


async def _db_status(artifact_id) -> str:
    fresh = await Artifact.objects.aget(id=artifact_id)
    return fresh.blueprint_status


# ---- 合法流转逐条（DESIGN §4.2 全部边） ----

_LEGAL_EDGES = [
    (from_status, to_status)
    for from_status, targets in _ALLOWED_TRANSITIONS.items()
    for to_status in sorted(targets)
]


@pytest.mark.parametrize(("from_status", "to_status"), _LEGAL_EDGES)
async def test_legal_edge_transitions_and_persists(from_status: str, to_status: str) -> None:
    artifact = await _make_artifact(blueprint_status=from_status)
    await BlueprintLifecycleService().transition(artifact, to_status, initiated_by_user_id="tester")
    assert artifact.blueprint_status == to_status
    assert await _db_status(artifact.id) == to_status


# ---- 非法流转 fail-loud（含终态无出边，LIFE-03） ----


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (BlueprintStatus.RESEARCHING, BlueprintStatus.CONFIRMED),
        (BlueprintStatus.IMPLEMENTED, BlueprintStatus.DRAFTING),
        (BlueprintStatus.ARCHIVED, BlueprintStatus.RESEARCHING),
        (BlueprintStatus.SUPERSEDED, BlueprintStatus.DRAFTING),
        ("", BlueprintStatus.DRAFTING),
    ],
)
async def test_illegal_edge_raises_and_db_unchanged(from_status: str, to_status: str) -> None:
    artifact = await _make_artifact(blueprint_status=from_status)
    with pytest.raises(ValueError):
        await BlueprintLifecycleService().transition(
            artifact, to_status, initiated_by_user_id="tester"
        )
    assert await _db_status(artifact.id) == from_status


# ---- needs_clarification：return_status 校验与缺省 ----


async def test_needs_clarification_rejects_illegal_return_status() -> None:
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.DRAFTING)
    with pytest.raises(ValueError):
        await BlueprintLifecycleService().transition(
            artifact,
            BlueprintStatus.NEEDS_CLARIFICATION,
            initiated_by_user_id="tester",
            return_status=BlueprintStatus.CONFIRMED,
        )
    assert await _db_status(artifact.id) == BlueprintStatus.DRAFTING


async def test_needs_clarification_return_status_defaults_to_from_status() -> None:
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.RESEARCHING)
    session = await _make_session()
    await BlueprintLifecycleService().transition(
        artifact,
        BlueprintStatus.NEEDS_CLARIFICATION,
        initiated_by_user_id="tester",
        session=session,
    )
    event = await ConvergenceSessionEvent.objects.aget(session=session)
    assert event.payload["return_status"] == BlueprintStatus.RESEARCHING


# ---- confirm 守卫：open+blocking 线程（LIFE-02 前半） ----


async def test_confirm_blocked_by_open_blocking_thread() -> None:
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    thread = await BlueprintThread.objects.acreate(
        artifact=artifact,
        kind=ThreadKind.REPO_CONFIRMATION,
        blocking=True,
    )
    with pytest.raises(ValueError):
        await BlueprintLifecycleService().transition(
            artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="tester"
        )
    assert await _db_status(artifact.id) == BlueprintStatus.PENDING_REVIEW

    # 线程 resolved 后可确认
    thread.status = ThreadStatus.RESOLVED
    await thread.asave(update_fields=["status"])
    await BlueprintLifecycleService().transition(
        artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="tester"
    )
    assert await _db_status(artifact.id) == BlueprintStatus.CONFIRMED


async def test_confirm_not_blocked_by_non_blocking_open_thread() -> None:
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    await BlueprintThread.objects.acreate(
        artifact=artifact,
        kind=ThreadKind.HUMAN_COMMENT,
        blocking=False,
    )
    await BlueprintLifecycleService().transition(
        artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="tester"
    )
    assert await _db_status(artifact.id) == BlueprintStatus.CONFIRMED


# ---- reviewer：确认动作自动入名单（LIFE-02 后半） ----


async def test_confirm_with_acting_user_records_reviewer() -> None:
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    user = await _make_user()
    await BlueprintLifecycleService().transition(
        artifact,
        BlueprintStatus.CONFIRMED,
        initiated_by_user_id=str(user.id),
        acting_user=user,
    )
    reviewer = await BlueprintReviewer.objects.aget(artifact=artifact, user=user)
    assert reviewer.first_action == "final_approve"


async def test_repeat_confirm_keeps_single_row_and_first_action() -> None:
    """同 user 先入名单再走一轮 confirmed→drafting→…→confirmed：仍一行且 first_action 未变。"""
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    user = await _make_user()
    service = BlueprintLifecycleService()
    # 先经确认门动作入名单（首个动作留痕）
    await service.add_reviewer(artifact, user, "repo_confirmation")
    await service.transition(
        artifact,
        BlueprintStatus.CONFIRMED,
        initiated_by_user_id=str(user.id),
        acting_user=user,
    )
    # 再走一轮回到 confirmed
    for to_status in (
        BlueprintStatus.DRAFTING,
        BlueprintStatus.AI_REVIEWING,
        BlueprintStatus.PENDING_REVIEW,
        BlueprintStatus.CONFIRMED,
    ):
        await service.transition(
            artifact, to_status, initiated_by_user_id=str(user.id), acting_user=user
        )
    assert await BlueprintReviewer.objects.filter(artifact=artifact).acount() == 1
    reviewer = await BlueprintReviewer.objects.aget(artifact=artifact, user=user)
    assert reviewer.first_action == "repo_confirmation"


async def test_add_reviewer_manual_supplement() -> None:
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    user_a = await _make_user()
    user_b = await _make_user()
    service = BlueprintLifecycleService()
    await service.transition(
        artifact,
        BlueprintStatus.CONFIRMED,
        initiated_by_user_id=str(user_a.id),
        acting_user=user_a,
    )
    reviewer_b = await service.add_reviewer(artifact, user_b, "manual_add")
    assert reviewer_b.first_action == "manual_add"
    assert await BlueprintReviewer.objects.filter(artifact=artifact).acount() == 2


# ---- CAS 并发拒绝 ----


async def test_concurrent_transition_rejected_by_cas() -> None:
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    # 旁路模拟并发：DB 已被推进为 drafting，内存对象仍是 pending_review
    await Artifact.objects.filter(id=artifact.id).aupdate(blueprint_status=BlueprintStatus.DRAFTING)
    with pytest.raises(ConcurrentBlueprintTransitionError):
        await BlueprintLifecycleService().transition(
            artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="tester"
        )
    assert await _db_status(artifact.id) == BlueprintStatus.DRAFTING


# ---- 事件 best-effort（RESEARCH P3） ----


async def test_transition_without_session_persists_no_event() -> None:
    artifact = await _make_artifact(blueprint_status="")
    await BlueprintLifecycleService().transition(
        artifact, BlueprintStatus.RESEARCHING, initiated_by_user_id="tester"
    )
    assert await ConvergenceSessionEvent.objects.acount() == 0
    assert await _db_status(artifact.id) == BlueprintStatus.RESEARCHING


async def test_transition_without_session_logs_warning() -> None:
    """MN-04：零 DB 留痕的转移必须留 warning，否则「怎么变的」只能靠翻 info 日志。"""
    artifact = await _make_artifact(blueprint_status="")
    with patch.object(lifecycle_module.logger, "warning") as warn_spy:
        await BlueprintLifecycleService().transition(
            artifact, BlueprintStatus.RESEARCHING, initiated_by_user_id="tester"
        )
    events = [call.args[0] for call in warn_spy.call_args_list]
    assert "blueprint_transition_without_session" in events


async def test_return_status_ignored_for_non_clarification_target() -> None:
    """MN-03：非 needs_clarification 目标态传入的 return_status 不得进事件 payload。"""
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.RESEARCHING)
    session = await _make_session()
    with patch.object(lifecycle_module.logger, "warning") as warn_spy:
        await BlueprintLifecycleService().transition(
            artifact,
            BlueprintStatus.DRAFTING,
            initiated_by_user_id="tester",
            session=session,
            return_status="随便一个没校验过的字符串",
        )
    event = await ConvergenceSessionEvent.objects.aget(session=session)
    assert event.payload["return_status"] is None
    events = [call.args[0] for call in warn_spy.call_args_list]
    assert "blueprint_return_status_ignored" in events


async def test_transition_with_session_persists_event_row() -> None:
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.RESEARCHING)
    session = await _make_session()
    await BlueprintLifecycleService().transition(
        artifact,
        BlueprintStatus.DRAFTING,
        initiated_by_user_id="tester",
        session=session,
    )
    event = await ConvergenceSessionEvent.objects.aget(session=session)
    assert event.event == "blueprint.status.transitioned"
    assert event.payload["artifact_id"] == str(artifact.id)
    assert event.payload["from_status"] == BlueprintStatus.RESEARCHING
    assert event.payload["to_status"] == BlueprintStatus.DRAFTING
    assert event.payload["initiated_by_user_id"] == "tester"
