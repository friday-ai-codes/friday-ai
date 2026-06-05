"""initial implementation plan — 增量索引 3 callsite `adelete_for_files` 孤儿清理测试。

覆盖 work item-02：

- 增量 3 callsite（branch overlay / git_diff / incremental）在调
  `_extract_and_write_graph` 之前先调 `GraphWriter.adelete_for_files`
  清理被删除文件的图谱孤儿数据（Symbol / ImportEdge / Endpoint 三件套）。
- 全量索引路径（`run_full_index`，CONTEXT 决议）**不加** delete hook，
  initial implementation-01 落 `build_graph_for_repository` 时再统一处理。
- `deleted_file_paths == []` 时短路（GraphWriter 内部已处理空列表）。

测试策略：以源码 regex 白盒断言为主——4 处 callsite 各自的"前后顺序"是结构性
不变量，整出 fixture 跑端到端会拉起 git/Qdrant/真实索引链路太重。少量端到端
集成 case 走"直接调 `adelete_for_files` + ORM 断言"模式（与 plan
`test_graph_writer_delete_for_files.py` 同款）。
"""

from __future__ import annotations

import inspect

import pytest
import structlog
from asgiref.sync import sync_to_async

from codegraph.models import Endpoint, ImportEdge, Symbol
from codegraph.services.graph_writer import GraphWriter
from repositories.models import Repository
from services.indexer import IndexerService

# ---------------------------------------------------------------------------
# 4 callsite 白盒结构断言（增量 3 处必须 hook + 全量 1 处不许 hook）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name",
    [
        "run_branch_index",
        "run_git_diff_index",
        "run_incremental_index",
    ],
)
def test_incremental_callsite_calls_adelete_for_files(method_name: str) -> None:
    """增量 3 callsite：必须在 `_extract_and_write_graph` 之前调
    `adelete_for_files`（白盒源码 regex 检查）。
    """
    method = getattr(IndexerService, method_name)
    src = inspect.getsource(method)

    extract_call_idx = src.find("await self._extract_and_write_graph(")
    assert extract_call_idx >= 0, (
        f"{method_name} 未调用 _extract_and_write_graph"
    )

    pre_segment = src[:extract_call_idx]
    assert "adelete_for_files" in pre_segment, (
        f"{method_name} 缺少 adelete_for_files hook —— "
        f"必须在 _extract_and_write_graph 之前调 GraphWriter.adelete_for_files "
        f"清理孤儿数据（work item-02）"
    )


def test_run_full_index_does_not_call_adelete_for_files() -> None:
    """全量索引 (run_full_index, line 874 callsite) **不许** hook
    adelete_for_files —— per CONTEXT 决议留给 initial implementation-01。
    """
    method = IndexerService.run_full_index
    src = inspect.getsource(method)
    assert "adelete_for_files" not in src, (
        "run_full_index 不应包含 adelete_for_files hook —— "
        "CONTEXT 决议：本 phase 仅 hook 增量 3 callsite，全量整仓清理留 initial implementation"
    )


def test_indexer_module_has_exactly_three_adelete_for_files_callsites() -> None:
    """indexer.py 整体只允许 3 处 `adelete_for_files` 调用（增量 3 callsite）。"""
    import services.indexer as indexer_module

    src = inspect.getsource(indexer_module)
    # 排除注释/文档串中可能出现的字面量，只数实际调用形态
    matches = [
        line for line in src.splitlines()
        if "adelete_for_files(" in line and not line.strip().startswith("#")
    ]
    assert len(matches) == 3, (
        f"adelete_for_files 调用预期 3 处，实际 {len(matches)} 处：\n"
        + "\n".join(matches)
    )


# ---------------------------------------------------------------------------
# 端到端：直接调 adelete_for_files 验证孤儿确实被删除（work item-02 success criterion）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_orphan_data_actually_removed_for_deleted_files(
    repository: Repository,
) -> None:
    """端到端：bulk_create Symbol(file=a.py / b.py) + 调 adelete_for_files(["a.py"])
    → `a.py` 行全删，`b.py` 行保留。
    """
    repo_id = str(repository.id)
    await sync_to_async(Symbol.objects.bulk_create)(
        [
            Symbol(
                repository_id=repo_id,
                file_path="a.py",
                name="foo_a",
                symbol_type=Symbol.SymbolType.FUNCTION,
                start_line=1,
                end_line=10,
            ),
            Symbol(
                repository_id=repo_id,
                file_path="b.py",
                name="foo_b",
                symbol_type=Symbol.SymbolType.FUNCTION,
                start_line=1,
                end_line=10,
            ),
        ]
    )

    writer = GraphWriter()
    deleted_count = await writer.adelete_for_files(repo_id, ["a.py"])

    assert deleted_count == 1
    assert (
        await sync_to_async(
            Symbol.objects.filter(repository_id=repo_id, file_path="a.py").exists
        )()
        is False
    )
    assert (
        await sync_to_async(
            Symbol.objects.filter(repository_id=repo_id, file_path="b.py").exists
        )()
        is True
    )


@pytest.mark.django_db(transaction=True)
async def test_empty_deleted_file_paths_short_circuits(
    repository: Repository,
) -> None:
    """`deleted_file_paths == []` → adelete_for_files 返回 0，不写 log。

    与 plan `test_empty_file_paths_short_circuit_returns_zero_without_transaction`
    呼应：indexer callsite 即便无脑调用，下游短路保护也能兜底。
    """
    writer = GraphWriter()
    with structlog.testing.capture_logs() as caps:
        n = await writer.adelete_for_files(str(repository.id), [])

    assert n == 0
    # GraphWriter 短路时不发 `graph_orphan_cleanup` 事件
    orphan_events = [c for c in caps if c.get("event") == "graph_orphan_cleanup"]
    assert orphan_events == []


@pytest.mark.django_db(transaction=True)
async def test_adelete_for_files_handles_multi_table(
    repository: Repository,
) -> None:
    """混合 Symbol / ImportEdge / Endpoint 三表，按 deleted_file_paths 一并清。"""
    repo_id = str(repository.id)

    await sync_to_async(Symbol.objects.bulk_create)(
        [
            Symbol(
                repository_id=repo_id,
                file_path="legacy.py",
                name="dead_fn",
                symbol_type=Symbol.SymbolType.FUNCTION,
                start_line=1,
                end_line=5,
            ),
        ]
    )
    await sync_to_async(ImportEdge.objects.bulk_create)(
        [
            ImportEdge(
                repository_id=repo_id,
                source_file="legacy.py",
                target_module="os",
            ),
        ]
    )
    await sync_to_async(Endpoint.objects.bulk_create)(
        [
            Endpoint(
                repository_id=repo_id,
                file_path="legacy.py",
                handler_name="legacy.handler",
                http_method="GET",
                url_path="/legacy",
                view_type=Endpoint.ViewType.FUNCTION_VIEW,
                line_number=1,
            ),
        ]
    )

    writer = GraphWriter()
    deleted = await writer.adelete_for_files(repo_id, ["legacy.py"])

    # Symbol + ImportEdge + Endpoint 三表各 1 行 → 总删 3
    assert deleted == 3
    assert (
        await sync_to_async(Symbol.objects.filter(repository_id=repo_id).count)() == 0
    )
    assert (
        await sync_to_async(ImportEdge.objects.filter(repository_id=repo_id).count)()
        == 0
    )
    assert (
        await sync_to_async(Endpoint.objects.filter(repository_id=repo_id).count)()
        == 0
    )


# ---------------------------------------------------------------------------
# 调用顺序断言：adelete_for_files 必须出现在 _extract_and_write_graph 之前
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name",
    [
        "run_branch_index",
        "run_git_diff_index",
        "run_incremental_index",
    ],
)
def test_adelete_for_files_called_before_extract_and_write_graph(
    method_name: str,
) -> None:
    """`adelete_for_files` 位置必须在 `_extract_and_write_graph` 之前（清孤儿
    在写新图谱前先发生，避免孤儿与新图谱混在一起的过渡态）。
    """
    method = getattr(IndexerService, method_name)
    src = inspect.getsource(method)

    extract_idx = src.find("await self._extract_and_write_graph(")
    adelete_idx = src.find("adelete_for_files(")

    assert adelete_idx >= 0, f"{method_name} 缺 adelete_for_files 调用"
    assert extract_idx >= 0
    assert adelete_idx < extract_idx, (
        f"{method_name}: adelete_for_files (offset={adelete_idx}) 必须在 "
        f"_extract_and_write_graph (offset={extract_idx}) 之前"
    )
