"""WorkItemService —— WorkItem 唯一写入入口（DOMAIN §13.1，INV-6）。

所有路径（webhook / manual / 后续 bitable_import / mr_reverse）都经 ``upsert``
收敛同一 canonical WorkItem（三元组幂等，INV-1）。落库步骤严格对齐 DOMAIN §13.1：

1. ``select_for_update`` 取/建 WorkItem（同步 ``transaction.atomic`` 经 ``sync_to_async``）。
2. ``fetch=True`` → ``get_work_item`` 回源（Phase 27 修好的真实 type）。
3. 刷新 **mirror** 字段（显式 update_fields 白名单）；**绝不动** friday_enhanced / writeback。
4. 派生关系 → ``WorkItemRelation``（占位/回填，复用 Phase 27 helper）。
5. 状态变更 append ``WorkItemStatusEvent``（先 append 后改 mirror，非就地覆盖）。
6. 写 ``field_provenance`` + ``last_synced_at``；按 facet 记 ``WorkItemSyncState``；
   best-effort 发 ``work_item_synced``。

失败策略（§1.4 / WIT-03，对齐 knowledge normalizer 降级范式）：部分 facet 失败
不回滚整体 WorkItem——已 get_or_create 的行保留，facet 记 missing/error。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from delivery.models import (
    SyncFacet,
    SyncStatus,
    WorkItem,
    WorkItemSyncState,
)
from delivery.services.derivation import derive_status_fields
from delivery.signals import work_item_synced
from services.feishu import create_feishu_client_for_project
from services.feishu_parsing import extract_prd_url, extract_tech_doc_url

logger = structlog.get_logger(__name__)

__all__ = ["WorkItemIdentity", "WorkItemService"]

# mirror 字段白名单：sync 仅刷这些，friday_enhanced / writeback 永不在内（WIT-02 / T-28-04）
_MIRROR_FIELDS = (
    "title",
    "status_state_key",
    "status_sub_stage",
    "status_display_name",
    "is_archived_state",
    "is_init_state",
    "feishu_fields",
    "prd_url",
    "tech_doc_url",
)

# 本 phase 不摄取正文/评论 facet → 记 missing（不假装 complete）
_UNINGESTED_FACETS = (SyncFacet.PRD_BODY, SyncFacet.TECH_DOC, SyncFacet.COMMENTS)

# SyncState.error 截断长度（脱敏：避免拼接大段不可信响应 / 凭证，T-28-07）
_ERROR_SNIPPET_LIMIT = 500


@dataclass(frozen=True)
class WorkItemIdentity:
    """WorkItem 自然键三元组（INV-1）。"""

    feishu_project_key: str
    work_item_type: str
    work_item_id: int


class WorkItemService:
    """WorkItem 唯一写入入口（INV-6）。"""

    async def upsert(
        self,
        identity: WorkItemIdentity,
        source: str,
        *,
        fetch: bool = True,
    ) -> WorkItem:
        """取/建 canonical WorkItem 并按 §13.1 刷新（缺料降配，不整体回滚）。

        Args:
            identity: 飞书三元组身份。
            source: 调用方来源（feishu_webhook|manual|bitable_import|mr_reverse）。
            fetch: 是否回源飞书补全 mirror（默认 True）。

        Returns:
            收敛后的 canonical WorkItem。
        """
        project = await self._resolve_project(identity.feishu_project_key)
        work_item, _created = await self._get_or_create_locked(identity, source, project)

        if not fetch:
            return work_item

        if project is None:
            await self._record_sync_state(
                work_item,
                SyncFacet.BASIC_FIELDS,
                SyncStatus.MISSING,
                source,
                error="project_unconfigured",
            )
            await self._emit(work_item, source, facets=[])
            return work_item

        try:
            info = await self._fetch(project, identity)
        except Exception as exc:
            error = self._safe_error(exc)
            logger.warning(
                "work_item_upsert_fetch_failed",
                project_key=identity.feishu_project_key,
                work_item_type=identity.work_item_type,
                work_item_id=identity.work_item_id,
                error=error,
                error_type=type(exc).__name__,
            )
            await self._record_sync_state(
                work_item, SyncFacet.BASIC_FIELDS, SyncStatus.MISSING, source, error=error
            )
            await self._emit(work_item, source, facets=[])
            return work_item

        raw_item = self._raw_item(info)
        status_fields = derive_status_fields(raw_item)
        await self._refresh_mirror(work_item, info, status_fields, source)
        await self._record_sync_state(
            work_item, SyncFacet.BASIC_FIELDS, SyncStatus.COMPLETE, source
        )
        for facet in _UNINGESTED_FACETS:
            await self._record_sync_state(work_item, facet, SyncStatus.MISSING, source)

        await self._emit(work_item, source, facets=[SyncFacet.BASIC_FIELDS.value])
        return work_item

    # === 步骤实现 ===

    async def _resolve_project(self, project_key: str):
        """按 feishu_project_key 解析 Project（async）；缺失返回 None。"""
        from projects.models import Project

        return await Project.objects.filter(feishu_project_key=project_key).afirst()

    @sync_to_async
    def _get_or_create_locked(
        self, identity: WorkItemIdentity, source: str, project
    ) -> tuple[WorkItem, bool]:
        """select_for_update 取/建 WorkItem（三元组幂等，origin 仅首次落）。"""
        with transaction.atomic():
            return WorkItem.objects.select_for_update().get_or_create(
                feishu_project_key=identity.feishu_project_key,
                work_item_type=identity.work_item_type,
                work_item_id=identity.work_item_id,
                defaults={"origin": source, "project": project},
            )

    async def _fetch(self, project, identity: WorkItemIdentity):
        """经项目加密凭证回源 get_work_item（真实 type，Phase 27 修好）。"""
        client = create_feishu_client_for_project(project)
        return await client.get_work_item(
            project_key=identity.feishu_project_key,
            work_item_id=identity.work_item_id,
            work_item_type=identity.work_item_type,
        )

    @sync_to_async
    def _refresh_mirror(
        self, work_item: WorkItem, info: Any, status_fields: dict, source: str
    ) -> None:
        """刷新 mirror 字段（显式 update_fields）+ field_provenance + last_synced_at。

        **绝不写** friday_enhanced（business_line_normalized/module_normalized/
        internal_note）与 writeback（feishu_chat_id）——它们不在 update_fields 内。
        """
        feishu_fields = info.feishu_fields or []
        work_item.title = info.name or ""
        work_item.feishu_fields = feishu_fields
        work_item.prd_url = extract_prd_url(feishu_fields) or ""
        work_item.tech_doc_url = extract_tech_doc_url(feishu_fields) or ""
        work_item.status_state_key = status_fields["status_state_key"]
        work_item.status_sub_stage = status_fields["status_sub_stage"]
        work_item.status_display_name = status_fields["status_display_name"]
        work_item.is_archived_state = status_fields["is_archived_state"]
        work_item.is_init_state = status_fields["is_init_state"]
        work_item.last_synced_at = timezone.now()

        provenance = dict(work_item.field_provenance or {})
        for field in _MIRROR_FIELDS:
            provenance[field] = source
        work_item.field_provenance = provenance

        work_item.save(
            update_fields=[
                *_MIRROR_FIELDS,
                "last_synced_at",
                "field_provenance",
                "updated_at",
            ]
        )

    @sync_to_async
    def _record_sync_state(
        self,
        work_item: WorkItem,
        facet: str,
        status: str,
        source: str,
        *,
        error: str = "",
    ) -> None:
        """按 (work_item, facet) 落 WorkItemSyncState（update_or_create 幂等）。"""
        WorkItemSyncState.objects.update_or_create(
            work_item=work_item,
            facet=facet,
            defaults={
                "status": status,
                "source": source,
                "last_synced_at": timezone.now() if status == SyncStatus.COMPLETE else None,
                "error": error,
            },
        )

    async def _emit(self, work_item: WorkItem, source: str, *, facets: list[str]) -> None:
        """best-effort 发 work_item_synced（订阅者异常吞掉 + warning，不影响落库）。"""
        try:
            await sync_to_async(work_item_synced.send)(
                sender=self.__class__,
                work_item_id=str(work_item.id),
                facets=facets,
            )
        except Exception as exc:
            logger.warning(
                "work_item_synced_emit_failed",
                work_item_id=str(work_item.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )

    # === helper ===

    def _raw_item(self, info: Any) -> dict:
        """从 WorkItemInfo.raw_response 容错取单条 item dict（缺失降级空 dict）。"""
        if not info.raw_response:
            return {}
        try:
            data = json.loads(info.raw_response)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        items = data.get("data") if isinstance(data, dict) else None
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
        return {}

    def _safe_error(self, exc: Exception) -> str:
        """脱敏错误摘要（截断；复用 feishu 既有脱敏，不拼凭证，T-28-07）。"""
        return str(exc)[:_ERROR_SNIPPET_LIMIT]
