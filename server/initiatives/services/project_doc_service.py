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

        本计划（83-01）建写入收口（INV-6），编排（何时调、归因、飞书评论提示）由 83-04 填充。
        """
        return await self._capture_block_revision_locked(
            doc_id, feishu_block_id, content, db_ref, source, reason
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
        status: str = ApiStatus.PLANNED,
        source: str = ApiSource.MANUAL,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> tuple[ProjectStateApi, bool]:
        """按 (project, method, path) 幂等新增 API 清单条目；新建时审计 state_api_added。"""
        api, created = await self._upsert_state_api_locked(
            project_id, method, path, params or {}, status, source
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
        return api, created

    @sync_to_async
    def _upsert_state_api_locked(
        self,
        project_id: Any,
        method: str,
        path: str,
        params: dict[str, Any],
        status: str,
        source: str,
    ) -> tuple[ProjectStateApi, bool]:
        with transaction.atomic():
            return ProjectStateApi.objects.get_or_create(
                project_id=project_id,
                method=method,
                path=path,
                defaults={"params": params, "status": status, "source": source},
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

        # 无父文件夹 / 无飞书凭证 → 5 文件全置 broken，fail-soft 返回（不抛）。
        if not parent_folder:
            broken = await self._mark_all_broken(project_id)
            self._log_completed(project_id, uid_repr, started, ready, broken, reason="no_parent_folder")
            return

        try:
            client = await self._build_doc_client(space)
        except Exception as exc:  # noqa: BLE001 — 缺凭证/构建失败降级，不阻断
            broken = await self._mark_all_broken(project_id)
            logger.warning(
                "project_workspace_provision_failed",
                project_id=str(project_id),
                reason="feishu_client_unavailable",
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            self._log_completed(project_id, uid_repr, started, ready, broken)
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
    ) -> None:
        logger.info(
            "project_workspace_provision_completed",
            project_id=str(project_id),
            initiated_by_user_id=uid_repr,
            ready=ready,
            broken=broken,
            reason=reason,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            component=_COMPONENT,
            category="caller",
        )
