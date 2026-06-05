"""``ENABLE_GRAPHRAG_ENRICHMENT`` flag + caller 参数四组合行为锁（per implementation）。

contract 三 flag 语义中"读出侧" flag 的入口守卫测试。implementation 落 ``enable_graph_enrichment``
caller 参数；implementation 在 ``HybridSearchService.search`` 入口**追加** settings 读取，
两者 AND 合并：任一为 False → 强制 ``_search_rag_only`` 路径（即使 Provider 是
GraphCapableProvider），byte-equivalent 兑现 implementation NullProvider 路径。

覆盖 4 组合（settings × caller × Provider 能力）：

1. ``test_enrichment_default_true_graph_capable_active``：默认 settings + LocalProvider
   + caller=True → ``_search_graph_capable`` → 返回 ``HybridSearchResult``。
2. ``test_enrichment_settings_false_forces_rag_only``：``override_settings(ENABLE_GRAPHRAG_ENRICHMENT=False)``
   + LocalProvider + caller=True → 强制 ``_search_rag_only`` → 返回 ``RagSearchResult``
   （implementation 新行为，本 plan RED）。
3. ``test_enrichment_caller_false_forces_rag_only``：默认 settings + LocalProvider
   + caller=False → ``_search_rag_only``（implementation 既有行为回归保护）。
4. ``test_enrichment_null_provider_always_rag_only``：NullProvider + 任意 flag 组合
   → ``_search_rag_only``（capability 守卫永远优先于 enrichment flag）。

**Mock 策略**（per <action>）：``patch services.retrieval.hybrid_search.search_rag``
+ ``patch LocalProvider.lookup_symbols`` 为 AsyncMock 隔离 ORM / Qdrant；
HybridSearchResult vs RagSearchResult ``isinstance`` 区分路径（types.py 设计选择：
不继承，字段同名同序兼容）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from django.test.utils import override_settings

from services.code_intel.local_provider import LocalProvider
from services.code_intel.null_provider import NullProvider
from services.retrieval import HybridSearchService
from services.retrieval.types import (
    HybridSearchResult,
    LayerSnapshot,
    RagSearchResult,
)


def _l3_item(file_path: str, content: str, score: float = 0.85) -> dict[str, Any]:
    """复用 test_null_provider_paths.py 同款 L3 item 构造器。"""
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
# 公共 mock helper
# ---------------------------------------------------------------------------


def _patch_search_rag(snapshot: LayerSnapshot):
    """patch search_rag 模块级符号，返回固定 snapshot。"""
    return patch(
        "services.retrieval.hybrid_search.search_rag",
        new=AsyncMock(return_value=snapshot),
    )


def _patch_local_lookup_symbols():
    """patch ``LocalProvider.lookup_symbols`` 为 AsyncMock 返回 []，避免 ORM 访问。"""
    return patch.object(
        LocalProvider, "lookup_symbols", new=AsyncMock(return_value=[]),
    )


# ---------------------------------------------------------------------------
# Test 1：默认 settings (True) + LocalProvider + caller=True → graph_capable
# ---------------------------------------------------------------------------


async def test_enrichment_default_true_graph_capable_active() -> None:
    """默认配置下 LocalProvider + enable_graph_enrichment=True → graph_capable 路径。

    断言：
    - 返回 ``HybridSearchResult`` 实例（独有 ``hop1_neighbors`` / ``hop2_neighbors``）；
    - 不返回 ``RagSearchResult``（两类型不继承，per types.py 设计选择）。

    items 不含 ``related_chunks`` payload key → hop1 邻居为空 + expand_hop2 fast-path
    早返 → 不触发 ChunkEdge ORM 查询。
    """
    items = [_l3_item("src/auth/login.py", "def login(req): ...")]
    snapshot = _make_l3_snapshot(items)

    with _patch_search_rag(snapshot), _patch_local_lookup_symbols():
        result = await HybridSearchService(LocalProvider()).search(
            "user login",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
            enable_graph_enrichment=True,
        )

    assert isinstance(result, HybridSearchResult), (
        "默认 settings + LocalProvider + caller=True 应走 _search_graph_capable "
        "（返回 HybridSearchResult）"
    )
    assert hasattr(result, "hop1_neighbors"), (
        "HybridSearchResult 必须暴露 hop1_neighbors 字段（per implementation contract）"
    )
    assert result.hop1_neighbors == [], (
        "items 无 related_chunks → 一跳邻居应为空"
    )


# ---------------------------------------------------------------------------
# Test 2：settings=False 强制 rag_only（implementation 新行为，本 plan 入口守卫验收）
# ---------------------------------------------------------------------------


async def test_enrichment_settings_false_forces_rag_only() -> None:
    """``settings.ENABLE_GRAPHRAG_ENRICHMENT=False`` 强制 rag_only，即使 caller=True。

    implementation 核心交付：HybridSearchService.search 入口读 settings + 与
    caller 参数 AND 合并；False 时短路到 ``_search_rag_only`` byte-equivalent
    implementation 路径。

    断言：
    - 返回 ``RagSearchResult``（无 ``hop1_neighbors`` / ``hop2_neighbors`` 字段）；
    - **不**返回 ``HybridSearchResult``。
    """
    items = [_l3_item("src/auth/login.py", "def login(req): ...")]
    snapshot = _make_l3_snapshot(items)

    with override_settings(ENABLE_GRAPHRAG_ENRICHMENT=False):
        with _patch_search_rag(snapshot), _patch_local_lookup_symbols():
            result = await HybridSearchService(LocalProvider()).search(
                "user login",
                repository_ids=["repo-a"],
                max_tokens=8000,
                top_k=30,
                enable_graph_enrichment=True,
            )

    assert isinstance(result, RagSearchResult), (
        "settings.ENABLE_GRAPHRAG_ENRICHMENT=False 应强制 _search_rag_only "
        "(返回 RagSearchResult)，即使 caller 参数 enable_graph_enrichment=True"
    )
    assert not isinstance(result, HybridSearchResult), (
        "RagSearchResult 与 HybridSearchResult 不继承（per types.py 设计选择）；"
        "rag_only 路径不应误命中 HybridSearchResult"
    )
    assert "## L3 Related Code" in result.final_context, (
        "rag_only 路径应保 implementation L3 markdown section 原貌"
    )


# ---------------------------------------------------------------------------
# Test 3：caller=False 强制 rag_only（implementation 既有行为回归保护）
# ---------------------------------------------------------------------------


async def test_enrichment_caller_false_forces_rag_only() -> None:
    """``enable_graph_enrichment=False`` (caller 参数) 强制 rag_only。

    implementation 既有行为回归保护：caller 不需要二跳扩散时主动短路，与
    implementation settings flag 独立（两者 AND 合并）。
    """
    items = [_l3_item("src/auth/login.py", "def login(req): ...")]
    snapshot = _make_l3_snapshot(items)

    with _patch_search_rag(snapshot), _patch_local_lookup_symbols():
        result = await HybridSearchService(LocalProvider()).search(
            "user login",
            repository_ids=["repo-a"],
            max_tokens=8000,
            top_k=30,
            enable_graph_enrichment=False,
        )

    assert isinstance(result, RagSearchResult)
    assert not isinstance(result, HybridSearchResult)


# ---------------------------------------------------------------------------
# Test 4：NullProvider + 任意 flag 组合 → rag_only（capability 守卫优先）
# ---------------------------------------------------------------------------


async def test_enrichment_null_provider_always_rag_only() -> None:
    """NullProvider 不实现 GraphCapableProvider Protocol → 任何 flag 组合都走 rag_only。

    capability 守卫（``isinstance(provider, GraphCapableProvider)``）优先于
    enrichment flag——NullProvider 永远不会进入图谱编排，无论 settings 或
    caller 参数如何取值。

    覆盖 4 组合（笛卡尔：settings True/False × caller True/False）。
    """
    items = [_l3_item("src/auth/login.py", "def login(req): ...")]
    snapshot = _make_l3_snapshot(items)

    combinations = [
        # (settings_value, caller_value)
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ]
    for settings_value, caller_value in combinations:
        with override_settings(ENABLE_GRAPHRAG_ENRICHMENT=settings_value):
            with _patch_search_rag(snapshot):
                result = await HybridSearchService(NullProvider()).search(
                    "user login",
                    repository_ids=["repo-a"],
                    max_tokens=8000,
                    top_k=30,
                    enable_graph_enrichment=caller_value,
                )
        assert isinstance(result, RagSearchResult), (
            f"NullProvider + settings={settings_value} + caller={caller_value} "
            "应走 _search_rag_only（capability 守卫优先于 enrichment flag）"
        )
        assert not isinstance(result, HybridSearchResult)
