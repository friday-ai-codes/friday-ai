"""Chassis v2 · P4 附着插件 → WorkflowReaction 配置同步测试。

覆盖：附着插件 + subscribeSignals → 生成正确 WorkflowReaction（host_node/target_type/
config/blocking_mode/signal_name）；多信号拆多条；删除插件 → 清理 reaction；重同步幂等
更新 config 与信号；非纳管/未附着节点被忽略；默认订阅完成信号。

config_sync 是同步函数（由 Workflow post_save 触发），故用同步 ORM 直接断言。
"""

import pytest

from projects.models import Space
from workflows.models import Workflow, WorkflowNode, WorkflowReaction
from workflows.reactions.config_sync import (
    PLUGIN_TARGET_TYPES,
    sync_reactions_for_workflow,
)

pytestmark = pytest.mark.django_db


def _make_workflow() -> tuple[Space, Workflow]:
    space = Space.objects.create(name="CS Space", description="config sync tests")
    workflow = Workflow.objects.create(name="CS WF", trigger_type="manual", space=space)
    return space, workflow


def _add_node(
    workflow: Workflow,
    node_type: str,
    *,
    metadata: dict | None = None,
    config: dict | None = None,
    name: str = "N",
) -> WorkflowNode:
    return WorkflowNode.objects.create(
        workflow=workflow,
        node_type=node_type,
        name=name,
        position_x=0,
        position_y=0,
        config=config or {},
        metadata=metadata or {},
    )


def test_attached_plugin_with_signals_creates_reactions():
    """附着通知插件 + 两个订阅信号 → 两条 WorkflowReaction，字段正确。"""
    _, wf = _make_workflow()
    host = _add_node(wf, "ai_plan_research", name="方案")
    _add_node(
        wf,
        "notify_feishu_im",
        metadata={
            "parentNodeId": str(host.id),
            "subscribeSignals": ["node.completed", "node.failed"],
        },
        config={"chat_id": "oc_x"},
        name="通知",
    )

    stats = sync_reactions_for_workflow(wf)

    assert stats["upserted"] == 2
    reactions = list(WorkflowReaction.objects.filter(workflow=wf).order_by("signal_name"))
    assert {r.signal_name for r in reactions} == {"node.completed", "node.failed"}
    for r in reactions:
        assert r.host_node_id == host.id
        assert r.target_type == "notify_feishu_im"
        assert r.config == {"chat_id": "oc_x"}
        assert r.blocking_mode == "non_blocking"
        assert r.enabled is True


def test_default_signal_when_no_subscribe_signals():
    """无 subscribeSignals → 默认订阅 node.completed。"""
    _, wf = _make_workflow()
    host = _add_node(wf, "ai_plan_research")
    _add_node(
        wf,
        "feishu_doc_create",
        metadata={"parentNodeId": str(host.id)},
        config={"title": "t", "content": "c"},
    )

    sync_reactions_for_workflow(wf)

    reactions = list(WorkflowReaction.objects.filter(workflow=wf))
    assert len(reactions) == 1
    assert reactions[0].signal_name == "node.completed"
    assert reactions[0].target_type == "feishu_doc_create"
    assert reactions[0].host_node_id == host.id


def test_removing_plugin_cleans_reaction():
    """删除附着插件后重同步 → 对应 reaction 被清理。"""
    _, wf = _make_workflow()
    host = _add_node(wf, "ai_plan_research")
    child = _add_node(
        wf,
        "notify_feishu_im",
        metadata={"parentNodeId": str(host.id), "subscribeSignals": ["node.completed"]},
        config={"chat_id": "oc"},
    )

    sync_reactions_for_workflow(wf)
    assert WorkflowReaction.objects.filter(workflow=wf).count() == 1

    child.delete()
    stats = sync_reactions_for_workflow(wf)

    assert stats["deleted"] == 1
    assert WorkflowReaction.objects.filter(workflow=wf).count() == 0


def test_resync_is_idempotent_and_updates_config_and_signal():
    """重同步：config/订阅信号变更被更新，不重复创建（仍 1 条）。"""
    _, wf = _make_workflow()
    host = _add_node(wf, "ai_plan_research")
    child = _add_node(
        wf,
        "notify_feishu_im",
        metadata={"parentNodeId": str(host.id), "subscribeSignals": ["node.completed"]},
        config={"chat_id": "old"},
    )

    sync_reactions_for_workflow(wf)
    assert WorkflowReaction.objects.filter(workflow=wf).count() == 1

    child.config = {"chat_id": "new"}
    child.metadata = {"parentNodeId": str(host.id), "subscribeSignals": ["node.failed"]}
    child.save()
    sync_reactions_for_workflow(wf)

    reactions = list(WorkflowReaction.objects.filter(workflow=wf))
    assert len(reactions) == 1
    assert reactions[0].signal_name == "node.failed"
    assert reactions[0].config == {"chat_id": "new"}


def test_non_plugin_and_unattached_nodes_ignored():
    """非纳管类型（clarification_card）/未附着节点 → 不生成 reaction。"""
    _, wf = _make_workflow()
    host = _add_node(wf, "ai_plan_research")
    # 未附着的通知插件（无 parentNodeId）→ 忽略
    _add_node(wf, "notify_feishu_im", metadata={}, config={"chat_id": "x"})
    # 附着但非纳管类型（澄清卡是 gate/内部回路）→ 忽略
    _add_node(wf, "clarification_card", metadata={"parentNodeId": str(host.id)})

    stats = sync_reactions_for_workflow(wf)

    assert stats["upserted"] == 0
    assert WorkflowReaction.objects.filter(workflow=wf).count() == 0


def test_invalid_signals_filtered_and_dedup():
    """非法/重复信号被过滤；全非法回退默认完成信号。"""
    _, wf = _make_workflow()
    host = _add_node(wf, "ai_plan_research")
    _add_node(
        wf,
        "writeback",
        metadata={
            "parentNodeId": str(host.id),
            "subscribeSignals": ["bogus", "node.failed", "node.failed", "also_bad"],
        },
        config={"field_key": "f", "work_item_id": 1},
    )

    sync_reactions_for_workflow(wf)

    reactions = list(WorkflowReaction.objects.filter(workflow=wf))
    assert len(reactions) == 1
    assert reactions[0].signal_name == "node.failed"
    assert reactions[0].target_type == "writeback"


def test_writeback_is_a_managed_plugin_target():
    """writeback 属纳管插件 target（确保删除孤儿能覆盖它）。"""
    assert "writeback" in PLUGIN_TARGET_TYPES
    assert "feishu_doc_create" in PLUGIN_TARGET_TYPES
