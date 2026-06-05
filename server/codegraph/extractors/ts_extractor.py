"""TypeScript / TSX 专用抽取器 —— 直接实现 LanguageExtractor，不依赖 registry 模块。

TSExtractor 固定使用 TreeSitterBackend("typescript")；
TSXExtractor 固定使用 TreeSitterBackend("tsx")。
两类同文件分离（per implementation），避免与 registry.py 的循环导入。
后续 implementation 切 volar 时只需在此覆写 backend 注入路径。
"""

from __future__ import annotations

from codegraph.backends.protocols import TreeSitterBackend
from codegraph.extractors.base import ExtractionBundle, FileContext


class TSExtractor:
    """TypeScript (.ts) 语言抽取器。

    直接组合 TreeSitterBackend("typescript") 实现 extract() 单一入口，
    类型名独立以便后续阶段引入替代 backend（如 volar）时可在此覆写。
    """

    def __init__(self, backend=None) -> None:  # type: ignore[no-untyped-def]
        if backend is None:
            backend = TreeSitterBackend("typescript")
        self._backend = backend

    def extract(self, file_path: str, source: str, ctx: FileContext) -> ExtractionBundle:
        """完整抽取流程：parse → 四维抽取 → ExtractionBundle。"""
        tree = self._backend.parse_file(file_path, source)

        bundle = ExtractionBundle(file_path=file_path, language=ctx.language)
        bundle.symbols = self._backend.extract_symbols(tree, source, ctx)
        bundle.imports = self._backend.extract_imports(tree, ctx)
        bundle.calls = self._backend.extract_calls(tree, ctx)
        bundle.endpoints = self._backend.extract_endpoints(tree, source, ctx)

        return bundle


class TSXExtractor:
    """TSX (.tsx) 语言抽取器 —— 与 TSExtractor 物理分离，使用独立 tree-sitter grammar。

    直接组合 TreeSitterBackend("tsx") 实现 extract() 单一入口，
    类型名独立以便后续阶段引入替代 backend（如 volar）时可在此覆写。
    """

    def __init__(self, backend=None) -> None:  # type: ignore[no-untyped-def]
        if backend is None:
            backend = TreeSitterBackend("tsx")
        self._backend = backend

    def extract(self, file_path: str, source: str, ctx: FileContext) -> ExtractionBundle:
        """完整抽取流程：parse → 四维抽取 → ExtractionBundle。"""
        tree = self._backend.parse_file(file_path, source)

        bundle = ExtractionBundle(file_path=file_path, language=ctx.language)
        bundle.symbols = self._backend.extract_symbols(tree, source, ctx)
        bundle.imports = self._backend.extract_imports(tree, ctx)
        bundle.calls = self._backend.extract_calls(tree, ctx)
        bundle.endpoints = self._backend.extract_endpoints(tree, source, ctx)

        return bundle


__all__ = ["TSExtractor", "TSXExtractor"]
