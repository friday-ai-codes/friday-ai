"""find_related Python API + explain_neighbor reason 模板（per implementation）。

兑现 success criterion 第三条 "MAX_HOPS=2 硬上限" 在 ``find_related`` API 入口（防 LLM
通过 implementation MCP tool 传 hops=10 引发指数级 ORM 扩散），并为 implementation 提前抹平
``reason`` 字段（让 LLM 理解相关性来源）。

本模块两职责：

1. ``explain_neighbor(edge_type, *, source_file, target_file, metadata)`` —— 6 类
   ``EdgeType`` 模板驱动 reason 字符串生成器；纯函数，无 ORM / Django 依赖；
   metadata 缺失 / source_file=None / target_file=None / unknown edge_type 全部
   走降级 fallback，不抛 ``KeyError``。模板表（per contract + plan must-haves）：

   - ``CALL`` → ``"caller of {target_file} via direct call"``（无 → ``"via direct call"``）
   - ``IMPORT`` → ``"imports module from {target_file}"``（无 → ``"imports module"``）
   - ``SAME_FILE`` → ``"same file as {source_file}"``（无 → ``"same file group"``）
   - ``TEST_OF`` → ``"test of {target_file}"``（无 → ``"test relationship"``）
   - ``CO_CHANGED`` → ``"co-changed with {target_file} × {commit_count} commits"``
     （metadata.commit_count 缺 → ``"co-changed with {target_file} × recent history"``）
   - ``SEMANTIC`` → ``"semantically similar (score={similarity:.2f})"``（缺 → ``"semantically similar"``）
   - 其他 → ``"related via {edge_type}"`` 通用 fallback

2. ``find_related(start_chunk_id, *, repo_ids, relation_types, hops, direction, limit)``
   —— implementation MCP tool 包一层即可暴露的 Python API；直接查 ChunkEdge ORM，复用
   ``hop2_expander.assert_hops_within_limit`` ValueError 守卫；hops=2 时复用
   ``hop2_expander.fetch_hop2_edges`` 走 downstream 二跳扩散（implementation notes
   "二跳扩散仅 downstream"——避免反向二跳指数级 fan-in）。

**不读** codegraph 启用开关（Pitfall 5）：本模块只做 reason 模板与 ORM 扩散；
启停决策由 implementation MCP tool 在外层守卫；CI grep gate
``rg "settings\\.ENABLE_CODEGRAP[H]" services/retrieval/`` 必须 0 命中。
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

import structlog
from asgiref.sync import sync_to_async

from services.retrieval.hop2_expander import (
    assert_hops_within_limit,
    fetch_hop2_edges,
)
from services.retrieval.types import NeighborMetadata

__all__ = ["explain_neighbor", "find_related"]

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Section 1: explain_neighbor —— 6 类 EdgeType reason 模板（纯函数）
# ---------------------------------------------------------------------------


def _tpl_call(
    *, source_file: str | None, target_file: str | None, metadata: dict[str, Any]
) -> str:
    """CALL → "caller of {target_file} via direct call"；无 target → fallback。"""
    if target_file:
        return f"caller of {target_file} via direct call"
    return "via direct call"


def _tpl_import(
    *, source_file: str | None, target_file: str | None, metadata: dict[str, Any]
) -> str:
    """IMPORT → "imports module from {target_file}"；无 target → fallback。"""
    if target_file:
        return f"imports module from {target_file}"
    return "imports module"


def _tpl_same_file(
    *, source_file: str | None, target_file: str | None, metadata: dict[str, Any]
) -> str:
    """SAME_FILE → "same file as {source_file}"；无 source → fallback。"""
    if source_file:
        return f"same file as {source_file}"
    return "same file group"


def _tpl_test_of(
    *, source_file: str | None, target_file: str | None, metadata: dict[str, Any]
) -> str:
    """TEST_OF → "test of {target_file}"；无 target → fallback。"""
    if target_file:
        return f"test of {target_file}"
    return "test relationship"


def _tpl_co_changed(
    *, source_file: str | None, target_file: str | None, metadata: dict[str, Any]
) -> str:
    """CO_CHANGED → "co-changed with {target_file} × {commit_count} commits"。

    缺 metadata.commit_count → "× recent history"；缺 target_file → 用通用占位符。
    """
    descriptor = target_file if target_file else "related chunk"
    commit_count = metadata.get("commit_count")
    # bool 是 int 的子类（True/False）；isinstance(True, int) → True，
    # 输出会变成 "× True commits"，与 _tpl_semantic 的 bool 排除模式对齐
    if (
        isinstance(commit_count, int)
        and not isinstance(commit_count, bool)
        and commit_count > 0
    ):
        return f"co-changed with {descriptor} × {commit_count} commits"
    return f"co-changed with {descriptor} × recent history"


def _tpl_semantic(
    *, source_file: str | None, target_file: str | None, metadata: dict[str, Any]
) -> str:
    """SEMANTIC → "semantically similar (score={similarity:.2f})"。

    缺 metadata.similarity → "semantically similar"。
    """
    similarity = metadata.get("similarity")
    if isinstance(similarity, (int, float)) and not isinstance(similarity, bool):
        return f"semantically similar (score={float(similarity):.2f})"
    return "semantically similar"


class _TemplateFn(Protocol):
    """``_TEMPLATE_REGISTRY`` value 类型——明确 keyword-only 三参数签名。

    所有 ``_tpl_*`` 函数必须接受 ``source_file`` / ``target_file`` / ``metadata``
    keyword-only 参数；mypy 借此校验调用 ``template_fn(...)`` 时参数完整。
    """

    def __call__(
        self,
        *,
        source_file: str | None,
        target_file: str | None,
        metadata: dict[str, Any],
    ) -> str: ...


def _tpl_api_calls(
    *, source_file: str | None, target_file: str | None, metadata: dict[str, Any]
) -> str:
    """API_CALLS → 跨仓 API 调用关系 reason 模板（implementation）。

    metadata 字段（由 cross_repo_expander / rebuild_cross_repo_edges 写入）：
    - function_symbol: str  —— ApiWrapper 函数名（如 fetchTopicFinished）
    - caller_file: str      —— ApiCallSite 文件路径（如 api/topic.ts）
    - line_number: int      —— ApiCallSite 行号
    - http_method: str      —— HTTP method（GET/POST/...）
    - url_path: str         —— URL 路径（如 /study-flow/topic/finished）
    - direction: "calls" | "called_by"  —— 边方向
    """
    direction = metadata.get("direction", "calls")
    fn = metadata.get("function_symbol", "")
    caller_file = metadata.get("caller_file") or source_file or ""
    line = metadata.get("line_number")
    method = metadata.get("http_method", "")
    url = metadata.get("url_path", "")

    loc = f"{caller_file}:{line}" if line else caller_file
    api_sig = f"via {method} {url}".strip() if (method or url) else ""

    if direction == "calls":
        subject = f"calls {fn} ({loc})" if fn else (loc or "cross-repo API")
        parts = [p for p in [subject, api_sig] if p]
        return ", ".join(parts) if parts else "calls cross-repo API"
    else:
        subject = f"called by {fn} ({loc})" if fn else f"called by ({loc})"
        parts = [p for p in [subject, api_sig] if p]
        return ", ".join(parts) if parts else "called by cross-repo client"


_TEMPLATE_REGISTRY: dict[str, _TemplateFn] = {
    "CALL": _tpl_call,
    "IMPORT": _tpl_import,
    "SAME_FILE": _tpl_same_file,
    "TEST_OF": _tpl_test_of,
    "CO_CHANGED": _tpl_co_changed,
    "SEMANTIC": _tpl_semantic,
    "API_CALLS": _tpl_api_calls,  # implementation
}
"""模板分发表（dict[edge_type, template_fn]）—— 比 if-else 链便于扩展（per plan
"模板用 dict[str, Callable] 驱动，方便扩展"）。"""


def explain_neighbor(
    edge_type: str,
    *,
    source_file: str | None = None,
    target_file: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """生成 NeighborMetadata.reason 字段：8 类模板 + graceful fallback（implementation）。

    Args:
        edge_type: ``EdgeType`` 字面值（``CALL`` / ``IMPORT`` / ``SAME_FILE`` /
            ``TEST_OF`` / ``CO_CHANGED`` / ``SEMANTIC`` / ``IMPLEMENTS`` /
            ``API_CALLS``）；未知 → fallback。
        source_file: source chunk 文件路径，可选；缺失走模板 fallback 分支。
        target_file: target chunk 文件路径，可选；缺失走模板 fallback 分支。
        metadata: ChunkEdge.metadata JSON 字典，可选；``None`` / 空 dict / 缺
            字段 → graceful fallback 不抛 ``KeyError``。

    Returns:
        非空 reason 字符串。形如：

        - ``"caller of src/utils.py via direct call"``
        - ``"co-changed with src/related.py × 7 commits"``
        - ``"semantically similar (score=0.85)"``
        - ``"related via FOO"``（unknown edge_type）

    Examples:
        >>> explain_neighbor("CALL", target_file="src/utils.py")
        'caller of src/utils.py via direct call'
        >>> explain_neighbor("CO_CHANGED", target_file="x.py", metadata={"commit_count": 7})
        'co-changed with x.py × 7 commits'
        >>> explain_neighbor("UNKNOWN_TYPE")
        'related via UNKNOWN_TYPE'
    """
    safe_metadata: dict[str, Any] = metadata if metadata is not None else {}
    template_fn = _TEMPLATE_REGISTRY.get(edge_type)
    if template_fn is None:
        # unknown edge_type 不抛错，统一 fallback；空字符串走 "related via " 兜底
        return f"related via {edge_type}" if edge_type else "related (unknown edge type)"
    return template_fn(
        source_file=source_file,
        target_file=target_file,
        metadata=safe_metadata,
    )


# ---------------------------------------------------------------------------
# Section 2: find_related Python API —— ChunkEdge ORM 扩散 + ValueError 守卫
# ---------------------------------------------------------------------------


_VALID_DIRECTIONS: frozenset[str] = frozenset({"downstream", "upstream", "both"})


def _assert_direction_valid(direction: str) -> None:
    """``direction`` 必须三选一；其他 → ``ValueError`` 含具体值。"""
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(
            f"direction={direction!r} invalid; must be one of "
            f"'downstream', 'upstream', 'both'"
        )


@sync_to_async
def _fetch_hop1_edges(
    start_chunk_id: str,
    *,
    repo_ids: list[str],
    relation_types: list[str] | None,
    direction: str,
    limit: int,
) -> list[tuple[str, str, str, float, dict[str, Any]]]:
    """单次 ChunkEdge ORM 拉一跳邻居边（含 metadata 用于 explain_neighbor）。

    Returns:
        ``list[(neighbor_chunk_id_str, edge_type_str, weight_float,
        edge_metadata_dict)]`` —— ``neighbor_chunk_id`` 为 target（downstream）
        或 source（upstream）；``both`` 双向各拉 ``limit//2 + 1`` 然后由调用方
        合并截断到 ``limit``。

        实际返回 5-tuple ``(start_chunk_id, neighbor_chunk_id, edge_type,
        weight, metadata)`` —— start 用于自环过滤，neighbor 用于 NeighborMetadata。
    """
    from code_relations.models import ChunkEdge

    base = ChunkEdge.objects.filter(repository_id__in=repo_ids)
    if relation_types:
        base = base.filter(edge_type__in=relation_types)

    half_limit = max(1, limit // 2)
    out: list[tuple[str, str, str, float, dict[str, Any]]] = []

    if direction in ("downstream", "both"):
        per_dir_limit = half_limit if direction == "both" else limit
        qs = (
            base.filter(source_chunk_id=start_chunk_id)
            .only("source_chunk_id", "target_chunk_id", "edge_type", "weight", "metadata")
            .order_by("-weight")[:per_dir_limit]
        )
        for edge in qs:
            out.append(
                (
                    str(edge.source_chunk_id),
                    str(edge.target_chunk_id),
                    str(edge.edge_type),
                    float(edge.weight),
                    dict(edge.metadata or {}),
                )
            )

    if direction in ("upstream", "both"):
        # upstream：用 idx_chunkedge_target 反向索引（implementation 落）
        per_dir_limit = half_limit if direction == "both" else limit
        qs = (
            base.filter(target_chunk_id=start_chunk_id)
            .only("source_chunk_id", "target_chunk_id", "edge_type", "weight", "metadata")
            .order_by("-weight")[:per_dir_limit]
        )
        for edge in qs:
            # upstream：邻居是 source（caller / importer）
            out.append(
                (
                    str(edge.target_chunk_id),  # start (self)
                    str(edge.source_chunk_id),  # neighbor (upstream)
                    str(edge.edge_type),
                    float(edge.weight),
                    dict(edge.metadata or {}),
                )
            )

    return out


@sync_to_async
def _resolve_chunk_files(
    chunk_ids: set[str],
) -> dict[str, tuple[str, int | None, int | None]]:
    """单次 ChunkRegistry.in_bulk 拉 (file_path, line_start, line_end)。

    缺失 → 不入 dict（调用方走 ``"<unknown>"`` fallback）。
    """
    if not chunk_ids:
        return {}

    from code_relations.models import ChunkRegistry

    registry_map = ChunkRegistry.objects.in_bulk(
        list(chunk_ids), field_name="chunk_id"
    )
    return {
        str(k): (v.file_path, v.line_start, v.line_end)
        for k, v in registry_map.items()
    }


def _build_neighbor(
    *,
    start_chunk_id: str,
    neighbor_chunk_id: str,
    edge_type: str,
    weight: float,
    edge_metadata: dict[str, Any],
    file_meta: dict[str, tuple[str, int | None, int | None]],
    hop: int,
) -> NeighborMetadata:
    """组装单个 NeighborMetadata —— 调 explain_neighbor 拼 reason。"""
    start_meta = file_meta.get(start_chunk_id)
    neighbor_meta = file_meta.get(neighbor_chunk_id)
    source_file = start_meta[0] if start_meta else None
    target_file = neighbor_meta[0] if neighbor_meta else None

    return NeighborMetadata(
        chunk_id=neighbor_chunk_id,
        file_path=target_file if target_file else "<unknown>",
        line_start=neighbor_meta[1] if neighbor_meta else None,
        line_end=neighbor_meta[2] if neighbor_meta else None,
        edge_type=edge_type,
        weight=weight,
        reason=explain_neighbor(
            edge_type,
            source_file=source_file,
            target_file=target_file,
            metadata=edge_metadata,
        ),
        hop=hop,
    )


async def find_related(
    start_chunk_id: str,
    *,
    repo_ids: list[str],
    relation_types: list[str] | None = None,
    hops: int = 1,
    direction: Literal["downstream", "upstream", "both"] = "both",
    limit: int = 20,
) -> list[NeighborMetadata]:
    """查 chunk 相关邻居（一跳 / 二跳，多方向，多关系类型过滤）。

    implementation MCP tool 仅需包一层 Pydantic schema delegate 到本函数（success criteria）。

    Args:
        start_chunk_id: 起点 chunk_id（UUID 字符串）。
        repo_ids: 候选仓库 ID 列表；空 → 立即返回 ``[]`` 不查 ORM。
        relation_types: 限定 ``EdgeType`` 列表；``None`` 或 ``[]`` → 不过滤
            （implementation notes："空列表语义=未指定过滤"）。
        hops: 跳数（1 或 2）；``> MAX_HOPS=2`` 或 ``< 0`` → ``ValueError``
            （复用 ``hop2_expander.assert_hops_within_limit``）。
        direction: ``"downstream"`` (源→目标) / ``"upstream"`` (目标→源 用
            ``idx_chunkedge_target`` 反向索引) / ``"both"`` (双向各取
            ``limit//2`` 合并去重)。其他 → ``ValueError``。
        limit: 输出邻居数上限（默认 20）。

    Returns:
        ``list[NeighborMetadata]``：
        - 按 ``(hop ASC, weight DESC)`` 排序；
        - 已对 ``chunk_id`` 去重（保 max weight + 较小 hop）；
        - ``reason`` 字段由 ``explain_neighbor`` 模板生成。

    Raises:
        ValueError: ``hops`` 越界 或 ``direction`` 非三选一。

    Examples:
        >>> # implementation MCP tool 调用示例（伪代码）
        >>> neighbors = await find_related(
        ...     "abc-uuid",
        ...     repo_ids=["repo-1"],
        ...     relation_types=["CALL", "IMPORT"],
        ...     hops=2,
        ...     direction="downstream",
        ...     limit=20,
        ... )
    """
    assert_hops_within_limit(hops)
    _assert_direction_valid(direction)

    if not repo_ids:
        return []

    if hops == 0:
        return []

    # ---- hop1：分方向拉边，保留方向标签为 hop2 反向扩散铺路（work item） -----
    # 同方向 hop1 + 同方向 hop2 才能正确解释「upstream hops=2 = 调用者的调用者」；
    # 把 hop1 集合按 direction 拆开并独立扩散，避免 both 模式下 upstream 那段
    # 的 hop2 静默退化成 downstream（work item 之前的失败语义）。
    downstream_hop1: list[tuple[str, str, str, float, dict[str, Any]]] = (
        await _fetch_hop1_edges(
            start_chunk_id,
            repo_ids=repo_ids,
            relation_types=relation_types,
            direction="downstream",
            limit=limit,
        )
        if direction in ("downstream", "both")
        else []
    )
    upstream_hop1: list[tuple[str, str, str, float, dict[str, Any]]] = (
        await _fetch_hop1_edges(
            start_chunk_id,
            repo_ids=repo_ids,
            relation_types=relation_types,
            direction="upstream",
            limit=limit,
        )
        if direction in ("upstream", "both")
        else []
    )
    hop1_edges = downstream_hop1 + upstream_hop1

    if not hop1_edges and hops == 1:
        return []

    # 收集需要 in_bulk 的 chunk_id（start + 所有 hop1 邻居）
    needed_chunk_ids: set[str] = {start_chunk_id}
    for _start, neighbor, _et, _w, _meta in hop1_edges:
        needed_chunk_ids.add(neighbor)

    # ---- hop2：work item 修复——按 direction 反向扩散 -----------------------
    # downstream hop2: 从 downstream hop1 targets 向下扩散一跳（被调者的被调者）
    # upstream hop2:   从 upstream hop1 sources 向上扩散一跳（调用者的调用者）
    hop2_neighbor_chunks: list[tuple[str, str, str, float, dict[str, Any]]] = []
    if hops == 2 and hop1_edges:
        all_hop1_ids: set[str] = {n for _s, n, _e, _w, _m in hop1_edges}
        reject: set[str] = {start_chunk_id} | all_hop1_ids

        if downstream_hop1:
            ds_h1_ids = [n for _s, n, _e, _w, _m in downstream_hop1]
            raw_ds_h2 = await fetch_hop2_edges(
                ds_h1_ids,
                repo_ids,
                relation_types=relation_types,
                direction="downstream",
            )
            for src, tgt, et, w, em in raw_ds_h2:
                if tgt in reject or tgt == src:
                    continue
                hop2_neighbor_chunks.append((src, tgt, et, w, em))
                needed_chunk_ids.add(tgt)

        if upstream_hop1:
            us_h1_ids = [n for _s, n, _e, _w, _m in upstream_hop1]
            raw_us_h2 = await fetch_hop2_edges(
                us_h1_ids,
                repo_ids,
                relation_types=relation_types,
                direction="upstream",
            )
            # upstream 边：source 是新的"调用者的调用者"，target 是 hop1 邻居
            for src, tgt, et, w, em in raw_us_h2:
                neighbor = src
                if neighbor in reject or neighbor == tgt:
                    continue
                hop2_neighbor_chunks.append((tgt, neighbor, et, w, em))
                needed_chunk_ids.add(neighbor)

    # ---- 单次 ChunkRegistry.in_bulk 拉 file_path / line_* 元数据 --------
    file_meta = await _resolve_chunk_files(needed_chunk_ids)

    # ---- 拼装 NeighborMetadata + 去重 + 排序 + limit -------------------
    by_chunk: dict[str, NeighborMetadata] = {}

    for _start, neighbor, edge_type, weight, edge_metadata in hop1_edges:
        if neighbor == start_chunk_id:
            continue
        nbr = _build_neighbor(
            start_chunk_id=start_chunk_id,
            neighbor_chunk_id=neighbor,
            edge_type=edge_type,
            weight=weight,
            edge_metadata=edge_metadata,
            file_meta=file_meta,
            hop=1,
        )
        # both 双向去重：同 chunk_id 保 max weight
        existing = by_chunk.get(neighbor)
        if existing is None or weight > existing.weight:
            by_chunk[neighbor] = nbr

    # contract: hop2 内部 dedup 仅需 first-wins（fetch_hop2_edges 已 weight desc 排序）
    # + hop1 优先 reject set。原死代码 ``existing = by_chunk.get(neighbor); if
    # existing is None or weight > existing.weight: by_chunk[neighbor] = nbr`` 在
    # 上面 `if neighbor in by_chunk: continue` 短路后必为 None / 必更新——已删除。
    for _src, neighbor, edge_type, weight, edge_metadata in hop2_neighbor_chunks:
        if neighbor in by_chunk:
            # hop1 优先（同 chunk_id 出现在 hop1 + hop2 → 保 hop1 强信号）
            continue
        by_chunk[neighbor] = _build_neighbor(
            start_chunk_id=start_chunk_id,
            neighbor_chunk_id=neighbor,
            edge_type=edge_type,
            weight=weight,
            edge_metadata=edge_metadata,
            file_meta=file_meta,
            hop=2,
        )

    sorted_neighbors = sorted(
        by_chunk.values(),
        key=lambda n: (n.hop, -n.weight),
    )

    return sorted_neighbors[:limit]
