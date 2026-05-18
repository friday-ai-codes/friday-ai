"""Phase Plan — indexer 双重判断 + IndexHistory.graph_build_status=SKIPPED 测试。
覆盖 GRAPH- / GRAPH-：
- `IndexerService._should_build_graph(history_id)` helper：
 双重判断 `settings.ENABLE_CODEGRAPH AND repository.auto_build_graph_enabled`，
 false 时 → return False + 写 `IndexHistory.graph_build_status=SKIPPED` + structlog
 事件 `graph_build_skipped`（reason ∈ {auto_build_graph_disabled, feature_flag_disabled}）。
- 4 处 callsite（line 874 全量 / 1129 branch overlay / 1512 git_diff / 1819 incremental）
 必须在 `_extract_and_write_graph` 之前 gating `_should_build_graph` 判断；
 用 `inspect.getsource(...)` regex 检查源码结构（白盒断言）。
- history_id 为 None 时只 log warn 不抛——沿用 hook 风格的异常隔离。
"""
from __future__ import annotations
import inspect
import re
import uuid
import pytest
import structlog
from asgiref.sync import sync_to_async
from repositories.models import (
 GraphBuildStatus,
 IndexHistory,
 IndexHistoryStatus,
 Repository,
)
from services.indexer import IndexerService
# ---------------------------------------------------------------------------
# _should_build_graph 行为单测（GRAPH- / GRAPH-）
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_should_build_graph_returns_true_when_both_flags_enabled(
 repository: Repository, settings
) -> None:
 """双重判断 true → return True，不写 IndexHistory，不发跳过事件。"""
 settings.ENABLE_CODEGRAPH = True
 repository.auto_build_graph_enabled = True
 await sync_to_async(repository.save)(update_fields=["auto_build_graph_enabled"])
 history = await sync_to_async(IndexHistory.objects.create)(
 repository=repository,
 status=IndexHistoryStatus.RUNNING,
 graph_build_status=GraphBuildStatus.PENDING,
 )
 idx = IndexerService(str(repository.id))
 with structlog.testing.capture_logs as caps:
 result = await idx._should_build_graph(str(history.id))
 assert result is True
 await sync_to_async(history.refresh_from_db)
 assert history.graph_build_status == GraphBuildStatus.PENDING
 skip_events = [c for c in caps if c.get("event") == "graph_build_skipped"]
 assert skip_events ==
@pytest.mark.django_db(transaction=True)
async def test_should_build_graph_skips_when_repo_flag_false(
 repository: Repository, settings
) -> None:
 """repo.auto_build_graph_enabled=False → return False + SKIPPED + 事件 reason."""
 settings.ENABLE_CODEGRAPH = True
 repository.auto_build_graph_enabled = False
 await sync_to_async(repository.save)(update_fields=["auto_build_graph_enabled"])
 history = await sync_to_async(IndexHistory.objects.create)(
 repository=repository,
 status=IndexHistoryStatus.RUNNING,
 graph_build_status=GraphBuildStatus.PENDING,
 )
 idx = IndexerService(str(repository.id))
 with structlog.testing.capture_logs as caps:
 result = await idx._should_build_graph(str(history.id))
 assert result is False
 await sync_to_async(history.refresh_from_db)
 assert history.graph_build_status == GraphBuildStatus.SKIPPED
 skip_events = [c for c in caps if c.get("event") == "graph_build_skipped"]
 assert len(skip_events) == 1
 assert skip_events[0].get("reason") == "auto_build_graph_disabled"
 assert skip_events[0].get("repository_id") == str(repository.id)
@pytest.mark.django_db(transaction=True)
async def test_should_build_graph_skips_when_global_flag_false(
 repository: Repository, settings
) -> None:
 """settings.ENABLE_CODEGRAPH=False → return False + SKIPPED + 事件 reason."""
 settings.ENABLE_CODEGRAPH = False
 repository.auto_build_graph_enabled = True
 await sync_to_async(repository.save)(update_fields=["auto_build_graph_enabled"])
 history = await sync_to_async(IndexHistory.objects.create)(
 repository=repository,
 status=IndexHistoryStatus.RUNNING,
 graph_build_status=GraphBuildStatus.PENDING,
 )
 idx = IndexerService(str(repository.id))
 with structlog.testing.capture_logs as caps:
 result = await idx._should_build_graph(str(history.id))
 assert result is False
 await sync_to_async(history.refresh_from_db)
 assert history.graph_build_status == GraphBuildStatus.SKIPPED
 skip_events = [c for c in caps if c.get("event") == "graph_build_skipped"]
 assert len(skip_events) == 1
 assert skip_events[0].get("reason") == "feature_flag_disabled"
@pytest.mark.django_db(transaction=True)
async def test_should_build_graph_global_flag_takes_precedence(
 repository: Repository, settings
) -> None:
 """两个 flag 都 false 时 global flag 优先（feature_flag_disabled）。"""
 settings.ENABLE_CODEGRAPH = False
 repository.auto_build_graph_enabled = False
 await sync_to_async(repository.save)(update_fields=["auto_build_graph_enabled"])
 history = await sync_to_async(IndexHistory.objects.create)(
 repository=repository,
 status=IndexHistoryStatus.RUNNING,
 graph_build_status=GraphBuildStatus.PENDING,
 )
 idx = IndexerService(str(repository.id))
 with structlog.testing.capture_logs as caps:
 result = await idx._should_build_graph(str(history.id))
 assert result is False
 skip_events = [c for c in caps if c.get("event") == "graph_build_skipped"]
 assert len(skip_events) == 1
 assert skip_events[0].get("reason") == "feature_flag_disabled"
@pytest.mark.django_db(transaction=True)
async def test_should_build_graph_handles_missing_history_id(
 repository: Repository, settings
) -> None:
 """history_id=None + flag false → 仍 return False，不抛异常。"""
 settings.ENABLE_CODEGRAPH = False
 idx = IndexerService(str(repository.id))
 with structlog.testing.capture_logs as caps:
 result = await idx._should_build_graph(None)
 assert result is False
 skip_events = [c for c in caps if c.get("event") == "graph_build_skipped"]
 assert len(skip_events) == 1
 assert skip_events[0].get("reason") == "feature_flag_disabled"
 assert skip_events[0].get("history_id") is None
@pytest.mark.django_db(transaction=True)
async def test_skip_byte_equivalent_main_track_unaffected(
 repository: Repository, settings
) -> None:
 """跳过图谱时 ChunkEdge / FileIndex 写入与不跳过时一致（仅图谱三件套行数为 0）。
 本测试只验证 `_should_build_graph` 写 SKIPPED 后主轨数据未被污染——
 断言 ChunkEdge / Symbol / ImportEdge / Endpoint 在 _should_build_graph 调用
 前后均为 0（helper 自身只 update IndexHistory 一行，不应写其他表）。
 """
 from code_relations.models import ChunkEdge
 from codegraph.models import Endpoint, ImportEdge, Symbol
 settings.ENABLE_CODEGRAPH = True
 repository.auto_build_graph_enabled = False
 await sync_to_async(repository.save)(update_fields=["auto_build_graph_enabled"])
 history = await sync_to_async(IndexHistory.objects.create)(
 repository=repository,
 status=IndexHistoryStatus.RUNNING,
 graph_build_status=GraphBuildStatus.PENDING,
 )
 idx = IndexerService(str(repository.id))
 result = await idx._should_build_graph(str(history.id))
 assert result is False
 assert (
 await sync_to_async(
 ChunkEdge.objects.filter(repository_id=repository.id).count
 )
 == 0
 )
 assert (
 await sync_to_async(
 Symbol.objects.filter(repository_id=str(repository.id)).count
 )
 == 0
 )
 assert (
 await sync_to_async(
 ImportEdge.objects.filter(repository_id=str(repository.id)).count
 )
 == 0
 )
 assert (
 await sync_to_async(
 Endpoint.objects.filter(repository_id=str(repository.id)).count
 )
 == 0
 )
 await sync_to_async(repository.refresh_from_db)
 # _should_build_graph 不动 Repository.index_status，沿用主流程现有状态
 # （indexer 主路径已在 persist_vector_track_complete 写过 INDEXED）。
# ---------------------------------------------------------------------------
# 4 callsite 白盒结构断言（GRAPH- 必含 4 处 callsite gating）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
 "method_name",
 [
 "run_full_index",
 "run_branch_index",
 "run_git_diff_index",
 "run_incremental_index",
 ],
)
def test_callsite_gated_by_should_build_graph(method_name: str) -> None:
 """4 处 callsite 必须在 `await self._extract_and_write_graph(...)` 之前
 出现 `await self._should_build_graph(...)`（白盒源码 regex 检查）。
 """
 method = getattr(IndexerService, method_name)
 src = inspect.getsource(method)
 extract_call_idx = src.find("await self._extract_and_write_graph(")
 assert extract_call_idx >= 0, (
 f"{method_name} 未调用 _extract_and_write_graph（callsite 应存在）"
 )
 pre_segment = src[:extract_call_idx]
 assert "_should_build_graph" in pre_segment, (
 f"{method_name} 缺少 _should_build_graph gating —— "
 f"callsite 必须以 `if await self._should_build_graph(...)` 包装"
 )
def test_should_build_graph_helper_signature_exists -> None:
 """`IndexerService._should_build_graph` 必须存在且为 async 方法。"""
 assert hasattr(IndexerService, "_should_build_graph"), (
 "IndexerService 缺少 _should_build_graph helper"
 )
 method = IndexerService._should_build_graph
 assert inspect.iscoroutinefunction(method), (
 "_should_build_graph 必须是 async 方法（async def）"
 )
 sig = inspect.signature(method)
 params = list(sig.parameters.keys)
 assert params[0] == "self"
 assert "history_id" in params, "_should_build_graph 缺少 history_id 形参"
def test_indexer_imports_graph_build_status -> None:
 """indexer.py 必须 import GraphBuildStatus（写 SKIPPED 所需）。"""
 import services.indexer as indexer_module
 src = inspect.getsource(indexer_module)
 assert re.search(r"GraphBuildStatus", src), (
 "indexer.py 缺少 GraphBuildStatus 引用（写 SKIPPED 所需）"
 )
def test_skip_event_name_used_in_indexer -> None:
 """indexer.py 中至少有一处 `graph_build_skipped` 事件 + 两个 reason 字面量。"""
 import services.indexer as indexer_module
 src = inspect.getsource(indexer_module)
 assert "graph_build_skipped" in src, (
 "indexer.py 缺少 `graph_build_skipped` structlog 事件名"
 )
 assert "auto_build_graph_disabled" in src
 assert "feature_flag_disabled" in src
# ---------------------------------------------------------------------------
# tail-noise：确保 structlog event 不污染其他 reason 字面量
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_skip_event_does_not_mention_invalid_reason(
 repository: Repository, settings
) -> None:
 """跳过事件 reason 字段只允许 {auto_build_graph_disabled, feature_flag_disabled}。"""
 settings.ENABLE_CODEGRAPH = True
 repository.auto_build_graph_enabled = False
 await sync_to_async(repository.save)(update_fields=["auto_build_graph_enabled"])
 history_id = str(uuid.uuid4)
 # 故意不创建 IndexHistory 行，模拟 fallback "找不到" 场景 —— 不应抛
 idx = IndexerService(str(repository.id))
 with structlog.testing.capture_logs as caps:
 result = await idx._should_build_graph(history_id)
 assert result is False
 skip_events = [c for c in caps if c.get("event") == "graph_build_skipped"]
 assert len(skip_events) == 1
 assert skip_events[0]["reason"] in {
 "auto_build_graph_disabled",
 "feature_flag_disabled",
 }
