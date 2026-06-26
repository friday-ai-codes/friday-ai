"""BoardSplitReviewNode 守护测试（Phase 87，BOARD-02，87-04）。

覆盖：
- 节点自动注册（registry 含 board_split_review）+ is_blocking。
- mock（resolve_or_create_group→chat_id、propose_split→proposal、CardKit）→ waiting_event，
  output_data 含 proposal/sources/card_id/round=1。
- resolve_or_create_group 返回 "" → failed + error（断言不发卡）。
- 无输入源 → failed + error。

纯 mock（patch ProjectService/BoardSplitService/FeishuIMService + _resolve_space/_aresolve_project），
ExecutionContext workflow_execution=None 跳过事件订阅落库。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.nodes.base import ExecutionContext
from workflows.nodes.integrations.board_split_review import BoardSplitReviewNode
from workflows.nodes.registry import NodeRegistry

_NODE_MOD = "workflows.nodes.integrations.board_split_review"

_PROPOSAL = {
    "modules": [{"name": "M", "features": [{"name": "A1"}, {"name": "A2"}]}],
    "features_flat": [
        {"module": "M", "name": "A1", "description": "d1", "acceptance": []},
        {"module": "M", "name": "A2", "description": "d2", "acceptance": []},
    ],
    "degraded": False,
    "chunk_count": 1,
}


def _ctx(config: dict) -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-1",
        node_id="node-1",
        node_config=config,
        input_data={},
        workflow_context={},
        previous_outputs={},
        workflow_execution=None,
    )


def _mock_im_service() -> MagicMock:
    im = MagicMock()
    im.create_card_entity = AsyncMock(return_value="card-1")
    im.send_card_entity = AsyncMock(return_value="msg-1")
    im.stream_card_content = AsyncMock(return_value=True)
    im.settle_card_stream = AsyncMock(return_value=True)
    im.send_card = AsyncMock(return_value="msg-fallback")
    return im


def test_node_auto_registered() -> None:
    node_cls = NodeRegistry.get("board_split_review")
    assert node_cls is BoardSplitReviewNode
    assert node_cls.is_blocking is True
    assert node_cls.execution_mode == "server_local"
    out_handles = {p.name for p in node_cls.outputs}
    assert out_handles == {"created", "refining", "timeout", "error"}


@pytest.mark.asyncio
async def test_no_input_source_fails() -> None:
    node = BoardSplitReviewNode()
    result = await node.execute(_ctx({}))
    assert result.status == "failed"
    assert result.next_handle == "error"


@pytest.mark.asyncio
async def test_waiting_event_with_proposal_persisted() -> None:
    node = BoardSplitReviewNode()
    proj_svc = MagicMock()
    proj_svc.resolve_or_create_group = AsyncMock(return_value="oc_group")
    split_svc = MagicMock()
    split_svc.propose_split = AsyncMock(return_value=_PROPOSAL)
    im = _mock_im_service()

    with (
        patch(f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))),
        patch(f"{_NODE_MOD}.ProjectService", return_value=proj_svc),
        patch(f"{_NODE_MOD}.BoardSplitService", return_value=split_svc),
        patch(f"{_NODE_MOD}.FeishuIMService.create", AsyncMock(return_value=im)),
    ):
        result = await node.execute(_ctx({"feature_list_text": "功能点A1\n功能点A2"}))

    assert result.status == "waiting_event"
    out = result.output
    assert out["proposal"] == _PROPOSAL
    assert out["card_id"] == "card-1"
    assert out["round"] == 1
    assert "sources" in out
    proj_svc.resolve_or_create_group.assert_awaited_once()
    split_svc.propose_split.assert_awaited_once()
    # CardKit 流式序列被调用
    im.create_card_entity.assert_awaited_once()
    im.stream_card_content.assert_awaited_once()
    im.settle_card_stream.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_group_fails_without_sending_card() -> None:
    node = BoardSplitReviewNode()
    proj_svc = MagicMock()
    proj_svc.resolve_or_create_group = AsyncMock(return_value="")
    split_svc = MagicMock()
    split_svc.propose_split = AsyncMock(return_value=_PROPOSAL)
    im = _mock_im_service()

    with (
        patch(f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))),
        patch(f"{_NODE_MOD}.ProjectService", return_value=proj_svc),
        patch(f"{_NODE_MOD}.BoardSplitService", return_value=split_svc),
        patch(f"{_NODE_MOD}.FeishuIMService.create", AsyncMock(return_value=im)),
    ):
        result = await node.execute(_ctx({"feature_list_text": "x"}))

    assert result.status == "failed"
    assert result.next_handle == "error"
    im.create_card_entity.assert_not_awaited()
    split_svc.propose_split.assert_not_awaited()
