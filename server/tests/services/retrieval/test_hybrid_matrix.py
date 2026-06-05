"""HybridSearchService matrix 路径覆盖 —— per implementation / work item。

3 条聚焦于 NullProvider 路径核心 path（rag_only 短路 / max_tokens 裁剪 / 空 query
兜底），与 implementation 既有 ``test_null_provider_paths.py`` 5 条形成 "基础行为 +
能力契约 + 编排路径" 三层覆盖。

函数名直接带 ``_null_provider`` 后缀（requirements 保险方案），不依赖
parametrize ID 即可被 ``pytest -k null_provider --co`` 收集（success criterion
字面要求 "≥10"）。

mock 模式完全沿用 ``test_null_provider_paths.py``：仅 patch
``services.retrieval.hybrid_search.search_rag`` 模块级 import；不依赖真实
ORM / Qdrant / Embedding。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from services.retrieval.types import LayerSnapshot


def _l3_item(file_path: str, content: str, score: float = 0.85) -> dict[str, Any]:
    """L3 命中 item，与 ``_format_l3_section`` 期望的 payload key 对齐。"""
    return {
        "score": score,
        "payload": {
            "file_path": file_path,
            "content": content,
            "language": "python",
            "chunk_index": 0,
            "start_line": 1,
            "end_line": 20,
            "repository_id": "repo-a",
        },
    }


def _make_l3_snapshot(items: list[dict[str, Any]]) -> LayerSnapshot:
    """``search_rag`` 返回值替身：固定 L3 LayerSnapshot。"""
    return LayerSnapshot(
        layer="L3", status="ok", result_count=len(items), items=items,
    )


# ---------------------------------------------------------------------------
# Test 1: rag_only path 渲染 L3 markdown
# ---------------------------------------------------------------------------


async def test_search_rag_only_path_for_null_provider() -> None:
    """``HybridSearchService(NullProvider()).search`` → final_context 含
    ``## L3 Related Code`` 段（rag_only 路径）。

    覆盖 plan must_have "关键 path 用 matrix fixture：HybridSearchService.search × 3"
    第一条；与 ``test_null_provider_paths.test_case_1_null_provider_returns_pure_rag``
    互补——本测试聚焦"rag_only 路径产物 markdown 形态"，case_1 聚焦"层级断言"。
    """
    items = [
        _l3_item("src/foo.py", "def foo():\n    return 'bar'"),
        _l3_item("src/baz.py", "def baz():\n    return 'qux'"),
    ]
    snapshot = _make_l3_snapshot(items)

    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=snapshot),
    ):
        result = await HybridSearchService(NullProvider()).search(
            "matrix path probe",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )

    assert "## L3 Related Code" in result.final_context
    assert "src/foo.py" in result.final_context
    assert "src/baz.py" in result.final_context
    assert result.total_tokens > 0
    # rag_only 路径只渲染 L3 RAG 段，不渲染图谱
    assert "## Graph Context" not in result.final_context


# ---------------------------------------------------------------------------
# Test 2: max_tokens 裁剪触发 (truncated: 标记
# ---------------------------------------------------------------------------


async def test_search_max_tokens_trim_for_null_provider() -> None:
    """``max_tokens=200`` + 长 RAG 结果 → final_context 含 ``(truncated:`` 标记。

    与 ``test_case_4_null_provider_token_overflow_triggers_trim`` 互补——本测试
    用更小的 items 与更紧的 token 边界，确保 trim_to_budget 在 NullProvider
    路径的 budgets ratio 100% rag 配置下仍正常触发（防 implementation plan 三 flag
    重构后 ratio 默认值变化打破 trim）。
    """
    long_block = "\n".join(
        f"line {i:03d}: synthetic content for null_provider trim assertion"
        for i in range(40)
    )
    items = [
        _l3_item(f"src/big/chunk_{i:02d}.py", long_block, score=0.9 - i * 0.01)
        for i in range(10)
    ]
    snapshot = _make_l3_snapshot(items)

    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=snapshot),
    ):
        result = await HybridSearchService(NullProvider()).search(
            "GiantNeedle",
            repository_ids=["repo-a"],
            max_tokens=200,
            top_k=30,
        )

    assert "(truncated:" in result.final_context, (
        "max_tokens=200 + 长 RAG 结果应触发 trim_to_budget 截断标记"
    )
    assert "## L3 Related Code" in result.final_context
    assert result.total_tokens > 0


# ---------------------------------------------------------------------------
# Test 3: 空 query 走 search_rag 兜底空 final_context
# ---------------------------------------------------------------------------


async def test_search_empty_query_for_null_provider() -> None:
    """空 query → search_rag 返回 status="ok" + items=[] → final_context=""。

    NullProvider 路径不解析 query / embedding（与 LocalProvider 路径不同），
    空 query 应原样穿透到 search_rag 决定行为；本测试保 search_rag 返空命中时
    final_context 兜底空串，不抛错。
    """
    empty_snapshot = _make_l3_snapshot([])

    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=empty_snapshot),
    ):
        result = await HybridSearchService(NullProvider()).search(
            "",  # 空 query
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )

    assert result.final_context == ""
    assert result.total_tokens == 0
    assert result.repository_ids == ["repo-a"]
    # layers 至少含一条 L3 snapshot 反映 search_rag 调用过
    assert any(layer.layer == "L3" for layer in result.layers)
