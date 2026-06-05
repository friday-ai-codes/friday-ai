"""find_related Python API 单测（per implementation Task 2）。

兑现 work item 第三条 "MAX_HOPS=2 硬上限" 在 find_related API 入口（防 LLM 通过
implementation MCP tool 传 hops=10 引发指数级 ORM 扩散）。

12 条覆盖矩阵（pytest.mark.django_db + 真 ChunkEdge fixtures）：

1. ``test_downstream_hops_1`` —— direction='downstream' hops=1 → 仅出边邻居（target=neighbor）
2. ``test_upstream_hops_1`` —— direction='upstream' hops=1 → 仅入边邻居（source=neighbor，
   走 ``idx_chunkedge_target`` 反向索引）
3. ``test_both_directions_union`` —— direction='both' → 双向 union + 同 chunk 去重
4. ``test_hops_2_includes_hop1_and_hop2`` —— hops=2 → 含一跳 + 二跳，hop 字段正确标记
5. ``test_hops_above_max_raises_value_error`` —— hops=3 → ValueError 含 'MAX_HOPS=2'
6. ``test_hops_negative_raises_value_error`` —— hops=-1 → ValueError 含 'non-negative'
7. ``test_invalid_direction_raises_value_error`` —— direction='invalid' → ValueError 含 'direction'
8. ``test_relation_types_filter_call_import`` —— relation_types=['CALL','IMPORT'] → 仅 CALL/IMPORT
9. ``test_relation_types_empty_list_treated_as_no_filter`` —— relation_types=[] = None 行为一致
10. ``test_limit_truncates_output`` —— limit=2 → 输出长度 ≤ 2
11. ``test_empty_repo_ids_returns_empty_no_query`` —— repo_ids=[] → 立即 [] 不查 ORM
12. ``test_non_existent_chunk_id_returns_empty`` —— start_chunk_id 无边 → []
13. ``test_reason_field_populated_via_explain_neighbor`` —— reason 字段非空 + 含模板关键词
14. ``test_hybrid_search_service_has_find_related_method`` —— HybridSearchService.find_related thin
    wrapper 暴露（per plan implementation MCP tool 直接调用入口）
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from code_relations.constants import MAX_HOPS
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from services.code_intel.local_provider import LocalProvider
from services.retrieval import HybridSearchService
from services.retrieval.find_related import find_related

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _create_registry(repository, chunk_id: uuid.UUID, file_path: str) -> None:
    """简化 ChunkRegistry 创建——line_start/line_end 固定 1/5。"""
    await ChunkRegistry.objects.acreate(
        chunk_id=chunk_id,
        content_hash=chunk_id.hex,
        repository=repository,
        file_path=file_path,
        chunk_index=0,
        line_start=1,
        line_end=5,
    )


# ---------------------------------------------------------------------------
# case 1：direction='downstream' hops=1 仅出边邻居
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_downstream_hops_1(repository) -> None:
    """direction='downstream' → 仅 source=start 出边；target 是邻居。"""
    start = uuid.uuid4()
    target_a = uuid.uuid4()
    target_b = uuid.uuid4()
    upstream_caller = uuid.uuid4()  # 入边 → 不应被 downstream 拿到

    for cid, fp in (
        (start, "src/start.py"),
        (target_a, "src/a.py"),
        (target_b, "src/b.py"),
        (upstream_caller, "src/upstream.py"),
    ):
        await _create_registry(repository, cid, fp)

    await ChunkEdge.objects.abulk_create([
        # downstream：start → target_a / target_b
        ChunkEdge(
            source_chunk_id=start, target_chunk_id=target_a,
            edge_type=EdgeType.CALL, weight=0.9, repository=repository,
        ),
        ChunkEdge(
            source_chunk_id=start, target_chunk_id=target_b,
            edge_type=EdgeType.IMPORT, weight=0.7, repository=repository,
        ),
        # upstream：upstream_caller → start（不应在 downstream 输出）
        ChunkEdge(
            source_chunk_id=upstream_caller, target_chunk_id=start,
            edge_type=EdgeType.CALL, weight=0.95, repository=repository,
        ),
    ])

    out = await find_related(
        str(start),
        repo_ids=[str(repository.id)],
        hops=1,
        direction="downstream",
    )

    chunk_ids = {n.chunk_id for n in out}
    assert str(target_a) in chunk_ids
    assert str(target_b) in chunk_ids
    assert str(upstream_caller) not in chunk_ids, (
        "downstream direction 不应包含入边邻居"
    )
    assert all(n.hop == 1 for n in out)


# ---------------------------------------------------------------------------
# case 2：direction='upstream' hops=1 仅入边邻居（idx_chunkedge_target 反向索引）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_upstream_hops_1(repository) -> None:
    """direction='upstream' → 仅 target=start 入边；source 是邻居（caller / importer）。"""
    start = uuid.uuid4()
    caller_a = uuid.uuid4()
    caller_b = uuid.uuid4()
    downstream_callee = uuid.uuid4()

    for cid, fp in (
        (start, "src/start.py"),
        (caller_a, "src/caller_a.py"),
        (caller_b, "src/caller_b.py"),
        (downstream_callee, "src/downstream.py"),
    ):
        await _create_registry(repository, cid, fp)

    await ChunkEdge.objects.abulk_create([
        # upstream：caller_a / caller_b → start
        ChunkEdge(
            source_chunk_id=caller_a, target_chunk_id=start,
            edge_type=EdgeType.CALL, weight=0.9, repository=repository,
        ),
        ChunkEdge(
            source_chunk_id=caller_b, target_chunk_id=start,
            edge_type=EdgeType.IMPORT, weight=0.6, repository=repository,
        ),
        # downstream：start → downstream_callee（不应在 upstream 输出）
        ChunkEdge(
            source_chunk_id=start, target_chunk_id=downstream_callee,
            edge_type=EdgeType.CALL, weight=0.95, repository=repository,
        ),
    ])

    out = await find_related(
        str(start),
        repo_ids=[str(repository.id)],
        hops=1,
        direction="upstream",
    )

    chunk_ids = {n.chunk_id for n in out}
    assert str(caller_a) in chunk_ids
    assert str(caller_b) in chunk_ids
    assert str(downstream_callee) not in chunk_ids, (
        "upstream direction 不应包含出边邻居"
    )
    assert all(n.hop == 1 for n in out)


# ---------------------------------------------------------------------------
# case 3：direction='both' 双向合并去重
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_both_directions_union(repository) -> None:
    """direction='both' → downstream + upstream 合并；同 chunk_id 去重保 max weight。"""
    start = uuid.uuid4()
    bidir_neighbor = uuid.uuid4()  # 双向边都存在 → 应只出现一次
    only_downstream = uuid.uuid4()
    only_upstream = uuid.uuid4()

    for cid, fp in (
        (start, "src/start.py"),
        (bidir_neighbor, "src/bidir.py"),
        (only_downstream, "src/down.py"),
        (only_upstream, "src/up.py"),
    ):
        await _create_registry(repository, cid, fp)

    await ChunkEdge.objects.abulk_create([
        ChunkEdge(  # downstream
            source_chunk_id=start, target_chunk_id=bidir_neighbor,
            edge_type=EdgeType.CALL, weight=0.7, repository=repository,
        ),
        ChunkEdge(  # upstream（同 neighbor，weight 较高）
            source_chunk_id=bidir_neighbor, target_chunk_id=start,
            edge_type=EdgeType.IMPORT, weight=0.95, repository=repository,
        ),
        ChunkEdge(
            source_chunk_id=start, target_chunk_id=only_downstream,
            edge_type=EdgeType.CALL, weight=0.5, repository=repository,
        ),
        ChunkEdge(
            source_chunk_id=only_upstream, target_chunk_id=start,
            edge_type=EdgeType.CALL, weight=0.6, repository=repository,
        ),
    ])

    out = await find_related(
        str(start),
        repo_ids=[str(repository.id)],
        hops=1,
        direction="both",
    )

    chunk_ids = [n.chunk_id for n in out]
    assert str(bidir_neighbor) in chunk_ids
    assert str(only_downstream) in chunk_ids
    assert str(only_upstream) in chunk_ids

    # bidir_neighbor 只能出现一次（去重）
    assert chunk_ids.count(str(bidir_neighbor)) == 1, (
        f"bidir neighbor 应去重，实际出现 {chunk_ids.count(str(bidir_neighbor))} 次"
    )

    by_chunk = {n.chunk_id: n for n in out}
    assert by_chunk[str(bidir_neighbor)].weight == pytest.approx(0.95), (
        "去重应保 max(weight)"
    )


# ---------------------------------------------------------------------------
# case 4：hops=2 含一跳 + 二跳
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_find_related_upstream_hops2_correctness(repository) -> None:
    """work item: direction='upstream' + hops=2 应返回「调用者的调用者」。

    构造调用链 A -> B -> C；find_related(start=C, direction='upstream', hops=2)
    应返回 [B (hop=1), A (hop=2)] 而非 [B (hop=1), B 的下游] —— 这是 work item
    修复前 fetch_hop2_edges 固定走 source_chunk_id__in 导致 upstream 二跳静默
    退化成「调用者的下游」的核心反例。
    """
    a = uuid.uuid4()
    b = uuid.uuid4()
    c = uuid.uuid4()
    b_downstream_red_herring = uuid.uuid4()

    for cid, fp in (
        (a, "src/a.py"),
        (b, "src/b.py"),
        (c, "src/c.py"),
        (b_downstream_red_herring, "src/red_herring.py"),
    ):
        await _create_registry(repository, cid, fp)

    await ChunkEdge.objects.abulk_create([
        ChunkEdge(
            source_chunk_id=a, target_chunk_id=b,
            edge_type=EdgeType.CALL, weight=0.9, repository=repository,
        ),
        ChunkEdge(
            source_chunk_id=b, target_chunk_id=c,
            edge_type=EdgeType.CALL, weight=0.85, repository=repository,
        ),
        # red_herring：B 的下游，work item 修复前会被错误地当作 C 的 upstream hop2
        ChunkEdge(
            source_chunk_id=b, target_chunk_id=b_downstream_red_herring,
            edge_type=EdgeType.CALL, weight=0.7, repository=repository,
        ),
    ])

    out = await find_related(
        str(c),
        repo_ids=[str(repository.id)],
        hops=2,
        direction="upstream",
    )

    by_chunk = {n.chunk_id: n for n in out}
    assert str(b) in by_chunk, "upstream hop1 应含 B（直接调用 C 者）"
    assert by_chunk[str(b)].hop == 1
    assert str(a) in by_chunk, (
        "upstream hop2 应含 A（B 的调用者，即 C 的两层调用者）；"
        "work item 修复前 fetch_hop2_edges 固定走 source__in 拿到的是 B 的下游，"
        "A 不会出现"
    )
    assert by_chunk[str(a)].hop == 2
    assert str(b_downstream_red_herring) not in by_chunk, (
        "upstream hops=2 不应包含 B 的下游（这是 work item 反例）"
    )


@pytest.mark.django_db(transaction=True)
async def test_hops_2_includes_hop1_and_hop2(repository) -> None:
    """hops=2 + downstream → hop1=直接邻居，hop2=邻居的下一跳；hop 字段标记正确。"""
    start = uuid.uuid4()
    h1 = uuid.uuid4()
    h2 = uuid.uuid4()  # h1 的 downstream

    for cid, fp in (
        (start, "src/start.py"),
        (h1, "src/h1.py"),
        (h2, "src/h2.py"),
    ):
        await _create_registry(repository, cid, fp)

    await ChunkEdge.objects.abulk_create([
        ChunkEdge(
            source_chunk_id=start, target_chunk_id=h1,
            edge_type=EdgeType.CALL, weight=0.9, repository=repository,
        ),
        ChunkEdge(
            source_chunk_id=h1, target_chunk_id=h2,
            edge_type=EdgeType.IMPORT, weight=0.7, repository=repository,
        ),
    ])

    out = await find_related(
        str(start),
        repo_ids=[str(repository.id)],
        hops=2,
        direction="downstream",
    )

    by_chunk = {n.chunk_id: n for n in out}
    assert str(h1) in by_chunk
    assert str(h2) in by_chunk
    assert by_chunk[str(h1)].hop == 1
    assert by_chunk[str(h2)].hop == 2


# ---------------------------------------------------------------------------
# case 5：hops > MAX_HOPS=2 → ValueError（复用 assert_hops_within_limit）
# ---------------------------------------------------------------------------


async def test_hops_above_max_raises_value_error() -> None:
    """hops=3 → ValueError 错误信息含 MAX_HOPS=2 字面（守卫复用 hop2_expander）。"""
    assert MAX_HOPS == 2
    with pytest.raises(ValueError) as exc_info:
        await find_related(
            str(uuid.uuid4()),
            repo_ids=["r1"],
            hops=3,
        )
    assert "MAX_HOPS=2" in str(exc_info.value)
    assert "hops=3" in str(exc_info.value)


# ---------------------------------------------------------------------------
# case 6：hops < 0 → ValueError
# ---------------------------------------------------------------------------


async def test_hops_negative_raises_value_error() -> None:
    """hops=-1 → ValueError 含 'non-negative'。"""
    with pytest.raises(ValueError) as exc_info:
        await find_related(
            str(uuid.uuid4()),
            repo_ids=["r1"],
            hops=-1,
        )
    assert "non-negative" in str(exc_info.value)


# ---------------------------------------------------------------------------
# case 7：invalid direction → ValueError
# ---------------------------------------------------------------------------


async def test_invalid_direction_raises_value_error() -> None:
    """direction='sideways' → ValueError 含 'direction'。"""
    with pytest.raises(ValueError) as exc_info:
        await find_related(
            str(uuid.uuid4()),
            repo_ids=["r1"],
            direction="sideways",  # type: ignore[arg-type]
        )
    msg = str(exc_info.value)
    assert "direction" in msg
    assert "sideways" in msg


# ---------------------------------------------------------------------------
# case 8：relation_types filter
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_relation_types_filter_call_import(repository) -> None:
    """relation_types=['CALL','IMPORT'] → 仅 CALL/IMPORT；TEST_OF 被过滤。"""
    start = uuid.uuid4()
    n_call = uuid.uuid4()
    n_import = uuid.uuid4()
    n_test = uuid.uuid4()  # 不应出现

    for cid, fp in (
        (start, "src/start.py"),
        (n_call, "src/n_call.py"),
        (n_import, "src/n_import.py"),
        (n_test, "src/n_test.py"),
    ):
        await _create_registry(repository, cid, fp)

    await ChunkEdge.objects.abulk_create([
        ChunkEdge(
            source_chunk_id=start, target_chunk_id=n_call,
            edge_type=EdgeType.CALL, weight=0.8, repository=repository,
        ),
        ChunkEdge(
            source_chunk_id=start, target_chunk_id=n_import,
            edge_type=EdgeType.IMPORT, weight=0.7, repository=repository,
        ),
        ChunkEdge(
            source_chunk_id=start, target_chunk_id=n_test,
            edge_type=EdgeType.TEST_OF, weight=0.9, repository=repository,
        ),
    ])

    out = await find_related(
        str(start),
        repo_ids=[str(repository.id)],
        relation_types=["CALL", "IMPORT"],
        direction="downstream",
    )

    chunk_ids = {n.chunk_id for n in out}
    assert str(n_call) in chunk_ids
    assert str(n_import) in chunk_ids
    assert str(n_test) not in chunk_ids, (
        "TEST_OF 应被 relation_types filter 过滤"
    )


# ---------------------------------------------------------------------------
# case 9：relation_types=[] 与 None 等价（不过滤）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_relation_types_empty_list_treated_as_no_filter(repository) -> None:
    """relation_types=[] → 不抛错且语义同 None（implementation notes）。"""
    start = uuid.uuid4()
    n_call = uuid.uuid4()
    n_test = uuid.uuid4()

    for cid, fp in (
        (start, "src/start.py"),
        (n_call, "src/n_call.py"),
        (n_test, "src/n_test.py"),
    ):
        await _create_registry(repository, cid, fp)

    await ChunkEdge.objects.abulk_create([
        ChunkEdge(
            source_chunk_id=start, target_chunk_id=n_call,
            edge_type=EdgeType.CALL, weight=0.8, repository=repository,
        ),
        ChunkEdge(
            source_chunk_id=start, target_chunk_id=n_test,
            edge_type=EdgeType.TEST_OF, weight=0.9, repository=repository,
        ),
    ])

    out_empty = await find_related(
        str(start),
        repo_ids=[str(repository.id)],
        relation_types=[],
        direction="downstream",
    )
    out_none = await find_related(
        str(start),
        repo_ids=[str(repository.id)],
        relation_types=None,
        direction="downstream",
    )
    assert {n.chunk_id for n in out_empty} == {n.chunk_id for n in out_none}
    assert len(out_empty) == 2  # 含 CALL + TEST_OF


# ---------------------------------------------------------------------------
# case 10：limit 截断输出
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_limit_truncates_output(repository) -> None:
    """limit=2 + 5 邻居 → 输出长度 == 2，按 weight desc。"""
    start = uuid.uuid4()
    targets = [uuid.uuid4() for _ in range(5)]

    await _create_registry(repository, start, "src/start.py")
    for cid in targets:
        await _create_registry(repository, cid, f"src/t_{cid.hex[:6]}.py")

    await ChunkEdge.objects.abulk_create([
        ChunkEdge(
            source_chunk_id=start, target_chunk_id=tgt,
            edge_type=EdgeType.CALL, weight=0.1 + i * 0.15,
            repository=repository,
        )
        for i, tgt in enumerate(targets)
    ])

    out = await find_related(
        str(start),
        repo_ids=[str(repository.id)],
        direction="downstream",
        limit=2,
    )
    assert len(out) == 2
    weights = [n.weight for n in out]
    assert weights == sorted(weights, reverse=True), "limit 截断应按 weight desc"


# ---------------------------------------------------------------------------
# case 11：repo_ids=[] 立即返回 [] 不查 ORM
# ---------------------------------------------------------------------------


async def test_empty_repo_ids_returns_empty_no_query() -> None:
    """repo_ids=[] → 立即 [] + 不触 ChunkEdge.objects.filter（fast-path 早返）。"""
    spy = patch.object(ChunkEdge.objects, "filter", wraps=ChunkEdge.objects.filter)
    with spy as mocked_filter:
        out = await find_related(
            str(uuid.uuid4()),
            repo_ids=[],
            direction="downstream",
        )
    assert out == []
    assert mocked_filter.call_count == 0, (
        f"empty repo_ids 应零 ORM 查询，实际 {mocked_filter.call_count}"
    )


# ---------------------------------------------------------------------------
# case 12：non-existent chunk_id 返回 [] 不抛错
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_non_existent_chunk_id_returns_empty(repository) -> None:
    """start_chunk_id 在 ChunkEdge 中无任何边 → [] 不抛错（graceful）。"""
    out = await find_related(
        str(uuid.uuid4()),
        repo_ids=[str(repository.id)],
        direction="both",
    )
    assert out == []


# ---------------------------------------------------------------------------
# case 13：reason 字段由 explain_neighbor 模板填充
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_reason_field_populated_via_explain_neighbor(repository) -> None:
    """NeighborMetadata.reason 含 explain_neighbor 模板关键词（CALL → 'direct call'）。"""
    start = uuid.uuid4()
    target = uuid.uuid4()

    await _create_registry(repository, start, "src/start.py")
    await _create_registry(repository, target, "src/target.py")

    await ChunkEdge.objects.acreate(
        source_chunk_id=start, target_chunk_id=target,
        edge_type=EdgeType.CALL, weight=0.85, repository=repository,
    )

    out = await find_related(
        str(start),
        repo_ids=[str(repository.id)],
        direction="downstream",
    )
    assert len(out) == 1
    nbr = out[0]
    assert nbr.reason
    assert "direct call" in nbr.reason
    assert "src/target.py" in nbr.reason  # target_file 模板替换


# ---------------------------------------------------------------------------
# case 14：HybridSearchService.find_related thin wrapper 暴露
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_hybrid_search_service_has_find_related_method(repository) -> None:
    """HybridSearchService.find_related 实例方法存在 + delegate 到 module-level 函数。

    implementation MCP tool 直接调用入口（success criteria："implementation MCP
    tool 仅需 thin wrapper：包 Pydantic schema + delegate 到 HybridSearchService.find_related"）。
    """
    assert hasattr(HybridSearchService, "find_related"), (
        "HybridSearchService 必须暴露 find_related 实例方法"
    )

    start = uuid.uuid4()
    target = uuid.uuid4()
    await _create_registry(repository, start, "src/start.py")
    await _create_registry(repository, target, "src/target.py")
    await ChunkEdge.objects.acreate(
        source_chunk_id=start, target_chunk_id=target,
        edge_type=EdgeType.CALL, weight=0.8, repository=repository,
    )

    svc = HybridSearchService(LocalProvider())
    out = await svc.find_related(
        str(start),
        repo_ids=[str(repository.id)],
        direction="downstream",
    )
    assert len(out) == 1
    assert out[0].chunk_id == str(target)
