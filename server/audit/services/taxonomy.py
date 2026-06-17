"""action taxonomy 稳定常量集（AUDIT-02）。

把审计 ``action`` 词表沉淀为模块级 ``Final[str]`` 稳定常量，各 emit 点统一引用常量
（消除字符串字面量漂移），镜像 ``delivery/services/event_taxonomy.py`` 范式。

命名规范：``object.verb`` 对象在前风格（``member.created`` / ``credential.updated`` /
``pat.revoked``），对齐既有 ``purge.started`` / ``repo.research.started`` / ``spec.drafted``
既成事实。

常量集说明：
- ``ALL_ACTIONS``：本 phase（v0.x audit 地基）定义的种子 action 全集——供守护测试断言
  命名规范与种子覆盖。具体 action 值由 Phase 54 各埋点补充消费。
- ``RESERVED_ACTIONS``：v0.5 既有埋点收口预留（``purge.started`` / ``purge.completed``，
  见 ``services/purge_reconcile.py``）——Phase 54 接线，**非本 phase** 产出，故不计入
  ``ALL_ACTIONS`` 词表（对齐 ``event_taxonomy.RESERVED_EVENTS`` 范式）。

说明：本 phase 仅定义稳定容器 + 种子/预留常量，具体 action 值由 Phase 54 各埋点补充消费。
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "ACTION_MEMBER_CREATED",
    "ACTION_MEMBER_UPDATED",
    "ACTION_MEMBER_DELETED",
    "ACTION_USER_ACTIVATED",
    "ACTION_USER_DEACTIVATED",
    "ACTION_ROLE_CHANGED",
    "ACTION_PROJECT_CONFIG_CHANGED",
    "ACTION_REPOSITORY_PERMISSION_CHANGED",
    "ACTION_CREDENTIAL_CREATED",
    "ACTION_CREDENTIAL_UPDATED",
    "ACTION_CREDENTIAL_DELETED",
    "ACTION_PAT_CREATED",
    "ACTION_PAT_REVOKED",
    "ACTION_FEISHU_SYNC_TRIGGERED",
    "ACTION_EXCLUSION_RULE_CHANGED",
    "ALL_ACTIONS",
    "RESERVED_ACTIONS",
]

# ---- 身份/权限类 action 种子常量 ----
ACTION_MEMBER_CREATED: Final[str] = "member.created"
ACTION_MEMBER_UPDATED: Final[str] = "member.updated"
ACTION_MEMBER_DELETED: Final[str] = "member.deleted"
ACTION_USER_ACTIVATED: Final[str] = "user.activated"
ACTION_USER_DEACTIVATED: Final[str] = "user.deactivated"
ACTION_ROLE_CHANGED: Final[str] = "role.changed"
ACTION_PROJECT_CONFIG_CHANGED: Final[str] = "project.config_changed"
ACTION_REPOSITORY_PERMISSION_CHANGED: Final[str] = "repository.permission_changed"

# ---- 凭证/数据治理类 action 种子常量 ----
ACTION_CREDENTIAL_CREATED: Final[str] = "credential.created"
ACTION_CREDENTIAL_UPDATED: Final[str] = "credential.updated"
ACTION_CREDENTIAL_DELETED: Final[str] = "credential.deleted"
ACTION_PAT_CREATED: Final[str] = "pat.created"
ACTION_PAT_REVOKED: Final[str] = "pat.revoked"
ACTION_FEISHU_SYNC_TRIGGERED: Final[str] = "feishu_sync.triggered"
ACTION_EXCLUSION_RULE_CHANGED: Final[str] = "exclusion_rule.changed"

# 本 phase 定义的种子 action 全集（守护测试基准）
ALL_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        ACTION_MEMBER_CREATED,
        ACTION_MEMBER_UPDATED,
        ACTION_MEMBER_DELETED,
        ACTION_USER_ACTIVATED,
        ACTION_USER_DEACTIVATED,
        ACTION_ROLE_CHANGED,
        ACTION_PROJECT_CONFIG_CHANGED,
        ACTION_REPOSITORY_PERMISSION_CHANGED,
        ACTION_CREDENTIAL_CREATED,
        ACTION_CREDENTIAL_UPDATED,
        ACTION_CREDENTIAL_DELETED,
        ACTION_PAT_CREATED,
        ACTION_PAT_REVOKED,
        ACTION_FEISHU_SYNC_TRIGGERED,
        ACTION_EXCLUSION_RULE_CHANGED,
    }
)

# v0.5 既有埋点收口预留（Phase 54 接线，非本 phase 产出）——不计入 ALL_ACTIONS 词表
RESERVED_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "purge.started",
        "purge.completed",
    }
)
