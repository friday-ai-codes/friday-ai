""" SymbolIndex 单测 + RESEARCH Open Question Q1 路径基准坐实。
覆盖 behavior 全部 7 项：
1. 精确命中 ``exact(file,name)`` 返回该文件该名全部 IndexedSymbol（list）
2. 模糊命中 ``fuzzy(name)`` 返回全仓所有同名 IndexedSymbol（跨文件）
3. 全仓覆盖：N 文件 M 符号，索引内 IndexedSymbol 总数 == M
4. 同名歧义：同文件 top-level + 类内方法同名（不同 start_line），exact 返回长度 2 的 list
5. has_file：仓内 True、仓外 False
6. 未命中：exact/fuzzy 对不存在键返回空 list（不抛 KeyError）
7. Q1：经真实 GraphWriter 写库后 ``Symbol.file_path`` 与构造时 source_file 一致，
 ``has_file`` 用精确等值口径命中
"""
from __future__ import annotations
import pytest
from asgiref.sync import sync_to_async
from codegraph.resolver import IndexedSymbol, SymbolIndex
from codegraph.resolver.tests.conftest import (
 SymbolSpec,
 acreate_symbols,
 build_repo_via_graph_writer,
)
async def _build_index(repo_id: str) -> SymbolIndex:
 """在 async 测试里安全调用 sync 的 ``SymbolIndex.build``（内部走 sync ORM iterator）。"""
 return await sync_to_async(SymbolIndex.build)(repo_id)
@pytest.mark.django_db(transaction=True)
async def test_exact_hit_returns_indexed_symbols(test_repository) -> None:
 """精确查 (file,name) 命中，返回 IndexedSymbol list。"""
 await acreate_symbols(
 test_repository,
 [SymbolSpec(name="foo", file_path="pkg/a.py", start_line=1)],
 )
 index = await _build_index(str(test_repository.id))
 hits = index.exact("pkg/a.py", "foo")
 assert len(hits) == 1
 assert isinstance(hits[0], IndexedSymbol)
 assert hits[0].name == "foo"
 assert hits[0].file_path == "pkg/a.py"
@pytest.mark.django_db(transaction=True)
async def test_fuzzy_hit_spans_files(test_repository) -> None:
 """模糊查 name 命中全仓所有同名符号（跨文件）。"""
 await acreate_symbols(
 test_repository,
 [
 SymbolSpec(name="handler", file_path="pkg/a.py", start_line=1),
 SymbolSpec(name="handler", file_path="pkg/b.py", start_line=1),
 SymbolSpec(name="other", file_path="pkg/c.py", start_line=1),
 ],
 )
 index = await _build_index(str(test_repository.id))
 hits = index.fuzzy("handler")
 assert len(hits) == 2
 assert {h.file_path for h in hits} == {"pkg/a.py", "pkg/b.py"}
@pytest.mark.django_db(transaction=True)
async def test_full_repo_coverage(test_repository) -> None:
 """N 文件 M 符号全部进索引（总数 == M）。"""
 specs = [
 SymbolSpec(name="a", file_path="pkg/x.py", start_line=1),
 SymbolSpec(name="b", file_path="pkg/x.py", start_line=5),
 SymbolSpec(name="c", file_path="pkg/y.py", start_line=1),
 SymbolSpec(name="d", file_path="pkg/z.py", start_line=1),
 ]
 await acreate_symbols(test_repository, specs)
 index = await _build_index(str(test_repository.id))
 total = sum(len(index.fuzzy(name)) for name in {"a", "b", "c", "d"})
 assert total == len(specs)
@pytest.mark.django_db(transaction=True)
async def test_same_name_ambiguity_kept_as_list(test_repository) -> None:
 """同文件 top-level + 类内方法同名（不同 start_line）都进精确索引，不互相覆盖（Pitfall 4）。"""
 await acreate_symbols(
 test_repository,
 [
 SymbolSpec(name="foo", file_path="pkg/m.py", symbol_type="FUNCTION", start_line=1),
 SymbolSpec(name="foo", file_path="pkg/m.py", symbol_type="METHOD", start_line=10),
 ],
 )
 index = await _build_index(str(test_repository.id))
 hits = index.exact("pkg/m.py", "foo")
 assert len(hits) == 2
 assert {h.symbol_type for h in hits} == {"FUNCTION", "METHOD"}
@pytest.mark.django_db(transaction=True)
async def test_has_file(test_repository) -> None:
 """has_file 仓内返回 True、仓外路径返回 False。"""
 await acreate_symbols(
 test_repository,
 [SymbolSpec(name="foo", file_path="pkg/a.py", start_line=1)],
 )
 index = await _build_index(str(test_repository.id))
 assert index.has_file("pkg/a.py") is True
 assert index.has_file("pkg/not_exist.py") is False
@pytest.mark.django_db(transaction=True)
async def test_miss_returns_empty_list(test_repository) -> None:
 """exact/fuzzy 对不存在键返回空 list（不抛 KeyError）。"""
 await acreate_symbols(
 test_repository,
 [SymbolSpec(name="foo", file_path="pkg/a.py", start_line=1)],
 )
 index = await _build_index(str(test_repository.id))
 assert index.exact("pkg/a.py", "nonexistent") ==
 assert index.exact("pkg/ghost.py", "foo") ==
 assert index.fuzzy("nonexistent") ==
@pytest.mark.django_db(transaction=True)
async def test_path_basis_alignment(test_repository) -> None:
 """Q1 路径基准坐实：经真实 GraphWriter 写库后，Symbol.file_path 与构造 source_file 一致。
 结论（供 引用）：基准 = 仓相对路径（GraphWriter 直接落 bundle.file_path /
 SymbolData.file_path，无 repo 子目录前缀改写）。因此 ``has_file`` 用**精确等值**口径
 即可命中；``/`` + endswith 锚定兜底仅在未来发现前缀不一致时才需要（留给 ）。
 """
 from codegraph.extractors.base import ExtractionBundle, ImportData, SymbolData
 bundle = ExtractionBundle(
 file_path="pkg/mod.py",
 language="python",
 symbols=[
 SymbolData(
 name="target_func",
 symbol_type="FUNCTION",
 file_path="pkg/mod.py",
 start_line=1,
 end_line=3,
 signature="def target_func:",
 ),
 ],
 imports=[
 ImportData(
 source_file="pkg/caller.py",
 target_module="pkg.mod",
 imported_names=["target_func"],
 is_relative=False,
 ),
 ],
 )
 await build_repo_via_graph_writer(test_repository, [bundle])
 index = await _build_index(str(test_repository.id))
 assert index.has_file("pkg/mod.py") is True
 assert index.exact("pkg/mod.py", "target_func")[0].file_path == "pkg/mod.py"
