"""DocumentService —— Document/DocumentVersion 唯一写入入口（DOC-01，INV-6）。

外部飞书文档（PRD/技术方案）落库的单一写入收口：所有路径（30-03 normalizer /
后续一键摄取）都经 ``upsert_from_feishu`` 收敛，**禁旁路写 Document/DocumentVersion
表**（test_document_inv6_guard.py grep 守护）。

去重/版本范式（对齐 CONTEXT Grey Area 1，复用 knowledge "hash 相等不翻版本" 铁律）：

- external_feishu 文档按 ``(feishu_tenant, external_ref=doc_token)`` 唯一定位/去重
  （同 token 重摄收敛同一 Document）；``feishu_tenant`` 由 doc URL host 派生。
- 内容 ``content_hash`` 相等 → 不建新 ``DocumentVersion``（仅刷 last_synced_at）；
  不等 → 建新版本 + ``supersedes`` 链 + 推进 ``current_version``。
- 外部飞书文档落 ``content_storage=both``（快照 + canonical_url 引用）。

文档摄取成功时按 ``document_type`` 映射记 ``WorkItemSyncState``
（prd→prd_body / tech_plan→tech_doc）facet 完整度（对齐 §1.4）：content 非空 →
complete，缺正文（拉取失败降级）→ missing。失败策略沿用 §1.4 降级范式——缺段不缺
实体，不抛、不回滚。

**不 import / 不写 knowledge 投影模型**（INV-3：knowledge 投影由 30-03 normalizer
经既有 ingestion 管线产出，DocumentService 只管操作态）。
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from delivery.models import (
    ContentStorage,
    Document,
    DocumentSourceKind,
    DocumentType,
    DocumentVersion,
    SyncFacet,
    SyncStatus,
    WorkItem,
    WorkItemSyncState,
)

logger = structlog.get_logger(__name__)

__all__ = ["DocumentService", "derive_feishu_tenant"]

# 飞书/Lark 文档域后缀（仅对这些域派生租户）
_FEISHU_HOST_SUFFIXES = (".feishu.cn", ".larksuite.com", ".feishu.net")

# 无租户语义的首段子域（feishu.cn / www.feishu.cn 等 → 派生不出租户）
_NON_TENANT_SUBDOMAINS = {"", "www", "feishu", "larksuite"}

# document_type → SyncFacet 映射（仅 prd/tech_plan 记 facet；其余类型不记）
_DOC_TYPE_FACET = {
    DocumentType.PRD: SyncFacet.PRD_BODY,
    DocumentType.TECH_PLAN: SyncFacet.TECH_DOC,
}


def _content_hash(text: str) -> str:
    """sha256 hex —— 与 knowledge ingestion 同算法（单一来源；不 import knowledge，守 INV-3）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def derive_feishu_tenant(canonical_url: str) -> str:
    """从 doc URL host 派生租户 slug（多租户区分来源，CONTEXT Claude's Discretion）。

    ``<tenant>.feishu.cn`` / ``<tenant>.larksuite.com`` 取首段子域作为租户标识
    （如 ``acme.feishu.cn`` → "acme"）。非飞书域、解析不出 host、或首段无租户
    语义（``feishu.cn`` / ``www`` 等）→ 返回 ""。

    Args:
        canonical_url: 文档 canonical URL。

    Returns:
        租户 slug，或派生不出时的空串。
    """
    if not canonical_url:
        return ""
    try:
        hostname = (urlparse(canonical_url).hostname or "").lower()
    except ValueError:
        return ""
    if not hostname:
        return ""
    if not any(hostname.endswith(suffix) for suffix in _FEISHU_HOST_SUFFIXES):
        return ""
    first = hostname.split(".")[0]
    if first in _NON_TENANT_SUBDOMAINS:
        return ""
    return first


class DocumentService:
    """Document/DocumentVersion 唯一写入入口（INV-6）。"""

    async def upsert_from_feishu(
        self,
        *,
        work_item: WorkItem | None,
        document_type: str,
        doc_token: str,
        content: str,
        canonical_url: str,
        feishu_tenant: str = "",
        source: str = "manual",
    ) -> Document:
        """**Document/DocumentVersion 落库的唯一写入收口**（去重 + 版本范式 + facet）。

        Args:
            work_item: 关联交付脊柱（REFERENCES 操作态对应）；None=脊柱未落库占位。
            document_type: ``DocumentType`` 值（prd/tech_plan/...）。
            doc_token: 飞书 doc token（external_ref，去重键之一）。
            content: 文档正文快照；空串=拉取失败降级（缺段不缺实体）。
            canonical_url: 文档 canonical URL（落 both 引用 + 派生租户）。
            feishu_tenant: 显式租户；空则由 ``canonical_url`` 派生。
            source: 调用方来源（WorkItemOrigin 值，记入 SyncState.source）。

        Returns:
            收敛后的 Document 实例。
        """
        tenant = feishu_tenant or derive_feishu_tenant(canonical_url)
        document = await self._upsert_locked(
            work_item=work_item,
            document_type=document_type,
            doc_token=doc_token,
            content=content,
            canonical_url=canonical_url,
            tenant=tenant,
        )

        # facet 记录（work_item 非空 + 可映射类型时）：content 非空 complete，缺正文 missing。
        if work_item is not None:
            facet = _DOC_TYPE_FACET.get(document_type)
            if facet is not None:
                status = SyncStatus.COMPLETE if content else SyncStatus.MISSING
                await self._record_sync_state(work_item, facet, status, source)

        return document

    async def create_internal_spec(
        self,
        *,
        work_item: WorkItem | None,
        repository_label: str,
        content: str,
        title: str = "",
        document: Document | None = None,
    ) -> Document:
        """**内部生成文档（spec 正文）落库的唯一写入收口**（D-49-2，INV-6）。

        与 ``upsert_from_feishu``（external_feishu）并列——二者都收口于 DocumentService，
        禁旁路写 Document/DocumentVersion（test_document_inv6_guard 守护）。内部文档
        ``external_ref=""`` / ``feishu_tenant=""``（豁免飞书去重唯一约束
        ``~Q(external_ref="")``），不派生 feishu_tenant、不记 WorkItemSyncState facet
        （facet 仅 prd/tech_plan）。

        Args:
            work_item: 关联交付脊柱（SPEC-02 追溯）；None=chat 自然语言需求（INV-2）。
            repository_label: SDD 仓标识（仅入日志上下文；内部 spec 无 external_ref，
                不持久化为 external_ref——不得伪造破坏豁免语义）。
            content: spec 正文快照；空串合法（缺段不缺实体）。
            title: 预留位（本 phase 未持久化为独立字段）。
            document: 既有 Document（version-existing 路径，供 SddSpecService 幂等/版本
                复用）；None=首建。

        Returns:
            落库后的 Document 实例。
        """
        logger.info(
            "create_internal_spec",
            repository_label=repository_label,
            work_item_id=str(work_item.id) if work_item is not None else None,
            existing_document=str(document.id) if document is not None else None,
        )
        return await self._create_internal_spec_locked(
            work_item=work_item,
            content=content,
            document=document,
        )

    @sync_to_async
    def _create_internal_spec_locked(
        self,
        *,
        work_item: WorkItem | None,
        content: str,
        document: Document | None,
    ) -> Document:
        """单锁原子：首建 internal Document / 既有 document 取锁 → hash 判定翻版本。

        ``document is None``：建 Document(sdd_spec, internal_generated, snapshot,
        external_ref="", feishu_tenant="")。``document`` 给定：``select_for_update``
        取锁，work_item 先前 None 现非空则补连。版本范式与 ``_upsert_locked`` 一致：
        current content_hash 相等不翻版本，否则建 version+1 接 supersedes 链并推进
        current_version。
        """
        new_hash = _content_hash(content)
        with transaction.atomic():
            if document is None:
                document = Document.objects.create(
                    document_type=DocumentType.SDD_SPEC,
                    source_kind=DocumentSourceKind.INTERNAL_GENERATED,
                    content_storage=ContentStorage.SNAPSHOT,
                    external_ref="",
                    feishu_tenant="",
                    work_item=work_item,
                )
            else:
                document = Document.objects.select_for_update().get(id=document.id)
                if document.work_item_id is None and work_item is not None:
                    document.work_item = work_item
                    document.save(update_fields=["work_item", "updated_at"])

            cur = document.current_version
            # hash 相等不翻版本（knowledge 铁律）
            if cur is not None and cur.content_hash == new_hash:
                return document

            new_version = DocumentVersion.objects.create(
                document=document,
                version=(cur.version + 1 if cur else 1),
                supersedes=cur,
                content=content,
                content_hash=new_hash,
            )
            document.current_version = new_version
            document.save(update_fields=["current_version", "updated_at"])
            return document

    @sync_to_async
    def _upsert_locked(
        self,
        *,
        work_item: WorkItem | None,
        document_type: str,
        doc_token: str,
        content: str,
        canonical_url: str,
        tenant: str,
    ) -> Document:
        """单锁原子：取/建 Document → hash 判定 → 翻版本 + 推进 current_version。

        ``(feishu_tenant, external_ref)`` 经 ``select_for_update().get_or_create``
        去重定位（首建落 both + canonical_url + work_item）。已存在时刷新 mirror 类
        字段（canonical_url、work_item 若先前 None 则补连；document_type 不漂移）。
        版本：current_version 存在且 content_hash 相等 → 不翻版本；否则建新版本接
        supersedes 链并推进 current_version。
        """
        new_hash = _content_hash(content)
        with transaction.atomic():
            document, created = Document.objects.select_for_update().get_or_create(
                feishu_tenant=tenant,
                external_ref=doc_token,
                defaults={
                    "document_type": document_type,
                    "source_kind": DocumentSourceKind.EXTERNAL_FEISHU,
                    "content_storage": ContentStorage.BOTH,
                    "canonical_url": canonical_url,
                    "work_item": work_item,
                },
            )

            update_fields = ["last_synced_at", "updated_at"]
            # 已存在：刷新 mirror 类字段（document_type 保持首建——doc_token 不变 type 不漂移）
            if not created:
                if canonical_url and document.canonical_url != canonical_url:
                    document.canonical_url = canonical_url
                    update_fields.append("canonical_url")
                if document.work_item_id is None and work_item is not None:
                    document.work_item = work_item
                    update_fields.append("work_item")

            cur = document.current_version
            document.last_synced_at = timezone.now()

            # hash 相等不翻版本（knowledge 铁律）：仅刷 last_synced_at（+ 已变更 mirror）
            if cur is not None and cur.content_hash == new_hash:
                document.save(update_fields=update_fields)
                return document

            new_version = DocumentVersion.objects.create(
                document=document,
                version=(cur.version + 1 if cur else 1),
                supersedes=cur,
                content=content,
                content_hash=new_hash,
            )
            document.current_version = new_version
            update_fields.append("current_version")
            document.save(update_fields=update_fields)
            return document

    @sync_to_async
    def _record_sync_state(
        self,
        work_item: WorkItem,
        facet: str,
        status: str,
        source: str,
    ) -> None:
        """按 (work_item, facet) 落 WorkItemSyncState（update_or_create 幂等，复用 28-02 范式）。"""
        WorkItemSyncState.objects.update_or_create(
            work_item=work_item,
            facet=facet,
            defaults={
                "status": status,
                "source": source,
                "last_synced_at": timezone.now() if status == SyncStatus.COMPLETE else None,
                "error": "",
            },
        )
