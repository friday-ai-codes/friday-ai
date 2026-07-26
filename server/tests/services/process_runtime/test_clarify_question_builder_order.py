"""ClarifyAdapter 问题组装器执行顺序回归测试。

守一个**很容易在重构中被悄悄弄反**的顺序：``question_builder`` 必须在 ``policy`` **之前**
执行。

为什么关键：默认 policy 见到全 high 置信路由会判「无需澄清」直接放行。如果 builder 排在
policy 后面，feature list 的强制确认（哪怕路由十分确定也要问一次关联仓库）就永远轮不到
执行——而且这个 bug 是静默的：编排照常跑完出方案，只是少问了用户一次，没有任何报错。
"""

from __future__ import annotations

from typing import Any

import pytest

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
)
from delivery.services import ClarificationService
from services.process_runtime.clarify_adapter import ClarifyAdapter

pytestmark = pytest.mark.django_db(transaction=True)

# 全 high 置信 → 默认 policy 会判「无需澄清」。
_CONFIDENT_ROUTING = {
    "candidates": [{"repo_id": "r1", "confidence": "high", "repository_name": "repo-a"}]
}

_BUILT_QUESTIONS = [
    {
        "question": "请确认本次需求实际涉及的仓库",
        "type": "multi",
        "options": ["repo-a"],
        "recommended": ["repo-a"],
    }
]


async def _make_session() -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.MCP,
        current_stage="clarify",
        stage_state={
            "decomposition": {"mode": "feature_list", "requirement_text": "做一批功能"},
            "routing": _CONFIDENT_ROUTING,
            "classification": {"items": [{"key": "m::a"}], "summary": {}},
        },
    )


@pytest.mark.asyncio
async def test_builder_runs_before_policy_and_forces_clarification() -> None:
    """默认 policy 判「不问」时，builder 仍然抢先发出确认题。"""
    session = await _make_session()
    policy_calls: list[Any] = []

    def _never_ask(sess: Any) -> tuple[bool, str, list]:
        policy_calls.append(sess)
        return False, "", []

    adapter = ClarifyAdapter(
        policy=_never_ask,
        question_builder=lambda sess, round_count=0: (_BUILT_QUESTIONS if round_count == 0 else []),
    )
    result = await adapter.clarify(session)

    assert result["needs_clarification"] is True, "builder 产出非空时必须挂起等确认"
    assert result.get("clarification_id")
    # 顺序证据：builder 抢先返回，policy 根本没被调用。
    assert policy_calls == [], "builder 应先于 policy 执行并短路"
    assert await ClarificationService().ahas_pending(session.id)


@pytest.mark.asyncio
async def test_second_round_falls_back_to_policy() -> None:
    """首轮已答后 builder 返回空 → 回落 policy；policy 判不问即放行进调研。"""
    session = await _make_session()
    policy_calls: list[Any] = []

    def _never_ask(sess: Any) -> tuple[bool, str, list]:
        policy_calls.append(sess)
        return False, "", []

    builder_rounds: list[int] = []

    def _builder(sess: Any, round_count: int = 0) -> list[dict]:
        builder_rounds.append(round_count)
        return _BUILT_QUESTIONS if round_count == 0 else []

    adapter = ClarifyAdapter(policy=_never_ask, question_builder=_builder)

    # 首轮：发确认题并挂起。
    first = await adapter.clarify(session)
    clarification_id = first["clarification_id"]

    # 作答整轮（否则 pending 短路会让第二次 clarify 原地返回）。
    from delivery.models import ClarificationQuestion

    answers = [
        {"question_id": str(row.id), "selected": ["repo-a"], "freeform_text": ""}
        async for row in ClarificationQuestion.objects.filter(clarification_id=clarification_id)
    ]
    await ClarificationService().answer_round(clarification_id, answers)

    # 第二轮：builder 返回空 → 回落 policy → 放行。
    second = await adapter.clarify(session)

    assert second["needs_clarification"] is False, "确认过一轮后应放行，不得反复追问"
    assert builder_rounds == [0, 1]
    assert len(policy_calls) == 1, "第二轮才应轮到 policy"


@pytest.mark.asyncio
async def test_builder_exception_falls_back_to_existing_path() -> None:
    """组装器抛异常 → best-effort 退回既有 policy 路径，绝不阻断编排。"""
    session = await _make_session()

    def _boom(sess: Any, round_count: int = 0) -> list[dict]:
        raise RuntimeError("builder broken")

    adapter = ClarifyAdapter(policy=lambda sess: (False, "", []), question_builder=_boom)
    result = await adapter.clarify(session)

    assert result["needs_clarification"] is False


@pytest.mark.asyncio
async def test_no_builder_keeps_existing_behaviour() -> None:
    """未注入 builder（既有入口）时行为不变：policy 说不问就不问。"""
    session = await _make_session()
    adapter = ClarifyAdapter(policy=lambda sess: (False, "", []))
    result = await adapter.clarify(session)

    assert result["needs_clarification"] is False
    assert not await ClarificationService().ahas_pending(session.id)
