"""Phase Plan：IndexHistory lifecycle wrapper 单测。
覆盖 4 条用例（per Plan deviations / Plan GraphBuildStatus 状态机）：
1. test_marks_running_before_dispatch
 wrapper 调 enqueue_edge_build 之前，IndexHistory.graph_build_status 已被
 写为 RUNNING（同步路径，per CONTEXT ）。
2. test_completion_marks_completed_with_edge_count
 真实 enqueue_edge_build 跑完 → done_callback 触发 → IndexHistory
 graph_build_status="completed" + edge_count = ChunkEdge.count +
 payload_synced_at 非 None。
3. test_completion_marks_failed_on_exception
 builder/payload 内部抛错 → done_callback 把 IndexHistory graph_build_status
 写为 "failed"，payload_synced_at 保 None（per 失败语义）。
4. test_empty_dirty_marks_skipped
 dirty_ids= → graph_build_status="skipped"，且 enqueue_edge_build 不被调
 （避免 tasks.py "skip_empty_dirty" log 路径与 IndexHistory 状态不一致）。
"""
from __future__ import annotations
import asyncio
import uuid
from typing import Any
from unittest.mock import patch
import pytest
from code_relations import tasks as tasks_module
from code_relations.lifecycle import enqueue_edge_build_for_history
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from repositories.models import (
 GraphBuildStatus,
 IndexHistory,
 IndexHistoryStatus,
 TriggerType,
)
pytestmark = pytest.mark.django_db(transaction=True)
async def _make_history(repository: Any) -> IndexHistory:
 return await IndexHistory.objects.acreate(
 repository=repository,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 graph_build_status=GraphBuildStatus.PENDING,
 )
async def _make_chunk(repository: Any, *, index: int = 0) -> ChunkRegistry:
 return await ChunkRegistry.objects.acreate(
 chunk_id=uuid.uuid4,
 content_hash="0" * 64,
 repository=repository,
 file_path=f"src/f_{index:03d}.py",
 chunk_index=index,
 )
async def _drain_background_tasks -> None:
 """等待 tasks._BACKGROUND_TASKS 全部完成。"""
 pending = list(tasks_module._BACKGROUND_TASKS)
 if pending:
 await asyncio.gather(*pending, return_exceptions=True)
 # done_callback 内部用 asyncio.create_task 开新协程更新 IndexHistory，
 # 需要再让事件循环 yield 一轮，等回写完成。
 for _ in range(5):
 await asyncio.sleep(0)
async def test_marks_running_before_dispatch(repository) -> None:
 """wrapper 在调 enqueue_edge_build 之前已把 IndexHistory 标 RUNNING。"""
 history = await _make_history(repository)
 dirty = [uuid.uuid4 for _ in range(2)]
 seen_status: dict[str, str] = {}
 async def _spy(*args: Any, **kwargs: Any) -> None:
 row = await IndexHistory.objects.aget(id=history.id)
 seen_status["status"] = row.graph_build_status
 with patch.object(tasks_module, "enqueue_edge_build", side_effect=_spy):
 await enqueue_edge_build_for_history(str(repository.id), dirty, history.id)
 assert seen_status["status"] == GraphBuildStatus.RUNNING
async def test_completion_marks_completed_with_edge_count(repository) -> None:
 """builder 跑完 → IndexHistory graph_build_status=completed + edge_count 同步 + payload_synced_at 非 None。"""
 history = await _make_history(repository)
 src = await _make_chunk(repository, index=0)
 tgt = await _make_chunk(repository, index=1)
 await ChunkEdge.objects.acreate(
 source_chunk_id=src.chunk_id,
 target_chunk_id=tgt.chunk_id,
 edge_type=EdgeType.CALL,
 weight=0.7,
 metadata={},
 repository=repository,
 )
 dirty = [src.chunk_id]
 # 用空 BUILDERS + mock batch_set_payload，确保 _run_all_builders_and_sync_payload
 # 跑通完整链路（aggregate_top_neighbors → batch_set_payload），不抛异常。
 with patch.object(tasks_module, "BUILDERS", ):
 with patch(
 "services.qdrant_service.QdrantService.batch_set_payload",
 ) as mock_batch:
 async def _noop(*args: Any, **kwargs: Any) -> None:
 return None
 mock_batch.side_effect = _noop
 await enqueue_edge_build_for_history(
 str(repository.id), dirty, history.id
 )
 await _drain_background_tasks
 refreshed = await IndexHistory.objects.aget(id=history.id)
 assert refreshed.graph_build_status == GraphBuildStatus.COMPLETED
 assert refreshed.edge_count == 1 # 累计快照口径
 assert refreshed.payload_synced_at is not None
async def test_completion_marks_failed_on_exception(repository) -> None:
 """builder 协调器抛错 → done_callback 把 IndexHistory 标 FAILED，payload_synced_at 保 None。"""
 history = await _make_history(repository)
 dirty = [uuid.uuid4]
 async def _boom(*args: Any, **kwargs: Any) -> None:
 raise RuntimeError("simulated builder crash")
 # patch enqueue_edge_build 自己 spawn 一个会抛错的 task，模拟"成功 dispatch
 # 但后台执行失败"的语义；done_callback 应识别 task.exception 并写 FAILED。
 async def _fake_enqueue(repo_id: str, dirty_ids: list[uuid.UUID]) -> None:
 task = asyncio.create_task(_boom)
 tasks_module._BACKGROUND_TASKS.add(task)
 task.add_done_callback(tasks_module._BACKGROUND_TASKS.discard)
 with patch.object(tasks_module, "enqueue_edge_build", side_effect=_fake_enqueue):
 await enqueue_edge_build_for_history(str(repository.id), dirty, history.id)
 await _drain_background_tasks
 refreshed = await IndexHistory.objects.aget(id=history.id)
 assert refreshed.graph_build_status == GraphBuildStatus.FAILED
 assert refreshed.payload_synced_at is None
async def test_empty_dirty_marks_skipped(repository) -> None:
 """dirty_ids= → mark SKIPPED + 不调 enqueue_edge_build。"""
 history = await _make_history(repository)
 with patch.object(tasks_module, "enqueue_edge_build") as mock_enqueue:
 await enqueue_edge_build_for_history(str(repository.id),, history.id)
 mock_enqueue.assert_not_called
 refreshed = await IndexHistory.objects.aget(id=history.id)
 assert refreshed.graph_build_status == GraphBuildStatus.SKIPPED
 assert refreshed.edge_count == 0
 assert refreshed.payload_synced_at is None
