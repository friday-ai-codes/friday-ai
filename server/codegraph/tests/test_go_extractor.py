"""Go 语言 extractor 测试 —— 验证 symbol / import / call 抽取。"""
from __future__ import annotations
import os
import pytest
from codegraph.backends.protocols import TreeSitterBackend
from codegraph.extractors.base import FileContext
from codegraph.services.orchestrator import GraphExtractor
@pytest.fixture
def go_source:
 """加载 Go fixture 源码。"""
 fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
 with open(os.path.join(fixtures_dir, "go_module.go"), "r", encoding="utf-8") as f:
 return f.read
@pytest.fixture
def go_parser:
 """返回预配置的 tree-sitter Go Parser。"""
 import tree_sitter_go
 from tree_sitter import Language, Parser
 ts_lang = Language(tree_sitter_go.language)
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
 def test_orchestrator_extract_all_go(self, go_parser, go_source):
 """Orchestrator 对 Go 文件返回非空 bundle。"""
 tree = go_parser.parse(go_source.encode("utf-8"))
 ctx = FileContext(file_path="main.go", language="go", repository_id="r1")
 extractor = GraphExtractor
 bundle = extractor.extract_all(tree, go_source, ctx)
 assert len(bundle.symbols) > 0
 assert len(bundle.imports) > 0
 def test_go_backend_registered(self):
 """Go backend 在 BACKEND_REGISTRY 中注册。"""
 from codegraph.extractors.registry import BACKEND_REGISTRY
 assert "go" in BACKEND_REGISTRY
