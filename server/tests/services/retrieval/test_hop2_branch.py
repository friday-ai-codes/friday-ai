"""work item hop2 branch-aware 契约测试（initial implementation plan）。

覆盖 fetch_hop2_edges 的 branch base/overlay 合并语义 + 跨分支不串 +
base 归一化回归（Pitfall 4 验收红线）：

1. test_feature_differs_from_base —— 切 feature 分支 neighbors 与 base 不同
2. test_base_edges_merged —— base 独有边在 feature 查询中被合并（出现）
3. test_no_cross_branch_leak —— 另一 feature 分支的边在本分支查询中不出现
4. test_base_normalized —— branch=None（base）不漏 base 边（防 ["main"] 漏 "" 行）

ChunkEdge.branch_name 语义（293/294 落地）：base 行 branch_name=""（全分支可见），
feature 行 branch_name=分支名（仅本分支可见）。fetch_hop2_edges 用
``branch_name__in=["", branch] if branch else [""]`` 做合并过滤。
"""

from __future__ import annotations

import uuid

import pytest

from code_relations.models import ChunkEdge, EdgeType
from repositories.models import Repository
from services.retrieval.hop2_expander import fetch_hop2_edges

# 同一 hop1 source，三类分支边共享 source 以验证合并/隔离语义。
_SOURCE = uuid.uuid4()
_TARGET_BASE = uuid.uuid4()
_TARGET_FEAT_A = uuid.uuid4()
_TARGET_FEAT_B = uuid.uuid4()


async def _create_branch_edges(repository: Repository) -> None:
    """构造 base / feat-a / feat-b 三类边，source 共享。"""
    await ChunkEdge.objects.abulk_create(
        [
            # base 独有边（branch_name=""，全分支可见）
            ChunkEdge(
                source_chunk_id=_SOURCE,
                target_chunk_id=_TARGET_BASE,
                edge_type=EdgeType.CALL,
                branch_name="",
                weight=0.9,
                repository=repository,
            ),
            # feature A 边（仅 feat-a 可见）
            ChunkEdge(
                source_chunk_id=_SOURCE,
                target_chunk_id=_TARGET_FEAT_A,
                edge_type=EdgeType.CALL,
                branch_name="feat-a",
                weight=0.8,
                repository=repository,
            ),
            # feature B 边（仅 feat-b 可见，验证跨分支不串）
            ChunkEdge(
                source_chunk_id=_SOURCE,
                target_chunk_id=_TARGET_FEAT_B,
                edge_type=EdgeType.CALL,
                branch_name="feat-b",
                weight=0.7,
                repository=repository,
            ),
        ]
    )


def _edge_keys(edges: list[tuple]) -> set[tuple[str, str, str]]:
    """提取 (source, target, edge_type) 三元组集合，稳定可比较。"""
    return {(src, tgt, et) for src, tgt, et, _w, _meta in edges}


@pytest.mark.django_db(transaction=True)
async def test_feature_differs_from_base(repository) -> None:
    """work item：切 feature 分支的 hop2 neighbors 与 base 不同。"""
    await _create_branch_edges(repository)
    hop1 = [str(_SOURCE)]
    repo_ids = [str(repository.id)]

    base_edges = await fetch_hop2_edges(hop1, repo_ids, branch_name=None)
    feat_a_edges = await fetch_hop2_edges(hop1, repo_ids, branch_name="feat-a")

    base_keys = _edge_keys(base_edges)
    feat_a_keys = _edge_keys(feat_a_edges)

    assert base_keys != feat_a_keys, "feature 查询结果应与 base 不同"
    # feature 查询含 feat-a 边；base 查询不含
    feat_a_key = (str(_SOURCE), str(_TARGET_FEAT_A), EdgeType.CALL)
    assert feat_a_key in feat_a_keys
    assert feat_a_key not in base_keys


@pytest.mark.django_db(transaction=True)
async def test_base_edges_merged(repository) -> None:
    """work item：base 独有边在 feature 查询中被合并（["", "feat-a"]）。"""
    await _create_branch_edges(repository)
    feat_a_edges = await fetch_hop2_edges(
        [str(_SOURCE)], [str(repository.id)], branch_name="feat-a"
    )
    keys = _edge_keys(feat_a_edges)

    base_key = (str(_SOURCE), str(_TARGET_BASE), EdgeType.CALL)
    feat_a_key = (str(_SOURCE), str(_TARGET_FEAT_A), EdgeType.CALL)
    assert base_key in keys, "base 独有边应被合并进 feature 查询"
    assert feat_a_key in keys, "feat-a 自身边应出现"


@pytest.mark.django_db(transaction=True)
async def test_no_cross_branch_leak(repository) -> None:
    """work item：feat-b 的边不应出现在 feat-a 查询中（跨分支不串，Pitfall 4）。"""
    await _create_branch_edges(repository)
    feat_a_edges = await fetch_hop2_edges(
        [str(_SOURCE)], [str(repository.id)], branch_name="feat-a"
    )
    keys = _edge_keys(feat_a_edges)

    feat_b_key = (str(_SOURCE), str(_TARGET_FEAT_B), EdgeType.CALL)
    assert feat_b_key not in keys, "另一 feature 分支的边不得泄漏到本分支查询"


@pytest.mark.django_db(transaction=True)
async def test_base_normalized(repository) -> None:
    """work item：branch=None（base）查询命中所有 base 边，不漏（防 ["main"] 漏 "" 行）。

    回归 Pitfall 4 二义：base 行 branch_name=""，若误用分支名过滤会漏全部 base 边。
    """
    await _create_branch_edges(repository)
    base_edges = await fetch_hop2_edges(
        [str(_SOURCE)], [str(repository.id)], branch_name=None
    )
    keys = _edge_keys(base_edges)

    base_key = (str(_SOURCE), str(_TARGET_BASE), EdgeType.CALL)
    # base 查询只命中 base 行，且全部命中（构造 1 条 base 边）
    assert keys == {base_key}, f"base 查询应恰好命中所有 base 边，得到 {keys}"
