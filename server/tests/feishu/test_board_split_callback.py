"""看板拆分卡片回调测试（Phase 87，BOARD-02，87-04）。

覆盖：
- 同步入口：board_split_start / board_split_refine 提取 ids + 后台调度 + 即时确认卡；
  缺 ids → None；refine 缺输入 → 不调度。
- board_split_start 后台：create_boards 一次 + 发 done 卡 + approve_node 恢复；
  非 waiting → 幂等忽略（不建看板）。
- board_split_refine 后台：propose_split(extra_instruction=输入) + round 递增 + 重发卡 +
  保持 waiting（approve_node 未被调）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feishu.callbacks.board_split_callback import handle_board_split_action
from feishu.views import CardCallback

_MOD = "feishu.callbacks.board_split_callback"
_SPLIT_SVC = "initiatives.services.board_split_service.BoardSplitService"

_PROPOSAL = {
    "modules": [],
    "features_flat": [{"module": "M", "name": "A1", "description": "d", "acceptance": []}],
    "degraded": False,
    "chunk_count": 1,
}

_CREATE_RESULT = {
    "created": [{"feature": "A1", "work_item_id": 1000, "linked": True}],
    "failures": [],
    "degraded_parent_child": False,
    "hint": None,
    "feature_count": 1,
}


def _make_callback(action_value: dict[str, Any]) -> CardCallback:
    return CardCallback(
        action_value=action_value,
        user_open_id="ou_user",
        message_id="msg",
        chat_id="oc_chat",
        tenant_key="t",
    )


# ---------------------------------------------------------------------------
# 同步入口
# ---------------------------------------------------------------------------


class TestSyncEntry:
    @patch(f"{_MOD}._run_in_thread")
    def test_start_schedules_and_acks(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "board_split_start", "execution_id": "e1", "node_id": "n1", "round": 1}
        )
        result = handle_board_split_action(cb)
        mock_run.assert_called_once()
        assert result is not None
        assert result["header"]["template"] == "grey"

    @patch(f"{_MOD}._run_in_thread")
    def test_refine_schedules_with_input(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {
                "action": "board_split_refine",
                "execution_id": "e1",
                "node_id": "n1",
                "round": 1,
                "refine_input": "按端拆分",
            }
        )
        result = handle_board_split_action(cb)
        mock_run.assert_called_once()
        assert result is not None

    @patch(f"{_MOD}._run_in_thread")
    def test_refine_without_input_not_scheduled(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "board_split_refine", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_board_split_action(cb)
        mock_run.assert_not_called()
        assert result is not None  # 提示输入的 ack 卡

    @patch(f"{_MOD}._run_in_thread")
    def test_missing_ids_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback({"action": "board_split_start"})
        result = handle_board_split_action(cb)
        assert result is None
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 后台：开始创建
# ---------------------------------------------------------------------------


def _waiting_node() -> MagicMock:
    ne = MagicMock()
    ne.output_data = {
        "proposal": _PROPOSAL,
        "sources": {"feishu_url": "", "pasted_text": "raw", "uploaded_text": ""},
        "work_item_type": "story",
        "chat_id": "oc_chat",
        "round": 1,
    }
    ne.approval_data = {}
    ne.asave = AsyncMock()
    we = MagicMock()
    we.status = "suspended"
    we.asave = AsyncMock()
    ne.workflow_execution = we
    return ne


class TestStartBackground:
    @pytest.mark.asyncio
    async def test_creates_boards_and_resumes(self) -> None:
        from feishu.callbacks.board_split_callback import _do_board_split_start_async

        ne = _waiting_node()
        split_svc = MagicMock()
        split_svc.create_boards = AsyncMock(return_value=_CREATE_RESULT)
        im_client = AsyncMock()
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(_SPLIT_SVC, return_value=split_svc),
            patch(f"{_MOD}.create_feishu_im_client_for_project", AsyncMock(return_value=im_client)),
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_board_split_start_async(
                execution_id="e1", node_id="n1", responder_id="ou_user"
            )

        split_svc.create_boards.assert_awaited_once()
        engine.approve_node.assert_awaited_once()
        im_client.send_card.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_waiting_is_idempotent(self) -> None:
        from feishu.callbacks.board_split_callback import _do_board_split_start_async

        split_svc = MagicMock()
        split_svc.create_boards = AsyncMock()
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=None)),
            patch(_SPLIT_SVC, return_value=split_svc),
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_board_split_start_async(
                execution_id="e1", node_id="n1", responder_id="ou_user"
            )

        split_svc.create_boards.assert_not_awaited()
        engine.approve_node.assert_not_awaited()


# ---------------------------------------------------------------------------
# 后台：多轮重拆
# ---------------------------------------------------------------------------


class TestRefineBackground:
    @pytest.mark.asyncio
    async def test_resplit_increments_round_keeps_waiting(self) -> None:
        from feishu.callbacks.board_split_callback import _do_board_split_refine_async

        ne = _waiting_node()
        split_svc = MagicMock()
        new_proposal = {**_PROPOSAL, "chunk_count": 2}
        split_svc.propose_split = AsyncMock(return_value=new_proposal)
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(_SPLIT_SVC, return_value=split_svc),
            patch(f"{_MOD}._resend_streaming_card", AsyncMock(return_value=None)) as mock_resend,
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_board_split_refine_async(
                execution_id="e1",
                node_id="n1",
                refine_input="按端拆分",
                responder_id="ou_user",
            )

        # propose_split 带 extra_instruction
        split_svc.propose_split.assert_awaited_once()
        assert split_svc.propose_split.await_args.kwargs["extra_instruction"] == "按端拆分"
        # round 递增 + 新 proposal
        assert ne.output_data["round"] == 2
        assert ne.output_data["proposal"] == new_proposal
        # 重发卡 + 保持 waiting（不 approve）
        mock_resend.assert_awaited_once()
        engine.approve_node.assert_not_awaited()
