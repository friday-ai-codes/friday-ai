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
from initiatives.models import (
    LinkProvenance,
    Project,
    ProjectMember,
    ProjectRole,
    ProjectStatus,
    ProjectWorkItemLink,
)
from initiatives.services.realtime import apush_project_event

logger = structlog.get_logger(__name__)

__all__ = ["ProjectService", "ProjectTransitionError", "ProjectMemberError"]

# 审计来源/组件常量（component=initiatives）。
_COMPONENT = "initiatives"


class ProjectTransitionError(Exception):
    """项目状态非法流转 fail-loud（API 层转 400）。"""


class ProjectMemberError(Exception):
    """项目成员操作非法 fail-loud（如裸改主R角色 / 转移给非成员，API 层转 400）。"""


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

    # ---- 成员协作（MEMBER-01/02） ----

    async def add_member(
        self,
        *,
        project_id: Any,
        user: Any,
        role: str = ProjectRole.BACKEND,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> tuple[ProjectMember, bool]:
        """添加项目成员（一人一项目一行，get_or_create 幂等）。

        ``role=owner`` 经此入口被拒（主R 唯一且转移须经 ``transfer_owner``）。返回
        ``(member, created)``；created=False 表示已是成员（不重复审计）。
        """
        if role == ProjectRole.OWNER:
            raise ProjectMemberError("主R（owner）不可经 add_member 设置，请用 transfer_owner")
        member, created = await self._add_member_locked(project_id, user, role)
        if created:
            actor_id = initiated_by_user_id or getattr(actor, "id", None)
            await AuditService.aemit(
                action=taxonomy.ACTION_PROJECT_MEMBER_ADDED,
                actor=actor,
                target_type="project_member",
                target_id=member.id,
                target_repr=f"{getattr(user, 'username', user)} @ {project_id}",
                after={
                    "project_id": str(project_id),
                    "user_id": str(getattr(user, "id", user)),
                    "role": role,
                },
                metadata={
                    "component": _COMPONENT,
                    "category": "caller",
                    "initiated_by_user_id": str(actor_id) if actor_id else "system",
                },
                source="api",
            )
            await apush_project_event(
                project_id,
                "member_added",
                {"user_id": str(getattr(user, "id", user)), "role": role},
            )
        return member, created

    @sync_to_async
    def _add_member_locked(
        self, project_id: Any, user: Any, role: str
    ) -> tuple[ProjectMember, bool]:
        with transaction.atomic():
            return ProjectMember.objects.get_or_create(
                project_id=project_id, user=user, defaults={"role": role}
            )

    async def change_member_role(
        self,
        *,
        project_id: Any,
        user_id: Any,
        role: str,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> ProjectMember:
        """变更成员角色（不含主R）。

        升/降为 owner 一律拒（用 ``transfer_owner``）；改当前 owner 的角色亦拒（避免留下
        无主项目）。
        """
        if role == ProjectRole.OWNER:
            raise ProjectMemberError("主R（owner）转移须经 transfer_owner，不可裸改角色")
        member, old_role = await self._change_member_role_locked(
            project_id, user_id, role
        )
        if old_role != role:
            actor_id = initiated_by_user_id or getattr(actor, "id", None)
            await AuditService.aemit(
                action=taxonomy.ACTION_PROJECT_MEMBER_ROLE_CHANGED,
                actor=actor,
                target_type="project_member",
                target_id=member.id,
                target_repr=f"{member.user_id} @ {project_id}",
                before={"role": old_role},
                after={"role": role},
                metadata={
                    "component": _COMPONENT,
                    "category": "caller",
                    "initiated_by_user_id": str(actor_id) if actor_id else "system",
                },
                source="api",
            )
            await apush_project_event(
                project_id,
                "member_role_changed",
                {"user_id": str(user_id), "role": role},
            )
        return member

    @sync_to_async
    def _change_member_role_locked(
        self, project_id: Any, user_id: Any, role: str
    ) -> tuple[ProjectMember, str]:
        with transaction.atomic():
            member = ProjectMember.objects.select_for_update().get(
                project_id=project_id, user_id=user_id
            )
            if member.role == ProjectRole.OWNER:
                raise ProjectMemberError("不可直接改主R 角色，请用 transfer_owner 转移")
            old_role = member.role
            if old_role != role:
                member.role = role
                member.save(update_fields=["role", "updated_at"])
        return member, old_role

    async def remove_member(
        self,
        *,
        project_id: Any,
        user_id: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> None:
        """移除项目成员（主R 不可直接移除，须先 ``transfer_owner``）。"""
        snapshot = await self._remove_member_locked(project_id, user_id)
        actor_id = initiated_by_user_id or getattr(actor, "id", None)
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_MEMBER_REMOVED,
            actor=actor,
            target_type="project_member",
            target_id=snapshot["member_id"],
            target_repr=f"{user_id} @ {project_id}",
            before={
                "project_id": str(project_id),
                "user_id": str(user_id),
                "role": snapshot["role"],
            },
            metadata={
                "component": _COMPONENT,
                "category": "caller",
                "initiated_by_user_id": str(actor_id) if actor_id else "system",
            },
            source="api",
        )
        await apush_project_event(
            project_id, "member_removed", {"user_id": str(user_id)}
        )

    @sync_to_async
    def _remove_member_locked(self, project_id: Any, user_id: Any) -> dict[str, Any]:
        with transaction.atomic():
            member = ProjectMember.objects.select_for_update().get(
                project_id=project_id, user_id=user_id
            )
            if member.role == ProjectRole.OWNER:
                raise ProjectMemberError(
                    "主R（owner）不可直接移除，请先 transfer_owner 转移后再移除"
                )
            snapshot = {"member_id": member.id, "role": member.role}
            member.delete()
        return snapshot

    async def transfer_owner(
        self,
        *,
        project_id: Any,
        new_owner_user_id: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> ProjectMember:
        """转移主R（owner）—— 原子操作（MEMBER-02）。

        新主R 须为既有成员。转移 = 旧 owner 降级为新 owner 转移前的角色（角色互换），新 owner
        升为 owner；先降旧再升新，任意语句间不存在两个 owner（满足 owner 唯一约束）。无既有
        owner 时直接升新 owner。审计 + WS 推送。
        """
        member, old_owner_id, changed = await self._transfer_owner_locked(
            project_id, new_owner_user_id
        )
        if changed:
            actor_id = initiated_by_user_id or getattr(actor, "id", None)
            await AuditService.aemit(
                action=taxonomy.ACTION_PROJECT_OWNER_TRANSFERRED,
                actor=actor,
                target_type="project",
                target_id=project_id,
                target_repr=str(project_id),
                before={"owner_user_id": str(old_owner_id) if old_owner_id else ""},
                after={"owner_user_id": str(new_owner_user_id)},
                metadata={
                    "component": _COMPONENT,
                    "category": "caller",
                    "initiated_by_user_id": str(actor_id) if actor_id else "system",
                },
                source="api",
            )
            await apush_project_event(
                project_id,
                "owner_transferred",
                {
                    "from_user_id": str(old_owner_id) if old_owner_id else "",
                    "to_user_id": str(new_owner_user_id),
                },
            )
        return member

    @sync_to_async
    def _transfer_owner_locked(
        self, project_id: Any, new_owner_user_id: Any
    ) -> tuple[ProjectMember, Any, bool]:
        with transaction.atomic():
            new_member = (
                ProjectMember.objects.select_for_update()
                .filter(project_id=project_id, user_id=new_owner_user_id)
                .first()
            )
            if new_member is None:
                raise ProjectMemberError("新主R 必须先是项目成员")
            if new_member.role == ProjectRole.OWNER:
                # 已是主R，幂等无操作
                return new_member, new_owner_user_id, False

            current_owner = (
                ProjectMember.objects.select_for_update()
                .filter(project_id=project_id, role=ProjectRole.OWNER)
                .first()
            )
            old_owner_id = None
            new_prev_role = new_member.role
            if current_owner is not None:
                old_owner_id = current_owner.user_id
                # 先降旧 owner（取新 owner 转移前的角色，互换），避免两 owner 并存
                current_owner.role = new_prev_role
                current_owner.save(update_fields=["role", "updated_at"])
            # 再升新 owner
            new_member.role = ProjectRole.OWNER
            new_member.save(update_fields=["role", "updated_at"])
        return new_member, old_owner_id, True

    # ---- 工作项组合（COMPOSE-01/02） ----

    async def attach_work_item(
        self,
        *,
        project_id: Any,
        work_item: Any,
        provenance: str = LinkProvenance.MANUAL,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> tuple[ProjectWorkItemLink, bool]:
        """把一个 WorkItem 经关系边挂入项目（COMPOSE-01/02，get_or_create 幂等）。

        story 与缺陷统一复用 ``delivery.WorkItem``（按 ``work_item_type`` 区分），不重复建模。
        重复并入只返回既有 link（``created=False``，不重复审计/推送）——board_derived 自动并入
        与 manual 手动并入共用此入口，幂等去重靠 ``unique_together(project, work_item)``。

        Args:
            project_id: 目标项目 id。
            work_item: ``delivery.WorkItem`` 实例（已由 ``WorkItemService`` 落库，INV-6）。
            provenance: 来源（board_derived / manual）。
            actor / initiated_by_user_id: 审计绑定。

        Returns:
            ``(link, created)``。
        """
        link, created = await self._attach_work_item_locked(
            project_id, work_item, provenance
        )
        if created:
            actor_id = initiated_by_user_id or getattr(actor, "id", None)
            await AuditService.aemit(
                action=taxonomy.ACTION_PROJECT_WORK_ITEM_ATTACHED,
                actor=actor,
                target_type="project_work_item_link",
                target_id=link.id,
                target_repr=f"{getattr(work_item, 'id', work_item)} @ {project_id}",
                after={
                    "project_id": str(project_id),
                    "work_item_id": str(getattr(work_item, "id", work_item)),
                    "work_item_type": getattr(work_item, "work_item_type", ""),
                    "provenance": provenance,
                },
                metadata={
                    "component": _COMPONENT,
                    "category": "caller",
                    "initiated_by_user_id": str(actor_id) if actor_id else "system",
                },
                source="api",
            )
            await apush_project_event(
                project_id,
                "work_item_attached",
                {
                    "work_item_id": str(getattr(work_item, "id", work_item)),
                    "provenance": provenance,
                },
            )
        return link, created

    @sync_to_async
    def _attach_work_item_locked(
        self, project_id: Any, work_item: Any, provenance: str
    ) -> tuple[ProjectWorkItemLink, bool]:
        with transaction.atomic():
            return ProjectWorkItemLink.objects.get_or_create(
                project_id=project_id,
                work_item=work_item,
                defaults={"provenance": provenance},
            )

    async def detach_work_item(
        self,
        *,
        project_id: Any,
        work_item_id: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> bool:
        """从项目移除一个 WorkItem 组合关系（COMPOSE-01 手动移除）。

        link 不存在时返回 ``False`` 不抛（幂等移除）。

        Returns:
            ``True`` 表示移除了一条 link，``False`` 表示原本未关联。
        """
        snapshot = await self._detach_work_item_locked(project_id, work_item_id)
        if snapshot is None:
            return False
        actor_id = initiated_by_user_id or getattr(actor, "id", None)
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_WORK_ITEM_DETACHED,
            actor=actor,
            target_type="project_work_item_link",
            target_id=snapshot["link_id"],
            target_repr=f"{work_item_id} @ {project_id}",
            before={
                "project_id": str(project_id),
                "work_item_id": str(work_item_id),
                "provenance": snapshot["provenance"],
            },
            metadata={
                "component": _COMPONENT,
                "category": "caller",
                "initiated_by_user_id": str(actor_id) if actor_id else "system",
            },
            source="api",
        )
        await apush_project_event(
            project_id, "work_item_detached", {"work_item_id": str(work_item_id)}
        )
        return True

    @sync_to_async
    def _detach_work_item_locked(
        self, project_id: Any, work_item_id: Any
    ) -> dict[str, Any] | None:
        with transaction.atomic():
            link = (
                ProjectWorkItemLink.objects.select_for_update()
                .filter(project_id=project_id, work_item_id=work_item_id)
                .first()
            )
            if link is None:
                return None
            snapshot = {"link_id": link.id, "provenance": link.provenance}
            link.delete()
        return snapshot
