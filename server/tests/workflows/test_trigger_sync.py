"""飞书触发器同步契约测试（per-workflow 专属端点重构后）。

断言 `async_sync_workflow_triggers` 的目标行为：
- 每个 `feishu_event_trigger` 节点按 node_id upsert 一条启用的 WorkflowTrigger，
  分配唯一 token，且不写入 event_type / filter_config（飞书侧自动化规则已决定触发时机）。
- 同步把权威 token 回填到节点 `config.endpoint_token`，供前端展示端点 URL。
- token 跨多次同步保持稳定（不重新生成、不产生重复 trigger）。
- 多个触发节点生成各自独立 token 的 trigger。
- 节点被移除后，其 trigger 被停用（含旧版无 node_id 的存量行）。
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
        description="Project for trigger sync tests",
    )
    return await Workflow.objects.acreate(
        name=name,
        project=project,
        trigger_type="event",
    )


async def _make_trigger_node(workflow: Workflow, config: dict | None = None) -> WorkflowNode:
    """创建一个 feishu_event_trigger 节点。"""
    return await WorkflowNode.objects.acreate(
        workflow=workflow,
        node_type="feishu_event_trigger",
        name="Feishu Event Trigger",
        position_x=0,
        position_y=0,
        config=config or {},
    )


async def _triggers(workflow: Workflow) -> list[WorkflowTrigger]:
    return [t async for t in workflow.triggers.all()]


async def test_node_creates_trigger_with_token():
    """单个触发节点同步后生成 1 条带唯一 token 的启用 trigger，且 token 回填节点 config。"""
    workflow = await _make_workflow()
    node = await _make_trigger_node(workflow)

    await async_sync_workflow_triggers(workflow)

    triggers = await _triggers(workflow)
    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger.is_active is True
    assert str(trigger.node_id) == str(node.id)
    assert trigger.token  # 非空唯一 token
    # 不再写入事件类型 / 过滤条件
    assert trigger.event_type == ""
    assert trigger.filter_config == {}
    # token 回填到节点 config.endpoint_token
    await node.arefresh_from_db()
    assert node.config.get("endpoint_token") == trigger.token


async def test_client_endpoint_token_adopted():
    """节点 config 预置合法 endpoint_token（拖入时客户端生成）→ 创建 trigger 时采纳该 token。"""
    workflow = await _make_workflow("Client Token WF")
    client_token = "Abc123_def456-GHI789jklMNO"  # 合法 base64url，长度 26
    node = await _make_trigger_node(workflow, config={"endpoint_token": client_token})

    await async_sync_workflow_triggers(workflow)

    trigger = (await _triggers(workflow))[0]
    assert trigger.token == client_token
    await node.arefresh_from_db()
    assert node.config.get("endpoint_token") == client_token


async def test_invalid_client_endpoint_token_falls_back():
    """非法 endpoint_token（含非法字符）→ 不采纳，回退模型 default 生成唯一 token。"""
    workflow = await _make_workflow("Invalid Token WF")
    node = await _make_trigger_node(workflow, config={"endpoint_token": "bad token!"})

    await async_sync_workflow_triggers(workflow)

    trigger = (await _triggers(workflow))[0]
    assert trigger.token != "bad token!"
    assert trigger.token  # 已回退生成合法 token
    await node.arefresh_from_db()
    assert node.config.get("endpoint_token") == trigger.token


async def test_duplicate_client_endpoint_token_falls_back():
    """客户端 token 与已有 trigger token 冲突 → 不采纳，回退生成唯一 token（保证唯一约束）。"""
    workflow = await _make_workflow("Dup Token WF")
    taken = "Dup123_def456-GHI789jklMNO"
    # 先占用该 token
    await WorkflowTrigger.objects.acreate(
        workflow=workflow, node_id=None, is_active=True, name="taken", token=taken,
    )
    node = await _make_trigger_node(workflow, config={"endpoint_token": taken})

    await async_sync_workflow_triggers(workflow)

    new_trigger = await workflow.triggers.filter(node_id=node.id).afirst()
    assert new_trigger is not None
    assert new_trigger.token != taken  # 冲突回退
    assert new_trigger.token


async def test_endpoint_path_format():
    """endpoint_path 为 /api/feishu/webhook/<token>/。"""
    workflow = await _make_workflow("Endpoint Path WF")
    await _make_trigger_node(workflow)

    await async_sync_workflow_triggers(workflow)

    trigger = (await _triggers(workflow))[0]
    assert trigger.endpoint_path == f"/api/feishu/webhook/{trigger.token}/"


async def test_token_stable_across_resync():
    """重复同步不重新生成 token、不产生重复 trigger。"""
    workflow = await _make_workflow("Stable Token WF")
    await _make_trigger_node(workflow)

    await async_sync_workflow_triggers(workflow)
    first = (await _triggers(workflow))[0]
    first_token = first.token

    await async_sync_workflow_triggers(workflow)
    triggers = await _triggers(workflow)
    assert len(triggers) == 1
    assert triggers[0].token == first_token


async def test_multiple_nodes_get_distinct_tokens():
    """多个触发节点各自生成独立 token 的 trigger。"""
    workflow = await _make_workflow("Multi Node WF")
    await _make_trigger_node(workflow)
    await _make_trigger_node(workflow)

    await async_sync_workflow_triggers(workflow)

    triggers = await _triggers(workflow)
    assert len(triggers) == 2
    tokens = {t.token for t in triggers}
    assert len(tokens) == 2  # token 互不相同
    assert all(t.is_active for t in triggers)


async def test_removed_node_deactivates_trigger():
    """节点被移除后其 trigger 被停用。"""
    workflow = await _make_workflow("Removed Node WF")
    node = await _make_trigger_node(workflow)
    await async_sync_workflow_triggers(workflow)
    assert (await _triggers(workflow))[0].is_active is True

    await node.adelete()
    await async_sync_workflow_triggers(workflow)

    triggers = await _triggers(workflow)
    assert len(triggers) == 1  # 行保留但停用
    assert triggers[0].is_active is False


async def test_legacy_trigger_without_node_deactivated():
    """旧版无 node_id 的存量 trigger 在同步后被停用（无对应画布节点）。"""
    workflow = await _make_workflow("Legacy Trigger WF")
    legacy = await WorkflowTrigger.objects.acreate(
        workflow=workflow,
        event_type="WorkitemStatusEvent",
        filter_config={"project_key": "old"},
        is_active=True,
        name="legacy",
    )
    assert legacy.node_id is None

    await async_sync_workflow_triggers(workflow)

    await legacy.arefresh_from_db()
    assert legacy.is_active is False
