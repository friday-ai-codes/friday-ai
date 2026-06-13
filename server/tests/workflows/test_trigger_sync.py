"""TRIG-01 同步契约测试（Phase 21 Wave 0 RED）。

断言**修复后**的 `async_sync_workflow_triggers` 目标行为：
- 单数 `event_type` 为事实源，同步后生成 WorkflowTrigger（当前读复数 → RED）。
- 历史复数 `event_types` 数组兜底仍生成 trigger（Pitfall 1 回归保护）。
- `filter_status` / `filter_project_key` / `filter_work_item_type` 正确写入 filter_config。
- 同步生成的 trigger 与真实 payload 端到端匹配（matches_event）。
- OQ#1 裁定：`project_ids` / `exclude_*` 负向 / 跨 ID 空间字段**不**写入正向 filter_config
  （避免静默误匹配，留 v2）。

注意：本文件为 TDD RED 阶段产物，多数用例在 21-03/04 实现前预期为**断言失败**，
而非 collection/import error。转绿计划：21-03（同步修复）。
"""

import pytest

from projects.models import Project
from workflows.api.views import async_sync_workflow_triggers
from workflows.models import Workflow, WorkflowNode, WorkflowTrigger

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


async def _make_workflow(name: str = "Trigger Sync WF") -> Workflow:
    """创建最小工作流（created_by 可空，省去 user 夹具）。"""
    project = await Project.objects.acreate(
        name=f"{name} Project",
        description="Project for trigger sync RED tests",
    )
    return await Workflow.objects.acreate(
        name=name,
        project=project,
        trigger_type="event",
    )


async def _make_trigger_node(workflow: Workflow, config: dict) -> WorkflowNode:
    """创建一个 feishu_event_trigger 节点，承载给定 config。"""
    return await WorkflowNode.objects.acreate(
        workflow=workflow,
        node_type="feishu_event_trigger",
        name="Feishu Event Trigger",
        position_x=0,
        position_y=0,
        config=config,
    )


async def _triggers(workflow: Workflow) -> list[WorkflowTrigger]:
    return [t async for t in workflow.triggers.all()]


async def test_singular_event_type_creates_trigger():
    """TRIG-01：单数 event_type 同步后应生成 1 条启用的 WorkflowTrigger。

    现状根因：`async_sync_workflow_triggers` 读 config['event_types']（复数）→ 恒空 →
    不生成 trigger。因此本用例在修复前为 RED（生成 0 条）。
    """
    workflow = await _make_workflow()
    await _make_trigger_node(
        workflow,
        {"event_type": "WorkitemStatusEvent", "filter_status": ["s1"]},
    )

    await async_sync_workflow_triggers(workflow)

    triggers = await _triggers(workflow)
    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger.event_type == "WorkitemStatusEvent"
    assert trigger.is_active is True
    # filter_status 数组 → 嵌套路径 cur_work_item_status.state_key（list 成员匹配）
    assert trigger.filter_config.get("cur_work_item_status.state_key") == ["s1"]


async def test_legacy_event_types_array_fallback():
    """TRIG-01 Pitfall 1：仅含历史复数 event_types 的节点同步后仍应生成 trigger（兜底）。"""
    workflow = await _make_workflow("Legacy Array WF")
    await _make_trigger_node(workflow, {"event_types": ["WorkitemStatusEvent"]})

    await async_sync_workflow_triggers(workflow)

    triggers = await _triggers(workflow)
    assert len(triggers) == 1
    assert triggers[0].event_type == "WorkitemStatusEvent"


async def test_filter_config_maps_project_and_work_item():
    """TRIG-01：filter_project_key / filter_work_item_type 正确映射进 filter_config。"""
    workflow = await _make_workflow("Filter Map WF")
    await _make_trigger_node(
        workflow,
        {
            "event_type": "WorkitemStatusEvent",
            "filter_project_key": "proj-key-123",
            "filter_work_item_type": "story",
        },
    )

    await async_sync_workflow_triggers(workflow)

    triggers = await _triggers(workflow)
    assert len(triggers) == 1
    fc = triggers[0].filter_config
    assert fc.get("project_key") == "proj-key-123"
    assert fc.get("work_item_type_key") == "story"


async def test_e2e_match():
    """TRIG-01 端到端：同步生成的 trigger 应能匹配真实 payload，错配返回 False。"""
    workflow = await _make_workflow("E2E Match WF")
    await _make_trigger_node(
        workflow,
        {"event_type": "WorkitemStatusEvent", "filter_status": ["s1"]},
    )

    await async_sync_workflow_triggers(workflow)

    triggers = await _triggers(workflow)
    assert len(triggers) == 1
    trigger = triggers[0]

    matching_payload = {"cur_work_item_status": {"state_key": "s1"}}
    assert trigger.matches_event("WorkitemStatusEvent", matching_payload) is True

    non_matching_payload = {"cur_work_item_status": {"state_key": "other"}}
    assert trigger.matches_event("WorkitemStatusEvent", non_matching_payload) is False


async def test_exclude_and_project_ids_not_in_filter_config():
    """OQ#1 裁定：project_ids / exclude_* 负向、跨 ID 空间字段不得写入正向 filter_config。

    `_matches_filter` 仅支持正向 include 语义，负向/Space UUID 字段若被正向写入会造成
    静默误匹配。本用例锁死「这些键不出现在 filter_config」。修复前无 trigger 生成 → RED。
    """
    workflow = await _make_workflow("Negative Fields WF")
    await _make_trigger_node(
        workflow,
        {
            "event_type": "WorkitemStatusEvent",
            "filter_status": ["s1"],
            "project_ids": ["space-uuid-aaa", "space-uuid-bbb"],
            "exclude_project_ids": ["space-uuid-ccc"],
            "exclude_work_item_pattern": "^TEST-",
        },
    )

    await async_sync_workflow_triggers(workflow)

    triggers = await _triggers(workflow)
    assert len(triggers) == 1
    fc = triggers[0].filter_config
    assert "project_ids" not in fc
    assert "exclude_project_ids" not in fc
    assert "exclude_work_item_pattern" not in fc
