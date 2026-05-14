"""code_relations.storage.bulk_insert_edges 测试（per Phase）。"""
from __future__ import annotations
import uuid
from unittest.mock import patch
import pytest
from code_relations.models import ChunkEdge, EdgeType
from code_relations.storage import bulk_insert_edges
def _make_edges(repository, n: int) -> list[ChunkEdge]:
 edges: list[ChunkEdge] =
 for _ in range(n):
 edges.append(
 ChunkEdge(
 source_chunk_id=uuid.uuid4,
 target_chunk_id=uuid.uuid4,
 edge_type=EdgeType.CALL,
 weight=0.5,
 metadata={},
 repository=repository,
 )
 )
 return edges
@pytest.mark.django_db(transaction=True)
async def test_bulk_insert_edges_basic(repository) -> None:
 edges = _make_edges(repository, 5)
 inserted = await bulk_insert_edges(edges)
 assert inserted == 5
 assert await ChunkEdge.objects.acount == 5
@pytest.mark.django_db(transaction=True)
async def test_bulk_insert_edges_conflict_ignored(repository) -> None:
 """ignore_conflicts=True：同 (source, target, edge_type) 第二次写入不抛错，
 DB 层仍只有 1 行（unique 约束 + ignore_conflicts 静默去重；abulk_create 在
 SQLite 上无法返回精确的 inserted 数，故只断言 DB 真实行数）。"""
 src = uuid.uuid4
 tgt = uuid.uuid4
 edges = [
 ChunkEdge(
 source_chunk_id=src,
 target_chunk_id=tgt,
 edge_type=EdgeType.CALL,
 weight=0.5,
 metadata={},
 repository=repository,
 )
 ]
 await bulk_insert_edges(edges)
 assert await ChunkEdge.objects.acount == 1
 edges2 = [
 ChunkEdge(
 source_chunk_id=src,
 target_chunk_id=tgt,
 edge_type=EdgeType.CALL,
 weight=0.5,
 metadata={},
 repository=repository,
 )
 ]
 # 第二次写入不抛错（ignore_conflicts 兜底）
 await bulk_insert_edges(edges2)
 assert await ChunkEdge.objects.acount == 1
@pytest.mark.django_db(transaction=True)
async def test_bulk_insert_edges_empty -> None:
 """空 list 立即返回 0，不抛错。"""
 inserted = await bulk_insert_edges
 assert inserted == 0
@pytest.mark.django_db(transaction=True)
async def test_bulk_insert_edges_batch_split(repository) -> None:
 """5000 条 edges + batch_size=1000 触发 5 次 abulk_create。"""
 edges = _make_edges(repository, 5000)
 original_abulk = ChunkEdge.objects.abulk_create
 call_count = 0
 async def _spy(chunk, **kwargs):
 nonlocal call_count
 call_count += 1
 return await original_abulk(chunk, **kwargs)
 with patch.object(ChunkEdge.objects, "abulk_create", side_effect=_spy):
 inserted = await bulk_insert_edges(edges, batch_size=1000)
 assert call_count == 5
 assert inserted == 5000
