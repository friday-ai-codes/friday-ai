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
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from delivery.models import (
    SyncFacet,
    SyncStatus,
    WorkItem,
    WorkItemRelation,
    WorkItemStatusEvent,
    WorkItemSyncState,
)
from delivery.services.derivation import derive_status_events, derive_status_fields
from delivery.signals import work_item_synced
from services.feishu import create_feishu_client_for_project
from services.feishu_parsing import (
    derive_relations_from_fields,
    extract_prd_url,
    extract_tech_doc_url,
)

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

# 误拼进异常消息的凭证兜底脱敏：键名命中（token/secret/...）的值整体抹掉。
# 上游 strict_response_json 已脱敏响应 body，本正则是 SyncState.error 落库前的最后一道防线。
_SECRET_KV_RE = re.compile(
    r"(?i)\b("
    r"x-plugin-token|x-user-key|plugin[_-]?secret|plugin[_-]?token|"
    r"access[_-]?token|refresh[_-]?token|api[_-]?key|access[_-]?key|secret[_-]?key|"
    r"authorization|password|passwd|token|secret|apikey"
    r")(\"?\s*[:=]\s*\"?)([^\s,\"'}\]]+)"  # 容忍 JSON "key": "value" 的引号/冒号/等号
)
# Bearer <token> 形式（HTTP Authorization header 误入错误串）。
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")


def _redact_secrets(text: str) -> str:
    """抹掉明显的凭证/令牌：``Bearer <token>`` + 键名命中的值，保留键名供排障。

    先抹 ``Bearer`` 串再抹键值对——否则 ``Authorization: Bearer <tok>`` 会被键值正则
    先吃掉 ``Bearer`` 字样而漏掉其后的 token。
    """
    text = _BEARER_RE.sub("Bearer ***", text)
    text = _SECRET_KV_RE.sub(r"\1\2***", text)
    return text


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
        # 状态事件取飞书 payload 业务时间（顶层 updated_at，§16），与历史回填同源 →
        # 实时合成事件与 history[] 回填走同一去重锚，避免 now() 戳并存重复（WR-03）。
        event_time = self._parse_ms(raw_item.get("updated_at"))
        await self._refresh_mirror(work_item, info, status_fields, source, event_time)
        await self._record_sync_state(
            work_item, SyncFacet.BASIC_FIELDS, SyncStatus.COMPLETE, source
        )
        for facet in _UNINGESTED_FACETS:
            await self._record_sync_state(work_item, facet, SyncStatus.MISSING, source)

        # 状态历史回填（best-effort，去重）
        await self._backfill_status_history(work_item, raw_item)

        # 关系派生（步骤 4）——独立 facet，派生异常仅记 relations error，不掀翻 WorkItem
        try:
            await self._apply_relations(work_item, info, source)
            await self._record_sync_state(
                work_item, SyncFacet.RELATIONS, SyncStatus.COMPLETE, source
            )
        except Exception as exc:
            error = self._safe_error(exc)
            logger.warning(
                "work_item_upsert_relations_failed",
                work_item_id=str(work_item.id),
                error=error,
                error_type=type(exc).__name__,
            )
            await self._record_sync_state(
                work_item, SyncFacet.RELATIONS, SyncStatus.MISSING, source, error=error
            )

        await self._emit(
            work_item,
            source,
            facets=[SyncFacet.BASIC_FIELDS.value, SyncFacet.RELATIONS.value],
        )
        return work_item

    async def awriteback_feishu_chat_id(
        self,
        feishu_project_key: str,
        work_item_type: str,
        work_item_id: int,
        chat_id: str,
    ) -> bool:
        """把建群 chat_id 写回 WorkItem.feishu_chat_id（writeback 单一入口，INV-6）。

        ``feishu_chat_id`` 属 writeback 字段（独立来源），**绝不**进 ``_MIRROR_FIELDS``、
        **绝不**在 ``_refresh_mirror`` 内写——否则下次 sync 的 mirror 刷新会把它覆盖回空
        （P-5）。本方法是它唯一的合规写入路径：三元组定位 WorkItem，仅写
        ``feishu_chat_id`` + ``updated_at``（显式 update_fields，不动其他字段）。

        WorkItem 不存在时返回 ``False`` 不抛（供调用方 fail-soft 判定）；DB 异常
        不吞（由调用方 fail-soft 捕获）。

        Args:
            feishu_project_key: 飞书空间 Key（三元组之一）。
            work_item_type: 工作项类型（三元组之一）。
            work_item_id: 工作项 ID（三元组之一）。
            chat_id: 建群返回的群聊 ID。

        Returns:
            命中并写入返回 True；WorkItem 不存在返回 False。
        """
        return await self._writeback_feishu_chat_id_sync(
            feishu_project_key, work_item_type, work_item_id, chat_id
        )

    @sync_to_async
    def _writeback_feishu_chat_id_sync(
        self,
        feishu_project_key: str,
        work_item_type: str,
        work_item_id: int,
        chat_id: str,
    ) -> bool:
        """三元组定位 + save(update_fields=[feishu_chat_id, updated_at])（同步块）。

        与 ``_get_or_create_locked`` / ``_refresh_mirror`` 的 ``@sync_to_async`` 私有
        同步块同款风格。命中 None → 返回 False；命中 → 仅写 feishu_chat_id + updated_at。
        """
        work_item = WorkItem.objects.filter(
            feishu_project_key=feishu_project_key,
            work_item_type=work_item_type,
            work_item_id=work_item_id,
        ).first()
        if work_item is None:
            logger.warning(
                "feishu_chat_id_writeback_target_missing",
                feishu_project_key=feishu_project_key,
                work_item_type=work_item_type,
                work_item_id=work_item_id,
            )
            return False

        work_item.feishu_chat_id = chat_id
        work_item.save(update_fields=["feishu_chat_id", "updated_at"])
        logger.info(
            "feishu_chat_id_writeback",
            work_item_id=work_item_id,
            chat_id=chat_id,
        )
        return True

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
        self,
        work_item: WorkItem,
        info: Any,
        status_fields: dict,
        source: str,
        event_time: Any = None,
    ) -> None:
        """单锁原子刷新 mirror + 状态事件 append（§13.1 读改写，WR-01/WIT-05）。

        回源（``get_work_item``）已在锁外完成；此处开**单个** ``transaction.atomic``
        并对该行重新 ``select_for_update`` 上锁，在同一锁内读当前状态 → 比对 →
        append ``WorkItemStatusEvent`` → 保存 mirror，三者原子完成（避免锁释放后用
        过期内存态判断导致状态事件重复/漏记，WR-01）。状态事件 ``event_time`` 取飞书
        payload 业务时间（与 history 回填同源），实时合成与历史回填走同一去重锚（WR-03）。

        **绝不写** friday_enhanced（business_line_normalized/module_normalized/
        internal_note）与 writeback（feishu_chat_id）——它们不在 update_fields 内。
        per-facet ``WorkItemSyncState`` 写在本锁**之外**（保 WIT-03 部分失败隔离）。
        """
        feishu_fields = info.feishu_fields or []
        new_state_key = status_fields["status_state_key"]
        new_sub_stage = status_fields["status_sub_stage"]

        with transaction.atomic():
            # 同一把锁内重取该行：当前状态判定 + 事件 append + mirror 保存原子完成
            locked = WorkItem.objects.select_for_update().get(pk=work_item.pk)

            # 状态变更先 append StatusEvent（pre=锁内旧态/cur=新），再改 mirror（WIT-05）
            if new_state_key and new_state_key != locked.status_state_key:
                WorkItemStatusEvent.objects.create(
                    work_item=locked,
                    pre_state_key=locked.status_state_key,
                    cur_state_key=new_state_key,
                    pre_sub_stage=locked.status_sub_stage,
                    cur_sub_stage=new_sub_stage,
                    event_time=event_time,
                )

            locked.title = info.name or ""
            locked.feishu_fields = feishu_fields
            locked.prd_url = extract_prd_url(feishu_fields) or ""
            locked.tech_doc_url = extract_tech_doc_url(feishu_fields) or ""
            locked.status_state_key = new_state_key
            locked.status_sub_stage = new_sub_stage
            locked.status_display_name = status_fields["status_display_name"]
            locked.is_archived_state = status_fields["is_archived_state"]
            locked.is_init_state = status_fields["is_init_state"]
            locked.last_synced_at = timezone.now()

            provenance = dict(locked.field_provenance or {})
            for field in _MIRROR_FIELDS:
                provenance[field] = source
            locked.field_provenance = provenance

            locked.save(
                update_fields=[
                    *_MIRROR_FIELDS,
                    "last_synced_at",
                    "field_provenance",
                    "updated_at",
                ]
            )

        # 把锁内刷新结果同步回传入实例，供 upsert 返回 / 后续步骤读取最新值
        for field in (*_MIRROR_FIELDS, "last_synced_at", "field_provenance"):
            setattr(work_item, field, getattr(locked, field))

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

    @sync_to_async
    def _apply_relations(self, work_item: WorkItem, info: Any, source: str) -> None:
        """派生关系 → WorkItemRelation（占位/回填，复用 Phase 27 derive_relations_from_fields）。

        - 每个 RelationSpec 经 update_or_create（unique_together 幂等）；target 已落库
          （同 project_key + work_item_id=target_external_id）则连 target_work_item，否则占位。
        - 反向回填：本次 upsert 的 WorkItem 作为他行占位 target_external_id（同 project_key）
          的目标时，补连这些 WorkItemRelation.target_work_item（best-effort）。
        """
        specs = derive_relations_from_fields(info.feishu_fields or [])
        for spec in specs:
            target = WorkItem.objects.filter(
                feishu_project_key=work_item.feishu_project_key,
                work_item_id=spec.target_external_id,
            ).first()
            WorkItemRelation.objects.update_or_create(
                source_work_item=work_item,
                relation_type=spec.relation_type,
                target_external_id=spec.target_external_id,
                source_field_key=spec.source_field_key,
                defaults={"origin": spec.origin, "target_work_item": target},
            )

        # 反向回填：他行以本 WorkItem 的 work_item_id 占位（同 project_key）→ 补连
        WorkItemRelation.objects.filter(
            target_work_item__isnull=True,
            target_external_id=work_item.work_item_id,
            source_work_item__feishu_project_key=work_item.feishu_project_key,
        ).update(target_work_item=work_item)

    @sync_to_async
    def _backfill_status_history(self, work_item: WorkItem, raw_item: dict) -> None:
        """从 work_item_status.history[] 回填历史 StatusEvent（去重，best-effort）。

        去重键 (work_item, cur_state_key, event_time)；缺 state_key 跳过。本步骤不抛——
        历史回填属增强，失败不影响主落库。
        """
        for event in derive_status_events(raw_item):
            state_key = event.get("state_key") or ""
            if not state_key:
                continue
            event_time = self._parse_ms(event.get("updated_at"))
            exists = WorkItemStatusEvent.objects.filter(
                work_item=work_item,
                cur_state_key=state_key,
                event_time=event_time,
            ).exists()
            if exists:
                continue
            WorkItemStatusEvent.objects.create(
                work_item=work_item,
                cur_state_key=state_key,
                operator=event.get("updated_by") or "",
                event_time=event_time,
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
        """脱敏错误摘要：先抹凭证再截断长度上限（T-28-07）。

        响应 body 可能夹带敏感串（误入异常消息的 token/secret/Authorization），故先
        ``_redact_secrets`` 抹掉键名命中的值与 ``Bearer`` 串，再 ``[:limit]`` 截断；
        先脱敏后截断避免截到 token 中段而残留半截凭证。绝不向 ``SyncState.error`` 落原始凭证。
        """
        return _redact_secrets(str(exc))[:_ERROR_SNIPPET_LIMIT]

    def _parse_ms(self, raw: Any):
        """毫秒时间戳 → aware UTC datetime；缺失/非法 → None（恒 aware，与 knowledge 对齐）。"""
        if raw is None:
            return None
        try:
            ms = int(raw)
        except (TypeError, ValueError):
            return None
        if ms <= 0:
            return None
        try:
            return datetime.fromtimestamp(ms / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
