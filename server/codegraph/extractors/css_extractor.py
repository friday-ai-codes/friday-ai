"""CSS 专用抽取器 —— TreeSitterBackend("css") thin wrapper。

per implementation / 与 html_extractor.py / ts_extractor.py 字面对称。
calls / endpoints 显式 [] —— per work item / work item CSS 无 callable / endpoint 语义。

SymbolData 通过 walker.py SYMBOL_TYPES["css"]=["rule_set"] + symbol.py css 分支落地
（class selector → CLASS / id selector → VARIABLE / CSS variable 不抽 / tag selector 不抽）；
ImportData 通过 walker.py IMPORT_TYPES["css"]=["import_statement"] + imports.py css 分支
落地（@import url(...) + @import "..." 双形态）。
"""

from __future__ import annotations

from codegraph.backends.protocols import TreeSitterBackend
from codegraph.extractors.base import ExtractionBundle, FileContext


class CssExtractor:
    """CSS (.css) 语言抽取器。"""

    def __init__(self, backend=None) -> None:  # type: ignore[no-untyped-def]
        if backend is None:
            backend = TreeSitterBackend("css")
        self._backend = backend

    def extract(self, file_path: str, source: str, ctx: FileContext) -> ExtractionBundle:
        tree = self._backend.parse_file(file_path, source)

        bundle = ExtractionBundle(file_path=file_path, language=ctx.language)
        bundle.symbols = self._backend.extract_symbols(tree, source, ctx)
        bundle.imports = self._backend.extract_imports(tree, ctx)
        bundle.calls = []
        bundle.endpoints = []
        return bundle


__all__ = ["CssExtractor"]
