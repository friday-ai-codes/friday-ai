"""工件正文 RepoRouterV2 路由 → RELATES_TO 边测试（Phase 98-01 Task 2，KDEP-07）。

- ragable markdown 工件摄取 → 对每个 mock 命中仓库落 artifact→repo RELATES_TO 边，
  metadata 含 source/artifact_id/node_paths/keywords/score。
- 重复摄取同工件不新增重复边且 metadata 覆盖最新（幂等 upsert）。
- 非 ragable / 空正文 / space 无仓库 → 不产生 RELATES_TO 边（仅 REFERENCES→project）。
- RepoRouterV2.route 抛异常 → ingest 不抛错，实体与 project 边照常产出（fail-soft）。

RepoRouterV2.route 全 mock（避开 Qdrant/LLM），Qdrant/embedding 全 mock。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from codegraph.services.repo_router_v2 import RepoRouteCandidateV2, RepoRouteResultV2
from initiatives.models import Artifact, ArtifactType, Project
from initiatives.services import ArtifactService
from initiatives.services.knowledge_graph import project_node_id, repository_node_id
from knowledge.ingestion import IngestionRequest, ingest
from knowledge.models import (
    EdgeRelation,
    EntityKind,
    KnowledgeEdge,
    generate_entity_id,
)
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def mock_ensure(monkeypatch) -> AsyncMock:
    ensure = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.ensure_delivery_knowledge_collection", ensure)
    return ensure


@pytest.fixture
def mock_upsert(monkeypatch) -> list:
    from services.qdrant_service import QdrantService

    calls: list = []
    monkeypatch.setattr(
        QdrantService,
        "upsert_vectors_by_name",
        classmethod(lambda cls, name, pts: calls.append(pts) or True),
    )
    return calls


@sync_to_async
def _setup(carrier="markdown", ragable=True, key="rt", *, with_repo=True):
    space = Space.objects.create(name="S", feishu_project_key=f"rt-{key}")
    project = Project.objects.create(space=space, name="P", feishu_project_key="")
    artifact_type = ArtifactType.objects.create(
        key=key, name=key, carrier=carrier, ragable=ragable
    )
    repository = None
    if with_repo:
        repository = Repository.objects.create(name="repo-a", git_url="https://git/repo-a.git")
        space.repositories.add(repository)
    return space, project, artifact_type, repository


@sync_to_async
def _setup_two_repos(key="conv"):
    space = Space.objects.create(name="S", feishu_project_key=f"rt-{key}")
    project = Project.objects.create(space=space, name="P", feishu_project_key="")
    artifact_type = ArtifactType.objects.create(
        key=key, name=key, carrier="markdown", ragable=True
    )
    repo_a = Repository.objects.create(name="repo-a", git_url="https://git/repo-a.git")
    repo_b = Repository.objects.create(name="repo-b", git_url="https://git/repo-b.git")
    space.repositories.add(repo_a, repo_b)
    return space, project, artifact_type, repo_a, repo_b


async def _create_artifact(project, t, **kw) -> Artifact:
    with patch(
        "initiatives.services.artifact_service.ArtifactService._maybe_schedule_ingestion",
        new=AsyncMock(),
    ):
        return await ArtifactService().create_artifact(project_id=project.id, type_id=t.id, **kw)


def _route_result(repo_id, *, score=0.87, node_paths=("backend/auth/login", "backend/auth")):
    return RepoRouteResultV2(
        candidates=[
            RepoRouteCandidateV2(
                repo_id=str(repo_id),
                repo_name="repo-a",
                score=score,
                confidence="high",
                reasoning="matched",
                matched_node_paths=list(node_paths),
            )
        ],
        router_version="v2",
        auto_selected=True,
    )


async def test_artifact_routes_to_repo_relates_to_edge(mock_ensure, mock_embedding, mock_upsert):
    _space, project, t, repository = await _setup(key="hit")
    artifact = await _create_artifact(project, t, title="登录方案", content_ref="# 登录\n实现细节")

    with patch(
        "codegraph.services.repo_router_v2.RepoRouterV2.route",
        new=AsyncMock(return_value=_route_result(repository.id)),
    ):
        n = await ingest(IngestionRequest("artifact", str(artifact.id), "test"))
    assert n == 1

    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    repo_node = repository_node_id(repository.id)
    edge = await KnowledgeEdge.objects.filter(
        source_entity_id=entity_id,
        target_entity_id=repo_node,
        relation=EdgeRelation.RELATES_TO,
        invalid_at__isnull=True,
    ).afirst()
    assert edge is not None
    assert edge.metadata["source"] == "artifact"
    assert edge.metadata["artifact_id"] == str(artifact.id)
    assert edge.metadata["node_paths"] == ["backend/auth/login", "backend/auth"]
    # keywords 由 node_paths 叶子段派生去重保序：login, auth
    assert edge.metadata["keywords"] == ["login", "auth"]
    assert edge.metadata["score"] == 0.87

    # REFERENCES→project 边仍在
    assert await KnowledgeEdge.objects.filter(
        source_entity_id=entity_id,
        target_entity_id=project_node_id(project.id),
        relation=EdgeRelation.REFERENCES,
        invalid_at__isnull=True,
    ).aexists()


async def test_reingest_idempotent_overwrites_metadata_no_dup(
    mock_ensure, mock_embedding, mock_upsert
):
    _space, project, t, repository = await _setup(key="idem")
    artifact = await _create_artifact(project, t, title="方案", content_ref="正文内容")
    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    repo_node = repository_node_id(repository.id)

    with patch(
        "codegraph.services.repo_router_v2.RepoRouterV2.route",
        new=AsyncMock(return_value=_route_result(repository.id, score=0.2)),
    ):
        await ingest(IngestionRequest("artifact", str(artifact.id), "test"))

    with patch(
        "codegraph.services.repo_router_v2.RepoRouterV2.route",
        new=AsyncMock(
            return_value=_route_result(repository.id, score=0.95, node_paths=("web/ui",))
        ),
    ):
        await ingest(IngestionRequest("artifact", str(artifact.id), "test"))

    edges = await sync_to_async(
        lambda: list(
            KnowledgeEdge.objects.filter(
                source_entity_id=entity_id,
                target_entity_id=repo_node,
                relation=EdgeRelation.RELATES_TO,
                invalid_at__isnull=True,
            )
        )
    )()
    assert len(edges) == 1
    assert edges[0].metadata["score"] == 0.95
    assert edges[0].metadata["keywords"] == ["ui"]


async def test_reingest_invalidates_stale_repo_edge(mock_ensure, mock_embedding, mock_upsert):
    """MED-02：重摄取命中仓库集合变化时，旧命中仓库的路由边被失效收敛。

    首轮命中 repo A → artifact→A 活跃边；次轮改命中 repo B（A 不再命中）→
    artifact→A 边被失效置位（非删除，历史仍存），artifact→B 活跃。收敛幂等：
    A 边不会因重复失效报错，B 边不重复。
    """
    _space, project, t, repo_a, repo_b = await _setup_two_repos()
    artifact = await _create_artifact(project, t, title="方案", content_ref="正文内容")
    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    node_a = repository_node_id(repo_a.id)
    node_b = repository_node_id(repo_b.id)

    with patch(
        "codegraph.services.repo_router_v2.RepoRouterV2.route",
        new=AsyncMock(return_value=_route_result(repo_a.id)),
    ):
        await ingest(IngestionRequest("artifact", str(artifact.id), "test"))

    assert await KnowledgeEdge.objects.filter(
        source_entity_id=entity_id,
        target_entity_id=node_a,
        relation=EdgeRelation.RELATES_TO,
        invalid_at__isnull=True,
    ).aexists()

    with patch(
        "codegraph.services.repo_router_v2.RepoRouterV2.route",
        new=AsyncMock(return_value=_route_result(repo_b.id)),
    ):
        await ingest(IngestionRequest("artifact", str(artifact.id), "test"))

    # A 边被失效收敛（不再活跃）
    assert not await KnowledgeEdge.objects.filter(
        source_entity_id=entity_id,
        target_entity_id=node_a,
        relation=EdgeRelation.RELATES_TO,
        invalid_at__isnull=True,
    ).aexists()
    # A 边失效置位而非删除：历史仍存
    assert await KnowledgeEdge.objects.filter(
        source_entity_id=entity_id,
        target_entity_id=node_a,
        relation=EdgeRelation.RELATES_TO,
        invalid_at__isnull=False,
    ).aexists()
    # B 边活跃且唯一
    active_b = await sync_to_async(
        lambda: list(
            KnowledgeEdge.objects.filter(
                source_entity_id=entity_id,
                target_entity_id=node_b,
                relation=EdgeRelation.RELATES_TO,
                invalid_at__isnull=True,
            )
        )
    )()
    assert len(active_b) == 1


async def test_reingest_same_matches_no_invalidation(mock_ensure, mock_embedding, mock_upsert):
    """MED-02 幂等：重摄取命中同一仓库集合 → 无失效、无重复（收敛 no-op）。"""
    _space, project, t, repo_a, _repo_b = await _setup_two_repos(key="convnoop")
    artifact = await _create_artifact(project, t, title="方案", content_ref="正文内容")
    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    node_a = repository_node_id(repo_a.id)

    for _ in range(2):
        with patch(
            "codegraph.services.repo_router_v2.RepoRouterV2.route",
            new=AsyncMock(return_value=_route_result(repo_a.id)),
        ):
            await ingest(IngestionRequest("artifact", str(artifact.id), "test"))

    all_a = await sync_to_async(
        lambda: list(
            KnowledgeEdge.objects.filter(
                source_entity_id=entity_id,
                target_entity_id=node_a,
                relation=EdgeRelation.RELATES_TO,
            )
        )
    )()
    # 单条 A 边、始终活跃（无失效历史、无重复）
    assert len(all_a) == 1
    assert all_a[0].invalid_at is None


async def test_non_ragable_no_relates_to_edge(mock_ensure, mock_embedding, mock_upsert):
    _space, project, t, _repo = await _setup(
        carrier="external_link", ragable=False, key="ui", with_repo=True
    )
    artifact = await _create_artifact(project, t, title="UI 稿", url="https://figma.com/file/x")

    route_mock = AsyncMock(return_value=_route_result("x"))
    with patch("codegraph.services.repo_router_v2.RepoRouterV2.route", new=route_mock):
        n = await ingest(IngestionRequest("artifact", str(artifact.id), "test"))
    assert n == 1
    route_mock.assert_not_awaited()

    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    assert not await KnowledgeEdge.objects.filter(
        source_entity_id=entity_id, relation=EdgeRelation.RELATES_TO
    ).aexists()


async def test_space_without_repos_skips_routing(mock_ensure, mock_embedding, mock_upsert):
    _space, project, t, _repo = await _setup(key="norepo", with_repo=False)
    artifact = await _create_artifact(project, t, title="无仓方案", content_ref="正文")

    route_mock = AsyncMock(return_value=_route_result("x"))
    with patch("codegraph.services.repo_router_v2.RepoRouterV2.route", new=route_mock):
        n = await ingest(IngestionRequest("artifact", str(artifact.id), "test"))
    assert n == 1
    route_mock.assert_not_awaited()

    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    assert not await KnowledgeEdge.objects.filter(
        source_entity_id=entity_id, relation=EdgeRelation.RELATES_TO
    ).aexists()


async def test_route_exception_fail_soft(mock_ensure, mock_embedding, mock_upsert):
    _space, project, t, repository = await _setup(key="err")
    artifact = await _create_artifact(project, t, title="方案", content_ref="正文")

    with patch(
        "codegraph.services.repo_router_v2.RepoRouterV2.route",
        new=AsyncMock(side_effect=RuntimeError("router boom")),
    ):
        n = await ingest(IngestionRequest("artifact", str(artifact.id), "test"))
    # fail-soft：ingest 不抛错，实体 + project 边照常产出
    assert n == 1
    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    assert await KnowledgeEdge.objects.filter(
        source_entity_id=entity_id,
        target_entity_id=project_node_id(project.id),
        relation=EdgeRelation.REFERENCES,
        invalid_at__isnull=True,
    ).aexists()
    assert not await KnowledgeEdge.objects.filter(
        source_entity_id=entity_id, relation=EdgeRelation.RELATES_TO
    ).aexists()
