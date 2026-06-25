"""CreateProjectNode 守护测试（FSPROJ-03）。

覆盖：节点自动注册、happy（经同源 service 建项目）、缺看板引用 → failed+error、
枚举 fail-soft 降级仍 completed、Space 未找到 → failed。纯 mock（patch service + _resolve_space），
不需 DB。另测 is_project_tracking_event 事件识别 gate（零回归命门）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from feishu.views import is_project_tracking_event
from workflows.nodes.base import ExecutionContext
from workflows.nodes.integrations.create_project import CreateProjectNode
from workflows.nodes.registry import NodeRegistry


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
    node_cls = NodeRegistry.get("create_project")
    assert node_cls is CreateProjectNode
    assert node_cls.category.value == "integration"
    assert node_cls.execution_mode == "server_local"
    out_handles = {p.name for p in node_cls.outputs}
    assert out_handles == {"default", "error"}


@pytest.mark.asyncio
async def test_missing_board_ref_fails_with_error_handle() -> None:
    node = CreateProjectNode()
    result = await node.execute(_ctx({"name": "X"}))  # 无 feishu_project_key / board_work_item_id
    assert result.status == "failed"
    assert result.next_handle == "error"


@pytest.mark.asyncio
async def test_invalid_board_work_item_id_fails() -> None:
    node = CreateProjectNode()
    result = await node.execute(
        _ctx({"feishu_project_key": "pk", "board_work_item_id": "abc"})
    )
    assert result.status == "failed"
    assert result.next_handle == "error"


@pytest.mark.asyncio
async def test_space_not_found_fails() -> None:
    node = CreateProjectNode()
    with patch.object(CreateProjectNode, "_resolve_space", AsyncMock(return_value=None)):
        result = await node.execute(
            _ctx({"feishu_project_key": "pk", "board_work_item_id": "123"})
        )
    assert result.status == "failed"
    assert result.next_handle == "error"


@pytest.mark.asyncio
async def test_happy_creates_via_sync_service() -> None:
    node = CreateProjectNode()
    fake_result = {
        "project_id": "pid-1",
        "created": True,
        "degraded": False,
        "warnings": [],
        "members_added": 2,
        "members_unmapped": 0,
        "work_items_linked": 3,
    }
    with (
        patch.object(
            CreateProjectNode, "_resolve_space", AsyncMock(return_value=MagicMock())
        ),
        patch("initiatives.services.ProjectBoardSyncService") as mock_cls,
    ):
        mock_cls.return_value.sync_from_board = AsyncMock(return_value=fake_result)
        result = await node.execute(
            _ctx(
                {
                    "feishu_project_key": "pk",
                    "board_work_item_id": "123",
                    "board_work_item_type": "project",
                    "name": "我的项目",
                }
            )
        )
    assert result.status == "completed"
    assert result.next_handle == "default"
    assert result.output["project_id"] == "pid-1"
    assert result.output["source"] == "create_project"
    assert result.output["work_items_linked"] == 3


@pytest.mark.asyncio
async def test_enumeration_degraded_still_completed() -> None:
    """枚举 fail-soft 降级（degraded=True）→ 节点仍 completed（项目已建，子项可后续并入）。"""
    node = CreateProjectNode()
    fake_result = {
        "project_id": "pid-2",
        "created": True,
        "degraded": True,
        "warnings": ["enumeration_failed"],
        "members_added": 0,
        "members_unmapped": 0,
        "work_items_linked": 0,
    }
    with (
        patch.object(
            CreateProjectNode, "_resolve_space", AsyncMock(return_value=MagicMock())
        ),
        patch("initiatives.services.ProjectBoardSyncService") as mock_cls,
    ):
        mock_cls.return_value.sync_from_board = AsyncMock(return_value=fake_result)
        result = await node.execute(
            _ctx({"feishu_project_key": "pk", "board_work_item_id": "123"})
        )
    assert result.status == "completed"
    assert result.output["degraded"] is True


# === 飞书事件识别 gate（FSPROJ-02 零回归命门）===


def test_is_project_tracking_event_gate() -> None:
    assert is_project_tracking_event({"work_item_type_key": "project"}) is True
    # 普通工作项事件不误触发（零回归）
    assert is_project_tracking_event({"work_item_type_key": "story"}) is False
    assert is_project_tracking_event({"work_item_type_key": "issue"}) is False
    assert is_project_tracking_event({}) is False
    assert is_project_tracking_event(None) is False
