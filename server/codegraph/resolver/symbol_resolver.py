""" —— 语言无关 SymbolResolver 编排层。
本模块串起 ``SymbolIndex`` 与语言专属 ``ImportResolver``：
1. 同文件裸名优先解析到当前文件内 Symbol；
2. 经 ``ImportEdge`` + 语言 resolver 解析跨文件 import；
3. JSX / TEMPLATE_REF 组件分支仅保留接口，具体实现留 Phase；
4. 解析不到时返回空结果，绝不靠 fuzzy 同名兜底乱连。
"""
from __future__ import annotations
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING
import structlog
from codegraph.resolver.base import ImportResolver, ResolveResult
from codegraph.resolver.symbol_index import IndexedSymbol, SymbolIndex
if TYPE_CHECKING:
 from codegraph.models import CallEdge, ImportEdge
__all__ = ["SymbolResolver"]
logger = structlog.get_logger(__name__)
def _lang_of(caller_file: str) -> str | None:
 """按 caller 文件扩展名选择语言 resolver；未知扩展走留空分支。"""
 if caller_file.endswith(".py"):
 return "python"
 return None
def _match_imported_name(callee_name: str, imported_names: Sequence[str]) -> str | None:
 """用本地名匹配 ``imported_names``，返回目标文件内应查找的原始名。
 ``ImportEdge.imported_names`` 的条目格式为 ``"foo"`` 或 ``"foo as bar"``。
 调用点使用本地名（alias 优先），但目标文件内 Symbol 仍使用原始定义名。
 """
 for item in imported_names:
 original, separator, alias = item.partition(" as ")
 local_name = alias if separator else original
 if callee_name == local_name:
 return original
 return None
def _pick(candidates: list[IndexedSymbol]) -> IndexedSymbol:
 """从同文件同名候选中裁定一个 Symbol。
 裸名调用通常指向 top-level ``FUNCTION`` / ``CLASS``，优先于 ``METHOD`` /
 ``VARIABLE``；同优先级保持索引构建顺序稳定。
 """
 priority = {"FUNCTION": 0, "CLASS": 0, "METHOD": 1, "VARIABLE": 2}
 return min(candidates, key=lambda symbol: priority.get(symbol.symbol_type, 99))
class SymbolResolver:
 """跨文件静态符号解析编排器，供 288/289/290/291 复用。"""
 def __init__(
 self,
 symbol_index: SymbolIndex,
 import_by_source: Mapping[str, Sequence[ImportEdge]],
 resolver_by_lang: Mapping[str, ImportResolver],
 ) -> None:
 self._idx = symbol_index
 self._imports = import_by_source
 self._resolvers = resolver_by_lang
 def resolve_call(self, edge: CallEdge) -> ResolveResult:
 """解析单条 ``CallEdge``，产出可回填的 callee 三元组。"""
 caller_file = edge.caller_file
 callee_name = edge.callee_name
 local_hits = self._idx.exact(caller_file, callee_name)
 if local_hits:
 symbol = _pick(local_hits)
 return ResolveResult(symbol.id, caller_file, is_cross_file=False)
 language = _lang_of(caller_file)
 resolver = self._resolvers.get(language) if language is not None else None
 if resolver is not None:
 for import_edge in self._imports.get(caller_file, ):
 original_name = _match_imported_name(
 callee_name,
 import_edge.imported_names,
 )
 if original_name is None:
 continue
 target_file = resolver.resolve_module(
 import_edge.target_module,
 import_edge.is_relative,
 caller_file,
 )
 if target_file is None:
 continue
 target_hits = self._idx.exact(target_file, original_name)
 if target_hits:
 symbol = _pick(target_hits)
 return ResolveResult(
 symbol.id,
 target_file,
 is_cross_file=target_file != caller_file,
 )
 # JSX / TEMPLATE_REF → Phase 挂组件解析分支。
 return ResolveResult(None, None, False)
 def backfill(self, repository_id: str) -> dict[str, int]:
 """批量回填该仓尚未解析的 ``CallEdge``。
 整库接入索引/重建流程留到 Phase；本入口仅供单测驱动与后续流程调用。
 单条边解析失败只记 warning，不阻断整批回填。
 """
 from codegraph.models import CallEdge
 edges = list(
 CallEdge.objects.filter(
 repository_id=repository_id,
 callee_symbol__isnull=True,
 )
 )
 resolved = 0
 for edge in edges:
 try:
 result = self.resolve_call(edge)
 except Exception as exc: # noqa: BLE001 - 单边异常必须隔离，不能中断整批回填。
 logger.warning(
 "resolve_call_failed",
 edge_id=str(edge.id),
 error=str(exc),
 )
 continue
 if result.callee_symbol_id is None:
 continue
 edge.callee_symbol_id = result.callee_symbol_id
 edge.callee_file = result.callee_file
 edge.is_cross_file = result.is_cross_file
 resolved += 1
 if edges:
 CallEdge.objects.bulk_update(
 edges,
 ["callee_symbol", "callee_file", "is_cross_file"],
 batch_size=500,
 )
 logger.info(
 "symbol_resolve_backfill_complete",
 repository_id=repository_id,
 total=len(edges),
 resolved=resolved,
 )
 return {"total": len(edges), "resolved": resolved}
