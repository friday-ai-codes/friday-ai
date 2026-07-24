"""Document / DocumentVersion 模型层单测（Phase 30-01）。

纯 ORM、无网络（pytest-socket 隔离）、无 DocumentService 依赖——直接建实例
验证 schema / 约束 / FK 行为。核心覆盖：

- Document 字段可读回（external_feishu / prd / both）。
- DocumentVersion + Document.current_version 指向当前版本，读回正文。
- unique_together(document, version) 重复抛 IntegrityError（T-30-01）。
- supersedes 自引用版本链可建可读。
- work_item FK 反查 wi.documents；work_item=None 占位亦可建。
- current_version on_delete=SET_NULL：删被指向版本后 Document 行保留、置 None。

fixture 取值参考 DOMAIN §16 实测（story 1000000002）。
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from delivery.models import (
    ContentStorage,
    Document,
    DocumentSourceKind,
    DocumentType,
    DocumentVersion,
    WorkItem,
    WorkItemOrigin,
)

pytestmark = pytest.mark.django_db

# DOMAIN §16 实测自然键
PROJECT_KEY = "000000000000000000000001"


def _make_work_item(work_item_id: int = 1000000002, **overrides) -> WorkItem:
    """创建一个 story WorkItem（origin=manual），允许 override。"""
    defaults = dict(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=work_item_id,
        origin=WorkItemOrigin.MANUAL,
        title="测试需求",
    )
    defaults.update(overrides)
    return WorkItem.objects.create(**defaults)


def _make_document(**overrides) -> Document:
    """创建一个 external_feishu PRD Document，允许 override。"""
    defaults = dict(
        document_type=DocumentType.PRD,
        source_kind=DocumentSourceKind.EXTERNAL_FEISHU,
        content_storage=ContentStorage.BOTH,
        external_ref="doc_tok",
        feishu_tenant="acme",
    )
    defaults.update(overrides)
    return Document.objects.create(**defaults)


def test_create_document_readback():
    """创建 external_feishu PRD Document 后字段可读回，默认值正确。"""
    doc = _make_document(canonical_url="https://acme.feishu.cn/docx/doc_tok")
    fetched = Document.objects.get(pk=doc.pk)
    assert fetched.document_type == DocumentType.PRD
    assert fetched.source_kind == DocumentSourceKind.EXTERNAL_FEISHU
    assert fetched.content_storage == ContentStorage.BOTH
    assert fetched.external_ref == "doc_tok"
    assert fetched.feishu_tenant == "acme"
    assert fetched.canonical_url == "https://acme.feishu.cn/docx/doc_tok"
    # 默认值
    assert fetched.writeback_allowed is False
    assert fetched.current_version is None
    assert fetched.work_item is None
    assert fetched.last_synced_at is None


def test_current_version_points_to_version():
    """DocumentVersion 落库 + Document.current_version 指向，读回正文。"""
    doc = _make_document()
    ver = DocumentVersion.objects.create(
        document=doc,
        version=1,
        content="正文",
        content_hash="a" * 64,
    )
    doc.current_version = ver
    doc.save(update_fields=["current_version"])

    fetched = Document.objects.get(pk=doc.pk)
    assert fetched.current_version is not None
    assert fetched.current_version.content == "正文"
    # 反查 versions
    assert doc.versions.count() == 1


def test_document_version_unique_together():
    """同 document 同 version 第二次 create → IntegrityError（T-30-01）。"""
    doc = _make_document()
    DocumentVersion.objects.create(document=doc, version=1, content="v1")
    with pytest.raises(IntegrityError):
        DocumentVersion.objects.create(document=doc, version=1, content="dup")


def test_document_version_distinct_versions_allowed():
    """同 document 不同 version 可共存。"""
    doc = _make_document()
    DocumentVersion.objects.create(document=doc, version=1)
    DocumentVersion.objects.create(document=doc, version=2)
    assert doc.versions.count() == 2


def test_supersedes_self_reference():
    """supersedes 自引用：v2.supersedes=v1 可建可读，反查 superseded_by。"""
    doc = _make_document()
    v1 = DocumentVersion.objects.create(document=doc, version=1, content="v1")
    v2 = DocumentVersion.objects.create(document=doc, version=2, content="v2", supersedes=v1)
    fetched = DocumentVersion.objects.get(pk=v2.pk)
    assert fetched.supersedes_id == v1.id
    assert v1.superseded_by.count() == 1


def test_work_item_fk_and_reverse():
    """work_item FK 反查 wi.documents 命中；work_item=None 占位亦可建。"""
    wi = _make_work_item()
    doc = _make_document(work_item=wi)
    assert wi.documents.count() == 1
    assert wi.documents.first().pk == doc.pk
    # work_item=None 占位
    orphan = _make_document(external_ref="orphan")
    assert orphan.work_item is None


def test_current_version_set_null_on_delete():
    """删被 current_version 指向的版本后 Document 行保留、current_version 置 None。"""
    doc = _make_document()
    ver = DocumentVersion.objects.create(document=doc, version=1, content="v1")
    doc.current_version = ver
    doc.save(update_fields=["current_version"])

    # 删除被指向的版本（独立事务后重取断言）
    with transaction.atomic():
        DocumentVersion.objects.filter(pk=ver.pk).delete()

    doc.refresh_from_db()
    assert Document.objects.filter(pk=doc.pk).exists()
    assert doc.current_version is None
