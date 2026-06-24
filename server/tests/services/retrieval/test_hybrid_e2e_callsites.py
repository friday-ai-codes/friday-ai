"""implementation Task 2 — agent / workflow / chat 三路径 E2E callsite 契约。

6 条核心断言验证 ROADMAP §implementation success criterion "agent / workflow / chat 三路径调用
`HybridSearchService.search(...)` 唯一入口"：

1. ``test_agent_search_repository_code_returns_l3_results`` —— 调
   ``agents.tools.space_tools.search_repository_code`` mock 各依赖 →
   ToolResult.success=True + output.data.results 非空 + L3 score 字段存在
2. ``test_agent_search_with_graph_capable_returns_graph_context`` —— 同上 mock
   HybridSearchResult 含 graph_context → ToolResult.output.metadata['context']
   含 ``## Graph Context`` 段（验证 callsite 不破坏 enrichment）
3. ``test_workflow_context_retrieval_node_consumes_hybrid_result`` —— 调
   ``workflows.nodes.ai.context_retrieval.ContextRetrievalNode._search_repository``
   mock HybridSearchService → 返回 dict 含 context / results / status='success'
4. ``test_chat_service_search_path_skipped_documented`` —— chat 通过 agent tool
   间接调用 HybridSearchService（chat → agent → HybridSearchService），无直接
   callsite；pytest.skip + 注释说明
5. ``test_callsite_signature_unchanged`` —— inspect.signature 验证
   ``search_repository_code`` / ``HybridSearchService.search`` 入参契约稳定
6. ``test_no_layered_search_direct_import_in_callsites`` —— rg grep gate:
   ``from codegraph.services.layered_search import`` 在 agents/ + workflows/ +
   chat/ 0 命中（仅 codegraph 自身 + hybrid_search.py lazy import 命中）

测试设计：
- 不依赖真实 Qdrant / ORM / Django ORM 查询；全 mock HybridSearchService.search
- agent test 用 ``pytest.mark.django_db`` + ``repository`` fixture 让 Repository.aget 通过
- workflow test 直接调 ``_search_repository`` 内部方法，避免完整节点 execute 链路
"""

from __future__ import annotations

import inspect
import pathlib
import subprocess
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from services.retrieval import HybridSearchService
from services.retrieval.types import (
    HybridSearchResult,
    LayerSnapshot,
    NeighborMetadata,
    RagSearchResult,
)

# ---------------------------------------------------------------------------
# helpers — 构造 HybridSearchService.search 替身返回值
# ---------------------------------------------------------------------------


def _l3_snapshot_with_items(repo_id: str = "repo-a") -> LayerSnapshot:
    """L3 LayerSnapshot 替身：含 2 个高分 item。

    item 的 ``repository_id`` 用传入的真实 repo_id（而非字面 "repo-a"）——
    search_repository_code 的 EXCL-02 兜底过滤会按 item.repository_id 预取匹配器，
    非法 id 会触发 fail-closed 丢弃；用真实 id 让良性 file_path 正常通过。
    """
    return LayerSnapshot(
        layer="L3",
        status="ok",
        result_count=2,
        items=[
            {
                "score": 0.85,
                "payload": {
                    "file_path": "src/auth/login.py",
                    "content": "def login(req):\n    return ok",
                    "language": "python",
                },
                "repository_id": repo_id,
            },
            {
                "score": 0.72,
                "payload": {
                    "file_path": "src/auth/session.py",
                    "content": "class Session: pass",
                    "language": "python",
                },
                "repository_id": repo_id,
            },
        ],
    )


def _rag_only_result(repo_id: str) -> RagSearchResult:
    """rag_only 路径返回值替身。"""
    return RagSearchResult(
        query="probe",
        repository_ids=[repo_id],
        layers=[_l3_snapshot_with_items(repo_id)],
        final_context="## L3 Related Code\n\n### src/auth/login.py (score: 0.850)\n",
        total_tokens=42,
    )


def _hybrid_result_with_graph(repo_id: str) -> HybridSearchResult:
    """graph_capable 路径返回值替身：含 graph_context + hop1 邻居。"""
    return HybridSearchResult(
        query="probe",
        repository_ids=[repo_id],
        layers=[_l3_snapshot_with_items(repo_id)],
        final_context=(
            "## L3 Related Code\n\n### src/auth/login.py (score: 0.850)\n\n"
            "## Graph Context\n\n"
            "### Direct Neighbors (1-hop)\n\n"
            "- `src/auth/handler.py:10` (CALL, w=0.90): via direct call"
        ),
        total_tokens=80,
        graph_context=(
            "## Graph Context\n\n### Direct Neighbors (1-hop)\n\n"
            "- `src/auth/handler.py:10` (CALL, w=0.90): via direct call"
        ),
        hop1_neighbors=[
            NeighborMetadata(
                chunk_id="h1-a",
                file_path="src/auth/handler.py",
                line_start=10,
                line_end=20,
                edge_type="CALL",
                weight=0.90,
                reason="via direct call",
                hop=1,
            ),
        ],
        hop2_neighbors=[],
    )


# ---------------------------------------------------------------------------
# Test 1: agent search_repository_code 路径返回 L3 results
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_agent_search_repository_code_returns_l3_results(
    repository,
) -> None:
    """Agent tool 调 HybridSearchService.search 返回 ToolResult 含 L3 results。

    断言：
    - ToolResult.success == True
    - output.data.results 非空（至少 1 条 score >= min_score）
    - 每个 result 含 file_path / content / score / repository_id 字段
    - HybridSearchService.search 被调用一次（callsite 链路正确）
    """
    from agents.tools.space_tools import search_repository_code

    repo_id = str(repository.id)
    search_mock = AsyncMock(return_value=_rag_only_result(repo_id))

    with patch.object(HybridSearchService, "search", new=search_mock):
        result = await search_repository_code(
            query="user login",
            repository_id=repo_id,
            limit=10,
            min_score=0.5,
        )

    assert result.success is True, f"ToolResult.success 应 True: {result.error}"
    data = result.output["data"]
    assert len(data["results"]) >= 1, "L3 results 应非空"
    first = data["results"][0]
    assert "file_path" in first and first["file_path"] != ""
    assert "content" in first
    assert "score" in first and first["score"] >= 0.5
    assert "repository_id" in first
    assert search_mock.call_count == 1, (
        f"HybridSearchService.search 应被调用 1 次，实际 {search_mock.call_count}"
    )


# ---------------------------------------------------------------------------
# Test 2: agent 路径 graph_capable 不破坏 graph_context enrichment
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_agent_search_with_graph_capable_returns_graph_context(
    repository,
) -> None:
    """Agent callsite 消费 HybridSearchResult → metadata.context 含 graph_context 段。

    断言 callsite 取 `result.final_context` 不破坏 ## Graph Context enrichment。
    """
    from agents.tools.space_tools import search_repository_code

    repo_id = str(repository.id)
    search_mock = AsyncMock(return_value=_hybrid_result_with_graph(repo_id))

    with patch.object(HybridSearchService, "search", new=search_mock):
        result = await search_repository_code(
            query="user login",
            repository_id=repo_id,
            limit=10,
            min_score=0.5,
        )

    assert result.success is True
    metadata = result.output["metadata"]
    assert "context" in metadata, "metadata 必须含 context 字段（final_context 透传）"
    assert "## Graph Context" in metadata["context"], (
        f"graph_capable 路径 metadata.context 必须含 ## Graph Context 段; "
        f"got: {metadata['context']!r}"
    )
    assert "### Direct Neighbors (1-hop)" in metadata["context"]


# ---------------------------------------------------------------------------
# Test 3: workflow ContextRetrievalNode._search_repository 消费 HybridSearchResult
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_workflow_context_retrieval_node_consumes_hybrid_result(
    repository,
) -> None:
    """workflow ContextRetrievalNode._search_repository 调 HybridSearchService.search
    → 返回 dict 含 status='success' / context (final_context) / results (L3 items)。

    断言 callsite 取 `result.final_context` / `result.layers` 无 AttributeError。
    """
    from workflows.nodes.ai.context_retrieval import ContextRetrievalNode

    repo_id = str(repository.id)
    search_mock = AsyncMock(return_value=_hybrid_result_with_graph(repo_id))

    node = ContextRetrievalNode()

    with patch.object(HybridSearchService, "search", new=search_mock):
        out = await node._search_repository(  # type: ignore[attr-defined]
            repository,
            query="user login",
            top_k=10,
            filters=None,
            timeout=30.0,
        )

    assert out["status"] == "success", f"status 应 success: {out}"
    assert out["repository_id"] == repo_id
    assert out["repository_name"] == repository.name
    assert "context" in out, "返回 dict 必须含 context 字段（final_context 透传）"
    assert "## Graph Context" in out["context"], (
        "workflow callsite 不应破坏 graph_context enrichment"
    )
    # L3 items 应被提取到 results 字段
    assert "results" in out and isinstance(out["results"], list)
    assert len(out["results"]) == 2, "L3 layer 2 items 应被透传到 results"
    assert search_mock.call_count == 1


# ---------------------------------------------------------------------------
# Test 4: chat callsite 间接（通过 agent tool）→ skip + 注释说明
# ---------------------------------------------------------------------------


def test_chat_service_search_path_skipped_documented() -> None:
    """chat 模块通过 agent tool ``search_repository_code`` 间接调用 HybridSearchService。

    grep ``HybridSearchService`` 在 ``server/chat/`` 0 命中（仅
    conversation_service.py 的 prompt 字面 ``search_repository_code`` 引用 agent
    tool name）。chat 路径覆盖由 test 1 / test 2（agent search_repository_code
    路径）端到端覆盖；本测试 skip 并文档化决策。
    """
    pytest.skip(
        "chat 路径通过 agent tool search_repository_code 间接调用 "
        "HybridSearchService —— 覆盖由 test 1 / test 2 提供；无直接 callsite。"
    )


# ---------------------------------------------------------------------------
# Test 5: callsite signature 稳定（agent + HybridSearchService.search）
# ---------------------------------------------------------------------------


def test_callsite_signature_unchanged() -> None:
    """inspect.signature 锁 agent tool + HybridSearchService.search 入参契约。

    任何新增/移除 callsite 入参都会触发本断言失败，提醒 reviewer 同步更新
    callsite 与下游消费者。
    """
    from agents.tools.space_tools import search_repository_code

    sig = inspect.signature(search_repository_code)
    expected_agent_params = {
        "query",
        "repository_id",
        "space_id",
        "limit",
        "min_score",
        "branch",
        # 72-04 RAG-02：chat 召回链留痕需 conversation_id（auto-injected，LLM 不可见）。
        "conversation_id",
    }
    actual_agent_params = set(sig.parameters.keys())
    assert expected_agent_params == actual_agent_params, (
        f"search_repository_code 签名漂移: "
        f"expected={expected_agent_params}, actual={actual_agent_params}"
    )

    hsig = inspect.signature(HybridSearchService.search)
    expected_hsearch_params = {
        "self",
        "query",
        "repository_ids",
        "project_id",
        "branch_name",
        "max_tokens",
        "top_k",
        "enable_graph_enrichment",
    }
    actual_hsearch_params = set(hsig.parameters.keys())
    assert expected_hsearch_params == actual_hsearch_params, (
        f"HybridSearchService.search 签名漂移: "
        f"expected={expected_hsearch_params}, actual={actual_hsearch_params}"
    )


# ---------------------------------------------------------------------------
# Test 6: grep gate — LayeredSearchService 直 import 仅命中允许的两个文件
# ---------------------------------------------------------------------------


def test_no_layered_search_direct_import_in_callsites() -> None:
    """rg grep gate：``from codegraph.services.layered_search import`` 在
    ``server/agents/`` + ``server/workflows/`` + ``server/chat/`` 0 命中
    （requirements §implementation success criterion "agent/workflow/chat 三路径全部通过
    HybridSearchService"）。

    允许命中：
    - ``server/codegraph/services/layered_search.py`` 自身
    - ``server/services/retrieval/hybrid_search.py`` lazy import（复用 _format_l3_section）
    - ``server/compat/`` / ``server/codegraph/`` 其他模块（不在三路径里）

    本测试 scope = ``agents/ workflows/ chat/`` 三路径目录，命中数必须 0。
    """
    server_dir = pathlib.Path(__file__).resolve().parents[3]
    targets = [
        server_dir / "agents",
        server_dir / "workflows",
        server_dir / "chat",
    ]
    for target in targets:
        assert target.exists(), f"target dir missing: {target}"

    cmd = [
        "rg",
        "-l",
        "--no-heading",
        "from codegraph\\.services\\.layered_search import",
        *(str(t) for t in targets),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # rg exit 0 = matches, 1 = no matches, 2 = error
    assert proc.returncode in (0, 1), (
        f"rg 异常退出 (code={proc.returncode}): stderr={proc.stderr!r}"
    )
    matches = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    assert not matches, (
        f"agent/workflow/chat 三路径必须 0 直 import LayeredSearchService; 命中文件: {matches}"
    )


# ---------------------------------------------------------------------------
# helper: keep references for type checker
# ---------------------------------------------------------------------------


def _typecheck_helpers() -> None:
    """让 mypy 看到 type 引用，避免 unused import 警告。"""
    _: Any = HybridSearchService
    _ = RagSearchResult
    _ = HybridSearchResult
    _ = NeighborMetadata
    _ = LayerSnapshot
