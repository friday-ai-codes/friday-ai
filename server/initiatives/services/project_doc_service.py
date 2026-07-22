"""ProjectDocService —— 项目工作区文件/映射/API 清单的唯一写入入口（WS-04/DOC-01~06，INV-6）。

所有 ``ProjectDoc`` / ``ProjectDocBlockMap`` / ``ProjectStateApi`` 的 create/update 都经本
service 收口（旁路写表由 ``test_project_doc_inv6_guard`` grep 守护）。模型层不提供业务
create/save 方法。

设计要点（逐字镜像 ``ProjectService`` 范式）：
- async 面向 adrf/channels；ORM 在 async 经 ``sync_to_async`` 桥接（``_xxx_locked`` +
  ``transaction.atomic`` + ``select_for_update``）。
- 写操作（state_api 增删）经 ``AuditService.aemit``（category=caller, component=initiatives,
  initiated_by_user_id；未知归因记 ``system``）。
- 后台 provision 编排（建飞书文件夹 + 5 文件 + 互链 + 看板描述追加）经
  ``services.background_runner.run_in_background`` 调度，**携带 initiated_by_user_id** 并在
  worker 入口 re-bind 用户上下文；飞书外呼任何失败 **fail-soft**（置对应 ``ProjectDoc``
  ``sync_status=broken`` 持久化 DB，绝不阻断项目创建主流程）。
- ``create_folder`` 5QPS/不可并发 → 文件夹 + 5 文件 + 互链 + 看板 **全部串行 await**
  （绝不 ``asyncio.gather``）。
- 飞书上游响应体/异常文本入日志前经 ``redact_secrets_in_text`` 脱敏；日志只记
  doc_id/doc_type/计数/sync_status，**绝不**记正文/token 明文。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from initiatives.models import (
    ApiSource,
    ApiStatus,
    DocSection,
    DocSyncStatus,
    DocType,
    ProjectDoc,
    ProjectDocBlockMap,
    ProjectDocBlockRevision,
    ProjectStateApi,
)

logger = structlog.get_logger(__name__)

__all__ = ["ProjectDocService"]

# 审计组件常量。
_COMPONENT = "initiatives"

# 工作区 5 文件固定建序（create_folder 5QPS 串行约束，逐个 await）。
_DOC_ORDER: tuple[str, ...] = (
    DocType.MEMORY,
    DocType.STATE,
    DocType.MILESTONES,
    DocType.RESEARCH,
    DocType.PREFLIGHT,
)

# 文件类型 → (标题后缀, 初始正文模板)。zh-CN，最小占位，正文长文留 Phase 84 编辑面。
_DOC_TEMPLATES: dict[str, tuple[str, str]] = {
    DocType.MEMORY: ("记忆 (MEMORY)", "# 项目记忆\n\n> 本文件由 Friday 项目工作区自动创建，记忆条目以 Friday 内记忆为准、此处镜像渲染。\n"),
    DocType.STATE: ("状态 (STATE)", "# 项目状态\n\n## 已完成 API 清单\n\n（结构化清单由 Friday 派生渲染）\n\n## 备注\n\n"),
    DocType.MILESTONES: ("里程碑 (MILESTONES)", "# 里程碑\n\n> 以关联工作项实时派生 + 人工补充段。\n"),
    DocType.RESEARCH: ("调研 (RESEARCH)", "# 项目调研\n\n> 项目调研长文。\n"),
    DocType.PREFLIGHT: ("预检 (PREFLIGHT)", "# 预检\n\n> 前置风险 / 修复清单。\n"),
}

# 看板描述「项目工作区」段幂等 marker（read-then-append，绝不整篇覆盖）。
_WORKSPACE_MARKER = "📁 项目工作区"


class ProjectDocService:
    """ProjectDoc / ProjectDocBlockMap / ProjectStateApi 唯一写入入口（INV-6）。"""

    # ---- ProjectDoc 写入 ----

    async def upsert_doc(
        self,
        *,
        project_id: Any,
        doc_type: str,
        **fields: Any,
    ) -> ProjectDoc:
        """按 (project, doc_type) 幂等 upsert 文件容器（DOC-01~05）。

        ``fields`` 中传入的列（如 ``feishu_document_id`` / ``feishu_doc_token`` /
        ``sync_status``）在新建与更新时均落库；未传列保持原值。
        """
        doc, _created = await self._upsert_doc_locked(project_id, doc_type, fields)
        return doc

    @sync_to_async
    def _upsert_doc_locked(
        self, project_id: Any, doc_type: str, fields: dict[str, Any]
    ) -> tuple[ProjectDoc, bool]:
        with transaction.atomic():
            return ProjectDoc.objects.update_or_create(
                project_id=project_id, doc_type=doc_type, defaults=fields
            )

    # ---- IDE stop hook RESEARCH active append（HOOK-02，用户授权 accepted deviation）----

    async def append_research_note(
        self,
        *,
        project_id: Any,
        content: str,
        contributor: Any,
        initiated_by_user_id: Any = None,
    ) -> dict[str, Any]:
        """IDE stop hook 写回 RESEARCH **active append**（accepted deviation，2026-06-26）。

        把脱敏后的调研内容 **append**（绝不就地覆盖既有正文，与 MILESTONE-PROPOSAL §4.2
        「Agent 写一律 append」一致）到该项目 RESEARCH ``ProjectDoc`` 正文
        （``last_synced_snapshot`` 追加段），不落 draft、不需人工确认。

        强制保留的兜底（绝不绕过）：

        - **非成员静默跳过**：``contributor`` 非项目成员 → 返回
          ``{"applied": False, "reason": "not_member"}``，不写任何表、**绝不抛**（T-86-01-03）。
        - **脱敏不可绕过**：入库前经 ``redact_secrets_in_text``（T-86-01-02）。
        - **审计可回滚**：``AuditService.aemit``（``project.research_note_appended``，
          category=caller，绑定 ``initiated_by_user_id``），可经人工编辑/移除撤销
          （T-86-01-01/05）。
        - **归因**：``initiated_by_user_id`` 优先；未提供取 ``contributor.id``；仍无 → ``system``。

        写入收口经本 service（INV-6，``ProjectDoc`` 写表只此一处）。
        """
        from common.logging import redact_secrets_in_text

        is_member = await self._ais_project_member(project_id, contributor)
        if not is_member:
            return {"applied": False, "reason": "not_member"}
        redacted = redact_secrets_in_text(content or "")
        doc = await self.upsert_doc(project_id=project_id, doc_type=DocType.RESEARCH)
        await self._append_research_snapshot_locked(doc.id, redacted)
        actor_id = initiated_by_user_id or getattr(contributor, "id", None)
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_RESEARCH_NOTE_APPENDED,
            actor=contributor,
            target_type="project_doc",
            target_id=doc.id,
            target_repr=f"research @ {project_id}",
            after={"project_id": str(project_id), "doc_type": DocType.RESEARCH},
            metadata={
                "component": _COMPONENT,
                "category": "caller",
                "initiated_by_user_id": str(actor_id) if actor_id else "system",
            },
            source="api",
        )
        # 写时增量材料化（CTX-01/02）：RESEARCH 正文写后物化进 delivery_knowledge，
        # best-effort 绝不反噬写主流程。
        await self._schedule_materialization(doc.id, actor_id)
        return {"applied": True, "doc_id": str(doc.id)}

    @staticmethod
    async def _ais_project_member(project_id: Any, user: Any) -> bool:
        """项目成员判定（与 ``MemoryService`` 同口径，fail-closed：无 user → 非成员）。"""
        from initiatives.models import ProjectMember

        uid = getattr(user, "id", None)
        if uid is None:
            return False
        return await ProjectMember.objects.filter(
            project_id=project_id, user_id=uid
        ).aexists()

    @sync_to_async
    def _append_research_snapshot_locked(self, doc_id: Any, addition: str) -> str:
        """把 ``addition`` append 到 RESEARCH ``last_synced_snapshot`` 末尾（append-only，
        绝不整篇覆盖既有正文）。返回 append 后的全文。"""
        with transaction.atomic():
            doc = ProjectDoc.objects.select_for_update().get(pk=doc_id)
            base = doc.last_synced_snapshot or ""
            section = f"\n\n## IDE 自动沉淀\n\n{addition}\n" if base else f"{addition}\n"
            doc.last_synced_snapshot = base + section
            doc.save(update_fields=["last_synced_snapshot", "updated_at"])
        return doc.last_synced_snapshot

    async def set_doc_feishu(
        self,
        *,
        doc_id: Any,
        document_id: str,
        doc_token: str,
        sync_status: str = DocSyncStatus.READY,
    ) -> ProjectDoc:
        """落某文件的飞书映射（document_id/doc_token）+ 同步状态。"""
        return await self._set_doc_feishu_locked(doc_id, document_id, doc_token, sync_status)

    @sync_to_async
    def _set_doc_feishu_locked(
        self, doc_id: Any, document_id: str, doc_token: str, sync_status: str
    ) -> ProjectDoc:
        with transaction.atomic():
            doc = ProjectDoc.objects.select_for_update().get(pk=doc_id)
            doc.feishu_document_id = document_id
            doc.feishu_doc_token = doc_token
            doc.sync_status = sync_status
            doc.save(
                update_fields=[
                    "feishu_document_id",
                    "feishu_doc_token",
                    "sync_status",
                    "updated_at",
                ]
            )
        return doc

    async def set_sync_status(self, *, doc_id: Any, status: str) -> ProjectDoc:
        """持久化文件同步状态（broken 落 DB，供一键重建）。"""
        return await self._set_sync_status_locked(doc_id, status)

    @sync_to_async
    def _set_sync_status_locked(self, doc_id: Any, status: str) -> ProjectDoc:
        with transaction.atomic():
            doc = ProjectDoc.objects.select_for_update().get(pk=doc_id)
            doc.sync_status = status
            doc.save(update_fields=["sync_status", "updated_at"])
        return doc

    async def advance_sync_revision(
        self,
        *,
        doc_id: Any,
        expected_revision: int,
        new_revision: int,
        snapshot: str,
    ) -> bool:
        """CAS 推进同步水位（乐观并发兜底，Pitfall 3）：仅当 ``last_synced_revision`` 仍等于
        ``expected_revision`` 时把它推进到 ``new_revision`` 并落新快照，返回是否更新成功。

        条件 update 不依赖 durable doing 锁（in-process fallback 忽略 lock）：并发 pull/push
        对同一文档时，先提交者推进成功，后者 CAS 失败（返回 False），调用方据此重拉 rebase
        而非盲覆盖。``snapshot`` 入库前由上游（DocSyncService）已脱敏，不在本层记日志。
        """
        return await self._advance_sync_revision_locked(
            doc_id, expected_revision, new_revision, snapshot
        )

    @sync_to_async
    def _advance_sync_revision_locked(
        self, doc_id: Any, expected_revision: int, new_revision: int, snapshot: str
    ) -> bool:
        with transaction.atomic():
            updated = ProjectDoc.objects.filter(
                pk=doc_id, last_synced_revision=expected_revision
            ).update(
                last_synced_revision=new_revision,
                last_synced_snapshot=snapshot,
                updated_at=timezone.now(),
            )
        return updated > 0

    async def clear_block_map(self, *, doc_id: Any, feishu_block_id: str) -> bool:
        """删除某 block 映射（飞书侧删块同步：清 map 行，幂等）。返回是否删到行。"""
        return await self._clear_block_map_locked(doc_id, feishu_block_id)

    @sync_to_async
    def _clear_block_map_locked(self, doc_id: Any, feishu_block_id: str) -> bool:
        with transaction.atomic():
            deleted, _ = (
                ProjectDocBlockMap.objects.filter(
                    doc_id=doc_id, feishu_block_id=feishu_block_id
                ).delete()
            )
        return deleted > 0

    # ---- ProjectDocBlockMap 写入 ----

    async def upsert_block_map(
        self,
        *,
        doc_id: Any,
        feishu_block_id: str,
        db_ref: str = "",
        section: str = DocSection.SYSTEM,
        content_hash: str = "",
    ) -> ProjectDocBlockMap:
        """按 (doc, feishu_block_id) 幂等 upsert block 映射（同步引擎 Phase 83 用，本期骨架）。"""
        block, _created = await self._upsert_block_map_locked(
            doc_id, feishu_block_id, db_ref, section, content_hash
        )
        return block

    @sync_to_async
    def _upsert_block_map_locked(
        self,
        doc_id: Any,
        feishu_block_id: str,
        db_ref: str,
        section: str,
        content_hash: str,
    ) -> tuple[ProjectDocBlockMap, bool]:
        with transaction.atomic():
            return ProjectDocBlockMap.objects.update_or_create(
                doc_id=doc_id,
                feishu_block_id=feishu_block_id,
                defaults={
                    "db_ref": db_ref,
                    "section": section,
                    "content_hash": content_hash,
                },
            )

    # ---- ProjectDocBlockRevision 写入（capture-never-clobber，SYNC-04） ----

    async def capture_block_revision(
        self,
        *,
        doc_id: Any,
        feishu_block_id: str,
        content: str,
        db_ref: str = "",
        source: str = "system",
        reason: str = "",
    ) -> ProjectDocBlockRevision:
        """三方合并落败方 append-only 留痕（绝不静默丢用户内容，SYNC-04）。

        唯一 ``ProjectDocBlockRevision`` 写入入口（INV-6）；编排（何时调、归因、飞书评论提示）由
        ``DocSyncService``（83-04）填充。``content`` 入库前经 ``redact_secrets_in_text`` 脱敏
        （留痕正文绝不含明文凭证，T-83-04-INFO）。
        """
        from common.logging import redact_secrets_in_text

        redacted = redact_secrets_in_text(content or "")
        return await self._capture_block_revision_locked(
            doc_id, feishu_block_id, redacted, db_ref, source, reason
        )

    async def touch_feishu_edit(self, *, doc_id: Any, at: Any = None) -> None:
        """记录某文件最近一次飞书侧编辑时间（编辑感知延迟写探测数据源，OQ-3）。

        ``last_feishu_edit_at`` 在 drive 事件回拉（``DocSyncService.pull``）时更新为事件时间；
        push 前据此判活跃窗口决定是否延迟写。best-effort 单字段 update，不反噬同步主流程。
        """
        await self._touch_feishu_edit_locked(doc_id, at)

    @sync_to_async
    def _touch_feishu_edit_locked(self, doc_id: Any, at: Any) -> None:
        ts = at or timezone.now()
        with transaction.atomic():
            ProjectDoc.objects.filter(pk=doc_id).update(
                last_feishu_edit_at=ts, updated_at=timezone.now()
            )

    @sync_to_async
    def _capture_block_revision_locked(
        self,
        doc_id: Any,
        feishu_block_id: str,
        content: str,
        db_ref: str,
        source: str,
        reason: str,
    ) -> ProjectDocBlockRevision:
        with transaction.atomic():
            return ProjectDocBlockRevision.objects.create(
                doc_id=doc_id,
                feishu_block_id=feishu_block_id,
                content=content,
                db_ref=db_ref,
                source=source,
                reason=reason,
            )

    # ---- ProjectStateApi 写入（DOC-02） ----

    async def upsert_state_api(
        self,
        *,
        project_id: Any,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        description: str = "",
        request_fields: list[dict[str, Any]] | None = None,
        response_fields: list[dict[str, Any]] | None = None,
        status: str = ApiStatus.PLANNED,
        source: str = ApiSource.MANUAL,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> tuple[ProjectStateApi, bool]:
        """按 (project, method, path) 幂等新增 API 清单条目；新建时审计 state_api_added。"""
        api, created = await self._upsert_state_api_locked(
            project_id,
            method,
            path,
            params or {},
            description or "",
            request_fields or [],
            response_fields or [],
            status,
            source,
        )
        if created:
            actor_id = initiated_by_user_id or getattr(actor, "id", None)
            await AuditService.aemit(
                action=taxonomy.ACTION_PROJECT_STATE_API_ADDED,
                actor=actor,
                target_type="project_state_api",
                target_id=api.id,
                target_repr=f"{method} {path} @ {project_id}",
                after={
                    "project_id": str(project_id),
                    "method": method,
                    "path": path,
                    "status": status,
                    "source": source,
                },
                metadata={
                    "component": _COMPONENT,
                    "category": "caller",
                    "initiated_by_user_id": str(actor_id) if actor_id else "system",
                },
                source="api",
            )
        # 系统区（STATE API 清单）写后 debounce defer push（SYNC-02 / 83-03，fail-soft 不反噬）。
        from initiatives.services.doc_push_scheduler import schedule_doc_push

        await schedule_doc_push(
            project_id=project_id,
            doc_type=DocType.STATE,
            initiated_by_user_id=(
                str(initiated_by_user_id or getattr(actor, "id", "")) or None
            ),
        )
        # KNOW-06（Phase 102）：API 上报后调度 STATE 文档物化进 delivery_knowledge——
        # 修复「upsert 只推飞书不物化」断链，让上报的 API 清单可被语义检索。
        # report_project_state 批量上报会逐条触发，摄取管线 content_hash 短路保证
        # 重复调度为幂等空操作，不需要额外去抖；工作区未 provision（无 STATE doc）
        # 时静默跳过（_schedule_materialization 自身全吞异常 fail-soft）。
        doc_id = await ProjectDoc.objects.filter(
            project_id=project_id, doc_type=DocType.STATE
        ).values_list("id", flat=True).afirst()
        if doc_id:
            await self._schedule_materialization(
                doc_id, initiated_by_user_id or getattr(actor, "id", None)
            )
        return api, created

    @sync_to_async
    def _upsert_state_api_locked(
        self,
        project_id: Any,
        method: str,
        path: str,
        params: dict[str, Any],
        description: str,
        request_fields: list[dict[str, Any]],
        response_fields: list[dict[str, Any]],
        status: str,
        source: str,
    ) -> tuple[ProjectStateApi, bool]:
        with transaction.atomic():
            return ProjectStateApi.objects.get_or_create(
                project_id=project_id,
                method=method,
                path=path,
                defaults={
                    "params": params,
                    "description": description,
                    "request_fields": request_fields,
                    "response_fields": response_fields,
                    "status": status,
                    "source": source,
                },
            )

    async def remove_state_api(
        self,
        *,
        project_id: Any,
        api_id: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> bool:
        """移除 API 清单条目；不存在返回 False（幂等），存在则审计 state_api_removed。"""
        snapshot = await self._remove_state_api_locked(project_id, api_id)
        if snapshot is None:
            return False
        actor_id = initiated_by_user_id or getattr(actor, "id", None)
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_STATE_API_REMOVED,
            actor=actor,
            target_type="project_state_api",
            target_id=snapshot["api_id"],
            target_repr=f"{snapshot['method']} {snapshot['path']} @ {project_id}",
            before={
                "project_id": str(project_id),
                "method": snapshot["method"],
                "path": snapshot["path"],
            },
            metadata={
                "component": _COMPONENT,
                "category": "caller",
                "initiated_by_user_id": str(actor_id) if actor_id else "system",
            },
            source="api",
        )
        # 系统区（STATE API 清单）移除后同样 debounce defer push（diff 自然得 deleted 增量）。
        from initiatives.services.doc_push_scheduler import schedule_doc_push

        await schedule_doc_push(
            project_id=project_id,
            doc_type=DocType.STATE,
            initiated_by_user_id=(
                str(initiated_by_user_id or getattr(actor, "id", "")) or None
            ),
        )
        return True

    @sync_to_async
    def _remove_state_api_locked(
        self, project_id: Any, api_id: Any
    ) -> dict[str, Any] | None:
        with transaction.atomic():
            api = (
                ProjectStateApi.objects.select_for_update()
                .filter(project_id=project_id, id=api_id)
                .first()
            )
            if api is None:
                return None
            snapshot = {"api_id": api.id, "method": api.method, "path": api.path}
            api.delete()
        return snapshot

    async def update_state_api(
        self,
        *,
        project_id: Any,
        api_id: Any,
        fields: dict[str, Any],
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> ProjectStateApi | None:
        """更新单条 API 清单条目的 method/path/params/status（DOC-02，84-01 Task 2）。

        ``fields`` 仅取白名单列（method/path/params/status），其余忽略；条目不存在返回 None
        （幂等，view 转 404）。更新后发结构化事件 ``project_state_api_updated``（caller，绑定
        触发用户）并 debounce defer STATE push（系统区重渲染，fail-soft 不反噬）。
        """
        allowed = {
            k: v
            for k, v in fields.items()
            if k
            in (
                "method",
                "path",
                "params",
                "description",
                "request_fields",
                "response_fields",
                "status",
            )
            and v is not None
        }
        updated = await self._update_state_api_locked(project_id, api_id, allowed)
        if updated is None:
            return None
        actor_id = initiated_by_user_id or getattr(actor, "id", None)
        logger.info(
            "project_state_api_updated",
            project_id=str(project_id),
            api_id=str(api_id),
            fields=sorted(allowed.keys()),
            initiated_by_user_id=str(actor_id) if actor_id else "system",
            component="initiatives.workspace",
            category="caller",
        )
        from initiatives.services.doc_push_scheduler import schedule_doc_push

        await schedule_doc_push(
            project_id=project_id,
            doc_type=DocType.STATE,
            initiated_by_user_id=(str(actor_id) if actor_id else None),
        )
        return updated

    @sync_to_async
    def _update_state_api_locked(
        self, project_id: Any, api_id: Any, fields: dict[str, Any]
    ) -> ProjectStateApi | None:
        with transaction.atomic():
            api = (
                ProjectStateApi.objects.select_for_update()
                .filter(project_id=project_id, id=api_id)
                .first()
            )
            if api is None:
                return None
            update_cols: list[str] = []
            for col, val in fields.items():
                setattr(api, col, val)
                update_cols.append(col)
            if update_cols:
                update_cols.append("updated_at")
                api.save(update_fields=update_cols)
        return api

    # ---- 人工区 block 写回（WB-03，84-01 Task 2；收口经本 service，INV-6）----

    async def write_human_block(
        self,
        *,
        doc_id: Any,
        feishu_block_id: str,
        content: str,
        editor: Any = None,
    ) -> ProjectDocBlockRevision:
        """人工区 block 文本写回（append-only 留痕 + 刷新映射指纹，永不整篇覆盖）。

        - 文本经 ``capture_block_revision``（source=``human``）append-only 留痕（内部脱敏），
          作为人工区当前态的权威存储（读侧取最新一条）。
        - 同步刷新 ``ProjectDocBlockMap`` 的 ``content_hash``（section 保持 HUMAN），供
          Phase 83 同步引擎 block 级增量识别变更（绝不整篇 replace）。
        - 仅写 section==HUMAN 的 block（系统区只读由上游 ``DocContentService`` 校验拒绝）。
        """
        from common.logging import redact_secrets_in_text
        from initiatives.services.doc_sync_diff import block_content_hash

        redacted = redact_secrets_in_text(content or "")
        existing_db_ref = await self._aget_block_db_ref(doc_id, feishu_block_id)
        revision = await self.capture_block_revision(
            doc_id=doc_id,
            feishu_block_id=feishu_block_id,
            content=content,
            db_ref=existing_db_ref,
            source="human",
            reason="human_write",
        )
        await self.upsert_block_map(
            doc_id=doc_id,
            feishu_block_id=feishu_block_id,
            db_ref=existing_db_ref,
            section=DocSection.HUMAN,
            content_hash=block_content_hash(redacted),
        )
        # 写时增量材料化（CTX-01/02）：人工区写回后把该文件正文物化进 delivery_knowledge，
        # best-effort 绝不反噬文件写主流程（content_hash 短路保证重复触发幂等空操作）。
        await self._schedule_materialization(doc_id, getattr(editor, "id", None))
        return revision

    @staticmethod
    async def _schedule_materialization(
        doc_id: Any, initiated_by_user_id: Any
    ) -> None:
        """文件正文写后调度材料化进 delivery_knowledge（CTX-01/02，fail-soft 不反噬）。

        投递经 ``aschedule_ingestion``（内部 on_commit → run_in_background，自身已吞异常），
        透传 ``initiated_by_user_id`` 供 worker 入口 re-bind 归因（无则 system）。外层 try
        为双保险：材料化失败绝不阻断文件写主流程（T-85-01-02）。
        """
        try:
            from knowledge.ingestion import IngestionRequest, aschedule_ingestion

            await aschedule_ingestion(
                IngestionRequest(
                    source_kind="project_doc",
                    source_id=str(doc_id),
                    trigger="project_doc_materialize",
                ),
                initiated_by_user_id=(
                    str(initiated_by_user_id) if initiated_by_user_id else None
                ),
            )
        except Exception:  # noqa: BLE001 — 材料化 best-effort，绝不反噬文件写主流程
            pass

    @sync_to_async
    def _aget_block_db_ref(self, doc_id: Any, feishu_block_id: str) -> str:
        row = (
            ProjectDocBlockMap.objects.filter(
                doc_id=doc_id, feishu_block_id=feishu_block_id
            )
            .values("db_ref")
            .first()
        )
        return (row["db_ref"] if row else "") or ""

    # ---- 后台 provision 编排（WS-04 / DOC-06） ----

    def provision_dispatch(
        self, project_id: Any, initiated_by_user_id: Any = None
    ) -> Any:
        """同步调度入口：把 provision 派发到后台 worker（携带触发用户归因，worker 入口 re-bind）。

        返回 ``concurrent.futures.Future``（调用方一般不消费，best-effort 后台执行）。
        """
        from services.background_runner import run_in_background

        uid = str(initiated_by_user_id) if initiated_by_user_id else None
        return run_in_background(
            lambda: self._provision_workspace_coro(project_id, initiated_by_user_id=uid),
            name=f"project-workspace:{project_id}",
            initiated_by_user_id=uid,
        )

    async def rebuild_workspace(
        self, *, project_id: Any, initiated_by_user_id: Any = None
    ) -> Any:
        """一键重建工作区（供 82-05 端点调用）= 重新派发 provision。

        派发前审计 ``project.workspace_rebuilt``（caller，归因触发用户），兜底飞书首建失败
        的 broken；派发本身 best-effort 后台执行（绝不阻断响应）。
        """
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_WORKSPACE_REBUILT,
            target_type="project",
            target_id=project_id,
            target_repr=str(project_id),
            metadata={
                "component": _COMPONENT,
                "category": "caller",
                "initiated_by_user_id": (
                    str(initiated_by_user_id) if initiated_by_user_id else "system"
                ),
            },
            source="api",
        )
        return self.provision_dispatch(project_id, initiated_by_user_id=initiated_by_user_id)

    async def _provision_workspace_coro(
        self, project_id: Any, initiated_by_user_id: str | None = None
    ) -> None:
        """串行建飞书文件夹 + 5 文件 + 互链 + 看板描述追加（best-effort，绝不抛）。

        任一外呼失败 → 对应 ``ProjectDoc.sync_status=broken``（持久化 DB），继续其余，
        绝不阻断主流程。``create_folder`` 5QPS/不可并发 → 全程串行（无 ``asyncio.gather``）。
        """
        from common.logging import redact_secrets_in_text

        started = time.monotonic()
        uid_repr = initiated_by_user_id or "system"
        logger.info(
            "project_workspace_provision_started",
            project_id=str(project_id),
            initiated_by_user_id=uid_repr,
            component=_COMPONENT,
            category="caller",
        )

        ready = 0
        broken = 0
        try:
            project = await self._aget_project_with_space(project_id)
        except Exception as exc:  # noqa: BLE001 — 连项目都取不到，记 failed 后退出（不抛）
            logger.warning(
                "project_workspace_provision_failed",
                project_id=str(project_id),
                reason="project_load_failed",
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return

        space = project.space
        parent_folder = getattr(space, "feishu_doc_folder_token", "") or ""

        # 未配置飞书（无父文件夹）→ #3：建本地「待同步」文档，不视为错误、不同步飞书。
        if not parent_folder:
            pending = await self._ensure_all_pending(project_id)
            self._log_completed(
                project_id, uid_repr, started, ready, broken,
                reason="feishu_not_configured", pending=pending,
            )
            return

        try:
            client = await self._build_doc_client(space)
        except Exception as exc:  # noqa: BLE001 — 缺凭证/构建失败：按未配置处理（本地待同步，不报错）
            pending = await self._ensure_all_pending(project_id)
            logger.info(
                "project_workspace_provision_local_only",
                project_id=str(project_id),
                reason="feishu_client_unavailable",
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            self._log_completed(
                project_id, uid_repr, started, ready, broken, pending=pending
            )
            return

        # ① 建文件夹（5QPS 串行）→ 落 Project.feishu_folder_token（经 ProjectService，INV-6）
        try:
            folder_token = await client.create_folder(
                name=f"{project.name} 工作区", folder_token=parent_folder
            )
            from initiatives.services.project_service import ProjectService

            await ProjectService().set_folder_token(
                project_id=project_id,
                token=folder_token,
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception as exc:  # noqa: BLE001 — 文件夹失败 → 5 文件全 broken，fail-soft
            broken = await self._mark_all_broken(project_id)
            logger.warning(
                "project_workspace_provision_failed",
                project_id=str(project_id),
                reason="folder_create_failed",
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            self._log_completed(project_id, uid_repr, started, ready, broken)
            return

        # ② 顺序建 5 文件（per-doc 串行）；单文件失败置该 doc broken 并继续
        created_docs: dict[str, tuple[ProjectDoc, str]] = {}
        for doc_type in _DOC_ORDER:
            title_suffix, content = _DOC_TEMPLATES[doc_type]
            title = f"{project.name} · {title_suffix}"
            try:
                result = await client.create_document(
                    title=title, folder_token=folder_token, content=content
                )
                document_id = result.get("document_id", "")
                doc = await self.upsert_doc(
                    project_id=project_id,
                    doc_type=doc_type,
                    feishu_document_id=document_id,
                    feishu_doc_token=document_id,
                    sync_status=DocSyncStatus.READY,
                )
                # 按文件订阅 drive.file.edit_v1 变更事件（SYNC-01）：fail-soft，失败退化 TTL
                # 轮询兜底（83-06），绝不阻断 provision。订阅成功才落 subscribed 标志。
                subscribed = bool(await client.subscribe_file(document_id))
                if subscribed:
                    doc = await self.upsert_doc(
                        project_id=project_id, doc_type=doc_type, subscribed=True
                    )
                created_docs[doc_type] = (doc, result.get("url", ""))
                ready += 1
            except Exception as exc:  # noqa: BLE001 — 单文件失败置 broken，继续其余
                await self.upsert_doc(
                    project_id=project_id,
                    doc_type=doc_type,
                    sync_status=DocSyncStatus.BROKEN,
                )
                broken += 1
                logger.warning(
                    "project_workspace_doc_create_failed",
                    project_id=str(project_id),
                    doc_type=doc_type,
                    error=redact_secrets_in_text(str(exc)),
                    error_type=type(exc).__name__,
                    component=_COMPONENT,
                    category="caller",
                )

        # ③ 互链 + ④ 看板描述追加：5 文件全就绪才执行（DOC-06）
        if ready == len(_DOC_ORDER):
            await self._interlink_docs(client, project, created_docs)
            await self._append_board_section(project, created_docs)

        self._log_completed(project_id, uid_repr, started, ready, broken)

    # ---- provision 内部 helper ----

    @sync_to_async
    def _aget_project_with_space(self, project_id: Any) -> Any:
        """预取 space（防 async lazy FK 访问报错，Pitfall 7）。"""
        from initiatives.models import Project

        return Project.objects.select_related("space").get(pk=project_id)

    @staticmethod
    async def _build_doc_client(space: Any) -> Any:
        """构建 FeishuDocClient（入参是 Space 实例，Pitfall 5）。"""
        from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project

        return await create_feishu_doc_client_for_project(space)

    async def _mark_all_broken(self, project_id: Any) -> int:
        """把 5 个 doc_type 全部 upsert 为 broken（持久化 DB，供一键重建）。返回置 broken 数。"""
        for doc_type in _DOC_ORDER:
            await self.upsert_doc(
                project_id=project_id,
                doc_type=doc_type,
                sync_status=DocSyncStatus.BROKEN,
            )
        return len(_DOC_ORDER)

    async def _ensure_all_pending(self, project_id: Any) -> int:
        """未配置飞书时：把 5 个 doc_type 建为本地「待同步」(pending) 而非 broken。

        #3：建项即建本地文档；飞书未配置就不视为错误（pending 是干净态，配置飞书后一键
        重建即推送同步）。未配置态下飞书从未建过文档（无 folder_token），不存在 ready 可回退。
        返回 pending 文档数。
        """
        for doc_type in _DOC_ORDER:
            await self.upsert_doc(
                project_id=project_id,
                doc_type=doc_type,
                sync_status=DocSyncStatus.PENDING,
            )
        return len(_DOC_ORDER)

    async def _interlink_docs(
        self,
        client: Any,
        project: Any,
        created_docs: dict[str, tuple[ProjectDoc, str]],
    ) -> None:
        """为每个文档头部追加导航段（链到其余 4 文件 + 看板 + Friday 项目页）。

        用 block 级 ``append_markdown`` 追加（绝不整篇 replace，为 Phase 83 同步引擎留接口）。
        """
        from common.logging import redact_secrets_in_text

        board_url = getattr(project, "feishu_board_url", "") or ""
        friday_path = f"/projects/{project.id}"
        for doc_type, (doc, _url) in created_docs.items():
            nav = self._build_nav_markdown(
                doc_type, created_docs, board_url, friday_path
            )
            try:
                await client.append_markdown(doc.feishu_document_id, nav)
            except Exception as exc:  # noqa: BLE001 — 互链失败不反噬，best-effort
                logger.warning(
                    "project_workspace_interlink_failed",
                    project_id=str(project.id),
                    doc_type=doc_type,
                    error=redact_secrets_in_text(str(exc)),
                    error_type=type(exc).__name__,
                    component=_COMPONENT,
                    category="caller",
                )

    @staticmethod
    def _build_nav_markdown(
        current: str,
        created_docs: dict[str, tuple[ProjectDoc, str]],
        board_url: str,
        friday_path: str,
    ) -> str:
        """构造单文档头部导航 Markdown（链到其余文件 + 看板 + Friday 项目页）。"""
        lines = [f"## {_WORKSPACE_MARKER} 导航", ""]
        for doc_type, (_doc, url) in created_docs.items():
            if doc_type == current:
                continue
            label, _tpl = _DOC_TEMPLATES[doc_type]
            if url:
                lines.append(f"- [{label}]({url})")
        if board_url:
            lines.append(f"- [项目看板]({board_url})")
        lines.append(f"- [Friday 项目页]({friday_path})")
        return "\n".join(lines) + "\n"

    async def _append_board_section(
        self,
        project: Any,
        created_docs: dict[str, tuple[ProjectDoc, str]],
    ) -> None:
        """看板描述追加「📁 项目工作区」段（read-then-append 幂等，DOC-06，Pitfall 6）。

        先 ``get_work_item`` 读现描述，无 marker 才 ``update_work_item_fields`` 追加；缺
        project_key / 看板工作项 → 跳过（fail-soft）。
        """
        from common.logging import redact_secrets_in_text

        project_key = getattr(project, "feishu_project_key", "") or ""
        board_id = getattr(project, "feishu_board_id", "") or ""
        if not project_key or not board_id:
            return  # 缺看板引用 → 跳过（fail-soft）
        try:
            work_item_id = int(board_id)
        except (TypeError, ValueError):
            return
        # A2: 看板工作项 type 的 field_key（description）MEDIUM，需 live 验证；默认 story。
        work_item_type = "story"

        try:
            client = await self._build_board_client(project.space)
        except Exception as exc:  # noqa: BLE001 — 无看板凭证 → 跳过
            logger.warning(
                "project_workspace_board_client_unavailable",
                project_id=str(project.id),
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return

        try:
            info = await client.get_work_item(project_key, work_item_id, work_item_type)
            description = getattr(info, "description", "") or ""
            if _WORKSPACE_MARKER in description:
                return  # 幂等：已含 marker 不重复追加
            section = self._build_board_section_text(project, created_docs)
            new_description = (description + "\n\n" + section) if description else section
            await client.update_work_item_fields(
                project_key, work_item_id, work_item_type, {"description": new_description}
            )
        except Exception as exc:  # noqa: BLE001 — 看板追加失败不反噬，best-effort
            logger.warning(
                "project_workspace_board_append_failed",
                project_id=str(project.id),
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )

    @staticmethod
    async def _build_board_client(space: Any) -> Any:
        """构建 FeishuClient（项目看板写，入参 Space）。"""
        from services.feishu import create_feishu_client_for_project

        return await sync_to_async(create_feishu_client_for_project)(space)

    @staticmethod
    def _build_board_section_text(
        project: Any,
        created_docs: dict[str, tuple[ProjectDoc, str]],
    ) -> str:
        """构造看板描述「📁 项目工作区」段（文件链接 + Friday 项目页）。"""
        lines = [_WORKSPACE_MARKER, ""]
        for doc_type, (_doc, url) in created_docs.items():
            label, _tpl = _DOC_TEMPLATES[doc_type]
            if url:
                lines.append(f"- {label}: {url}")
        lines.append(f"- Friday 项目页: /projects/{project.id}")
        return "\n".join(lines)

    @staticmethod
    def _log_completed(
        project_id: Any,
        uid_repr: str,
        started: float,
        ready: int,
        broken: int,
        reason: str = "",
        pending: int = 0,
    ) -> None:
        logger.info(
            "project_workspace_provision_completed",
            project_id=str(project_id),
            initiated_by_user_id=uid_repr,
            ready=ready,
            broken=broken,
            pending=pending,
            reason=reason,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            component=_COMPONENT,
            category="caller",
        )
