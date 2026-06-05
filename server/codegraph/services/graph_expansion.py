"""Graph Expansion Service —— 2-hop 图遍历扩展。

基于 initial implementation 已入库的 Symbol/CallEdge 图谱数据，
从种子符号出发沿调用边扩展调用者和被调用者关系。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async

from codegraph.models import CallEdge, Symbol

logger = structlog.get_logger(__name__)


class GraphExpansionService:
    """2-hop 图遍历扩展服务。

    从种子 Symbol 出发，沿调用边向外扩展：
    - 1-hop: 出边（种子调用了谁）+ 入边（谁调用了种子）
    - 2-hop: 对每个 1-hop 邻居重复相同过程

    返回值结构（per contract）：
    {
        "seed_symbol": Symbol,
        "nodes": [{"symbol": Symbol, "depth": int, "relationship": "caller"|"callee"}],
        "edges": [{"source": str, "target": str, "call_type": str}],
    }
    """

    MAX_DEPTH: int = 2  # 不可配置 (contract)

    @classmethod
    async def expand(
        cls,
        seed_symbol: Symbol,
        *,
        max_symbols_per_hop: int = 20,
        max_total: int = 50,
    ) -> dict[str, Any]:
        """从种子符号出发做 2-hop 图遍历扩展。

        Args:
            seed_symbol: 种子符号（必须有 id 和 repository_id）
            max_symbols_per_hop: 每 hop 最大新增节点数（默认 20，per contract）
            max_total: 总节点数上限（默认 50，per contract）

        Returns:
            {"seed_symbol": Symbol, "nodes": [...], "edges": [...]}
        """
        repository_id = str(seed_symbol.repository_id)

        # visited: symbol_id (str) -> depth
        visited: dict[str, int] = {str(seed_symbol.id): 0}
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        # 1-hop 扩展
        hop1_neighbors = await cls._expand_one_hop(
            seed_symbol, repository_id, visited, nodes, edges,
            max_symbols_per_hop=max_symbols_per_hop,
        )

        # 2-hop 扩展（仅当有 1-hop 邻居时）
        if hop1_neighbors:
            await cls._expand_second_hop(
                hop1_neighbors, repository_id, visited, nodes, edges,
                max_symbols_per_hop=max_symbols_per_hop,
                max_total=max_total,
            )

        logger.info(
            "graph_expansion_completed",
            seed_symbol_id=str(seed_symbol.id),
            seed_name=seed_symbol.name,
            node_count=len(nodes),
            edge_count=len(edges),
            max_depth_reached=(
                2 if any(n["depth"] == 2 for n in nodes)
                else 1 if nodes else 0
            ),
        )

        return {
            "seed_symbol": seed_symbol,
            "nodes": nodes,
            "edges": edges,
        }

    # ------------------------------------------------------------------
    # 1-hop 扩展
    # ------------------------------------------------------------------

    @classmethod
    async def _expand_one_hop(
        cls,
        seed: Symbol,
        repository_id: str,
        visited: dict[str, int],
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        max_symbols_per_hop: int = 20,
    ) -> list[Symbol]:
        """从 seed 符号出发做 1-hop 扩展（出边 + 入边）。

        Returns:
            1-hop 邻居 Symbol 列表（供 2-hop 使用）
        """
        neighbors: list[Symbol] = []

        # --- 出边：seed 调用了谁 ---
        outgoing_edges = await sync_to_async(list)(
            seed.outgoing_calls.select_related("caller_symbol").all()
        )
        for edge in outgoing_edges:
            # 按 callee_name 查找目标 Symbol
            callee_symbols = await sync_to_async(list)(
                Symbol.objects.filter(
                    name=edge.callee_name,
                    repository_id=repository_id,
                )
            )
            for callee in callee_symbols:
                callee_id = str(callee.id)
                if callee_id not in visited:
                    visited[callee_id] = 1
                    nodes.append({
                        "symbol": callee,
                        "depth": 1,
                        "relationship": "callee",
                    })
                    neighbors.append(callee)
            # 记录 edge（source=seed, target 使用 callee_name 作为后备标识）
            for callee in callee_symbols:
                edges.append({
                    "source": str(seed.id),
                    "target": str(callee.id),
                    "call_type": edge.call_type,
                })

        # --- 入边：谁调用了 seed ---
        # 排除 caller_symbol=NULL 的模块级边（initial implementation）：符号级 DAG 以
        # Symbol 为节点，模块级 caller 无对应 Symbol，本 phase 最小过滤不展示（完整改造留 291/work item）。
        incoming_edges = await sync_to_async(list)(
            CallEdge.objects.filter(
                callee_name=seed.name,
                repository_id=repository_id,
            ).exclude(caller_symbol__isnull=True).select_related("caller_symbol")
        )
        for edge in incoming_edges:
            caller = edge.caller_symbol
            # belt-and-suspenders：双保险防 select_related 缓存边界，理论上 exclude 后恒非 None
            if caller is None:
                continue
            caller_id = str(caller.id)
            if caller_id not in visited:
                visited[caller_id] = 1
                nodes.append({
                    "symbol": caller,
                    "depth": 1,
                    "relationship": "caller",
                })
                neighbors.append(caller)
            edges.append({
                "source": str(caller.id),
                "target": str(seed.id),
                "call_type": edge.call_type,
            })

        # 上限截断：按 outgoing_calls 数量预估排序，保留关系密集的符号
        if len(neighbors) > max_symbols_per_hop:
            neighbors = await cls._truncate_by_edge_count(
                neighbors, max_symbols_per_hop, repository_id,
            )
            # 同步截断 nodes 列表——只保留 truncate 后仍在 neighbors 中的符号
            kept_ids = {str(n.id) for n in neighbors}
            # 清理 visited 中已被截断的符号（回退访问标记）
            removed_ids = [
                nid for nid in visited if visited[nid] == 1 and nid not in kept_ids
            ]
            for rid in removed_ids:
                del visited[rid]
            # 从 nodes 中移除被截断的条目
            for i in range(len(nodes) - 1, -1, -1):
                nd = nodes[i]
                if nd["depth"] == 1 and str(nd["symbol"].id) not in kept_ids:
                    nodes.pop(i)

        return neighbors

    # ------------------------------------------------------------------
    # 2-hop 扩展
    # ------------------------------------------------------------------

    @classmethod
    async def _expand_second_hop(
        cls,
        hop1_neighbors: list[Symbol],
        repository_id: str,
        visited: dict[str, int],
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        max_symbols_per_hop: int = 20,
        max_total: int = 50,
    ) -> None:
        """对每个 1-hop 邻居做 2-hop 扩展。

        使用批量入边查询避免 N+1 问题（per RESEARCH.md 陷阱 5）。
        """
        # 收集所有 1-hop 邻居名称用于批量入边查询
        neighbor_names = list({n.name for n in hop1_neighbors})
        neighbor_ids = {str(n.id) for n in hop1_neighbors}

        # 批量查询所有 1-hop 邻居的出边
        all_outgoing = await sync_to_async(list)(
            CallEdge.objects.filter(
                caller_symbol_id__in=[str(n.id) for n in hop1_neighbors],
                repository_id=repository_id,
            ).select_related("caller_symbol")
        )

        # 批量查询所有 1-hop 邻居的入边
        from django.db.models import Q

        all_incoming = await sync_to_async(list)(
            CallEdge.objects.filter(
                Q(callee_name__in=neighbor_names),
                repository_id=repository_id,
            ).exclude(caller_symbol__isnull=True).select_related("caller_symbol")
        )

        hop2_new_nodes: list[dict[str, Any]] = []

        # 处理出边：1-hop neighbor -> callee (2-hop)
        for edge in all_outgoing:
            caller_id = str(edge.caller_symbol_id)
            if caller_id not in neighbor_ids:
                continue
            callee_symbols = await sync_to_async(list)(
                Symbol.objects.filter(
                    name=edge.callee_name,
                    repository_id=repository_id,
                )
            )
            for callee in callee_symbols:
                callee_id = str(callee.id)
                if callee_id not in visited:
                    visited[callee_id] = 2
                    hop2_new_nodes.append({
                        "symbol": callee,
                        "depth": 2,
                        "relationship": "callee",
                    })
                edges.append({
                    "source": str(edge.caller_symbol_id),
                    "target": str(callee.id),
                    "call_type": edge.call_type,
                })

        # 处理入边：caller -> 1-hop neighbor (2-hop caller of neighbor)
        for edge in all_incoming:
            caller = edge.caller_symbol
            # belt-and-suspenders：双保险防 select_related 缓存边界，exclude 后恒非 None
            if caller is None:
                continue
            caller_id = str(caller.id)
            if caller_id not in visited and caller_id not in neighbor_ids:
                visited[caller_id] = 2
                hop2_new_nodes.append({
                    "symbol": caller,
                    "depth": 2,
                    "relationship": "caller",
                })
            edges.append({
                "source": str(caller.id),
                "target": str(edge.callee_name),
                "call_type": edge.call_type,
            })

        # 上限控制：总节点数不超过 max_total
        current_total = len(nodes)
        remaining = max_total - current_total
        if remaining <= 0:
            return

        if len(hop2_new_nodes) > remaining:
            # 截断：按 depth=2 节点对应符号的关系密度排序
            hop2_new_nodes = await cls._truncate_nodes_by_edge_count(
                hop2_new_nodes, remaining, repository_id,
            )

        # 应用截断并添加剩余节点
        if len(hop2_new_nodes) > max_symbols_per_hop:
            hop2_new_nodes = await cls._truncate_nodes_by_edge_count(
                hop2_new_nodes, max_symbols_per_hop, repository_id,
            )

        nodes.extend(hop2_new_nodes)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @classmethod
    async def _truncate_by_edge_count(
        cls,
        symbols: list[Symbol],
        max_count: int,
        repository_id: str,
    ) -> list[Symbol]:
        """按 outgoing_calls 数量排序截断 Symbol 列表。

        优先保留关系密集的符号（信息量更大）。
        """
        if len(symbols) <= max_count:
            return symbols

        # 统计每个符号的 outgoing_calls 数量
        symbol_counts: list[tuple[Symbol, int]] = []
        for sym in symbols:
            count = await sync_to_async(
                sym.outgoing_calls.count
            )()
            symbol_counts.append((sym, count))

        # 按 outgoing_calls 数量降序排序
        symbol_counts.sort(key=lambda x: x[1], reverse=True)
        return [sc[0] for sc in symbol_counts[:max_count]]

    @classmethod
    async def _truncate_nodes_by_edge_count(
        cls,
        node_dicts: list[dict[str, Any]],
        max_count: int,
        repository_id: str,
    ) -> list[dict[str, Any]]:
        """按 outgoing_calls 数量排序截断 node dict 列表。"""
        if len(node_dicts) <= max_count:
            return node_dicts

        node_counts: list[tuple[dict[str, Any], int]] = []
        for nd in node_dicts:
            sym = nd["symbol"]
            count = await sync_to_async(
                sym.outgoing_calls.count
            )()
            node_counts.append((nd, count))

        node_counts.sort(key=lambda x: x[1], reverse=True)
        return [nc[0] for nc in node_counts[:max_count]]


__all__ = ["GraphExpansionService"]
