"""Backend Protocol 抽象层 —— 为 tree-sitter / volar / gopls 提供统一插件接口。"""

from codegraph.backends.protocols import ExtractorBackend, TreeSitterBackend

__all__ = ["ExtractorBackend", "TreeSitterBackend"]
