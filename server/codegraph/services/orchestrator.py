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
 """四维抽取，返回汇总 bundle。
 通过 registry 获取 language 对应的 backend，委托 4 个 extract_* 方法。
 后续 Stage B/C 引入 volar/gopls 时，registry 自动路由到新 backend。
 Args:
 tree: tree-sitter Tree 对象
 source: 源文件完整文本（用于签名提取和参数解析）
 ctx: FileContext (file_path, language, repository_id, module_path)
 Returns:
 ExtractionBundle: 包含 symbols / imports / calls / endpoints 四个列表
 """
 from codegraph.extractors.base import ExtractionBundle
 from codegraph.extractors.registry import get_backend
 bundle = ExtractionBundle(file_path=ctx.file_path, language=ctx.language)
 backend = get_backend(ctx.language)
 if backend is None:
 logger.warning(
 "no_backend_for_language",
 language=ctx.language,
 file_path=ctx.file_path,
 )
 return bundle
 # =====================================================================
 # 四维抽取：通过 backend Protocol 委托
 # =====================================================================
 try:
 bundle.symbols = backend.extract_symbols(tree, source, ctx)
 except Exception as e:
 logger.warning(
 "symbol_extraction_failed",
 file_path=ctx.file_path,
 language=ctx.language,
 error=str(e),
 )
 try:
 bundle.imports = backend.extract_imports(tree, ctx)
 except Exception as e:
 logger.warning(
 "import_extraction_failed",
 file_path=ctx.file_path,
 language=ctx.language,
 error=str(e),
 )
 try:
 bundle.calls = backend.extract_calls(tree, ctx)
 except Exception as e:
 logger.warning(
 "call_extraction_failed",
 file_path=ctx.file_path,
 language=ctx.language,
 error=str(e),
 )
 try:
 bundle.endpoints = backend.extract_endpoints(tree, source, ctx)
 except Exception as e:
 logger.warning(
 "endpoint_extraction_failed",
 file_path=ctx.file_path,
 language=ctx.language,
 error=str(e),
 )
 return bundle
__all__ = ["GraphExtractor"]
