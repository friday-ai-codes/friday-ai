"""codegraph 测试共享 fixture —— tree-sitter parser + FileContext + 源码加载工具。"""
import os
import pytest
# ---- 路径常量 ----
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
def load_fixture(name: str) -> str:
 """加载 fixtures 目录下的 Python 源码文件，返回完整文本内容。"""
 path = os.path.join(FIXTURES_DIR, name)
 with open(path, "r", encoding="utf-8") as f:
 return f.read
# ---- tree-sitter Parser fixture ----
@pytest.fixture
def python_parser:
 """返回预配置的 tree-sitter Python Parser。"""
 import tree_sitter_python
 from tree_sitter import Language, Parser
 ts_lang = Language(tree_sitter_python.language)
 parser = Parser(ts_lang)
 return parser
@pytest.fixture
def python_language:
 """返回 tree-sitter Python Language 对象。"""
 import tree_sitter_python
 from tree_sitter import Language
 return Language(tree_sitter_python.language)
# ---- FileContext fixture ----
@pytest.fixture
def make_file_context:
 """工厂 fixture：创建 FileContext 实例。
 Usage:
 ctx = make_file_context(file_path="test.py")
 ctx = make_file_context(file_path="urls.py", repository_id="repo-1")
 """
 from server.codegraph.extractors.base import FileContext
 def _make(file_path: str = "test.py", language: str = "python",
 repository_id: str = "test-repo-001", module_path: str = "") -> FileContext:
 return FileContext(
 file_path=file_path,
 language=language,
 repository_id=repository_id,
 module_path=module_path,
 )
 return _make
# ---- 源码解析工具 fixture ----
@pytest.fixture
def parse_source(python_parser):
 """解析 Python 源码字符串，返回 (tree, source)。
 Usage:
 tree, source = parse_source('''
 def foo:
 return bar
 ''')
 """
 def _parse(source: str) -> tuple:
 source_bytes = source.encode("utf-8")
 tree = python_parser.parse(source_bytes)
 return tree, source
 return _parse
@pytest.fixture
def parse_fixture(python_parser):
 """解析 fixtures 目录下的 Python 源码文件，返回 (tree, source, file_path)。
 Usage:
 tree, source, path = parse_fixture("basic_module.py")
 """
 def _parse(name: str) -> tuple:
 source = load_fixture(name)
 source_bytes = source.encode("utf-8")
 tree = python_parser.parse(source_bytes)
 file_path = os.path.join(FIXTURES_DIR, name)
 return tree, source, file_path
 return _parse
