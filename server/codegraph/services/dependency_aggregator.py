""" —— 文件级 / 组件级双向依赖查询时聚合。
从符号级 ``CallEdge``（callee_file/caller_file，work-item 已回填）+ ``ImportEdge`` 上卷出
文件级双向依赖；从 ``JSX``/``TEMPLATE_REF`` 边 + 组件 Symbol 上卷出组件级双向依赖。
- 文件级：同一对文件多条符号边聚合为一条带 ``count`` 的文件级边；``ImportEdge``
 纯 import 依赖经语言 resolver 解析 target → 叠加（kind="import"）。
- 组件级：组件 = CLASS Symbol（Vue/TSX）；上游=用本组件的组件，下游=本组件用的组件。
纯查询服务，按 ``repository_id`` 隔离。``direction`` ∈ {both, up, down}。
"""
from __future__ import annotations
from typing import Any
from django.db.models import Count
from codegraph.resolver.frontend_import import FrontendImportResolver
from codegraph.resolver.go_import import GoImportResolver
from codegraph.resolver.python_import import PythonImportResolver
from codegraph.resolver.symbol_index import SymbolIndex
_FRONTEND_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".vue")
_COMPONENT_CALL_TYPES = ("JSX", "TEMPLATE_REF")
def _want_up(direction: str) -> bool:
 return direction in ("both", "up")
def _want_down(direction: str) -> bool:
 return direction in ("both", "down")
def _build_file_set_index(repository_id: str) -> SymbolIndex:
 """构建仅含文件集的轻量 SymbolIndex（供 import 叠加解析 target，免全量符号灌入）。"""
 from codegraph.models import Symbol
 index = SymbolIndex
 file_paths = (
 Symbol.objects.filter(repository_id=repository_id)
 .values_list("file_path", flat=True)
 .distinct
 )
 index._files.update(file_paths)
 return index
def _resolver_for(source_file: str, index: SymbolIndex) -> Any:
 """按 source_file 扩展名选语言 resolver（import 叠加用，配置无关）。
 Python 无需配置；前端相对 import 无需 alias 即可解析（alias import 缺 tsconfig 漏）；
 Go 缺 module_path 时 resolve_module 返回 None（无 Go import 叠加）。
 """
 if source_file.endswith(".py"):
 return PythonImportResolver(index)
 if source_file.endswith(_FRONTEND_EXTENSIONS):
 return FrontendImportResolver(index, {})
 if source_file.endswith(".go"):
 return GoImportResolver(index, "")
 return None
def _merge(target: dict[str, dict[str, Any]], file_path: str, kind: str) -> None:
 """把一条邻居边并入聚合 dict：同文件累加 count、合并 kind。"""
 entry = target.setdefault(file_path, {"file": file_path, "count": 0, "kinds": set})
 entry["count"] += 1
 entry["kinds"].add(kind)
def _finalize(agg: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
 """聚合 dict → 排序后的列表（kinds set → 排序 list）。"""
 rows =
 for entry in agg.values:
 rows.append(
 {
 "file": entry["file"],
 "count": entry["count"],
 "kinds": sorted(entry["kinds"]),
 }
 )
 return sorted(rows, key=lambda row: row["file"])
def file_neighbors(
 repository_id: str, file_path: str, direction: str = "both"
) -> dict[str, list[dict[str, Any]]]:
 """文件级双向依赖：上游=被谁调用/导入，下游=调用/导入了谁。
 同一对文件多条符号边聚合带 ``count``；``ImportEdge`` 纯依赖经 resolver 解析叠加。
 """
 from codegraph.models import CallEdge, ImportEdge
 upstream: dict[str, dict[str, Any]] = {}
 downstream: dict[str, dict[str, Any]] = {}
 if _want_down(direction):
 down_calls = (
 CallEdge.objects.filter(
 repository_id=repository_id,
 caller_file=file_path,
 callee_file__isnull=False,
 )
 .exclude(callee_file=file_path)
 .values("callee_file")
 .annotate(count=Count("id"))
 )
 for row in down_calls:
 target = row["callee_file"]
 for _ in range(row["count"]):
 _merge(downstream, target, "call")
 if _want_up(direction):
 up_calls = (
 CallEdge.objects.filter(
 repository_id=repository_id,
 callee_file=file_path,
 )
 .exclude(caller_file=file_path)
 .values("caller_file")
 .annotate(count=Count("id"))
 )
 for row in up_calls:
 for _ in range(row["count"]):
 _merge(upstream, row["caller_file"], "call")
 # ImportEdge 叠加：纯 import 依赖经语言 resolver 解析 target → 文件级边。
 index = _build_file_set_index(repository_id)
 if _want_down(direction):
 for import_edge in ImportEdge.objects.filter(
 repository_id=repository_id, source_file=file_path
 ):
 resolver = _resolver_for(file_path, index)
 if resolver is None:
 continue
 target = resolver.resolve_module(
 import_edge.target_module, import_edge.is_relative, file_path
 )
 if target and target != file_path:
 _merge(downstream, target, "import")
 if _want_up(direction):
 for import_edge in ImportEdge.objects.filter(
 repository_id=repository_id
 ).exclude(source_file=file_path):
 resolver = _resolver_for(import_edge.source_file, index)
 if resolver is None:
 continue
 target = resolver.resolve_module(
 import_edge.target_module, import_edge.is_relative, import_edge.source_file
 )
 if target == file_path:
 _merge(upstream, import_edge.source_file, "import")
 result: dict[str, list[dict[str, Any]]] = {}
 if _want_up(direction):
 result["upstream"] = _finalize(upstream)
 if _want_down(direction):
 result["downstream"] = _finalize(downstream)
 return result
def component_neighbors(
 repository_id: str, component_symbol_id: str, direction: str = "both"
) -> dict[str, Any]:
 """组件级双向依赖：上游=用本组件的组件，下游=本组件用的组件。
 组件 = CLASS Symbol；上下游经 JSX/TEMPLATE_REF 边 + callee_symbol 聚合。
 """
 from codegraph.models import CallEdge, Symbol
 seed = Symbol.objects.get(id=component_symbol_id, repository_id=repository_id)
 seed_file = seed.file_path
 def _component_of_file(file_path: str) -> Symbol | None:
 """取某文件的组件 CLASS Symbol（Vue/TSX 一文件一组件约定）。"""
 return (
 Symbol.objects.filter(
 repository_id=repository_id,
 file_path=file_path,
 symbol_type="CLASS",
 )
 .order_by("start_line")
 .first
 )
 upstream: dict[str, dict[str, Any]] = {}
 downstream: dict[str, dict[str, Any]] = {}
 if _want_down(direction):
 down_edges = CallEdge.objects.filter(
 repository_id=repository_id,
 caller_file=seed_file,
 call_type__in=_COMPONENT_CALL_TYPES,
 callee_symbol__isnull=False,
 ).select_related("callee_symbol")
 for edge in down_edges:
 comp = edge.callee_symbol
 if comp is not None and comp.symbol_type == "CLASS":
 key = str(comp.id)
 entry = downstream.setdefault(
 key,
 {"symbol_id": key, "name": comp.name, "file": comp.file_path, "count": 0},
 )
 entry["count"] += 1
 if _want_up(direction):
 up_edges = CallEdge.objects.filter(
 repository_id=repository_id,
 call_type__in=_COMPONENT_CALL_TYPES,
 callee_symbol=seed,
 )
 for edge in up_edges:
 comp = _component_of_file(edge.caller_file)
 if comp is not None:
 key = str(comp.id)
 entry = upstream.setdefault(
 key,
 {"symbol_id": key, "name": comp.name, "file": comp.file_path, "count": 0},
 )
 entry["count"] += 1
 result: dict[str, Any] = {"seed_symbol_id": str(component_symbol_id)}
 if _want_up(direction):
 result["upstream"] = sorted(upstream.values, key=lambda row: row["name"])
 if _want_down(direction):
 result["downstream"] = sorted(downstream.values, key=lambda row: row["name"])
 return result
