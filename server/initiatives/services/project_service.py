"""ProjectService —— Project 聚合根的唯一写入入口（PROJ-01/02/05，INV-6）。

所有 ``Project`` / ``ProjectMember`` / ``ProjectRelation`` 的 create/update/状态流转/成员变更
都经本 service 收口（旁路写表由 ``test_project_inv6_guard`` grep 守护）。模型层不提供业务
create/save 方法。

设计要点（对齐 ``delivery``/``audit`` 既有范式）：
- async 面向 adrf/channels；ORM 在 async 经 ``sync_to_async`` 桥接。
- 状态机：合法流转表显式定义，非法流转 fail-loud ``ProjectTransitionError``；状态变更经
  ``AuditService.aemit``（category=caller, component=initiatives, before/after 脱敏入口强制,
  initiated_by_user_id）。
- 幂等：``(space, feishu_project_key)`` 在 key 非空时 ``get_or_create``；空 key 的手动项目每次新建。
- 写库成功后 best-effort WS 推送（``apush_project_event``，失败不反噬主写入）。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from initiatives.models import Project, ProjectMember, ProjectRole, ProjectStatus
from initiatives.services.realtime import apush_project_event

logger = structlog.get_logger(__name__)

__all__ = ["ProjectService", "ProjectTransitionError"]

# 审计来源/组件常量（component=initiatives）。
_COMPONENT = "initiatives"


class ProjectTransitionError(Exception):
    """项目状态非法流转 fail-loud（API 层转 400）。"""


class ProjectService:
    """Project 聚合根唯一写入入口（INV-6）。"""

    # 合法状态流转表：from -> 允许的 to 集合。terminated 为终态（无出边）。
    _LEGAL_TRANSITIONS: dict[str, set[str]] = {
        ProjectStatus.DEVELOPING: {ProjectStatus.ARCHIVED, ProjectStatus.TERMINATED},
        ProjectStatus.ARCHIVED: {ProjectStatus.DEVELOPING, ProjectStatus.TERMINATED},
        ProjectStatus.TERMINATED: set(),
    }

    # ---- 创建 / 更新 ----

    async def create(
        self,
        *,
        space: Any,
        name: str,
        description: str = "",
        feishu_project_key: str = "",
        feishu_board_url: str = "",
        feishu_board_id: str = "",
        created_by: Any = None,
        initiated_by_user_id: Any = None,
    ) -> tuple[Project, bool]:
        """幂等创建项目（PROJ-01/05）。

        ``feishu_project_key`` 非空时按 ``(space, feishu_project_key)`` 幂等
        （``get_or_create``）；空 key 的手动项目每次新建。新建时把 ``created_by`` 设为
        主R（owner）成员。返回 ``(project, created)``。

        Args:
            space: 所属 ``Space`` 实例。
            name: 项目名称。
            description: 项目描述。
            feishu_project_key: 飞书看板 project_key（幂等键，可空）。
            feishu_board_url / feishu_board_id: 飞书看板引用。
            created_by: 创建者 ``User``（新建时设为 owner 成员）。
            initiated_by_user_id: 触发用户 id（审计绑定；缺省回退 created_by）。
        """
        project, created = await self._create_locked(
            space=space,
            name=name,
            description=description,
            feishu_project_key=feishu_project_key,
            feishu_board_url=feishu_board_url,
            feishu_board_id=feishu_board_id,
            created_by=created_by,
        )

        if created:
            actor_id = initiated_by_user_id or getattr(created_by, "id", None)
            await AuditService.aemit(
                action=taxonomy.ACTION_PROJECT_CREATED,
                actor=created_by,
                target_type="project",
                target_id=project.id,
                target_repr=project.name,
                after={
                    "space_id": str(space.id),
                    "name": name,
                    "feishu_project_key": feishu_project_key,
                    "status": project.status,
                },
                metadata={
                    "component": _COMPONENT,
                    "category": "caller",
                    "initiated_by_user_id": str(actor_id) if actor_id else "system",
                },
                source="api",
            )
            await apush_project_event(
                project.id, "created", {"name": name, "status": project.status}
            )

        return project, created

    @sync_to_async
    def _create_locked(
        self,
        *,
        space: Any,
        name: str,
        description: str,
        feishu_project_key: str,
        feishu_board_url: str,
        feishu_board_id: str,
        created_by: Any,
    ) -> tuple[Project, bool]:
        """原子建/取 Project（key 非空走 get_or_create 幂等，新建时建 owner 成员）。"""
        defaults = {
            "name": name,
            "description": description,
            "feishu_board_url": feishu_board_url,
            "feishu_board_id": feishu_board_id,
            "created_by": created_by,
        }
        with transaction.atomic():
            if feishu_project_key:
                project, created = Project.objects.get_or_create(
                    space=space,
                    feishu_project_key=feishu_project_key,
                    defaults=defaults,
                )
            else:
                project = Project.objects.create(
                    space=space, feishu_project_key="", **defaults
                )
                created = True

            if created and created_by is not None:
                # 创建者默认成为主R（owner 唯一约束天然满足，因项目刚建无其他成员）
                ProjectMember.objects.get_or_create(
                    project=project,
                    user=created_by,
                    defaults={"role": ProjectRole.OWNER},
                )
        return project, created

    async def update(
        self,
        *,
        project_id: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        **fields: Any,
    ) -> Project:
        """更新项目可变字段（name/description/feishu_board_url/feishu_board_id）。

        仅白名单字段可改；``status`` 不在此处改（经 ``change_status``）。审计记 before/after。
        """
        allowed = {"name", "description", "feishu_board_url", "feishu_board_id"}
        changes = {k: v for k, v in fields.items() if k in allowed and v is not None}
        project, before = await self._update_locked(project_id, changes)
        if changes:
            actor_id = initiated_by_user_id or getattr(actor, "id", None)
            await AuditService.aemit(
                action=taxonomy.ACTION_PROJECT_UPDATED,
                actor=actor,
                target_type="project",
                target_id=project.id,
                target_repr=project.name,
                before=before,
                after={k: getattr(project, k) for k in changes},
                metadata={
                    "component": _COMPONENT,
                    "category": "caller",
                    "initiated_by_user_id": str(actor_id) if actor_id else "system",
                },
                source="api",
            )
            await apush_project_event(project.id, "updated", {"fields": list(changes)})
        return project

    @sync_to_async
    def _update_locked(
        self, project_id: Any, changes: dict[str, Any]
    ) -> tuple[Project, dict[str, Any]]:
        with transaction.atomic():
            project = Project.objects.select_for_update().get(pk=project_id)
            before = {k: getattr(project, k) for k in changes}
            for k, v in changes.items():
                setattr(project, k, v)
            if changes:
                project.save(update_fields=[*changes.keys(), "updated_at"])
        return project, before

    # ---- 状态机（PROJ-02） ----

    async def change_status(
        self,
        *,
        project_id: Any,
        to_status: str,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> Project:
        """驱动项目状态流转，非法流转 fail-loud（``ProjectTransitionError``）。

        合法流转表见 ``_LEGAL_TRANSITIONS``。状态变更经 ``AuditService.aemit`` 记
        before/after + initiated_by_user_id，写库后 best-effort WS 推送。
        """
        project, from_status, changed = await self._change_status_locked(
            project_id, to_status
        )
        if changed:
            actor_id = initiated_by_user_id or getattr(actor, "id", None)
            await AuditService.aemit(
                action=taxonomy.ACTION_PROJECT_STATUS_CHANGED,
                actor=actor,
                target_type="project",
                target_id=project.id,
                target_repr=project.name,
                before={"status": from_status},
                after={"status": to_status},
                metadata={
                    "component": _COMPONENT,
                    "category": "caller",
                    "initiated_by_user_id": str(actor_id) if actor_id else "system",
                },
                source="api",
            )
            await apush_project_event(
                project.id, "status_changed", {"from": from_status, "to": to_status}
            )
        return project

    async def archive(self, *, project_id: Any, **kwargs: Any) -> Project:
        """归档项目（developing/archived → archived）。"""
        return await self.change_status(
            project_id=project_id, to_status=ProjectStatus.ARCHIVED, **kwargs
        )

    async def terminate(self, *, project_id: Any, **kwargs: Any) -> Project:
        """终止项目（developing/archived → terminated，终态）。"""
        return await self.change_status(
            project_id=project_id, to_status=ProjectStatus.TERMINATED, **kwargs
        )

    @sync_to_async
    def _change_status_locked(
        self, project_id: Any, to_status: str
    ) -> tuple[Project, str, bool]:
        if to_status not in ProjectStatus.values:
            raise ProjectTransitionError(f"未知目标状态：{to_status}")
        with transaction.atomic():
            project = Project.objects.select_for_update().get(pk=project_id)
            from_status = project.status
            if from_status == to_status:
                # 幂等：同态不改、不审计、不推送（返回 changed=False）
                return project, from_status, False
            legal = self._LEGAL_TRANSITIONS.get(from_status, set())
            if to_status not in legal:
                raise ProjectTransitionError(
                    f"非法状态流转：{from_status} → {to_status}（项目 {project_id}）"
                )
            project.status = to_status
            project.save(update_fields=["status", "updated_at"])
        return project, from_status, True
