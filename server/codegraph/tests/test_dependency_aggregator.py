""" 单测 —— file_neighbors / component_neighbors 双向依赖聚合。
用 resolver conftest 路线 B（acreate_symbols/imports/calls）造多文件场景，断言文件级
与组件级上下游集合、计数、去重、direction 三态。
"""
from __future__ import annotations
import uuid
from collections.abc import AsyncIterator
import pytest
import pytest_asyncio
from asgiref.sync import sync_to_async
from codegraph.resolver.tests.conftest import (
 CallSpec,
 ImportSpec,
 SymbolSpec,
 acreate_calls,
 acreate_imports,
 acreate_symbols,
)
from codegraph.services.dependency_aggregator import (
 component_neighbors,
 file_neighbors,
)
@pytest_asyncio.fixture
async def test_repository -> AsyncIterator:
 """本地 Repository fixture（codegraph/tests/ 不继承 resolver conftest）。"""
 from repositories.models import Repository
 repo = await Repository.objects.acreate(
 id=uuid.uuid4,
 name="test-agg-repo",
 git_url="https://github.com/test/agg-repo.git",
 default_branch="main",
 )
 yield repo
 await Repository.objects.filter(id=repo.id).adelete
@pytest.mark.django_db(transaction=True)
async def test_file_neighbors_bidirectional_with_count_and_dedup(test_repository) -> None:
 """文件级：A 调 B 两次（聚合带 count）、C 调 A → 查 A 上游 {C} 下游 {B count=2}。"""
 await acreate_symbols(
 test_repository,
 [
 SymbolSpec(name="a_fn", file_path="a.py", start_line=1),
 SymbolSpec(name="b_fn", file_path="b.py", start_line=1),
 SymbolSpec(name="c_fn", file_path="c.py", start_line=1),
 ],
 )
 await acreate_calls(
 test_repository,
 [
 CallSpec(caller_file="a.py", callee_name="b_fn", callee_file="b.py"),
 CallSpec(caller_file="a.py", callee_name="b_fn", callee_file="b.py"),
 CallSpec(caller_file="c.py", callee_name="a_fn", callee_file="a.py"),
 ],
 )
 result = await sync_to_async(file_neighbors)(str(test_repository.id), "a.py")
 downstream = {row["file"]: row["count"] for row in result["downstream"]}
 upstream = {row["file"]: row["count"] for row in result["upstream"]}
 assert downstream == {"b.py": 2}
 assert upstream == {"c.py": 1}
@pytest.mark.django_db(transaction=True)
async def test_file_neighbors_import_overlay(test_repository) -> None:
 """文件级：纯 import（A import B 但无调用）经 resolver 解析叠加为下游 import 边。"""
 await acreate_symbols(
 test_repository,
 [
 SymbolSpec(name="a_fn", file_path="pkg/a.py", start_line=1),
 SymbolSpec(name="b_fn", file_path="pkg/b.py", start_line=1),
 ],
 )
 await acreate_imports(
 test_repository,
 [
 ImportSpec(
 source_file="pkg/a.py",
 target_module="pkg.b",
 imported_names=["b_fn"],
 )
 ],
 )
 result = await sync_to_async(file_neighbors)(str(test_repository.id), "pkg/a.py")
 downstream = {row["file"]: row["kinds"] for row in result["downstream"]}
 assert "pkg/b.py" in downstream
 assert "import" in downstream["pkg/b.py"]
 # 反向：查 b 的上游含 a（import）。
 up_b = await sync_to_async(file_neighbors)(
 str(test_repository.id), "pkg/b.py", "up"
 )
 assert any(row["file"] == "pkg/a.py" for row in up_b["upstream"])
@pytest.mark.django_db(transaction=True)
async def test_file_neighbors_direction_filter(test_repository) -> None:
 """direction=up/down 只返回对应方向。"""
 await acreate_symbols(
 test_repository,
 [
 SymbolSpec(name="a_fn", file_path="a.py", start_line=1),
 SymbolSpec(name="b_fn", file_path="b.py", start_line=1),
 ],
 )
 await acreate_calls(
 test_repository,
 [CallSpec(caller_file="a.py", callee_name="b_fn", callee_file="b.py")],
 )
 down = await sync_to_async(file_neighbors)(str(test_repository.id), "a.py", "down")
 assert "downstream" in down and "upstream" not in down
 up = await sync_to_async(file_neighbors)(str(test_repository.id), "b.py", "up")
 assert "upstream" in up and "downstream" not in up
@pytest.mark.django_db(transaction=True)
async def test_component_neighbors_bidirectional(test_repository) -> None:
 """组件级 SC：A 用 B、C 用 A → 查 A 上游 {C} 下游 {B}。"""
 symbols = await acreate_symbols(
 test_repository,
 [
 SymbolSpec(name="A", file_path="src/A.vue", symbol_type="CLASS", start_line=1),
 SymbolSpec(name="B", file_path="src/B.vue", symbol_type="CLASS", start_line=1),
 SymbolSpec(name="C", file_path="src/C.vue", symbol_type="CLASS", start_line=1),
 ],
 )
 a_sym, b_sym, c_sym = symbols
 await acreate_calls(
 test_repository,
 [
 # A 用 B：A.vue 内 TEMPLATE_REF 边连到 B 组件 Symbol
 CallSpec(
 caller_file="src/A.vue",
 callee_name="B",
 call_type="TEMPLATE_REF",
 callee_symbol=b_sym,
 callee_file="src/B.vue",
 is_cross_file=True,
 ),
 # C 用 A：C.vue 内 TEMPLATE_REF 边连到 A 组件 Symbol
 CallSpec(
 caller_file="src/C.vue",
 callee_name="A",
 call_type="TEMPLATE_REF",
 callee_symbol=a_sym,
 callee_file="src/A.vue",
 is_cross_file=True,
 ),
 ],
 )
 result = await sync_to_async(component_neighbors)(
 str(test_repository.id), str(a_sym.id)
 )
 upstream_names = {row["name"] for row in result["upstream"]}
 downstream_names = {row["name"] for row in result["downstream"]}
 assert upstream_names == {"C"}
 assert downstream_names == {"B"}
