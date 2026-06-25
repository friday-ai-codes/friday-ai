"""ArtifactService —— ArtifactType / Artifact 唯一写入入口（ARTIFACT-01/02/04/05，INV-6）。

所有 ``ArtifactType`` / ``Artifact`` 的 create/update/delete 都经本 service 收口（旁路写表由
``test_artifact_inv6_guard`` grep 守护）。模型层不提供业务 create/save 方法。

关键约束：
- **禁用类型不可新建实例、既有实例只读**（``create_artifact`` / ``update_artifact`` 校验
  ``type.enabled``，否则 ``ArtifactDisabledError``）。
- **类型删除双重保护**：``Artifact.type`` FK ``on_delete=PROTECT``（DB 兜底）+ 本 service 预检
  （有实例则拒删 / builtin 禁删只可禁用，``ArtifactTypeError``）。
- **RAG 摄取**：``ragable=True`` 且文字载体（飞书 doc/表格/md/repo_file）→ 调
  ``aschedule_ingestion``（source_kind=``"artifact"``）异步全文进 ``delivery_knowledge``；
  UI 稿图形外链（``ragable=False`` / ``external_link``）仅元数据不强行 RAG（ARTIFACT-04）。
- 写入经 ``AuditService.aemit``（component=initiatives, category=caller, initiated_by_user_id）。
  async ORM 经 ``sync_to_async``。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import ProtectedError

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from initiatives.models import Artifact, ArtifactType, TEXT_CARRIERS

logger = structlog.get_logger(__name__)

__all__ = [
    "ArtifactService",
    "ArtifactError",
    "ArtifactDisabledError",
    "ArtifactTypeError",
]

_COMPONENT = "initiatives"

# 工件可变内容字段（变更触发版本递增 + RAG 重摄取）。
_CONTENT_FIELDS = ("title", "url", "content_ref", "carrier")


class ArtifactError(Exception):
    """工件操作非法基类（API 层转 400）。"""


class ArtifactDisabledError(ArtifactError):
    """禁用类型不可新建实例 / 既有实例只读（API 层转 400）。"""


class ArtifactTypeError(ArtifactError):
    """工件类型操作非法（builtin 禁删 / 有实例拒删，API 层转 400/409）。"""


def _should_ingest(artifact: Artifact, artifact_type: ArtifactType) -> bool:
    """是否应把工件正文摄取进 RAG：类型 ragable 且载体为文字载体。

    UI 稿图形外链（external_link / ragable=False）→ False（仅元数据，不强行 RAG 正文）。
    """
    return bool(artifact_type.ragable) and artifact.carrier in TEXT_CARRIERS


class ArtifactService:
    """ArtifactType / Artifact 唯一写入入口（INV-6）。"""

    # ---- 工件类型（ARTIFACT-01/05） ----

    async def create_type(
        self,
        *,
        key: str,
        name: str,
        carrier: str,
        ragable: bool = False,
        enabled: bool = True,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> ArtifactType:
        """新增自定义工件类型（``builtin=False``）。"""
        artifact_type = await self._create_type_locked(
            key=key, name=name, carrier=carrier, ragable=ragable, enabled=enabled
        )
        await self._emit(
            taxonomy.ACTION_ARTIFACT_TYPE_CREATED,
            actor=actor,
            initiated_by_user_id=initiated_by_user_id,
            target_type="artifact_type",
            target_id=artifact_type.id,
            target_repr=artifact_type.key,
            after={
                "key": key,
                "name": name,
                "carrier": carrier,
                "ragable": ragable,
                "enabled": enabled,
                "builtin": False,
            },
        )
        return artifact_type

    @sync_to_async
    def _create_type_locked(
        self, *, key: str, name: str, carrier: str, ragable: bool, enabled: bool
    ) -> ArtifactType:
        with transaction.atomic():
            return ArtifactType.objects.create(
                key=key,
                name=name,
                carrier=carrier,
                ragable=ragable,
                enabled=enabled,
                builtin=False,
            )

    async def update_type(
        self,
        *,
        type_id: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        **fields: Any,
    ) -> ArtifactType:
        """更新工件类型可变字段（name/carrier/ragable/enabled）。

        ``enabled=False`` 即"禁用"——禁用后该类型不可新建实例、既有实例只读
        （由 ``create_artifact`` / ``update_artifact`` 强制）。``key`` / ``builtin`` 不可改。
        """
        allowed = {"name", "carrier", "ragable", "enabled"}
        changes = {k: v for k, v in fields.items() if k in allowed and v is not None}
        artifact_type, before = await self._update_type_locked(type_id, changes)
        if changes:
            await self._emit(
                taxonomy.ACTION_ARTIFACT_TYPE_UPDATED,
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
                target_type="artifact_type",
                target_id=artifact_type.id,
                target_repr=artifact_type.key,
                before=before,
                after={k: getattr(artifact_type, k) for k in changes},
            )
        return artifact_type

    @sync_to_async
    def _update_type_locked(
        self, type_id: Any, changes: dict[str, Any]
    ) -> tuple[ArtifactType, dict[str, Any]]:
        with transaction.atomic():
            artifact_type = ArtifactType.objects.select_for_update().get(pk=type_id)
            before = {k: getattr(artifact_type, k) for k in changes}
            for k, v in changes.items():
                setattr(artifact_type, k, v)
            if changes:
                artifact_type.save(update_fields=[*changes.keys(), "updated_at"])
        return artifact_type, before

    async def delete_type(
        self,
        *,
        type_id: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> None:
        """删除自定义工件类型（受双重保护）。

        - builtin 类型禁删（``ArtifactTypeError``，只可禁用）；
        - 有既有实例的类型拒删（service 预检 + DB ``PROTECT`` 兜底）。
        """
        snapshot = await self._delete_type_locked(type_id)
        await self._emit(
            taxonomy.ACTION_ARTIFACT_TYPE_DELETED,
            actor=actor,
            initiated_by_user_id=initiated_by_user_id,
            target_type="artifact_type",
            target_id=type_id,
            target_repr=snapshot["key"],
            before=snapshot,
        )

    @sync_to_async
    def _delete_type_locked(self, type_id: Any) -> dict[str, Any]:
        with transaction.atomic():
            artifact_type = ArtifactType.objects.select_for_update().get(pk=type_id)
            if artifact_type.builtin:
                raise ArtifactTypeError(
                    f"内置类型 {artifact_type.key} 禁止删除（只可禁用）"
                )
            if Artifact.objects.filter(type=artifact_type).exists():
                raise ArtifactTypeError(
                    f"类型 {artifact_type.key} 仍有工件实例，删除受保护（请先迁移/删除实例或改为禁用）"
                )
            snapshot = {"key": artifact_type.key, "name": artifact_type.name}
            try:
                artifact_type.delete()
            except ProtectedError as exc:  # DB 兜底（并发新建实例的极端竞态）
                raise ArtifactTypeError(
                    f"类型 {artifact_type.key} 仍有工件实例，删除受保护"
                ) from exc
        return snapshot

    # ---- 工件实例（ARTIFACT-02/04/05） ----

    async def create_artifact(
        self,
        *,
        project_id: Any,
        type_id: Any,
        title: str,
        carrier: str = "",
        url: str = "",
        content_ref: str = "",
        contributor: Any = None,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> Artifact:
        """新建工件实例（ARTIFACT-02）。

        - 禁用类型不可新建（``ArtifactDisabledError``）；
        - ``carrier`` 缺省取类型默认载体；
        - ragable 文字载体 → 调度 RAG 摄取（``aschedule_ingestion``，best-effort 不阻断）。
        """
        artifact, artifact_type = await self._create_artifact_locked(
            project_id=project_id,
            type_id=type_id,
            title=title,
            carrier=carrier,
            url=url,
            content_ref=content_ref,
            contributor=contributor,
        )
        await self._emit(
            taxonomy.ACTION_ARTIFACT_CREATED,
            actor=actor,
            initiated_by_user_id=initiated_by_user_id,
            target_type="artifact",
            target_id=artifact.id,
            target_repr=artifact.title,
            after={
                "project_id": str(project_id),
                "type": artifact_type.key,
                "carrier": artifact.carrier,
                "version": artifact.version,
            },
        )
        await self._maybe_schedule_ingestion(artifact, artifact_type, trigger="artifact_created")
        return artifact

    @sync_to_async
    def _create_artifact_locked(
        self,
        *,
        project_id: Any,
        type_id: Any,
        title: str,
        carrier: str,
        url: str,
        content_ref: str,
        contributor: Any,
    ) -> tuple[Artifact, ArtifactType]:
        with transaction.atomic():
            artifact_type = ArtifactType.objects.get(pk=type_id)
            if not artifact_type.enabled:
                raise ArtifactDisabledError(
                    f"类型 {artifact_type.key} 已禁用，不可新建工件实例"
                )
            artifact = Artifact.objects.create(
                project_id=project_id,
                type=artifact_type,
                carrier=carrier or artifact_type.carrier,
                title=title,
                url=url,
                content_ref=content_ref,
                contributor=contributor,
                version=1,
            )
        return artifact, artifact_type

    async def update_artifact(
        self,
        *,
        artifact_id: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        **fields: Any,
    ) -> Artifact:
        """更新工件实例（ARTIFACT-03 md/内部可编辑）。

        - 禁用类型的工件只读（``ArtifactDisabledError``）；
        - 内容字段（title/url/content_ref/carrier）变更 → 版本递增 + 重摄取（若 ragable）。
        """
        allowed = {"title", "url", "content_ref", "carrier"}
        changes = {k: v for k, v in fields.items() if k in allowed and v is not None}
        artifact, artifact_type, before, content_changed = await self._update_artifact_locked(
            artifact_id, changes
        )
        if changes:
            await self._emit(
                taxonomy.ACTION_ARTIFACT_UPDATED,
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
                target_type="artifact",
                target_id=artifact.id,
                target_repr=artifact.title,
                before=before,
                after={**{k: getattr(artifact, k) for k in changes}, "version": artifact.version},
            )
        if content_changed:
            await self._maybe_schedule_ingestion(
                artifact, artifact_type, trigger="artifact_updated"
            )
        return artifact

    @sync_to_async
    def _update_artifact_locked(
        self, artifact_id: Any, changes: dict[str, Any]
    ) -> tuple[Artifact, ArtifactType, dict[str, Any], bool]:
        with transaction.atomic():
            artifact = Artifact.objects.select_for_update().select_related("type").get(
                pk=artifact_id
            )
            artifact_type = artifact.type
            if not artifact_type.enabled:
                raise ArtifactDisabledError(
                    f"类型 {artifact_type.key} 已禁用，既有工件只读不可编辑"
                )
            before = {k: getattr(artifact, k) for k in changes}
            content_changed = any(
                k in _CONTENT_FIELDS and getattr(artifact, k) != v for k, v in changes.items()
            )
            for k, v in changes.items():
                setattr(artifact, k, v)
            update_fields = list(changes.keys())
            if content_changed:
                artifact.version += 1
                update_fields.append("version")
            if changes:
                artifact.save(update_fields=[*update_fields, "updated_at"])
        return artifact, artifact_type, before, content_changed

    async def delete_artifact(
        self,
        *,
        artifact_id: Any,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> None:
        """删除工件实例。"""
        snapshot = await self._delete_artifact_locked(artifact_id)
        await self._emit(
            taxonomy.ACTION_ARTIFACT_DELETED,
            actor=actor,
            initiated_by_user_id=initiated_by_user_id,
            target_type="artifact",
            target_id=artifact_id,
            target_repr=snapshot["title"],
            before=snapshot,
        )

    @sync_to_async
    def _delete_artifact_locked(self, artifact_id: Any) -> dict[str, Any]:
        with transaction.atomic():
            artifact = Artifact.objects.select_for_update().get(pk=artifact_id)
            snapshot = {
                "title": artifact.title,
                "project_id": str(artifact.project_id),
            }
            artifact.delete()
        return snapshot

    # ---- 内部 helper ----

    async def _maybe_schedule_ingestion(
        self, artifact: Artifact, artifact_type: ArtifactType, *, trigger: str
    ) -> None:
        """ragable 文字载体 → 调度异步 RAG 摄取（best-effort，绝不阻断主写入）。"""
        if not _should_ingest(artifact, artifact_type):
            return
        try:
            from knowledge.ingestion import IngestionRequest, aschedule_ingestion

            logger.info(
                "artifact_rag_scheduled",
                artifact_id=str(artifact.id),
                carrier=artifact.carrier,
                trigger=trigger,
                component=_COMPONENT,
                category="caller",
            )
            await aschedule_ingestion(
                IngestionRequest(
                    source_kind="artifact",
                    source_id=str(artifact.id),
                    trigger=trigger,
                )
            )
        except Exception as exc:  # noqa: BLE001 — 观测/摄取永不反噬工件写入
            logger.warning(
                "artifact_rag_schedule_failed",
                artifact_id=str(artifact.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def _emit(
        self,
        action: str,
        *,
        actor: Any,
        initiated_by_user_id: Any,
        target_type: str,
        target_id: Any,
        target_repr: str,
        before: Any = None,
        after: Any = None,
    ) -> None:
        actor_id = initiated_by_user_id or getattr(actor, "id", None)
        await AuditService.aemit(
            action=action,
            actor=actor,
            target_type=target_type,
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
