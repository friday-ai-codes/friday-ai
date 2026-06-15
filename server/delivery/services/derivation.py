"""飞书工作项响应 → mirror 状态字段派生（纯函数，无 DB / 无网络）。

仅承担 Phase 27 ``feishu_parsing`` 未覆盖的 delivery 侧状态派生：从单条工作项响应
dict 取 ``work_item_status`` 的 state_key / sub_stage / 人类显示名 / archived / init，
并把 ``work_item_status.history[]`` 归一为状态事件列表供回填去重。

设计约束（对齐 knowledge normalizer 降级范式，§1.4 / WIT-03）：
- **绝不抛**：所有取值经 ``dict.get`` 容错，缺字段降级为空串 / False / ``[]``。
- **免映射人类名**（§1.5）：``status_display_name`` 优先 ``current_nodes[].name``，
  回退 ``state_times[].name``（匹配当前 state_key 优先），皆缺则空串。
"""

from __future__ import annotations

from typing import Any

__all__ = ["derive_status_fields", "derive_status_events"]


def _status_dict(raw_item: Any) -> dict:
    """从工作项响应 item 取 ``work_item_status`` dict（容错非 dict → 空 dict）。"""
    if not isinstance(raw_item, dict):
        return {}
    status = raw_item.get("work_item_status")
    return status if isinstance(status, dict) else {}


def _derive_display_name(status: dict, state_key: str) -> str:
    """派生人类可读状态名：current_nodes 优先，state_times 回退（§1.5 免映射）。"""
    current_nodes = status.get("current_nodes")
    if isinstance(current_nodes, list):
        for node in current_nodes:
            if isinstance(node, dict) and node.get("name"):
                return str(node["name"])

    state_times = status.get("state_times")
    if isinstance(state_times, list):
        # 优先匹配当前 state_key 的条目
        for entry in state_times:
            if (
                isinstance(entry, dict)
                and entry.get("state_key") == state_key
                and entry.get("name")
            ):
                return str(entry["name"])
        # 回退首个有名字的条目
        for entry in state_times:
            if isinstance(entry, dict) and entry.get("name"):
                return str(entry["name"])

    return ""


def derive_status_fields(raw_item: Any) -> dict:
    """从单条工作项响应 dict 派生 mirror 状态字段（缺字段降级，不抛）。

    Args:
        raw_item: 工作项响应单条 item（飞书 query 接口 ``data[0]``）。

    Returns:
        ``{status_state_key, status_sub_stage, status_display_name,
        is_archived_state, is_init_state}``；缺失项降级空串 / False。
    """
    status = _status_dict(raw_item)
    state_key = str(status.get("state_key") or "")
    sub_stage = str(status.get("sub_stage") or "")
    display_name = _derive_display_name(status, state_key)

    return {
        "status_state_key": state_key,
        "status_sub_stage": sub_stage,
        "status_display_name": display_name,
        "is_archived_state": bool(status.get("is_archived_state", False)),
        "is_init_state": bool(status.get("is_init_state", False)),
    }


def derive_status_events(raw_item: Any) -> list[dict]:
    """从 ``work_item_status.history[]`` 归一状态事件列表（best-effort，可空）。

    Args:
        raw_item: 工作项响应单条 item。

    Returns:
        ``[{state_key, updated_at, updated_by}, ...]``；无 history → ``[]``。
    """
    status = _status_dict(raw_item)
    history = status.get("history")
    if not isinstance(history, list):
        return []

    events: list[dict] = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        events.append(
            {
                "state_key": str(entry.get("state_key") or ""),
                "updated_at": entry.get("updated_at"),
                "updated_by": str(entry.get("updated_by") or ""),
            }
        )
    return events
