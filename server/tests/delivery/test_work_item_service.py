"""WorkItemService.upsert 与派生纯函数守护测试（Phase 28-02）。

覆盖 DOMAIN §13.1 upsert 步骤与 WIT-01..05：
- Task 1：`derive_status_fields` / `derive_status_events` 纯函数 + `work_item_synced` 信号。
- Task 2：三元组幂等收敛（WIT-01）、mirror-only 刷新保护 enhanced（WIT-02）、
  per-facet `WorkItemSyncState` 且回源失败不整体回滚（WIT-03）。
- Task 3：关系派生 + `target_external_id` 占位/回填（WIT-04）、状态变更 append
  `WorkItemStatusEvent`（WIT-05）、relations facet 完整度。

所有回源经 `respx` mock（先 token 端点后业务端点），pytest-socket 隔离不发真实网络。
fixture 字段形状取 DOMAIN §16 实测（story 7010225564：field_caadeb=[7010938167]）。
"""

from __future__ import annotations

from delivery.services.derivation import derive_status_events, derive_status_fields

# === DOMAIN §16 实测自然键 ===
PROJECT_KEY = "622c10eb5daaee81db915189"
STORY_ID = 7010225564


# ============================================================================
# Task 1：派生纯函数 + 信号（纯函数，无 DB / 无网络）
# ============================================================================


def _story_raw_item() -> dict:
    """story 工作项响应 item（current_nodes 给出人类名）。"""
    return {
        "id": STORY_ID,
        "name": "实现学习平台 A",
        "work_item_status": {
            "state_key": "fi46o4r6m",
            "sub_stage": "dev",
            "current_nodes": [{"id": "state_2", "name": "Sprint计划"}],
            "state_times": [{"state_key": "fi46o4r6m", "name": "Sprint计划(times)"}],
            "is_archived_state": False,
            "is_init_state": True,
        },
    }


def _issue_raw_item() -> dict:
    """issue 工作项响应 item（无 current_nodes，仅 state_times 回退）。"""
    return {
        "id": 5580252273,
        "name": "登录崩溃",
        "work_item_status": {
            "state_key": "OPEN",
            "state_times": [
                {"state_key": "OPEN", "name": "待处理"},
                {"state_key": "CLOSED", "name": "已关闭"},
            ],
        },
    }


def test_derive_status_fields_story_current_nodes() -> None:
    """story：state_key 透传，display_name 取 current_nodes 优先。"""
    result = derive_status_fields(_story_raw_item())
    assert result["status_state_key"] == "fi46o4r6m"
    assert result["status_sub_stage"] == "dev"
    assert result["status_display_name"] == "Sprint计划"
    assert result["is_init_state"] is True
    assert result["is_archived_state"] is False


def test_derive_status_fields_issue_state_times_fallback() -> None:
    """issue：无 current_nodes → display_name 回退 state_times（匹配 state_key）。"""
    result = derive_status_fields(_issue_raw_item())
    assert result["status_state_key"] == "OPEN"
    assert result["status_display_name"] == "待处理"


def test_derive_status_fields_missing_display_name_returns_empty() -> None:
    """current_nodes / state_times 皆缺 → display_name 空串，不抛。"""
    result = derive_status_fields({"work_item_status": {"state_key": "X"}})
    assert result["status_state_key"] == "X"
    assert result["status_display_name"] == ""


def test_derive_status_fields_missing_archived_init_default_false() -> None:
    """is_archived_state / is_init_state 缺失 → False（降级），不抛。"""
    result = derive_status_fields({"work_item_status": {"state_key": "X"}})
    assert result["is_archived_state"] is False
    assert result["is_init_state"] is False


def test_derive_status_fields_non_dict_input_degrades() -> None:
    """非 dict 输入 → 全空降级，不抛异常。"""
    result = derive_status_fields(None)  # type: ignore[arg-type]
    assert result["status_state_key"] == ""
    assert result["status_display_name"] == ""
    assert result["is_archived_state"] is False


def test_derive_status_events_from_history() -> None:
    """从 work_item_status.history[] 归一状态事件列表。"""
    raw = {
        "work_item_status": {
            "state_key": "B",
            "history": [
                {"state_key": "A", "updated_at": 1700000000000, "updated_by": "u1"},
                {"state_key": "B", "updated_at": 1700000100000, "updated_by": "u2"},
            ],
        }
    }
    events = derive_status_events(raw)
    assert len(events) == 2
    assert events[0]["state_key"] == "A"
    assert events[0]["updated_by"] == "u1"
    assert events[1]["state_key"] == "B"


def test_derive_status_events_empty_without_history() -> None:
    """无 history → 空列表，不抛。"""
    assert derive_status_events({"work_item_status": {"state_key": "X"}}) == []
    assert derive_status_events(None) == []  # type: ignore[arg-type]


def test_work_item_synced_signal_importable() -> None:
    """work_item_synced 信号对象可 import（best-effort 事件位）。"""
    from django.dispatch import Signal

    from delivery.signals import work_item_synced

    assert isinstance(work_item_synced, Signal)
