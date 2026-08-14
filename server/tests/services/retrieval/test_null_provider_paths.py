"""NullProvider 路径行为测试 —— per implementation contract / contract / Pitfall 5。

5 条 case 覆盖 ROADMAP §implementation Success Criteria #3 一半（剩余完整 pytest
matrix 由 implementation 补全）：

1. ``test_case_1_null_provider_returns_pure_rag``：禁用配置 + 给定 repo_ids
   → final_context 仅含 ``## L3 Related Code``，**无** symbol / expansion 段。
2. ``test_case_2_null_provider_repo_ids_none_skips_repo_router``：repo_ids=None
   → NullProvider 路径不触发 RepoRouter（mock spy.called False），直接以空 repo
   列表调 search_rag，final_context 兜底空字符串。
3. ``test_case_3_null_provider_empty_results_does_not_raise``：query 命中空
   chunk → final_context="" + total_tokens=0，**不抛错**。
4. ``test_case_4_null_provider_token_overflow_triggers_trim``：max_tokens=200
   + 长 RAG 结果 → final_context 含 ``(truncated:`` 标记（trim_to_budget 触发，
   与 L3-only 路径等价）。
5. ``test_case_5_local_provider_equivalent_to_null_when_disabled``：
   ENABLE_CODEGRAPH=False 等价配置（L2/L4 mock 为空）下，LocalProvider 路径
   final_context 包含 NullProvider 路径的 L3 RAG 输出（"零漂移"补充验证）。

**Pitfall 5 关键约束 #4**：所有 case 用 ``HybridSearchService(NullProvider())``
直接调用，**禁止 patch settings.ENABLE_CODEGRAPH** —— Provider 注入是依赖注入，
开关语义集中在 ``CodeIntelConfig.ready()``。

外部依赖（``services.retrieval.rag_search.search_rag`` /
``codegraph.services.repo_router_v2.RepoRouterV2.route`` /
``LayeredSearchService._lN`` 私有 classmethod）走 ``unittest.mock.patch`` 局部
mock，不依赖真实 ORM / Qdrant / Embedding。目标 < 5 秒跑完 5 条。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from services.code_intel.local_provider import LocalProvider
from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from services.retrieval.types import LayerSnapshot


def _l3_item(file_path: str, content: str, score: float = 0.85) -> dict[str, Any]:
    """构造 L3 命中 item，与 ``_format_l3_section`` 期望的 payload key 对齐。"""
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
# case 1：禁用配置 + 给定 repo_ids → 纯 RAG final_context
# ---------------------------------------------------------------------------


async def test_case_1_null_provider_returns_pure_rag() -> None:
    """NullProvider 注入下 final_context 仅含 ``## L3 Related Code`` 段。

    断言四点：
    - 含 ``## L3 Related Code`` 标题与 chunk 内容；
    - **不**含 ``## L2 Exact Matches`` / ``## L4 Graph Context`` 标题（
      capability 守卫确保 NullProvider 路径不进入 L2 / L4 编排）；
    - ``total_tokens > 0``；
    - ``layers`` 至少含 1 条 ``layer="L3"``。
    """
    items = [
        _l3_item("src/auth/login.py", "def login(req):\n    return authenticate(req)"),
        _l3_item("src/auth/session.py", "def make_session(user):\n    return Session(user)"),
    ]
    snapshot = _make_l3_snapshot(items)

    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=snapshot),
    ):
        result = await HybridSearchService(NullProvider()).search(
            "user login flow",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )

    assert "## L3 Related Code" in result.final_context
    assert "src/auth/login.py" in result.final_context
    assert "## L2 Exact Matches" not in result.final_context
    assert "## L4 Graph Context (1-hop)" not in result.final_context
    assert "## L4 Graph Context (2-hop)" not in result.final_context
    assert result.total_tokens > 0
    assert any(layer.layer == "L3" for layer in result.layers)


# ---------------------------------------------------------------------------
# case 2：repo_ids=None → 不调 RepoRouter，直接走 search_rag([])
# ---------------------------------------------------------------------------


async def test_case_2_null_provider_repo_ids_none_skips_repo_router() -> None:
    """``repository_ids=None`` 时 NullProvider 路径直接传 ``[]`` 给 search_rag。

    断言：
    - ``RepoRouter.route`` 调用次数 == 0（NullProvider 路径不触图谱编排，per security mitigation）；
    - ``search_rag`` 被以 ``repo_ids=[]`` 调用一次；
    - 空命中时 final_context == ""。
    """
    from codegraph.services.repo_router_v2 import RepoRouterV2

    repo_router_spy = AsyncMock()
    rag_search_mock = AsyncMock(return_value=_make_l3_snapshot([]))

    with patch.object(RepoRouterV2, "route", new=repo_router_spy), patch(
        "services.retrieval.hybrid_search.search_rag",
        new=rag_search_mock,
    ):
        result = await HybridSearchService(NullProvider()).search(
            "fallback query",
            repository_ids=None,
            max_tokens=8000,
            top_k=30,
        )

    assert repo_router_spy.call_count == 0, (
        "NullProvider 路径不应触发 RepoRouter (per security mitigation + contract case 2)"
    )
    rag_search_mock.assert_called_once()
    call_kwargs = rag_search_mock.call_args.kwargs
    assert call_kwargs["repo_ids"] == [], (
        "repository_ids=None 时 NullProvider 路径应以 repo_ids=[] 调 search_rag"
    )
    assert result.final_context == ""
    assert result.total_tokens == 0
    assert result.repository_ids == []


# ---------------------------------------------------------------------------
# case 3：query 命中空结果 → final_context="" 不 raise
# ---------------------------------------------------------------------------


async def test_case_3_null_provider_empty_results_does_not_raise() -> None:
    """空 chunk 返回时兜底 final_context="" + total_tokens=0，不抛错。"""
    empty_snapshot = _make_l3_snapshot([])

    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=empty_snapshot),
    ):
        result = await HybridSearchService(NullProvider()).search(
            "no_match_query_xyz_unique",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )

    assert result.final_context == ""
    assert result.total_tokens == 0
    assert result.repository_ids == ["repo-a"]


# ---------------------------------------------------------------------------
# case 4：max_tokens=200 → trim_to_budget 触发 (truncated: 标记
# ---------------------------------------------------------------------------


async def test_case_4_null_provider_token_overflow_triggers_trim() -> None:
    """长 RAG 结果 + max_tokens=200 → final_context 含 ``(truncated:`` 标记。

    与 L3-only 路径等价：``_search_rag_only`` 调 ``trim_to_budget(l3_markdown,
    budgets["rag"])``，溢出时 token_budget 模块在文末附加 ``(truncated: ...)``。
    """
    long_block = "\n".join(
        f"line {i:03d}: synthetic chunk content for trim_to_budget overflow testing"
        for i in range(60)
    )
    items = [
        _l3_item(f"src/giant/chunk_{i:02d}.py", long_block, score=0.95 - i * 0.01)
        for i in range(20)
    ]
    snapshot = _make_l3_snapshot(items)

    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=snapshot),
    ):
        result = await HybridSearchService(NullProvider()).search(
            "GiantSeed",
            repository_ids=["repo-a"],
            max_tokens=200,
            top_k=30,
        )

    assert "(truncated:" in result.final_context, (
        "max_tokens=200 + 长 RAG 结果应触发 trim_to_budget 截断标记"
    )
    assert result.total_tokens > 0
    assert "## L3 Related Code" in result.final_context


# ---------------------------------------------------------------------------
# case 5：禁用配置下 LocalProvider == NullProvider 的 L3 RAG 输出（零漂移）
# ---------------------------------------------------------------------------


async def test_case_5_local_provider_equivalent_to_null_when_disabled() -> None:
    """无邻居（payload 无 related_chunks + ChunkEdge 为空）时 LocalProvider 与 NullProvider 输出等价。

    **implementation 更新（contract refresh）**：
    implementation era 下 LocalProvider 路径会内联调 LayeredSearchService._l1.._l5
    渲染 L1/L2/L4 stub 段，导致 final_context 不等于 NullProvider 路径；本测试
    旧版断言 ``"## L2 Exact Matches" in local_result.final_context`` 捕获了那个
    implementation 现状。

    implementation 重写 ``_search_graph_capable`` 后：
    - 不再渲染 L2/L4 stub 段（去除"图谱编排"与"layered 五层包装"耦合）
    - hop1/hop2 邻居均空时 ``## Graph Context`` 段**不写入**（避免空 markdown 块）
    - 与 ``_search_rag_only`` 在零邻居下输出**byte-equal**（per implementation CONTEXT.md
      "graph_capable 路径**期望产生差异**" 反向解读：仅当存在图谱信号才差异）

    本测试现在断言：无邻居条件下 LocalProvider 与 NullProvider final_context
    完全相等（零漂移 byte-eq 升级版本，per implementation contract case 5 末段
    "implementation 灰度切换若让 LocalProvider 在 codegraph 禁用配置下也走 _search_rag_only
    同一路径，则 byte-equality 升级为全等" —— implementation 提前兑现该承诺）。
    """
    items = [
        _l3_item("src/equiv/foo.py", "def foo():\n    return 'shared'", score=0.81),
        _l3_item("src/equiv/bar.py", "def bar():\n    return 'shared'", score=0.74),
    ]
    null_snapshot = _make_l3_snapshot(items)

    # 两次调用共享同一 rag_snapshot mock —— 让 LocalProvider 和 NullProvider 走同一
    # RAG 召回数据；LocalProvider 路径的 symbol_task 走 LocalProvider.lookup_symbols
    # 真实代码（无 mock，会触发"Database access not allowed"），但 asyncio.gather
    # return_exceptions=True 把异常降级为 symbol_results=[]，hop1/hop2 仍走 RAG
    # snapshot 的 payload（本测试 items 无 related_chunks → 邻居空），最终
    # final_context 仅含 L3 RAG section。
    with patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=null_snapshot),
    ):
        null_result = await HybridSearchService(NullProvider()).search(
            "equiv probe",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )
        local_result = await HybridSearchService(LocalProvider()).search(
            "equiv probe",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
        )

    assert null_result.final_context, (
        "NullProvider 路径应有非空 final_context"
    )
    assert null_result.final_context == local_result.final_context, (
        "无邻居场景下 LocalProvider 与 NullProvider final_context 必须 byte-equal "
        "(implementation 零漂移升级，per CONTEXT.md graph_capable 反向解读)"
    )
    assert "## L3 Related Code" in local_result.final_context
    assert "## L2 Exact Matches" not in local_result.final_context, (
        "implementation 重写后 LocalProvider 路径不再渲染 L2 stub 段"
    )
    assert "## Graph Context" not in local_result.final_context, (
        "无邻居时不写空 graph_context markdown 块（避免污染 LLM 上下文）"
    )
