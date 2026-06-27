"""standalone 澄清卡回调测试（SLOT-02，92-03 Task 2）。

覆盖（mirror test_plan_clarify_callback 范式，纯 mock 无 DB/网络）：
- Test 1 前缀注册唯一：``clarify_card_`` 已注册，与 ``plan_clarify_`` / ``chat_question_answer`` 不交叉。
- Test 2 同步 ack + 缺 id no-op：缺 execution_id/node_id → None；action != clarify_card_answer → None；正常 → ack + 派发。
- Test 3 _build_answers 映射：按 order 枚举 q{i}/qt{i} → answers[{question_id, selected, freeform_text}]。
- Test 4 后台续推 + approve_node 本节点：有 clarification_id → answer_round 落库 → approve_node 本 card 节点。
- Test 5 非 waiting 幂等：非 waiting_event → ignored no-op。
- Test 6 fail-soft：answer_round/approve_node 抛错 → 不反噬。
- Test 7 transient 无 clarification_id：跳过 answer_round、仍 approve_node 携 answers。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feishu.callbacks.clarify_card_callback import (
    _build_answers,
    handle_clarify_card_action,
)
from feishu.views import CardCallback

_MOD = "feishu.callbacks.clarify_card_callback"

_QUESTIONS = [
    {"id": "qa", "order": 0, "question": "实验组用户？", "qtype": "single"},
    {"id": "qb", "order": 1, "question": "命中策略？", "qtype": "multi"},
]


def _make_callback(action_value: dict[str, Any]) -> CardCallback:
    return CardCallback(
        action_value=action_value,
        user_open_id="ou_user",
        message_id="msg",
        chat_id="oc_chat",
        tenant_key="t",
    )


def _waiting_node(node_type: str = "clarification_card") -> MagicMock:
    ne = MagicMock()
    ne.id = "ne-1"
    ne.node = MagicMock(node_type=node_type)
    ne.output_data = {"questions_meta": [{"id": "qa", "order": 0, "qtype": "single"}]}
    ne.approval_data = {}
    ne.asave = AsyncMock()
    we = MagicMock()
    we.status = "suspended"
    we.asave = AsyncMock()
    ne.workflow_execution = we
    return ne


# ---------------------------------------------------------------------------
# Test 1：前缀注册唯一
# ---------------------------------------------------------------------------


def test_prefix_registered_and_unique() -> None:
    import feishu.urls  # noqa: F401 — 触发回调注册
    from feishu.views import _card_callback_handlers

    assert "clarify_card_" in _card_callback_handlers
    # clarify_card_answer 不被 plan_clarify_ / chat_question_ 抢路由
    assert not "clarify_card_answer".startswith("plan_clarify_")
    assert not "clarify_card_answer".startswith("chat_question")
    for prefix in _card_callback_handlers:
        if prefix == "clarify_card_":
            continue
        assert not "clarify_card_answer".startswith(prefix), prefix


# ---------------------------------------------------------------------------
# Test 2：同步 ack + 缺 id no-op
# ---------------------------------------------------------------------------


class TestSyncEntry:
    @patch(f"{_MOD}._run_in_thread")
    def test_answer_schedules_and_acks(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {
                "action": "clarify_card_answer",
                "execution_id": "e1",
                "node_id": "n1",
                "clarification_id": "c1",
                "question_count": 2,
                "q0": "A",
            }
        )
        result = handle_clarify_card_action(cb)
        mock_run.assert_called_once()
        assert result is not None
        assert result["header"]["template"] == "grey"

    @patch(f"{_MOD}._run_in_thread")
    def test_missing_execution_ids_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback({"action": "clarify_card_answer", "clarification_id": "c1"})
        result = handle_clarify_card_action(cb)
        assert result is None
        mock_run.assert_not_called()

    @patch(f"{_MOD}._run_in_thread")
    def test_unknown_action_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "clarify_card_bogus", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_clarify_card_action(cb)
        assert result is None
        mock_run.assert_not_called()

    @patch(f"{_MOD}._run_in_thread")
    def test_transient_no_clarification_id_still_schedules(self, mock_run: MagicMock) -> None:
        # 无 clarification_id（透传模式）仍调度（区别 91：不强制 clarification_id）
        cb = _make_callback(
            {"action": "clarify_card_answer", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_clarify_card_action(cb)
        mock_run.assert_called_once()
        assert result is not None


# ---------------------------------------------------------------------------
# Test 3：_build_answers 映射（索引↔question_id）
# ---------------------------------------------------------------------------


class TestBuildAnswers:
    def test_maps_by_order_index_to_question_id(self) -> None:
        data = {"q0": "实验组", "qt0": "", "q1": ["策略A", "策略B"], "qt1": "其他补充"}
        answers = _build_answers(_QUESTIONS, data)
        assert answers == [
            {"question_id": "qa", "selected": "实验组", "freeform_text": ""},
            {"question_id": "qb", "selected": ["策略A", "策略B"], "freeform_text": "其他补充"},
        ]

    def test_missing_field_yields_none_selected(self) -> None:
        answers = _build_answers(_QUESTIONS, {"qt0": "自定义"})
        assert answers[0] == {"question_id": "qa", "selected": None, "freeform_text": "自定义"}
        assert answers[1]["question_id"] == "qb"


# ---------------------------------------------------------------------------
# Test 4：后台续推 + approve_node 本节点（有 clarification_id 落库）
# ---------------------------------------------------------------------------


class TestAnswerBackground:
    @pytest.mark.asyncio
    async def test_answer_persists_and_approves_self(self) -> None:
        from feishu.callbacks.clarify_card_callback import _do_clarify_card_async

        ne = _waiting_node()
        wf_engine = AsyncMock()
        clar_service = MagicMock()
        clar_service.answer_round = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._acollect_round_questions", AsyncMock(return_value=_QUESTIONS)),
            patch(f"{_MOD}.ClarificationService", return_value=clar_service),
            patch(f"{_MOD}._send_answered_card_best_effort", AsyncMock()) as mock_card,
            patch(f"{_MOD}.WorkflowEngine", return_value=wf_engine),
        ):
            await _do_clarify_card_async(
                execution_id="e1",
                node_id="n1",
                clarification_id="c1",
                question_count=2,
                data={"q0": "A", "qt0": "", "q1": ["X", "Y"], "qt1": ""},
                responder_id="ou_user",
                chat_id="oc_chat",
            )

        # 有 clarification_id → answer_round 落库（INV-6）
        clar_service.answer_round.assert_awaited_once()
        assert clar_service.answer_round.await_args.args[0] == "c1"
        assert clar_service.answer_round.await_args.args[1] == [
            {"question_id": "qa", "selected": "A", "freeform_text": ""},
            {"question_id": "qb", "selected": ["X", "Y"], "freeform_text": ""},
        ]
        # approve 本 card 节点（携 answers）
        assert ne.approval_data["clarification_answered"] is True
        assert ne.approval_data["clarification_id"] == "c1"
        assert ne.approval_data["answers"][0]["question_id"] == "qa"
        wf_engine.approve_node.assert_awaited_once()
        assert wf_engine.approve_node.await_args.args[0] is ne
        assert wf_engine.approve_node.await_args.args[2] == "clarify_card_answer"
        mock_card.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_waiting_is_idempotent(self) -> None:
        from feishu.callbacks.clarify_card_callback import _do_clarify_card_async

        wf_engine = AsyncMock()
        clar_service = MagicMock()
        clar_service.answer_round = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=None)),
            patch(f"{_MOD}._acollect_round_questions", AsyncMock()) as mock_collect,
            patch(f"{_MOD}.ClarificationService", return_value=clar_service),
            patch(f"{_MOD}.WorkflowEngine", return_value=wf_engine),
        ):
            await _do_clarify_card_async(
                execution_id="e1",
                node_id="n1",
                clarification_id="c1",
                question_count=2,
                data={"q0": "A"},
                responder_id="ou_user",
                chat_id="oc_chat",
            )

        mock_collect.assert_not_awaited()
        clar_service.answer_round.assert_not_awaited()
        wf_engine.approve_node.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wrong_node_type_is_no_op(self) -> None:
        from feishu.callbacks.clarify_card_callback import _do_clarify_card_async

        ne = _waiting_node(node_type="ai_plan_research")
        wf_engine = AsyncMock()
        clar_service = MagicMock()
        clar_service.answer_round = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._acollect_round_questions", AsyncMock()) as mock_collect,
            patch(f"{_MOD}.ClarificationService", return_value=clar_service),
            patch(f"{_MOD}.WorkflowEngine", return_value=wf_engine),
        ):
            await _do_clarify_card_async(
                execution_id="e1",
                node_id="n1",
                clarification_id="c1",
                question_count=2,
                data={"q0": "A"},
                responder_id="ou_user",
                chat_id="oc_chat",
            )

        # 跨节点防误 approve：node_type 不符 → no-op
        mock_collect.assert_not_awaited()
        clar_service.answer_round.assert_not_awaited()
        wf_engine.approve_node.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failsoft_does_not_raise(self) -> None:
        from feishu.callbacks.clarify_card_callback import _do_clarify_card_async

        ne = _waiting_node()
        wf_engine = AsyncMock()
        clar_service = MagicMock()
        clar_service.answer_round = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._acollect_round_questions", AsyncMock(return_value=_QUESTIONS)),
            patch(f"{_MOD}.ClarificationService", return_value=clar_service),
            patch(f"{_MOD}.WorkflowEngine", return_value=wf_engine),
        ):
            # answer_round 抛 → fail-soft（不冒泡）
            await _do_clarify_card_async(
                execution_id="e1",
                node_id="n1",
                clarification_id="c1",
                question_count=2,
                data={"q0": "A"},
                responder_id="ou_user",
                chat_id="oc_chat",
            )

        clar_service.answer_round.assert_awaited_once()
        wf_engine.approve_node.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transient_skips_answer_round_still_approves(self) -> None:
        from feishu.callbacks.clarify_card_callback import _do_clarify_card_async

        ne = _waiting_node()
        # transient：questions 来自 output_data.questions_meta
        ne.output_data = {
            "questions_meta": [
                {"id": "qa", "order": 0, "qtype": "single"},
                {"id": "qb", "order": 1, "qtype": "multi"},
            ]
        }
        wf_engine = AsyncMock()
        clar_service = MagicMock()
        clar_service.answer_round = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._acollect_round_questions", AsyncMock()) as mock_collect,
            patch(f"{_MOD}.ClarificationService", return_value=clar_service),
            patch(f"{_MOD}._send_answered_card_best_effort", AsyncMock()),
            patch(f"{_MOD}.WorkflowEngine", return_value=wf_engine),
        ):
            await _do_clarify_card_async(
                execution_id="e1",
                node_id="n1",
                clarification_id="",
                question_count=2,
                data={"q0": "A", "q1": ["X"]},
                responder_id="ou_user",
                chat_id="oc_chat",
            )

        # 无 clarification_id → 不查轮、不 answer_round；据 questions_meta 透传
        mock_collect.assert_not_awaited()
        clar_service.answer_round.assert_not_awaited()
        wf_engine.approve_node.assert_awaited_once()
        assert ne.approval_data["answers"][0]["question_id"] == "qa"
