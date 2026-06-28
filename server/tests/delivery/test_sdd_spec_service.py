"""SddSpecService.create_draft 单一写入入口测试（Phase 49-02）。

覆盖 D-49-3 SddSpec 写入收口（INV-6）+ 幂等：

- 首次 create_draft → 经 DocumentService.create_internal_spec 落 Document(sdd_spec) +
  建 SddSpec(status=draft, change_kind) 连 document/work_item/artifact_version_id/repository。
- 重产同 (artifact_version_id, repository)：返回既有 SddSpec，不新增 SddSpec 行，且不新增
  Document/DocumentVersion（幂等短路：先探测命中即返回，不再调 create_internal_spec）。
- work_item=None 合法不抛（INV-2）。

异步 + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import uuid

import pytest

from delivery.models import (
    Artifact,
    Document,
    DocumentSourceKind,
    DocumentType,
    DocumentVersion,
    SddSpec,
    SddSpecStatus,
    WorkItem,
    WorkItemOrigin,
)
from delivery.services import SddSpecService
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_repo() -> Repository:
    return await Repository.objects.acreate(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


async def _make_work_item() -> WorkItem:
    return await WorkItem.objects.acreate(
        feishu_project_key="622c10eb5daaee81db915189",
        work_item_type="story",
        work_item_id=7010225564,
        origin=WorkItemOrigin.MANUAL,
        title="测试需求",
    )


async def _make_artifact_version_id() -> str:
    """建一个 canonical TechnicalPlan + v1，返回 ArtifactVersion.id（标量）。"""
    plan = await Artifact.objects.acreate(artifact_type="technical_plan")
    from delivery.models import ArtifactVersion

    pv = await ArtifactVersion.objects.acreate(artifact=plan, version_no=1, content={}, content_hash="h")
    return str(pv.id)


async def test_first_create_draft_lands_document_and_sdd_spec() -> None:
    """首产：建 Document(sdd_spec, internal_generated) + SddSpec(draft) 关联齐全。"""
    repo = await _make_repo()
    work_item = await _make_work_item()
    pv_id = await _make_artifact_version_id()

    spec = await SddSpecService().create_draft(
        artifact_version_id=pv_id,
        repository=repo,
        work_item=work_item,
        content="## Why\n需求\n",
    )

    assert isinstance(spec, SddSpec)
    assert spec.status == SddSpecStatus.DRAFT
    assert spec.change_kind == "proposal"
    assert str(spec.artifact_version_id) == pv_id
    assert spec.repository_id == repo.id
    assert spec.work_item_id == work_item.id

    doc = await Document.objects.aget(pk=spec.document_id)
    assert doc.document_type == DocumentType.SDD_SPEC
    assert doc.source_kind == DocumentSourceKind.INTERNAL_GENERATED

    assert await SddSpec.objects.acount() == 1
    assert await Document.objects.filter(document_type=DocumentType.SDD_SPEC).acount() == 1
    assert await DocumentVersion.objects.filter(document=doc).acount() == 1


async def test_recreate_same_key_is_idempotent_no_new_rows() -> None:
    """重产同 (artifact_version_id, repository)：返回既有 SddSpec，不新增 SddSpec/Document/Version。"""
    repo = await _make_repo()
    pv_id = await _make_artifact_version_id()
    service = SddSpecService()

    spec1 = await service.create_draft(
        artifact_version_id=pv_id, repository=repo, work_item=None, content="正文 v1"
    )
    spec2 = await service.create_draft(
        artifact_version_id=pv_id, repository=repo, work_item=None, content="正文 v2 不同"
    )

    assert spec1.id == spec2.id
    assert await SddSpec.objects.acount() == 1
    assert await Document.objects.filter(document_type=DocumentType.SDD_SPEC).acount() == 1
    # 短路不调 create_internal_spec → 不翻版本
    assert await DocumentVersion.objects.filter(document_id=spec1.document_id).acount() == 1


async def test_work_item_none_is_allowed() -> None:
    """work_item=None 合法不抛（INV-2）。"""
    repo = await _make_repo()
    pv_id = await _make_artifact_version_id()

    spec = await SddSpecService().create_draft(
        artifact_version_id=pv_id, repository=repo, work_item=None, content="正文"
    )
    assert spec.work_item_id is None
    assert spec.status == SddSpecStatus.DRAFT


async def test_change_kind_delta_persisted() -> None:
    """change_kind 透传落库。"""
    repo = await _make_repo()
    pv_id = await _make_artifact_version_id()

    spec = await SddSpecService().create_draft(
        artifact_version_id=pv_id,
        repository=repo,
        work_item=None,
        content="正文",
        change_kind="delta",
    )
    assert spec.change_kind == "delta"
