"""Phase Plan — `services/graph_builder.py` 顶层服务单元测试。
覆盖 GRAPH- + GRAPH-：
1. `GraphBuildResult` dataclass 形态（frozen + 10 字段位齐全）
2. `build_graph_for_repository` API 签名（async + keyword-only trigger / history_id）
3. 正常路径（manual trigger）：history 自创建 RUNNING → COMPLETED + counts 落字段
4. 已有 history_id 复用（不重复创建行）
5. `adelete_for_files` 在 `_extract_and_write_graph` 之前调用（孤儿前置删除）
6. 异常路径：薄壳 raise → history.status=FAILED + error_message 截断 ≤ 1000 + 透传 raise
7. structlog 事件契约：`graph_build_started` / `graph_build_completed` / `graph_build_failed`
8. 等价：manual 与 auto_after_index 触发产物计数完全一致
测试策略：mock `IndexerService._extract_and_write_graph` 返回固定 stats，避免拉
真实 tree-sitter / Qdrant / git。`adelete_for_files` 用 AsyncMock spy 验证调用顺序与
入参；structlog 用 `capture_logs` 上下文捕获事件。
"""
from __future__ import annotations
import dataclasses
import inspect
from typing import Any
from unittest.mock import AsyncMock, patch
import pytest
import structlog
from asgiref.sync import sync_to_async
from repositories.models import (
 FileIndex,
 GraphBuildHistory,
 GraphBuildHistoryStatus,
 GraphBuildHistoryTrigger,
 Repository,
)
# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def graph_repo(db) -> Repository:
 """创建一个空 Repository fixture（不依赖 conftest 内 throttle/cache fixture 链）。"""
 return Repository.objects.create(
 name="graph-builder-test-repo",
 git_url="https://example.com/graph-builder-test.git",
 default_branch="main",
 )
@pytest.fixture
def graph_repo_with_files(graph_repo: Repository) -> Repository:
 """预填 3 行 FileIndex 模拟"已索引仓库"。"""
 FileIndex.objects.bulk_create([
 FileIndex(
 repository=graph_repo,
 file_path=f"src/module_{i}.py",
 file_hash=f"hash{i:040x}",
 )
 for i in range(3)
 ])
 return graph_repo
@pytest.fixture
def fake_extract_stats -> dict[str, Any]:
 """模拟 `_extract_and_write_graph` 成功返回值。"""
 return {
 "files_processed": 3,
 "files_failed": 0,
 "total_symbols": 7,
 "total_imports": 4,
 "total_calls": 5,
 "total_endpoints": 0,
 }
# ---------------------------------------------------------------------------
# 1. GraphBuildResult dataclass 形态
# ---------------------------------------------------------------------------
def test_result_is_frozen_dataclass_with_ten_fields -> None:
 """`GraphBuildResult` 必须是 frozen dataclass，含 must_haves 列出的 10 字段位。"""
 from services.graph_builder import GraphBuildResult
 assert dataclasses.is_dataclass(GraphBuildResult)
 assert GraphBuildResult.__dataclass_params__.frozen is True
 field_names = {f.name for f in dataclasses.fields(GraphBuildResult)}
 expected = {
 "status",
 "files_total",
 "files_processed",
 "files_failed",
 "symbols_count",
 "imports_count",
 "calls_count",
 "endpoints_count",
 "duration_seconds",
 "error_message",
 }
 assert expected.issubset(field_names), (
 f"GraphBuildResult 缺少字段：{expected - field_names}"
 )
# ---------------------------------------------------------------------------
# 2. build_graph_for_repository API 签名
# ---------------------------------------------------------------------------
def test_build_graph_for_repository_is_async_keyword_only -> None:
 """`build_graph_for_repository` 必须 async + `trigger` / `history_id` 均为 KEYWORD_ONLY。"""
 from services.graph_builder import build_graph_for_repository
 assert inspect.iscoroutinefunction(build_graph_for_repository)
 sig = inspect.signature(build_graph_for_repository)
 params = sig.parameters
 assert "repository_id" in params
 assert "trigger" in params
 assert "history_id" in params
 assert params["trigger"].kind is inspect.Parameter.KEYWORD_ONLY
 assert params["history_id"].kind is inspect.Parameter.KEYWORD_ONLY
 assert params["history_id"].default is None
# ---------------------------------------------------------------------------
# 3. 正常路径（manual trigger）— history 自创建 + COMPLETED + counts
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_manual_trigger_creates_running_history_then_completes(
 graph_repo_with_files: Repository,
 fake_extract_stats: dict[str, Any],
) -> None:
 """trigger='manual' + history_id=None → service 自创建 RUNNING 行 → 转 COMPLETED 落计数。"""
 from services.graph_builder import build_graph_for_repository
 from services.indexer import IndexerService
 repo_id = str(graph_repo_with_files.id)
 with patch.object(
 IndexerService,
 "_extract_and_write_graph",
 new_callable=AsyncMock,
 return_value=fake_extract_stats,
 ):
 result = await build_graph_for_repository(repo_id, trigger="manual")
 histories = await sync_to_async(list)(
 GraphBuildHistory.objects.filter(repository_id=repo_id)
 )
 assert len(histories) == 1
 h = histories[0]
 assert h.trigger_type == GraphBuildHistoryTrigger.MANUAL
 assert h.status == GraphBuildHistoryStatus.COMPLETED
 assert h.symbols_count == 7
 assert h.imports_count == 4
 assert h.calls_count == 5
 assert h.endpoints_count == 0
 assert h.files_processed == 3
 assert h.finished_at is not None
 assert result.status == GraphBuildHistoryStatus.COMPLETED
 assert result.symbols_count == 7
@pytest.mark.django_db(transaction=True)
async def test_existing_history_id_reused(
 graph_repo_with_files: Repository,
 fake_extract_stats: dict[str, Any],
) -> None:
 """history_id 显式传入时复用已存在行，不创建新 row。"""
 from services.graph_builder import build_graph_for_repository
 from services.indexer import IndexerService
 repo_id = str(graph_repo_with_files.id)
 pre = await sync_to_async(GraphBuildHistory.objects.create)(
 repository=graph_repo_with_files,
 trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX,
 status=GraphBuildHistoryStatus.RUNNING,
 )
 with patch.object(
 IndexerService,
 "_extract_and_write_graph",
 new_callable=AsyncMock,
 return_value=fake_extract_stats,
 ):
 await build_graph_for_repository(
 repo_id,
 trigger="auto_after_index",
 history_id=str(pre.id),
 )
 total = await sync_to_async(
 GraphBuildHistory.objects.filter(repository_id=repo_id).count,
 )
 assert total == 1
 await sync_to_async(pre.refresh_from_db)
 assert pre.status == GraphBuildHistoryStatus.COMPLETED
 assert pre.symbols_count == 7
 assert pre.trigger_type == GraphBuildHistoryTrigger.AUTO_AFTER_INDEX
# ---------------------------------------------------------------------------
# 4. adelete_for_files 前置删除
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_adelete_for_files_called_before_extract(
 graph_repo_with_files: Repository,
 fake_extract_stats: dict[str, Any],
) -> None:
 """`GraphWriter.adelete_for_files` 必须在 `_extract_and_write_graph` 之前调用，
 并传入仓库的全量 file_path 列表。
 """
 from codegraph.services.graph_writer import GraphWriter
 from services.graph_builder import build_graph_for_repository
 from services.indexer import IndexerService
 repo_id = str(graph_repo_with_files.id)
 call_order: list[str] =
 async def _adelete_spy(self: Any, *args: Any, **kwargs: Any) -> int:
 call_order.append(f"adelete:{args}")
 return 0
 async def _extract_spy(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
 call_order.append("extract")
 return fake_extract_stats
 with (
 patch.object(GraphWriter, "adelete_for_files", new=_adelete_spy),
 patch.object(IndexerService, "_extract_and_write_graph", new=_extract_spy),
 ):
 await build_graph_for_repository(repo_id, trigger="manual")
 adelete_idx = next(
 (i for i, e in enumerate(call_order) if e.startswith("adelete:")),
 -1,
 )
 extract_idx = next((i for i, e in enumerate(call_order) if e == "extract"), -1)
 assert adelete_idx >= 0, "adelete_for_files 未被调用"
 assert extract_idx >= 0, "_extract_and_write_graph 未被调用"
 assert adelete_idx < extract_idx, (
 f"adelete_for_files 必须在 _extract_and_write_graph 之前调用，"
 f"实际顺序：{call_order}"
 )
 adelete_call_str = call_order[adelete_idx]
 for i in range(3):
 assert f"src/module_{i}.py" in adelete_call_str, (
 f"adelete_for_files 缺少全量 file_path，实际入参：{adelete_call_str}"
 )
# ---------------------------------------------------------------------------
# 5. 异常路径：FAILED + error_message 截断 + raise
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_extract_failure_marks_history_failed_and_raises(
 graph_repo_with_files: Repository,
) -> None:
 """`_extract_and_write_graph` 抛 → history 转 FAILED，error_message 截断 1000，异常透传。"""
 from services.graph_builder import build_graph_for_repository
 from services.indexer import IndexerService
 repo_id = str(graph_repo_with_files.id)
 long_msg = "boom" + ("X" * 5000)
 with patch.object(
 IndexerService,
 "_extract_and_write_graph",
 new_callable=AsyncMock,
 side_effect=RuntimeError(long_msg),
 ):
 with pytest.raises(RuntimeError):
 await build_graph_for_repository(repo_id, trigger="manual")
 histories = await sync_to_async(list)(
 GraphBuildHistory.objects.filter(repository_id=repo_id)
 )
 assert len(histories) == 1
 h = histories[0]
 assert h.status == GraphBuildHistoryStatus.FAILED
 assert h.error_message.startswith("boom")
 assert len(h.error_message) <= 1000
 assert h.finished_at is not None
# ---------------------------------------------------------------------------
# 6. structlog 事件契约
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_structlog_events_emitted(
 graph_repo_with_files: Repository,
 fake_extract_stats: dict[str, Any],
) -> None:
 """成功路径：发 graph_build_started + graph_build_completed，含核心字段。"""
 from services.graph_builder import build_graph_for_repository
 from services.indexer import IndexerService
 repo_id = str(graph_repo_with_files.id)
 with patch.object(
 IndexerService,
 "_extract_and_write_graph",
 new_callable=AsyncMock,
 return_value=fake_extract_stats,
 ):
 with structlog.testing.capture_logs as caps:
 await build_graph_for_repository(repo_id, trigger="manual")
 started = [c for c in caps if c.get("event") == "graph_build_started"]
 completed = [c for c in caps if c.get("event") == "graph_build_completed"]
 assert started, f"缺少 graph_build_started 事件，实际：{caps}"
 assert completed, f"缺少 graph_build_completed 事件，实际：{caps}"
 s = started[0]
 assert s.get("repository_id") == repo_id
 assert s.get("trigger") == "manual"
 assert "history_id" in s
 c = completed[0]
 assert c.get("repository_id") == repo_id
 assert c.get("trigger") == "manual"
 assert "history_id" in c
 assert "duration_seconds" in c
 assert c.get("symbols_count") == 7
@pytest.mark.django_db(transaction=True)
async def test_structlog_failed_event_on_exception(
 graph_repo_with_files: Repository,
) -> None:
 """失败路径：发 graph_build_failed 事件并含 error 字段。"""
 from services.graph_builder import build_graph_for_repository
 from services.indexer import IndexerService
 repo_id = str(graph_repo_with_files.id)
 with patch.object(
 IndexerService,
 "_extract_and_write_graph",
 new_callable=AsyncMock,
 side_effect=RuntimeError("boom"),
 ):
 with structlog.testing.capture_logs as caps:
 with pytest.raises(RuntimeError):
 await build_graph_for_repository(repo_id, trigger="manual")
 failed = [c for c in caps if c.get("event") == "graph_build_failed"]
 assert failed, f"缺少 graph_build_failed 事件，实际：{caps}"
 f = failed[0]
 assert "boom" in str(f.get("error", ""))
 assert f.get("repository_id") == repo_id
# ---------------------------------------------------------------------------
# 7.：manual 与 auto_after_index 产物等价
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
async def test_manual_and_auto_after_index_produce_equivalent_history_counts(
 graph_repo_with_files: Repository,
 fake_extract_stats: dict[str, Any],
) -> None:
 """ROADMAP：相同抽取产物下，manual 与 auto_after_index 触发的 history 计数完全相等。"""
 from services.graph_builder import build_graph_for_repository
 from services.indexer import IndexerService
 repo_id = str(graph_repo_with_files.id)
 with patch.object(
 IndexerService,
 "_extract_and_write_graph",
 new_callable=AsyncMock,
 return_value=fake_extract_stats,
 ):
 await build_graph_for_repository(repo_id, trigger="manual")
 pre_auto = await sync_to_async(GraphBuildHistory.objects.create)(
 repository=graph_repo_with_files,
 trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX,
 status=GraphBuildHistoryStatus.RUNNING,
 )
 await build_graph_for_repository(
 repo_id,
 trigger="auto_after_index",
 history_id=str(pre_auto.id),
 )
 histories = await sync_to_async(
 lambda: list(
 GraphBuildHistory.objects.filter(repository_id=repo_id).order_by(
 "started_at",
 )
 )
 )
 assert len(histories) == 2
 manual_h = next(h for h in histories if h.trigger_type == GraphBuildHistoryTrigger.MANUAL)
 auto_h = next(
 h for h in histories if h.trigger_type == GraphBuildHistoryTrigger.AUTO_AFTER_INDEX
 )
 fields_to_compare = (
 "files_processed",
 "symbols_count",
 "imports_count",
 "calls_count",
 "endpoints_count",
 )
 for field in fields_to_compare:
 assert getattr(manual_h, field) == getattr(auto_h, field), (
 f"manual 与 auto_after_index 在 {field} 上不一致："
 f"manual={getattr(manual_h, field)}, auto={getattr(auto_h, field)}"
 )
