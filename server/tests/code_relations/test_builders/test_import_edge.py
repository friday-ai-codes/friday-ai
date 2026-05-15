"""ImportEdgeBuilder 测试（per Phase）。"""
from __future__ import annotations
import uuid
import pytest
from asgiref.sync import sync_to_async
from code_relations.builders.import_edge import ImportEdgeBuilder
from code_relations.models import ChunkRegistry, EdgeType
from codegraph.models import ImportEdge as CodegraphImportEdge
@sync_to_async
def _make_chunk(repository, file_path: str, chunk_index: int = 0) -> ChunkRegistry:
 return ChunkRegistry.objects.create(
 chunk_id=uuid.uuid4,
 content_hash="x" * 64,
 repository=repository,
 file_path=file_path,
 chunk_index=chunk_index,
 )
@sync_to_async
def _make_import(
 repository,
 source_file: str,
 target_module: str,
 is_relative: bool = False,
 imported_names: list[str] | None = None,
) -> None:
 CodegraphImportEdge.objects.create(
 repository=repository,
 source_file=source_file,
 target_module=target_module,
 is_relative=is_relative,
 imported_names=imported_names or,
 )
@pytest.mark.django_db(transaction=True)
async def test_basic_two_imports(repository) -> None:
 """2 ImportEdge → 2 ChunkEdge[IMPORT] weight=1.0。"""
 src_a = await _make_chunk(repository, "src/a.py")
 tgt_u = await _make_chunk(repository, "services/utils.py")
 src_b = await _make_chunk(repository, "src/b.py")
 tgt_c = await _make_chunk(repository, "src/c.py")
 await _make_import(repository, "src/a.py", "services.utils", imported_names=["foo"])
 await _make_import(
 repository, "src/b.py", "src/c", is_relative=True, imported_names=["bar"]
 )
 edges = await ImportEdgeBuilder.build(repository, )
 assert len(edges) == 2
 by_src = {e.source_chunk_id: e for e in edges}
 assert by_src[src_a.chunk_id].target_chunk_id == tgt_u.chunk_id
 assert by_src[src_a.chunk_id].edge_type == EdgeType.IMPORT
 assert by_src[src_a.chunk_id].weight == 1.0
 assert by_src[src_a.chunk_id].metadata["imported_names"] == ["foo"]
 assert by_src[src_b.chunk_id].target_chunk_id == tgt_c.chunk_id
@pytest.mark.django_db(transaction=True)
async def test_target_module_resolve_miss_skipped(repository) -> None:
 """target_module 在 ChunkRegistry 找不到对应 file → skip。"""
 await _make_chunk(repository, "src/a.py")
 await _make_import(repository, "src/a.py", "nonexistent.lib")
 edges = await ImportEdgeBuilder.build(repository, )
 assert edges ==
@pytest.mark.django_db(transaction=True)
async def test_source_file_not_in_registry_skipped(repository) -> None:
 """source_file 不在 ChunkRegistry → skip。"""
 await _make_chunk(repository, "src/c.py")
 await _make_import(repository, "src/missing.py", "src.c")
 edges = await ImportEdgeBuilder.build(repository, )
 assert edges ==
@pytest.mark.django_db(transaction=True)
async def test_empty_import_edge_table(repository) -> None:
 edges = await ImportEdgeBuilder.build(repository, )
 assert edges ==
@pytest.mark.django_db(transaction=True)
async def test_self_loop_allowed(repository) -> None:
 """source_file == 候选 target_file 时 self-loop 允许。"""
 only = await _make_chunk(repository, "src/a.py")
 await _make_import(repository, "src/a.py", "src.a")
 edges = await ImportEdgeBuilder.build(repository, )
 assert len(edges) == 1
 assert edges[0].source_chunk_id == edges[0].target_chunk_id == only.chunk_id
@pytest.mark.django_db(transaction=True)
async def test_resolve_dot_dot_parent_import(repository) -> None:
 """ 回归：``from ..utils import X`` (target_module=``..utils``) 应解析
 到 source_file 父目录下的 utils.py，而非根 utils.py。"""
 src_a = await _make_chunk(repository, "pkg/sub/a.py")
 target_parent = await _make_chunk(repository, "pkg/utils.py")
 await _make_chunk(repository, "utils.py") # 根 utils.py 不应被选中
 await _make_import(
 repository,
 "pkg/sub/a.py",
 "..utils",
 is_relative=True,
 imported_names=["X"],
 )
 edges = await ImportEdgeBuilder.build(repository, )
 assert len(edges) == 1
 assert edges[0].source_chunk_id == src_a.chunk_id
 assert edges[0].target_chunk_id == target_parent.chunk_id
 assert edges[0].metadata["target_file"] == "pkg/utils.py"
@pytest.mark.django_db(transaction=True)
async def test_resolve_single_dot_same_package(repository) -> None:
 """ 回归：``from .helper import Y`` (target_module=``.helper``) 应解析
 到 source_file 同目录下的 helper.py。"""
 src_a = await _make_chunk(repository, "pkg/sub/a.py")
 target_same = await _make_chunk(repository, "pkg/sub/helper.py")
 await _make_import(
 repository,
 "pkg/sub/a.py",
 ".helper",
 is_relative=True,
 imported_names=["Y"],
 )
 edges = await ImportEdgeBuilder.build(repository, )
 assert len(edges) == 1
 assert edges[0].source_chunk_id == src_a.chunk_id
 assert edges[0].target_chunk_id == target_same.chunk_id
@pytest.mark.django_db(transaction=True)
async def test_endswith_no_false_match(repository) -> None:
 """ 回归：candidate ``auth.py`` 不得匹配 ``xauth.py`` / ``oauth.py``。"""
 real_target = await _make_chunk(repository, "pkg/auth.py")
 await _make_chunk(repository, "lib/xauth.py") # 不应被匹配
 await _make_chunk(repository, "lib/oauth.py") # 不应被匹配
 src = await _make_chunk(repository, "pkg/main.py")
 await _make_import(repository, "pkg/main.py", "pkg.auth")
 edges = await ImportEdgeBuilder.build(repository, )
 assert len(edges) == 1
 assert edges[0].source_chunk_id == src.chunk_id
 assert edges[0].target_chunk_id == real_target.chunk_id
 assert edges[0].metadata["target_file"] == "pkg/auth.py"
@pytest.mark.django_db(transaction=True)
async def test_vue_target_module_resolution(repository) -> None:
 """Phase work item：CANDIDATE_EXTENSIONS 含 .vue 后，target_module=components.Button
 能解析到 components/Button.vue（候选枚举枚到 .vue 扩展即命中）。"""
 src = await _make_chunk(repository, "App.vue")
 target = await _make_chunk(repository, "components/Button.vue")
 await _make_import(
 repository,
 "App.vue",
 "components.Button",
 is_relative=False,
 imported_names=["Button"],
 )
 edges = await ImportEdgeBuilder.build(repository, )
 assert len(edges) == 1
 assert edges[0].source_chunk_id == src.chunk_id
 assert edges[0].target_chunk_id == target.chunk_id
 assert edges[0].metadata["target_file"] == "components/Button.vue"
