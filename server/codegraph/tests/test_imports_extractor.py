"""Tests for Import extractor ."""
import pytest
class TestImportExtractorHappyPath:
 """正常路径：basic_module.py 导入提取。"""
 def test_extracts_import_statement(self, parse_fixture, make_file_context):
 """import os 提取为 target_module="os"。"""
 from codegraph.extractors.imports import extract_imports
 tree, _, file_path = parse_fixture("basic_module.py")
 ctx = make_file_context(file_path=file_path)
 imports = extract_imports(tree, ctx)
 target_modules = {imp.target_module for imp in imports}
 assert "os" in target_modules, f"Missing 'os' in target modules: {target_modules}"
 assert "sys" in target_modules, f"Missing 'sys' in target modules: {target_modules}"
 def test_extracts_import_from_statement(self, parse_fixture, make_file_context):
 """from typing import Optional, List 提取 target_module="typing"。"""
 from codegraph.extractors.imports import extract_imports
 tree, _, _ = parse_fixture("basic_module.py")
 ctx = make_file_context
 imports = extract_imports(tree, ctx)
 target_modules = {imp.target_module for imp in imports}
 assert "typing" in target_modules, f"Missing 'typing' in target modules: {target_modules}"
 assert "collections" in target_modules, f"Missing 'collections' in target modules: {target_modules}"
 def test_multiple_imports_from_same_module(self, parse_fixture, make_file_context):
 """from collections import defaultdict, OrderedDict 合并为一条 ImportData。"""
 from codegraph.extractors.imports import extract_imports
 tree, _, _ = parse_fixture("basic_module.py")
 ctx = make_file_context
 imports = extract_imports(tree, ctx)
 collections_imps = [imp for imp in imports if imp.target_module == "collections"]
 assert len(collections_imps) == 1, \
 f"Expected 1 ImportData for collections, got {len(collections_imps)}"
 imported = collections_imps[0].imported_names
 assert "defaultdict" in imported, f"Missing defaultdict in {imported}"
 assert "OrderedDict" in imported, f"Missing OrderedDict in {imported}"
 def test_source_file_field(self, parse_fixture, make_file_context):
 """所有 ImportData.source_file == ctx.file_path。"""
 from codegraph.extractors.imports import extract_imports
 tree, _, file_path = parse_fixture("basic_module.py")
 ctx = make_file_context(file_path=file_path)
 imports = extract_imports(tree, ctx)
 for imp in imports:
 assert imp.source_file == file_path, \
 f"Expected source_file={file_path}, got {imp.source_file}"
 def test_non_relative_import(self, parse_fixture, make_file_context):
 """绝对导入 is_relative == False。"""
 from codegraph.extractors.imports import extract_imports
 tree, _, _ = parse_fixture("basic_module.py")
 ctx = make_file_context
 imports = extract_imports(tree, ctx)
 for imp in imports:
 assert imp.is_relative is False, \
 f"{imp.target_module}: expected is_relative=False"
class TestImportExtractorEdgeCases:
 """边界条件测试。"""
 def test_relative_import(self, parse_source, make_file_context):
 """相对导入 is_relative == True。"""
 from codegraph.extractors.imports import extract_imports
 tree, source = parse_source("from .module import foo\n")
 ctx = make_file_context
 imports = extract_imports(tree, ctx)
 assert len(imports) > 0, "No imports extracted for relative import"
 rel_imps = [imp for imp in imports if imp.is_relative]
 assert len(rel_imps) > 0, f"No relative imports found in {imports}"
 assert rel_imps[0].target_module.startswith("."), \
 f"Relative module should start with '.', got {rel_imps[0].target_module}"
 def test_conditional_import(self, parse_fixture, make_file_context):
 """条件导入被提取（typing/typing_extensions）。"""
 from codegraph.extractors.imports import extract_imports
 tree, _, _ = parse_fixture("edge_cases.py")
 ctx = make_file_context
 imports = extract_imports(tree, ctx)
 target_modules = {imp.target_module for imp in imports}
 # edge_cases.py 有条件导入 typing 和 typing_extensions
 assert len(target_modules) >= 1, f"Expected at least 1 import, got {target_modules}"
 def test_empty_file_returns_empty(self, parse_source, make_file_context):
 """空文件返回空列表。"""
 from codegraph.extractors.imports import extract_imports
 tree, source = parse_source("")
 ctx = make_file_context
 imports = extract_imports(tree, ctx)
 assert imports ==, f"Expected empty, got {len(imports)} imports"
 def test_no_duplicate_imports(self, parse_fixture, make_file_context):
 """同一 import 语句不产生重复 ImportData。"""
 from codegraph.extractors.imports import extract_imports
 # 使用只有单个 import 语句的源文件
 source = "import os\n"
 import tree_sitter_python
 from tree_sitter import Language, Parser
 ts_lang = Language(tree_sitter_python.language)
 parser = Parser(ts_lang)
 tree = parser.parse(source.encode("utf-8"))
 ctx = make_file_context
 imports = extract_imports(tree, ctx)
 os_imports = [imp for imp in imports if imp.target_module == "os"]
 assert len(os_imports) == 1, \
 f"Expected exactly 1 'os' import, got {len(os_imports)}"
 def test_aliased_import(self, parse_source, make_file_context):
 """别名导入 imported_names 包含 as 格式。"""
 from codegraph.extractors.imports import extract_imports
 tree, source = parse_source("import os.path as path\n")
 ctx = make_file_context
 imports = extract_imports(tree, ctx)
 assert len(imports) > 0, "No imports extracted"
 # 检查是否有别名格式的 imported_name
 aliased = [imp for imp in imports if any(" as " in name for name in imp.imported_names)]
 assert len(aliased) > 0, f"No aliased imports found in {imports}"
