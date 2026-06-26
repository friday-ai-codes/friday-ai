"""分支确认卡片回调状态机测试（Phase 89 PLAN-04，建分支绑项目 HITL）。

覆盖（逐字镜像 repo_association_callback 测试范式，纯 mock 无 DB/网络）：
- 同步入口：apply / edit / cancel 提取 ids + 后台调度 + 即时确认卡；缺 ids → None；
  edit 缺 type → 不调度；未知动作 → None。
- apply 后台：provision_and_bind 被调 + approve_node 恢复（携结果）。
- edit 后台：按新 type 重拼分支名 + round+1 + 保持 waiting（approve_node 未被调）。
- cancel 后台：不建分支（provision 未被调）+ approve_node（携 cancelled）。
- 回调重活异常 → fail-soft（不冒泡）。
- 前缀 ``branch_confirm_`` 唯一 + urls.py 已 import。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feishu.callbacks.branch_confirm_callback import handle_branch_confirm_action
from feishu.views import CardCallback

_MOD = "feishu.callbacks.branch_confirm_callback"
_PROVISION = "initiatives.services.branch_provision_service.BranchProvisionService"

_BRANCH_PLAN = [
    {
        "repository_id": "r1",
        "repository_name": "repo-1",
        "branch_name": "feat/260610.m-123.高三提分专项-v1.0",
        "change_type": "feat",
        "yymmdd": "260610",
        "tracking_id": "123",
        "project_name": "高三提分专项",
        "version": "v1.0",
    }
]


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
        "branch_plan": _BRANCH_PLAN,
        "chat_id": "oc_chat",
        "round": 1,
        "feishu_board_id": "board-9",
    }
    ne.approval_data = {}
    ne.asave = AsyncMock()
    we = MagicMock()
    we.status = "suspended"
    we.asave = AsyncMock()
    ne.workflow_execution = we
    return ne


class TestSyncEntry:
    @patch(f"{_MOD}._run_in_thread")
    def test_apply_schedules_and_acks(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "branch_confirm_apply", "execution_id": "e1", "node_id": "n1", "round": 1}
        )
        result = handle_branch_confirm_action(cb)
        mock_run.assert_called_once()
        assert result is not None
        assert result["header"]["template"] == "grey"

    @patch(f"{_MOD}._run_in_thread")
    def test_edit_schedules_with_type(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {
                "action": "branch_confirm_edit",
                "execution_id": "e1",
                "node_id": "n1",
                "type_input": "fix",
            }
        )
        result = handle_branch_confirm_action(cb)
        mock_run.assert_called_once()
        assert result is not None

    @patch(f"{_MOD}._run_in_thread")
    def test_edit_without_type_not_scheduled(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "branch_confirm_edit", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_branch_confirm_action(cb)
        mock_run.assert_not_called()
        assert result is not None

    @patch(f"{_MOD}._run_in_thread")
    def test_cancel_schedules(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "branch_confirm_cancel", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_branch_confirm_action(cb)
        mock_run.assert_called_once()
        assert result is not None

    @patch(f"{_MOD}._run_in_thread")
    def test_missing_ids_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback({"action": "branch_confirm_apply"})
        result = handle_branch_confirm_action(cb)
        assert result is None
        mock_run.assert_not_called()

    @patch(f"{_MOD}._run_in_thread")
    def test_unknown_action_returns_none(self, mock_run: MagicMock) -> None:
        cb = _make_callback(
            {"action": "branch_confirm_bogus", "execution_id": "e1", "node_id": "n1"}
        )
        result = handle_branch_confirm_action(cb)
        assert result is None
        mock_run.assert_not_called()


class TestApplyBackground:
    @pytest.mark.asyncio
    async def test_apply_provisions_and_approves(self) -> None:
        from feishu.callbacks.branch_confirm_callback import _do_apply_async

        ne = _waiting_node()
        svc = MagicMock()
        svc.provision_and_bind = AsyncMock(
            return_value={
                "succeeded": [{"repository_id": "r1"}],
                "failed": [],
                "all_succeeded": True,
            }
        )
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aresolve_project", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aload_repositories", AsyncMock(return_value=[MagicMock()])),
            patch(_PROVISION, return_value=svc),
            patch(f"{_MOD}._send_card_best_effort", AsyncMock()) as mock_card,
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_apply_async(execution_id="e1", node_id="n1", responder_id="ou_user")

        svc.provision_and_bind.assert_awaited_once()
        assert svc.provision_and_bind.await_args.kwargs["feishu_board_id"] == "board-9"
        assert ne.approval_data["all_succeeded"] is True
        mock_card.assert_awaited_once()
        engine.approve_node.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_apply_not_waiting_is_idempotent(self) -> None:
        from feishu.callbacks.branch_confirm_callback import _do_apply_async

        svc = MagicMock()
        svc.provision_and_bind = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=None)),
            patch(_PROVISION, return_value=svc),
        ):
            await _do_apply_async(execution_id="e1", node_id="n1", responder_id="ou_user")

        svc.provision_and_bind.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_apply_failsoft_swallows_error(self) -> None:
        from feishu.callbacks.branch_confirm_callback import _do_apply_async

        svc = MagicMock()
        svc.provision_and_bind = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=_waiting_node())),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aresolve_project", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._aload_repositories", AsyncMock(return_value=[MagicMock()])),
            patch(_PROVISION, return_value=svc),
        ):
            # 重活异常不冒泡（fail-soft）
            await _do_apply_async(execution_id="e1", node_id="n1", responder_id="ou_user")


class TestEditBackground:
    @pytest.mark.asyncio
    async def test_edit_rebuilds_with_new_type_keeps_waiting(self) -> None:
        from feishu.callbacks.branch_confirm_callback import _do_edit_async

        ne = _waiting_node()
        engine = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._send_card_best_effort", AsyncMock()) as mock_card,
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_edit_async(
                execution_id="e1", node_id="n1", type_input="fix", responder_id="ou_user"
            )

        assert ne.output_data["round"] == 2
        new_branch = ne.output_data["branch_plan"][0]["branch_name"]
        assert new_branch == "fix/260610.m-123.高三提分专项-v1.0"
        mock_card.assert_awaited_once()
        engine.approve_node.assert_not_awaited()


class TestCancelBackground:
    @pytest.mark.asyncio
    async def test_cancel_does_not_provision_and_approves(self) -> None:
        from feishu.callbacks.branch_confirm_callback import _do_cancel_async

        ne = _waiting_node()
        engine = AsyncMock()
        svc = MagicMock()
        svc.provision_and_bind = AsyncMock()

        with (
            patch(f"{_MOD}._aget_waiting_node", AsyncMock(return_value=ne)),
            patch(f"{_MOD}._resolve_space", AsyncMock(return_value=MagicMock())),
            patch(f"{_MOD}._send_card_best_effort", AsyncMock()) as mock_card,
            patch(_PROVISION, return_value=svc),
            patch(f"{_MOD}.WorkflowEngine", return_value=engine),
        ):
            await _do_cancel_async(execution_id="e1", node_id="n1", responder_id="ou_user")

        svc.provision_and_bind.assert_not_awaited()
        assert ne.approval_data["cancelled"] is True
        mock_card.assert_awaited_once()
        engine.approve_node.assert_awaited_once()


class TestPrefixWiring:
    def test_prefix_unique_and_urls_imported(self) -> None:
        feishu_dir = Path(__file__).resolve().parents[2] / "feishu"
        # register_card_callback("branch_confirm_") 前缀唯一，不撞其他回调注册。
        offenders: list[str] = []
        for path in (feishu_dir / "callbacks").glob("*.py"):
            if path.name == "branch_confirm_callback.py":
                continue
            if 'register_card_callback("branch_confirm_' in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        assert not offenders, f"前缀撞车: {offenders}"

        urls_text = (feishu_dir / "urls.py").read_text(encoding="utf-8")
        assert "branch_confirm_callback" in urls_text
