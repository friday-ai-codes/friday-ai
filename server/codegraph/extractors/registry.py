"""LanguageExtractor Registry —— 语言级抽取器注册表 + Backend 注入。
支持运行时切换 backend（tree_sitter / volar / gopls）。
"""
from __future__ import annotations
from typing import Callable, Protocol, runtime_checkable
import structlog
from codegraph.backends.protocols import ExtractorBackend, TreeSitterBackend
from codegraph.extractors.base import ExtractionBundle, FileContext
logger = structlog.get_logger(__name__)
@runtime_checkable
class LanguageExtractor(Protocol):
 """语言级抽取器协议 —— 单一入口完成 parse + 四维抽取。
 与 ExtractorBackend 的区别：
 - ExtractorBackend 是 AST 级接口（接收已解析的 Tree）
 - LanguageExtractor 是文件级接口（接收源码文本，内部管理 parse）
 """
 def extract(self, file_path: str, source: str, ctx: FileContext) -> ExtractionBundle:
 """解析源码并完成四维抽取，返回完整 bundle。
 Args:
 file_path: 文件路径
 source: 源文件完整文本
 ctx: FileContext（含 language / repository_id 等）
 Returns:
 ExtractionBundle: symbols / imports / calls / endpoints
 """
 ...
class TreeSitterExtractor:
 """tree-sitter 语言抽取器 —— 组合 TreeSitterBackend 完成全链路抽取。"""
 def __init__(self, backend: ExtractorBackend | None = None) -> None:
 self._backend = backend
 def _get_backend(self, language: str) -> ExtractorBackend:
 """获取或创建 backend 实例。"""
 if self._backend is None:
 self._backend = TreeSitterBackend(language)
 return self._backend
 def extract(self, file_path: str, source: str, ctx: FileContext) -> ExtractionBundle:
 """完整抽取流程：parse → extract_symbols → extract_imports → extract_calls → extract_endpoints。"""
 backend = self._get_backend(ctx.language)
 tree = backend.parse_file(file_path, source)
 bundle = ExtractionBundle(file_path=file_path, language=ctx.language)
 bundle.symbols = backend.extract_symbols(tree, source, ctx)
 bundle.imports = backend.extract_imports(tree, ctx)
 bundle.calls = backend.extract_calls(tree, ctx)
 bundle.endpoints = backend.extract_endpoints(tree, source, ctx)
 return bundle
# =============================================================================
# Backend Registry —— 语言到 Backend 类的映射（供 GraphExtractor 直接使用）
# =============================================================================
BACKEND_REGISTRY: dict[str, Callable[[str], ExtractorBackend]] = {
 "python": TreeSitterBackend,
}
def get_backend(language: str) -> ExtractorBackend | None:
 """根据语言名获取对应的 Backend 实例。
 GraphExtractor.extract_all 直接消费此接口（避免重复 parse）。
 Args:
 language: 语言标识符
 Returns:
 ExtractorBackend 实例，或 None（语言未注册）
 """
 backend_cls = BACKEND_REGISTRY.get(language)
 if backend_cls is None:
 logger.warning(
 "backend_not_found",
 language=language,
 registered=list(BACKEND_REGISTRY.keys),
 )
 return None
 return backend_cls(language)
def register_backend(language: str, backend_cls: Callable[[str], ExtractorBackend]) -> None:
 """动态注册新的语言 backend。
 供后续 Stage B/C 的 volar / gopls backend 在启动时注册。
 Args:
 language: 语言标识符
 backend_cls: 实现 ExtractorBackend Protocol 的类
 Raises:
 TypeError: backend_cls 不兼容 ExtractorBackend Protocol
 """
 if not callable(backend_cls):
 raise TypeError(
 f"{getattr(backend_cls, '__name__', repr(backend_cls))} must be callable"
 )
 BACKEND_REGISTRY[language] = backend_cls
 logger.info(
 "backend_registered",
 language=language,
 backend=backend_cls.__name__,
 )
# =============================================================================
# Extractor Registry —— 语言到 LanguageExtractor 类的映射
# =============================================================================
EXTRACTOR_REGISTRY: dict[str, type[LanguageExtractor]] = {
 "python": TreeSitterExtractor,
}
class UnsupportedLanguageError(ValueError):
 """请求的语言无注册抽取器。"""
 pass
def get_extractor(language: str) -> LanguageExtractor | None:
 """根据语言名获取对应的抽取器实例。
 Args:
 language: 语言标识符（如 "python", "go", "typescript"）
 Returns:
 LanguageExtractor 实例，或 None（语言未注册）
 """
 extractor_cls = EXTRACTOR_REGISTRY.get(language)
 if extractor_cls is None:
 logger.warning(
 "extractor_not_found",
 language=language,
 registered=list(EXTRACTOR_REGISTRY.keys),
 )
 return None
 return extractor_cls
def register_extractor(language: str, extractor_cls: type[LanguageExtractor]) -> None:
 """动态注册新的语言抽取器。
 供后续 Stage B/C 的 volar / gopls backend 在启动时注册。
 Args:
 language: 语言标识符
 extractor_cls: 实现 LanguageExtractor Protocol 的类
 Raises:
 TypeError: extractor_cls 不兼容 LanguageExtractor Protocol
 """
 if not issubclass(extractor_cls, LanguageExtractor):
 # Protocol 的 issubclass 在 @runtime_checkable 下可用
 raise TypeError(
 f"{extractor_cls.__name__} must implement LanguageExtractor Protocol"
 )
 EXTRACTOR_REGISTRY[language] = extractor_cls
 logger.info(
 "extractor_registered",
 language=language,
 extractor=extractor_cls.__name__,
 )
