"""RAG 主线检索 —— per contract / contract。

`search_rag` 是 `LayeredSearchService._l3_hybrid_search`（layered_search.py 行
work-item）的纯函数抽出版本：

- 步骤照搬现状（embedding 生成 → BranchAwareSearchService.search → 跨仓去重 →
  按 score 降序 → 截断 top_k）
- 行为契约由 implementation golden snapshot 守护（plan wire-up 后由 zero-drift
  门禁验证 contract）
- **禁止读 codegraph 启用开关**（per Pitfall 5）：search_rag 不参与启用/禁用
  决策，纯计算；启用决策由 plan 的 HybridSearchService 通过 Provider 注入
  处理（grep 守护：rg 'settings\\.ENABLE_CODEGRAP[H]' 必须 0 命中）

Logger 命名 `rag_search_*` 与现状 `layered_search_*` / `compat_layered_search_*`
保持同 idiom，便于 grep 排查。
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from services.exclusion import build_matcher_for_repo, log_exclusion_blocked
from services.retrieval.types import LayerSnapshot

logger = structlog.get_logger(__name__)

# 多仓 RAG 并发上限：每仓一次 Qdrant 混合检索，跨 50+ 仓时串行延迟线性累加。
# 用有界并发把延迟从 O(N) 降到 O(N/并发)，上限防止打爆 Qdrant 连接/worker。
_RAG_REPO_CONCURRENCY = 8


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
        from services.retrieval.rerank import get_rerank_plan, reorder
        from services.sparse_encoder import SparseEncoderService

        # 重排计划：model 模式下 over-fetch 更多候选交给 reranker 精排；
        # heuristic / off 模式按 top_k 召回（与历史行为一致）。读取失败已 fail-open。
        plan = await get_rerank_plan()
        fetch_k = max(top_k, plan.fetch_k) if plan.mode == "model" else top_k

        query_dense = await EmbeddingService.generate_embedding(query)
        if not query_dense:
            return LayerSnapshot(layer="L3", status="error", error="embedding generation failed")

        query_sparse: dict[str, Any] | None = await sync_to_async(SparseEncoderService.encode)(
            query
        )
        if not query_sparse or not query_sparse.get("indices"):
            query_sparse = None

        all_results: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str, int]] = set()

        # 单仓检索（含 EXCL-02 排除过滤），返回该仓"已过滤"的命中列表（未去重）。
        # 抽成内部协程以便有界并发：matcher 构造 / search 异常一律 fail-closed 返回 []。
        sem = asyncio.Semaphore(_RAG_REPO_CONCURRENCY)

        async def _search_one(repo_id: str) -> list[dict[str, Any]]:
            async with sem:
                try:
                    matcher = await build_matcher_for_repo(repo_id)
                except Exception as e:  # noqa: BLE001 — 构造失败一律 fail-closed
                    logger.warning("rag_search_matcher_build_failed", repo_id=repo_id, error=str(e))
                    log_exclusion_blocked(surface="rag", repository_id=repo_id, rel_path="")
                    return []
                try:
                    results = await BranchAwareSearchService.search(
                        repo_id,
                        query_dense,
                        query_sparse=query_sparse,
                        branch_name=branch_name,
                        top_k=fetch_k,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("rag_search_single_repo_failed", repo_id=repo_id, error=str(e))
                    return []
                out: list[dict[str, Any]] = []
                for r in results:
                    payload = r.get("payload", {})
                    file_path = payload.get("file_path", "")
                    try:
                        excluded = matcher.is_excluded(file_path)
                    except Exception:  # noqa: BLE001 — 判定异常 → 丢弃该项（fail-closed）
                        excluded = True
                    if excluded:
                        log_exclusion_blocked(
                            surface="rag", repository_id=repo_id, rel_path=str(file_path)
                        )
                        continue
                    out.append({**r, "repository_id": repo_id})
                return out

        # 有界并发执行所有仓库的检索；**按 repo_ids 原序合并 + 去重**，保证与串行版
        # 完全一致的去重/排序结果（zero-drift：先到先得 key 仅取决于合并顺序，不取决
        # 于实际完成顺序）。
        per_repo = await asyncio.gather(
            *[_search_one(rid) for rid in repo_ids], return_exceptions=True
        )
        for repo_id, res in zip(repo_ids, per_repo, strict=True):
            if isinstance(res, BaseException):
                logger.warning("rag_search_single_repo_failed", repo_id=repo_id, error=str(res))
                continue
            for r in res:
                payload = r.get("payload", {})
                key = (
                    r["repository_id"],
                    payload.get("file_path", ""),
                    payload.get("chunk_index", 0),
                )
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_results.append(r)

        all_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        # 精排阶段（单一卡点）：model → 外部 reranker，heuristic → 词法重排，
        # off → 原 score 截断。已 fail-open，异常退回 all_results[:top_k]。
        rerank_meta: dict[str, Any] = {}
        reordered = await reorder(
            query, all_results, top_k=top_k, plan=plan, out_meta=rerank_meta
        )
        return LayerSnapshot(
            layer="L3",
            status="ok",
            result_count=len(all_results),
            items=reordered,
            extra={"rerank": rerank_meta} if rerank_meta else None,
        )
    except Exception as e:
        logger.warning("rag_search_failed", query=query[:100], error=str(e))
        return LayerSnapshot(layer="L3", status="error", error=str(e))


__all__ = ["search_rag"]
