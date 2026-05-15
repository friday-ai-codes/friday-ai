"""ExtractorBackend Protocol + TreeSitterBackend 实现。
为后续 Stage B/C 引入 volar / gopls 准备插件化基础设施。
所有 backend 必须实现 ExtractorBackend Protocol 的 5 个方法。
"""
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable
import structlog
from codegraph.extractors.base import (
 CallData,
 EndpointData,
 FileContext,
 ImportData,
 SymbolData,
)
logger = structlog.get_logger(__name__)
@runtime_checkable
class ExtractorBackend(Protocol):
 """Backend-agnostic 抽取器协议。
 所有语言后端（tree-sitter / volar / gopls）必须实现此接口。
 parse_file 负责将源码解析为 AST Tree；
 4 个 extract_* 方法从 Tree 中抽取对应维度的数据。
 """
 def parse_file(self, file_path: str, source: str) -> Any:
 """解析源码文件为 AST Tree。
 Args:
 file_path: 文件路径（用于错误日志定位）
 source: 源文件完整文本
 Returns:
 tree-sitter Tree 对象（或 LSP 等效结构）
 """
 ...
 def extract_symbols(self, tree: Any, source: str, ctx: FileContext) -> list[SymbolData]:
 """从 AST 提取符号定义（函数/类/方法）。"""
 ...
 def extract_imports(self, tree: Any, ctx: FileContext) -> list[ImportData]:
 """从 AST 提取 import 关系。"""
 ...
 def extract_calls(self, tree: Any, ctx: FileContext) -> list[CallData]:
 """从 AST 提取调用关系。"""
 ...
 def extract_endpoints(self, tree: Any, source: str, ctx: FileContext) -> list[EndpointData]:
 """从 AST 提取 API 端点。"""
 ...
# =============================================================================
# TreeSitterBackend —— 封装现有 tree-sitter extractor
# =============================================================================
# 语言到 tree-sitter 语言模块的映射
# 后续 phase 添加 Go / TS / Vue 时扩展此字典
_TREE_SITTER_LANGUAGE_MODULES: dict[str, str] = {
 "python": "tree_sitter_python",
}
def _get_tree_sitter_language(language: str) -> Any:
 """动态导入并创建 tree-sitter Language 对象。"""
 module_name = _TREE_SITTER_LANGUAGE_MODULES.get(language)
 if module_name is None:
 raise ValueError(
 f"Language '{language}' not supported by TreeSitterBackend. "
 f"Supported: {list(_TREE_SITTER_LANGUAGE_MODULES.keys)}"
 )
 try:
 lang_module = __import__(module_name)
 from tree_sitter import Language
 return Language(lang_module.language)
 except ImportError as e:
 raise ImportError(
 f"Failed to import {module_name} for language '{language}'. "
 f"Install with: pip install {module_name.replace('_', '-')}"
 ) from e
class TreeSitterBackend:
 """tree-sitter 后端实现 —— 封装现有 Python extractor。
 当前支持语言：python
 后续 Phase 将扩展：go / typescript / tsx / vue / html / css
 """
 def __init__(self, language: str) -> None:
 self.language = language
 self._parser: Any | None = None
 def _ensure_parser(self) -> Any:
 """惰性初始化 Parser。"""
 if self._parser is None:
 from tree_sitter import Parser
 ts_lang = _get_tree_sitter_language(self.language)
 self._parser = Parser(ts_lang)
 return self._parser
 def parse_file(self, file_path: str, source: str) -> Any:
 """使用 tree-sitter Parser 解析源码。"""
 parser = self._ensure_parser
 return parser.parse(source.encode("utf-8"))
 def extract_symbols(self, tree: Any, source: str, ctx: FileContext) -> list[SymbolData]:
 """委托给 symbol 抽取器。"""
 from codegraph.extractors.symbol import extract_symbols
 return extract_symbols(tree, source, ctx)
 def extract_imports(self, tree: Any, ctx: FileContext) -> list[ImportData]:
 """委托给 import 抽取器。"""
 from codegraph.extractors.imports import extract_imports
 return extract_imports(tree, ctx)
 def extract_calls(self, tree: Any, ctx: FileContext) -> list[CallData]:
 """委托给 call 抽取器。"""
 from codegraph.extractors.calls import extract_calls
 return extract_calls(tree, ctx)
 def extract_endpoints(self, tree: Any, source: str, ctx: FileContext) -> list[EndpointData]:
 """委托给 endpoint 抽取器。"""
 from codegraph.extractors.endpoints import extract_endpoints
 return extract_endpoints(tree, source, ctx)
