"""ContextLinkService + 上下文关联 REST API 守护测试（「生成知识关联」）。

覆盖：
- agenerate 编排：委托 RepoAssociationService.propose（不旁路）+ 知识/工件候选分流
  （排除本项目自身工件/项目实体）+ MR 标题命中 → 统一落 ProjectContextLink(proposed, ai)。
- 生成幂等纪律：rejected 不复活、manual/accepted 不被覆盖、AI proposed 可刷新。
- REST：成员可列表/生成/接受/拒绝/手动添加/删除；外人 403；仓库候选裁决
  accept → confirmed / reject → rejected（走 RepoAssociationService 收口）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from initiatives.models import (
    Artifact,
    ArtifactType,
    ContextLinkKind,
    ContextLinkOrigin,
    ContextLinkStatus,
    MergeRequest,
    Project,
    ProjectContextLink,
    ProjectMember,
    ProjectRole,
    RepoAssociation,
    RepoAssociationStatus,
)
from initiatives.services.context_link_service import ContextLinkService
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()

_SVC_MOD = "initiatives.services.context_link_service"
_TREE = {
    "modules": [
        {
            "module": "鉴权",
            "features": [
                {"name": "登录", "acceptance": ["支持飞书扫码登录"]},
                {"name": "登出", "acceptance": []},
            ],
        }
    ]
}


# ===========================================================================
# fixtures / helpers
# ===========================================================================


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="CtxLink Space", feishu_project_key="ctx-space")


@pytest.fixture
def project(db, space) -> Project:
    return Project.objects.create(space=space, name="P", feishu_project_key="")


@pytest.fixture
def member(db, project):
    u = User.objects.create_user(username="ctx_member", password="x")
    ProjectMember.objects.create(project=project, user=u, role=ProjectRole.OWNER)
    return u


@pytest.fixture
def outsider(db):
    return User.objects.create_user(username="ctx_outsider", password="x")


@pytest.fixture
def repo(db, space) -> Repository:
    r = Repository.objects.create(name="repoA", git_url="https://git/repoA.git")
    space.repositories.add(r)
    return r


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _hit(
    *,
    score: float,
    entity_kind: str,
    title: str,
    artifact: dict | None = None,
    source_id: str = "",
    entity_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        score=score,
        toc_path=[],
        entity=SimpleNamespace(
            entity_id=entity_id or uuid.uuid4(),
            entity_kind=entity_kind,
            title=title,
            source_id=source_id,
            artifact=artifact,
        ),
    )


def _patches(project, hits, repo_result=None):
    """打包 agenerate 依赖的四个 patch（构树 / 选仓 / 知识检索 / 留痕）。"""
    return (
        patch(
            "initiatives.services.feature_list_service.FeatureListService.build_tree",
            AsyncMock(return_value=_TREE),
        ),
        patch(
            "initiatives.services.repo_association_service.RepoAssociationService.propose",
            AsyncMock(return_value=repo_result or {"candidates": [], "router_version": "v2"}),
        ),
        patch(
            "knowledge.retrieval.DeliveryKnowledgeSearchService.search_similar",
            AsyncMock(return_value=hits),
        ),
        patch(f"{_SVC_MOD}.arecord_retrieval_trace", AsyncMock(return_value=None)),
    )


async def _agenerate(project, member, hits, repo_result=None):
    p1, p2, p3, p4 = _patches(project, hits, repo_result)
    with p1, p2 as propose_mock, p3, p4:
        summary = await ContextLinkService().agenerate(
            project, user=member, initiated_by_user_id=member.id
        )
    return summary, propose_mock


# ===========================================================================
# agenerate — 编排 + 分流 + 幂等纪律
# ===========================================================================


async def test_generate_creates_proposed_candidates(project, member, repo) -> None:
    other_space = await sync_to_async(Space.objects.create)(
        name="Other", feishu_project_key="other-space"
    )
    other_project = await sync_to_async(Project.objects.create)(
        space=other_space, name="OtherP", feishu_project_key=""
    )
    atype = await sync_to_async(ArtifactType.objects.create)(
        key="prd_ctx", name="PRD", carrier="external_link"
    )
    other_artifact = await sync_to_async(Artifact.objects.create)(
        project=other_project,
        type=atype,
        carrier="external_link",
        title="外部 PRD",
        url="https://doc/prd",
    )
    own_artifact = await sync_to_async(Artifact.objects.create)(
        project=project,
        type=atype,
        carrier="external_link",
        title="本项目 PRD",
        url="https://doc/own",
    )
    # 空间仓库内的 MR：标题命中「登录」应成候选；已挂本项目的 MR 排除。
    await sync_to_async(MergeRequest.objects.create)(
        repository=repo,
        platform="github",
        external_id="10",
        title="feat: 登录页面重构",
        url="https://git/pr/10",
    )
    await sync_to_async(MergeRequest.objects.create)(
        repository=repo,
        platform="github",
        external_id="11",
        project=project,
        title="feat: 登录态迁移",
        url="https://git/pr/11",
    )
    await sync_to_async(MergeRequest.objects.create)(
        repository=repo,
        platform="github",
        external_id="12",
        title="chore: 无关改动",
        url="https://git/pr/12",
    )

    knowledge_id = uuid.uuid4()
    hits = [
        _hit(score=0.9, entity_kind="tech_plan", title="登录方案", entity_id=knowledge_id),
        _hit(
            score=0.8,
            entity_kind="document",
            title="外部 PRD",
            artifact={
                "artifact_id": str(other_artifact.id),
                "url": "https://doc/prd",
                "type_name": "PRD",
                "project_name": "OtherP",
                "project_id": str(other_project.id),
            },
        ),
        # 本项目自己的工件 → 排除
        _hit(
            score=0.7,
            entity_kind="document",
            title="本项目 PRD",
            artifact={
                "artifact_id": str(own_artifact.id),
                "url": "https://doc/own",
                "type_name": "PRD",
                "project_name": "P",
                "project_id": str(project.id),
            },
        ),
        # 项目实体自身 → 排除
        _hit(score=0.6, entity_kind="project", title="P", source_id=str(project.id)),
    ]

    summary, propose_mock = await _agenerate(project, member, hits)

    assert propose_mock.await_count == 1
    kwargs = propose_mock.await_args.kwargs
    assert kwargs["project"] is project
    assert [f["name"] for f in kwargs["features_flat"]] == ["登录", "登出"]

    assert summary["knowledge_candidates"] == 1
    assert summary["artifact_candidates"] == 1
    assert summary["mr_candidates"] == 1
    assert summary["created"] == 3

    links = await sync_to_async(lambda: list(ProjectContextLink.objects.filter(project=project)))()
    by_kind = {link.target_kind: link for link in links}
    assert set(by_kind) == {
        ContextLinkKind.KNOWLEDGE,
        ContextLinkKind.ARTIFACT,
        ContextLinkKind.MERGE_REQUEST,
    }
    assert all(link.status == ContextLinkStatus.PROPOSED for link in links)
    assert all(link.origin == ContextLinkOrigin.AI for link in links)
    assert by_kind[ContextLinkKind.KNOWLEDGE].target_id == knowledge_id
    assert by_kind[ContextLinkKind.ARTIFACT].target_id == other_artifact.id
    assert "登录" in by_kind[ContextLinkKind.MERGE_REQUEST].reason


async def test_generate_never_resurrects_rejected_or_overwrites_manual(project, member) -> None:
    knowledge_id = uuid.uuid4()
    manual_id = uuid.uuid4()
    await sync_to_async(ProjectContextLink.objects.create)(
        project=project,
        target_kind=ContextLinkKind.KNOWLEDGE,
        target_id=knowledge_id,
        title="旧标题",
        reason="人工拒绝过",
        origin=ContextLinkOrigin.AI,
        status=ContextLinkStatus.REJECTED,
    )
    await sync_to_async(ProjectContextLink.objects.create)(
        project=project,
        target_kind=ContextLinkKind.KNOWLEDGE,
        target_id=manual_id,
        title="人工添加",
        origin=ContextLinkOrigin.MANUAL,
        status=ContextLinkStatus.ACCEPTED,
    )

    hits = [
        _hit(score=0.9, entity_kind="tech_plan", title="新标题", entity_id=knowledge_id),
        _hit(score=0.8, entity_kind="tech_plan", title="AI 改写", entity_id=manual_id),
    ]
    summary, _ = await _agenerate(project, member, hits)

    assert summary["created"] == 0
    assert summary["skipped"] == 2
    rejected = await ProjectContextLink.objects.aget(project=project, target_id=knowledge_id)
    assert rejected.status == ContextLinkStatus.REJECTED
    assert rejected.title == "旧标题"
    manual = await ProjectContextLink.objects.aget(project=project, target_id=manual_id)
    assert manual.status == ContextLinkStatus.ACCEPTED
    assert manual.origin == ContextLinkOrigin.MANUAL
    assert manual.title == "人工添加"


async def test_generate_refreshes_ai_proposed(project, member) -> None:
    knowledge_id = uuid.uuid4()
    await sync_to_async(ProjectContextLink.objects.create)(
        project=project,
        target_kind=ContextLinkKind.KNOWLEDGE,
        target_id=knowledge_id,
        title="旧标题",
        score=0.1,
        origin=ContextLinkOrigin.AI,
        status=ContextLinkStatus.PROPOSED,
    )
    hits = [_hit(score=0.95, entity_kind="tech_plan", title="新标题", entity_id=knowledge_id)]
    summary, _ = await _agenerate(project, member, hits)

    assert summary["refreshed"] == 1
    link = await ProjectContextLink.objects.aget(project=project, target_id=knowledge_id)
    assert link.title == "新标题"
    assert link.score == pytest.approx(0.95)
    assert link.status == ContextLinkStatus.PROPOSED


# ===========================================================================
# REST API — 列表 / 手动添加 / 裁决 / 删除 / 权限
# ===========================================================================


def test_outsider_cannot_access(project, outsider):
    resp = _client(outsider).get(f"/api/projects/{project.id}/context-links/")
    assert resp.status_code == 403


def test_list_returns_links_and_repo_candidates(project, member, repo):
    ProjectContextLink.objects.create(
        project=project,
        target_kind=ContextLinkKind.EXTERNAL,
        title="设计稿",
        url="https://figma/x",
        origin=ContextLinkOrigin.MANUAL,
        status=ContextLinkStatus.ACCEPTED,
    )
    RepoAssociation.objects.create(
        project=project,
        repository=repo,
        status=RepoAssociationStatus.PROPOSED,
        score=0.8,
        routed_reason="命中鉴权能力",
    )
    resp = _client(member).get(f"/api/projects/{project.id}/context-links/")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["links"]) == 1
    assert body["links"][0]["target_kind"] == "external"
    assert len(body["repos"]) == 1
    assert body["repos"][0]["repository_id"] == str(repo.id)
    assert body["repos"][0]["status"] == "proposed"


def test_manual_add_external_and_mr(project, member, repo):
    client = _client(member)
    resp = client.post(
        f"/api/projects/{project.id}/context-links/",
        {"target_kind": "external", "title": "竞品调研", "url": "https://doc/rd"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert resp.json()["origin"] == "manual"
    assert resp.json()["status"] == "accepted"

    mr = MergeRequest.objects.create(
        repository=repo,
        platform="github",
        external_id="42",
        title="feat: 支付回调",
        url="https://git/pr/42",
    )
    resp = client.post(
        f"/api/projects/{project.id}/context-links/",
        {"target_kind": "merge_request", "target_id": str(mr.id)},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert resp.json()["title"] == "feat: 支付回调"

    # external 缺 url → 400；目标不存在 → 400
    resp = client.post(
        f"/api/projects/{project.id}/context-links/",
        {"target_kind": "external", "title": "无链接"},
        format="json",
    )
    assert resp.status_code == 400
    resp = client.post(
        f"/api/projects/{project.id}/context-links/",
        {"target_kind": "merge_request", "target_id": str(uuid.uuid4())},
        format="json",
    )
    assert resp.status_code == 400


def test_accept_reject_and_delete(project, member):
    link = ProjectContextLink.objects.create(
        project=project,
        target_kind=ContextLinkKind.KNOWLEDGE,
        target_id=uuid.uuid4(),
        title="候选",
        origin=ContextLinkOrigin.AI,
        status=ContextLinkStatus.PROPOSED,
    )
    client = _client(member)
    resp = client.post(f"/api/projects/{project.id}/context-links/{link.id}/accept/")
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "accepted"

    resp = client.post(f"/api/projects/{project.id}/context-links/{link.id}/reject/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    resp = client.delete(f"/api/projects/{project.id}/context-links/{link.id}/")
    assert resp.status_code == 204
    assert not ProjectContextLink.objects.filter(pk=link.id).exists()

    resp = client.post(f"/api/projects/{project.id}/context-links/{uuid.uuid4()}/accept/")
    assert resp.status_code == 404


def test_repo_decision_accept_and_reject(project, member, repo, space):
    repo2 = Repository.objects.create(name="repoB", git_url="https://git/repoB.git")
    space.repositories.add(repo2)
    RepoAssociation.objects.create(
        project=project, repository=repo, status=RepoAssociationStatus.PROPOSED
    )
    RepoAssociation.objects.create(
        project=project, repository=repo2, status=RepoAssociationStatus.PROPOSED
    )
    client = _client(member)
    resp = client.post(
        f"/api/projects/{project.id}/context-links/repo-decision/",
        {"repository_id": str(repo.id), "action": "accept"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    assert (
        RepoAssociation.objects.get(project=project, repository=repo).status
        == RepoAssociationStatus.CONFIRMED
    )

    resp = client.post(
        f"/api/projects/{project.id}/context-links/repo-decision/",
        {"repository_id": str(repo2.id), "action": "reject"},
        format="json",
    )
    assert resp.status_code == 200
    assert (
        RepoAssociation.objects.get(project=project, repository=repo2).status
        == RepoAssociationStatus.REJECTED
    )

    # 已流转候选重复 reject → 404（无可裁决）
    resp = client.post(
        f"/api/projects/{project.id}/context-links/repo-decision/",
        {"repository_id": str(repo2.id), "action": "reject"},
        format="json",
    )
    assert resp.status_code == 404
