"""initial implementation（contract）：EdgeBuilder 分支隔离回归测试。

覆盖三条验收红线：

1. test_dual_write_no_integrity_error
   base ChunkEdge（branch_name=""）+ feature ChunkEdge（同 source/target/
   edge_type，branch_name="feat-x"）经 bulk_insert_edges 双写，**不抛
   IntegrityError** 且两行并存（依赖 293 改后的 (source,target,edge_type,
   branch_name) unique + bulk_insert_edges 的 ignore_conflicts）。
2. test_feature_edge_branch_name
   feature 路径（branch_name="feat-x"）构建的 ChunkEdge.branch_name=="feat-x"，
   且只读 feature ChunkRegistry 行（base 行被 branch 过滤排除）。
3. test_enqueue_threads_branch
   enqueue_edge_build_for_history → EdgeBuilder.build 链透传 branch_name
   （mock builder.build 捕获 kwarg）。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import patch

import pytest

from code_relations import tasks as tasks_module
from code_relations.builders.base import BaseEdgeBuilder
from code_relations.builders.same_file_edge import SameFileEdgeBuilder
from code_relations.lifecycle import enqueue_edge_build_for_history
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from code_relations.storage import bulk_insert_edges
from repositories.models import (
    GraphBuildStatus,
    IndexHistory,
    IndexHistoryStatus,
    TriggerType,
)

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_chunk(
    repository: Any, *, index: int, file_path: str, branch_name: str = ""
) -> ChunkRegistry:
    return await ChunkRegistry.objects.acreate(
        chunk_id=uuid.uuid4(),
        content_hash="0" * 64,
        repository=repository,
        branch_name=branch_name,
        file_path=file_path,
        chunk_index=index,
    )


async def _drain_background_tasks() -> None:
    """循环 drain `_BACKGROUND_TASKS` 直到为空（与 lifecycle 测试同款）。"""
    for _ in range(50):
        pending = list(tasks_module._BACKGROUND_TASKS)
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.sleep(0)


async def test_dual_write_no_integrity_error(repository) -> None:
    """contract：base + feature 双写同三元组不抛 IntegrityError，两行并存。"""
    source = uuid.uuid4()
    target = uuid.uuid4()

    base_edge = ChunkEdge(
        source_chunk_id=source,
        target_chunk_id=target,
        edge_type=EdgeType.CALL,
        branch_name="",
        weight=0.5,
        metadata={},
        repository=repository,
    )
    feature_edge = ChunkEdge(
        source_chunk_id=source,
        target_chunk_id=target,
        edge_type=EdgeType.CALL,
        branch_name="feat-x",
        weight=0.5,
        metadata={},
        repository=repository,
    )

    # 双写不应抛 IntegrityError（unique 含 branch_name + ignore_conflicts）。
    await bulk_insert_edges([base_edge, feature_edge])

    total = await ChunkEdge.objects.filter(repository=repository).acount()
    assert total == 2, "base 与 feature 边应并存（branch_name 进 unique 区分）"

    base_count = await ChunkEdge.objects.filter(
        repository=repository, branch_name=""
    ).acount()
    feature_count = await ChunkEdge.objects.filter(
        repository=repository, branch_name="feat-x"
    ).acount()
    assert base_count == 1
    assert feature_count == 1

    # 再次写入同 base 三元组：ignore_conflicts 静默去重，仍只 1 行 base。
    dup_base = ChunkEdge(
        source_chunk_id=source,
        target_chunk_id=target,
        edge_type=EdgeType.CALL,
        branch_name="",
        weight=0.9,
        metadata={},
        repository=repository,
    )
    await bulk_insert_edges([dup_base])
    assert (
        await ChunkEdge.objects.filter(
            repository=repository, branch_name=""
        ).acount()
        == 1
    )


async def test_feature_edge_branch_name(repository) -> None:
    """contract：feature 路径构建的 ChunkEdge.branch_name 正确且只读本分支行。"""
    file_path = "src/module.py"

    # base 行（branch_name=""）：feature build 不应读到它们。
    await _make_chunk(repository, index=0, file_path=file_path, branch_name="")
    await _make_chunk(repository, index=1, file_path=file_path, branch_name="")

    # feature 行（branch_name="feat-x"）：feature build 应据此建 SAME_FILE 边。
    await _make_chunk(
        repository, index=0, file_path=file_path, branch_name="feat-x"
    )
    await _make_chunk(
        repository, index=1, file_path=file_path, branch_name="feat-x"
    )

    builder = SameFileEdgeBuilder()
    edges = await builder.build(repository, [], branch_name="feat-x")

    assert edges, "feature ChunkRegistry 行应建出至少一条 SAME_FILE 边"
    assert all(e.branch_name == "feat-x" for e in edges), (
        "feature 路径构建的边 branch_name 必须为 feat-x"
    )

    # base build（branch_name=""）应只读 base 行，与 feature 互不干扰。
    base_edges = await builder.build(repository, [], branch_name="")
    assert base_edges
    assert all(e.branch_name == "" for e in base_edges)


async def test_enqueue_threads_branch(repository) -> None:
    """contract：enqueue_edge_build_for_history → build 链透传 branch_name。"""
    history = await IndexHistory.objects.acreate(
        repository=repository,
        trigger_type=TriggerType.MANUAL,
        status=IndexHistoryStatus.RUNNING,
        graph_build_status=GraphBuildStatus.PENDING,
    )
    dirty = [uuid.uuid4()]
    captured: dict[str, str] = {}

    class _SpyBuilder(BaseEdgeBuilder):
        edge_type_label = "SpyBuilder"

        async def build(
            self,
            repository: Any,
            dirty_chunk_ids: list[uuid.UUID],
            *,
            branch_name: str = "",
        ) -> list[ChunkEdge]:
            captured["branch_name"] = branch_name
            return []

    async def _noop_payload(*args: Any, **kwargs: Any) -> None:
        return None

    with patch.object(tasks_module, "BUILDERS", [_SpyBuilder]):
        with patch(
            "services.qdrant_service.QdrantService.batch_set_payload",
            side_effect=_noop_payload,
        ):
            await enqueue_edge_build_for_history(
                str(repository.id), dirty, history.id, branch_name="feat-x"
            )
            await _drain_background_tasks()

    assert captured.get("branch_name") == "feat-x", (
        "EdgeBuilder.build 应收到透传的 branch_name=feat-x"
    )
