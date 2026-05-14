"""tasks._run_all_builders_and_sync_payload + enqueue_edge_build 测试
（per Phase / / ）。
覆盖：
- 空 dirty 短路（不 spawn task）
- fire-and-forget wall-clock < 100ms（mock builder sleep 2s 不阻塞）
- 6 builder gather + 1 fail 不中断其余
- batch_set_payload 调**恰好一次**（per，不是 6 次 per builder）
- Repository 不存在 → log error + return，不抛
- BUILDERS 注册 6 类
"""
from __future__ import annotations
import asyncio
import time
import uuid
from unittest.mock import AsyncMock, patch
import pytest
from code_relations import tasks as tasks_module
from code_relations.builders import (
 BUILDERS,
 CallEdgeBuilder,
 CoChangedEdgeBuilder,
 ImportEdgeBuilder,
 SameFileEdgeBuilder,
 SemanticEdgeBuilder,
 TestOfEdgeBuilder,
)
from code_relations.models import ChunkEdge, EdgeType
from code_relations.tasks import _run_all_builders_and_sync_payload, enqueue_edge_build
def test_builders_registered_six_classes -> None:
 """BUILDERS 注册顺序 + 含 6 类 builder 类。"""
 assert BUILDERS == [
 CallEdgeBuilder,
 ImportEdgeBuilder,
 SameFileEdgeBuilder,
 TestOfEdgeBuilder,
 CoChangedEdgeBuilder,
 SemanticEdgeBuilder,
 ]
@pytest.mark.django_db(transaction=True)
async def test_enqueue_empty_dirty_does_not_spawn -> None:
 """空 dirty_chunk_ids → 不调 asyncio.create_task。"""
 with patch.object(asyncio, "create_task") as mock_ct:
 await enqueue_edge_build("11111111-1111-1111-1111-111111111111", )
 mock_ct.assert_not_called
@pytest.mark.django_db(transaction=True)
async def test_enqueue_fire_and_forget_returns_quickly(repository) -> None:
 """enqueue_edge_build 立即 return（< 100ms），不等待背景 task 完成。"""
 async def _slow_runner(repo_id: str, dirty: list[uuid.UUID]) -> None:
 await asyncio.sleep(2.0)
 with patch.object(tasks_module, "_run_all_builders_and_sync_payload", _slow_runner):
 start = time.monotonic
 await enqueue_edge_build(str(repository.id), [uuid.uuid4])
 elapsed = time.monotonic - start
 assert elapsed < 0.1, f"expected < 100ms, got {elapsed * 1000:.0f}ms"
@pytest.mark.django_db(transaction=True)
async def test_run_all_builders_one_failure_does_not_abort_rest(repository) -> None:
 """6 builder 之一 raise → 其余 5 个仍跑完，bulk_insert_edges 仍调用，
 payload sync 仍调一次。"""
 src = uuid.uuid4
 tgt = uuid.uuid4
 successful_edges = [
 ChunkEdge(
 source_chunk_id=src,
 target_chunk_id=tgt,
 edge_type=EdgeType.CALL,
 weight=0.5,
 metadata={},
 repository=repository,
 )
 ]
 class _GoodBuilder:
 edge_type_label = "Good"
 async def build(self, repo, dirty): # type: ignore[no-untyped-def]
 return successful_edges
 class _BadBuilder:
 edge_type_label = "Bad"
 async def build(self, repo, dirty): # type: ignore[no-untyped-def]
 raise RuntimeError("simulated builder failure")
 fake_builders = [_GoodBuilder, _GoodBuilder, _GoodBuilder, _BadBuilder, _GoodBuilder, _GoodBuilder]
 with patch.object(tasks_module, "BUILDERS", fake_builders):
 with patch(
 "services.qdrant_service.QdrantService.batch_set_payload",
 new_callable=AsyncMock,
 ) as mock_batch:
 await _run_all_builders_and_sync_payload(str(repository.id), [src])
 assert mock_batch.call_count == 1
 assert await ChunkEdge.objects.acount == 1
@pytest.mark.django_db(transaction=True)
async def test_batch_set_payload_called_exactly_once(repository) -> None:
 """6 builder 全部返回 [ChunkEdge × N] → batch_set_payload 仅调用 1 次（不是 6 次）。"""
 src = uuid.uuid4
 targets = [uuid.uuid4 for _ in range(6)]
 def _make_builder(weight: float, target: uuid.UUID, edge_type: EdgeType, label: str):
 class _B:
 edge_type_label = label
 async def build(self, repo, dirty): # type: ignore[no-untyped-def]
 return [
 ChunkEdge(
 source_chunk_id=src,
 target_chunk_id=target,
 edge_type=edge_type,
 weight=weight,
 metadata={},
 repository=repository,
 )
 ]
 return _B
 fake_builders = [
 _make_builder(0.9, targets[0], EdgeType.CALL, "B1"),
 _make_builder(0.8, targets[1], EdgeType.IMPORT, "B2"),
 _make_builder(0.3, targets[2], EdgeType.SAME_FILE, "B3"),
 _make_builder(0.6, targets[3], EdgeType.TEST_OF, "B4"),
 _make_builder(0.5, targets[4], EdgeType.CO_CHANGED, "B5"),
 _make_builder(0.95, targets[5], EdgeType.SEMANTIC, "B6"),
 ]
 with patch.object(tasks_module, "BUILDERS", fake_builders):
 with patch(
 "services.qdrant_service.QdrantService.batch_set_payload",
 new_callable=AsyncMock,
 ) as mock_batch:
 await _run_all_builders_and_sync_payload(str(repository.id), [src])
 assert mock_batch.call_count == 1
 repo_arg, updates_arg = mock_batch.call_args.args[0], mock_batch.call_args.args[1]
 assert repo_arg == str(repository.id)
 assert len(updates_arg) == 1
 point_id, payload = updates_arg[0]
 assert point_id == str(src)
 assert len(payload["related_chunks"]) == 6
 assert await ChunkEdge.objects.acount == 6
@pytest.mark.django_db(transaction=True)
async def test_repository_not_found_logs_and_returns(caplog) -> None:
 """repo 不存在 → log error + return，不抛错，不调任何后续 API。"""
 bogus_id = "99999999-9999-9999-9999-999999999999"
 with patch(
 "services.qdrant_service.QdrantService.batch_set_payload",
 new_callable=AsyncMock,
 ) as mock_batch:
 await _run_all_builders_and_sync_payload(bogus_id, [uuid.uuid4])
 mock_batch.assert_not_called
