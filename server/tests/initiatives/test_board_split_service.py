"""BoardSplitService 守护测试（Phase 87，BOARD-01 收口侧，87-03）。

覆盖：
- propose_split 薄委托 FeatureListExtractor。
- create_boards：父子可用 → 每 feature create_work_item + relation_type=1 + 父子 +
  attach_work_item 各一次；created 长度 == feature 数。
- 父子缺失 → degraded_parent_child=True + hint 含「配置中心」，不写父子，仍建看板 + attach。
- 单 feature 建项抛 → 入 failures、其余继续（created+failures==总数，不整体抛）。
- INV-6：board_split_service.py 不旁路 ProjectWorkItemLink.objects.create（经 ProjectService）。
- AI 工具 split_feature_list_to_boards：空间不存在 → ToolResult error；正常 → output.data.created。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from initiatives.models import LinkProvenance
from initiatives.services.board_split_service import BoardSplitService

_SVC_MOD = "initiatives.services.board_split_service"
_FEISHU_FACTORY = "services.feishu.create_feishu_client_for_project"
_WORK_ITEM_SVC = "delivery.services.work_item_service.WorkItemService"

_PROPOSAL = {
    "modules": [{"name": "模块A", "features": []}],
    "features_flat": [
        {"module": "模块A", "name": "功能点A1", "description": "A1 原文", "acceptance": []},
        {"module": "模块A", "name": "功能点A2", "description": "A2 原文", "acceptance": []},
    ],
    "degraded": False,
    "chunk_count": 1,
}


def _space() -> SimpleNamespace:
    return SimpleNamespace(id="s1", feishu_project_key="pk")


def _fake_project() -> SimpleNamespace:
    return SimpleNamespace(id="pid-1", feishu_board_id="999")


def _fake_client(
    *, parent_child: bool, create_side_effect=None, create_return: int = 1000
) -> MagicMock:
    client = MagicMock()
    if create_side_effect is not None:
        client.create_work_item = AsyncMock(side_effect=create_side_effect)
    else:
        client.create_work_item = AsyncMock(return_value=create_return)
    client.add_work_item_relation = AsyncMock(return_value=True)
    client.detect_relation_capability = AsyncMock(
        return_value={"parent_child": parent_child, "project_track": True, "raw": None}
    )
    return client


def _patch_writes(stack: list, attach_mock: AsyncMock) -> None:
    """patch WorkItemService.upsert + ProjectService.attach_work_item（共用）。"""
    wi_instance = MagicMock()
    wi_instance.upsert = AsyncMock(return_value=SimpleNamespace(id="wi-1"))
    proj_instance = MagicMock()
    proj_instance.attach_work_item = attach_mock

    p1 = patch(_WORK_ITEM_SVC, return_value=wi_instance)
    p2 = patch(f"{_SVC_MOD}.ProjectService", return_value=proj_instance)
    stack.append(p1)
    stack.append(p2)
    p1.start()
    p2.start()


# ===========================================================================
# propose_split
# ===========================================================================


async def test_propose_split_delegates_to_extractor() -> None:
    svc = BoardSplitService()
    with (
        patch(
            f"{_SVC_MOD}.FeatureListExtractor",
        ) as mock_extractor_cls,
    ):
        instance = mock_extractor_cls.return_value
        instance.normalize_sources = AsyncMock(return_value="merged raw")
        instance.extract_structure = AsyncMock(return_value=_PROPOSAL)
        result = await svc.propose_split(space=_space(), pasted_text="x")
    assert result == _PROPOSAL
    instance.normalize_sources.assert_awaited_once()
    instance.extract_structure.assert_awaited_once()


# ===========================================================================
# create_boards — 父子可用
# ===========================================================================


async def test_create_boards_parent_child_enabled() -> None:
    svc = BoardSplitService()
    client = _fake_client(parent_child=True)
    attach = AsyncMock(return_value=(MagicMock(), True))
    stack: list = []
    _patch_writes(stack, attach)
    try:
        with (
            patch(_FEISHU_FACTORY, return_value=client),
            patch.object(
                BoardSplitService, "_aresolve_project", AsyncMock(return_value=_fake_project())
            ),
        ):
            result = await svc.create_boards(
                space=_space(), proposal=_PROPOSAL, parent_work_item_id=999
            )
    finally:
        for p in stack:
            p.stop()

    assert len(result["created"]) == 2
    assert result["degraded_parent_child"] is False
    assert result["hint"] is None
    assert client.create_work_item.await_count == 2
    # relation_type=1 + 父子(2)，每 feature 2 次 → 共 4 次
    assert client.add_work_item_relation.await_count == 4
    rel_types = {
        c.kwargs["relation_type"] for c in client.add_work_item_relation.await_args_list
    }
    assert rel_types == {1, 2}
    # attach_work_item 每 feature 一次，provenance=board_derived
    assert attach.await_count == 2
    assert attach.await_args.kwargs["provenance"] == LinkProvenance.BOARD_DERIVED


# ===========================================================================
# create_boards — 父子缺失降级
# ===========================================================================


async def test_create_boards_parent_child_degraded() -> None:
    svc = BoardSplitService()
    client = _fake_client(parent_child=False)
    attach = AsyncMock(return_value=(MagicMock(), True))
    stack: list = []
    _patch_writes(stack, attach)
    try:
        with (
            patch(_FEISHU_FACTORY, return_value=client),
            patch.object(
                BoardSplitService, "_aresolve_project", AsyncMock(return_value=_fake_project())
            ),
        ):
            result = await svc.create_boards(
                space=_space(), proposal=_PROPOSAL, parent_work_item_id=999
            )
    finally:
        for p in stack:
            p.stop()

    assert len(result["created"]) == 2
    assert result["degraded_parent_child"] is True
    assert "配置中心" in (result["hint"] or "")
    # 仍建看板 + attach
    assert client.create_work_item.await_count == 2
    assert attach.await_count == 2
    # 仅 relation_type=1（关联项目跟踪），绝不写父子(2)
    rel_types = {
        c.kwargs["relation_type"] for c in client.add_work_item_relation.await_args_list
    }
    assert rel_types == {1}


# ===========================================================================
# create_boards — 逐条 fail-soft
# ===========================================================================


async def test_create_boards_feature_fail_soft() -> None:
    svc = BoardSplitService()

    call_count = {"n": 0}

    async def _create(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("create failed")
        return 2000

    client = _fake_client(parent_child=True, create_side_effect=_create)
    attach = AsyncMock(return_value=(MagicMock(), True))
    stack: list = []
    _patch_writes(stack, attach)
    try:
        with (
            patch(_FEISHU_FACTORY, return_value=client),
            patch.object(
                BoardSplitService, "_aresolve_project", AsyncMock(return_value=_fake_project())
            ),
        ):
            result = await svc.create_boards(
                space=_space(), proposal=_PROPOSAL, parent_work_item_id=999
            )
    finally:
        for p in stack:
            p.stop()

    # 不整体抛：第一条入 failures、第二条成功
    assert len(result["failures"]) == 1
    assert len(result["created"]) == 1
    assert len(result["created"]) + len(result["failures"]) == result["feature_count"]
    # 成功的那条仍 attach
    assert attach.await_count == 1


# ===========================================================================
# INV-6 守护
# ===========================================================================


def test_inv6_no_direct_link_write() -> None:
    """board_split_service.py 不旁路 ProjectWorkItemLink 写表（经 ProjectService）。"""
    src = Path(__file__).resolve().parents[2] / "initiatives" / "services" / "board_split_service.py"
    text = src.read_text(encoding="utf-8")
    assert "ProjectWorkItemLink.objects.create" not in text
    assert "ProjectWorkItemLink.objects.get_or_create" not in text
    assert "ProjectService" in text
    assert "attach_work_item" in text


# ===========================================================================
# AI 工具 split_feature_list_to_boards
# ===========================================================================


async def test_tool_space_not_found() -> None:
    from agents.tools.board_split_tools import split_feature_list_to_boards

    with patch("agents.tools.board_split_tools.Space") as mock_space:
        mock_space.DoesNotExist = Exception
        mock_space.objects.aget = AsyncMock(side_effect=mock_space.DoesNotExist())
        result = await split_feature_list_to_boards(
            space_id="missing", feature_list_text="x"
        )
    assert result.success is False
    assert "不存在" in (result.error or "")


async def test_tool_no_input_source() -> None:
    from agents.tools.board_split_tools import split_feature_list_to_boards

    result = await split_feature_list_to_boards(space_id="s1")
    assert result.success is False


async def test_tool_happy_delegates_service() -> None:
    from agents.tools.board_split_tools import split_feature_list_to_boards

    create_result = {
        "created": [{"feature": "A1", "work_item_id": 1000, "linked": True}],
        "failures": [],
        "degraded_parent_child": False,
        "hint": None,
        "feature_count": 1,
    }
    with (
        patch("agents.tools.board_split_tools.Space") as mock_space,
        patch("agents.tools.board_split_tools.BoardSplitService") as mock_svc_cls,
    ):
        mock_space.DoesNotExist = Exception
        mock_space.objects.aget = AsyncMock(return_value=_space())
        instance = mock_svc_cls.return_value
        instance.propose_split = AsyncMock(return_value=_PROPOSAL)
        instance.create_boards = AsyncMock(return_value=create_result)
        result = await split_feature_list_to_boards(
            space_id="s1", feature_list_text="x"
        )
    assert result.success is True
    assert result.output["data"]["created"]
    assert result.output["data"]["feature_count"] == 1
