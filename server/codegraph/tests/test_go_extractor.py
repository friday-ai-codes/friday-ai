"""Go 语言 extractor 测试 —— 验证 symbol / import / call 抽取。"""

from __future__ import annotations

import os

import pytest

from codegraph.backends.protocols import TreeSitterBackend
from codegraph.extractors.base import FileContext
from codegraph.services.orchestrator import GraphExtractor


@pytest.fixture
def go_source():
    """加载 Go fixture 源码。"""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(os.path.join(fixtures_dir, "go_module.go"), "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def go_gin_handler_source():
    """加载 Go gin handler fixture 源码。"""
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(
        os.path.join(fixtures_dir, "go_gin_handler.go"), "r", encoding="utf-8"
    ) as f:
        return f.read()


@pytest.fixture
def go_parser():
    """返回预配置的 tree-sitter Go Parser。"""
    import tree_sitter_go
    from tree_sitter import Language, Parser

    ts_lang = Language(tree_sitter_go.language())
    return Parser(ts_lang)


class TestGoExtractor:
    """Go 语言 extractor 端到端测试。"""

    def test_tree_sitter_go_parser_available(self, go_parser):
        """tree-sitter-go parser 必须可用。"""
        assert go_parser is not None

    def test_go_symbols(self, go_parser, go_source):
        """Go 符号抽取：函数 + 方法 + struct。"""
        tree = go_parser.parse(go_source.encode("utf-8"))
        ctx = FileContext(file_path="main.go", language="go", repository_id="r1")
        backend = TreeSitterBackend("go")

        symbols = backend.extract_symbols(tree, go_source, ctx)

        names = [s.name for s in symbols]
        assert "greet" in names
        assert "Server" in names
        assert "Start" in names
        assert "main" in names

    def test_go_imports(self, go_parser, go_source):
        """Go import 抽取。"""
        tree = go_parser.parse(go_source.encode("utf-8"))
        ctx = FileContext(file_path="main.go", language="go", repository_id="r1")
        backend = TreeSitterBackend("go")

        imports = backend.extract_imports(tree, ctx)

        assert len(imports) >= 1
        modules = [imp.target_module for imp in imports]
        assert "fmt" in modules

    def test_go_calls(self, go_parser, go_source):
        """Go 调用抽取。"""
        tree = go_parser.parse(go_source.encode("utf-8"))
        ctx = FileContext(file_path="main.go", language="go", repository_id="r1")
        backend = TreeSitterBackend("go")

        calls = backend.extract_calls(tree, ctx)

        callee_names = [c.callee_name for c in calls]
        assert "Sprintf" in callee_names or "Println" in callee_names

    def test_go_selector_captures_package_qualifier(self, go_parser, go_source):
        """selector 调用 fmt.X() 捕获包限定符 callee_qualifier='fmt'，callee_name 不变。"""
        tree = go_parser.parse(go_source.encode("utf-8"))
        ctx = FileContext(file_path="main.go", language="go", repository_id="r1")
        backend = TreeSitterBackend("go")

        calls = backend.extract_calls(tree, ctx)

        fmt_calls = [c for c in calls if c.callee_qualifier == "fmt"]
        assert fmt_calls, f"expected ≥1 fmt-qualified call: {[(c.callee_qualifier, c.callee_name) for c in calls]}"
        # callee_name 仍是裸函数名（不变语义），qualifier 才是包名。
        assert all(c.callee_name in ("Sprintf", "Println", "Printf", "Errorf") for c in fmt_calls)

    def test_orchestrator_extract_all_go(self, go_parser, go_source):
        """Orchestrator 对 Go 文件返回非空 bundle。"""
        tree = go_parser.parse(go_source.encode("utf-8"))
        ctx = FileContext(file_path="main.go", language="go", repository_id="r1")
        extractor = GraphExtractor()

        bundle = extractor.extract_all(tree, go_source, ctx)

        assert len(bundle.symbols) > 0
        assert len(bundle.imports) > 0

    def test_go_backend_registered(self):
        """Go backend 在 BACKEND_REGISTRY 中注册。"""
        from codegraph.extractors.registry import BACKEND_REGISTRY

        assert "go" in BACKEND_REGISTRY


class TestGoGinHandler:
    """Go gin handler fixture 端到端测试 —— 覆盖 work item。"""

    def test_handler_symbols(self, go_parser, go_gin_handler_source):
        """gin handler 函数 + struct 抽取。"""
        tree = go_parser.parse(go_gin_handler_source.encode("utf-8"))
        ctx = FileContext(file_path="handler.go", language="go", repository_id="r1")
        backend = TreeSitterBackend("go")

        symbols = backend.extract_symbols(tree, go_gin_handler_source, ctx)

        names = [s.name for s in symbols]
        assert "GetUser" in names
        assert "CreateUser" in names
        assert "RegisterRoutes" in names
        assert "User" in names

    def test_gin_imports(self, go_parser, go_gin_handler_source):
        """gin import path + grouping 解析。"""
        tree = go_parser.parse(go_gin_handler_source.encode("utf-8"))
        ctx = FileContext(file_path="handler.go", language="go", repository_id="r1")
        backend = TreeSitterBackend("go")

        imports = backend.extract_imports(tree, ctx)

        modules = [imp.target_module for imp in imports]
        assert "github.com/gin-gonic/gin" in modules
        assert "net/http" in modules

    def test_gin_method_calls(self, go_parser, go_gin_handler_source):
        """selector_expression call：c.JSON / c.BindJSON / r.GET / r.POST。"""
        tree = go_parser.parse(go_gin_handler_source.encode("utf-8"))
        ctx = FileContext(file_path="handler.go", language="go", repository_id="r1")
        backend = TreeSitterBackend("go")

        calls = backend.extract_calls(tree, ctx)

        callee_names = [c.callee_name for c in calls]
        assert "JSON" in callee_names
        method_call_types = {
            c.call_type for c in calls if c.callee_name == "JSON"
        }
        assert "METHOD" in method_call_types
        # c.JSON() 的 receiver 变量 c 被捕获为 callee_qualifier（resolver 据 import 判定包/变量）。
        json_qualifiers = {c.callee_qualifier for c in calls if c.callee_name == "JSON"}
        assert "c" in json_qualifiers

    def test_endpoints_extracted_for_go_treesitter(self, go_parser, go_gin_handler_source):
        """：默认禁用 gopls 后 go 走 tree-sitter backend，gin 路由 endpoint 被抽取。

        旧断言（endpoints==[]）建立在 gopls backend（GOPLS_BACKEND_ENABLED=True，
        gopls 路径不抽 gin 路由）之上。Phase 66 默认禁用 LSP 后 BACKEND_REGISTRY['go']
        回落 TreeSitterBackend，gin `r.GET/r.POST` 路由被 tree-sitter 抽取为 EndpointData。
        """
        tree = go_parser.parse(go_gin_handler_source.encode("utf-8"))
        ctx = FileContext(file_path="handler.go", language="go", repository_id="r1")
        extractor = GraphExtractor()

        bundle = extractor.extract_all(tree, go_gin_handler_source, ctx)

        methods = {(e.http_method, e.url_path) for e in bundle.endpoints}
        assert ("GET", "/users/:id") in methods
        assert ("POST", "/users") in methods
