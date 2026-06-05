"""HTML 专用抽取器 —— TreeSitterBackend("html") thin wrapper。

per implementation / work item：与 ts_extractor.py / go_extractor.py 字面对称，
**不**沿用 implementation SFC pre-splitter 模式（HTML 是单 grammar 文件，无须中间层）。

calls / endpoints 显式 [] —— per work item / work item：HTML 无 callable / endpoint 语义；
inline `<script>` / `<style>` 段不递归解析（per work item / work item 留 implementation volar）。

SymbolData 通过 walker.py SYMBOL_TYPES["html"] + symbol.py html 分支落地（PascalCase tag /
custom element / id 属性）；ImportData 通过 walker.py IMPORT_TYPES["html"] +
imports.py html 分支落地（<link href> / <script src> / <img src>）。
"""

from __future__ import annotations

from codegraph.backends.protocols import TreeSitterBackend
from codegraph.extractors.base import ExtractionBundle, FileContext


class HtmlExtractor:
    """HTML (.html) 语言抽取器。"""

    def __init__(self, backend=None) -> None:  # type: ignore[no-untyped-def]
        if backend is None:
            backend = TreeSitterBackend("html")
        self._backend = backend

    def extract(self, file_path: str, source: str, ctx: FileContext) -> ExtractionBundle:
        """完整抽取流程：parse → symbols / imports → ExtractionBundle。"""
        tree = self._backend.parse_file(file_path, source)

        bundle = ExtractionBundle(file_path=file_path, language=ctx.language)
        bundle.symbols = self._backend.extract_symbols(tree, source, ctx)
        bundle.imports = self._backend.extract_imports(tree, ctx)
        bundle.calls = []
        bundle.endpoints = []
        return bundle


__all__ = ["HtmlExtractor"]
