""" 单测 —— SymbolResolver 4 路径编排、alias 映射与回填入口。"""
from __future__ import annotations
import pytest
from asgiref.sync import sync_to_async
from codegraph.resolver import SymbolIndex
from codegraph.resolver.python_import import PythonImportResolver
from codegraph.resolver.symbol_resolver import SymbolResolver
from codegraph.resolver.tests.conftest import (
 CallSpec,
 ImportSpec,
 SymbolSpec,
 acreate_calls,
 acreate_imports,
 acreate_symbols,
)
async def _build_index(repo_id: str) -> SymbolIndex:
 """在 async 测试里安全构建同步 ORM 驱动的 ``SymbolIndex``。"""
 return await sync_to_async(SymbolIndex.build)(repo_id)
def _resolver(
 index: SymbolIndex,
 imports: list[object],
 *,
 include_python: bool = True,
) -> SymbolResolver:
 """按 ``source_file`` 聚合 ImportEdge，构造被测 resolver。"""
 import_by_source: dict[str, list[object]] = {}
 for edge in imports:
 source_file = getattr(edge, "source_file")
 import_by_source.setdefault(source_file, ).append(edge)
 resolver_by_lang = {"python": PythonImportResolver(index)} if include_python else {}
 return SymbolResolver(index, import_by_source, resolver_by_lang)
@pytest.mark.django_db(transaction=True)
async def test_resolve_same_file_call(test_repository) -> None:
 """路径①：caller_file 内同名调用解析到本文件 Symbol。"""
 symbols = await acreate_symbols(
 test_repository,
 [SymbolSpec(name="foo", file_path="pkg/caller.py", start_line=1)],
 )
 calls = await acreate_calls(
 test_repository,
 [CallSpec(caller_file="pkg/caller.py", callee_name="foo")],
 )
 index = await _build_index(str(test_repository.id))
 result = _resolver(index, ).resolve_call(calls[0])
 assert result.callee_symbol_id == str(symbols[0].id)
 assert result.callee_file == "pkg/caller.py"
 assert result.is_cross_file is False
@pytest.mark.django_db(transaction=True)
async def test_resolve_cross_file_via_python_import(test_repository) -> None:
 """路径②：经 ImportEdge + PythonImportResolver 解析跨文件调用。"""
 symbols = await acreate_symbols(
 test_repository,
 [SymbolSpec(name="foo", file_path="pkg/target.py", start_line=1)],
 )
 imports = await acreate_imports(
 test_repository,
 [
 ImportSpec(
 source_file="pkg/caller.py",
 target_module="pkg.target",
 imported_names=["foo"],
 )
 ],
 )
 calls = await acreate_calls(
 test_repository,
 [CallSpec(caller_file="pkg/caller.py", callee_name="foo")],
 )
 index = await _build_index(str(test_repository.id))
 result = _resolver(index, imports).resolve_call(calls[0])
 assert result.callee_symbol_id == str(symbols[0].id)
 assert result.callee_file == "pkg/target.py"
 assert result.is_cross_file is True
@pytest.mark.django_db(transaction=True)
async def test_alias_import_matches_local_name_but_looks_up_original(test_repository) -> None:
 """alias：callee_name 匹配本地名，目标文件查原始定义名。"""
 symbols = await acreate_symbols(
 test_repository,
 [SymbolSpec(name="calc", file_path="utils.py", start_line=1)],
 )
 imports = await acreate_imports(
 test_repository,
 [
 ImportSpec(
 source_file="pkg/caller.py",
 target_module="utils",
 imported_names=["calc as c"],
 )
 ],
 )
 calls = await acreate_calls(
 test_repository,
 [CallSpec(caller_file="pkg/caller.py", callee_name="c")],
 )
 index = await _build_index(str(test_repository.id))
 result = _resolver(index, imports).resolve_call(calls[0])
 assert result.callee_symbol_id == str(symbols[0].id)
 assert result.callee_file == "utils.py"
 assert result.is_cross_file is True
@pytest.mark.django_db(transaction=True)
async def test_third_party_import_keeps_result_empty_even_with_fuzzy_name(test_repository) -> None:
 """路径④：第三方 import 解析不到时留空，不用 fuzzy 同名乱连。"""
 await acreate_symbols(
 test_repository,
 [SymbolSpec(name="JsonResponse", file_path="local/http.py", start_line=1)],
 )
 imports = await acreate_imports(
 test_repository,
 [
 ImportSpec(
 source_file="views.py",
 target_module="django.http",
 imported_names=["JsonResponse"],
 )
 ],
 )
 calls = await acreate_calls(
 test_repository,
 [CallSpec(caller_file="views.py", callee_name="JsonResponse")],
 )
 index = await _build_index(str(test_repository.id))
 result = _resolver(index, imports).resolve_call(calls[0])
 assert result.callee_symbol_id is None
 assert result.callee_file is None
 assert result.is_cross_file is False
@pytest.mark.django_db(transaction=True)
async def test_missing_language_resolver_keeps_result_empty(test_repository) -> None:
 """无语言 resolver（或未知扩展）时走留空分支，不报错。"""
 await acreate_symbols(
 test_repository,
 [SymbolSpec(name="foo", file_path="pkg/target.py", start_line=1)],
 )
 imports = await acreate_imports(
 test_repository,
 [
 ImportSpec(
 source_file="pkg/caller.ts",
 target_module="pkg.target",
 imported_names=["foo"],
 )
 ],
 )
 calls = await acreate_calls(
 test_repository,
 [CallSpec(caller_file="pkg/caller.ts", callee_name="foo")],
 )
 index = await _build_index(str(test_repository.id))
 result = _resolver(index, imports, include_python=False).resolve_call(calls[0])
 assert result.callee_symbol_id is None
 assert result.callee_file is None
 assert result.is_cross_file is False
@pytest.mark.django_db(transaction=True)
async def test_same_file_ambiguity_prefers_top_level_symbol(test_repository) -> None:
 """同文件同名歧义：FUNCTION / CLASS 优先于 METHOD / VARIABLE。"""
 symbols = await acreate_symbols(
 test_repository,
 [
 SymbolSpec(
 name="foo",
 file_path="pkg/caller.py",
 symbol_type="METHOD",
 start_line=20,
 ),
 SymbolSpec(
 name="foo",
 file_path="pkg/caller.py",
 symbol_type="FUNCTION",
 start_line=1,
 ),
 ],
 )
 calls = await acreate_calls(
 test_repository,
 [CallSpec(caller_file="pkg/caller.py", callee_name="foo")],
 )
 index = await _build_index(str(test_repository.id))
 result = _resolver(index, ).resolve_call(calls[0])
 assert result.callee_symbol_id == str(symbols[1].id)
