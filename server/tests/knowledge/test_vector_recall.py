"""vector_recall 与 metadata_hydrate 测试（Phase 15-02）。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone
from qdrant_client import models as qmodels

from knowledge.metadata_hydrate import hydrate_entity_metadata
from knowledge.models import CodeChangeArchive, EntityKind
from knowledge.vector_recall import (
    VectorHit,
    _build_knowledge_must_filter,
    _dedupe_by_entity,
    _rrf_fuse,
    recall_similar_chunks,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _payload(entity_id: uuid.UUID, kind: str, version: int = 1) -> dict:
    return {
        "entity_id": str(entity_id),
        "entity_kind": kind,
        "version": version,
        "is_latest": True,
        "project_id": "proj-a",
        "repository_id": "repo-x",
    }


@pytest.fixture
def hybrid_calls(monkeypatch):
    calls: list[dict] = []

    async def _fake_hybrid(query_dense, query_sparse, *, limit, query_filter):
        calls.append({"limit": limit, "filter": query_filter})
        eid = uuid.uuid4()
        return [{"id": str(uuid.uuid4()), "score": 0.9, "payload": _payload(eid, "work_item")}]

    monkeypatch.setattr("knowledge.vector_recall._hybrid_query", _fake_hybrid)
    return calls


@pytest.fixture
def recall_deps(monkeypatch, hybrid_calls):
    monkeypatch.setattr(
        "knowledge.vector_recall.EmbeddingService.generate_embedding",
        AsyncMock(return_value=[0.1] * 8),
    )
    monkeypatch.setattr(
        "knowledge.vector_recall.sync_to_async",
        lambda fn: AsyncMock(side_effect=lambda *a, **kw: fn(*a, **kw)),
    )
    monkeypatch.setattr(
        "knowledge.vector_recall.SparseEncoderService.encode",
        staticmethod(lambda q: {"indices": [1], "values": [0.5]}),
    )
    return hybrid_calls


def _project_gate_filter(flt) -> qmodels.Filter | None:
    """定位 must 中的嵌套 project 闸（models.Filter 元素，D-01 逃生支）。"""
    for cond in flt.must:
        if isinstance(cond, qmodels.Filter):
            return cond
    return None


async def test_vector_is_latest_filter_in_must():
    """include_superseded=False 时 filter must 含 is_latest=true。"""
    flt = _build_knowledge_must_filter(
        allowed_project_ids=["p1"],
        allowed_repository_ids=["r1"],
        entity_kinds=None,
        include_superseded=False,
    )
    keys = {getattr(c, "key", None) for c in flt.must}
    assert "is_latest" in keys


async def test_vector_project_and_repository_filter():
    """allowed project/repository → repository_id 仍在顶层 must；project 闸移入嵌套支（D-01）。"""
    flt = _build_knowledge_must_filter(
        allowed_project_ids=["proj-a"],
        allowed_repository_ids=["repo-x"],
        entity_kinds=None,
        include_superseded=False,
    )
    keys = {getattr(c, "key", None) for c in flt.must}
    assert "repository_id" in keys
    # project 闸变为嵌套 should 支（allowed_repository_ids 非空时）
    assert _project_gate_filter(flt) is not None


# ---------------------------------------------------------------------------
# quick-260726-q3z（D-01）：project 闸嵌套 OR 逃生支——MCP 三类产物
# （payload project_id="" 但 repository_id 非空）对可见该仓库的用户可召回
# ---------------------------------------------------------------------------


def _assert_project_gate_escape(flt, *, projects: list[str], repos: list[str]) -> None:
    """断言嵌套 project 闸两支结构：A 支 project ∈ allowed；B 支 project=="" ∧ repo ∈ allowed。"""

    gate = _project_gate_filter(flt)
    assert gate is not None, "project 闸应为嵌套 models.Filter(should=[...])"
    assert gate.should is not None and len(gate.should) == 2
    branch_a, branch_b = gate.should
    # 分支 A：原平铺条件 project_id ∈ allowed_project_ids
    assert isinstance(branch_a, qmodels.FieldCondition)
    assert branch_a.key == "project_id"
    assert isinstance(branch_a.match, qmodels.MatchAny)
    assert list(branch_a.match.any) == projects
    # 分支 B：内层 must——project_id 精确空串 ∧ repository_id ∈ allowed_repository_ids
    assert isinstance(branch_b, qmodels.Filter)
    assert branch_b.must is not None and len(branch_b.must) == 2
    proj_cond, repo_cond = branch_b.must
    assert isinstance(proj_cond, qmodels.FieldCondition)
    assert proj_cond.key == "project_id"
    assert isinstance(proj_cond.match, qmodels.MatchValue)
    assert proj_cond.match.value == ""
    assert isinstance(repo_cond, qmodels.FieldCondition)
    assert repo_cond.key == "repository_id"
    assert isinstance(repo_cond.match, qmodels.MatchAny)
    assert list(repo_cond.match.any) == repos
    # 防双空串孤儿点泄漏：第二支 repository_id MatchAny 绝不含空串
    assert "" not in repo_cond.match.any


async def test_vector_project_gate_escape_branch_demand_route():
    """demand 分路（require_repository=False）：project 闸为嵌套 should 两支结构。"""
    flt = _build_knowledge_must_filter(
        allowed_project_ids=["p1"],
        allowed_repository_ids=["r1"],
        entity_kinds=None,
        include_superseded=False,
        require_repository=False,
    )
    _assert_project_gate_escape(flt, projects=["p1"], repos=["r1"])


async def test_vector_project_gate_escape_branch_code_route():
    """code 分路（require_repository=True）同享嵌套 project 闸（独立断言防未来分叉）。"""
    flt = _build_knowledge_must_filter(
        allowed_project_ids=["p1"],
        allowed_repository_ids=["r1"],
        entity_kinds=None,
        include_superseded=False,
        require_repository=True,
    )
    _assert_project_gate_escape(flt, projects=["p1"], repos=["r1"])


async def test_vector_project_gate_flat_when_no_allowed_repos():
    """allowed_repository_ids=[] → project 闸退回平铺 FieldCondition，无嵌套 should 支。

    fail-closed 守护：无可见仓库时行为与修复前逐字段一致。"""
    for require_repository in (False, True):
        flt = _build_knowledge_must_filter(
            allowed_project_ids=["p1"],
            allowed_repository_ids=[],
            entity_kinds=None,
            include_superseded=False,
            require_repository=require_repository,
        )
        assert _project_gate_filter(flt) is None
        project_conds = [c for c in flt.must if getattr(c, "key", None) == "project_id"]
        assert len(project_conds) == 1
        cond = project_conds[0]
        assert isinstance(cond.match, qmodels.MatchAny)
        assert list(cond.match.any) == ["p1"]


async def test_vector_escape_branch_repository_matchany_never_contains_empty():
    """嵌套第二支 repository_id MatchAny.any 不含空串——防 project/repo 双空串孤儿点泄漏。"""
    flt = _build_knowledge_must_filter(
        allowed_project_ids=["p1", "p2"],
        allowed_repository_ids=["r1", "r2"],
        entity_kinds=None,
        include_superseded=False,
        require_repository=False,
    )
    gate = _project_gate_filter(flt)
    assert gate is not None
    branch_b = gate.should[1]
    assert isinstance(branch_b, qmodels.Filter)
    repo_conds = [c for c in branch_b.must if getattr(c, "key", None) == "repository_id"]
    assert len(repo_conds) == 1
    assert "" not in repo_conds[0].match.any


async def test_vector_fail_closed_empty_allowed(recall_deps):
    """allowed=[] → 零 hybrid 调用。"""
    result = await recall_similar_chunks(
        "query",
        allowed_project_ids=[],
        allowed_repository_ids=["r1"],
    )
    assert result == []
    assert recall_deps == []


async def test_vector_route_quotas(recall_deps):
    """top_k=10 → demand limit=7、code limit=3。"""
    await recall_similar_chunks(
        "query",
        allowed_project_ids=["p1"],
        allowed_repository_ids=["r1"],
        top_k=10,
    )
    limits = sorted(c["limit"] for c in recall_deps)
    assert limits == [3, 7]


def _demand_entity_kinds(calls: list[dict]) -> set:
    """从 hybrid 调用记录里抽取 demand 分路 entity_kind MatchAny 值集合。"""
    kinds: set = set()
    for c in calls:
        for cond in c["filter"].must:
            if getattr(cond, "key", None) == "entity_kind":
                kinds.update(cond.match.any)
    return kinds


async def test_vector_include_document_kind_adds_document(recall_deps):
    """include_document_kind=True → demand 分路 entity_kind 纳入 document（CTX-01 读路径）。"""
    await recall_similar_chunks(
        "query",
        allowed_project_ids=["p1"],
        allowed_repository_ids=[],
        top_k=5,
        include_document_kind=True,
    )
    assert recall_deps, "应至少有一次 demand 召回"
    assert EntityKind.DOCUMENT in _demand_entity_kinds(recall_deps)


async def test_vector_default_excludes_document_kind(recall_deps):
    """默认（不传 flag）demand 分路不含 document（不回归全局代码检索召回口径）。"""
    await recall_similar_chunks(
        "query",
        allowed_project_ids=["p1"],
        allowed_repository_ids=[],
        top_k=5,
    )
    assert EntityKind.DOCUMENT not in _demand_entity_kinds(recall_deps)


# ---------------------------------------------------------------------------
# Phase 100（KNOW-02）：显式 entity_kinds 严格过滤（吞参 bug 修复）
# ---------------------------------------------------------------------------


async def test_vector_explicit_learning_case_only_demand_route(recall_deps):
    """entity_kinds=["learning_case"] → 仅 demand 分路 1 次调用，
    filter 中 entity_kind 值集合 == {learning_case}（code 分路交集空被跳过）。"""
    await recall_similar_chunks(
        "query",
        allowed_project_ids=["p1"],
        allowed_repository_ids=["r1"],
        top_k=10,
        entity_kinds=["learning_case"],
    )
    assert len(recall_deps) == 1
    assert _demand_entity_kinds(recall_deps) == {"learning_case"}


async def test_vector_explicit_unknown_kind_returns_empty_no_query(recall_deps):
    """entity_kinds=["nonexistent_kind"] → 0 次 hybrid 调用、返回 []。

    本次修复的核心断言（证伪型）：修复前该场景回退全量白名单必然失败。"""
    result = await recall_similar_chunks(
        "query",
        allowed_project_ids=["p1"],
        allowed_repository_ids=["r1"],
        top_k=10,
        entity_kinds=["nonexistent_kind"],
    )
    assert result == []
    assert recall_deps == []


async def test_vector_explicit_code_change_only_code_route(recall_deps):
    """entity_kinds=["code_change"] → 仅 code 分路 1 次调用（demand 交集空被跳过）。"""
    await recall_similar_chunks(
        "query",
        allowed_project_ids=["p1"],
        allowed_repository_ids=["r1"],
        top_k=10,
        entity_kinds=["code_change"],
    )
    assert len(recall_deps) == 1
    kinds: set = set()
    for cond in recall_deps[0]["filter"].must:
        if getattr(cond, "key", None) == "entity_kind":
            kinds.update(cond.match.any)
    assert kinds == {"code_change"}


async def test_vector_default_kinds_include_learning_case(recall_deps):
    """entity_kinds=None → demand 白名单含 work_item/tech_plan/learning_case，
    code 分路照常（既有 route quota 零回归 + Phase 100 白名单扩容断言）。"""
    await recall_similar_chunks(
        "query",
        allowed_project_ids=["p1"],
        allowed_repository_ids=["r1"],
        top_k=10,
    )
    limits = sorted(c["limit"] for c in recall_deps)
    assert limits == [3, 7]
    demand_kinds = _demand_entity_kinds(recall_deps)
    assert {
        EntityKind.WORK_ITEM,
        EntityKind.TECH_PLAN,
        EntityKind.LEARNING_CASE,
    } <= demand_kinds


async def test_vector_dedupe_same_entity():
    """两路同 entity_id → 融合后单条目。"""
    eid = uuid.uuid4()
    a = VectorHit("p1", eid, "work_item", 1, 0.9, 0.1, {})
    b = VectorHit("p2", eid, "work_item", 1, 0.8, 0.2, {})
    fused = _rrf_fuse([a], [b])
    deduped = _dedupe_by_entity(fused)
    assert len(deduped) == 1
    assert deduped[0].entity_id == eid


async def test_hydrate_work_item_feishu_url(entity_factory, version_factory, project):
    """work_item hydrate 含 feishu_url。"""
    entity = await sync_to_async(entity_factory)(
        kind=EntityKind.WORK_ITEM,
        source_kind="feishu_work_item",
        space=project,
    )
    ver = await sync_to_async(version_factory)(entity)
    meta = await hydrate_entity_metadata(entity.id, ver.version)
    assert meta is not None
    assert meta.provenance.feishu_url is not None


async def test_hydrate_code_change_mr_url(entity_factory, version_factory, repository):
    """code_change hydrate 含 mr_url。"""
    entity = await sync_to_async(entity_factory)(
        kind=EntityKind.CODE_CHANGE,
        source_kind="task_result",
        repository=repository,
    )
    ver = await sync_to_async(version_factory)(entity)
    await sync_to_async(CodeChangeArchive.objects.create)(
        source_kind=entity.source_kind,
        source_id=entity.source_id,
        repository=repository,
        commit_sha="abc123",
        mr_url="https://gitlab.example.com/mr/1",
        diff_compressed=b"x",
        diff_size=1,
        compressed_size=1,
        diff_sha256="a" * 64,
        event_time=timezone.now(),
    )
    meta = await hydrate_entity_metadata(entity.id, ver.version)
    assert meta is not None
    assert meta.provenance.mr_url == "https://gitlab.example.com/mr/1"


async def test_hydrate_skips_non_latest(entity_factory, version_factory):
    """is_latest=false 且 include_superseded=False → None。"""
    entity = await sync_to_async(entity_factory)()
    await sync_to_async(version_factory)(entity, version=1, is_latest=False)
    meta = await hydrate_entity_metadata(entity.id, 1, include_superseded=False)
    assert meta is None


async def test_hydrate_superseded_hint(entity_factory, version_factory):
    """非 latest 版本 superseded_hint 标注。"""
    entity = await sync_to_async(entity_factory)()
    await sync_to_async(version_factory)(entity, version=1, is_latest=False)
    await sync_to_async(version_factory)(entity, version=2, is_latest=True)
    meta = await hydrate_entity_metadata(entity.id, 1, include_superseded=True)
    assert meta is not None
    assert meta.superseded_hint == "superseded by v2"
