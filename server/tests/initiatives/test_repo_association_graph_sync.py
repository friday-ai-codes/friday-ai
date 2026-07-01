"""verified RepoAssociation → 项目↔仓库派生边同步测试（Phase 98-02，KDEP-08）。

Task 1（ProjectKnowledgeGraphService）：
- link_repository(metadata=...) 首建带 metadata / 重复覆盖不重复建边；
- unlink_repository 失效活跃派生边且幂等；
- sync_relations_from_operational 对 verified RepoAssociation 派生带 source=repo_association 的边。

Task 2（RepoAssociationService 单一 hook）：
- record_verdict(fit) → 派生边 / record_verdict(mismatch) → 失效边；
- accept_mismatch → 派生边；reopen_candidates → 失效边；
- hook 内部异常被吞不打断状态流转（mock link_repository 抛错，record_verdict 仍返回 True）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from initiatives.models import (
    Project,
    RepoAssociation,
    RepoAssociationStatus,
    RepoVerifyTask,
    RepoVerifyTaskStatus,
)
from initiatives.services.knowledge_graph import (
    ProjectKnowledgeGraphService,
    project_node_id,
    repository_node_id,
)
from initiatives.services.repo_association_service import RepoAssociationService
from knowledge.graph_store import graph_store
from knowledge.models import EdgeRelation, KnowledgeEdge
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _make_project(key="rg") -> Project:
    space = Space.objects.create(name="S", feishu_project_key=f"rg-{key}")
    return Project.objects.create(space=space, name="P", feishu_project_key="")


@sync_to_async
def _make_repo(name="repo") -> Repository:
    return Repository.objects.create(name=name, git_url=f"https://x/{name}.git")


@sync_to_async
def _make_assoc(project, repository, status=RepoAssociationStatus.VERIFIED, **kw) -> RepoAssociation:
    defaults = {
        "status": status,
        "score": 0.75,
        "confidence": "high",
        "matched_node_paths": ["backend/auth"],
    }
    defaults.update(kw)
    return RepoAssociation.objects.create(project=project, repository=repository, **defaults)


@sync_to_async
def _active_repo_edge(project, repository):
    node = project_node_id(project.id)
    repo_node = repository_node_id(repository.id)
    return (
        KnowledgeEdge.objects.filter(
            source_entity_id=node,
            target_entity_id=repo_node,
            relation=EdgeRelation.RELATES_TO,
            invalid_at__isnull=True,
        ).first()
    )


# ============================================================================
# Task 1 — ProjectKnowledgeGraphService
# ============================================================================


async def test_link_repository_with_metadata_creates_edge():
    svc = ProjectKnowledgeGraphService()
    project = await _make_project("l1")
    repo = await _make_repo()

    created = await svc.link_repository(
        project=project, repository=repo, metadata={"source": "repo_association", "score": 0.5}
    )
    assert created is True
    edge = await _active_repo_edge(project, repo)
    assert edge is not None
    assert edge.metadata["source"] == "repo_association"
    assert edge.metadata["score"] == 0.5


async def test_link_repository_reapply_overwrites_metadata_no_dup():
    svc = ProjectKnowledgeGraphService()
    project = await _make_project("l2")
    repo = await _make_repo()

    await svc.link_repository(project=project, repository=repo, metadata={"score": 0.1})
    created2 = await svc.link_repository(project=project, repository=repo, metadata={"score": 0.9})
    assert created2 is False  # 已存在，仅 upsert

    node = project_node_id(project.id)
    repo_node = repository_node_id(repo.id)
    edges = await sync_to_async(
        lambda: list(
            KnowledgeEdge.objects.filter(
                source_entity_id=node,
                target_entity_id=repo_node,
                relation=EdgeRelation.RELATES_TO,
                invalid_at__isnull=True,
            )
        )
    )()
    assert len(edges) == 1
    assert edges[0].metadata["score"] == 0.9


async def test_unlink_repository_invalidates_edge_and_idempotent():
    svc = ProjectKnowledgeGraphService()
    project = await _make_project("u1")
    repo = await _make_repo()
    await svc.link_repository(project=project, repository=repo, metadata={"score": 0.5})

    unlinked = await svc.unlink_repository(project=project, repository=repo)
    assert unlinked is True
    assert await _active_repo_edge(project, repo) is None

    # 幂等 no-op：无活跃边再调返回 False
    unlinked2 = await svc.unlink_repository(project=project, repository=repo)
    assert unlinked2 is False


async def test_sync_relations_derives_verified_associations():
    svc = ProjectKnowledgeGraphService()
    project = await _make_project("s1")
    repo = await _make_repo("verified-repo")
    await _make_assoc(project, repo, status=RepoAssociationStatus.VERIFIED)
    # 非 verified 关联不应派生
    other_repo = await _make_repo("proposed-repo")
    await _make_assoc(project, other_repo, status=RepoAssociationStatus.PROPOSED)

    await svc.sync_relations_from_operational(project=project)

    edge = await _active_repo_edge(project, repo)
    assert edge is not None
    assert edge.metadata["source"] == "repo_association"
    assert edge.metadata["confidence"] == "high"
    assert edge.metadata["matched_node_paths"] == ["backend/auth"]
    # proposed 关联无派生边
    assert await _active_repo_edge(project, other_repo) is None


# ============================================================================
# Task 2 — RepoAssociationService 单一 hook
# ============================================================================


@sync_to_async
def _make_verify_task(assoc, repo) -> RepoVerifyTask:
    return RepoVerifyTask.objects.create(
        association=assoc, repository=repo, status=RepoVerifyTaskStatus.RUNNING
    )


async def test_record_verdict_fit_derives_edge():
    project = await _make_project("v1")
    repo = await _make_repo()
    assoc = await _make_assoc(project, repo, status=RepoAssociationStatus.VERIFYING)
    task = await _make_verify_task(assoc, repo)

    applied = await RepoAssociationService().record_verdict(task, {"fit": "fit"})
    assert applied is True
    assert await _active_repo_edge(project, repo) is not None


async def test_record_verdict_mismatch_invalidates_edge():
    svc_graph = ProjectKnowledgeGraphService()
    project = await _make_project("v2")
    repo = await _make_repo()
    assoc = await _make_assoc(project, repo, status=RepoAssociationStatus.VERIFYING)
    # 先有一条派生边
    await svc_graph.link_repository(project=project, repository=repo, metadata={"source": "repo_association"})
    task = await _make_verify_task(assoc, repo)

    applied = await RepoAssociationService().record_verdict(task, {"fit": "mismatch"})
    assert applied is True
    assert await _active_repo_edge(project, repo) is None


async def test_accept_mismatch_derives_edge():
    project = await _make_project("v3")
    repo = await _make_repo()
    assoc = await _make_assoc(project, repo, status=RepoAssociationStatus.REJECTED)

    applied = await RepoAssociationService().accept_mismatch(assoc)
    assert applied is True
    assert await _active_repo_edge(project, repo) is not None


async def test_reopen_candidates_invalidates_edge():
    svc_graph = ProjectKnowledgeGraphService()
    project = await _make_project("v4")
    repo = await _make_repo()
    assoc = await _make_assoc(project, repo, status=RepoAssociationStatus.VERIFIED)
    await svc_graph.link_repository(project=project, repository=repo, metadata={"source": "repo_association"})

    applied = await RepoAssociationService().reopen_candidates(assoc)
    assert applied is True
    assert await _active_repo_edge(project, repo) is None


async def test_graph_sync_failure_does_not_break_verdict():
    """hook 内 link_repository 抛错 → record_verdict 仍返回 True 且 verdict 落库（fail-soft）。"""
    project = await _make_project("v5")
    repo = await _make_repo()
    assoc = await _make_assoc(project, repo, status=RepoAssociationStatus.VERIFYING)
    task = await _make_verify_task(assoc, repo)

    with patch.object(
        ProjectKnowledgeGraphService,
        "link_repository",
        new=AsyncMock(side_effect=RuntimeError("graph boom")),
    ):
        applied = await RepoAssociationService().record_verdict(task, {"fit": "fit"})

    assert applied is True
    # verdict 落库、task 终态
    refreshed = await RepoVerifyTask.objects.aget(id=task.id)
    assert refreshed.status == RepoVerifyTaskStatus.DONE
    assert refreshed.verdict.get("fit") == "fit"
