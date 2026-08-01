"""蓝图 → 交付知识图谱 normalizer 测试（Phase 116-04 Task 2，VIEW-04 / SC-4）。

守十一件事（每条都对准一个「断言全绿而功能为零」的失败形态）：

1. ⭐ citation 目标实体不存在 ⇒ **不产边** + 一条记了 ``source_type`` 的 ``sampling`` 事件
   （⛔ 不接受静默 warning —— ``apply_edge_specs:435`` 那个 except 与「并发已建」共用，
   日志里分不出「边丢了」和「本来就有」）。
2. ⭐ 同目标两条 citation 经**完整 ingest** ⇒ 活跃边**恰好 1 条**且 ``citation_ids`` 两项
   （朴素「一条 citation 一条边」从第二条起撞 ``uniq_kedge_active`` 被吞成 warning）。
3. ⭐ ``RELATES_TO`` 出边**恰好 1 条**（``exclusive`` 作用域是 ``(source, relation)``，
   多条会互相 ``invalidate_edge`` 且走**正常路径** —— 完全静默）。
3b. ⭐ **项目图谱节点不预建**时仍能建出该边 —— ``ensure_project_node`` 语义的可证伪形态。
    把项目边改写成「查一下、查不到就丢弃」⇒ 本条转红。
4. ⭐ ``REFERENCES`` 边 metadata ⛔ **不含** ``first_seen_version_no``（重摄取会整体覆盖，
   该字段每次被刷成当前版本号 ⇒ 字段名与语义对不上）。
5. ⭐ ``space`` 反查不到 ⇒ **返回空列表** + warning（⛔ 不产双向不可见的孤儿节点）。
6. v0 content（无 ``schema_version``）不入图。
7. ⭐ 九种 ``source_type`` 换算各一条（含「``url`` 不成边」与「还原不出即丢弃」）。
8. ⭐ v1 骨架经 ``ArtifactService.create`` 也入图（配 v0 content 零调用的反向对照 ——
   它证明门控判据没写反）。
9. ⭐ ``add_version`` 内容无变化（hash 相等、版本没翻）⇒ **不重复投递**。
10. 实体身份 = ``generate_entity_id("tech_plan","blueprint",artifact_id)``、
    ``kind == EntityKind.TECH_PLAN``，且 ⛔ 未新建 ``EntityKind``。
"""

from __future__ import annotations

import hashlib
import uuid
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone
from structlog.testing import capture_logs

from delivery.models import Artifact, ArtifactVersion
from initiatives.models import Project as InitiativeProject
from initiatives.services.knowledge_graph import project_node_id, repository_node_id
from knowledge.ingestion import IngestionRequest, ingest_events
from knowledge.models import (
    EdgeRelation,
    EntityKind,
    EntityOrigin,
    KnowledgeEdge,
    KnowledgeEntity,
    generate_entity_id,
)
from knowledge.sources.blueprint import normalize
from services.process_runtime.blueprint_schema import BLUEPRINT_SCHEMA_VERSION

pytestmark = pytest.mark.django_db(transaction=True)

_ARTIFACT_TYPE = "technical_plan"


# ---- 向量侧 seam（照 test_ingestion.py 的纪律：执行体测试不触 Qdrant）----


@pytest.fixture
def mock_ensure(monkeypatch) -> AsyncMock:
    ensure = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.ensure_delivery_knowledge_collection", ensure)
    return ensure


@pytest.fixture
def mock_upsert(monkeypatch) -> list[list[str]]:
    from services.qdrant_service import QdrantService

    calls: list[list[str]] = []

    def _fake(cls, name, pts):
        calls.append([p["id"] for p in pts])
        return True

    monkeypatch.setattr(QdrantService, "upsert_vectors_by_name", classmethod(_fake))
    return calls


# ---- 夹具工厂 ----


def _make_project(space) -> InitiativeProject:
    return InitiativeProject.objects.create(space=space, name="洋葱练习", feishu_project_key="")


def _content(project_id, *, citations=None, schema_version=BLUEPRINT_SCHEMA_VERSION) -> dict:
    content: dict = {
        "meta": {"title": "登录改造蓝图", "project_id": str(project_id)},
        "requirement_spec": {
            "goal": [{"block_id": "b1", "type": "paragraph", "text": "把登录改造好"}],
            "feature_points": [],
        },
        "citations": citations or {},
    }
    if schema_version is not None:
        content["schema_version"] = schema_version
    return content


def _make_artifact(content: dict) -> Artifact:
    artifact = Artifact.objects.create(artifact_type=_ARTIFACT_TYPE, title="登录改造蓝图")
    version = ArtifactVersion.objects.create(
        artifact=artifact,
        version_no=1,
        content=content,
        content_hash=hashlib.sha256(str(content).encode()).hexdigest(),
    )
    artifact.current_version = version
    artifact.save(update_fields=["current_version", "updated_at"])
    return artifact


def _make_entity(space, *, kind, source_kind, source_id) -> KnowledgeEntity:
    return KnowledgeEntity.objects.create(
        id=generate_entity_id(kind, source_kind, source_id),
        kind=kind,
        origin=EntityOrigin.ARTIFACT,
        source_kind=source_kind,
        source_id=source_id,
        title="被引实体",
        space_id=space.id,
        event_time=timezone.now(),
    )


def _request(artifact) -> IngestionRequest:
    return IngestionRequest("blueprint", str(artifact.id), "blueprint_version_created")


def _reference_specs(event) -> list:
    return [e for e in event.edges if e.relation == EdgeRelation.REFERENCES]


# ---- 1. 目标不存在 ⇒ 不产边 + 记了 source_type 的 sampling 事件 ----


async def test_missing_target_drops_edge_and_counts_by_source_type(project) -> None:
    """⭐ 目标实体不存在的 spec 必须在 apply_edge_specs 之前就被过滤并**计数**。"""
    iproject = await sync_to_async(_make_project)(project)
    citations = {
        "c1": {
            "citation_id": "c1",
            "source_type": "knowledge_entity",
            "source_id": str(uuid.uuid4()),
        }
    }
    artifact = await sync_to_async(_make_artifact)(_content(iproject.id, citations=citations))

    with capture_logs() as cap:
        events = await normalize(_request(artifact))

    assert _reference_specs(events[0]) == []
    resolved = [e for e in cap if e["event"] == "blueprint_knowledge_edges_resolved"]
    assert len(resolved) == 1
    assert resolved[0]["dropped_by_source_type"] == {"knowledge_entity": 1}
    assert resolved[0]["dropped_count"] == 1
    assert resolved[0]["kept_count"] == 0
    assert resolved[0]["category"] == "sampling"
    assert resolved[0]["component"] == "knowledge"


# ---- 2. 同目标多条 citation ⇒ 活跃边恰好 1 条（经完整 ingest）----


async def test_two_citations_same_target_produce_one_edge(
    project, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert
) -> None:
    """⭐ 朴素写法会在第二条撞 uniq_kedge_active 被吞成 warning ⇒ 这条是唯一能逮住它的形态。"""
    iproject = await sync_to_async(_make_project)(project)
    target = await sync_to_async(_make_entity)(
        project, kind=EntityKind.DOCUMENT, source_kind="feishu_document", source_id="tok-1"
    )
    citations = {
        "c1": {"citation_id": "c1", "source_type": "feishu_doc", "source_id": "tok-1"},
        "c2": {"citation_id": "c2", "source_type": "feishu_doc", "source_id": "tok-1"},
    }
    artifact = await sync_to_async(_make_artifact)(_content(iproject.id, citations=citations))

    events = await normalize(_request(artifact))
    await ingest_events(events, trigger="blueprint_version_created")

    entity_id = generate_entity_id(EntityKind.TECH_PLAN, "blueprint", str(artifact.id))
    edges = [
        edge
        async for edge in KnowledgeEdge.objects.filter(
            source_entity_id=entity_id,
            target_entity_id=target.id,
            relation=EdgeRelation.REFERENCES,
            invalid_at__isnull=True,
        )
    ]
    assert len(edges) == 1
    assert sorted(edges[0].metadata["citation_ids"]) == ["c1", "c2"]
    assert edges[0].metadata["source_types"] == ["feishu_doc"]


# ---- 3 / 3b. RELATES_TO 恰好 1 条 + 项目节点不预建也能建出边 ----


async def test_relates_to_edge_is_exactly_one(project) -> None:
    """⭐ exclusive 作用域是 (source, relation)：多条 RELATES_TO 会互相静默清洗。"""
    iproject = await sync_to_async(_make_project)(project)
    artifact = await sync_to_async(_make_artifact)(_content(iproject.id))

    events = await normalize(_request(artifact))

    relates = [e for e in events[0].edges if e.relation == EdgeRelation.RELATES_TO]
    assert len(relates) == 1
    assert relates[0].exclusive is True
    assert relates[0].target_entity_id == project_node_id(iproject.id)


async def test_project_node_absent_is_created_by_ensure(
    project, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert
) -> None:
    """⭐ B2 可证伪形态：夹具**不预建**项目节点，跑完整摄取后边仍必须在。

    把项目边改写成「查一下项目节点、查不到就丢弃」⇒ 本条转红（那正是生产里边被存在性
    过滤静默吃掉、而任何预建节点的夹具都会掩盖的失败形态）。
    """
    iproject = await sync_to_async(_make_project)(project)
    node_id = project_node_id(iproject.id)
    assert await KnowledgeEntity.objects.filter(id=node_id).aexists() is False

    with capture_logs() as cap:
        events = await normalize(
            _request(await sync_to_async(_make_artifact)(_content(iproject.id)))
        )
    await ingest_events(events, trigger="blueprint_version_created")

    assert await KnowledgeEntity.objects.filter(id=node_id).aexists() is True
    active = [
        edge
        async for edge in KnowledgeEdge.objects.filter(
            target_entity_id=node_id,
            relation=EdgeRelation.RELATES_TO,
            invalid_at__isnull=True,
        )
    ]
    assert len(active) == 1
    resolved = [e for e in cap if e["event"] == "blueprint_knowledge_edges_resolved"]
    assert resolved[0]["dropped_by_source_type"] == {}


# ---- 4. ⛔ 无 first_seen_version_no ----


async def test_reference_edge_metadata_has_no_first_seen_version_no(project) -> None:
    iproject = await sync_to_async(_make_project)(project)
    await sync_to_async(_make_entity)(
        project, kind=EntityKind.DOCUMENT, source_kind="feishu_document", source_id="tok-2"
    )
    citations = {"c1": {"citation_id": "c1", "source_type": "feishu_doc", "source_id": "tok-2"}}
    artifact = await sync_to_async(_make_artifact)(_content(iproject.id, citations=citations))

    events = await normalize(_request(artifact))

    specs = _reference_specs(events[0])
    assert len(specs) == 1
    assert "first_seen_version_no" not in specs[0].metadata


# ---- 5 / 6. 降级：space 反查不到 / v0 content ----


async def test_space_unresolved_returns_empty_with_warning(project) -> None:
    """⭐ 反查不到 project/space ⇒ 整体不入图（⛔ 不造双向不可见的孤儿节点）。"""
    artifact = await sync_to_async(_make_artifact)(_content(uuid.uuid4()))

    with capture_logs() as cap:
        events = await normalize(_request(artifact))

    assert events == []
    warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
    assert "knowledge_normalize_blueprint_space_unresolved" in warnings


async def test_v0_content_is_not_ingested(project) -> None:
    iproject = await sync_to_async(_make_project)(project)
    artifact = await sync_to_async(_make_artifact)(_content(iproject.id, schema_version=None))

    with capture_logs() as cap:
        events = await normalize(_request(artifact))

    assert events == []
    warnings = [e["event"] for e in cap if e.get("log_level") == "warning"]
    assert "blueprint_knowledge_normalize_schema_mismatch" in warnings


async def test_missing_artifact_returns_empty_with_warning() -> None:
    with capture_logs() as cap:
        events = await normalize(IngestionRequest("blueprint", str(uuid.uuid4()), "t"))

    assert events == []
    assert "knowledge_normalize_source_missing" in [e["event"] for e in cap]


# ---- 7. 九种 source_type 换算各一条 ----


async def _single_target(project, iproject, citation: dict):
    """跑一次 normalize，返回 (REFERENCES spec 列表, 丢弃统计)。"""
    artifact = await sync_to_async(_make_artifact)(
        _content(iproject.id, citations={citation["citation_id"]: citation})
    )
    with capture_logs() as cap:
        events = await normalize(_request(artifact))
    resolved = [e for e in cap if e["event"] == "blueprint_knowledge_edges_resolved"][0]
    return _reference_specs(events[0]), resolved


async def test_source_type_knowledge_entity_resolves_directly(project) -> None:
    iproject = await sync_to_async(_make_project)(project)
    target = await sync_to_async(_make_entity)(
        project, kind=EntityKind.WORK_ITEM, source_kind="feishu_work_item", source_id="k:t:1"
    )
    specs, _ = await _single_target(
        project,
        iproject,
        {"citation_id": "c1", "source_type": "knowledge_entity", "source_id": str(target.id)},
    )
    assert [s.target_entity_id for s in specs] == [target.id]


async def test_source_type_work_item_restores_triple(project) -> None:
    iproject = await sync_to_async(_make_project)(project)
    target = await sync_to_async(_make_entity)(
        project, kind=EntityKind.WORK_ITEM, source_kind="feishu_work_item", source_id="pk:story:7"
    )
    specs, _ = await _single_target(
        project,
        iproject,
        {"citation_id": "c1", "source_type": "work_item", "source_id": "pk:story:7"},
    )
    assert [s.target_entity_id for s in specs] == [
        generate_entity_id(EntityKind.WORK_ITEM, "feishu_work_item", "pk:story:7")
    ]
    assert specs[0].target_entity_id == target.id


async def test_source_type_work_item_unrestorable_is_dropped(project) -> None:
    """⭐ 三元组还原不出即丢弃并计数（半可信 citation 的畸形输入防御）。"""
    iproject = await sync_to_async(_make_project)(project)
    specs, resolved = await _single_target(
        project,
        iproject,
        {"citation_id": "c1", "source_type": "work_item", "source_id": "只有一个片段"},
    )
    assert specs == []
    assert resolved["dropped_by_source_type"] == {"work_item": 1}


async def test_source_type_feishu_doc_resolves_by_token(project) -> None:
    iproject = await sync_to_async(_make_project)(project)
    await sync_to_async(_make_entity)(
        project, kind=EntityKind.DOCUMENT, source_kind="feishu_document", source_id="doccnXX"
    )
    specs, _ = await _single_target(
        project,
        iproject,
        {"citation_id": "c1", "source_type": "feishu_doc", "source_id": "doccnXX"},
    )
    assert [s.target_entity_id for s in specs] == [
        generate_entity_id(EntityKind.DOCUMENT, "feishu_document", "doccnXX")
    ]


async def test_source_type_blueprint_resolves_to_same_natural_key(project) -> None:
    iproject = await sync_to_async(_make_project)(project)
    other = await sync_to_async(_make_artifact)(_content(iproject.id))
    await sync_to_async(_make_entity)(
        project, kind=EntityKind.TECH_PLAN, source_kind="blueprint", source_id=str(other.id)
    )
    specs, _ = await _single_target(
        project,
        iproject,
        {"citation_id": "c1", "source_type": "blueprint", "source_id": str(other.id)},
    )
    assert [s.target_entity_id for s in specs] == [
        generate_entity_id(EntityKind.TECH_PLAN, "blueprint", str(other.id))
    ]


async def test_source_type_artifact_version_resolves_via_artifact(project) -> None:
    """``artifact_version`` 经一次 ArtifactVersion → artifact_id 查询后换算成蓝图实体 id。"""
    iproject = await sync_to_async(_make_project)(project)
    other = await sync_to_async(_make_artifact)(_content(iproject.id))
    other_version_id = (
        await ArtifactVersion.objects.filter(artifact_id=other.id)
        .values_list("id", flat=True)
        .afirst()
    )
    await sync_to_async(_make_entity)(
        project, kind=EntityKind.TECH_PLAN, source_kind="blueprint", source_id=str(other.id)
    )
    specs, _ = await _single_target(
        project,
        iproject,
        {
            "citation_id": "c1",
            "source_type": "artifact_version",
            "source_id": str(other_version_id),
        },
    )
    assert [s.target_entity_id for s in specs] == [
        generate_entity_id(EntityKind.TECH_PLAN, "blueprint", str(other.id))
    ]


async def _repo_case(project, iproject, source_type: str, repository):
    citation = {
        "citation_id": "c1",
        "source_type": source_type,
        "source_id": str(repository.id),
        "locator": {"repository_id": str(repository.id)},
    }
    return await _single_target(project, iproject, citation)


async def test_source_type_repo_file_falls_back_to_repository_node(project, repository) -> None:
    iproject = await sync_to_async(_make_project)(project)
    await sync_to_async(_make_entity)(
        project,
        kind=EntityKind.REPOSITORY,
        source_kind="repository",
        source_id=str(repository.id),
    )
    specs, _ = await _repo_case(project, iproject, "repo_file", repository)
    assert [s.target_entity_id for s in specs] == [repository_node_id(repository.id)]
    assert specs[0].metadata["source_types"] == ["repo_file"]


async def test_source_type_rag_chunk_falls_back_to_repository_node(project, repository) -> None:
    iproject = await sync_to_async(_make_project)(project)
    await sync_to_async(_make_entity)(
        project,
        kind=EntityKind.REPOSITORY,
        source_kind="repository",
        source_id=str(repository.id),
    )
    specs, _ = await _repo_case(project, iproject, "rag_chunk", repository)
    assert [s.target_entity_id for s in specs] == [repository_node_id(repository.id)]
    assert specs[0].metadata["source_types"] == ["rag_chunk"]


async def test_source_type_repo_charter_falls_back_to_repository_node(project, repository) -> None:
    """``repo_charter`` 的引用条目把 repo id 放在 ``source_id``（blueprint_route.py:791）。"""
    iproject = await sync_to_async(_make_project)(project)
    await sync_to_async(_make_entity)(
        project,
        kind=EntityKind.REPOSITORY,
        source_kind="repository",
        source_id=str(repository.id),
    )
    specs, resolved = await _single_target(
        project,
        iproject,
        {
            "citation_id": "c1",
            "source_type": "repo_charter",
            "source_id": str(repository.id),
            "locator": {"domain": "auth"},
        },
    )
    assert [s.target_entity_id for s in specs] == [repository_node_id(repository.id)]
    assert resolved["dropped_count"] == 0


async def test_source_type_url_never_becomes_an_edge(project) -> None:
    """⭐ ``url`` 在图里没有对应节点，建边只会撞 FK 被吞成 warning ⇒ 直接不成边。"""
    iproject = await sync_to_async(_make_project)(project)
    specs, resolved = await _single_target(
        project,
        iproject,
        {"citation_id": "c1", "source_type": "url", "source_id": "https://example.com/a"},
    )
    assert specs == []
    assert resolved["dropped_by_source_type"] == {"url": 1}


# ---- 8 / 9. 两处门控 ----


async def test_create_schedules_ingestion_for_blueprint_v1(project, monkeypatch) -> None:
    """⭐ P-10：intake 建的 v1 骨架走 create **不经 add_version**，必须也入图。"""
    from delivery.services import artifact_service as artifact_service_module

    iproject = await sync_to_async(_make_project)(project)
    scheduled = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", scheduled)

    await artifact_service_module.ArtifactService().create(
        _ARTIFACT_TYPE, _blueprint_v1_content(iproject.id), title="骨架"
    )

    assert scheduled.await_count == 1
    request = scheduled.await_args.args[0]
    assert request.source_kind == "blueprint"
    assert request.trigger == "blueprint_version_created"


async def test_create_does_not_schedule_for_v0_content(project, monkeypatch) -> None:
    """反向对照：v0 content ⇒ 零调用（证明门控判据没写反）。"""
    from delivery.services import artifact_service as artifact_service_module

    scheduled = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", scheduled)

    await artifact_service_module.ArtifactService().create(
        _ARTIFACT_TYPE,
        {"title": "旧链方案", "summary": "摘要", "execution_plan": []},
        title="v0",
    )

    assert scheduled.await_count == 0


async def test_add_version_without_content_change_schedules_once(project, monkeypatch) -> None:
    """⭐ hash 相等时 `_add_version_sync` 返回 current（版本没翻）⇒ 不重复投递。"""
    from delivery.services import artifact_service as artifact_service_module

    iproject = await sync_to_async(_make_project)(project)
    service = artifact_service_module.ArtifactService()
    content = _blueprint_v1_content(iproject.id)
    artifact = await service.create(_ARTIFACT_TYPE, content, title="骨架")

    scheduled = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", scheduled)
    changed = _blueprint_v1_content(iproject.id, title="改过的标题")
    await service.add_version(artifact, changed)
    await service.add_version(artifact, changed)

    assert scheduled.await_count == 1


# ---- 10. 实体身份 ----


async def test_entity_identity_uses_natural_key_and_tech_plan_kind(project) -> None:
    iproject = await sync_to_async(_make_project)(project)
    artifact = await sync_to_async(_make_artifact)(_content(iproject.id))

    events = await normalize(_request(artifact))

    event = events[0]
    assert event.kind == EntityKind.TECH_PLAN
    assert event.source_kind == "blueprint"
    assert event.source_id == str(artifact.id)
    assert generate_entity_id(event.kind, event.source_kind, event.source_id) == (
        generate_entity_id(EntityKind.TECH_PLAN, "blueprint", str(artifact.id))
    )
    assert event.space_id == str(iproject.space_id)


def test_entity_kind_members_unchanged() -> None:
    """⛔ 零新 EntityKind：蓝图沿用 tech_plan，由 source_kind 区分子类（Phase 100 惯例）。"""
    assert set(EntityKind.values) == {
        "work_item",
        "tech_plan",
        "code_change",
        "document",
        "project",
        "repository",
        "space",
        "learning_case",
    }


def _blueprint_v1_content(project_id, *, title: str = "骨架蓝图") -> dict:
    """过 ``validate_content`` 的最小 blueprint/v1（复用 intake 的骨架工厂，⛔ 不自造一份）。"""
    from services.process_runtime.blueprint_intake import build_skeleton

    return build_skeleton(title=title, project_id=str(project_id), goal_text="需求原文")


# ---- 11. ⭐ 入图实体的 title 也过脱敏（116-REVIEW MN-01）----
#
# `meta.title` 的缺省来源是**需求原文的首行**（`blueprint_intake` 的 `_first_line(goal_text)`）
# ⇒ 半可信文本。回退前全链只有它没过脱敏：`content` 过了、`payload` 只有标量、日志只记 id
# 与计数，唯独 title 直通进 `KnowledgeEntity.title`，并显示在知识库搜索结果与「关联知识」
# 列表里。对照组：同一份 title 在 MCP 侧本就过了脱敏（口径不一致 ⇒ 不是有意豁免）。


_LEAKY_TITLE = "排障：调 sk-ant-api03-LEAKYTOKENVALUE 老是 401"


async def test_entity_title_is_redacted_like_the_content(project) -> None:
    """⭐ 需求首行里的凭证不得原样进 ``KnowledgeEntity.title``。"""
    iproject = await sync_to_async(_make_project)(project)
    content = _content(iproject.id)
    content["meta"]["title"] = _LEAKY_TITLE
    artifact = await sync_to_async(_make_artifact)(content)

    events = await normalize(_request(artifact))

    title = events[0].title
    assert "sk-ant-api03-LEAKYTOKENVALUE" not in title
    assert "***REDACTED***" in title
    # 非凭证部分保持可读（⛔ 不是把整个标题抹掉）
    assert "排障" in title


async def test_clean_title_is_untouched_by_the_redaction(project) -> None:
    """非恒真对照：不含凭证的标题**逐字不变**（⛔ 脱敏不是无差别改写）。"""
    iproject = await sync_to_async(_make_project)(project)
    artifact = await sync_to_async(_make_artifact)(_content(iproject.id))

    events = await normalize(_request(artifact))

    assert events[0].title == "登录改造蓝图"


async def test_title_is_still_capped_at_500_chars(project) -> None:
    """脱敏后仍按 500 截断（⛔ 截断不能被脱敏顺序调整挤掉）。"""
    iproject = await sync_to_async(_make_project)(project)
    content = _content(iproject.id)
    content["meta"]["title"] = "长" * 900
    artifact = await sync_to_async(_make_artifact)(content)

    events = await normalize(_request(artifact))

    assert len(events[0].title) == 500


# ---- 12. ⭐ 入图后台任务必须携带发起用户（116-REVIEW MN-02，CTX-02）----
#
# `aschedule_ingestion` 的 keyword-only 形参 `initiated_by_user_id` 专门用来让 worker
# `bind_task_context` 重绑发起用户。仓内已有五个调用点在传它，蓝图这两处回退前都没传
# ⇒ 「谁触发了这次入图」在图谱侧不可回答（`.cursor/rules/observability-logging.mdc`
# 「后台任务**必须**显式携带 `initiated_by_user_id`」）。两处**都拿得到**触发用户。


async def test_create_carries_the_triggering_user_into_the_background_task(
    project, monkeypatch
) -> None:
    """⭐ ``create`` 的形参里就有 ``created_by_user_id`` ⇒ 必须透传给后台任务。"""
    from delivery.services import artifact_service as artifact_service_module

    iproject = await sync_to_async(_make_project)(project)
    scheduled = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", scheduled)

    await artifact_service_module.ArtifactService().create(
        _ARTIFACT_TYPE,
        _blueprint_v1_content(iproject.id),
        title="骨架",
        created_by_user_id="u-42",
    )

    assert scheduled.await_args.kwargs["initiated_by_user_id"] == "u-42"


async def test_add_version_resolves_the_initiator_from_the_session(project, monkeypatch) -> None:
    """⭐ ``add_version`` 拿不到 ``created_by_user_id``，经 ``produced_by_session_id`` 反查。"""
    from delivery.models import ConvergenceSession, ConvergenceSessionEntrypoint
    from delivery.services import artifact_service as artifact_service_module

    iproject = await sync_to_async(_make_project)(project)
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        initiated_by_user_id="u-77",
    )
    service = artifact_service_module.ArtifactService()
    artifact = await service.create(_ARTIFACT_TYPE, _blueprint_v1_content(iproject.id))

    scheduled = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", scheduled)
    await service.add_version(
        artifact,
        _blueprint_v1_content(iproject.id, title="改过的标题"),
        produced_by_session_id=str(session.id),
    )

    assert scheduled.await_args.kwargs["initiated_by_user_id"] == "u-77"


async def test_missing_initiator_is_recorded_as_system_not_blank(project, monkeypatch) -> None:
    """无触发用户记 ``"system"``（⛔ 不留空串——那让「系统行为」与「漏传」不可区分）。"""
    from delivery.services import artifact_service as artifact_service_module

    iproject = await sync_to_async(_make_project)(project)
    scheduled = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", scheduled)

    await artifact_service_module.ArtifactService().create(
        _ARTIFACT_TYPE, _blueprint_v1_content(iproject.id)
    )

    assert scheduled.await_args.kwargs["initiated_by_user_id"] == "system"


async def test_unresolvable_session_does_not_break_the_ingestion(project, monkeypatch) -> None:
    """⭐ 归因 best-effort：会话 id 查不到（甚至非法）⇒ 记 system，⛔ 绝不废掉这次入图。"""
    from delivery.services import artifact_service as artifact_service_module

    iproject = await sync_to_async(_make_project)(project)
    service = artifact_service_module.ArtifactService()
    artifact = await service.create(_ARTIFACT_TYPE, _blueprint_v1_content(iproject.id))

    scheduled = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", scheduled)
    await service.add_version(
        artifact,
        _blueprint_v1_content(iproject.id, title="改过的标题"),
        produced_by_session_id="not-a-uuid-at-all",
    )

    assert scheduled.await_count == 1, "归因失败绝不能吃掉一次入图"
    assert scheduled.await_args.kwargs["initiated_by_user_id"] == "system"
