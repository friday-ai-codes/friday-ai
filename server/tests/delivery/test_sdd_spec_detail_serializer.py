"""SddSpecDetailSerializer 交付验收追溯摘要守护（Phase 52-02，D-52-4，LINK-01/LINK-02）。

覆盖 D-52-4 后端：detail 序列化暴露 spec → 需求 → PR 完整追溯 JSON——

- implementation_prs：detail 输出该字段为列表；无回填 → 空列表 []（天然 fail-soft）。
- work_item 追溯：relations.work_item 含 {id, title, url}，url 取 prd_url（无 prd_url → ""）；
  无 work_item → relations 不含 work_item 键（降级不报错）。
- artifact_version 追溯：relations.artifact_version 含 {id, version}；无 → 不含该键。
- 列表序列化（SddSpecListSerializer）不暴露 implementation_prs（仅 detail）。

纯序列化器单测（sync），无 async ORM；建模 fixture 对齐 test_spec_api.py 范式。
"""

from __future__ import annotations

import uuid

import pytest

from delivery.api.serializers import SddSpecDetailSerializer, SddSpecListSerializer
from delivery.models import (
    Artifact,
    ArtifactVersion,
    SddSpec,
    SddSpecStatus,
    WorkItem,
    WorkItemOrigin,
)
from repositories.models import Repository

pytestmark = pytest.mark.django_db


def _make_repo() -> Repository:
    return Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


def _make_work_item(*, prd_url: str = "") -> WorkItem:
    return WorkItem.objects.create(
        feishu_project_key="proj",
        work_item_type="story",
        work_item_id=int(uuid.uuid4().int % 1_000_000_000),
        origin=WorkItemOrigin.MANUAL,
        title="交付需求",
        prd_url=prd_url,
    )


def _make_artifact_version() -> ArtifactVersion:
    plan = Artifact.objects.create(artifact_type="technical_plan")
    return ArtifactVersion.objects.create(artifact=plan, version_no=3, content={}, content_hash="h")


def test_detail_exposes_implementation_prs() -> None:
    """有回填 → implementation_prs 含 PR 列表。"""
    repo = _make_repo()
    prs = [
        {"pr_url": "https://github.com/test/r/pull/1", "repository_id": str(repo.id), "linked_at": "2026-06-17T00:00:00Z"},
    ]
    spec = SddSpec.objects.create(repository=repo, status=SddSpecStatus.IMPLEMENTED, implementation_prs=prs)
    data = SddSpecDetailSerializer(spec).data
    assert data["implementation_prs"] == prs


def test_detail_implementation_prs_empty_when_no_backfill() -> None:
    """无回填 → implementation_prs 为空列表（fail-soft）。"""
    spec = SddSpec.objects.create(repository=_make_repo())
    data = SddSpecDetailSerializer(spec).data
    assert data["implementation_prs"] == []


def test_detail_work_item_includes_url_from_prd_url() -> None:
    """work_item 有 prd_url → relations.work_item 含 url/title。"""
    wi = _make_work_item(prd_url="https://feishu.example/prd/1")
    spec = SddSpec.objects.create(repository=_make_repo(), work_item=wi)
    rel = SddSpecDetailSerializer(spec).data["relations"]
    assert rel["work_item"]["id"] == str(wi.id)
    assert rel["work_item"]["title"] == "交付需求"
    assert rel["work_item"]["url"] == "https://feishu.example/prd/1"


def test_detail_work_item_url_blank_when_no_prd_url() -> None:
    """work_item 有 title 无 prd_url → url 为空串（不臆造 URL）。"""
    wi = _make_work_item(prd_url="")
    spec = SddSpec.objects.create(repository=_make_repo(), work_item=wi)
    rel = SddSpecDetailSerializer(spec).data["relations"]
    assert rel["work_item"]["url"] == ""
    assert rel["work_item"]["title"] == "交付需求"


def test_detail_relations_omits_work_item_when_absent() -> None:
    """无 work_item → relations 不含 work_item 键（降级不报错）。"""
    spec = SddSpec.objects.create(repository=_make_repo())
    rel = SddSpecDetailSerializer(spec).data["relations"]
    assert "work_item" not in rel


def test_detail_relations_includes_artifact_version() -> None:
    """有 artifact_version → relations.artifact_version 含 version。"""
    pv = _make_artifact_version()
    spec = SddSpec.objects.create(repository=_make_repo(), artifact_version=pv)
    rel = SddSpecDetailSerializer(spec).data["relations"]
    assert rel["artifact_version"]["id"] == str(pv.id)
    assert rel["artifact_version"]["version"] == 3


def test_list_serializer_omits_implementation_prs() -> None:
    """列表序列化不暴露 implementation_prs（仅 detail）。"""
    spec = SddSpec.objects.create(repository=_make_repo(), implementation_prs=[{"pr_url": "x"}])
    data = SddSpecListSerializer(spec).data
    assert "implementation_prs" not in data
