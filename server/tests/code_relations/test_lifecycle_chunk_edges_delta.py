"""Phase：chunk_edges_added per-run delta 回写单测（Pitfall 7）。
验证 lifecycle `_handle_completion` 在 COMPLETED 分支经 `task.result` 读取
orchestrator 返回的本次插入数，写入 IndexHistory.chunk_edges_added，且该值与
全表累计 edge_count 语义对立（绝不复用 _count_edges_or_none 全表 count）。
"""
from __future__ import annotations
import asyncio
import uuid
from typing import Any
import pytest
from code_relations.lifecycle import _handle_completion
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
 graph_build_status=GraphBuildStatus.RUNNING,
 )
async def _make_edge(repository: Any, idx: int) -> None:
 src = await ChunkRegistry.objects.acreate(
 chunk_id=uuid.uuid4,
 content_hash="0" * 64,
 repository=repository,
 file_path=f"src/s_{idx:03d}.py",
 chunk_index=idx,
 )
 tgt = await ChunkRegistry.objects.acreate(
 chunk_id=uuid.uuid4,
 content_hash="1" * 64,
 repository=repository,
 file_path=f"src/t_{idx:03d}.py",
 chunk_index=idx + 1000,
 )
 await ChunkEdge.objects.acreate(
 source_chunk_id=src.chunk_id,
 target_chunk_id=tgt.chunk_id,
 edge_type=EdgeType.CALL,
 weight=0.5,
 metadata={},
 repository=repository,
 )
async def _completed_task(value: int) -> asyncio.Task[int]:
 """构造一个已完成、result==value 的 task（模拟 orchestrator return inserted）。"""
 async def _coro -> int:
 return value
 task: asyncio.Task[int] = asyncio.create_task(_coro)
 await task
 return task
async def test_chunk_edges_added_is_per_run(repository) -> None:
 """task.result 返回 inserted=N → chunk_edges_added 写为 N。"""
 history = await _make_history(repository)
 task = await _completed_task(3)
 await _handle_completion(task, history.id, str(repository.id), remaining=[1])
 refreshed = await IndexHistory.objects.aget(id=history.id)
 assert refreshed.graph_build_status == GraphBuildStatus.COMPLETED
 assert refreshed.chunk_edges_added == 3
async def test_chunk_edges_added_differs_from_edge_count(repository) -> None:
 """全表累计 edge_count 大数 vs 本次 inserted 小数：两字段值不同（Pitfall 7）。"""
 history = await _make_history(repository)
 # 造 5 条 ChunkEdge → _count_edges_or_none 全表累计 = 5
 for i in range(5):
 await _make_edge(repository, i)
 # 本次 orchestrator 仅插入 2 条（去重后真实新增）
 task = await _completed_task(2)
 await _handle_completion(task, history.id, str(repository.id), remaining=[1])
 refreshed = await IndexHistory.objects.aget(id=history.id)
 assert refreshed.edge_count == 5 # 累计快照口径
 assert refreshed.chunk_edges_added == 2 # per-run delta
 assert refreshed.chunk_edges_added != refreshed.edge_count
async def test_zero_inserted_writes_zero(repository) -> None:
 """task.result==0（本次无新增）→ chunk_edges_added 写真实 0。"""
 history = await _make_history(repository)
 task = await _completed_task(0)
 await _handle_completion(task, history.id, str(repository.id), remaining=[1])
 refreshed = await IndexHistory.objects.aget(id=history.id)
 assert refreshed.chunk_edges_added == 0
