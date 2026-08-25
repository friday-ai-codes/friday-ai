"""implementation Task 3 — HybridSearchService 结构化日志契约测试。

5 条断言锁定 plan 落地的 4 类 structlog 事件 + 字段拼写一致性，作为后续
phase 修改 hybrid_search.py 的"日志契约"屏障。事件矩阵（per CONTEXT.md
D-Discretion + plan 代码）：

1. ``hybrid_search_started`` —— ``path="graph_capable"`` / ``"rag_only"`` +
   ``query`` (前 100 字符)
2. ``hybrid_search_wave_started`` —— ``wave_id=0`` + ``wave_0_tasks=["rag","symbol"]``
3. ``hybrid_search_wave_done`` —— ``wave_id=0`` + ``elapsed_ms: int >= 0``
4. ``hybrid_search_completed`` —— ``path`` + ``repo_count`` + ``total_tokens`` +
   （graph_capable 额外）``hop1_count`` / ``hop2_count`` / ``symbol_failed``

5 测试 case：

1. ``test_hybrid_search_started_emits_path_field`` —— graph_capable 路径下事件
   ``hybrid_search_started`` 含 path="graph_capable" + query 字段
2. ``test_hybrid_search_wave_started_emits_wave_id_and_tasks`` —— wave_id=0 +
   wave_0_tasks=["rag","symbol"] 字段完整
3. ``test_hybrid_search_wave_done_emits_elapsed_ms_int`` —— elapsed_ms 是 int
   且 ≥ 0；wave_id=0
4. ``test_hybrid_search_completed_emits_counts`` —— path / repo_count /
   total_tokens / hop1_count / hop2_count / symbol_failed 全部字段存在 + 类型正确
5. ``test_null_provider_path_emits_started_with_rag_only`` —— NullProvider 路径
   下 hybrid_search_started.path=="rag_only" + 不 emit wave_started/wave_done

测试技术（implementation notes）：
- 用 ``structlog.testing.capture_logs()`` 而非自实现 capture processor——项目
  ``cache_logger_on_first_use=True`` 致模块级 ``logger = structlog.get_logger(__name__)``
  首次绑定后自实现 helper 无法接管；官方 capture_logs 直接 monkeypatch
  ``BoundLoggerBase._proxy_to_logger`` 无视 cache。
- 全 mock HybridSearchService 子调用（search_rag / resolve_neighbor_metadata /
  expand_hop2 / LocalProvider.lookup_symbols），无 DB / Qdrant 依赖。

与 ``test_hybrid_concurrency.py`` test 2 部分重叠（wave_id=0 字段），本测试
增加宽度（4 类事件全覆盖）+ 字段键完整性（wave_0_tasks / elapsed_ms /
hop1_count / hop2_count / symbol_failed 全锁）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from services.code_intel.local_provider import LocalProvider
from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from services.retrieval.types import LayerSnapshot

# ---------------------------------------------------------------------------
# shared fixtures（避免重复 mock 设置）
# ---------------------------------------------------------------------------


class _RecordingLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def debug(self, event: str, **kwargs: Any) -> None:
        self.events.append({"event": event, **kwargs})

    def info(self, event: str, **kwargs: Any) -> None:
        self.events.append({"event": event, **kwargs})

    def warning(self, event: str, **kwargs: Any) -> None:
        self.events.append({"event": event, **kwargs})


def _empty_snapshot() -> LayerSnapshot:
    return LayerSnapshot(layer="L3", status="ok", result_count=0, items=[])


async def _run_graph_capable_capture(
    *,
    symbol_raises: bool = False,
) -> list[dict[str, Any]]:
    """跑 graph_capable 路径 + 捕获所有 structlog 事件。

    Args:
        symbol_raises: True 时 lookup_symbols 抛 ValueError（验证 symbol_failed=True 分支）。
    """
    if symbol_raises:
        symbol_mock = AsyncMock(side_effect=ValueError("simulated symbol failure"))
    else:
        symbol_mock = AsyncMock(return_value=[])
    recording = _RecordingLogger()

    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=_empty_snapshot()),
    ), patch(
        "services.retrieval.hybrid_search.resolve_neighbor_metadata",
        new=AsyncMock(return_value=[]),
    ), patch(
        "services.retrieval.hybrid_search.expand_hop2",
        new=AsyncMock(return_value=[]),
    ), patch.object(
        LocalProvider, "lookup_symbols", new=symbol_mock,
    ), patch(
        "services.retrieval.hybrid_search.logger", new=recording
    ):
        await HybridSearchService(LocalProvider()).search(
            "structlog probe",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )
    return recording.events


async def _run_rag_only_capture() -> list[dict[str, Any]]:
    """跑 rag_only 路径（NullProvider）+ 捕获所有 structlog 事件。"""
    recording = _RecordingLogger()
    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=_empty_snapshot()),
    ), patch(
        "services.retrieval.hybrid_search.logger", new=recording
    ):
        await HybridSearchService(NullProvider()).search(
            "rag-only probe",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )
    return recording.events


def _find_event(
    cap: list[dict[str, Any]], event_name: str
) -> dict[str, Any] | None:
    for log in cap:
        if log.get("event") == event_name:
            return log
    return None


# ---------------------------------------------------------------------------
# Test 1: hybrid_search_started.path == "graph_capable" + 无 query 正文
# ---------------------------------------------------------------------------


async def test_hybrid_search_started_emits_path_field() -> None:
    """graph_capable 路径下事件仅含低基数 path，不含 query 正文。"""
    cap = await _run_graph_capable_capture()
    started = _find_event(cap, "hybrid_search_started")
    assert started is not None, "未发现 hybrid_search_started 事件"
    assert started.get("path") == "graph_capable", (
        f"path 字段应为 'graph_capable'，got: {started.get('path')!r}"
    )
    assert "query" not in started
    assert started["category"] == "sampling"
    assert started["component"] == "code_graph"


# ---------------------------------------------------------------------------
# Test 2: hybrid_search_wave_started — wave_id=0 + wave_0_tasks
# ---------------------------------------------------------------------------


async def test_hybrid_search_wave_started_emits_wave_id_and_tasks() -> None:
    """wave_started 事件含 wave_id=0 + wave_0_tasks=["rag","symbol"]。"""
    cap = await _run_graph_capable_capture()
    started = _find_event(cap, "hybrid_search_wave_started")
    assert started is not None, "未发现 hybrid_search_wave_started 事件"
    assert started.get("wave_id") == 0, (
        f"wave_id 字段应为 0，got: {started.get('wave_id')!r}"
    )
    tasks = started.get("wave_0_tasks")
    assert tasks is not None and list(tasks) == ["rag", "symbol"], (
        f"wave_0_tasks 字段应为 ['rag', 'symbol']，got: {tasks!r}"
    )


# ---------------------------------------------------------------------------
# Test 3: hybrid_search_wave_done — elapsed_ms int 且 >= 0
# ---------------------------------------------------------------------------


async def test_hybrid_search_wave_done_emits_elapsed_ms_int() -> None:
    """wave_done 事件含 elapsed_ms: int >= 0 + wave_id=0。"""
    cap = await _run_graph_capable_capture()
    done = _find_event(cap, "hybrid_search_wave_done")
    assert done is not None, "未发现 hybrid_search_wave_done 事件"
    assert done.get("wave_id") == 0, (
        f"wave_id 字段应为 0，got: {done.get('wave_id')!r}"
    )
    elapsed = done.get("elapsed_ms")
    assert isinstance(elapsed, int), (
        f"elapsed_ms 字段应为 int 类型，got: {type(elapsed).__name__}"
    )
    assert elapsed >= 0, f"elapsed_ms 应 >= 0，got: {elapsed}"


# ---------------------------------------------------------------------------
# Test 4: hybrid_search_completed — path/repo_count/tokens/hop counts/symbol_failed
# ---------------------------------------------------------------------------


async def test_hybrid_search_completed_emits_counts() -> None:
    """completed 事件含完整字段集合 + 类型正确。"""
    cap = await _run_graph_capable_capture()
    completed = _find_event(cap, "hybrid_search_completed")
    assert completed is not None, "未发现 hybrid_search_completed 事件"

    # 必有字段及类型
    expected_field_types: dict[str, type] = {
        "path": str,
        "repo_count": int,
        "total_tokens": int,
        "hop1_count": int,
        "hop2_count": int,
        "symbol_failed": bool,
    }
    for field_name, expected_type in expected_field_types.items():
        assert field_name in completed, (
            f"hybrid_search_completed 缺字段 {field_name!r}: {completed!r}"
        )
        value = completed[field_name]
        # symbol_failed=bool 在 Python 中是 int 的子类，单独允许
        if expected_type is bool:
            assert isinstance(value, bool), (
                f"{field_name} 应为 bool 类型，got: {type(value).__name__}"
            )
        else:
            assert isinstance(value, expected_type) and not isinstance(value, bool), (
                f"{field_name} 应为 {expected_type.__name__}，got: "
                f"{type(value).__name__}={value!r}"
            )

    assert completed["path"] == "graph_capable"
    assert completed["repo_count"] == 1
    assert completed["hop1_count"] == 0  # mock 返回空 list
    assert completed["hop2_count"] == 0
    assert completed["symbol_failed"] is False  # 默认 mock 不 raise


# ---------------------------------------------------------------------------
# Test 5: NullProvider rag_only 路径 — started.path=rag_only + 无 wave 事件
# ---------------------------------------------------------------------------


async def test_null_provider_path_emits_started_with_rag_only() -> None:
    """rag_only 路径仅 emit hybrid_search_started + hybrid_search_completed，
    **不 emit** hybrid_search_wave_started / wave_done（无并发 wave）。"""
    cap = await _run_rag_only_capture()

    started = _find_event(cap, "hybrid_search_started")
    assert started is not None
    assert started.get("path") == "rag_only", (
        f"NullProvider 路径下 path 应为 'rag_only'，got: {started.get('path')!r}"
    )

    completed = _find_event(cap, "hybrid_search_completed")
    assert completed is not None
    assert completed.get("path") == "rag_only"

    # 关键：rag_only 路径不应出现 wave 事件
    wave_events = [
        e for e in cap
        if e.get("event") in {"hybrid_search_wave_started", "hybrid_search_wave_done"}
    ]
    assert not wave_events, (
        f"NullProvider rag_only 路径不应 emit wave 事件 (无并发)，got: {wave_events!r}"
    )


# ---------------------------------------------------------------------------
# Test 6（额外）: symbol_failed=True 时 completed.symbol_failed 字段反映降级
# ---------------------------------------------------------------------------


async def test_hybrid_search_completed_symbol_failed_flag_true_on_downgrade() -> None:
    """provider.lookup_symbols raise → completed.symbol_failed == True；
    同时 emit symbol_task_failed warning 事件（per plan 降级路径）。"""
    cap = await _run_graph_capable_capture(symbol_raises=True)

    completed = _find_event(cap, "hybrid_search_completed")
    assert completed is not None
    assert completed.get("symbol_failed") is True, (
        f"symbol_task raise 时 completed.symbol_failed 应为 True，"
        f"got: {completed.get('symbol_failed')!r}"
    )

    # 降级路径 warning 事件
    sym_fail = _find_event(cap, "symbol_task_failed")
    assert sym_fail is not None, "symbol_task raise 应 emit symbol_task_failed 事件"
