"""CallEdgeBuilder 测试（per implementation contract / contract）。"""

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


@sync_to_async
def _create_module_level_call_edge(
    repository, caller_file: str, callee_name: str, line_number: int
) -> None:
    """构造 caller_symbol=NULL 的模块级调用边（implementation 产物）。"""
    CodegraphCallEdge.objects.create(
        repository=repository,
        caller_symbol=None,
        caller_file=caller_file,
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

    cid_caller_a = uuid.uuid4()
    cid_callee_foo = uuid.uuid4()
    cid_caller_b = uuid.uuid4()
    cid_callee_bar = uuid.uuid4()

    async def _resolve(file_path: str, line: int):
        return {
            ("a.py", 10): cid_caller_a,
            ("a.py", 100): cid_callee_foo,
            ("b.py", 20): cid_caller_b,
            ("c.py", 5): cid_callee_bar,
        }.get((file_path, line))

    with _patch_resolver(_resolve):
        edges = await CallEdgeBuilder().build(repository, [])

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
    cid = uuid.uuid4()

    async def _resolve(file_path: str, line: int):
        return cid if (file_path, line) == ("a.py", 10) else None

    with _patch_resolver(_resolve):
        edges = await CallEdgeBuilder().build(repository, [])
    assert edges == []


@pytest.mark.django_db(transaction=True)
async def test_caller_chunk_resolve_miss_skipped(repository) -> None:
    """caller line 不在任何 chunk 内 → skip。"""
    caller = await _create_symbol(repository, "caller", "a.py", 10)
    await _create_symbol(repository, "foo", "a.py", 100)
    await _create_call_edge(repository, caller, "foo", 11)

    async def _resolve(file_path: str, line: int):
        return None

    with _patch_resolver(_resolve):
        edges = await CallEdgeBuilder().build(repository, [])
    assert edges == []


@pytest.mark.django_db(transaction=True)
async def test_module_level_call_edge_skipped(repository) -> None:
    """caller_symbol=NULL 的模块级边被安全跳过，不抛 AttributeError。

    构造一条正常文件内边 + 一条模块级边（caller_symbol=None），断言 build 不崩、
    且产出的 ChunkEdge 只来自正常边（模块级边计入 skipped_caller_chunk）。
    """
    caller = await _create_symbol(repository, "caller", "a.py", 10)
    await _create_symbol(repository, "foo", "a.py", 100)
    await _create_call_edge(repository, caller, "foo", 11)
    # 模块级边：caller_symbol=NULL，按既有抽取产物 caller_file 兜底
    await _create_module_level_call_edge(repository, "m.py", "foo", 1)

    cid_caller = uuid.uuid4()
    cid_callee = uuid.uuid4()

    async def _resolve(file_path: str, line: int):
        return {("a.py", 10): cid_caller, ("a.py", 100): cid_callee}.get(
            (file_path, line)
        )

    with _patch_resolver(_resolve):
        edges = await CallEdgeBuilder().build(repository, [])

    # 仅正常文件内边产出 ChunkEdge；模块级边被跳过而非崩溃
    assert len(edges) == 1
    assert edges[0].source_chunk_id == cid_caller
    assert edges[0].target_chunk_id == cid_callee
    assert edges[0].metadata["callee_name"] == "foo"


@pytest.mark.django_db(transaction=True)
async def test_empty_call_edge_table(repository) -> None:
    """空 codegraph.CallEdge → []。"""

    async def _resolve(file_path: str, line: int):
        return None

    with _patch_resolver(_resolve):
        edges = await CallEdgeBuilder().build(repository, [])
    assert edges == []


@pytest.mark.django_db(transaction=True)
async def test_self_loop_allowed(repository) -> None:
    """caller 与 callee 解析到同 chunk_id → 仍生成 1 条 self-loop ChunkEdge。"""
    caller = await _create_symbol(repository, "self_caller", "a.py", 10)
    await _create_symbol(repository, "self_caller_callee", "a.py", 12)
    await _create_call_edge(repository, caller, "self_caller_callee", 11)
    cid = uuid.uuid4()

    async def _resolve(file_path: str, line: int):
        return cid

    with _patch_resolver(_resolve):
        edges = await CallEdgeBuilder().build(repository, [])
    assert len(edges) == 1
    assert edges[0].source_chunk_id == edges[0].target_chunk_id == cid


# =============================================================================
# implementation / 跨语言守门 parametrize 测试
# 静态审计：CallEdgeBuilder 基于 codegraph.CallEdge.callee_name 字符串名匹配 Symbol.name，
# 无 file extension / language 假设 → 天然语言无关 git diff = 0。
# =============================================================================


@pytest.mark.parametrize(
    "caller_file,callee_file,callee_name",
    [
        ("handlers/user.go", "handlers/user.go", "GetUser"),         # Go
        ("src/api.ts", "src/utils.ts", "fetchData"),                 # TypeScript
        ("components/App.vue", "components/Button.vue", "onClick"),  # Vue
    ],
)
@pytest.mark.django_db(transaction=True)
async def test_call_edge_cross_language_resolution(
    repository, caller_file: str, callee_file: str, callee_name: str
) -> None:
    """implementation / work item 守门：CallEdge 对 Go / TS / Vue 命名解析均能建 edge。

    构造 caller Symbol + callee Symbol + CodegraphCallEdge + mock SymbolChunkResolver.resolve
    → 断言生成 ≥ 1 ChunkEdge[CALL]。
    """
    caller = await _create_symbol(repository, "caller_x", caller_file, 10)
    await _create_symbol(repository, callee_name, callee_file, 100)
    await _create_call_edge(repository, caller, callee_name, 11)

    cid_caller = uuid.uuid4()
    cid_callee = uuid.uuid4()

    async def _resolve(file_path: str, line: int):
        return {(caller_file, 10): cid_caller, (callee_file, 100): cid_callee}.get(
            (file_path, line)
        )

    with _patch_resolver(_resolve):
        edges = await CallEdgeBuilder().build(repository, [])
    assert len(edges) >= 1
    assert edges[0].edge_type == EdgeType.CALL
    assert edges[0].metadata["callee_name"] == callee_name


@pytest.mark.django_db(transaction=True)
async def test_log10_weight_at_count_1000(repository) -> None:
    """call_count=1000 → weight clamp 到 1.0。"""
    caller = await _create_symbol(repository, "caller", "a.py", 10)
    await _create_symbol(repository, "foo", "a.py", 100)

    @sync_to_async
    def _bulk_create_calls() -> None:
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

    await _bulk_create_calls()

    cid_caller = uuid.uuid4()
    cid_callee = uuid.uuid4()

    async def _resolve(file_path: str, line: int):
        return {("a.py", 10): cid_caller, ("a.py", 100): cid_callee}.get(
            (file_path, line)
        )

    with _patch_resolver(_resolve):
        edges = await CallEdgeBuilder().build(repository, [])
    assert len(edges) == 1
    assert edges[0].weight == pytest.approx(1.0)
    assert edges[0].metadata["call_count"] == 1000
