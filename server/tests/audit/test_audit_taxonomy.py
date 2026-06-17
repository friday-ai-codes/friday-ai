"""action taxonomy 守护测试（AUDIT-02）。

镜像 ``test_event_taxonomy`` 范式：断言命名规范（object.verb 全小写）+ 种子覆盖 +
RESERVED 与 ALL_ACTIONS 不相交（purge.* 预留不计入本 phase 词表）。
"""

import re

from audit.services.taxonomy import ALL_ACTIONS, RESERVED_ACTIONS

# object.verb 命名：全小写，至少一个 "." 分隔的两段及以上（如 member.created / project.config_changed）
_ACTION_NAME_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")


def test_actions_naming_convention():
    """ALL_ACTIONS 每个值全小写、含至少一个 "." 分隔的 object.verb 形。"""
    for action in ALL_ACTIONS:
        assert _ACTION_NAME_RE.match(action), f"action 命名不符 object.verb 规范：{action!r}"


def test_all_actions_contains_seeds():
    """ALL_ACTIONS ⊇ 代表性种子常量值（身份/凭证/PAT 各一）。"""
    seeds = {"member.created", "credential.updated", "pat.revoked"}
    assert seeds <= ALL_ACTIONS, f"种子常量缺失：{seeds - ALL_ACTIONS}"


def test_reserved_disjoint_from_all():
    """RESERVED_ACTIONS（purge.* 预留）与 ALL_ACTIONS 不相交。"""
    assert RESERVED_ACTIONS.isdisjoint(ALL_ACTIONS), (
        f"RESERVED 与 ALL_ACTIONS 不应相交：{RESERVED_ACTIONS & ALL_ACTIONS}"
    )
    assert {"purge.started", "purge.completed"} <= RESERVED_ACTIONS
