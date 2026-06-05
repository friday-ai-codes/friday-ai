"""hop1_reader —— implementation 编排器一跳 payload 直读测试（contract）。

覆盖矩阵（14 条）：

Task 1（纯 payload 解析，无 ORM）：
1. 正常 5 items × 5 邻居 → 5 keys × ≤10 邻居（按 weight desc）
2. payload 缺失 'related_chunks' → 该 source 跳过 + warning
3. related_chunks=[] → source 不入 dict（无 warning）
4. related_chunks=None → 跳过 + warning
5. 邻居元素是 dict（错误类型）→ 跳过整个 source + warning
6. 邻居元素是 [str, str, float] 但少字段 → 跳过整个 source + warning
7. 单 source 25 邻居 → 输出截断到 TOP_NEIGHBORS_PER_HOP1=10
8. weight 乱序输入 → 输出按 weight desc
9. 重复 target chunk_id 在 source 内 → 防御性 dict.setdefault 保留先到

Task 2（async + ChunkRegistry.in_bulk metadata 解析）：
10. 正常 in_bulk 路径，metadata 完整
11. ChunkRegistry 缺 1 个 chunk → "<unknown>" + line_*=None + log debug
12. line_start=NULL 历史数据 → NeighborMetadata.line_start = None graceful
13. 多 source 指向同 target chunk_id → 合并保 max(weight)
14. reason_fn 注入自定义函数 → reason 字段使用注入结果
15. in_bulk 调用次数 == 1（mock 计数器断言，无 N+1）
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
import structlog

from code_relations.constants import TOP_NEIGHBORS_PER_HOP1
from code_relations.models import ChunkRegistry
from services.retrieval.hop1_reader import (
    extract_hop1_neighbors_raw,
    resolve_neighbor_metadata,
)
from services.retrieval.types import NeighborMetadata

# ---------------------------------------------------------------------------
# structlog 捕获助手（与 test_hybrid_budget.py 同模式）
# ---------------------------------------------------------------------------


def _capture_structlog_events() -> tuple[list[dict[str, Any]], object]:
    events: list[dict[str, Any]] = []

    def _capture(logger, method_name, event_dict):  # type: ignore[no-untyped-def]
        events.append(dict(event_dict))
        raise structlog.DropEvent

    old = structlog.get_config()
    structlog.configure(
        processors=[_capture],
        wrapper_class=old["wrapper_class"],
        logger_factory=old["logger_factory"],
        cache_logger_on_first_use=False,
    )

    def _restore() -> None:
        structlog.configure(**old)

    return events, _restore


def _make_item(chunk_id: str, neighbors: Any) -> dict[str, Any]:
    """构造 rag_search items[i] minimum shape。"""
    return {
        "id": chunk_id,
        "score": 0.5,
        "payload": {
            "file_path": "src/foo.py",
            "chunk_index": 0,
            "content": "def foo(): ...",
            "related_chunks": neighbors,
        },
        "repository_id": "11111111-1111-1111-1111-111111111111",
    }


# ---------------------------------------------------------------------------
# Task 1：extract_hop1_neighbors_raw 纯函数解析
# ---------------------------------------------------------------------------


def test_extract_hop1_neighbors_raw_normal_5x5() -> None:
    """5 sources × 5 邻居 → 5 keys × 5 (str, str, float) 三元组。"""
    items = []
    for i in range(5):
        src = f"00000000-0000-0000-0000-00000000000{i}"
        neighbors = [
            [f"target-{i}-{j}", "CALL", 0.9 - j * 0.1] for j in range(5)
        ]
        items.append(_make_item(src, neighbors))

    out = extract_hop1_neighbors_raw(items)
    assert len(out) == 5
    for i, src in enumerate(item["id"] for item in items):
        assert src in out
        assert len(out[src]) == 5
        for tup in out[src]:
            assert isinstance(tup, tuple)
            assert len(tup) == 3
            assert isinstance(tup[0], str)
            assert isinstance(tup[1], str)
            assert isinstance(tup[2], float)


def test_extract_skips_when_related_chunks_key_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """payload 不含 'related_chunks' key → warning + 该 source 不入 dict。"""
    item = {
        "id": "src-1",
        "score": 0.5,
        "payload": {"file_path": "a.py", "chunk_index": 0, "content": ""},
        "repository_id": "r",
    }
    out = extract_hop1_neighbors_raw([item])

    assert "src-1" not in out
    captured = capsys.readouterr().out
    assert "hop1_payload_malformed" in captured
    assert "src-1" in captured


def test_extract_skips_when_related_chunks_empty_list(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """related_chunks=[] → 静默跳过（不入 dict，无 warning）。"""
    item = _make_item("src-empty", [])
    out = extract_hop1_neighbors_raw([item])

    assert "src-empty" not in out
    captured = capsys.readouterr().out
    assert "hop1_payload_malformed" not in captured


def test_extract_warns_when_related_chunks_is_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """related_chunks=None → warning + 跳过。"""
    item = _make_item("src-none", None)
    out = extract_hop1_neighbors_raw([item])

    assert "src-none" not in out
    captured = capsys.readouterr().out
    assert "hop1_payload_malformed" in captured
    assert "src-none" in captured


def test_extract_skips_source_when_neighbor_is_dict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """邻居元素是 dict（错误类型）→ 整个 source 跳过 + warning。"""
    item = _make_item(
        "src-dict",
        [{"chunk_id": "x", "edge_type": "CALL", "weight": 0.5}],
    )
    out = extract_hop1_neighbors_raw([item])

    assert "src-dict" not in out
    captured = capsys.readouterr().out
    assert "hop1_payload_malformed" in captured


def test_extract_skips_source_when_weight_is_nan_or_inf() -> None:
    """work item: weight 为 NaN / ±Inf / [0,1] 越界 → _is_valid_neighbor_tuple 拒绝整个 source。

    NaN 进 sorted() 不可排序 + budget 估算异常；Inf 进 markdown 渲染会污染
    LLM 上下文（``w=inf``）。与 ChunkEdge.weight DB 约束 [0.0, 1.0] 对齐。
    """
    events, restore = _capture_structlog_events()
    try:
        for bad_weight in (float("nan"), float("inf"), float("-inf"), -0.1, 1.5):
            item = _make_item(
                f"src-bad-{bad_weight}",
                [["target-1", "CALL", bad_weight]],
            )
            out = extract_hop1_neighbors_raw([item])
            assert f"src-bad-{bad_weight}" not in out, (
                f"weight={bad_weight!r} 应被 _is_valid_neighbor_tuple 拒绝"
            )
    finally:
        restore()  # type: ignore[operator]
    _ = events  # 不强校验 warning 内容，仅校验 dict 不入


def test_extract_skips_source_when_tuple_short(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """邻居元素少字段（[chunk_id, edge_type]，缺 weight）→ 跳过 source + warning。"""
    item = _make_item("src-short", [["target-1", "CALL"]])
    out = extract_hop1_neighbors_raw([item])

    assert "src-short" not in out
    captured = capsys.readouterr().out
    assert "hop1_payload_malformed" in captured


def test_extract_truncates_to_top10() -> None:
    """单 source 25 邻居 → 输出截断到 TOP_NEIGHBORS_PER_HOP1=10（按 weight desc）。"""
    neighbors = [[f"t-{i}", "CALL", i * 0.04] for i in range(25)]
    item = _make_item("src-25", neighbors)

    out = extract_hop1_neighbors_raw([item])
    assert "src-25" in out
    assert len(out["src-25"]) == TOP_NEIGHBORS_PER_HOP1 == 10
    weights = [w for _, _, w in out["src-25"]]
    assert weights == sorted(weights, reverse=True)
    assert weights[0] == pytest.approx(24 * 0.04)
    assert weights[-1] == pytest.approx(15 * 0.04)


def test_extract_sorts_by_weight_desc() -> None:
    """weight 乱序输入 → 输出按 weight desc。"""
    neighbors = [
        ["a", "CALL", 0.1],
        ["b", "CALL", 0.9],
        ["c", "CALL", 0.5],
    ]
    item = _make_item("src-mix", neighbors)
    out = extract_hop1_neighbors_raw([item])
    weights = [w for _, _, w in out["src-mix"]]
    assert weights == [0.9, 0.5, 0.1]


def test_extract_dedups_duplicate_target_within_source() -> None:
    """单 source 内重复 target chunk_id → 防御性 dict.setdefault 保留先到。"""
    neighbors = [
        ["dup-target", "CALL", 0.9],
        ["dup-target", "IMPORT", 0.5],
        ["other", "CALL", 0.7],
    ]
    item = _make_item("src-dup", neighbors)
    out = extract_hop1_neighbors_raw([item])
    targets = [t for t, _, _ in out["src-dup"]]
    edge_types = {t: et for t, et, _ in out["src-dup"]}
    assert targets.count("dup-target") == 1
    assert edge_types["dup-target"] == "CALL"  # 先到
    assert "other" in targets


# ---------------------------------------------------------------------------
# Task 2：resolve_neighbor_metadata async + ChunkRegistry.in_bulk
# ---------------------------------------------------------------------------


def _default_reason(
    edge_type: str,
    source_file: str | None,
    target_file: str | None,
    metadata: dict,
) -> str:
    """work item 后 ReasonFn 新签名 ``(edge_type, source_file, target_file, metadata)``。

    用 target_file 当 descriptor，因为本文件 fixtures 仅注册 target chunk_id
    （source 用 ``"source-1"`` / ``"src-x"`` 等占位字符串非 UUID）。
    """
    descriptor = target_file if target_file else "<missing>"
    return f"{edge_type} from {descriptor}"


@pytest.mark.django_db(transaction=True)
async def test_resolve_metadata_full_lookup(repository) -> None:
    """正常路径：所有 chunk_id 在 ChunkRegistry 中找到，metadata 完整。"""
    cid_a = uuid.uuid4()
    cid_b = uuid.uuid4()
    await ChunkRegistry.objects.acreate(
        chunk_id=cid_a,
        content_hash="a" * 64,
        repository=repository,
        file_path="src/a.py",
        chunk_index=0,
        line_start=10,
        line_end=20,
    )
    await ChunkRegistry.objects.acreate(
        chunk_id=cid_b,
        content_hash="b" * 64,
        repository=repository,
        file_path="src/b.py",
        chunk_index=1,
        line_start=30,
        line_end=40,
    )

    neighbor_tuples: dict[str, list[tuple[str, str, float]]] = {
        "source-1": [(str(cid_a), "CALL", 0.9), (str(cid_b), "IMPORT", 0.7)],
    }
    out = await resolve_neighbor_metadata(
        neighbor_tuples, hop=1, reason_fn=_default_reason
    )
    assert len(out) == 2
    by_chunk = {n.chunk_id: n for n in out}
    assert by_chunk[str(cid_a)].file_path == "src/a.py"
    assert by_chunk[str(cid_a)].line_start == 10
    assert by_chunk[str(cid_a)].line_end == 20
    assert by_chunk[str(cid_a)].edge_type == "CALL"
    assert by_chunk[str(cid_a)].weight == pytest.approx(0.9)
    assert by_chunk[str(cid_a)].hop == 1
    assert by_chunk[str(cid_a)].reason == "CALL from src/a.py"
    assert by_chunk[str(cid_b)].file_path == "src/b.py"


@pytest.mark.django_db(transaction=True)
async def test_resolve_metadata_missing_chunk_uses_unknown_fallback(repository) -> None:
    """ChunkRegistry 中缺一个 chunk_id → file_path='<unknown>' + line_*=None + debug log。"""
    cid_present = uuid.uuid4()
    cid_missing = uuid.uuid4()
    await ChunkRegistry.objects.acreate(
        chunk_id=cid_present,
        content_hash="c" * 64,
        repository=repository,
        file_path="src/present.py",
        chunk_index=0,
        line_start=1,
        line_end=5,
    )

    neighbor_tuples = {
        "src-x": [(str(cid_present), "CALL", 0.9), (str(cid_missing), "CALL", 0.5)],
    }
    events, restore = _capture_structlog_events()
    try:
        out = await resolve_neighbor_metadata(
            neighbor_tuples, hop=1, reason_fn=_default_reason
        )
    finally:
        restore()  # type: ignore[operator]

    by_chunk = {n.chunk_id: n for n in out}
    assert by_chunk[str(cid_missing)].file_path == "<unknown>"
    assert by_chunk[str(cid_missing)].line_start is None
    assert by_chunk[str(cid_missing)].line_end is None
    miss_events = [e for e in events if e.get("event") == "hop1_chunk_registry_miss"]
    assert miss_events, f"expected miss debug event, got {events}"


@pytest.mark.django_db(transaction=True)
async def test_resolve_metadata_null_line_fields_graceful(repository) -> None:
    """ChunkRegistry.line_start=NULL 历史数据 → NeighborMetadata.line_start=None。"""
    cid = uuid.uuid4()
    await ChunkRegistry.objects.acreate(
        chunk_id=cid,
        content_hash="d" * 64,
        repository=repository,
        file_path="src/legacy.py",
        chunk_index=0,
        line_start=None,
        line_end=None,
    )

    neighbor_tuples = {"src-y": [(str(cid), "SAME_FILE", 0.4)]}
    out = await resolve_neighbor_metadata(
        neighbor_tuples, hop=1, reason_fn=_default_reason
    )
    assert len(out) == 1
    assert out[0].file_path == "src/legacy.py"
    assert out[0].line_start is None
    assert out[0].line_end is None


@pytest.mark.django_db(transaction=True)
async def test_resolve_metadata_merges_max_weight_across_sources(repository) -> None:
    """多 source 指向同 target chunk_id 同 edge_type → 合并保 max(weight)。"""
    cid = uuid.uuid4()
    await ChunkRegistry.objects.acreate(
        chunk_id=cid,
        content_hash="e" * 64,
        repository=repository,
        file_path="src/shared.py",
        chunk_index=0,
        line_start=1,
        line_end=10,
    )

    neighbor_tuples = {
        "src-A": [(str(cid), "CALL", 0.3)],
        "src-B": [(str(cid), "CALL", 0.8)],
        "src-C": [(str(cid), "CALL", 0.5)],
    }
    out = await resolve_neighbor_metadata(
        neighbor_tuples, hop=1, reason_fn=_default_reason
    )
    same = [n for n in out if n.chunk_id == str(cid) and n.edge_type == "CALL"]
    assert len(same) == 1
    assert same[0].weight == pytest.approx(0.8)


@pytest.mark.django_db(transaction=True)
async def test_resolve_metadata_uses_injected_reason_fn(repository) -> None:
    """reason_fn 注入自定义函数 → reason 字段使用注入结果。"""
    cid = uuid.uuid4()
    await ChunkRegistry.objects.acreate(
        chunk_id=cid,
        content_hash="f" * 64,
        repository=repository,
        file_path="src/r.py",
        chunk_index=0,
        line_start=1,
        line_end=2,
    )

    def custom_reason(
        edge_type: str,
        source_file: str | None,
        target_file: str | None,
        metadata: dict,
    ) -> str:
        return f"custom::{edge_type}::{target_file}"

    neighbor_tuples = {"my-src": [(str(cid), "TEST_OF", 0.4)]}
    out = await resolve_neighbor_metadata(
        neighbor_tuples, hop=2, reason_fn=custom_reason
    )
    assert len(out) == 1
    assert out[0].reason == "custom::TEST_OF::src/r.py"
    assert out[0].hop == 2


@pytest.mark.django_db(transaction=True)
async def test_resolve_metadata_calls_in_bulk_exactly_once(repository) -> None:
    """无 N+1 守护：ChunkRegistry.objects.in_bulk 必须仅被调用 1 次。"""
    cids = [uuid.uuid4() for _ in range(5)]
    for i, cid in enumerate(cids):
        await ChunkRegistry.objects.acreate(
            chunk_id=cid,
            content_hash=f"{i:064x}",
            repository=repository,
            file_path=f"src/n{i}.py",
            chunk_index=i,
            line_start=i * 10,
            line_end=i * 10 + 5,
        )

    neighbor_tuples = {
        f"source-{i}": [(str(cid), "CALL", 0.5)] for i, cid in enumerate(cids)
    }

    real_in_bulk = ChunkRegistry.objects.in_bulk
    with patch.object(
        ChunkRegistry.objects,
        "in_bulk",
        side_effect=real_in_bulk,
    ) as spy:
        out = await resolve_neighbor_metadata(
            neighbor_tuples, hop=1, reason_fn=_default_reason
        )

    assert spy.call_count == 1, f"expected exactly 1 in_bulk call, got {spy.call_count}"
    assert len(out) == 5


def test_neighbor_metadata_dataclass_shape() -> None:
    """NeighborMetadata 字段类型 sanity check（与 plan types.py 严格对齐）。"""
    n = NeighborMetadata(
        chunk_id="x",
        file_path="src/x.py",
        line_start=None,
        line_end=None,
        edge_type="CALL",
        weight=0.5,
        reason="r",
        hop=1,
    )
    assert n.chunk_id == "x"
    assert n.line_start is None
