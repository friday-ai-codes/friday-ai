"""跨仓 API 扩散器 —— initial implementation HybridSearch wave（per work item）。

当 RAG 命中 ApiCallSite chunk 时，扩散到对端 Endpoint chunk（via CrossRepoApiCall join）。
当 RAG 命中 Endpoint chunk 时，反向扩散到 ApiCallSite chunk。

设计原则：
- 纯 async ORM，最多 4 次 SQL（select_related 防 N+1）
- ENABLE_CROSS_REPO_ENRICHMENT=False 时调用方短路，本模块不读 settings（per Pitfall 5）
- 返回 NeighborMetadata(hop=3, edge_type="API_CALLS")
- metadata 字段与 find_related._tpl_api_calls 对齐（work item）

CI grep gate:
  rg "settings\\.ENABLE_CROSS_REPO_ENRICHMENT" code_relations/cross_repo_expander.py
必须 0 命中（本模块不读 settings）。
"""

from __future__ import annotations

from typing import Any, Callable

import structlog
from asgiref.sync import sync_to_async

from services.retrieval.types import NeighborMetadata

logger = structlog.get_logger(__name__)

__all__ = ["expand_cross_repo"]

ReasonFn = Callable[..., str]


async def expand_cross_repo(
    *,
    rag_items: list[dict[str, Any]],
    repo_ids: list[str],
    reason_fn: ReasonFn,
    exclude_chunk_ids: frozenset[str] | None = None,
) -> list[NeighborMetadata]:
    """wave 跨仓 API 扩散主入口。

    Args:
        rag_items: RAG 命中条目列表（含 file_path / id 字段）。
        repo_ids: 当前查询仓库 ID 列表。
        reason_fn: reason 生成函数；签名 ``(edge_type, source_file, target_file, metadata) -> str``。
        exclude_chunk_ids: 已知 chunk_id 集合（hop1+hop2+rag），用于三重去重。

    Returns:
        ``list[NeighborMetadata]``，``hop=3``，``edge_type="API_CALLS"``。
    """
    if not rag_items:
        return []

    file_paths: list[str] = [
        item["file_path"]
        for item in rag_items
        if item.get("file_path")
    ]
    if not file_paths:
        return []

    exclude: frozenset[str] = exclude_chunk_ids or frozenset()

    logger.info(
        "cross_repo_wave3_started",
        file_path_count=len(file_paths),
        repo_count=len(repo_ids),
    )

    # 方向 A：ApiCallSite chunk → Endpoint chunk
    call_side = await _expand_call_site_to_endpoint(
        file_paths=file_paths,
        exclude=exclude,
        reason_fn=reason_fn,
    )

    # 方向 B：Endpoint chunk → ApiCallSite chunk
    endpoint_side = await _expand_endpoint_to_call_site(
        file_paths=file_paths,
        exclude=exclude,
        reason_fn=reason_fn,
    )

    results = call_side + endpoint_side

    logger.info(
        "cross_repo_wave3_done",
        call_side_count=len(call_side),
        endpoint_side_count=len(endpoint_side),
        total=len(results),
    )
    return results


@sync_to_async  # type: ignore[misc]
def _fetch_call_site_to_endpoint(
    file_paths: list[str],
    exclude: frozenset[str],
) -> list[tuple[str, str, dict[str, Any]]]:
    """同步 ORM：ApiCallSite → CrossRepoApiCall → Endpoint → ChunkRegistry。

    Returns:
        [(target_chunk_id, caller_file_for_reason, metadata), ...]
    """
    from code_relations.models import ChunkRegistry
    from codegraph.models import ApiCallSite, CrossRepoApiCall

    call_sites = list(
        ApiCallSite.objects.filter(caller_file__in=file_paths).select_related("api_wrapper")
    )
    if not call_sites:
        return []

    cross_calls = list(
        CrossRepoApiCall.objects.filter(call_site__in=call_sites).select_related("endpoint")
    )
    if not cross_calls:
        return []

    endpoint_files = list({cc.endpoint.file_path for cc in cross_calls})
    chunk_map: dict[str, str] = {}
    for reg in ChunkRegistry.objects.filter(file_path__in=endpoint_files).only(
        "chunk_id", "file_path"
    ):
        fp = reg.file_path
        if fp not in chunk_map:
            chunk_map[fp] = str(reg.chunk_id)

    out: list[tuple[str, str, dict[str, Any]]] = []
    for cc in cross_calls:
        ep = cc.endpoint
        tgt_chunk_id = chunk_map.get(ep.file_path)
        if not tgt_chunk_id or tgt_chunk_id in exclude:
            continue
        fn_sym = ""
        if cc.call_site.api_wrapper_id:
            fn_sym = cc.call_site.api_wrapper.function_symbol
        meta: dict[str, Any] = {
            "function_symbol": fn_sym,
            "caller_file": cc.call_site.caller_file,
            "line_number": cc.call_site.line_number,
            "http_method": ep.http_method,
            "url_path": ep.url_path,
            "match_confidence": float(cc.match_confidence),
            "direction": "calls",
        }
        out.append((tgt_chunk_id, cc.call_site.caller_file, meta))
    return out


@sync_to_async  # type: ignore[misc]
def _fetch_endpoint_to_call_site(
    file_paths: list[str],
    exclude: frozenset[str],
) -> list[tuple[str, str, dict[str, Any]]]:
    """同步 ORM：Endpoint → CrossRepoApiCall → ApiCallSite → ChunkRegistry。

    Returns:
        [(target_chunk_id, endpoint_url_for_reason, metadata), ...]
    """
    from code_relations.models import ChunkRegistry
    from codegraph.models import CrossRepoApiCall, Endpoint

    endpoints = list(Endpoint.objects.filter(file_path__in=file_paths))
    if not endpoints:
        return []

    cross_calls = list(
        CrossRepoApiCall.objects.filter(endpoint__in=endpoints).select_related(
            "call_site__api_wrapper"
        )
    )
    if not cross_calls:
        return []

    caller_files = list({cc.call_site.caller_file for cc in cross_calls})
    chunk_map: dict[str, str] = {}
    for reg in ChunkRegistry.objects.filter(file_path__in=caller_files).only(
        "chunk_id", "file_path"
    ):
        fp = reg.file_path
        if fp not in chunk_map:
            chunk_map[fp] = str(reg.chunk_id)

    out: list[tuple[str, str, dict[str, Any]]] = []
    for cc in cross_calls:
        cs = cc.call_site
        ep = cc.endpoint
        tgt_chunk_id = chunk_map.get(cs.caller_file)
        if not tgt_chunk_id or tgt_chunk_id in exclude:
            continue
        fn_sym = ""
        if cs.api_wrapper_id:
            fn_sym = cs.api_wrapper.function_symbol
        meta: dict[str, Any] = {
            "function_symbol": fn_sym,
            "caller_file": cs.caller_file,
            "line_number": cs.line_number,
            "http_method": ep.http_method,
            "url_path": ep.url_path,
            "match_confidence": float(cc.match_confidence),
            "direction": "called_by",
        }
        out.append((tgt_chunk_id, ep.url_path, meta))
    return out


async def _expand_call_site_to_endpoint(
    *,
    file_paths: list[str],
    exclude: frozenset[str],
    reason_fn: ReasonFn,
) -> list[NeighborMetadata]:
    """ApiCallSite → Endpoint 方向扩散。"""
    pairs = await _fetch_call_site_to_endpoint(file_paths, exclude)
    return [
        NeighborMetadata(
            chunk_id=chunk_id,
            file_path=meta.get("caller_file", "<unknown>"),
            line_start=None,
            line_end=None,
            edge_type="API_CALLS",
            weight=float(meta.get("match_confidence", 0.7)),
            reason=reason_fn(
                "API_CALLS",
                source_file=meta.get("caller_file"),
                target_file=meta.get("url_path"),
                metadata=meta,
            ),
            hop=3,
        )
        for chunk_id, _, meta in pairs
    ]


async def _expand_endpoint_to_call_site(
    *,
    file_paths: list[str],
    exclude: frozenset[str],
    reason_fn: ReasonFn,
) -> list[NeighborMetadata]:
    """Endpoint → ApiCallSite 方向扩散。"""
    pairs = await _fetch_endpoint_to_call_site(file_paths, exclude)
    return [
        NeighborMetadata(
            chunk_id=chunk_id,
            file_path=meta.get("caller_file", "<unknown>"),
            line_start=None,
            line_end=None,
            edge_type="API_CALLS",
            weight=float(meta.get("match_confidence", 0.7)),
            reason=reason_fn(
                "API_CALLS",
                source_file=meta.get("url_path"),
                target_file=meta.get("caller_file"),
                metadata=meta,
            ),
            hop=3,
        )
        for chunk_id, _, meta in pairs
    ]
