"""aanswer_round_and_resume 入口无关共享回流 helper 单测（CLARIFY-06，91-01 Task 1）。

覆盖：
- answer_round 写入子题（selected/freeform）后，adrive 以同源 engine + 解析出的 session 续驱一次。
- engine 缺省 → 经 build_orchestration_engine() 构造（chat 入口形态）。
- 显式传入 engine → 直接复用，不再 build_orchestration_engine。
- 注入 clarification_service → 复用同一实例。
- answer_round 幂等：重复 answers 安全 no-op，不二次覆盖首答（adrive 仍续驱）。
- 解析不出 session（session 不存在）→ 直接 return None，adrive 不被调用。

pytest-socket 禁网——IO 全在 ORM（真实 PlanSession/Clarification/ClarificationQuestion）+
build_orchestration_engine / adrive mock 边界。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from delivery.models import (
    Clarification,
    ClarificationQuestion,
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionStatus,
)
from delivery.services import ClarificationService
from services.plan_orchestration import aanswer_round_and_resume

pytestmark = pytest.mark.django_db(transaction=True)

_BUILD_ENGINE = "services.plan_orchestration.entrypoint.build_orchestration_engine"
_ADRIVE = "services.plan_orchestration.resume.adrive_plan_session_to_pause_or_terminal"


async def _make_round() -> tuple[PlanSession, Clarification, ClarificationQuestion]:
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.CLARIFYING
    )
    clar = await ClarificationService().create_round(
        session,
        [{"question": "口径？", "type": "single", "options": ["a", "b"], "recommended": "a"}],
    )
    assert clar is not None
    q = await ClarificationQuestion.objects.aget(clarification_id=clar.id)
    return session, clar, q


@pytest.mark.asyncio
async def test_answers_then_drives_with_same_engine() -> None:
    """answer_round 写入子题 + adrive 以缺省 build 出的 engine + 解析 session 续驱一次。"""
    session, clar, q = await _make_round()
    sentinel_engine = MagicMock(name="engine")
    adrive = AsyncMock(return_value=session)

    with (
        patch(_BUILD_ENGINE, return_value=sentinel_engine) as build,
        patch(_ADRIVE, new=adrive),
    ):
        result = await aanswer_round_and_resume(
            clar.id, [{"question_id": str(q.id), "selected": "a", "freeform_text": ""}]
        )

    # 子题被写入
    answered = await ClarificationQuestion.objects.aget(id=q.id)
    assert answered.selected == "a"
    assert answered.answered_at is not None
    # engine 缺省 → build_orchestration_engine 构造
    build.assert_called_once()
    # adrive 以同源 engine + 解析出的 session 续驱一次
    adrive.assert_awaited_once()
    called_engine, called_session = adrive.await_args.args
    assert called_engine is sentinel_engine
    assert called_session.id == session.id
    assert result is session


@pytest.mark.asyncio
async def test_explicit_engine_reused_no_build() -> None:
    """显式传入 engine → 直接复用，不再调用 build_orchestration_engine。"""
    session, clar, q = await _make_round()
    explicit_engine = MagicMock(name="explicit_engine")
    adrive = AsyncMock(return_value=session)

    with (
        patch(_BUILD_ENGINE) as build,
        patch(_ADRIVE, new=adrive),
    ):
        await aanswer_round_and_resume(
            clar.id,
            [{"question_id": str(q.id), "selected": "a", "freeform_text": ""}],
            engine=explicit_engine,
        )

    build.assert_not_called()
    adrive.assert_awaited_once()
    assert adrive.await_args.args[0] is explicit_engine


@pytest.mark.asyncio
async def test_injected_service_reused() -> None:
    """注入 clarification_service → 复用同一实例完成 answer_round。"""
    session, clar, q = await _make_round()
    spy_service = ClarificationService()
    spy_service.answer_round = AsyncMock(side_effect=spy_service.answer_round)  # type: ignore[method-assign]
    adrive = AsyncMock(return_value=session)

    with (
        patch(_BUILD_ENGINE, return_value=MagicMock()),
        patch(_ADRIVE, new=adrive),
    ):
        await aanswer_round_and_resume(
            clar.id,
            [{"question_id": str(q.id), "selected": "a", "freeform_text": ""}],
            clarification_service=spy_service,
        )

    spy_service.answer_round.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotent_repeat_answer_noop() -> None:
    """重复提交相同 answers → 第二次幂等 no-op（首答不被覆盖），adrive 仍续驱。"""
    session, clar, q = await _make_round()
    adrive = AsyncMock(return_value=session)

    with (
        patch(_BUILD_ENGINE, return_value=MagicMock()),
        patch(_ADRIVE, new=adrive),
    ):
        await aanswer_round_and_resume(
            clar.id, [{"question_id": str(q.id), "selected": "a", "freeform_text": "first"}]
        )
        first = await ClarificationQuestion.objects.aget(id=q.id)
        first_answered_at = first.answered_at
        # 二次提交不同答案 → 幂等 no-op，不覆盖首答
        await aanswer_round_and_resume(
            clar.id, [{"question_id": str(q.id), "selected": "b", "freeform_text": "second"}]
        )

    again = await ClarificationQuestion.objects.aget(id=q.id)
    assert again.selected == "a"
    assert again.freeform_text == "first"
    assert again.answered_at == first_answered_at
    assert adrive.await_count == 2


@pytest.mark.asyncio
async def test_missing_session_returns_none() -> None:
    """answer_round 返回的 clar.session_id 解析不出 session → 直接 return None，adrive 不调。"""
    fake_clar = MagicMock()
    fake_clar.session_id = uuid.uuid4()
    fake_service = MagicMock()
    fake_service.answer_round = AsyncMock(return_value=fake_clar)
    adrive = AsyncMock()

    with (
        patch(_BUILD_ENGINE) as build,
        patch(_ADRIVE, new=adrive),
    ):
        result = await aanswer_round_and_resume(
            fake_clar, [], clarification_service=fake_service
        )

    assert result is None
    adrive.assert_not_awaited()
    build.assert_not_called()
