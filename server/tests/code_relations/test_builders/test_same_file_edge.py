"""SameFileEdgeBuilder 测试（per Phase/14/15）。"""
from __future__ import annotations
import uuid
import pytest
from asgiref.sync import sync_to_async
from code_relations.builders.same_file_edge import SameFileEdgeBuilder
from code_relations.models import ChunkRegistry, EdgeType
@sync_to_async
def _create_chunks(repository, file_path: str, n: int) -> None:
 objs = [
 ChunkRegistry(
 chunk_id=uuid.uuid4,
 content_hash="x" * 64,
 repository=repository,
 file_path=file_path,
 chunk_index=i,
 )
 for i in range(n)
 ]
 ChunkRegistry.objects.bulk_create(objs)
@pytest.mark.django_db(transaction=True)
async def test_5_chunks_full_pair(repository) -> None:
 """5 chunks → 10 edges，weight=0.3 / source<target 字典序。"""
 await _create_chunks(repository, "src/x.py", 5)
 edges = await SameFileEdgeBuilder.build(repository, )
 assert len(edges) == 10
 for e in edges:
 assert e.weight == 0.3
 assert e.edge_type == EdgeType.SAME_FILE
 assert str(e.source_chunk_id) < str(e.target_chunk_id)
 assert e.metadata["file_path"] == "src/x.py"
@pytest.mark.django_db(transaction=True)
async def test_50_chunks_full_pair(repository) -> None:
 """n=50 仍走全配对：50*49/2 = 1225 边。"""
 await _create_chunks(repository, "src/big.py", 50)
 edges = await SameFileEdgeBuilder.build(repository, )
 assert len(edges) == 50 * 49 // 2
@pytest.mark.django_db(transaction=True)
async def test_100_chunks_neighbor_window(repository) -> None:
 """n=100 (>50) 走相邻 5：sum(min(5, n-1-i) for i in range(100)) = 95×5 + 4+3+2+1 = 485。"""
 await _create_chunks(repository, "src/huge.py", 100)
 edges = await SameFileEdgeBuilder.build(repository, )
 expected = sum(min(5, 100 - 1 - i) for i in range(100))
 assert expected == 485
 assert len(edges) == 485
@pytest.mark.django_db(transaction=True)
async def test_multi_file_mixed(repository) -> None:
 """fileA: 3 chunks (3 edges) + fileB: 60 chunks (60×5 - 15 = 285 edges) = 288。"""
 await _create_chunks(repository, "a.py", 3)
 await _create_chunks(repository, "b.py", 60)
 edges = await SameFileEdgeBuilder.build(repository, )
 expected_b = sum(min(5, 60 - 1 - i) for i in range(60))
 assert expected_b == 285
 assert len(edges) == 3 + 285
@pytest.mark.django_db(transaction=True)
async def test_empty_registry(repository) -> None:
 edges = await SameFileEdgeBuilder.build(repository, )
 assert edges ==
@pytest.mark.django_db(transaction=True)
async def test_single_chunk_no_edge(repository) -> None:
 await _create_chunks(repository, "x.py", 1)
 edges = await SameFileEdgeBuilder.build(repository, )
 assert edges ==
@pytest.mark.django_db(transaction=True)
async def test_chunk_index_diff_metadata(repository) -> None:
 """5 chunks 中应出现 diff=4 (idx 0↔4) 与 diff=1 (idx 1↔2)。"""
 await _create_chunks(repository, "src/x.py", 5)
 edges = await SameFileEdgeBuilder.build(repository, )
 diffs = {e.metadata["chunk_index_diff"] for e in edges}
 assert 4 in diffs
 assert 1 in diffs
