"""Phase Plan：ChunkRegistry pre_delete 信号 handler 单测。
覆盖 4 + 1 条用例（per Plan / / / ）：
1. test_handler_deletes_inbound_chunk_edges
 pre_delete handler 同步删除 ChunkEdge.target_chunk_id=deleted 的孤儿边
 （ChunkRegistry 行删除前反查 → 自动清理）。
2. test_handler_schedules_reconcile_with_distinct_sources
 handler 通过 transaction.on_commit 投递一次 `_schedule_reconcile(repo_id, sources)`，
 sources 为去重后的所有 source_chunk_id（per dirty source 收集）。
3. test_handler_skips_reconcile_when_no_inbound_edges
 无 inbound edge → 不调 `_schedule_reconcile`（空 dirty_set 不触发 enqueue）。
4. test_handler_exception_does_not_block_delete
 handler 内任意 ORM 调用抛错 → catch + log warning，不向上传播；
 ChunkRegistry 行仍被成功删除（per 异常隔离）。
5. test_reconcile_not_triggered_on_rollback
 transaction.atomic 回滚时 `_schedule_reconcile` 不被调用（per
 on_commit 语义 —— 避免 rollback 但 dirty enqueue 不一致）。
"""
from __future__ import annotations
import uuid
from unittest.mock import patch
import pytest
from django.db import transaction
from code_relations import signals as signals_module
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
pytestmark = pytest.mark.django_db(transaction=True)
def _make_chunk(repository, *, file_path: str = "src/foo.py", index: int = 0) -> ChunkRegistry:
 """创建一个 ChunkRegistry 行（chunk_id 随机 UUID）。"""
 return ChunkRegistry.objects.create(
 chunk_id=uuid.uuid4,
 content_hash="0" * 64,
 repository=repository,
 file_path=file_path,
 chunk_index=index,
 )
def _make_edge(
 repository, *, source: uuid.UUID, target: uuid.UUID, edge_type: str = EdgeType.CALL
) -> ChunkEdge:
 return ChunkEdge.objects.create(
 source_chunk_id=source,
 target_chunk_id=target,
 edge_type=edge_type,
 weight=0.5,
 metadata={},
 repository=repository,
 )
def test_handler_deletes_inbound_chunk_edges(repository) -> None:
 """删 target chunk → 指向它的 2 条 ChunkEdge 同步被清理（孤儿边自动清理 per ）。"""
 target = _make_chunk(repository, file_path="src/target.py")
 src1 = _make_chunk(repository, file_path="src/src1.py", index=1)
 src2 = _make_chunk(repository, file_path="src/src2.py", index=2)
 _make_edge(repository, source=src1.chunk_id, target=target.chunk_id, edge_type=EdgeType.CALL)
 _make_edge(repository, source=src2.chunk_id, target=target.chunk_id, edge_type=EdgeType.IMPORT)
 other_target = _make_chunk(repository, file_path="src/other.py", index=3)
 _make_edge(repository, source=src1.chunk_id, target=other_target.chunk_id, edge_type=EdgeType.CALL)
 with patch.object(signals_module, "_schedule_reconcile"):
 target.delete
 assert ChunkEdge.objects.filter(target_chunk_id=target.chunk_id).count == 0
 assert ChunkEdge.objects.filter(target_chunk_id=other_target.chunk_id).count == 1
def test_handler_schedules_reconcile_with_distinct_sources(repository) -> None:
 """transaction commit 后 `_schedule_reconcile` 被调用 1 次，且收到去重后的 source_ids。"""
 target = _make_chunk(repository, file_path="src/t.py")
 src1 = _make_chunk(repository, file_path="src/s1.py", index=1)
 src2 = _make_chunk(repository, file_path="src/s2.py", index=2)
 _make_edge(repository, source=src1.chunk_id, target=target.chunk_id, edge_type=EdgeType.CALL)
 _make_edge(repository, source=src1.chunk_id, target=target.chunk_id, edge_type=EdgeType.IMPORT)
 _make_edge(repository, source=src2.chunk_id, target=target.chunk_id, edge_type=EdgeType.SAME_FILE)
 with patch.object(signals_module, "_schedule_reconcile") as mock_schedule:
 target.delete
 assert mock_schedule.call_count == 1
 repo_id_arg, source_ids_arg = mock_schedule.call_args.args
 assert repo_id_arg == str(repository.id)
 assert set(source_ids_arg) == {src1.chunk_id, src2.chunk_id}
def test_handler_skips_reconcile_when_no_inbound_edges(repository) -> None:
 """孤立 ChunkRegistry（无 inbound edge）→ `_schedule_reconcile` 不被调用（空 dirty_set 不触发 enqueue）。"""
 isolated = _make_chunk(repository, file_path="src/isolated.py")
 with patch.object(signals_module, "_schedule_reconcile") as mock_schedule:
 isolated.delete
 assert mock_schedule.call_count == 0
def test_handler_exception_does_not_block_delete(repository) -> None:
 """handler 内 ORM 抛错 → catch + log warning + ChunkRegistry 删除仍成功（per ）。"""
 target = _make_chunk(repository, file_path="src/boom.py")
 with patch.object(signals_module, "ChunkEdge") as mock_edge_cls:
 mock_edge_cls.objects.filter.side_effect = RuntimeError("simulated ORM failure")
 target.delete
 assert not ChunkRegistry.objects.filter(chunk_id=target.chunk_id).exists
def test_reconcile_not_triggered_on_rollback(repository) -> None:
 """transaction.atomic 回滚 → `_schedule_reconcile` 不被调用（on_commit 语义）。"""
 target = _make_chunk(repository, file_path="src/rollback.py")
 src = _make_chunk(repository, file_path="src/s.py", index=1)
 _make_edge(repository, source=src.chunk_id, target=target.chunk_id, edge_type=EdgeType.CALL)
 target_id = target.chunk_id # 缓存：Django delete 后会把 instance.pk 设为 None
 with patch.object(signals_module, "_schedule_reconcile") as mock_schedule:
 try:
 with transaction.atomic:
 target.delete
 raise RuntimeError("force rollback")
 except RuntimeError:
 pass
 mock_schedule.assert_not_called
 assert ChunkRegistry.objects.filter(chunk_id=target_id).exists
 assert ChunkEdge.objects.filter(target_chunk_id=target_id).count == 1
