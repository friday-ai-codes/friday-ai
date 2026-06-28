"""附着插件 → WorkflowReaction 配置同步（Chassis v2 · P4）。

reaction 配置是横切副作用的**单一事实源（SSOT）**；画布上的隐藏边只是它的派生
渲染。保存工作流时，把带 ``metadata.parentNodeId`` 的附着插件（notify_feishu_im /
notify_feishu / feishu_doc_create / writeback）按其 ``metadata.subscribeSignals``
upsert 成 ``WorkflowReaction``：

- ``host_node`` = 父（宿主）节点；
- ``target_type`` = 插件类型；
- ``config`` = 子节点 config；
- ``blocking_mode`` = ``non_blocking``；
- 一个插件订阅 N 个信号 → N 条反应（按信号拆分，便于按 signal_name 幂等匹配）。

并删除已不存在的附着插件对应的反应（仅纳管「host_node 非空 + 插件 target_type」范围，
不误删工作流级 webhook/alert 等其他来源反应）。

经 ``Workflow`` 的 ``post_save`` 信号触发（在 ``workflows.apps`` 的 ``ready()`` 里
connect），避免改 api/serializers/views（属其他 phase）。观测 best-effort，绝不反噬
主流程（见 WORKFLOW-RUNTIME-SPEC §4/§7）。
"""

from __future__ import annotations

from typing import Any

import structlog

from workflows.models.reaction import ReactionBlockingMode, WorkflowReaction
from workflows.reactions.signal import (
    SIG_ARTIFACT_PRODUCED,
    SIG_NODE_COMPLETED,
    SIG_NODE_FAILED,
)

logger = structlog.get_logger(__name__)

# 附着插件 node_type → reaction target_type（1:1）。仅这些类型被本同步器纳管。
# human_approval 保持 gate（由 DAG 节点承载），不在此列、不转 reaction。
PLUGIN_TARGET_TYPES: frozenset[str] = frozenset(
    {
        "notify_feishu_im",
        "notify_feishu",
        "feishu_doc_create",
        "writeback",
    }
)

# 可订阅信号白名单（与前端 slotTaxonomy CAPABILITY_SIGNALS 对齐）。
_SUBSCRIBABLE_SIGNALS: frozenset[str] = frozenset(
    {SIG_NODE_COMPLETED, SIG_NODE_FAILED, SIG_ARTIFACT_PRODUCED}
)
_DEFAULT_SIGNAL = SIG_NODE_COMPLETED


def _normalize_signals(raw: Any) -> list[str]:
    """归一化子节点 ``metadata.subscribeSignals``：过滤非法值 + 去重；空则默认完成信号。"""
    if not isinstance(raw, (list, tuple)):
        return [_DEFAULT_SIGNAL]
    picked: list[str] = []
    for item in raw:
        name = str(item)
        if name in _SUBSCRIBABLE_SIGNALS and name not in picked:
            picked.append(name)
    return picked or [_DEFAULT_SIGNAL]


def sync_reactions_for_workflow(workflow: Any) -> dict[str, int]:
    """把附着插件转换为 ``WorkflowReaction`` 配置（幂等 upsert + 删除孤儿）。

    Returns:
        统计 ``{"upserted": int, "deleted": int}``，便于日志与测试断言。
    """
    nodes = list(workflow.nodes.all())
    by_id = {str(node.id): node for node in nodes}

    # 期望反应集合：键 (host_node_id, target_type, signal_name) → spec。
    desired: dict[tuple[str, str, str], dict[str, Any]] = {}
    for node in nodes:
        meta = node.metadata or {}
        parent_id = meta.get("parentNodeId")
        if not parent_id or node.node_type not in PLUGIN_TARGET_TYPES:
            continue
        host = by_id.get(str(parent_id))
        if host is None:
            continue
        for signal_name in _normalize_signals(meta.get("subscribeSignals")):
            key = (str(host.id), node.node_type, signal_name)
            desired[key] = {
                "host_node": host,
                "target_type": node.node_type,
                "signal_name": signal_name,
                "config": node.config or {},
            }

    upserted = 0
    for spec in desired.values():
        WorkflowReaction.objects.update_or_create(
            workflow=workflow,
            host_node=spec["host_node"],
            target_type=spec["target_type"],
            signal_name=spec["signal_name"],
            defaults={
                "config": spec["config"],
                "blocking_mode": ReactionBlockingMode.NON_BLOCKING,
                "enabled": True,
            },
        )
        upserted += 1

    # 删除孤儿：纳管范围内（host_node 非空 + 插件 target_type）已无对应附着插件的反应。
    deleted = 0
    managed = WorkflowReaction.objects.filter(
        workflow=workflow,
        host_node__isnull=False,
        target_type__in=PLUGIN_TARGET_TYPES,
    )
    for reaction in managed:
        key = (str(reaction.host_node_id), reaction.target_type, reaction.signal_name)
        if key not in desired:
            reaction.delete()
            deleted += 1

    logger.info(
        "reaction_config_synced",
        component="reaction_config_sync",
        category="caller",
        workflow_id=str(getattr(workflow, "id", "")),
        upserted=upserted,
        deleted=deleted,
    )
    return {"upserted": upserted, "deleted": deleted}


def on_workflow_saved(sender: Any, instance: Any, **kwargs: Any) -> None:
    """``Workflow`` post_save handler：保存后同步反应配置（best-effort，不反噬主流程）。"""
    try:
        sync_reactions_for_workflow(instance)
    except Exception:  # noqa: BLE001 — 派生同步绝不反噬主交付/保存链路
        logger.warning(
            "reaction_config_sync_failed",
            component="reaction_config_sync",
            category="caller",
            workflow_id=str(getattr(instance, "id", "")),
            exc_info=True,
        )
