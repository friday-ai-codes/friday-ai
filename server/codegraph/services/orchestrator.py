"""图谱抽取编排器 —— 单趟 AST 遍历调度四维抽取器（per ）。
GraphExtractor.extract_all(tree, source, ctx) 在一次 walk_tree 遍历中
完成 Symbol/Import/Call 三维抽取。Endpoint 抽取单独分层扫描。
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any
import structlog
if TYPE_CHECKING:
 from codegraph.extractors.base import ExtractionBundle, FileContext
logger = structlog.get_logger(__name__)
class GraphExtractor:
 """代码图谱四维抽取编排器。
 在同一次 AST DFS 遍历中执行 Symbol/Import/Call 抽取（共享 walk_tree 生成器），
 Endpoint 抽取因需要多遍扫描（三层），单独调用 endpoint 模块。
 """
 def extract_all(
 self, tree: Any, source: str, ctx: "FileContext"
 ) -> "ExtractionBundle":
 """单趟 AST 遍历完成四维抽取，返回汇总 bundle。
 Args:
 tree: tree-sitter Tree 对象
 source: 源文件完整文本（用于签名提取和参数解析）
 ctx: FileContext (file_path, language, repository_id, module_path)
 Returns:
 ExtractionBundle: 包含 symbols / imports / calls / endpoints 四个列表
 """
 from codegraph.extractors.base import ExtractionBundle
 from codegraph.extractors.walker import walk_tree, SYMBOL_TYPES, IMPORT_TYPES, CALL_TYPES
 from codegraph.extractors.symbol import _extract_one_symbol
 from codegraph.extractors.imports import _extract_one_import
 from codegraph.extractors.calls import _extract_one_call
 bundle = ExtractionBundle(file_path=ctx.file_path, language=ctx.language)
 symbol_types = SYMBOL_TYPES.get(ctx.language, )
 import_types = IMPORT_TYPES.get(ctx.language, )
 call_types = CALL_TYPES.get(ctx.language, )
 # =====================================================================
 # 单趟 DFS 遍历：Symbol + Import + Call 三维抽取
 # =====================================================================
 for wn in walk_tree(tree, ctx.language):
 node_type = wn.node.type
 # --- Symbol 抽取 ---
 if node_type in symbol_types:
 try:
 sym = _extract_one_symbol(wn, source, ctx)
 if sym is not None:
 bundle.symbols.append(sym)
 except Exception as e:
 logger.warning(
 "symbol_extraction_failed",
 file_path=ctx.file_path,
 node_type=node_type,
 error=str(e),
 )
 # --- Import 抽取 ---
 if node_type in import_types:
 try:
 imps = _extract_one_import(wn, ctx)
 if imps:
 bundle.imports.extend(imps)
 except Exception as e:
 logger.warning(
 "import_extraction_failed",
 file_path=ctx.file_path,
 node_type=node_type,
 error=str(e),
 )
 # --- Call 抽取 ---
 if node_type in call_types:
 try:
 call = _extract_one_call(wn, ctx)
 if call is not None:
 bundle.calls.append(call)
 except Exception as e:
 logger.warning(
 "call_extraction_failed",
 file_path=ctx.file_path,
 error=str(e),
 )
 # =====================================================================
 # Endpoint 抽取：独立三层扫描（不与主遍历耦合）
 # =====================================================================
 try:
 from codegraph.extractors.endpoints import extract_endpoints
 bundle.endpoints = extract_endpoints(tree, source, ctx)
 except Exception as e:
 logger.warning(
 "endpoint_extraction_failed",
 file_path=ctx.file_path,
 error=str(e),
 )
 return bundle
__all__ = ["GraphExtractor"]
