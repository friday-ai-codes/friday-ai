"""业务↔仓库关联卡片回调状态机测试（Phase 88，REPO-02，88-05）。

覆盖（逐字镜像 board_split_callback 测试范式，纯 mock 无 DB/网络）：
- 同步入口：confirm / refine / reconfirm / accept_mismatch 提取 ids + 后台调度 + 即时确认卡；
  缺 ids → None；refine 缺输入 → 不调度；未知动作 → None。
- confirm 后台：confirm_repos + dispatch_verify(node_execution_id=...) 派深验 + stage=verifying
  + 保持 waiting（approve_node 未被调）；非 waiting → 幂等忽略。
- refine 后台：refine(extra_instruction=输入) + round 递增 + 重发卡 + 保持 waiting。
- reconfirm 后台：reopen_candidates 回 proposed + stage=clarify + 重发卡 + 保持 waiting。
- accept_mismatch 后台：accept_mismatch 置 verified + approve_node 恢复。
- 回调重活异常 → fail-soft（不冒泡）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feishu.callbacks.repo_association_callback import handle_repo_assoc_action
from feishu.views import CardCallback

_MOD = "feishu.callbacks.repo_association_callback"
_SVC = f"{_MOD}.RepoAssociationService"

_PROPOSAL = {
    "candidates": [
        {"repo_id": "r1", "repo_name": "repo-1", "confidence": "high", "score": 0.9},
        {"repo_id": "r2", "repo_name": "repo-2", "confidence": "medium", "score": 0.7},
    ],
    "router_version": "v2",
}


def _make_callback(action_value: dict[str, Any]) -> CardCallback:
    return CardCallback(
        action_value=action_value,
        user_open_id="ou_user",
        message_id="msg",
        chat_id="oc_chat",
        tenant_key="t",
    )


def _waiting_node(output: dict[str, Any] | None = None) -> MagicMock:
    ne = MagicMock()
    ne.id = "ne-1"
    ne.output_data = output or {
        "proposal": _PROPOSAL,
        "sources": {"feature_list": {"features_flat": [{"name": "A"}]}},
        "chat_id": "oc_chat",
        "round": 1,
        "stage": "clarify",
    }
    ne.approval_data = {}
    ne.asave = AsyncMock()
    we = MagicMock()
    we.status = "suspended"
    we.asave = AsyncMock()
    ne.workflow_execution = we
    return ne


def _assoc(repo_id: str, name: str) -> MagicMock:
    a = MagicMock()
    a.repository_id = repo_id
    a.repository = MagicMock()
    a.repository.name = name
    return a


# ---------------------------------------------------------------------------
# 同步入口
# ---------------------------------------------------------------------------


class TestSyncEntry:
    @patch(f"{_MOD}._run_in_thread")
    def test_confirm_schedules_and_acks(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {
                "action": "repo_assoc_confirm",
                "execution_id": "e1",
                "node_id": "n1",
                "round": 1,
                "repo_ids": ["r1", "r2"],
            }
        )
        result = handle_repo_assoc_action(cb)
        mock_run.assert_called_once()
        assert result is not None
        assert result["header"]["template"] == "grey"

    @patch(f"{_MOD}._run_in_thread")
    def test_refine_schedules_with_input(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {
                "action": "repo_assoc_refine",
                "execution_id": "e1",
                "node_id": "n1",
                "round": 1,
                "refine_input": "只看后端仓",
            }
        )
        result = handle_repo_assoc_action(cb)
        mock_run.assert_called_once()
        assert result is not None

    @patch(f"{_MOD}._run_in_thread")
    def test_refine_without_input_not_scheduled(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "repo_assoc_refine", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_repo_assoc_action(cb)
        mock_run.assert_not_called()
        assert result is not None  # 提示输入的 ack 卡

    @patch(f"{_MOD}._run_in_thread")
    def test_reconfirm_schedules(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "repo_assoc_reconfirm", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_repo_assoc_action(cb)
        mock_run.assert_called_once()
        assert result is not None

    @patch(f"{_MOD}._run_in_thread")
    def test_accept_schedules(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {
                "action": "repo_assoc_accept_mismatch",
                "execution_id": "e1",
                "node_id": "n1",
            }
        )
        result = handle_repo_assoc_action(cb)
        mock_run.assert_called_once()
        assert result is not None

    @patch(f"{_MOD}._run_in_thread")
    def test_missing_ids_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback({"action": "repo_assoc_confirm"})
        result = handle_repo_assoc_action(cb)
        assert result is None
        mock_run.assert_not_called()

    @patch(f"{_MOD}._run_in_thread")
    def test_unknown_action_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "repo_assoc_bogus", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_repo_assoc_action(cb)
        assert result is None
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 后台：确认派深验（保持 waiting，绝不 approve）
# ---------------------------------------------------------------------------


class TestConfirmBackground:
    @pytest.mark.asyncio
    async def test_confirm_dispatches_and_keeps_waiting(self) -> None:
        from feishu.callbacks.repo_association_callback import (
            _do_confirm_and_verify_async,
        )

        ne = _waiting_node()
        svc = MagicMock()
        confirmed = [_assoc("r1", "repo-1"), _assoc("r2", "repo-2")]
        svc.confirm_repos = AsyncMock(return_value=confirmed)
        svc.dispatch_verify = AsyncMock(
            return_value={"dispatched": ["r1", "r2"], "failed": [], "runner_offline": False}
        )
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aresolve_project", AsyncMock(return_value=MagicMock())),
            patch(_SVC, return_value=svc),
            patch(f"{_MOD}._send_card_best_effort", AsyncMock()) as mock_card,
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_confirm_and_verify_async(
                execution_id="e1",
                node_id="n1",
                repo_ids=["r1", "r2"],
                responder_id="ou_user",
            )

        svc.confirm_repos.assert_awaited_once()
        svc.dispatch_verify.assert_awaited_once()
        # dispatch 透传 node_execution_id（容器回调续驱本节点）
        assert svc.dispatch_verify.await_args.kwargs["node_execution_id"] == "ne-1"
        # stage=verifying + confirmed_repo_ids 持久化，保持 waiting（绝不 approve）
        assert ne.output_data["stage"] == "verifying"
        assert ne.output_data["confirmed_repo_ids"] == ["r1", "r2"]
        mock_card.assert_awaited_once()
        engine.approve_node.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_confirm_not_waiting_is_idempotent(self) -> None:
        from feishu.callbacks.repo_association_callback import (
            _do_confirm_and_verify_async,
        )

        svc = MagicMock()
        svc.confirm_repos = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=None)),
            patch(_SVC, return_value=svc),
        ):
            await _do_confirm_and_verify_async(
                execution_id="e1",
                node_id="n1",
                repo_ids=["r1"],
                responder_id="ou_user",
            )

        svc.confirm_repos.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_confirm_failsoft_swallows_error(self) -> None:
        from feishu.callbacks.repo_association_callback import (
            _do_confirm_and_verify_async,
        )

        svc = MagicMock()
        svc.confirm_repos = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=_waiting_node())),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aresolve_project", AsyncMock(return_value=MagicMock())),
            patch(_SVC, return_value=svc),
        ):
            # 重活异常不冒泡（fail-soft）
            await _do_confirm_and_verify_async(
                execution_id="e1",
                node_id="n1",
                repo_ids=["r1"],
                responder_id="ou_user",
            )


# ---------------------------------------------------------------------------
# 后台：多轮重 route（保持 waiting）
# ---------------------------------------------------------------------------


class TestRefineBackground:
    @pytest.mark.asyncio
    async def test_refine_reroute_increments_round_keeps_waiting(self) -> None:
        from feishu.callbacks.repo_association_callback import _do_refine_async

        ne = _waiting_node()
        svc = MagicMock()
        new_proposal = {**_PROPOSAL, "router_version": "v2"}
        svc.refine = AsyncMock(return_value=new_proposal)
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aresolve_project", AsyncMock(return_value=MagicMock())),
            patch(_SVC, return_value=svc),
            patch(f"{_MOD}._resend_streaming_card", AsyncMock()) as mock_resend,
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_refine_async(
                execution_id="e1",
                node_id="n1",
                refine_input="只看后端仓",
                responder_id="ou_user",
            )

        svc.refine.assert_awaited_once()
        assert svc.refine.await_args.kwargs["extra_instruction"] == "只看后端仓"
        assert ne.output_data["round"] == 2
        assert ne.output_data["proposal"] == new_proposal
        mock_resend.assert_awaited_once()
        engine.approve_node.assert_not_awaited()


# ---------------------------------------------------------------------------
# 后台：回退重确认（回 clarify，保持 waiting）
# ---------------------------------------------------------------------------


class TestReconfirmBackground:
    @pytest.mark.asyncio
    async def test_mismatch_rollback_reopens_keeps_waiting(self) -> None:
        from feishu.callbacks.repo_association_callback import _do_reconfirm_async

        ne = _waiting_node(
            {
                "proposal": _PROPOSAL,
                "chat_id": "oc_chat",
                "round": 1,
                "stage": "reconfirm",
                "confirmed_repo_ids": ["r1", "r2"],
            }
        )
        svc = MagicMock()
        svc.reopen_candidates = AsyncMock(return_value=True)
        engine = AsyncMock()
        associations = [_assoc("r1", "repo-1"), _assoc("r2", "repo-2")]

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aresolve_project", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aload_associations", AsyncMock(return_value=associations)),
            patch(_SVC, return_value=svc),
            patch(f"{_MOD}._resend_streaming_card", AsyncMock()) as mock_resend,
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_reconfirm_async(
                execution_id="e1", node_id="n1", responder_id="ou_user"
            )

        assert svc.reopen_candidates.await_count == 2
        assert ne.output_data["stage"] == "clarify"
        assert "confirmed_repo_ids" not in ne.output_data
        mock_resend.assert_awaited_once()
        engine.approve_node.assert_not_awaited()


# ---------------------------------------------------------------------------
# 后台：接受 mismatch（置 verified + approve_node 恢复）
# ---------------------------------------------------------------------------


class TestAcceptBackground:
    @pytest.mark.asyncio
    async def test_accept_mismatch_sets_verified_and_approves(self) -> None:
        from feishu.callbacks.repo_association_callback import _do_accept_async

        ne = _waiting_node(
            {
                "chat_id": "oc_chat",
                "round": 1,
                "stage": "reconfirm",
                "confirmed_repo_ids": ["r1", "r2"],
                "verdicts": {"fit": ["r1"], "mismatch": ["r2"], "unknown": []},
            }
        )
        svc = MagicMock()
        svc.accept_mismatch = AsyncMock(return_value=True)
        engine = AsyncMock()
        associations = [_assoc("r1", "repo-1"), _assoc("r2", "repo-2")]

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aresolve_project", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aload_associations", AsyncMock(return_value=associations)),
            patch(_SVC, return_value=svc),
            patch(f"{_MOD}._send_card_best_effort", AsyncMock()) as mock_card,
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_accept_async(
                execution_id="e1", node_id="n1", responder_id="ou_user"
            )

        assert svc.accept_mismatch.await_count == 2
        # 恢复携 verified 仓 + verdict
        assert ne.approval_data["verified_repos"] == ["repo-1", "repo-2"]
        assert ne.approval_data["accepted_mismatch"] is True
        mock_card.assert_awaited_once()
        engine.approve_node.assert_awaited_once()
