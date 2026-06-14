"""WorkflowTrigger.matches_event / _matches_filter 负向过滤纯函数单测（Phase 21）。

matches_event 仅读 self.event_type / self.is_active / self.filter_config，与 DB 无关，
本文件构造未落库的 WorkflowTrigger 实例直接断言匹配语义，无需数据库 fixture。

覆盖：
- _include 白名单：project_key 命中 / 未命中；
- _exclude 黑名单：project_key、name 子串 pattern、name 正则 regex；
- 非法正则容错（视为未命中该 exclude 规则，不抛异常）；
- 正向键与 _include/_exclude 共存时遍历跳过 `_` 特殊键（不被当作字段路径误匹配）。
"""

from workflows.models import WorkflowTrigger


def _trigger(filter_config: dict) -> WorkflowTrigger:
    """构造未落库的启用态 WorkflowTrigger（仅供 matches_event 纯逻辑断言）。"""
    return WorkflowTrigger(
        event_type="WorkitemStatusEvent",
        is_active=True,
        filter_config=filter_config,
    )


def test_include_whitelist_hit():
    """_include.project_keys 非空且 payload.project_key 命中 → 匹配。"""
    trigger = _trigger({"_include": {"project_keys": ["key-a", "key-b"]}})
    assert trigger.matches_event("WorkitemStatusEvent", {"project_key": "key-a"}) is True


def test_include_whitelist_miss():
    """_include.project_keys 非空但 payload.project_key 不在白名单 → 不匹配。"""
    trigger = _trigger({"_include": {"project_keys": ["key-a"]}})
    assert trigger.matches_event("WorkitemStatusEvent", {"project_key": "key-x"}) is False


def test_include_whitelist_missing_project_key_in_payload():
    """白名单非空但 payload 无 project_key → 不匹配（None 不在白名单）。"""
    trigger = _trigger({"_include": {"project_keys": ["key-a"]}})
    assert trigger.matches_event("WorkitemStatusEvent", {"name": "工作项"}) is False


def test_exclude_project_key_blacklisted():
    """_exclude.project_keys 命中 → 不匹配。"""
    trigger = _trigger({"_exclude": {"project_keys": ["key-bad"]}})
    assert trigger.matches_event("WorkitemStatusEvent", {"project_key": "key-bad"}) is False
    assert trigger.matches_event("WorkitemStatusEvent", {"project_key": "key-ok"}) is True


def test_exclude_name_pattern_substring():
    """_exclude.work_item_pattern 子串命中 payload.name → 不匹配。"""
    trigger = _trigger({"_exclude": {"work_item_pattern": "TEST"}})
    assert trigger.matches_event("WorkitemStatusEvent", {"name": "这是 TEST 项"}) is False
    assert trigger.matches_event("WorkitemStatusEvent", {"name": "正式需求"}) is True


def test_exclude_name_regex():
    """_exclude.work_item_regex 正则命中 payload.name → 不匹配。"""
    trigger = _trigger({"_exclude": {"work_item_regex": r"^\[草稿\]"}})
    assert trigger.matches_event("WorkitemStatusEvent", {"name": "[草稿] 需求 A"}) is False
    assert trigger.matches_event("WorkitemStatusEvent", {"name": "需求 A"}) is True


def test_exclude_invalid_regex_is_tolerated():
    """非法正则不抛异常，视为未命中该 exclude 规则（payload 照常匹配）。"""
    trigger = _trigger({"_exclude": {"work_item_regex": "([unclosed"}})
    # 非法正则不应打断匹配，且因未命中任何排除规则 → 匹配
    assert trigger.matches_event("WorkitemStatusEvent", {"name": "任意名称"}) is True


def test_positive_keys_skip_underscore_specials():
    """正向键与 _include/_exclude 共存：正向遍历跳过 `_` 键，不当作字段路径误匹配。"""
    trigger = _trigger(
        {
            "cur_work_item_status.state_key": ["s1"],
            "_include": {"project_keys": ["key-a"]},
            "_exclude": {"work_item_pattern": "TEST"},
        }
    )
    # 正向状态匹配 + 白名单命中 + 未触发排除 → 匹配
    payload = {
        "project_key": "key-a",
        "name": "正式需求",
        "cur_work_item_status": {"state_key": "s1"},
    }
    assert trigger.matches_event("WorkitemStatusEvent", payload) is True
    # 正向状态不符 → 不匹配（与负向无关）
    payload_bad_state = {**payload, "cur_work_item_status": {"state_key": "other"}}
    assert trigger.matches_event("WorkitemStatusEvent", payload_bad_state) is False


def test_exclude_takes_precedence_over_include():
    """先跑 _exclude：黑名单命中即不匹配，即便白名单也命中。"""
    trigger = _trigger(
        {
            "_include": {"project_keys": ["key-a"]},
            "_exclude": {"work_item_pattern": "TEST"},
        }
    )
    payload = {"project_key": "key-a", "name": "TEST 项"}
    assert trigger.matches_event("WorkitemStatusEvent", payload) is False
