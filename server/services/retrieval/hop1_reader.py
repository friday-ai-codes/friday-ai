"""一跳邻居 payload 直读器（per implementation / contract / contract）。

兑现 success criterion 第一条 —— "payload `related_chunks` 一跳扩散直读召回 chunk
自带快照（不走 Qdrant 二次查询，不走 ORM）"：

- ``extract_hop1_neighbors_raw``：纯函数，从 ``rag_items[*].payload['related_chunks']``
  解析 ``(target_chunk_id, edge_type, weight)`` 三元组，按 weight desc 二次裁剪
  到 ``TOP_NEIGHBORS_PER_HOP1=10``。malformed payload 走 graceful 降级（log
  warning + 跳过 source），**不退到 ORM**——D-Discretion 决策："payload 缺失走
  0 邻居比退 ORM 更稳"。

- ``resolve_neighbor_metadata``：async 函数，单次
  ``ChunkRegistry.objects.in_bulk(chunk_ids, field_name='chunk_id')`` 拉满
  邻居 ``file_path`` / ``line_start`` / ``line_end`` metadata，扁平到
  ``list[NeighborMetadata]``。无 N+1（用 mock 计数器在测试中守护）。
  ``ChunkRegistry`` 中缺失（payload 写时 chunk 在，读时已删——增量删除一致性
  implementation reconcile 兜底）→ ``file_path='<unknown>'`` + ``line_*=None`` +
  log debug。``line_start`` / ``line_end`` 为 NULL（per contract 历史数据未回填）→
  graceful pass-through 到 ``NeighborMetadata``。

**不读** codegraph 启用开关（Pitfall 5）：本模块只做 payload 解析与 ORM
metadata 拉取，启停决策由 plan 的 ``HybridSearchService`` 通过 Provider
注入处理；CI 守护 ``rg "settings\\.ENABLE_CODEGRAP[H]" services/retrieval/``
必须 0 命中。
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from code_relations.constants import TOP_NEIGHBORS_PER_HOP1
from services.retrieval.types import NeighborMetadata

__all__ = [
    "ReasonFn",
    "extract_hop1_neighbors_raw",
    "resolve_neighbor_metadata",
]

logger = structlog.get_logger(__name__)

def _is_uuid_str(value: str) -> bool:
    """``ChunkRegistry.in_bulk(field_name='chunk_id')`` 防御非 UUID 字符串。

    ``ChunkRegistry.chunk_id`` 是 UUIDField；in_bulk 传入非 UUID 会触发
    ``ValidationError``。生产路径 source_chunk_id / target_chunk_id 均为 UUID
    （payload 来自 rag_item.id），本守卫为测试环境占位符 + 增量同步异常数据
    的 last-mile guard。
    """
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


_UNKNOWN_FILE_PATH: str = "<unknown>"
"""ChunkRegistry 缺失时的 fallback file_path（per D-Deviation 1）。

plan 编排器在 graph_context markdown 渲染时按 ``file_path == "<unknown>"``
跳过该邻居，避免渲染出无效行。
"""


def _is_valid_neighbor_tuple(item: Any) -> bool:
    """校验单个 payload neighbor 是否为 ``[str, str, float|int]`` 三元组。

    payload_sync 写入格式固定 ``[chunk_id_str, edge_type_str, weight_float]``；
    任一字段类型错误或长度不为 3 → False。weight 接受 ``int``（JSON 数字常被
    解码为 int），后续显式 ``float()`` 转换。

    拒绝 ``NaN`` / ``±Inf`` / 越界（[0.0, 1.0] 之外）weight——
    ``isinstance(float('nan'), float) is True``，但 NaN 进 ``sorted()`` 不可排序
    （比较全部 False），会让 budget 估算异常 + graph_context markdown 出现
    ``w=nan`` / ``w=inf`` 污染 LLM 上下文。与 ChunkEdge.weight ``MinValueValidator(0.0)``
    / ``MaxValueValidator(1.0)`` 对齐。
    """
    if not isinstance(item, (list, tuple)):
        return False
    if len(item) != 3:
        return False
    cid, edge_type, weight = item
    if not isinstance(cid, str) or not isinstance(edge_type, str):
        return False
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        return False
    weight_f = float(weight)
    if not math.isfinite(weight_f):
        return False
    if weight_f < 0.0 or weight_f > 1.0:
        return False
    return True


def extract_hop1_neighbors_raw(
    rag_items: list[dict[str, Any]],
) -> dict[str, list[tuple[str, str, float]]]:
    """从 rag_items 解析 payload `related_chunks` 一跳邻居快照（纯函数，无 ORM）。

    Args:
        rag_items: ``rag_search.search_rag`` 返回的 items 列表，每个 dict 含
            ``id``（source chunk_id）+ ``payload['related_chunks']``。

    Returns:
        ``dict[source_chunk_id, list[(target_chunk_id, edge_type, weight)]]``：
        - 每个 source 最多 ``TOP_NEIGHBORS_PER_HOP1=10`` 个邻居
        - 列表内按 weight desc 排序
        - 同一 source 内重复 target_chunk_id 防御性 setdefault 保留先到
        - payload 缺失 / malformed → 该 source 不入 dict（log warning）
        - empty list → 该 source 不入 dict（静默，无 warning）

    **不会** 触发 ORM 查询；纯字典操作。
    """
    out: dict[str, list[tuple[str, str, float]]] = {}

    for item in rag_items:
        source_chunk_id = item.get("id")
        if not isinstance(source_chunk_id, str):
            logger.warning(
                "hop1_payload_malformed",
                chunk_id=source_chunk_id,
                reason="source_id_not_str",
            )
            continue

        payload = item.get("payload") or {}
        if "related_chunks" not in payload:
            logger.warning(
                "hop1_payload_malformed",
                chunk_id=source_chunk_id,
                reason="related_chunks_key_missing",
            )
            continue

        raw = payload["related_chunks"]
        if raw is None:
            logger.warning(
                "hop1_payload_malformed",
                chunk_id=source_chunk_id,
                reason="related_chunks_is_none",
            )
            continue

        if not isinstance(raw, list):
            logger.warning(
                "hop1_payload_malformed",
                chunk_id=source_chunk_id,
                reason="related_chunks_not_list",
                actual_type=type(raw).__name__,
            )
            continue

        if len(raw) == 0:
            continue

        if not all(_is_valid_neighbor_tuple(n) for n in raw):
            logger.warning(
                "hop1_payload_malformed",
                chunk_id=source_chunk_id,
                reason="neighbor_element_shape_invalid",
            )
            continue

        # source 内 target chunk_id 去重 (per contract)：max-wins，避免依赖隐式
        # "payload 已按 weight desc 排序" 契约。若 EdgeBuilder 将来 bug 写出
        # 重复 + 不按 weight desc，setdefault 会丢高 weight 边。
        seen: dict[str, tuple[str, str, float]] = {}
        for cid, edge_type, weight in raw:
            w = float(weight)
            existing = seen.get(cid)
            if existing is None or w > existing[2]:
                seen[cid] = (cid, edge_type, w)

        sorted_neighbors = sorted(seen.values(), key=lambda t: -t[2])

        # 同 source 重复出现：merge 而非覆盖（per contract），保留双方邻居 +
        # max-wins 去重 + 重新裁剪到 TOP_NEIGHBORS_PER_HOP1；warning 级别让
        # 运维可见 RAG 上游可能违反「不返回重复 chunk_id」契约。
        if source_chunk_id in out:
            logger.warning(
                "hop1_duplicate_source_merged",
                chunk_id=source_chunk_id,
            )
            existing_neighbors = out[source_chunk_id]
            merged_pool: dict[str, tuple[str, str, float]] = {
                t[0]: t for t in existing_neighbors
            }
            for cid, edge_type, w in sorted_neighbors:
                prev = merged_pool.get(cid)
                if prev is None or w > prev[2]:
                    merged_pool[cid] = (cid, edge_type, w)
            sorted_neighbors = sorted(merged_pool.values(), key=lambda t: -t[2])

        out[source_chunk_id] = sorted_neighbors[:TOP_NEIGHBORS_PER_HOP1]

    return out


ReasonFn = Callable[
    [str, str | None, str | None, dict[str, Any]],
    str,
]
"""``resolve_neighbor_metadata`` / ``expand_hop2`` 注入式 reason 生成器签名。

参数顺序：``(edge_type, source_file, target_file, metadata)``。implementation
升级——原 ``(edge_type, source_chunk_id)`` 签名让 ``hybrid_search`` 路径无法
传完整 metadata 给 ``explain_neighbor``，导致 reason 全部走 fallback；新签名让
``_enrichment_reason_fn`` 与 ``find_related._build_neighbor`` 拿到等价的
template 上下文（commit_count / similarity / target_file 等核心信号不再丢失）。
"""


async def resolve_neighbor_metadata(
    neighbor_tuples: (
        dict[str, list[tuple[str, str, float]]]
        | dict[str, list[tuple[str, str, float, dict[str, Any]]]]
    ),
    *,
    hop: int,
    reason_fn: ReasonFn,
) -> list[NeighborMetadata]:
    """单次 ``ChunkRegistry.in_bulk`` 拉满邻居 metadata，扁平到 NeighborMetadata 列表。

    Args:
        neighbor_tuples: ``extract_hop1_neighbors_raw`` 输出
            ``dict[source_chunk_id, list[(target_chunk_id, edge_type, weight)]]``，
            或 ``hop2_expander.expand_hop2`` 扩展后的 4-tuple 形式
            ``dict[source_chunk_id, list[(target, edge_type, weight, edge_metadata)]]``
            （edge_metadata 让 hop2 reason 透出 ChunkEdge.metadata 信号）。
        hop: 跳数标记（一跳=1，二跳=2）。
        reason_fn: 注入的 reason 生成函数，签名见 ``ReasonFn``。

    Returns:
        ``list[NeighborMetadata]``：
        - 跨 source 同 (target_chunk_id, edge_type) 合并保 ``max(weight)``
        - ``ChunkRegistry`` 缺失 → ``file_path='<unknown>'`` + ``line_*=None``
        - ``ChunkRegistry.line_start/line_end`` NULL → ``NeighborMetadata.line_*=None``

    **零 N+1**：仅一次 ``ChunkRegistry.objects.in_bulk(field_name='chunk_id')``——
    一次拉满 source + target 双侧 chunk_id 让 reason_fn 可拿到 source_file。
    """
    from code_relations.models import ChunkRegistry

    source_chunk_ids: set[str] = set(neighbor_tuples.keys())
    target_chunk_ids: set[str] = set()
    for tuples in neighbor_tuples.values():
        for t in tuples:
            target_chunk_ids.add(t[0])

    if not target_chunk_ids:
        return []

    # 同一次 in_bulk 拉满 source + target 双侧 chunk_id，让 reason_fn 可拿到
    # source_file（work item 升级前 source 侧不查 ORM，reason 模板缺 source_file）。
    # 过滤非 UUID 字符串：source_chunk_ids 在 prod 都是 UUID（payload 写入时为
    # rag_item.id），但 test fixtures 可能用 ``"source-1"`` 等占位符；ChunkRegistry
    # PK 是 UUIDField，传非 UUID 会触发 ValidationError。
    all_chunk_ids: set[str] = {
        cid for cid in (source_chunk_ids | target_chunk_ids) if _is_uuid_str(cid)
    }

    registry_map: dict[Any, ChunkRegistry] = await sync_to_async(
        ChunkRegistry.objects.in_bulk
    )(list(all_chunk_ids), field_name="chunk_id")
    # in_bulk 用 UUIDField PK 时 key 类型为 ``uuid.UUID``；本函数对外契约用 str，
    # 统一转 str key 便于与 neighbor_tuples 中的 str chunk_id 对齐
    by_str_id: dict[str, ChunkRegistry] = {
        str(k): v for k, v in registry_map.items()
    }

    # 合并 key=(target_chunk_id, edge_type)，保 max(weight) + 记录 source +
    # edge_metadata（hop2 4-tuple 携带；hop1 3-tuple 缺省 {}）
    merged: dict[tuple[str, str], tuple[float, str, dict[str, Any]]] = {}
    for source_chunk_id, tuples in neighbor_tuples.items():
        for t in tuples:
            tgt = t[0]
            edge_type = t[1]
            weight = t[2]
            edge_metadata: dict[str, Any] = t[3] if len(t) > 3 else {}
            key = (tgt, edge_type)
            existing = merged.get(key)
            if existing is None or weight > existing[0]:
                merged[key] = (weight, source_chunk_id, edge_metadata)

    out: list[NeighborMetadata] = []
    for (tgt, edge_type), (weight, source_chunk_id, edge_metadata) in merged.items():
        target_registry = by_str_id.get(tgt)
        if target_registry is None:
            # info（非 debug）：ChunkRegistry 缺失意味着 payload 与 ORM 间存在
            # 数据不一致（implementation reconcile 兜底场景），prod 默认 INFO 级别下
            # 必须可见以便 ops 关注；debug 级别在 prod 不输出会丢失信号
            logger.info(
                "hop1_chunk_registry_miss",
                chunk_id=tgt,
            )
            file_path = _UNKNOWN_FILE_PATH
            line_start: int | None = None
            line_end: int | None = None
            target_file: str | None = None
        else:
            file_path = target_registry.file_path
            line_start = target_registry.line_start
            line_end = target_registry.line_end
            target_file = target_registry.file_path

        source_registry = by_str_id.get(source_chunk_id)
        source_file = source_registry.file_path if source_registry else None

        out.append(
            NeighborMetadata(
                chunk_id=tgt,
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                edge_type=edge_type,
                weight=weight,
                reason=reason_fn(edge_type, source_file, target_file, edge_metadata),
                hop=hop,
            )
        )

    return out
