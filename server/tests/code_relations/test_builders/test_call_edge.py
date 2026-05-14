"""CallEdgeBuilder 测试（per Phase / ）。"""
from __future__ import annotations
import math
import uuid
from unittest.mock import patch
import pytest
from asgiref.sync import sync_to_async
from code_relations.builders.call_edge import CallEdgeBuilder
from code_relations.models import EdgeType
from code_relations.symbol_lookup import SymbolChunkResolver
from codegraph.models import CallEdge as CodegraphCallEdge
from codegraph.models import Symbol
@sync_to_async
def _create_symbol(repository, name: str, file_path: str, start_line: int) -> Symbol:
 return Symbol.objects.create(
 repository=repository,
 name=name,
 symbol_type=Symbol.SymbolType.FUNCTION,
 file_path=file_path,
 start_line=start_line,
 end_line=start_line + 5,
 )
@sync_to_async
def _create_call_edge(repository, caller: Symbol, callee_name: str, line_number: int) -> None:
 CodegraphCallEdge.objects.create(
 repository=repository,
 caller_symbol=caller,
 callee_name=callee_name,
 call_type=CodegraphCallEdge.CallType.DIRECT,
 line_number=line_number,
 )
def _patch_resolver(resolve_fn):
 """patch SymbolChunkResolver.resolve 用 side_effect 注入。"""
 return patch.object(SymbolChunkResolver, "resolve", side_effect=resolve_fn, autospec=False)
@pytest.mark.django_db(transaction=True)
async def test_basic_two_groups(repository) -> None:
 """3 CallEdge → 2 ChunkEdge（同 caller→foo 调用 2 次合并；caller→bar 1 次）。"""
 caller_a = await _create_symbol(repository, "caller_a", "a.py", 10)
 caller_b = await _create_symbol(repository, "caller_b", "b.py", 20)
 await _create_symbol(repository, "foo", "a.py", 100)
 await _create_symbol(repository, "bar", "c.py", 5)
 await _create_call_edge(repository, caller_a, "foo", 11)
 await _create_call_edge(repository, caller_a, "foo", 12)
 await _create_call_edge(repository, caller_b, "bar", 21)
 cid_caller_a = uuid.uuid4
 cid_callee_foo = uuid.uuid4
 cid_caller_b = uuid.uuid4
 cid_callee_bar = uuid.uuid4
 async def _resolve(file_path: str, line: int):
 return {
 ("a.py", 10): cid_caller_a,
 ("a.py", 100): cid_callee_foo,
 ("b.py", 20): cid_caller_b,
 ("c.py", 5): cid_callee_bar,
 }.get((file_path, line))
 with _patch_resolver(_resolve):
 edges = await CallEdgeBuilder.build(repository, )
 assert len(edges) == 2
 by_target = {e.target_chunk_id: e for e in edges}
 assert by_target[cid_callee_foo].source_chunk_id == cid_caller_a
 assert by_target[cid_callee_foo].edge_type == EdgeType.CALL
 assert by_target[cid_callee_foo].weight == pytest.approx(math.log10(3) / 3.0)
 assert by_target[cid_callee_foo].metadata == {"call_count": 2, "callee_name": "foo"}
 assert by_target[cid_callee_bar].source_chunk_id == cid_caller_b
 assert by_target[cid_callee_bar].weight == pytest.approx(math.log10(2) / 3.0)
@pytest.mark.django_db(transaction=True)
async def test_callee_lookup_miss_skipped(repository) -> None:
 """callee_name 在 Symbol 中查不到 → skip。"""
 caller = await _create_symbol(repository, "caller", "a.py", 10)
 await _create_call_edge(repository, caller, "missing", 11)
 cid = uuid.uuid4
 async def _resolve(file_path: str, line: int):
 return cid if (file_path, line) == ("a.py", 10) else None
 with _patch_resolver(_resolve):
 edges = await CallEdgeBuilder.build(repository, )
 assert edges ==
@pytest.mark.django_db(transaction=True)
async def test_caller_chunk_resolve_miss_skipped(repository) -> None:
 """caller line 不在任何 chunk 内 → skip。"""
 caller = await _create_symbol(repository, "caller", "a.py", 10)
 await _create_symbol(repository, "foo", "a.py", 100)
 await _create_call_edge(repository, caller, "foo", 11)
 async def _resolve(file_path: str, line: int):
 return None
 with _patch_resolver(_resolve):
 edges = await CallEdgeBuilder.build(repository, )
 assert edges ==
@pytest.mark.django_db(transaction=True)
async def test_empty_call_edge_table(repository) -> None:
 """空 codegraph.CallEdge → 。"""
 async def _resolve(file_path: str, line: int):
 return None
 with _patch_resolver(_resolve):
 edges = await CallEdgeBuilder.build(repository, )
 assert edges ==
@pytest.mark.django_db(transaction=True)
async def test_self_loop_allowed(repository) -> None:
 """caller 与 callee 解析到同 chunk_id → 仍生成 1 条 self-loop ChunkEdge。"""
 caller = await _create_symbol(repository, "self_caller", "a.py", 10)
 await _create_symbol(repository, "self_caller_callee", "a.py", 12)
 await _create_call_edge(repository, caller, "self_caller_callee", 11)
 cid = uuid.uuid4
 async def _resolve(file_path: str, line: int):
 return cid
 with _patch_resolver(_resolve):
 edges = await CallEdgeBuilder.build(repository, )
 assert len(edges) == 1
 assert edges[0].source_chunk_id == edges[0].target_chunk_id == cid
@pytest.mark.django_db(transaction=True)
async def test_log10_weight_at_count_1000(repository) -> None:
 """call_count=1000 → weight clamp 到 1.0。"""
 caller = await _create_symbol(repository, "caller", "a.py", 10)
 await _create_symbol(repository, "foo", "a.py", 100)
 @sync_to_async
 def _bulk_create_calls -> None:
 edges = [
 CodegraphCallEdge(
 repository=repository,
 caller_symbol=caller,
 callee_name="foo",
 call_type=CodegraphCallEdge.CallType.DIRECT,
 line_number=11 + i,
 )
 for i in range(1000)
 ]
 CodegraphCallEdge.objects.bulk_create(edges)
 await _bulk_create_calls
 cid_caller = uuid.uuid4
 cid_callee = uuid.uuid4
 async def _resolve(file_path: str, line: int):
 return {("a.py", 10): cid_caller, ("a.py", 100): cid_callee}.get(
 (file_path, line)
 )
 with _patch_resolver(_resolve):
 edges = await CallEdgeBuilder.build(repository, )
 assert len(edges) == 1
 assert edges[0].weight == pytest.approx(1.0)
 assert edges[0].metadata["call_count"] == 1000
