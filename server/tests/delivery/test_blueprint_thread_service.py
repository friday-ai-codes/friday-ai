"""BlueprintLifecycleService 线程写入方法守护（Phase 112-02 Task 1）。

覆盖矩阵：

- ``open_thread``：线程 + 首条 AI 消息同事务落库；非法 kind 抛 ValueError 且零行写入。
- ``ahas_open_blocking_threads``：无线程 / open+blocking / resolved 后 / kind 过滤四态。
- ``record_answer``：open→answered 推进 + 消息累加；answered 线程再作答不回退状态。
- ``resolve_thread``：幂等（连调两次仍 resolved）；dismissed 分支；resolution 落消息。
- ``return_stage`` 超 16 字符截断且不抛（字段 max_length=16）。
- 与既有 LIFE-02 守卫联动：新方法开出的阻塞线程仍能挡住 ``→ confirmed``。

async + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import uuid

import pytest

from delivery.models import (
    Artifact,
    BlueprintStatus,
    BlueprintThread,
    BlueprintThreadMessage,
    ThreadAuthorType,
    ThreadKind,
    ThreadStatus,
)
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_artifact(blueprint_status: str = "") -> Artifact:
    return await Artifact.objects.acreate(
        artifact_type="technical_plan", blueprint_status=blueprint_status
    )


async def _make_user():
    from django.contrib.auth import get_user_model

    return await get_user_model().objects.acreate(username=f"u-{uuid.uuid4().hex[:6]}")


# ---- open_thread ----


async def test_open_thread_creates_thread_with_first_ai_message() -> None:
    artifact = await _make_artifact()
    options = [{"label": "只改后端", "value": "backend", "citations": ["cit_a"]}]

    thread = await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="目标用户是谁？",
        options=options,
        initiated_by_user_id="tester",
        return_stage=BlueprintStatus.RESEARCHING,
    )

    fresh = await BlueprintThread.objects.aget(id=thread.id)
    assert fresh.kind == ThreadKind.AI_CLARIFICATION
    assert fresh.blocking is True
    assert fresh.status == ThreadStatus.OPEN
    assert fresh.options == options
    assert fresh.initiated_by_user_id == "tester"
    assert fresh.return_stage == BlueprintStatus.RESEARCHING

    messages = [m async for m in BlueprintThreadMessage.objects.filter(thread=fresh)]
    assert len(messages) == 1
    assert messages[0].author_type == ThreadAuthorType.AI
    assert messages[0].body == "目标用户是谁？"


async def test_open_thread_illegal_kind_raises_and_writes_nothing() -> None:
    """非法 kind fail-loud，且不得留下半截线程。"""
    artifact = await _make_artifact()
    with pytest.raises(ValueError):
        await BlueprintLifecycleService().open_thread(
            artifact, kind="not_a_kind", blocking=True, question="?"
        )
    assert await BlueprintThread.objects.acount() == 0
    assert await BlueprintThreadMessage.objects.acount() == 0


async def test_open_thread_truncates_overlong_return_stage() -> None:
    """return_stage 字段 max_length=16：超长截断而非抛（开不出线程 = 规格门静默放行）。"""
    artifact = await _make_artifact()
    thread = await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="?",
        return_stage="x" * 20,
    )
    fresh = await BlueprintThread.objects.aget(id=thread.id)
    assert len(fresh.return_stage) <= 16


# ---- ahas_open_blocking_threads ----


async def test_has_open_blocking_threads_lifecycle() -> None:
    artifact = await _make_artifact()
    service = BlueprintLifecycleService()

    assert await service.ahas_open_blocking_threads(artifact) is False

    thread = await service.open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="?"
    )
    assert await service.ahas_open_blocking_threads(artifact) is True

    await service.resolve_thread(thread)
    assert await service.ahas_open_blocking_threads(artifact) is False


async def test_has_open_blocking_threads_kind_filter() -> None:
    """kind 过滤生效：确认门查询不得被澄清线程误挡（反之亦然）。"""
    artifact = await _make_artifact()
    service = BlueprintLifecycleService()
    await service.open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="?"
    )

    assert await service.ahas_open_blocking_threads(artifact, kind=ThreadKind.AI_CLARIFICATION)
    assert (
        await service.ahas_open_blocking_threads(artifact, kind=ThreadKind.REPO_CONFIRMATION)
        is False
    )


async def test_non_blocking_open_thread_not_counted() -> None:
    artifact = await _make_artifact()
    service = BlueprintLifecycleService()
    await service.open_thread(
        artifact, kind=ThreadKind.HUMAN_COMMENT, blocking=False, question="随手评论"
    )
    assert await service.ahas_open_blocking_threads(artifact) is False


# ---- record_answer ----


async def test_record_answer_advances_to_answered_and_appends_message() -> None:
    artifact = await _make_artifact()
    user = await _make_user()
    service = BlueprintLifecycleService()
    thread = await service.open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="目标用户是谁？"
    )

    message = await service.record_answer(
        thread, body="高三学生", author=user, initiated_by_user_id=str(user.id)
    )

    assert message.author_type == ThreadAuthorType.HUMAN
    fresh = await BlueprintThread.objects.aget(id=thread.id)
    assert fresh.status == ThreadStatus.ANSWERED
    assert await BlueprintThreadMessage.objects.filter(thread=thread).acount() == 2


async def test_record_answer_does_not_regress_terminal_status() -> None:
    """已 resolved 的线程再作答只追加消息，状态不得被拉回 answered。"""
    artifact = await _make_artifact()
    service = BlueprintLifecycleService()
    thread = await service.open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="?"
    )
    await service.record_answer(thread, body="第一次")
    await service.resolve_thread(thread)

    await service.record_answer(thread, body="第二次")

    fresh = await BlueprintThread.objects.aget(id=thread.id)
    assert fresh.status == ThreadStatus.RESOLVED
    assert await BlueprintThreadMessage.objects.filter(thread=thread).acount() == 3


# ---- resolve_thread ----


async def test_resolve_thread_is_idempotent() -> None:
    artifact = await _make_artifact()
    service = BlueprintLifecycleService()
    thread = await service.open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="?"
    )

    await service.resolve_thread(thread, resolution="已确认目标用户")
    await service.resolve_thread(thread, resolution="又来一次")

    fresh = await BlueprintThread.objects.aget(id=thread.id)
    assert fresh.status == ThreadStatus.RESOLVED
    # 首次的结论消息落库，重复调用不再追加噪声
    bodies = [m.body async for m in BlueprintThreadMessage.objects.filter(thread=thread)]
    assert bodies == ["?", "已确认目标用户"]


async def test_resolve_thread_dismissed_branch() -> None:
    artifact = await _make_artifact()
    service = BlueprintLifecycleService()
    thread = await service.open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="?"
    )
    await service.resolve_thread(thread, dismissed=True)
    fresh = await BlueprintThread.objects.aget(id=thread.id)
    assert fresh.status == ThreadStatus.DISMISSED


# ---- 与既有 LIFE-02 守卫联动 ----


async def test_open_thread_still_blocks_confirm_transition() -> None:
    """新 writer 开出的阻塞线程必须仍被既有 confirm 守卫认得（LIFE-02 未被破坏）。"""
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    service = BlueprintLifecycleService()
    thread = await service.open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="?"
    )

    with pytest.raises(ValueError):
        await service.transition(artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="tester")

    await service.resolve_thread(thread)
    await service.transition(artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="tester")
    fresh = await Artifact.objects.aget(id=artifact.id)
    assert fresh.blueprint_status == BlueprintStatus.CONFIRMED
