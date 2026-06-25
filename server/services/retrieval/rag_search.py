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
import time
from typing import Any

import structlog

from services.exclusion import build_matcher_for_repo, log_exclusion_blocked
from services.retrieval.types import LayerSnapshot

logger = structlog.get_logger(__name__)

# 多仓 RAG 并发上限：每仓一次 Qdrant 混合检索，跨 50+ 仓时串行延迟线性累加。
# 用有界并发把延迟从 O(N) 降到 O(N/并发)，上限防止打爆 Qdrant 连接/worker。
_RAG_REPO_CONCURRENCY = 8
# 单仓检索超时：一个慢 Qdrant 查询不得拖垮整波检索（避免 turn 被无限拉长 →
# 客户端/网关超时中断 → 前端 network error）。超时单仓 fail-soft 返回 []。
_RAG_PER_REPO_TIMEOUT_S = 20.0


def _record_rag_metric(
    *,
    start: float,
    all_results: list[dict[str, Any]],
    stage_embedding_ms: float,
    stage_sparse_ms: float,
    stage_qdrant_ms: float,
    stage_rerank_ms: float,
    rag_status: str,
) -> None:
    """search_rag 出口聚合一行召回指标（RAG-01，best-effort，绝不反噬召回主流程）。

    指标只记**聚合数值**：召回条数 + 分层耗时（embedding/sparse/qdrant/rerank）+
    top score，按来源（``call_source`` contextvar，区分 MCP/对话/workflow）打标。
    召回内容（query/chunk 原文）**绝不**进 labels（基数控制 + 防泄漏，§A.4 /
    T-72-04-02），只走 RetrievalTrace 留痕。整段 ``try/except: pass``：计时/写入
    任何异常都不影响召回返回（zero-drift 行为契约保持）。
    """
    try:
        from agents.call_source import get_call_source
        from common.request_metrics import record_request_metric

        total_ms = int((time.perf_counter() - start) * 1000)
        top_score = round(all_results[0].get("score", 0.0), 4) if all_results else 0
        labels: dict[str, Any] = {
            "call_source": get_call_source() or "",
            "recall_count": len(all_results),
            "top_score": top_score,
            "stage_embedding_ms": round(stage_embedding_ms, 2),
            "stage_sparse_ms": round(stage_sparse_ms, 2),
            "stage_qdrant_ms": round(stage_qdrant_ms, 2),
            "stage_rerank_ms": round(stage_rerank_ms, 2),
        }
        if rag_status != "ok":
            labels["rag_status"] = rag_status
        record_request_metric(
            source="rag",
            route="search_rag",
            method="RAG",
            status_code=200 if rag_status == "ok" else 500,
            error_class="none" if rag_status == "ok" else "system",
            duration_ms=total_ms,
            labels=labels,
        )
    except Exception:  # noqa: BLE001 —— 指标写入绝不反噬召回主流程
        pass


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
    # RAG-01 分层计时：旁路累计各阶段耗时，**不改**步骤顺序/去重/排序/返回结构
    # （zero-drift）。早退/异常路径也尽量记一行 status 标签。
    _metric_start = time.perf_counter()
    _stage_embedding_ms = 0.0
    _stage_sparse_ms = 0.0
    _stage_qdrant_ms = 0.0
    _stage_rerank_ms = 0.0
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

        _t0 = time.perf_counter()
        query_dense = await EmbeddingService.generate_embedding(query)
        _stage_embedding_ms = (time.perf_counter() - _t0) * 1000
        if not query_dense:
            _record_rag_metric(
                start=_metric_start,
                all_results=[],
                stage_embedding_ms=_stage_embedding_ms,
                stage_sparse_ms=_stage_sparse_ms,
                stage_qdrant_ms=_stage_qdrant_ms,
                stage_rerank_ms=_stage_rerank_ms,
                rag_status="error",
            )
            return LayerSnapshot(layer="L3", status="error", error="embedding generation failed")

        _t0 = time.perf_counter()
        query_sparse: dict[str, Any] | None = await sync_to_async(SparseEncoderService.encode)(
            query
        )
        _stage_sparse_ms = (time.perf_counter() - _t0) * 1000
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
                    results = await asyncio.wait_for(
                        BranchAwareSearchService.search(
                            repo_id,
                            query_dense,
                            query_sparse=query_sparse,
                            branch_name=branch_name,
                            top_k=fetch_k,
                        ),
                        timeout=_RAG_PER_REPO_TIMEOUT_S,
                    )
                except TimeoutError:
                    logger.warning("rag_search_single_repo_timeout", repo_id=repo_id, timeout_s=_RAG_PER_REPO_TIMEOUT_S)
                    return []
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
        _t0 = time.perf_counter()
        per_repo = await asyncio.gather(
            *[_search_one(rid) for rid in repo_ids], return_exceptions=True
        )
        _stage_qdrant_ms = (time.perf_counter() - _t0) * 1000
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
        _t0 = time.perf_counter()
        reordered = await reorder(
            query, all_results, top_k=top_k, plan=plan, out_meta=rerank_meta
        )
        _stage_rerank_ms = (time.perf_counter() - _t0) * 1000
        _record_rag_metric(
            start=_metric_start,
            all_results=all_results,
            stage_embedding_ms=_stage_embedding_ms,
            stage_sparse_ms=_stage_sparse_ms,
            stage_qdrant_ms=_stage_qdrant_ms,
            stage_rerank_ms=_stage_rerank_ms,
            rag_status="ok",
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
        _record_rag_metric(
            start=_metric_start,
            all_results=[],
            stage_embedding_ms=_stage_embedding_ms,
            stage_sparse_ms=_stage_sparse_ms,
            stage_qdrant_ms=_stage_qdrant_ms,
            stage_rerank_ms=_stage_rerank_ms,
            rag_status="error",
        )
        return LayerSnapshot(layer="L3", status="error", error=str(e))


__all__ = ["search_rag"]
