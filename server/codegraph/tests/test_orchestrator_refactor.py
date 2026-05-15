"""Orchestrator 改造测试 —— 验证 registry 驱动后与硬编码路径行为一致。"""
from __future__ import annotations
import pytest
from codegraph.extractors.base import FileContext
from codegraph.services.orchestrator import GraphExtractor
class TestOrchestratorRefactor:
 """GraphExtractor.extract_all 改造后行为一致性测试。"""
 @pytest.fixture
 def graph_extractor(self):
 return GraphExtractor
 @pytest.fixture
 def parse_source(self, python_parser):
 """解析 Python 源码字符串，返回 (tree, source)。"""
 def _parse(source: str) -> tuple:
 source_bytes = source.encode("utf-8")
 tree = python_parser.parse(source_bytes)
 return tree, source
 return _parse
 def test_extract_all_symbols(self, graph_extractor, parse_source):
 """Symbol 抽取与改造前一致。"""
 source = "def foo: pass\nclass Bar:\n def baz(self): pass\n"
 tree, _ = parse_source(source)
 ctx = FileContext(file_path="test.py", language="python", repository_id="r1")
 bundle = graph_extractor.extract_all(tree, source, ctx)
 assert len(bundle.symbols) == 3
 assert bundle.symbols[0].name == "foo"
 assert bundle.symbols[1].name == "Bar"
 assert bundle.symbols[2].name == "baz"
 def test_extract_all_imports(self, graph_extractor, parse_source):
 """Import 抽取与改造前一致。"""
 source = "import os\nfrom django.http import JsonResponse\n"
 tree, _ = parse_source(source)
 ctx = FileContext(file_path="test.py", language="python", repository_id="r1")
 bundle = graph_extractor.extract_all(tree, source, ctx)
 assert len(bundle.imports) == 2
 assert bundle.imports[0].target_module == "os"
 assert bundle.imports[1].target_module == "django.http"
 def test_extract_all_calls(self, graph_extractor, parse_source):
 """Call 抽取与改造前一致。"""
 source = "def foo:\n bar\n obj.method\n"
 tree, _ = parse_source(source)
 ctx = FileContext(file_path="test.py", language="python", repository_id="r1")
 bundle = graph_extractor.extract_all(tree, source, ctx)
 assert len(bundle.calls) == 2
 assert bundle.calls[0].callee_name == "bar"
 assert bundle.calls[0].call_type == "DIRECT"
 assert bundle.calls[1].callee_name == "method"
 assert bundle.calls[1].call_type == "METHOD"
 def test_extract_all_endpoints(self, graph_extractor, parse_source):
 """Endpoint 抽取与改造前一致（非 urls.py 返回空）。"""
 source = "def foo: pass\n"
 tree, _ = parse_source(source)
 ctx = FileContext(file_path="views.py", language="python", repository_id="r1")
 bundle = graph_extractor.extract_all(tree, source, ctx)
 assert bundle.endpoints ==
 def test_extract_all_endpoints_from_urls(self, graph_extractor, parse_source):
 """urls.py 中的 endpoint 抽取。"""
 source = 'path("users/", views.UserViewSet.as_view({"get": "list"}))\n'
 tree, _ = parse_source(source)
 ctx = FileContext(file_path="urls.py", language="python", repository_id="r1")
 bundle = graph_extractor.extract_all(tree, source, ctx)
 assert len(bundle.endpoints) == 1
 assert bundle.endpoints[0].http_method == "GET"
 assert bundle.endpoints[0].url_path == "/users/"
 def test_extract_all_unsupported_language_graceful(self, graph_extractor, parse_source):
 """未支持语言 graceful 降级，返回空 bundle。"""
 source = "func main {}\n"
 tree, _ = parse_source(source)
 ctx = FileContext(file_path="main.go", language="go", repository_id="r1")
 bundle = graph_extractor.extract_all(tree, source, ctx)
 assert bundle.symbols ==
 assert bundle.imports ==
 assert bundle.calls ==
 assert bundle.endpoints ==
 def test_extract_all_preserves_file_path_and_language(self, graph_extractor, parse_source):
 """Bundle 元数据正确保留。"""
 source = "def foo: pass\n"
 tree, _ = parse_source(source)
 ctx = FileContext(file_path="app/models.py", language="python", repository_id="r1")
 bundle = graph_extractor.extract_all(tree, source, ctx)
 assert bundle.file_path == "app/models.py"
 assert bundle.language == "python"
 def test_extract_all_error_isolation(self, graph_extractor, parse_source):
 """单维度抽取失败不影响其他维度。"""
 # 语法有效的 Python，但某些抽取可能失败
 source = "def foo:\n import os\n bar\n"
 tree, _ = parse_source(source)
 ctx = FileContext(file_path="test.py", language="python", repository_id="r1")
 bundle = graph_extractor.extract_all(tree, source, ctx)
 # 所有维度都应该有结果（不会因为某个维度失败而全部丢失）
 assert len(bundle.symbols) == 1
 assert len(bundle.imports) == 1
 assert len(bundle.calls) == 1
