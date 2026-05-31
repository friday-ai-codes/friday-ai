""" —— 整库符号解析回填编排。
把 work-item 的解析层接到索引/重建流程：整库 raw（Symbol/Import/raw Call）写完后，
对整库构建解析上下文并跑 ``SymbolResolver.backfill`` 回填 287 留 NULL 的
``CallEdge.callee_symbol / callee_file / is_cross_file``。
解析上下文 = ``SymbolIndex`` + 按 ``source_file`` 分组的 ``ImportEdge`` + 三语言
``ImportResolver``（python / frontend / go）。前端 alias_map 来自仓内 ``tsconfig.json``、
Go module_path 来自 ``go.mod``；缺失则对应 resolver 用空配置（Python 边照常解析）。
创建索引与手动重建均经 indexer ``_extract_and_write_graph``，本服务一处接入两路径覆盖。
"""
from __future__ import annotations
import os
import structlog
from codegraph.resolver.base import ImportResolver
from codegraph.resolver.frontend_import import FrontendImportResolver, load_alias_map
from codegraph.resolver.go_import import GoImportResolver, parse_go_module
from codegraph.resolver.python_import import PythonImportResolver
from codegraph.resolver.symbol_index import SymbolIndex
from codegraph.resolver.symbol_resolver import SymbolResolver
__all__ = ["backfill_symbol_resolution"]
logger = structlog.get_logger(__name__)
def _discover_alias_map(repo_path: str) -> dict[str, str]:
 """从仓内 tsconfig 解析前端 alias_map；候选取首个存在的文件，无则 ``{}``。"""
 candidates = [
 os.path.join(repo_path, "tsconfig.json"),
 os.path.join(repo_path, "web", "tsconfig.json"),
 ]
 for candidate in candidates:
 if os.path.exists(candidate):
 alias_map = load_alias_map(candidate)
 if alias_map:
 return alias_map
 return {}
def _discover_go_module(repo_path: str) -> str:
 """从仓内 ``go.mod`` 读取 module path；不存在/读失败返回空串。"""
 go_mod_path = os.path.join(repo_path, "go.mod")
 try:
 with open(go_mod_path, encoding="utf-8") as fh:
 module_path = parse_go_module(fh.read)
 return module_path or ""
 except OSError:
 return ""
def backfill_symbol_resolution(repository_id: str, repo_path: str) -> dict[str, int]:
 """对整库构建解析上下文并回填 ``CallEdge`` 的 callee 侧字段。
 Args:
 repository_id: 仓库 UUID 字符串。
 repo_path: 克隆仓库的本地路径（用于发现 tsconfig / go.mod）。
 Returns:
 ``{"total": N, "resolved": M}``——本次待解析边总数与成功回填数。
 """
 from codegraph.models import ImportEdge
 index = SymbolIndex.build(repository_id)
 import_by_source: dict[str, list[ImportEdge]] = {}
 for import_edge in ImportEdge.objects.filter(repository_id=repository_id):
 import_by_source.setdefault(import_edge.source_file, ).append(import_edge)
 alias_map = _discover_alias_map(repo_path)
 module_path = _discover_go_module(repo_path)
 resolver_by_lang: dict[str, ImportResolver] = {
 "python": PythonImportResolver(index),
 "frontend": FrontendImportResolver(index, alias_map),
 "go": GoImportResolver(index, module_path),
 }
 resolver = SymbolResolver(index, import_by_source, resolver_by_lang)
 stats = resolver.backfill(repository_id)
 logger.info(
 "symbol_resolution_wired",
 repository_id=repository_id,
 total=stats["total"],
 resolved=stats["resolved"],
 has_tsconfig=bool(alias_map),
 has_go_module=bool(module_path),
 )
 return stats
