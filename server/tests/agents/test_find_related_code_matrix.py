"""``HybridSearchService.find_related`` 矩阵覆盖 —— per implementation / work item。

2 条聚焦 NullProvider + find_related Python API 路径：

- ``test_find_related_returns_empty_when_no_edges_for_null_provider`` —— mock
  ChunkEdge ORM 空 → ``find_related`` 返 ``[]``；与 implementation deviation
  "任何 provider 调 find_related 都能拿到 ChunkEdge 数据" 形成正向覆盖。
- ``test_find_related_with_chunk_edge_data_for_null_provider`` —— mock 2 ChunkEdge
  hop1 边 → ``find_related`` 返 2 ``NeighborMetadata``；NullProvider 不阻挡
  ChunkEdge ORM 路径（与 ``find_related_code`` MCP tool 的 ``symbol_name`` 路径
  需要 SymbolCapableProvider 守卫语义对偶）。

函数名带 ``_null_provider`` 后缀（success criterion 字面要求 ``pytest -k
null_provider --co`` 收集）。mock 模式：patch
``services.retrieval.find_related._fetch_hop1_edges`` /
``_resolve_chunk_files`` 直接绕过 ``@sync_to_async`` ORM 边界（与
``tests/agents/test_find_related_code_tool.py`` 同模式但更靠下层）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from services.retrieval.types import NeighborMetadata

_START_CHUNK_ID = "11111111-1111-1111-1111-111111111111"
_NEIGHBOR_1 = "22222222-2222-2222-2222-222222222222"
_NEIGHBOR_2 = "33333333-3333-3333-3333-333333333333"
_REPO_ID = "44444444-4444-4444-4444-444444444444"


# ---------------------------------------------------------------------------
# Test 1: 空 ChunkEdge → find_related 返 []
# ---------------------------------------------------------------------------


async def test_find_related_returns_empty_when_no_edges_for_null_provider() -> None:
    """NullProvider 注入 + ChunkEdge ORM 空 → ``find_related`` 返 ``[]`` 不抛错。

    ``HybridSearchService.find_related`` thin wrapper delegate 到
    ``services.retrieval.find_related.find_related``——implementation deviation
    "不做 isinstance(GraphCapableProvider) 守卫" 决策点：直接查 ChunkEdge ORM。
    NullProvider 注入不阻挡本路径，hop1 边查询无结果 → 返 ``[]``。
    """
    service = HybridSearchService(NullProvider())

    with patch(
        "services.retrieval.find_related._fetch_hop1_edges",
        new=AsyncMock(return_value=[]),
    ):
        result = await service.find_related(
            _START_CHUNK_ID,
            repo_ids=[_REPO_ID],
            relation_types=["CALL", "IMPORT"],
            hops=1,
            direction="both",
            limit=20,
        )

    assert result == []


# ---------------------------------------------------------------------------
# Test 2: 2 ChunkEdge hop1 → find_related 返 2 NeighborMetadata
# ---------------------------------------------------------------------------


async def test_find_related_with_chunk_edge_data_for_null_provider() -> None:
    """NullProvider 注入 + 2 mock ChunkEdge hop1 边 → 返 2 ``NeighborMetadata``。

    断言三点：
    - 邻居数量 == 2；
    - 每个 NeighborMetadata 的 ``chunk_id`` / ``edge_type`` / ``weight`` 与 mock
      边 1:1 对齐；
    - ``reason`` 非空（implementation ``explain_neighbor`` 模板生成）；
    - ``file_path`` 由 ``_resolve_chunk_files`` 模拟的 ChunkRegistry metadata
      填充（验证 NullProvider 路径不阻断 ChunkRegistry 元数据补全）。
    """
    service = HybridSearchService(NullProvider())

    hop1_edges: list[tuple[str, str, str, float, dict[str, object]]] = [
        # (start_chunk_id, neighbor_chunk_id, edge_type, weight, metadata)
        (_START_CHUNK_ID, _NEIGHBOR_1, "CALL", 0.9, {}),
        (_START_CHUNK_ID, _NEIGHBOR_2, "IMPORT", 0.7, {}),
    ]
    file_meta = {
        _START_CHUNK_ID: ("src/start.py", 10, 30),
        _NEIGHBOR_1: ("src/neighbor1.py", 5, 25),
        _NEIGHBOR_2: ("src/neighbor2.py", 1, 15),
    }

    with patch(
        "services.retrieval.find_related._fetch_hop1_edges",
        new=AsyncMock(return_value=hop1_edges),
    ), patch(
        "services.retrieval.find_related._resolve_chunk_files",
        new=AsyncMock(return_value=file_meta),
    ):
        result = await service.find_related(
            _START_CHUNK_ID,
            repo_ids=[_REPO_ID],
            relation_types=["CALL", "IMPORT"],
            hops=1,
            direction="downstream",
            limit=20,
        )

    assert len(result) == 2
    # 按 (hop ASC, weight DESC) 排序 → CALL 在前（weight 0.9 > 0.7）
    assert all(isinstance(n, NeighborMetadata) for n in result)
    assert result[0].chunk_id == _NEIGHBOR_1
    assert result[0].edge_type == "CALL"
    assert result[0].weight == 0.9
    assert result[0].file_path == "src/neighbor1.py"
    assert result[0].hop == 1
    assert result[0].reason, "reason 必须非空（per implementation explain_neighbor 模板）"

    assert result[1].chunk_id == _NEIGHBOR_2
    assert result[1].edge_type == "IMPORT"
    assert result[1].weight == 0.7
    assert result[1].file_path == "src/neighbor2.py"
