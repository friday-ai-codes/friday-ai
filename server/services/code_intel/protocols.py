"""代码智能 Provider 三层 Protocol 定义 (per Phase, )。
三层结构允许调用方按能力分级 isinstance 守卫：
- BaseCodeProvider —— 所有 provider 的最小契约（capabilities 声明 + health check）。
- SymbolCapableProvider —— 在 Base 之上支持 L2 符号精确查找。
- GraphCapableProvider —— 在 Symbol 之上支持 L4 调用图扩展。
NullProvider 仅实现 BaseCodeProvider；LocalProvider 实现到 GraphCapableProvider。
后续 v25+ RemoteProvider 也按本协议落地，HybridSearchService 通过
``isinstance(provider, GraphCapableProvider)`` 等运行时守卫决定降级路径。
"""
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable
@runtime_checkable
class BaseCodeProvider(Protocol):
 """所有代码智能 Provider 的最小契约。
 Attributes:
 capabilities: 能力集合，元素是 ``"symbol_lookup"`` / ``"graph_expansion"`` 等字符串；
 上游用 ``"symbol_lookup" in provider.capabilities`` 做能力门禁，避免直接
 ``isinstance`` 检查耦合 Protocol 类型。
 """
 capabilities: frozenset[str] = frozenset
 async def health_check(self) -> bool:
 """探活方法。
 Returns:
 True 表示可服务；False 表示后端不可用，调用方应降级到 NullProvider 路径。
 """
 ...
@runtime_checkable
class SymbolCapableProvider(BaseCodeProvider, Protocol):
 """支持 L2 符号精确查找的 Provider。
 返回值 dict 字段语义对齐 ``LayeredSearchService._l2_symbol_lookup`` 的 items 形态：
 ``symbol_id`` / ``name`` / ``symbol_type`` / ``file_path`` / ``start_line`` /
 ``end_line`` / ``signature`` / ``repository_id`` / ``repository_name``。
 """
 async def lookup_symbols(
 self,
 names: list[str],
 *,
 repository_ids: list[str],
 branch_name: str | None = None,
 ) -> list[dict[str, Any]]:
 """按符号名在指定仓库范围内做 iexact + icontains 回退查找。
 Args:
 names: 候选符号名列表（已过 keyword 过滤）。
 repository_ids: 限定的仓库 id 范围（不可为空）。
 branch_name: 分支维度过滤（base/overlay 合并语义同 hop2）。
 ``None`` / ``""`` → base 语义（仅 base 行），现存不传 branch 的
 callsite 向后兼容；``"feature"`` → 合并 base + 本分支符号。
 Returns:
 符号 dict 列表；未命中返回空列表，不抛错。
 """
 ...
@runtime_checkable
class GraphCapableProvider(SymbolCapableProvider, Protocol):
 """支持 L4 调用图扩展的 Provider。
 返回值结构对齐 ``GraphExpansionService.expand``:
 {
 "nodes": [{"symbol": <serialized>, "depth": int, "relationship": str}, ...],
 "edges": [{"source": str, "target": str, "call_type": str}, ...],
 }
 注意：``nodes[*].symbol`` 在 Provider 层应序列化为 dict（不暴露 ORM 对象），
 具体字段语义沿用 ``SymbolCapableProvider.lookup_symbols`` 同等 dict 形态。
 """
 async def expand_graph(
 self,
 seed_symbols: list[dict[str, Any]],
 *,
 max_hops: int = 2,
 ) -> dict[str, list[dict[str, Any]]]:
 """对 L2 命中的种子符号集做 2-hop 调用图扩展。
 Args:
 seed_symbols: L2 输出的符号 dict 列表，至少包含 ``symbol_id`` 字段。
 max_hops: 最大跳数（默认 2，本 phase 仅支持 ≤2，超过 raise ValueError）。
 Returns:
 ``{"nodes": [...], "edges": [...]}``；空种子时返回空集合不抛错。
 """
 ...
__all__ = [
 "BaseCodeProvider",
 "SymbolCapableProvider",
 "GraphCapableProvider",
]
