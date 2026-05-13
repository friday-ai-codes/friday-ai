"""RAG 主线检索 —— per / 。
`search_rag` 是 `LayeredSearchService._l3_hybrid_search`（layered_search.py 行
work-item）的纯函数抽出版本：
- 步骤照搬现状（embedding 生成 → BranchAwareSearchService.search → 跨仓去重 →
 按 score 降序 → 截断 top_k）
- 行为契约由 Phase golden snapshot 守护（Plan wire-up 后由 zero-drift
 门禁验证 ）
- **禁止读 codegraph 启用开关**（per Pitfall 5）：search_rag 不参与启用/禁用
 决策，纯计算；启用决策由 Plan 的 HybridSearchService 通过 Provider 注入
 处理（grep 守护：rg 'settings\\.ENABLE_CODEGRAP[H]' 必须 0 命中）
Logger 命名 `rag_search_*` 与现状 `layered_search_*` / `compat_layered_search_*`
保持同 idiom，便于 grep 排查。
"""
from __future__ import annotations
from typing import Any
import structlog
from services.retrieval.types import LayerSnapshot
logger = structlog.get_logger(__name__)
async def search_rag(
 query: str,
 *,
 repo_ids: list[str],
 branch_name: str | None = None,
 top_k: int = 30,
) -> LayerSnapshot:
 """对一组 repo_ids 执行 dense + sparse 混合向量检索。
 抽出 `LayeredSearchService._l3_hybrid_search` 行 work-item 的逻辑，行为契约：
 1. `query_dense = await EmbeddingService.generate_embedding(query)`，
 falsy（None / 空 list）→ 返回 status="error"
 2. `query_sparse = await sync_to_async(SparseEncoderService.encode)(query)`，
 缺 indices → 置 None
 3. 遍历 `repo_ids` 顺序调 `BranchAwareSearchService.search(...)`，单仓异常
 log warning 后继续
 4. 跨仓去重 key = (repo_id, file_path, chunk_index)
 5. 按 score 降序，截断 top_k
 6. 返回 `LayerSnapshot(layer="L3", status="ok", result_count=len(all),
 items=all[:top_k])`
 Args:
 query: 查询文本（来自 chat / agent / workflow，非可信输入）。
 repo_ids: 候选仓库 id 列表（已经过 L1 RepoRouter 路由）。
 branch_name: 分支名（None → BranchAwareSearchService 走 base 分支）。
 top_k: 返回的最大条数（默认 30，与 LayeredSearchService.DEFAULT_TOP_K 一致）。
 Returns:
 `LayerSnapshot`，每个 item 含 `payload` / `score` / `repository_id`。
 """
 try:
 from asgiref.sync import sync_to_async
 from services.branch_search import BranchAwareSearchService
 from services.embedding import EmbeddingService
 from services.sparse_encoder import SparseEncoderService
 query_dense = await EmbeddingService.generate_embedding(query)
 if not query_dense:
 return LayerSnapshot(layer="L3", status="error", error="embedding generation failed")
 query_sparse: dict[str, Any] | None = await sync_to_async(SparseEncoderService.encode)(query)
 if not query_sparse or not query_sparse.get("indices"):
 query_sparse = None
 all_results: list[dict[str, Any]] =
 seen_keys: set[tuple[str, str, int]] = set
 for repo_id in repo_ids:
 try:
 results = await BranchAwareSearchService.search(
 repo_id, query_dense,
 query_sparse=query_sparse,
 branch_name=branch_name,
 top_k=top_k,
 )
 for r in results:
 payload = r.get("payload", {})
 key = (repo_id, payload.get("file_path", ""), payload.get("chunk_index", 0))
 if key not in seen_keys:
 seen_keys.add(key)
 all_results.append({**r, "repository_id": repo_id})
 except Exception as e:
 logger.warning("rag_search_single_repo_failed", repo_id=repo_id, error=str(e))
 all_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
 return LayerSnapshot(
 layer="L3", status="ok",
 result_count=len(all_results), items=all_results[:top_k],
 )
 except Exception as e:
 logger.warning("rag_search_failed", query=query[:100], error=str(e))
 return LayerSnapshot(layer="L3", status="error", error=str(e))
__all__ = ["search_rag"]
