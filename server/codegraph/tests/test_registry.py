"""Registry 测试 —— 验证 EXTRACTOR_REGISTRY + BACKEND_REGISTRY + get/register API。"""
from __future__ import annotations
import pytest
from codegraph.backends.protocols import TreeSitterBackend
from codegraph.extractors.base import FileContext
from codegraph.extractors.go_extractor import GoExtractor
from codegraph.extractors.python_extractor import PythonExtractor
from codegraph.extractors.ts_extractor import TSExtractor, TSXExtractor
from codegraph.extractors.registry import (
 BACKEND_REGISTRY,
 EXTRACTOR_REGISTRY,
 TreeSitterExtractor,
 get_backend,
 get_extractor,
 register_backend,
 register_extractor,
)
class TestBackendRegistry:
 """BACKEND_REGISTRY + get_backend 测试。"""
 def test_get_backend_python_returns_tree_sitter_backend(self):
 """get_backend('python') 返回 TreeSitterBackend 实例。"""
 backend = get_backend("python")
 assert isinstance(backend, TreeSitterBackend)
 assert backend.language == "python"
 def test_get_backend_unknown_returns_none(self):
 """未注册语言返回 None。"""
 assert get_backend("unknown") is None
 def test_backend_registry_has_python(self):
 """BACKEND_REGISTRY 默认含 python。"""
 assert "python" in BACKEND_REGISTRY
 def test_register_backend_adds_new_language(self):
 """register_backend 成功注册新 backend。"""
 class FakeBackend:
 def __init__(self, language: str) -> None:
 self.language = language
 def parse_file(self, file_path: str, source: str):
 return None
 def extract_symbols(self, tree, source, ctx):
 return
 def extract_imports(self, tree, ctx):
 return
 def extract_calls(self, tree, ctx):
 return
 def extract_endpoints(self, tree, source, ctx):
 return
 register_backend("fake", FakeBackend)
 assert "fake" in BACKEND_REGISTRY
 backend = get_backend("fake")
 assert isinstance(backend, FakeBackend)
class TestExtractorRegistry:
 """EXTRACTOR_REGISTRY + get_extractor 测试。"""
 def test_get_extractor_python_returns_python_extractor(self):
 """get_extractor('python') 返回 PythonExtractor 实例。"""
 extractor = get_extractor("python")
 assert isinstance(extractor, PythonExtractor)
 def test_get_extractor_unknown_returns_none(self):
 """未注册语言返回 None。"""
 assert get_extractor("unknown") is None
 def test_extractor_registry_has_python(self):
 """EXTRACTOR_REGISTRY 默认含 python。"""
 assert "python" in EXTRACTOR_REGISTRY
 assert EXTRACTOR_REGISTRY["python"] is PythonExtractor
 def test_tree_sitter_extractor_extract(self):
 """TreeSitterExtractor.extract 返回完整 ExtractionBundle。"""
 extractor = TreeSitterExtractor
 ctx = FileContext(file_path="test.py", language="python", repository_id="r1")
 source = "def foo:\n import os\n bar\n"
 bundle = extractor.extract("test.py", source, ctx)
 assert bundle.file_path == "test.py"
 assert bundle.language == "python"
 assert len(bundle.symbols) == 1
 assert len(bundle.imports) == 1
 assert len(bundle.calls) == 1
 def test_python_extractor_extract(self):
 """PythonExtractor.extract 行为与 TreeSitterExtractor 一致。"""
 extractor = PythonExtractor
 ctx = FileContext(file_path="test.py", language="python", repository_id="r1")
 source = "class MyClass:\n def method(self):\n pass\n"
 bundle = extractor.extract("test.py", source, ctx)
 assert len(bundle.symbols) == 2 # class + method
 assert bundle.symbols[0].symbol_type == "CLASS"
 assert bundle.symbols[1].symbol_type == "METHOD"
 def test_register_extractor_adds_new_language(self):
 """register_extractor 成功注册新抽取器。"""
 class FakeExtractor:
 def extract(self, file_path: str, source: str, ctx):
 from codegraph.extractors.base import ExtractionBundle
 return ExtractionBundle
 register_extractor("fake", FakeExtractor) # type: ignore[arg-type]
 assert "fake" in EXTRACTOR_REGISTRY
 extractor = get_extractor("fake")
 assert isinstance(extractor, FakeExtractor)
 def test_get_extractor_go_returns_go_extractor(self):
 """get_extractor('go') 返回 GoExtractor 实例（Phase 注册）。"""
 extractor = get_extractor("go")
 assert isinstance(extractor, GoExtractor)
 def test_extractor_registry_has_go(self):
 """EXTRACTOR_REGISTRY 含 go 注册且类引用为 GoExtractor。"""
 assert "go" in EXTRACTOR_REGISTRY
 assert EXTRACTOR_REGISTRY["go"] is GoExtractor
 def test_get_extractor_unknown_language_returns_none(self):
 """未知语言名仍走 warn-and-skip 路径返 None（零回归守护）。"""
 assert get_extractor("nonexistent_lang_xyz") is None
 def test_get_extractor_typescript_returns_ts_extractor(self):
 """get_extractor('typescript') 返回 TSExtractor 实例（Phase 注册）。"""
 extractor = get_extractor("typescript")
 assert isinstance(extractor, TSExtractor)
 def test_get_extractor_tsx_returns_tsx_extractor(self):
 """get_extractor('tsx') 返回 TSXExtractor 实例（Phase 注册）。"""
 extractor = get_extractor("tsx")
 assert isinstance(extractor, TSXExtractor)
 def test_extractor_registry_has_typescript(self):
 """EXTRACTOR_REGISTRY 含 typescript 注册且类引用为 TSExtractor。"""
 assert "typescript" in EXTRACTOR_REGISTRY
 assert EXTRACTOR_REGISTRY["typescript"] is TSExtractor
 def test_extractor_registry_has_tsx(self):
 """EXTRACTOR_REGISTRY 含 tsx 注册且类引用为 TSXExtractor。"""
 assert "tsx" in EXTRACTOR_REGISTRY
 assert EXTRACTOR_REGISTRY["tsx"] is TSXExtractor
