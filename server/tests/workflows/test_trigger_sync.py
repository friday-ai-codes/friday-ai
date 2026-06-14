"""TRIG-01 同步契约测试（Phase 21 Wave 0 RED）。

断言**修复后**的 `async_sync_workflow_triggers` 目标行为：
- 单数 `event_type` 为事实源，同步后生成 WorkflowTrigger（当前读复数 → RED）。
- 历史复数 `event_types` 数组兜底仍生成 trigger（Pitfall 1 回归保护）。
- `filter_status` / `filter_project_key` / `filter_work_item_type` 正确写入 filter_config。
- 同步生成的 trigger 与真实 payload 端到端匹配（matches_event）。
- 负向 / 白名单字段（`project_ids` / `exclude_project_ids` / `exclude_work_item_*`）写入
  `_include` / `_exclude` 子结构，不污染正向 filter_config；UUID 经 Project 映射成
  飞书 project_key。
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


async def test_negative_fields_go_to_include_exclude_substructures():
    """负向 / 白名单字段写入 _include / _exclude 子结构，不污染正向 filter_config。

    不变式（延续原 OQ#1 本意）：project_ids / exclude_project_ids / exclude_work_item_*
    的**原始键**绝不作为正向顶层键出现——正向匹配遍历会跳过 `_` 开头特殊键，因此
    负向字段必须落在 `_include` / `_exclude` 而非顶层，避免被当作普通字段路径静默误匹配。
    project_ids（UUID）经 Project.feishu_project_key 映射成飞书 key。
    """
    workflow = await _make_workflow("Negative Fields WF")
    # 真实 Project（带 feishu_project_key）供 UUID → key 映射
    inc = await Project.objects.acreate(name="Inc Project", feishu_project_key="key-inc")
    exc = await Project.objects.acreate(name="Exc Project", feishu_project_key="key-exc")
    await _make_trigger_node(
        workflow,
        {
            "event_type": "WorkitemStatusEvent",
            "filter_status": ["s1"],
            "project_ids": [str(inc.id)],
            "exclude_project_ids": [str(exc.id)],
            "exclude_work_item_pattern": "TEST",
            "exclude_work_item_regex": r"^\[草稿\]",
        },
    )

    await async_sync_workflow_triggers(workflow)

    triggers = await _triggers(workflow)
    assert len(triggers) == 1
    fc = triggers[0].filter_config
    # 原始负向键不得作为正向顶层键
    assert "project_ids" not in fc
    assert "exclude_project_ids" not in fc
    assert "exclude_work_item_pattern" not in fc
    assert "exclude_work_item_regex" not in fc
    # 正向键保留
    assert fc.get("cur_work_item_status.state_key") == ["s1"]
    # 映射进 _include / _exclude
    assert fc["_include"]["project_keys"] == ["key-inc"]
    assert fc["_exclude"]["project_keys"] == ["key-exc"]
    assert fc["_exclude"]["work_item_pattern"] == "TEST"
    assert fc["_exclude"]["work_item_regex"] == r"^\[草稿\]"


async def test_unmapped_project_uuid_skipped():
    """映射不到 feishu_project_key 的 UUID（Project 无 key / 非法 UUID）跳过，不写 _include。"""
    workflow = await _make_workflow("Unmapped WF")
    no_key = await Project.objects.acreate(name="NoKey Project")  # feishu_project_key=None
    await _make_trigger_node(
        workflow,
        {
            "event_type": "WorkitemStatusEvent",
            "project_ids": [str(no_key.id), "not-a-uuid"],
        },
    )

    await async_sync_workflow_triggers(workflow)

    triggers = await _triggers(workflow)
    assert len(triggers) == 1
    fc = triggers[0].filter_config
    # 无可映射 key → 不生成 _include 子结构
    assert "_include" not in fc
