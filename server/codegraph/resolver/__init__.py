"""codegraph 解析层 —— 跨文件静态符号解析框架（SymbolIndex + Resolver）。
per：仓库级内存符号索引 + 语言无关 4 路径解析框架 + Python import
解析。用纯静态启发式（``ImportEdge`` + 同名 ``Symbol`` 匹配，不依赖 LSP）把 287 留
NULL 的 ``CallEdge.callee_symbol`` 解析回填。框架可被 289（前端）/290（Go）复用。
本 plan落地语言无关契约 ``base`` 与 ``SymbolIndex``。
"""
from codegraph.resolver.base import ImportResolver, ResolveResult
from codegraph.resolver.frontend_import import FrontendImportResolver
from codegraph.resolver.go_import import GoImportResolver, parse_go_module
from codegraph.resolver.python_import import PythonImportResolver
from codegraph.resolver.symbol_index import IndexedSymbol, SymbolIndex
from codegraph.resolver.symbol_resolver import SymbolResolver
__all__ = [
 "FrontendImportResolver",
 "GoImportResolver",
 "ImportResolver",
 "IndexedSymbol",
 "PythonImportResolver",
 "ResolveResult",
 "SymbolIndex",
 "SymbolResolver",
 "parse_go_module",
]
