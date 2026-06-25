"""action taxonomy 稳定常量集（AUDIT-02）。

把审计 ``action`` 词表沉淀为模块级 ``Final[str]`` 稳定常量，各 emit 点统一引用常量
（消除字符串字面量漂移），镜像 ``delivery/services/event_taxonomy.py`` 范式。

命名规范：``object.verb`` 对象在前风格（``member.created`` / ``credential.updated`` /
``pat.revoked``），对齐既有 ``purge.started`` / ``repo.research.started`` / ``spec.drafted``
既成事实。

常量集说明：
- ``ALL_ACTIONS``：audit 词表 action 全集——供守护测试断言命名规范与种子覆盖。
- ``RESERVED_ACTIONS``：v0.5 既有埋点收口预留位。Phase 54 已把 ``purge.started`` /
  ``purge.completed`` 提升为具名 ``ACTION_PURGE_*`` 常量并纳入 ``ALL_ACTIONS``（接线见
  ``services/purge_reconcile.py:run_cleanup`` 经 ``_emit_purge_audit`` 收口 AuditService），
  故 RESERVED 现为空集预留位
  （对齐 ``event_taxonomy.RESERVED_EVENTS`` 范式，留待后续里程碑新增埋点收口）。
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
    "ACTION_PURGE_STARTED",
    "ACTION_PURGE_COMPLETED",
    # ---- v0.15.0 Phase 77 项目聚合根 ----
    "ACTION_PROJECT_CREATED",
    "ACTION_PROJECT_UPDATED",
    "ACTION_PROJECT_STATUS_CHANGED",
    "ACTION_PROJECT_MEMBER_ADDED",
    "ACTION_PROJECT_MEMBER_REMOVED",
    "ACTION_PROJECT_MEMBER_ROLE_CHANGED",
    "ACTION_PROJECT_OWNER_TRANSFERRED",
    "ACTION_FEISHU_USER_BOUND",
    # ---- v0.15.0 Phase 78 工作项组合 ----
    "ACTION_PROJECT_WORK_ITEM_ATTACHED",
    "ACTION_PROJECT_WORK_ITEM_DETACHED",
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

# ---- 清理/数据治理类 action 常量（Phase 54 自 v0.5 purge 埋点收口提升）----
ACTION_PURGE_STARTED: Final[str] = "purge.started"
ACTION_PURGE_COMPLETED: Final[str] = "purge.completed"

# ---- v0.15.0 Phase 77 项目聚合根 action 常量（component=initiatives）----
ACTION_PROJECT_CREATED: Final[str] = "project.created"
ACTION_PROJECT_UPDATED: Final[str] = "project.updated"
ACTION_PROJECT_STATUS_CHANGED: Final[str] = "project.status_changed"
ACTION_PROJECT_MEMBER_ADDED: Final[str] = "project.member_added"
ACTION_PROJECT_MEMBER_REMOVED: Final[str] = "project.member_removed"
ACTION_PROJECT_MEMBER_ROLE_CHANGED: Final[str] = "project.member_role_changed"
ACTION_PROJECT_OWNER_TRANSFERRED: Final[str] = "project.owner_transferred"
ACTION_FEISHU_USER_BOUND: Final[str] = "feishu_user.bound"

# ---- v0.15.0 Phase 78 工作项组合 action 常量（component=initiatives）----
ACTION_PROJECT_WORK_ITEM_ATTACHED: Final[str] = "project.work_item_attached"
ACTION_PROJECT_WORK_ITEM_DETACHED: Final[str] = "project.work_item_detached"

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
        ACTION_PURGE_STARTED,
        ACTION_PURGE_COMPLETED,
        ACTION_PROJECT_CREATED,
        ACTION_PROJECT_UPDATED,
        ACTION_PROJECT_STATUS_CHANGED,
        ACTION_PROJECT_MEMBER_ADDED,
        ACTION_PROJECT_MEMBER_REMOVED,
        ACTION_PROJECT_MEMBER_ROLE_CHANGED,
        ACTION_PROJECT_OWNER_TRANSFERRED,
        ACTION_FEISHU_USER_BOUND,
        ACTION_PROJECT_WORK_ITEM_ATTACHED,
        ACTION_PROJECT_WORK_ITEM_DETACHED,
    }
)

# v0.5 既有埋点收口预留位——purge.* 已于 Phase 54 提升为具名常量纳入 ALL_ACTIONS，
# 现为空集预留（留待后续里程碑新增埋点收口，对齐 event_taxonomy.RESERVED_EVENTS 范式）。
RESERVED_ACTIONS: Final[frozenset[str]] = frozenset()
