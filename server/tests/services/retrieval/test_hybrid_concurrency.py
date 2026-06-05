"""HybridSearchService asyncio.gather 并发 wave 测试（per initial implementation plan）。

5 条核心断言（per ROADMAP success criterion + contract + Discretion fallback 策略）：

1. ``test_wave_0_concurrent_under_250ms`` —— rag_task + symbol_task 各 sleep 100ms
   asyncio.gather 并发 → 总耗时 < 250ms（验证真正并发）。
2. ``test_wave_started_log_emits_wave_id_zero`` —— structlog 事件
   ``hybrid_search_wave_started`` 含 ``wave_id == 0`` / ``wave_0_tasks == ["rag", "symbol"]``。
3. ``test_rag_failure_raises`` —— rag_task raise → search 传播异常（RAG 主线）。
4. ``test_symbol_failure_downgrades`` —— symbol_task raise → search 成功完成 + log
   ``symbol_task_failed`` warning + 仍走 rag 路径（图谱 enrichment 降级到空）。
5. ``test_two_tasks_started_within_5ms`` —— 用 perf_counter 记录两 task 启动时间，
   |t_rag - t_symbol| < 5ms（验证 asyncio.create_task 即刻调度）。

依赖：unittest.mock.AsyncMock + asyncio.sleep + structlog.testing.capture_logs。
不依赖真实 Embedding/Qdrant/ORM；纯 mock，目标 < 1s 跑完。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from structlog.testing import capture_logs

from services.code_intel.local_provider import LocalProvider
from services.retrieval import HybridSearchService
from services.retrieval.types import HybridSearchResult, LayerSnapshot

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _empty_snapshot() -> LayerSnapshot:
    """``search_rag`` 替身返回值：空命中（hop1 解析时退到 0 邻居路径）。"""
    return LayerSnapshot(layer="L3", status="ok", result_count=0, items=[])


async def _sleep_then_snapshot(_query: str, **_kwargs: Any) -> LayerSnapshot:
    """search_rag 替身：sleep 100ms 后返回空 snapshot。"""
    await asyncio.sleep(0.1)
    return _empty_snapshot()


async def _sleep_then_symbols(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
    """provider.lookup_symbols 替身：sleep 100ms 后返回空列表。"""
    await asyncio.sleep(0.1)
    return []


# ---------------------------------------------------------------------------
# Test 1: 并发 wall-clock < 250ms（验证真正并发）
# ---------------------------------------------------------------------------


async def test_wave_0_concurrent_under_250ms() -> None:
    """rag_task + symbol_task 各 100ms 并发 → 总耗时 < 250ms。

    若改回串行 await（先 rag 再 symbol），总耗时 ≥ 200ms + 噪声，
    通常 > 220ms；250ms 阈值留 50ms 噪声余地（CI 抖动）。
    """
    svc = HybridSearchService(LocalProvider())
    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(side_effect=_sleep_then_snapshot),
    ), patch.object(
        LocalProvider, "lookup_symbols",
        new=AsyncMock(side_effect=_sleep_then_symbols),
    ):
        start = time.perf_counter()
        result = await svc.search(
            "anything",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )
        elapsed = time.perf_counter() - start

    assert elapsed < 0.25, (
        f"asyncio.gather 并发未生效：rag+symbol 各 100ms 总耗时 {elapsed:.3f}s "
        f"超过 250ms 阈值（串行会 > 200ms）"
    )
    assert isinstance(result, HybridSearchResult)


# ---------------------------------------------------------------------------
# Test 2: hybrid_search_wave_started 日志 wave_id=0
# ---------------------------------------------------------------------------


async def test_wave_started_log_emits_wave_id_zero() -> None:
    """``hybrid_search_wave_started`` 事件 ``wave_id == 0`` 且 ``wave_0_tasks`` 含 rag/symbol。"""
    svc = HybridSearchService(LocalProvider())
    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=_empty_snapshot()),
    ), patch.object(
        LocalProvider, "lookup_symbols",
        new=AsyncMock(return_value=[]),
    ), capture_logs() as cap:
        await svc.search(
            "log probe",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )

    started_events = [e for e in cap if e.get("event") == "hybrid_search_wave_started"]
    done_events = [e for e in cap if e.get("event") == "hybrid_search_wave_done"]

    assert started_events, "未发现 hybrid_search_wave_started 日志事件"
    assert done_events, "未发现 hybrid_search_wave_done 日志事件"
    assert started_events[0].get("wave_id") == 0, (
        f"wave_id 非 0: {started_events[0]}"
    )
    assert list(started_events[0].get("wave_0_tasks") or []) == ["rag", "symbol"], (
        f"wave_0_tasks 字段错误: {started_events[0].get('wave_0_tasks')}"
    )
    assert isinstance(done_events[0].get("elapsed_ms"), int), (
        "hybrid_search_wave_done.elapsed_ms 应为 int"
    )


# ---------------------------------------------------------------------------
# Test 3: rag 失败 → 异常传播（RAG 主线必选）
# ---------------------------------------------------------------------------


async def test_rag_failure_raises() -> None:
    """search_rag raise → HybridSearchService.search 直接传播 RuntimeError。

    per Discretion："rag 失败 → 直接抛（RAG 是主线必选项）"。
    """
    svc = HybridSearchService(LocalProvider())
    boom = RuntimeError("simulated rag failure")

    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(side_effect=boom),
    ), patch.object(
        LocalProvider, "lookup_symbols",
        new=AsyncMock(return_value=[]),
    ):
        with pytest.raises(RuntimeError, match="simulated rag failure"):
            await svc.search(
                "rag-fail probe",
                repository_ids=["repo-a"],
                max_tokens=8000,
                top_k=30,
            )


# ---------------------------------------------------------------------------
# Test 4: symbol 失败 → 降级（log warning + 走 rag 路径）
# ---------------------------------------------------------------------------


async def test_symbol_failure_downgrades() -> None:
    """provider.lookup_symbols raise → search 成功完成 + log ``symbol_task_failed``。

    per Discretion："symbol 失败 → log warning + symbol_results=[] + 继续走纯
    RAG 路径"。验证三点：
    1. search 不 raise，返回 HybridSearchResult；
    2. capture_logs 含 ``symbol_task_failed`` event；
    3. hop1/hop2 邻居仍按 rag_snapshot 进行（mock rag 返回空 snapshot 所以邻居均为空）。
    """
    svc = HybridSearchService(LocalProvider())

    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=_empty_snapshot()),
    ), patch.object(
        LocalProvider, "lookup_symbols",
        new=AsyncMock(side_effect=ValueError("simulated symbol failure")),
    ), capture_logs() as cap:
        result = await svc.search(
            "symbol-fail probe",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )

    assert isinstance(result, HybridSearchResult), (
        "symbol 失败时 search 不应抛错，应降级返回 HybridSearchResult"
    )
    symbol_fail_events = [e for e in cap if e.get("event") == "symbol_task_failed"]
    assert symbol_fail_events, (
        "symbol_task 失败应记录 symbol_task_failed warning event"
    )
    assert result.hop1_neighbors == []
    assert result.hop2_neighbors == []


# ---------------------------------------------------------------------------
# Test 5: 两 task 启动时间差 < 5ms（asyncio.create_task 即刻调度）
# ---------------------------------------------------------------------------


async def test_two_tasks_started_within_5ms() -> None:
    """rag_task / symbol_task 实际进入协程函数体的时间差 < 5ms。

    用 perf_counter 在 mock 内记录每个 task 启动时间戳。asyncio.gather 创建后
    eventloop 即刻把两 task 调入运行栈，差值由 create_task 调用顺序 + Python
    解释器决定，通常 < 100µs。5ms 阈值远超实际。
    """
    started_at: dict[str, float] = {}

    async def _record_rag(*_args: Any, **_kwargs: Any) -> LayerSnapshot:
        started_at["rag"] = time.perf_counter()
        await asyncio.sleep(0.05)
        return _empty_snapshot()

    async def _record_symbol(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        started_at["symbol"] = time.perf_counter()
        await asyncio.sleep(0.05)
        return []

    svc = HybridSearchService(LocalProvider())
    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(side_effect=_record_rag),
    ), patch.object(
        LocalProvider, "lookup_symbols",
        new=AsyncMock(side_effect=_record_symbol),
    ):
        await svc.search(
            "wave-skew probe",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )

    assert "rag" in started_at and "symbol" in started_at, (
        f"未记录到 task 启动时间戳: {started_at}"
    )
    skew_ms = abs(started_at["rag"] - started_at["symbol"]) * 1000
    assert skew_ms < 5.0, (
        f"rag/symbol task 启动时间差 {skew_ms:.3f}ms 超过 5ms 阈值（asyncio.gather"
        f"应即刻调度两 task）"
    )
