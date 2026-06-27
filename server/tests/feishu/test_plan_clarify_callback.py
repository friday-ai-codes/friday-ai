"""澄清回路卡片回调状态机测试（Phase 91，PLAN-03，91-03，CLARIFY-05/06）。

覆盖（镜像 plan_revision_callback 测试范式，纯 mock 无 DB/网络）：
- 同步入口：plan_clarify_answer 后台调度 + 即时确认卡；缺 clarification_id → None 不调度；
  缺 execution/node ids → None；非 plan_clarify_answer → None。
- 前缀 ``plan_clarify_`` 已注册且唯一（不撞 plan_revise / plan_revision_ / chat_question_）。
- 映射（WARNING #3 索引↔question_id）：``_build_answers`` 按 order 枚举 q{i}/qt{i} → answers[]，
  single=str / multi=list / freeform；索引固定对齐子题 id 不错位。
- 后台：form_value → answers → aanswer_round_and_resume 被调（mock，工作流入口 engine）→
  approve_node 被调；非 waiting 节点 → 幂等忽略（helper / approve 均未调）；helper 抛错 →
  fail-soft（不冒泡、approve 未调）；据卡片 clarification_id 取轮（不信回调直传 session_id）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feishu.callbacks.plan_clarify_callback import (
    _build_answers,
    handle_plan_clarify_action,
)
from feishu.views import CardCallback

_MOD = "feishu.callbacks.plan_clarify_callback"

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


def _waiting_node() -> MagicMock:
    ne = MagicMock()
    ne.id = "ne-1"
    ne.output_data = {"session_id": "sess-1", "kind": "clarification"}
    ne.approval_data = {}
    ne.asave = AsyncMock()
    we = MagicMock()
    we.status = "suspended"
    we.asave = AsyncMock()
    ne.workflow_execution = we
    return ne


# ---------------------------------------------------------------------------
# 前缀注册唯一
# ---------------------------------------------------------------------------


def test_prefix_registered_and_unique() -> None:
    import feishu.urls  # noqa: F401 — 触发回调注册
    from feishu.views import _card_callback_handlers

    assert "plan_clarify_" in _card_callback_handlers
    # plan_clarify_answer 不被既有 plan_revise / plan_revision_ / chat_question_ 抢路由
    assert not "plan_clarify_answer".startswith("plan_revise")
    assert not "plan_clarify_answer".startswith("plan_revision_")
    assert not "plan_clarify_answer".startswith("chat_question")
    # 与既有前缀互不为前缀
    for prefix in _card_callback_handlers:
        if prefix == "plan_clarify_":
            continue
        assert not "plan_clarify_answer".startswith(prefix), prefix


# ---------------------------------------------------------------------------
# 同步入口
# ---------------------------------------------------------------------------


class TestSyncEntry:
    @patch(f"{_MOD}._run_in_thread")
    def test_answer_schedules_and_acks(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {
                "action": "plan_clarify_answer",
                "execution_id": "e1",
                "node_id": "n1",
                "clarification_id": "c1",
                "question_count": 2,
                "q0": "A",
                "qt0": "",
            }
        )
        result = handle_plan_clarify_action(cb)
        mock_run.assert_called_once()
        assert result is not None
        assert result["header"]["template"] == "grey"

    @patch(f"{_MOD}._run_in_thread")
    def test_missing_clarification_id_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "plan_clarify_answer", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_plan_clarify_action(cb)
        assert result is None
        mock_run.assert_not_called()

    @patch(f"{_MOD}._run_in_thread")
    def test_missing_execution_ids_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback({"action": "plan_clarify_answer", "clarification_id": "c1"})
        result = handle_plan_clarify_action(cb)
        assert result is None
        mock_run.assert_not_called()

    @patch(f"{_MOD}._run_in_thread")
    def test_unknown_action_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {
                "action": "plan_clarify_bogus",
                "execution_id": "e1",
                "node_id": "n1",
                "clarification_id": "c1",
            }
        )
        result = handle_plan_clarify_action(cb)
        assert result is None
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 映射：索引↔question_id（WARNING #3）
# ---------------------------------------------------------------------------


class TestBuildAnswers:
    def test_maps_by_order_index_to_question_id(self) -> None:
        data = {
            "q0": "实验组",
            "qt0": "",
            "q1": ["策略A", "策略B"],
            "qt1": "其他补充",
        }
        answers = _build_answers(_QUESTIONS, data)
        assert answers == [
            {"question_id": "qa", "selected": "实验组", "freeform_text": ""},
            {
                "question_id": "qb",
                "selected": ["策略A", "策略B"],
                "freeform_text": "其他补充",
            },
        ]

    def test_missing_field_yields_none_selected(self) -> None:
        # 仅填了 freeform，没选下拉 → selected=None（纯 freeform），index 仍对齐 id
        answers = _build_answers(_QUESTIONS, {"qt0": "自定义"})
        assert answers[0] == {
            "question_id": "qa",
            "selected": None,
            "freeform_text": "自定义",
        }
        assert answers[1]["question_id"] == "qb"


# ---------------------------------------------------------------------------
# 后台：收答 → 同源 helper 续推 → approve_node 重调度
# ---------------------------------------------------------------------------


class TestAnswerBackground:
    @pytest.mark.asyncio
    async def test_answer_resumes_and_approves(self) -> None:
        from feishu.callbacks.plan_clarify_callback import _do_clarify_answer_async

        ne = _waiting_node()
        engine = MagicMock()
        wf_engine = AsyncMock()
        helper = AsyncMock(return_value=MagicMock(id="sess-1", status="researching"))

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._acollect_round_questions", AsyncMock(return_value=_QUESTIONS)),
            patch(f"{_MOD}.build_orchestration_engine", return_value=engine) as mock_build,
            patch(f"{_MOD}.aanswer_round_and_resume", helper),
            patch(f"{_MOD}._send_answered_card_best_effort", AsyncMock()) as mock_card,
            patch(f"{_MOD}.WorkflowEngine", return_value=wf_engine),
        ):
            await _do_clarify_answer_async(
                execution_id="e1",
                node_id="n1",
                clarification_id="c1",
                question_count=2,
                data={"q0": "A", "qt0": "", "q1": ["X", "Y"], "qt1": ""},
                responder_id="ou_user",
                chat_id="oc_chat",
            )

        # 据卡片 clarification_id 取轮（不信回调直传 session_id）+ 工作流入口 engine（带 node_execution_id）
        mock_build.assert_called_once_with(node_execution_id="ne-1")
        helper.assert_awaited_once()
        call_args = helper.await_args
        assert call_args.args[0] == "c1"
        assert call_args.args[1] == [
            {"question_id": "qa", "selected": "A", "freeform_text": ""},
            {"question_id": "qb", "selected": ["X", "Y"], "freeform_text": ""},
        ]
        assert call_args.kwargs["engine"] is engine
        # approve_node 重调度 + 置灰卡
        assert ne.approval_data["clarification_answered"] is True
        assert ne.approval_data["clarification_id"] == "c1"
        wf_engine.approve_node.assert_awaited_once()
        mock_card.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_waiting_is_idempotent(self) -> None:
        from feishu.callbacks.plan_clarify_callback import _do_clarify_answer_async

        helper = AsyncMock()
        wf_engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=None)),
            patch(f"{_MOD}._acollect_round_questions", AsyncMock()) as mock_collect,
            patch(f"{_MOD}.aanswer_round_and_resume", helper),
            patch(f"{_MOD}.WorkflowEngine", return_value=wf_engine),
        ):
            await _do_clarify_answer_async(
                execution_id="e1",
                node_id="n1",
                clarification_id="c1",
                question_count=2,
                data={"q0": "A"},
                responder_id="ou_user",
                chat_id="oc_chat",
            )

        mock_collect.assert_not_awaited()
        helper.assert_not_awaited()
        wf_engine.approve_node.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_helper_failsoft_no_approve(self) -> None:
        from feishu.callbacks.plan_clarify_callback import _do_clarify_answer_async

        ne = _waiting_node()
        wf_engine = AsyncMock()
        helper = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._acollect_round_questions", AsyncMock(return_value=_QUESTIONS)),
            patch(f"{_MOD}.build_orchestration_engine", return_value=MagicMock()),
            patch(f"{_MOD}.aanswer_round_and_resume", helper),
            patch(f"{_MOD}.WorkflowEngine", return_value=wf_engine),
        ):
            # helper 抛异常 → fail-soft（不冒泡）
            await _do_clarify_answer_async(
                execution_id="e1",
                node_id="n1",
                clarification_id="c1",
                question_count=2,
                data={"q0": "A"},
                responder_id="ou_user",
                chat_id="oc_chat",
            )

        helper.assert_awaited_once()
        wf_engine.approve_node.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_questions_short_circuits(self) -> None:
        from feishu.callbacks.plan_clarify_callback import _do_clarify_answer_async

        ne = _waiting_node()
        wf_engine = AsyncMock()
        helper = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._acollect_round_questions", AsyncMock(return_value=[])),
            patch(f"{_MOD}.aanswer_round_and_resume", helper),
            patch(f"{_MOD}.WorkflowEngine", return_value=wf_engine),
        ):
            await _do_clarify_answer_async(
                execution_id="e1",
                node_id="n1",
                clarification_id="c1",
                question_count=0,
                data={},
                responder_id="ou_user",
                chat_id="oc_chat",
            )

        helper.assert_not_awaited()
        wf_engine.approve_node.assert_not_awaited()
