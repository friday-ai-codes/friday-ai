"""DocumentService.upsert_from_feishu 单一写入入口守护测试（Phase 30-02）。

覆盖 DOC-01 写入收口（INV-6）与 CONTEXT Grey Area 1/4：

- 首摄建 Document(external_feishu, content_storage=both) + DocumentVersion(v1) +
  current_version=v1；feishu_tenant 由 doc URL host 派生。
- 去重：同 (feishu_tenant, external_ref=doc_token) 再摄收敛同一 Document（不新增行）。
- 版本范式（复用 knowledge "hash 相等不翻版本" 铁律）：content_hash 相等不建新版本；
  不等 → version=2 + supersedes=v1 + current_version 推进。
- facet 记录：prd 且 content 非空 → SyncState(prd_body)=complete；content 空 → missing；
  tech_plan → tech_doc facet。
- work_item=None 不抛、不记 facet、Document.work_item 为空。
- derive_feishu_tenant 纯函数派生（acme.feishu.cn → acme；非飞书域 / 无意义首段 → ""）。

无真实网络（pytest-socket 隔离；DocumentService 不回源，content 由调用方传入）。
异步 + sync_to_async 跨线程写库 → transaction=True（与 28-02 service 测试同理）。
"""

from __future__ import annotations

import pytest

from delivery.models import (
    ContentStorage,
    Document,
    DocumentSourceKind,
    DocumentType,
    DocumentVersion,
    SyncFacet,
    SyncStatus,
    WorkItem,
    WorkItemOrigin,
    WorkItemSyncState,
)
from delivery.services import DocumentService, derive_feishu_tenant

pytestmark = pytest.mark.django_db(transaction=True)

# DOMAIN §16 实测自然键 + 多租户深链
PROJECT_KEY = "000000000000000000000001"
STORY_ID = 1000000002
DOC_TOKEN = "Abcd1234efGhIjKl"
PRD_URL = f"https://acme.feishu.cn/docx/{DOC_TOKEN}"


async def _make_work_item(work_item_id: int = STORY_ID) -> WorkItem:
    """建一个 story WorkItem（origin=manual）。"""
    return await WorkItem.objects.acreate(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=work_item_id,
        origin=WorkItemOrigin.MANUAL,
        title="测试需求",
    )


# ============================================================================
# derive_feishu_tenant 纯函数（无 DB / 无网络）
# ============================================================================


def test_derive_feishu_tenant_from_doc_url() -> None:
    """<tenant>.feishu.cn → 取首段子域作为租户 slug。"""
    assert derive_feishu_tenant("https://acme.feishu.cn/docx/abc") == "acme"
    assert derive_feishu_tenant("https://acme.larksuite.com/docx/xyz") == "acme"


def test_derive_feishu_tenant_non_feishu_or_meaningless_returns_empty() -> None:
    """非飞书域 / 无意义首段（feishu.cn / www）/ 空 → ""。"""
    assert derive_feishu_tenant("") == ""
    assert derive_feishu_tenant("https://feishu.cn/docx/abc") == ""
    assert derive_feishu_tenant("https://www.feishu.cn/docx/abc") == ""
    assert derive_feishu_tenant("https://example.com/docx/abc") == ""
    assert derive_feishu_tenant("not-a-url") == ""


# ============================================================================
# upsert_from_feishu —— 首摄 + 去重 + 版本范式 + facet
# ============================================================================


async def test_first_ingest_creates_document_version_and_facet() -> None:
    """首摄建 Document(both, external_feishu) + v1 + current_version=v1 + tenant 派生 + facet complete。"""
    work_item = await _make_work_item()

    doc = await DocumentService().upsert_from_feishu(
        work_item=work_item,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="PRD 正文 v1",
        canonical_url=PRD_URL,
        source=WorkItemOrigin.MANUAL,
    )

    assert await Document.objects.acount() == 1
    assert doc.source_kind == DocumentSourceKind.EXTERNAL_FEISHU
    assert doc.content_storage == ContentStorage.BOTH
    assert doc.external_ref == DOC_TOKEN
    assert doc.feishu_tenant == "acme"
    assert doc.canonical_url == PRD_URL
    assert doc.work_item_id == work_item.id

    assert await DocumentVersion.objects.filter(document=doc).acount() == 1
    cur = await DocumentVersion.objects.aget(pk=doc.current_version_id)
    assert cur.version == 1
    assert cur.content == "PRD 正文 v1"
    assert cur.supersedes_id is None

    state = await WorkItemSyncState.objects.aget(work_item=work_item, facet=SyncFacet.PRD_BODY)
    assert state.status == SyncStatus.COMPLETE


async def test_dedup_same_tenant_and_token_converges_one_document() -> None:
    """去重：同 (feishu_tenant, doc_token) 再摄收敛同一 Document（不新增 Document 行）。"""
    work_item = await _make_work_item()
    service = DocumentService()

    doc1 = await service.upsert_from_feishu(
        work_item=work_item,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="PRD 正文 v1",
        canonical_url=PRD_URL,
    )
    doc2 = await service.upsert_from_feishu(
        work_item=work_item,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="PRD 正文 v1",
        canonical_url=PRD_URL,
    )

    assert doc1.id == doc2.id
    assert await Document.objects.acount() == 1


async def test_hash_equal_does_not_create_new_version() -> None:
    """content_hash 相等再摄 → DocumentVersion 计数不变（不翻版本）。"""
    work_item = await _make_work_item()
    service = DocumentService()

    doc = await service.upsert_from_feishu(
        work_item=work_item,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="同一正文",
        canonical_url=PRD_URL,
    )
    v1_id = doc.current_version_id

    doc = await service.upsert_from_feishu(
        work_item=work_item,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="同一正文",
        canonical_url=PRD_URL,
    )

    assert await DocumentVersion.objects.filter(document=doc).acount() == 1
    assert doc.current_version_id == v1_id


async def test_content_change_bumps_version_with_supersedes_and_current() -> None:
    """content 变化（hash 不等）→ version=2 + supersedes=v1 + current_version 推进 v2。"""
    work_item = await _make_work_item()
    service = DocumentService()

    doc = await service.upsert_from_feishu(
        work_item=work_item,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="正文 v1",
        canonical_url=PRD_URL,
    )
    v1_id = doc.current_version_id

    doc = await service.upsert_from_feishu(
        work_item=work_item,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="正文 v2（改动）",
        canonical_url=PRD_URL,
    )

    assert await DocumentVersion.objects.filter(document=doc).acount() == 2
    v2 = await DocumentVersion.objects.aget(pk=doc.current_version_id)
    assert v2.version == 2
    assert v2.supersedes_id == v1_id
    assert v2.content == "正文 v2（改动）"
    assert doc.current_version_id != v1_id


async def test_empty_content_records_facet_missing_no_raise() -> None:
    """缺正文降级：content 空仍 upsert（缺段不缺实体），facet 记 missing，不抛。"""
    work_item = await _make_work_item()

    doc = await DocumentService().upsert_from_feishu(
        work_item=work_item,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="",
        canonical_url=PRD_URL,
    )

    assert await Document.objects.acount() == 1
    assert await DocumentVersion.objects.filter(document=doc).acount() == 1
    state = await WorkItemSyncState.objects.aget(work_item=work_item, facet=SyncFacet.PRD_BODY)
    assert state.status == SyncStatus.MISSING


async def test_tech_plan_records_tech_doc_facet() -> None:
    """document_type=tech_plan 成功 → SyncState(tech_doc)=complete。"""
    work_item = await _make_work_item()

    await DocumentService().upsert_from_feishu(
        work_item=work_item,
        document_type=DocumentType.TECH_PLAN,
        doc_token="TechDocToken99",
        content="技术方案正文",
        canonical_url="https://acme.feishu.cn/docx/TechDocToken99",
    )

    state = await WorkItemSyncState.objects.aget(work_item=work_item, facet=SyncFacet.TECH_DOC)
    assert state.status == SyncStatus.COMPLETE
    # prd_body facet 不应被 tech_plan 摄取写入
    assert not await WorkItemSyncState.objects.filter(
        work_item=work_item, facet=SyncFacet.PRD_BODY
    ).aexists()


async def test_work_item_none_skips_facet_no_raise() -> None:
    """work_item=None（脊柱未落库）→ Document.work_item 置空，不记 facet，不抛。"""
    doc = await DocumentService().upsert_from_feishu(
        work_item=None,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="PRD 正文",
        canonical_url=PRD_URL,
    )

    assert doc.work_item_id is None
    assert await Document.objects.acount() == 1
    assert await WorkItemSyncState.objects.acount() == 0


async def test_explicit_tenant_overrides_url_derivation() -> None:
    """显式传 feishu_tenant 覆盖 URL 派生（去重键用显式值）。"""
    work_item = await _make_work_item()

    doc = await DocumentService().upsert_from_feishu(
        work_item=work_item,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="正文",
        canonical_url=PRD_URL,
        feishu_tenant="explicit_tenant",
    )

    assert doc.feishu_tenant == "explicit_tenant"


async def test_backfill_work_item_when_previously_none() -> None:
    """已存在 Document.work_item=None，后续带 work_item 再摄 → 补连 work_item。"""
    service = DocumentService()
    doc1 = await service.upsert_from_feishu(
        work_item=None,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="正文",
        canonical_url=PRD_URL,
    )
    assert doc1.work_item_id is None

    work_item = await _make_work_item()
    doc2 = await service.upsert_from_feishu(
        work_item=work_item,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="正文",
        canonical_url=PRD_URL,
    )

    assert doc1.id == doc2.id
    refreshed = await Document.objects.aget(pk=doc1.id)
    assert refreshed.work_item_id == work_item.id


# ============================================================================
# WR-01: (feishu_tenant, external_ref) DB 级唯一约束（并发去重）
# ============================================================================


async def test_duplicate_external_ref_raises_integrity_error() -> None:
    """同 (feishu_tenant, external_ref) 旁路直插第二行 → IntegrityError（约束生效，WR-01）。"""
    from django.db import IntegrityError

    await Document.objects.acreate(
        document_type=DocumentType.PRD,
        source_kind=DocumentSourceKind.EXTERNAL_FEISHU,
        external_ref=DOC_TOKEN,
        feishu_tenant="acme",
    )
    with pytest.raises(IntegrityError):
        await Document.objects.acreate(
            document_type=DocumentType.PRD,
            source_kind=DocumentSourceKind.EXTERNAL_FEISHU,
            external_ref=DOC_TOKEN,
            feishu_tenant="acme",
        )


async def test_empty_external_ref_exempt_from_unique() -> None:
    """空 external_ref 行豁免唯一约束（internal_generated / 无 token 不在空键互撞，WR-01）。"""
    await Document.objects.acreate(
        document_type=DocumentType.RELEASE_NOTE,
        source_kind=DocumentSourceKind.INTERNAL_GENERATED,
        external_ref="",
        feishu_tenant="",
    )
    await Document.objects.acreate(
        document_type=DocumentType.SDD_SPEC,
        source_kind=DocumentSourceKind.INTERNAL_GENERATED,
        external_ref="",
        feishu_tenant="",
    )
    assert await Document.objects.filter(external_ref="").acount() == 2


async def test_upsert_idempotent_under_unique_constraint() -> None:
    """约束存在下 upsert_from_feishu 仍幂等收敛同一 Document（不抛、不建重复）。"""
    service = DocumentService()
    doc1 = await service.upsert_from_feishu(
        work_item=None,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="正文",
        canonical_url=PRD_URL,
    )
    doc2 = await service.upsert_from_feishu(
        work_item=None,
        document_type=DocumentType.PRD,
        doc_token=DOC_TOKEN,
        content="正文 v2",
        canonical_url=PRD_URL,
    )
    assert doc1.id == doc2.id
    assert (
        await Document.objects.filter(feishu_tenant="acme", external_ref=DOC_TOKEN).acount() == 1
    )
