"""方案修订回路卡片回调状态机测试（Phase 89，PLAN-02，89-02）。

覆盖（逐字镜像 repo_association_callback 测试范式，纯 mock 无 DB/网络）：
- 同步入口：confirm / adjust / cancel 后台调度 + 即时确认卡；adjust 缺输入 → 不调度但 ack；
  缺 ids → None；未知动作 → None。
- confirm 后台：apply_supplement_revision 被调 + approve_node 恢复；非 waiting → 幂等忽略；
  service 抛 → fail-soft（不冒泡，approve 未被调）。
- adjust 后台：detect_revision 重研判 + round+1 + 保持 waiting（approve 未被调）。
- cancel 后台：不修订（apply 未被调）+ approve_node 恢复。
- 前缀 ``plan_revision_`` 已注册且唯一（不撞既有 plan_revise/repo_assoc_/board_split_）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feishu.callbacks.plan_revision_callback import handle_plan_revision_action
from feishu.views import CardCallback

_MOD = "feishu.callbacks.plan_revision_callback"
_SVC = f"{_MOD}.PlanDeepenService"

_REVISION = {
    "add_repos": ["r3"],
    "remove_repos": ["r2"],
    "change_repos": ["r1"],
    "plan_delta_summary": "新增缓存仓",
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
        "revision": _REVISION,
        "observed_change_text": "发现还要改缓存仓",
        "chat_id": "oc_chat",
        "round": 1,
        "stage": "revising",
        "plan_id": "plan-1",
    }
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

    assert "plan_revision_" in _card_callback_handlers
    # plan_revision_* 不会被既有 plan_revise（plan_callback）抢路由
    assert not "plan_revision_confirm".startswith("plan_revise_")
    # 与既有前缀互不为前缀
    for prefix in _card_callback_handlers:
        if prefix == "plan_revision_":
            continue
        assert not "plan_revision_confirm".startswith(prefix), prefix


# ---------------------------------------------------------------------------
# 同步入口
# ---------------------------------------------------------------------------


class TestSyncEntry:
    @patch(f"{_MOD}._run_in_thread")
    def test_confirm_schedules_and_acks(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "plan_revision_confirm", "execution_id": "e1", "node_id": "n1", "round": 1}
        )
        result = handle_plan_revision_action(cb)
        mock_run.assert_called_once()
        assert result is not None
        assert result["header"]["template"] == "grey"

    @patch(f"{_MOD}._run_in_thread")
    def test_adjust_schedules_with_input(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {
                "action": "plan_revision_adjust",
                "execution_id": "e1",
                "node_id": "n1",
                "adjust_input": "还要改网关仓",
            }
        )
        result = handle_plan_revision_action(cb)
        mock_run.assert_called_once()
        assert result is not None

    @patch(f"{_MOD}._run_in_thread")
    def test_adjust_without_input_not_scheduled(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "plan_revision_adjust", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_plan_revision_action(cb)
        mock_run.assert_not_called()
        assert result is not None  # 提示输入的 ack 卡

    @patch(f"{_MOD}._run_in_thread")
    def test_cancel_schedules(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "plan_revision_cancel", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_plan_revision_action(cb)
        mock_run.assert_called_once()
        assert result is not None

    @patch(f"{_MOD}._run_in_thread")
    def test_missing_ids_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback({"action": "plan_revision_confirm"})
        result = handle_plan_revision_action(cb)
        assert result is None
        mock_run.assert_not_called()

    @patch(f"{_MOD}._run_in_thread")
    def test_unknown_action_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "plan_revision_bogus", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_plan_revision_action(cb)
        assert result is None
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 后台：确认补充修订（apply + approve_node 恢复）
# ---------------------------------------------------------------------------


class TestConfirmBackground:
    @pytest.mark.asyncio
    async def test_confirm_applies_revision_and_approves(self) -> None:
        from feishu.callbacks.plan_revision_callback import _do_revise_confirm_async

        ne = _waiting_node()
        svc = MagicMock()
        svc.apply_supplement_revision = AsyncMock(
            return_value=MagicMock(version=2, id="nv")
        )
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aresolve_project", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aresolve_plan", AsyncMock(return_value=MagicMock())),
            patch(_SVC, return_value=svc),
            patch(f"{_MOD}._send_card_best_effort", AsyncMock()) as mock_card,
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_revise_confirm_async(
                execution_id="e1", node_id="n1", responder_id="ou_user"
            )

        svc.apply_supplement_revision.assert_awaited_once()
        assert svc.apply_supplement_revision.await_args.kwargs["revision"] == _REVISION
        assert ne.approval_data["revision_applied"] is True
        mock_card.assert_awaited_once()
        engine.approve_node.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_confirm_not_waiting_is_idempotent(self) -> None:
        from feishu.callbacks.plan_revision_callback import _do_revise_confirm_async

        svc = MagicMock()
        svc.apply_supplement_revision = AsyncMock()
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=None)),
            patch(_SVC, return_value=svc),
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_revise_confirm_async(
                execution_id="e1", node_id="n1", responder_id="ou_user"
            )

        svc.apply_supplement_revision.assert_not_awaited()
        engine.approve_node.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_confirm_failsoft_no_approve(self) -> None:
        from feishu.callbacks.plan_revision_callback import _do_revise_confirm_async

        ne = _waiting_node()
        svc = MagicMock()
        svc.apply_supplement_revision = AsyncMock(side_effect=RuntimeError("boom"))
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aresolve_project", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aresolve_plan", AsyncMock(return_value=MagicMock())),
            patch(_SVC, return_value=svc),
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            # service 抛异常 → fail-soft（不冒泡）
            await _do_revise_confirm_async(
                execution_id="e1", node_id="n1", responder_id="ou_user"
            )

        engine.approve_node.assert_not_awaited()


# ---------------------------------------------------------------------------
# 后台：调整重研判（保持 waiting，round+1）
# ---------------------------------------------------------------------------


class TestAdjustBackground:
    @pytest.mark.asyncio
    async def test_adjust_redetects_increments_round_keeps_waiting(self) -> None:
        from feishu.callbacks.plan_revision_callback import _do_revise_adjust_async

        ne = _waiting_node()
        svc = MagicMock()
        new_rev = {**_REVISION, "plan_delta_summary": "再加网关仓"}
        svc.detect_revision = AsyncMock(return_value=new_rev)
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(_SVC, return_value=svc),
            patch(f"{_MOD}._send_card_best_effort", AsyncMock()) as mock_card,
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_revise_adjust_async(
                execution_id="e1",
                node_id="n1",
                adjust_input="还要改网关仓",
                responder_id="ou_user",
            )

        svc.detect_revision.assert_awaited_once()
        assert "还要改网关仓" in svc.detect_revision.await_args.kwargs["observed_change_text"]
        assert ne.output_data["round"] == 2
        assert ne.output_data["revision"] == new_rev
        mock_card.assert_awaited_once()
        engine.approve_node.assert_not_awaited()


# ---------------------------------------------------------------------------
# 后台：取消修订（不修订 + approve_node 恢复）
# ---------------------------------------------------------------------------


class TestCancelBackground:
    @pytest.mark.asyncio
    async def test_cancel_keeps_plan_and_approves(self) -> None:
        from feishu.callbacks.plan_revision_callback import _do_revise_cancel_async

        ne = _waiting_node()
        svc = MagicMock()
        svc.apply_supplement_revision = AsyncMock()
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(_SVC, return_value=svc),
            patch(f"{_MOD}._send_card_best_effort", AsyncMock()) as mock_card,
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_revise_cancel_async(
                execution_id="e1", node_id="n1", responder_id="ou_user"
            )

        # 不修订（apply 未被调）+ 恢复
        svc.apply_supplement_revision.assert_not_awaited()
        assert ne.approval_data["cancelled"] is True
        mock_card.assert_awaited_once()
        engine.approve_node.assert_awaited_once()
