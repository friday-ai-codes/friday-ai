"""HybridSearchService 骨架烟测 —— initial implementation plan Task 2。

6 条核心断言（per hard_constraint #4 / #5 / #6 / #7 + Pitfall 5）：

1. ``test_provider_type_guard`` —— 非 ``BaseCodeProvider`` 注入 raise TypeError
   （per security mitigation 防御 duck-type 绕过）。
2. ``test_local_provider_equivalent_to_layered`` —— 同一 query / mock 环境下，
   ``HybridSearchService(LocalProvider()).search`` 与 ``LayeredSearchService.search``
   的 ``final_context`` 字节级一致（hard_constraint #4 + #7 + #6 zero-drift gate）。
3. ``test_null_provider_returns_only_l3_section`` —— NullProvider 注入下
   ``final_context`` 仅含 ``## L3 Related Code`` 标题，且
   ``LayeredSearchService.search`` 调用次数 = 0（hard_constraint #5 +
   security mitigation：不触 symbol/expansion）。
4. ``test_null_provider_empty_query`` —— 空 query 不抛错；embedding 失败时
   ``total_tokens == 0`` / ``final_context == ""``。
5. ``test_null_provider_trim_on_overflow`` —— ``max_tokens=200`` 超限触发
   ``trim_to_budget`` 截断，输出含 ``(truncated:`` 标记。
6. ``test_no_settings_enable_codegraph_in_module`` —— Pitfall 5 grep gate：
   ``services/retrieval/hybrid_search.py`` 源码（过滤 ``#`` 注释行）不出现
   ``settings.ENABLE_CODEGRAPH`` 字面值。

外部依赖（RepoRouter / Symbol ORM / BranchAwareSearch / Embedding /
SparseEncoder / GraphExpansion）全部走 plan 落的
``golden_mock_environment_context`` 确定性 mock；所有测试不依赖真实 ORM /
Qdrant，目标 < 5 秒跑完。
"""

from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, patch

import pytest

from codegraph.services.layered_search import LayeredSearchService
from services.code_intel.local_provider import LocalProvider
from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from tests.codegraph.conftest import golden_mock_environment_context


# ---------------------------------------------------------------------------
# Test 1: Provider 类型守卫（per security mitigation）
# ---------------------------------------------------------------------------


def test_provider_type_guard() -> None:
    """非 BaseCodeProvider 注入 raise TypeError，错误信息可定位。"""

    class _NotAProvider:
        """裸对象，缺 capabilities / health_check。"""

    with pytest.raises(TypeError, match="BaseCodeProvider"):
        HybridSearchService(_NotAProvider())  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="BaseCodeProvider"):
        HybridSearchService(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 2: LocalProvider 等价 LayeredSearchService（hard_constraint #4 + #7）
# ---------------------------------------------------------------------------


async def test_local_provider_equivalent_to_layered() -> None:
    """LocalProvider 注入下 final_context 与 LayeredSearchService.search 字节级一致。

    选取 Q04 ``UserService`` (L2 精确匹配 + L4 expand 走全五层) 作为代表，
    覆盖 _l1.._l5 全链路。同一 mock 环境下两次执行确定性等价。
    """
    query = "UserService"
    repo_ids = ["repo-a"]

    with golden_mock_environment_context():
        result_layered = await LayeredSearchService.search(
            query, repository_ids=repo_ids, max_tokens=8000, top_k=30,
        )
        result_hybrid = await HybridSearchService(LocalProvider()).search(
            query, repository_ids=repo_ids, max_tokens=8000, top_k=30,
        )

    assert result_hybrid.final_context == result_layered.final_context, (
        "LocalProvider 路径漂移：HybridSearchService 必须与 LayeredSearchService "
        "在 final_context 上字节级等价（hard_constraint #4 + #7）"
    )
    assert result_hybrid.total_tokens == result_layered.total_tokens
    assert result_hybrid.repository_ids == result_layered.repository_ids
    assert result_hybrid.final_context != ""


# ---------------------------------------------------------------------------
# Test 3: NullProvider 仅 L3 section + 不触 LayeredSearchService.search
#         （hard_constraint #5 + security mitigation）
# ---------------------------------------------------------------------------


async def test_null_provider_returns_only_l3_section() -> None:
    """NullProvider 注入下 final_context 仅含 ``## L3 Related Code`` 标题。

    断言 hard_constraint #5：``LayeredSearchService.search`` 调用次数 == 0
    （capability 守卫确保 NullProvider 路径不进入图谱编排）。
    """
    query = "user model"
    repo_ids = ["repo-a"]

    layered_search_spy = AsyncMock(wraps=LayeredSearchService.search)
    with golden_mock_environment_context(), patch.object(
        LayeredSearchService, "search", new=layered_search_spy,
    ):
        result = await HybridSearchService(NullProvider()).search(
            query, repository_ids=repo_ids, max_tokens=8000, top_k=30,
        )

    assert layered_search_spy.call_count == 0, (
        "NullProvider 路径不应触发 LayeredSearchService.search "
        "(hard_constraint #5 + security mitigation)"
    )
    assert "## L3 Related Code" in result.final_context
    assert "## L2 Exact Matches" not in result.final_context
    assert "## L4 Graph Context (1-hop)" not in result.final_context
    assert "## L4 Graph Context (2-hop)" not in result.final_context
    assert result.total_tokens > 0
    assert any(layer.layer == "L3" for layer in result.layers)


# ---------------------------------------------------------------------------
# Test 4: NullProvider 空 query 边界（embedding 失败兜底）
# ---------------------------------------------------------------------------


async def test_null_provider_empty_query() -> None:
    """空 query 触发 embedding 返回空列表，search_rag 报 error，兜底空 final_context。"""
    with golden_mock_environment_context():
        result = await HybridSearchService(NullProvider()).search(
            "", repository_ids=["repo-a"], max_tokens=8000, top_k=30,
        )

    assert result.total_tokens == 0
    assert result.final_context == ""
    assert result.repository_ids == ["repo-a"]
    l3_layers = [lyr for lyr in result.layers if lyr.layer == "L3"]
    assert l3_layers and l3_layers[0].status == "error"


# ---------------------------------------------------------------------------
# Test 5: NullProvider trim_to_budget 截断（max_tokens=200 强制溢出）
# ---------------------------------------------------------------------------


async def test_null_provider_trim_on_overflow() -> None:
    """``GiantSeed`` query 在 repo-a 下返回 30 个 60 行 chunk，max_tokens=200 必触截断。"""
    with golden_mock_environment_context():
        result = await HybridSearchService(NullProvider()).search(
            "GiantSeed", repository_ids=["repo-a"], max_tokens=200, top_k=30,
        )

    assert "(truncated:" in result.final_context, (
        "max_tokens=200 应触发 trim_to_budget 截断标记"
    )
    assert result.total_tokens > 0
    assert result.total_tokens <= 200
    assert "## L3 Related Code" in result.final_context


# ---------------------------------------------------------------------------
# Test 6: Pitfall 5 grep gate（同步测试，不需 mock）
# ---------------------------------------------------------------------------


def test_no_settings_enable_codegraph_in_module() -> None:
    """``services/retrieval/hybrid_search.py`` 源码（过滤 ``#`` 注释行）必须不
    出现 ``settings.ENABLE_CODEGRAPH`` 字面值（per Pitfall 5 + hard_constraint #2）。

    注意：planner 关键规则要求过滤注释行（``lstrip().startswith('#')``），
    避免误伤 docstring / 注释中的提及。
    """
    server_dir = pathlib.Path(__file__).resolve().parents[3]
    target = server_dir / "services" / "retrieval" / "hybrid_search.py"
    assert target.exists(), f"target file missing: {target}"

    text = target.read_text(encoding="utf-8")
    non_comment_lines = [
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    ]
    non_comment = "\n".join(non_comment_lines)
    assert "settings.ENABLE_CODEGRAPH" not in non_comment, (
        "Pitfall 5 violation: hybrid_search.py 必须不读 settings.ENABLE_CODEGRAPH; "
        "Provider 注入由 CodeIntelConfig.ready() 集中管理"
    )
