"""Backend Protocol 测试 —— 验证 ExtractorBackend + TreeSitterBackend。"""

from __future__ import annotations

import pytest

from codegraph.backends.protocols import ExtractorBackend, TreeSitterBackend
from codegraph.extractors.base import FileContext


class TestExtractorBackendProtocol:
    """ExtractorBackend Protocol 元测试。"""

    def test_protocol_is_runtime_checkable(self):
        """Protocol 必须支持 isinstance 检查。"""
        assert issubclass(TreeSitterBackend, ExtractorBackend)

    def test_tree_sitter_backend_implements_protocol(self):
        """TreeSitterBackend 必须实现 ExtractorBackend。"""
        backend = TreeSitterBackend("python")
        assert isinstance(backend, ExtractorBackend)

    def test_protocol_has_all_five_methods(self):
        """Protocol 必须定义 5 个 extract_* + parse_file 方法。"""
        required = {
            "parse_file",
            "extract_symbols",
            "extract_imports",
            "extract_calls",
            "extract_endpoints",
        }
        actual = {m for m in dir(ExtractorBackend) if not m.startswith("_")}
        assert required.issubset(actual), f"Missing: {required - actual}"


class TestTreeSitterBackend:
    """TreeSitterBackend 实现测试。"""

    def test_parse_file_returns_tree(self):
        """parse_file 必须返回 tree-sitter Tree 对象。"""
        backend = TreeSitterBackend("python")
        tree = backend.parse_file("test.py", "def foo(): pass\n")

        assert tree is not None
        assert hasattr(tree, "root_node")
        assert tree.root_node is not None

    def test_extract_symbols(self):
        """extract_symbols 委托正确。"""
        backend = TreeSitterBackend("python")
        tree = backend.parse_file("test.py", "def foo(): pass\n")
        ctx = FileContext(file_path="test.py", language="python", repository_id="r1")

        symbols = backend.extract_symbols(tree, "def foo(): pass\n", ctx)

        assert len(symbols) == 1
        assert symbols[0].name == "foo"
        assert symbols[0].symbol_type == "FUNCTION"

    def test_extract_imports(self):
        """extract_imports 委托正确。"""
        backend = TreeSitterBackend("python")
        source = "import os\n"
        tree = backend.parse_file("test.py", source)
        ctx = FileContext(file_path="test.py", language="python", repository_id="r1")

        imports = backend.extract_imports(tree, ctx)

        assert len(imports) == 1
        assert imports[0].target_module == "os"

    def test_extract_calls(self):
        """extract_calls 委托正确。"""
        backend = TreeSitterBackend("python")
        source = "def foo():\n    bar()\n"
        tree = backend.parse_file("test.py", source)
        ctx = FileContext(file_path="test.py", language="python", repository_id="r1")

        calls = backend.extract_calls(tree, ctx)

        assert len(calls) == 1
        assert calls[0].callee_name == "bar"

    def test_extract_endpoints_empty_for_non_django(self):
        """非 Django 文件 endpoint 抽取返回空列表。"""
        backend = TreeSitterBackend("python")
        source = "def foo(): pass\n"
        tree = backend.parse_file("test.py", source)
        ctx = FileContext(file_path="test.py", language="python", repository_id="r1")

        endpoints = backend.extract_endpoints(tree, source, ctx)

        assert endpoints == []

    def test_unsupported_language_raises(self):
        """不支持的语言必须抛 ValueError。"""
        with pytest.raises(ValueError, match="Unsupported language"):
            TreeSitterBackend("unsupported_lang")

    def test_backend_lazily_initializes_parser(self):
        """Parser 应惰性初始化。"""
        backend = TreeSitterBackend("python")
        assert backend._parser is None

        backend._ensure_parser()
        assert backend._parser is not None
