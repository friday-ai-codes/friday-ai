"""ProjectBranchService —— 分支↔项目绑定的唯一写入入口（BIND-01，INV-6）。

所有 ``ProjectBranch`` 的 create/delete 都经本 service 收口（旁路写表由
``test_project_branch_inv6_guard`` grep 守护）。模型层无业务写方法。

设计要点（对齐 ``MemoryService`` / ``ProjectService`` 既有范式）：
- **写仅成员 fail-closed**：bind/unbind 仅限项目成员（``ProjectMember``）；非成员一律
  ``ProjectBranchPermissionError`` 拒绝（与 visibility 无关，写恒守成员闸）。
- **bind 幂等**：``get_or_create((project, repository, branch_name))``；已存在按需回填
  source 漂移 / feishu_board_id。重复 bind 不产重复行、不抛。
- **unbind 幂等**：绑定不存在返回 ``False`` 不抛。
- 写入经 ``AuditService.aemit``（component=initiatives, category=caller,
  initiated_by_user_id 归因，无则 system）；结构化日志带 ``duration_ms``。
- async 面向 adrf/MCP；所有 ORM 经 ``sync_to_async`` 桥接。

Out-of-scope（Phase 89 handoff）：source=coding 的 git push 自动绑定、source=plan 的方案
流水线写入——本期仅提供 ``bind(source=…)`` 写收口 seam + 手动 REST（source=manual）。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from initiatives.models import BranchSource, ProjectBranch, ProjectMember

logger = structlog.get_logger(__name__)

__all__ = [
    "ProjectBranchService",
    "ProjectBranchError",
    "ProjectBranchPermissionError",
]

_COMPONENT = "initiatives"


class ProjectBranchError(Exception):
    """分支绑定操作非法基类（API 层转 400）。"""


class ProjectBranchPermissionError(ProjectBranchError):
    """非项目成员 bind/unbind 分支（写恒守成员闸 fail-closed，API 层转 403）。"""


def _user_id_of(user: Any) -> Any:
    return getattr(user, "id", None) if user is not None else None


class ProjectBranchService:
    """分支↔项目绑定唯一写入入口（INV-6）。"""

    # ---- 成员校验（写仅成员 fail-closed）----

    @staticmethod
    def _is_member_sync(project_id: Any, user: Any) -> bool:
        uid = _user_id_of(user)
        if uid is None:
            return False
        return ProjectMember.objects.filter(project_id=project_id, user_id=uid).exists()

    async def _assert_member(self, project_id: Any, user: Any) -> None:
        is_member = await sync_to_async(self._is_member_sync)(project_id, user)
        if not is_member:
            raise ProjectBranchPermissionError("仅项目成员可绑定/解绑分支")

    # ---- 绑定（bind / unbind / list）----

    async def bind(
        self,
        *,
        project_id: Any,
        repository_id: Any,
        branch_name: str,
        source: str = BranchSource.MANUAL,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        feishu_board_id: str = "",
        _skip_member_check: bool = False,
    ) -> ProjectBranch:
        """绑定分支到项目（BIND-01，幂等）。成员校验 + get_or_create + 审计。

        已存在的绑定按需回填 ``source`` 漂移与 ``feishu_board_id``（manual→plan/coding 升级
        由流水线调用，Phase 89 seam）。``_skip_member_check`` 供流水线内部复用。
        """
        started = time.monotonic()
        if not _skip_member_check:
            await self._assert_member(project_id, actor)
        binding, created = await self._bind_locked(
            project_id=project_id,
            repository_id=repository_id,
            branch_name=branch_name,
            source=source,
            created_by=actor,
            feishu_board_id=feishu_board_id,
        )
        actor_id = initiated_by_user_id or _user_id_of(actor)
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_BRANCH_BOUND,
            actor=actor,
            target_type="project_branch",
            target_id=binding.id,
            target_repr=f"{repository_id}:{branch_name} @ {project_id}",
            after={
                "project_id": str(project_id),
                "repository_id": str(repository_id),
                "branch_name": branch_name,
                "source": binding.source,
                "created": created,
            },
            metadata={
                "component": _COMPONENT,
                "category": "caller",
                "initiated_by_user_id": str(actor_id) if actor_id else "system",
            },
            source="api",
        )
        logger.info(
            "project_branch_bound",
            project_id=str(project_id),
            repository_id=str(repository_id),
            branch_name=branch_name,
            source=binding.source,
            created=created,
            initiated_by_user_id=str(actor_id) if actor_id else "system",
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            category="caller",
            component=_COMPONENT,
        )
        return binding

    @sync_to_async
    def _bind_locked(
        self,
        *,
        project_id: Any,
        repository_id: Any,
        branch_name: str,
        source: str,
        created_by: Any,
        feishu_board_id: str,
    ) -> tuple[ProjectBranch, bool]:
        with transaction.atomic():
            binding, created = ProjectBranch.objects.get_or_create(
                project_id=project_id,
                repository_id=repository_id,
                branch_name=branch_name,
                defaults={
                    "source": source,
                    "created_by": created_by,
                    "feishu_board_id": feishu_board_id,
                },
            )
            if not created:
                # 已存在：按需回填 source 漂移 / feishu_board_id（幂等不产重复行）。
                update_fields: list[str] = []
                if source and binding.source != source:
                    binding.source = source
                    update_fields.append("source")
                if feishu_board_id and binding.feishu_board_id != feishu_board_id:
                    binding.feishu_board_id = feishu_board_id
                    update_fields.append("feishu_board_id")
                if update_fields:
                    update_fields.append("updated_at")
                    binding.save(update_fields=update_fields)
        return binding, created

    async def unbind(
        self,
        *,
        project_id: Any,
        repository_id: Any,
        branch_name: str,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        _skip_member_check: bool = False,
    ) -> bool:
        """解绑分支（幂等）。成员校验 → 删除该绑定（不存在返回 False 不抛）→ 审计。"""
        started = time.monotonic()
        if not _skip_member_check:
            await self._assert_member(project_id, actor)
        snapshot = await self._unbind_locked(
            project_id=project_id,
            repository_id=repository_id,
            branch_name=branch_name,
        )
        if snapshot is None:
            return False
        actor_id = initiated_by_user_id or _user_id_of(actor)
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_BRANCH_UNBOUND,
            actor=actor,
            target_type="project_branch",
            target_id=snapshot["binding_id"],
            target_repr=f"{repository_id}:{branch_name} @ {project_id}",
            before={
                "project_id": str(project_id),
                "repository_id": str(repository_id),
                "branch_name": branch_name,
                "source": snapshot["source"],
            },
            metadata={
                "component": _COMPONENT,
                "category": "caller",
                "initiated_by_user_id": str(actor_id) if actor_id else "system",
            },
            source="api",
        )
        logger.info(
            "project_branch_unbound",
            project_id=str(project_id),
            repository_id=str(repository_id),
            branch_name=branch_name,
            initiated_by_user_id=str(actor_id) if actor_id else "system",
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            category="caller",
            component=_COMPONENT,
        )
        return True

    @sync_to_async
    def _unbind_locked(
        self,
        *,
        project_id: Any,
        repository_id: Any,
        branch_name: str,
    ) -> dict[str, Any] | None:
        with transaction.atomic():
            binding = (
                ProjectBranch.objects.select_for_update()
                .filter(
                    project_id=project_id,
                    repository_id=repository_id,
                    branch_name=branch_name,
                )
                .first()
            )
            if binding is None:
                return None
            snapshot = {"binding_id": binding.id, "source": binding.source}
            binding.delete()
        return snapshot

    async def list_for_project(self, *, project_id: Any) -> list[ProjectBranch]:
        """只读列出项目全部分支绑定（select_related repository）。"""
        return await sync_to_async(
            lambda: list(
                ProjectBranch.objects.filter(project_id=project_id).select_related(
                    "repository"
                )
            )
        )()
