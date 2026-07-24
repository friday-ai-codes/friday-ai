"""DocumentService.create_internal_spec 内部生成文档单一写入入口测试（Phase 49-01）。

覆盖 D-49-2 内部生成文档（spec 正文）写入收口（INV-6）：

- 首次 create_internal_spec → 落 Document(sdd_spec, internal_generated, snapshot,
  external_ref="", feishu_tenant="") + DocumentVersion(v1, content_hash) +
  current_version=v1；返回 Document。
- work_item 非空连 Document.work_item；work_item=None 合法不抛（INV-2）。
- 传入既有 document 且 content_hash 与 current 相等 → 不翻版本（hash 铁律），返回同
  document；不等 → version+1 + supersedes 链 + 推进 current_version。
- 多个 internal spec（external_ref="" 多行）并存不触发飞书唯一约束（~Q(external_ref="")）。

异步 + sync_to_async 跨线程写库 → transaction=True（与既有 DocumentService 测试同理）。
"""

from __future__ import annotations

import pytest

from delivery.models import (
    ContentStorage,
    Document,
    DocumentSourceKind,
    DocumentType,
    DocumentVersion,
    WorkItem,
    WorkItemOrigin,
)
from delivery.services import DocumentService

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_work_item(work_item_id: int = 1000000002) -> WorkItem:
    return await WorkItem.objects.acreate(
        feishu_project_key="000000000000000000000001",
        work_item_type="story",
        work_item_id=work_item_id,
        origin=WorkItemOrigin.MANUAL,
        title="测试需求",
    )


async def test_first_create_internal_spec_lands_document_version() -> None:
    """首次 → Document(sdd_spec, internal_generated, snapshot, external_ref="") + v1。"""
    work_item = await _make_work_item()

    doc = await DocumentService().create_internal_spec(
        work_item=work_item,
        repository_label="backend-repo",
        content="## Why\n需求 A\n",
    )

    assert await Document.objects.acount() == 1
    assert doc.document_type == DocumentType.SDD_SPEC
    assert doc.source_kind == DocumentSourceKind.INTERNAL_GENERATED
    assert doc.content_storage == ContentStorage.SNAPSHOT
    assert doc.external_ref == ""
    assert doc.feishu_tenant == ""
    assert doc.work_item_id == work_item.id

    assert await DocumentVersion.objects.filter(document=doc).acount() == 1
    cur = await DocumentVersion.objects.aget(pk=doc.current_version_id)
    assert cur.version == 1
    assert cur.content == "## Why\n需求 A\n"
    assert cur.content_hash
    assert cur.supersedes_id is None


async def test_work_item_none_is_allowed() -> None:
    """work_item=None 合法不抛（INV-2）；Document.work_item 为空。"""
    doc = await DocumentService().create_internal_spec(
        work_item=None,
        repository_label="backend-repo",
        content="spec 正文",
    )
    assert doc.work_item_id is None
    assert await Document.objects.acount() == 1


async def test_existing_document_same_hash_no_new_version() -> None:
    """传入既有 document 且 content 相同 → 不翻版本，返回同 document。"""
    service = DocumentService()
    doc = await service.create_internal_spec(
        work_item=None,
        repository_label="backend-repo",
        content="同一正文",
    )
    v1_id = doc.current_version_id

    same = await service.create_internal_spec(
        work_item=None,
        repository_label="backend-repo",
        content="同一正文",
        document=doc,
    )

    assert same.id == doc.id
    assert await DocumentVersion.objects.filter(document=doc).acount() == 1
    assert same.current_version_id == v1_id


async def test_existing_document_changed_content_bumps_version() -> None:
    """传入既有 document 且 content 变化 → version=2 + supersedes=v1 + 推进 current。"""
    service = DocumentService()
    doc = await service.create_internal_spec(
        work_item=None,
        repository_label="backend-repo",
        content="正文 v1",
    )
    v1_id = doc.current_version_id

    doc = await service.create_internal_spec(
        work_item=None,
        repository_label="backend-repo",
        content="正文 v2（改）",
        document=doc,
    )

    assert await DocumentVersion.objects.filter(document=doc).acount() == 2
    v2 = await DocumentVersion.objects.aget(pk=doc.current_version_id)
    assert v2.version == 2
    assert v2.supersedes_id == v1_id
    assert v2.content == "正文 v2（改）"
    assert doc.current_version_id != v1_id


async def test_existing_document_backfills_work_item_when_previously_none() -> None:
    """既有 document.work_item=None，再次带 work_item → 补连。"""
    service = DocumentService()
    doc = await service.create_internal_spec(
        work_item=None,
        repository_label="backend-repo",
        content="正文 v1",
    )
    assert doc.work_item_id is None

    work_item = await _make_work_item()
    doc = await service.create_internal_spec(
        work_item=work_item,
        repository_label="backend-repo",
        content="正文 v2（改）",
        document=doc,
    )
    refreshed = await Document.objects.aget(pk=doc.id)
    assert refreshed.work_item_id == work_item.id


async def test_multiple_internal_specs_coexist_without_unique_violation() -> None:
    """多个 internal spec（external_ref="" 多行）并存不触发飞书唯一约束。"""
    service = DocumentService()
    doc1 = await service.create_internal_spec(
        work_item=None, repository_label="repo-a", content="spec A"
    )
    doc2 = await service.create_internal_spec(
        work_item=None, repository_label="repo-b", content="spec B"
    )
    assert doc1.id != doc2.id
    assert await Document.objects.filter(external_ref="").acount() == 2
