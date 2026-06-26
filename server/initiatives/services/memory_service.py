"""MemoryService —— 项目记忆唯一写入入口（MEM-01~04，INV-6）。

所有 ``ProjectMemory`` / ``ProjectMemoryRevision`` / ``ProjectMemoryDraft`` 的写入都经本
service 收口（旁路写表由 ``test_memory_inv6_guard`` grep 守护）。模型层无业务方法。

关键约束：
- **MEM-02 成员校验 fail-closed**：贡献/编辑/确认草稿仅限项目成员（``ProjectMember``）；
  非成员（含私聊/未绑定项目会话的发起人）一律 ``MemoryPermissionError`` 拒绝。
- **MEM-03 可追溯**：append/edit 各落一条 ``ProjectMemoryRevision`` 快照（append-only），
  当前态读 ``ProjectMemory.content``，编辑历史永不就地丢失。
- **MEM-04 草稿**：LLM 仅产 ``pending`` 草稿（``create_draft``），**绝不自动写 active**；
  人工 ``confirm_draft`` 才入库为 ``ProjectMemory``。
- **脱敏不可绕过**：入库内容经 ``redact_secrets_in_text``；审计 before/after 经 AuditService
  内置 ``redact_for_ledger``。
- 写入经 ``AuditService.aemit``（component=initiatives, category=caller, initiated_by_user_id）；
  async ORM 走 ``sync_to_async``。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from common.logging import redact_secrets_in_text
from initiatives.models import (
    DraftStatus,
    ProjectMember,
    ProjectMemory,
    ProjectMemoryDraft,
    ProjectMemoryRevision,
    ProjectMemoryStatus,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "MemoryService",
    "MemoryError",
    "MemoryPermissionError",
    "MemoryStateError",
]

_COMPONENT = "initiatives"


class MemoryError(Exception):
    """记忆操作非法基类（API 层转 400）。"""


class MemoryPermissionError(MemoryError):
    """非项目成员贡献/编辑/确认记忆（MEM-02 fail-closed，API 层转 403）。"""


class MemoryStateError(MemoryError):
    """记忆/草稿状态非法（如重复确认已处理草稿，API 层转 400）。"""


def _user_id_of(user: Any) -> Any:
    return getattr(user, "id", None) if user is not None else None


class MemoryService:
    """项目记忆唯一写入入口（INV-6）。"""

    # ---- 成员校验（MEM-02 fail-closed）----

    @staticmethod
    def _is_member_sync(project_id: Any, user: Any) -> bool:
        uid = _user_id_of(user)
        if uid is None:
            return False
        return ProjectMember.objects.filter(project_id=project_id, user_id=uid).exists()

    async def _assert_member(self, project_id: Any, user: Any) -> None:
        """非项目成员 fail-closed 拒绝（MEM-02）。"""
        is_member = await sync_to_async(self._is_member_sync)(project_id, user)
        if not is_member:
            raise MemoryPermissionError(
                "仅项目成员可贡献/编辑项目记忆（非成员/私聊会话不纳入）"
            )

    # ---- 记忆条目（MEM-01/03）----

    async def append(
        self,
        *,
        project_id: Any,
        content: str,
        contributor: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        _skip_member_check: bool = False,
        _skip_doc_push: bool = False,
    ) -> ProjectMemory:
        """新增一条项目记忆（MEM-01）。成员校验 + 脱敏 + 初始 revision 快照。

        ``_skip_member_check`` 仅供 ``confirm_draft`` 内部复用（草稿确认时成员校验已在外层完成）。
        ``_skip_doc_push``：飞书镜像编辑（DocSyncService pull 回写）传 True，防 pull→push 回声（83-03）。
        """
        if not _skip_member_check:
            await self._assert_member(project_id, contributor)
        redacted = redact_secrets_in_text(content or "")
        memory = await self._append_locked(
            project_id=project_id, content=redacted, contributor=contributor
        )
        await self._emit(
            taxonomy.ACTION_PROJECT_MEMORY_CREATED,
            actor=actor or contributor,
            initiated_by_user_id=initiated_by_user_id,
            target_id=memory.id,
            target_repr=str(memory.id),
            after={"project_id": str(project_id), "status": memory.status},
        )
        if not _skip_doc_push:
            await self._schedule_doc_push(project_id, initiated_by_user_id)
        return memory

    @sync_to_async
    def _append_locked(
        self, *, project_id: Any, content: str, contributor: Any
    ) -> ProjectMemory:
        with transaction.atomic():
            memory = ProjectMemory.objects.create(
                project_id=project_id,
                content=content,
                contributor=contributor,
                status=ProjectMemoryStatus.ACTIVE,
            )
            # 初始 revision 快照（MEM-03 可追溯，append-only）。
            ProjectMemoryRevision.objects.create(
                memory=memory, content=content, editor=contributor
            )
        return memory

    async def edit(
        self,
        *,
        memory_id: Any,
        content: str,
        editor: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        _skip_doc_push: bool = False,
    ) -> ProjectMemory:
        """人工编辑/覆盖记忆（MEM-03）。成员校验 + 脱敏 + append revision（保留可追溯）。

        ``_skip_doc_push``：飞书镜像编辑（DocSyncService pull 回写）传 True，防 pull→push 回声。
        """
        project_id = await self._project_id_of_memory(memory_id)
        await self._assert_member(project_id, editor)
        redacted = redact_secrets_in_text(content or "")
        memory, before = await self._edit_locked(
            memory_id=memory_id, content=redacted, editor=editor
        )
        await self._emit(
            taxonomy.ACTION_PROJECT_MEMORY_EDITED,
            actor=actor or editor,
            initiated_by_user_id=initiated_by_user_id,
            target_id=memory.id,
            target_repr=str(memory.id),
            before={"content": before},
            after={"content": redacted},
        )
        if not _skip_doc_push:
            await self._schedule_doc_push(project_id, initiated_by_user_id)
        return memory

    @sync_to_async
    def _edit_locked(
        self, *, memory_id: Any, content: str, editor: Any
    ) -> tuple[ProjectMemory, str]:
        with transaction.atomic():
            memory = ProjectMemory.objects.select_for_update().get(pk=memory_id)
            before = memory.content
            memory.content = content
            memory.save(update_fields=["content", "updated_at"])
            # append-only 快照新态（编辑历史链，绝不就地丢历史）。
            ProjectMemoryRevision.objects.create(
                memory=memory, content=content, editor=editor
            )
        return memory, before

    async def sync_edit(
        self,
        *,
        memory_id: Any,
        content: str,
        editor: Any,
        initiated_by_user_id: Any = None,
    ) -> dict[str, Any]:
        """飞书镜像编辑受限入口（origin=feishu_sync，OQ-1）：兼顾 SYNC-06 fail-soft 与 MEM-02。

        - **成员**：正常落 active + append revision（飞书优先覆盖，旧态留在 revision 链，
          capture-never-clobber 由历史链天然保证），返回 ``{"applied": True, "attribution": "member"}``。
        - **非成员**：**绝不抛**（区别于前端贡献 ``edit`` 的 MEM-02 fail-closed）——把飞书内容
          append 为 ``ProjectMemoryRevision`` 留痕但 **不改 active**（不进 active ProjectMemory），
          归因 ``system``（未解析用户）/``unmapped``（已解析但非成员），返回
          ``{"applied": False, "attribution": ...}``。绝不静默丢用户内容（SYNC-04）。

        始终脱敏入库（``redact_secrets_in_text``）。``_skip_doc_push`` 隐含 True（飞书镜像回写，
        防 pull→push 回声，T-83-03-ECHO）。
        """
        project_id = await self._project_id_of_memory(memory_id)
        is_member = await sync_to_async(self._is_member_sync)(project_id, editor)
        redacted = redact_secrets_in_text(content or "")
        if is_member:
            memory, before = await self._edit_locked(
                memory_id=memory_id, content=redacted, editor=editor
            )
            await self._emit(
                taxonomy.ACTION_PROJECT_MEMORY_EDITED,
                actor=editor,
                initiated_by_user_id=initiated_by_user_id,
                target_id=memory.id,
                target_repr=str(memory.id),
                before={"content": before},
                after={"content": redacted},
            )
            return {"applied": True, "attribution": "member"}
        # 非成员飞书编辑：capture 为 revision（不进 active），归因受限，绝不抛、绝不丢。
        await self._capture_sync_revision_locked(
            memory_id=memory_id, content=redacted, editor=editor
        )
        attribution = "system" if _user_id_of(editor) is None else "unmapped"
        return {"applied": False, "attribution": attribution}

    @sync_to_async
    def _capture_sync_revision_locked(
        self, *, memory_id: Any, content: str, editor: Any
    ) -> None:
        """非成员飞书镜像编辑 → append-only 留痕（绝不改 active，capture-never-clobber）。"""
        with transaction.atomic():
            memory = ProjectMemory.objects.get(pk=memory_id)
            ProjectMemoryRevision.objects.create(
                memory=memory, content=content, editor=editor
            )

    async def supersede(
        self,
        *,
        memory_id: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        _skip_doc_push: bool = False,
    ) -> ProjectMemory:
        """废弃记忆（status → superseded）。成员校验。

        ``_skip_doc_push``：飞书镜像删除（DocSyncService pull 回写）传 True，防 pull→push 回声。
        """
        project_id = await self._project_id_of_memory(memory_id)
        await self._assert_member(project_id, actor)
        memory = await self._supersede_locked(memory_id)
        await self._emit(
            taxonomy.ACTION_PROJECT_MEMORY_SUPERSEDED,
            actor=actor,
            initiated_by_user_id=initiated_by_user_id,
            target_id=memory.id,
            target_repr=str(memory.id),
            after={"status": memory.status},
        )
        if not _skip_doc_push:
            await self._schedule_doc_push(project_id, initiated_by_user_id)
        return memory

    @sync_to_async
    def _supersede_locked(self, memory_id: Any) -> ProjectMemory:
        with transaction.atomic():
            memory = ProjectMemory.objects.select_for_update().get(pk=memory_id)
            memory.status = ProjectMemoryStatus.SUPERSEDED
            memory.save(update_fields=["status", "updated_at"])
        return memory

    @sync_to_async
    def _project_id_of_memory(self, memory_id: Any) -> Any:
        return ProjectMemory.objects.values_list("project_id", flat=True).get(pk=memory_id)

    # ---- 草稿（MEM-04）----

    async def create_draft(
        self,
        *,
        project_id: Any,
        content: str,
        proposed_by: Any = None,
        source_conversation_id: Any = None,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        _skip_member_check: bool = False,
    ) -> ProjectMemoryDraft:
        """创建记忆草稿（pending，MEM-04）。脱敏入库，**绝不自动写 active**。

        LLM 蒸馏（``MemoryDistiller``）调本入口产 pending 草稿；人工确认才入库。
        ``_skip_member_check`` 供蒸馏器内部使用（成员校验已在蒸馏入口完成）。
        """
        if not _skip_member_check and proposed_by is not None:
            await self._assert_member(project_id, proposed_by)
        redacted = redact_secrets_in_text(content or "")
        draft = await self._create_draft_locked(
            project_id=project_id,
            content=redacted,
            proposed_by=proposed_by,
            source_conversation_id=source_conversation_id,
        )
        await self._emit(
            taxonomy.ACTION_PROJECT_MEMORY_DRAFT_CREATED,
            actor=actor or proposed_by,
            initiated_by_user_id=initiated_by_user_id,
            target_id=draft.id,
            target_repr=str(draft.id),
            after={"project_id": str(project_id), "status": draft.status},
        )
        return draft

    @sync_to_async
    def _create_draft_locked(
        self,
        *,
        project_id: Any,
        content: str,
        proposed_by: Any,
        source_conversation_id: Any,
    ) -> ProjectMemoryDraft:
        return ProjectMemoryDraft.objects.create(
            project_id=project_id,
            content=content,
            proposed_by=proposed_by,
            source_conversation_id=source_conversation_id,
            status=DraftStatus.PENDING,
        )

    async def confirm_draft(
        self,
        *,
        draft_id: Any,
        confirmer: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> ProjectMemory:
        """人工确认草稿入库为 active 记忆（MEM-04）。成员校验 fail-closed。"""
        draft = await self._get_draft(draft_id)
        if draft.status != DraftStatus.PENDING:
            raise MemoryStateError(f"草稿状态为 {draft.status}，不可重复确认")
        await self._assert_member(draft.project_id, confirmer)
        # 入库为 active 记忆（复用 append；成员校验已完成）。
        memory = await self.append(
            project_id=draft.project_id,
            content=draft.content,
            contributor=confirmer,
            actor=actor or confirmer,
            initiated_by_user_id=initiated_by_user_id,
            _skip_member_check=True,
        )
        await self._mark_draft_confirmed(draft_id, memory)
        await self._emit(
            taxonomy.ACTION_PROJECT_MEMORY_DRAFT_CONFIRMED,
            actor=actor or confirmer,
            initiated_by_user_id=initiated_by_user_id,
            target_id=draft_id,
            target_repr=str(draft_id),
            after={"memory_id": str(memory.id)},
        )
        return memory

    @sync_to_async
    def _mark_draft_confirmed(self, draft_id: Any, memory: ProjectMemory) -> None:
        with transaction.atomic():
            draft = ProjectMemoryDraft.objects.select_for_update().get(pk=draft_id)
            draft.status = DraftStatus.CONFIRMED
            draft.confirmed_memory = memory
            draft.save(update_fields=["status", "confirmed_memory", "updated_at"])

    async def reject_draft(
        self,
        *,
        draft_id: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> ProjectMemoryDraft:
        """拒绝草稿（status → rejected）。成员校验。"""
        draft = await self._get_draft(draft_id)
        if draft.status != DraftStatus.PENDING:
            raise MemoryStateError(f"草稿状态为 {draft.status}，不可重复拒绝")
        await self._assert_member(draft.project_id, actor)
        rejected = await self._mark_draft_rejected(draft_id)
        await self._emit(
            taxonomy.ACTION_PROJECT_MEMORY_DRAFT_REJECTED,
            actor=actor,
            initiated_by_user_id=initiated_by_user_id,
            target_id=draft_id,
            target_repr=str(draft_id),
            after={"status": rejected.status},
        )
        return rejected

    @sync_to_async
    def _mark_draft_rejected(self, draft_id: Any) -> ProjectMemoryDraft:
        with transaction.atomic():
            draft = ProjectMemoryDraft.objects.select_for_update().get(pk=draft_id)
            draft.status = DraftStatus.REJECTED
            draft.save(update_fields=["status", "updated_at"])
        return draft

    @sync_to_async
    def _get_draft(self, draft_id: Any) -> ProjectMemoryDraft:
        return ProjectMemoryDraft.objects.get(pk=draft_id)

    # ---- 系统区写后钩子（debounce defer push，SYNC-02 / 83-03）----

    @staticmethod
    async def _schedule_doc_push(project_id: Any, initiated_by_user_id: Any) -> None:
        """MEMORY 系统区写后调统一调度钩子（fail-soft 不反噬记忆写主流程）。"""
        from initiatives.models import DocType
        from initiatives.services.doc_push_scheduler import schedule_doc_push

        await schedule_doc_push(
            project_id=project_id,
            doc_type=DocType.MEMORY,
            initiated_by_user_id=(
                str(initiated_by_user_id) if initiated_by_user_id else None
            ),
        )

    # ---- 审计 ----

    async def _emit(
        self,
        action: str,
        *,
        actor: Any,
        initiated_by_user_id: Any,
        target_id: Any,
        target_repr: str,
        before: Any = None,
        after: Any = None,
    ) -> None:
        actor_id = initiated_by_user_id or _user_id_of(actor)
        await AuditService.aemit(
            action=action,
            actor=actor,
            target_type="project_memory",
            target_id=target_id,
            target_repr=target_repr,
            before=before,
            after=after,
            metadata={
                "component": _COMPONENT,
                "category": "caller",
                "initiated_by_user_id": str(actor_id) if actor_id else "system",
            },
            source="api",
        )
