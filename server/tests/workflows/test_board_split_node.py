"""BoardSplitNode 守护测试（Phase 87，BOARD-01，87-03）。

覆盖：节点自动注册（registry 含 board_split）、端到端 mock（propose 返回 N feature +
create_boards 返回 created → output.created 长度==N、completed）、无输入源 → failed+error。
纯 mock（patch BoardSplitService + _resolve_project），不需 DB。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.nodes.base import ExecutionContext
from workflows.nodes.integrations.board_split import BoardSplitNode
from workflows.nodes.registry import NodeRegistry

_NODE_MOD = "workflows.nodes.integrations.board_split"

_PROPOSAL = {
    "modules": [],
    "features_flat": [
        {"module": "M", "name": "A1", "description": "d1", "acceptance": []},
        {"module": "M", "name": "A2", "description": "d2", "acceptance": []},
    ],
    "degraded": False,
    "chunk_count": 1,
}

_CREATE_RESULT = {
    "created": [
        {"feature": "A1", "work_item_id": 1000, "linked": True},
        {"feature": "A2", "work_item_id": 1001, "linked": True},
    ],
    "failures": [],
    "degraded_parent_child": False,
    "hint": None,
    "feature_count": 2,
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


def test_node_auto_registered() -> None:
    node_cls = NodeRegistry.get("board_split")
    assert node_cls is BoardSplitNode
    assert node_cls.category.value == "integration"
    assert node_cls.execution_mode == "server_local"
    out_handles = {p.name for p in node_cls.outputs}
    assert out_handles == {"default", "error"}


@pytest.mark.asyncio
async def test_no_input_source_fails() -> None:
    node = BoardSplitNode()
    result = await node.execute(_ctx({}))
    assert result.status == "failed"
    assert result.next_handle == "error"


@pytest.mark.asyncio
async def test_end_to_end_creates_boards() -> None:
    node = BoardSplitNode()
    svc = MagicMock()
    svc.propose_split = AsyncMock(return_value=_PROPOSAL)
    svc.create_boards = AsyncMock(return_value=_CREATE_RESULT)
    with (
        patch(f"{_NODE_MOD}._resolve_project", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}.BoardSplitService", return_value=svc),
    ):
        result = await node.execute(_ctx({"feature_list_text": "功能点A1\n功能点A2"}))

    assert result.status == "completed"
    assert result.next_handle == "default"
    assert len(result.output["created"]) == 2
    assert result.output["feature_count"] == 2
    assert result.output["degraded_parent_child"] is False
    svc.propose_split.assert_awaited_once()
    svc.create_boards.assert_awaited_once()


@pytest.mark.asyncio
async def test_space_not_found_fails() -> None:
    node = BoardSplitNode()
    with patch(f"{_NODE_MOD}._resolve_project", AsyncMock(return_value=None)):
        result = await node.execute(_ctx({"feature_list_text": "x"}))
    assert result.status == "failed"
    assert result.next_handle == "error"


@pytest.mark.asyncio
async def test_service_exception_routes_error() -> None:
    node = BoardSplitNode()
    svc = MagicMock()
    svc.propose_split = AsyncMock(side_effect=RuntimeError("extract boom"))
    with (
        patch(f"{_NODE_MOD}._resolve_project", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}.BoardSplitService", return_value=svc),
    ):
        result = await node.execute(_ctx({"feature_list_text": "x"}))
    assert result.status == "failed"
    assert result.next_handle == "error"
