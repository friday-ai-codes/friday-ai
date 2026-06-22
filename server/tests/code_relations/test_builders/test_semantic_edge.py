"""SemanticEdgeBuilder 单元测试（per implementation contract/08）。

mock Qdrant client（scroll + query_points），断言：
- 空 dirty 不调 client
- 单 dirty + 3 candidates → 3 ChunkEdge[SEMANTIC] weight 对齐 score
- score 越界 (>1 / <0) → 双重 clamp 到 [0, 1]
- score = NaN / Inf → skip 不入边（security mitigation 守卫）
- hybrid vector dict → 取 dense 子键传 query_points
- scroll miss（chunk 已删）→ skip 不调 query_points
- query_points 调用参数严格对齐 contract：limit=20 / score_threshold=0.85 / must_not file_path
- metadata = {'qdrant_score': float}
"""

from __future__ import annotations

import math
import uuid
from unittest.mock import MagicMock, patch

import pytest
from qdrant_client.http import models as qmodels

from code_relations.builders.semantic_edge import SemanticEdgeBuilder
from code_relations.models import EdgeType


def _make_scroll_result(
    chunk_id: str,
    file_path: str | None,
    vector: list[float] | dict[str, object] | None,
) -> tuple[list[MagicMock], None]:
    p = MagicMock()
    p.id = chunk_id
    p.payload = {"file_path": file_path} if file_path else {}
    p.vector = vector
    return [p], None


def _make_query_result(points: list[tuple[str, float]]) -> MagicMock:
    result = MagicMock()
    result.points = []
    for cid, score in points:
        sp = MagicMock()
        sp.id = cid
        sp.score = score
        result.points.append(sp)
    return result


@pytest.mark.django_db(transaction=True)
async def test_empty_dirty_returns_empty(repository) -> None:
    """dirty_chunk_ids 为空 → 直接返 []，不调 Qdrant client。"""
    with patch("services.qdrant_service.QdrantService.get_client") as mock_get_client:
        edges = await SemanticEdgeBuilder().build(repository, [])
        mock_get_client.assert_not_called()
    assert edges == []


@pytest.mark.django_db(transaction=True)
async def test_single_dirty_three_candidates(repository) -> None:
    """1 dirty chunk → scroll 拿向量 → query_points 返 3 candidate → 3 SEMANTIC 边。"""
    dirty_cid = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    candidates = [
        ("bbbbbbbb-0000-0000-0000-000000000001", 0.95),
        ("cccccccc-0000-0000-0000-000000000001", 0.90),
        ("dddddddd-0000-0000-0000-000000000001", 0.86),
    ]
    mock_client = MagicMock()
    mock_client.scroll.return_value = _make_scroll_result(
        str(dirty_cid), "src/a.py", [0.1] * 1024
    )
    mock_client.query_points.return_value = _make_query_result(candidates)

    with patch(
        "services.qdrant_service.QdrantService.get_client", return_value=mock_client
    ):
        edges = await SemanticEdgeBuilder().build(repository, [dirty_cid])

    assert len(edges) == 3
    assert all(e.edge_type == EdgeType.SEMANTIC for e in edges)
    assert all(e.source_chunk_id == dirty_cid for e in edges)
    assert edges[0].weight == pytest.approx(0.95)
    assert edges[1].weight == pytest.approx(0.90)
    assert edges[2].weight == pytest.approx(0.86)

    kwargs = mock_client.query_points.call_args.kwargs
    assert kwargs["limit"] == 20
    assert kwargs["score_threshold"] == 0.85
    # 单向量（dense list）collection 不传 using（保持默认向量空间）
    assert kwargs.get("using") is None
    assert isinstance(kwargs["query_filter"], qmodels.Filter)
    must_not = kwargs["query_filter"].must_not
    assert must_not is not None
    assert isinstance(must_not, list) and len(must_not) == 1
    cond = must_not[0]
    assert isinstance(cond, qmodels.FieldCondition)
    assert cond.key == "file_path"
    assert isinstance(cond.match, qmodels.MatchValue)
    assert cond.match.value == "src/a.py"


@pytest.mark.django_db(transaction=True)
async def test_score_clamping(repository) -> None:
    """score 越界（>1 / <0）→ clamp 到 [0, 1]，原始 score 仍记 metadata。"""
    dirty_cid = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    candidates = [
        ("bbbbbbbb-0000-0000-0000-000000000001", 1.5),
        ("cccccccc-0000-0000-0000-000000000001", -0.2),
    ]
    mock_client = MagicMock()
    mock_client.scroll.return_value = _make_scroll_result(
        str(dirty_cid), "a.py", [0.1] * 1024
    )
    mock_client.query_points.return_value = _make_query_result(candidates)

    with patch(
        "services.qdrant_service.QdrantService.get_client", return_value=mock_client
    ):
        edges = await SemanticEdgeBuilder().build(repository, [dirty_cid])

    assert len(edges) == 2
    assert edges[0].weight == 1.0
    assert edges[1].weight == 0.0
    assert edges[0].metadata == {"qdrant_score": 1.5}
    assert edges[1].metadata == {"qdrant_score": -0.2}


@pytest.mark.django_db(transaction=True)
async def test_nan_and_inf_score_skipped(repository) -> None:
    """security mitigation 守卫：score = NaN / Inf 跳过，不污染 weight。"""
    dirty_cid = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    candidates = [
        ("bbbbbbbb-0000-0000-0000-000000000001", math.nan),
        ("cccccccc-0000-0000-0000-000000000001", math.inf),
        ("dddddddd-0000-0000-0000-000000000001", 0.9),
    ]
    mock_client = MagicMock()
    mock_client.scroll.return_value = _make_scroll_result(
        str(dirty_cid), "a.py", [0.1] * 1024
    )
    mock_client.query_points.return_value = _make_query_result(candidates)

    with patch(
        "services.qdrant_service.QdrantService.get_client", return_value=mock_client
    ):
        edges = await SemanticEdgeBuilder().build(repository, [dirty_cid])

    assert len(edges) == 1
    assert edges[0].weight == pytest.approx(0.9)


@pytest.mark.django_db(transaction=True)
async def test_hybrid_vector_dict_takes_dense(repository) -> None:
    """hybrid collection: vector 是 dict → 取 vector['dense'] 传 query_points。"""
    dirty_cid = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    hybrid_vec: dict[str, object] = {
        "dense": [0.5] * 1024,
        "sparse": {"indices": [], "values": []},
    }
    mock_client = MagicMock()
    mock_client.scroll.return_value = _make_scroll_result(
        str(dirty_cid), "a.py", hybrid_vec
    )
    mock_client.query_points.return_value = _make_query_result([])

    with patch(
        "services.qdrant_service.QdrantService.get_client", return_value=mock_client
    ):
        await SemanticEdgeBuilder().build(repository, [dirty_cid])

    kwargs = mock_client.query_points.call_args.kwargs
    assert kwargs["query"] == [0.5] * 1024
    # hybrid（命名向量）collection 必须指定 using="dense"，否则 Qdrant 报
    # "Not existing vector name"
    assert kwargs["using"] == "dense"


@pytest.mark.django_db(transaction=True)
async def test_scroll_miss_skips_chunk(repository) -> None:
    """scroll 拿不到该 chunk_id（已删）→ skip 该 dirty，不调 query_points。"""
    dirty_cid = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    mock_client = MagicMock()
    mock_client.scroll.return_value = ([], None)

    with patch(
        "services.qdrant_service.QdrantService.get_client", return_value=mock_client
    ):
        edges = await SemanticEdgeBuilder().build(repository, [dirty_cid])

    assert edges == []
    mock_client.query_points.assert_not_called()


@pytest.mark.django_db(transaction=True)
async def test_metadata_qdrant_score(repository) -> None:
    """metadata 必含原始 qdrant_score（未 clamp 前的浮点）。"""
    dirty_cid = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    mock_client = MagicMock()
    mock_client.scroll.return_value = _make_scroll_result(
        str(dirty_cid), "a.py", [0.1] * 1024
    )
    mock_client.query_points.return_value = _make_query_result(
        [("bbbbbbbb-0000-0000-0000-000000000001", 0.9123)]
    )

    with patch(
        "services.qdrant_service.QdrantService.get_client", return_value=mock_client
    ):
        edges = await SemanticEdgeBuilder().build(repository, [dirty_cid])

    assert edges[0].metadata == {"qdrant_score": 0.9123}


# =============================================================================
# implementation / 跨语言守门 parametrize 测试
# 静态审计：SemanticEdgeBuilder 基于 Qdrant 向量近邻 + payload.file_path 过滤，
# 无语言假设 → 天然语言无关 git diff = 0。
# =============================================================================


@pytest.mark.parametrize(
    "file_path",
    [
        "handlers/user.go",          # Go
        "src/utils.ts",              # TypeScript
        "components/Button.vue",     # Vue
    ],
)
@pytest.mark.django_db(transaction=True)
async def test_semantic_edge_cross_language_guard(repository, file_path: str) -> None:
    """implementation / work item 守门：SemanticEdge 对所有语言 file_path 均能建 ≥ 1 edge。

    mock Qdrant return 1 candidate → ≥ 1 SEMANTIC edge。验证 builder 文件路径无关。
    """
    dirty_cid = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    candidate_cid = "bbbbbbbb-0000-0000-0000-000000000001"
    mock_client = MagicMock()
    mock_client.scroll.return_value = _make_scroll_result(
        str(dirty_cid), file_path, [0.1] * 1024
    )
    mock_client.query_points.return_value = _make_query_result([(candidate_cid, 0.92)])

    with patch(
        "services.qdrant_service.QdrantService.get_client", return_value=mock_client
    ):
        edges = await SemanticEdgeBuilder().build(repository, [dirty_cid])

    assert len(edges) >= 1
    assert edges[0].edge_type == EdgeType.SEMANTIC
    assert edges[0].source_chunk_id == dirty_cid


@pytest.mark.django_db(transaction=True)
async def test_self_target_skipped(repository) -> None:
    """query_points 万一回返自身 chunk_id（理论 must_not 已防）→ skip 自环。"""
    dirty_cid = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    mock_client = MagicMock()
    mock_client.scroll.return_value = _make_scroll_result(
        str(dirty_cid), "a.py", [0.1] * 1024
    )
    mock_client.query_points.return_value = _make_query_result(
        [
            (str(dirty_cid), 1.0),  # 自身
            ("bbbbbbbb-0000-0000-0000-000000000001", 0.9),
        ]
    )

    with patch(
        "services.qdrant_service.QdrantService.get_client", return_value=mock_client
    ):
        edges = await SemanticEdgeBuilder().build(repository, [dirty_cid])

    assert len(edges) == 1
    assert edges[0].source_chunk_id == dirty_cid
    assert str(edges[0].target_chunk_id) == "bbbbbbbb-0000-0000-0000-000000000001"
