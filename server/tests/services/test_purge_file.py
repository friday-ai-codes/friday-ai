"""``purge_file`` 统一删除入口守护测试（Phase 23 Plan 01，PF-03 + PF-05）。

覆盖「删后五面无残留」：
- Qdrant 主 collection（``delete_by_file_path``）+ 每个 overlay collection
  （``delete_by_payload_field``，PF-05）被以正确 ``(collection, field, value)`` 调用。
- ``FileIndex`` 行删空。
- ``ChunkRegistry`` 行删空，且经既有 ``pre_delete`` 信号联动清掉指向被删 chunk 的
  ``ChunkEdge``（PF-03）。
- codegraph（Symbol / ImportEdge / Endpoint / CallEdge）在 base + feature 分支均删空。
- 幂等：对同一文件二次 ``purge_file`` 不抛异常、计数归 0。
- 从未索引的文件调用不抛异常。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db(transaction=True)

PATH = "src/leak.py"
OTHER = "src/keeps.py"
FEATURE = "feat-x"


def _seed_chunk(repository: Any, *, file_path: str, branch_name: str = "", index: int = 0) -> Any:
    from code_relations.models import ChunkRegistry

    return ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="0" * 64,
        repository=repository,
        branch_name=branch_name,
        file_path=file_path,
        chunk_index=index,
    )


def _seed_edge(repository: Any, *, source: uuid.UUID, target: uuid.UUID) -> Any:
    from code_relations.models import ChunkEdge, EdgeType

    return ChunkEdge.objects.create(
        source_chunk_id=source,
        target_chunk_id=target,
        edge_type=EdgeType.CALL,
        weight=0.7,
        metadata={},
        repository=repository,
    )


def _seed_codegraph(repository: Any, *, file_path: str, branch_name: str = "") -> None:
    from codegraph.models import CallEdge, Endpoint, ImportEdge, Symbol

    Symbol.objects.create(
        repository=repository,
        branch_name=branch_name,
        name="foo",
        symbol_type=Symbol.SymbolType.FUNCTION,
        file_path=file_path,
        start_line=1,
        end_line=5,
    )
    ImportEdge.objects.create(
        repository=repository,
        branch_name=branch_name,
        source_file=file_path,
        target_module="os",
        imported_names=["path"],
    )
    Endpoint.objects.create(
        repository=repository,
        branch_name=branch_name,
        http_method="GET",
        url_path="/x",
        handler_name="foo",
        view_type=Endpoint.ViewType.FUNCTION_VIEW,
        file_path=file_path,
        line_number=1,
    )
    CallEdge.objects.create(
        repository=repository,
        branch_name=branch_name,
        caller_file=file_path,
        callee_name="bar",
        call_type=CallEdge.CallType.DIRECT,
        line_number=2,
    )


def _seed_branch_index(
    repository: Any, *, branch_name: str, is_base: bool, collection_name: str | None
) -> None:
    from repositories.models import RepositoryBranchIndex

    RepositoryBranchIndex.objects.create(
        repository=repository,
        branch_name=branch_name,
        is_base_branch=is_base,
        collection_name=collection_name,
    )


class _QdrantSpy:
    """同步 stub：捕获主/overlay 删除调用，返回成功。"""

    def __init__(self) -> None:
        self.main_calls: list[tuple[str, str]] = []
        self.field_calls: list[tuple[str, str, str]] = []

    def delete_by_file_path(self, repository_id: str, file_path: str) -> bool:
        self.main_calls.append((repository_id, file_path))
        return True

    def delete_by_payload_field(self, collection_name: str, field: str, value: str) -> bool:
        self.field_calls.append((collection_name, field, value))
        return True


def _codegraph_rows(repository_id: str, file_path: str) -> int:
    from codegraph.models import CallEdge, Endpoint, ImportEdge, Symbol

    return (
        Symbol.objects.filter(repository_id=repository_id, file_path=file_path).count()
        + ImportEdge.objects.filter(repository_id=repository_id, source_file=file_path).count()
        + Endpoint.objects.filter(repository_id=repository_id, file_path=file_path).count()
        + CallEdge.objects.filter(repository_id=repository_id, caller_file=file_path).count()
    )


@pytest.fixture(autouse=True)
def _no_background_reconcile():
    """阻断 pre_delete 信号的后台 reconcile 投递，避免单测触发真实 Qdrant 调用。

    边清理（同步）仍照常发生；仅 mock 掉 ``run_in_background`` 调度。
    """
    with patch("code_relations.signals.run_in_background", return_value=None):
        yield


async def test_purge_file_clears_all_five_planes(repository: Any) -> None:
    """有 base+overlay / FileIndex / ChunkRegistry(+edge) / codegraph 的文件删后五面皆空。"""
    from asgiref.sync import sync_to_async

    from code_relations.models import ChunkEdge, ChunkRegistry
    from repositories.models import FileIndex
    from services.purge import PurgeResult, purge_file

    # 分支索引：base（无 overlay collection）+ feature（有 overlay collection）
    await sync_to_async(_seed_branch_index)(
        repository, branch_name="main", is_base=True, collection_name=None
    )
    await sync_to_async(_seed_branch_index)(
        repository, branch_name=FEATURE, is_base=False, collection_name="overlay_feat"
    )

    # FileIndex
    await sync_to_async(FileIndex.objects.create)(
        repository=repository, file_path=PATH, file_hash="h"
    )

    # ChunkRegistry：base + feature 两条都在 PATH；另有 OTHER 上一条作为指向 PATH 的边的源
    target = await sync_to_async(_seed_chunk)(repository, file_path=PATH, branch_name="")
    await sync_to_async(_seed_chunk)(repository, file_path=PATH, branch_name=FEATURE, index=1)
    source = await sync_to_async(_seed_chunk)(repository, file_path=OTHER, index=2)
    await sync_to_async(_seed_edge)(repository, source=source.chunk_id, target=target.chunk_id)

    # codegraph：base + feature
    await sync_to_async(_seed_codegraph)(repository, file_path=PATH, branch_name="")
    await sync_to_async(_seed_codegraph)(repository, file_path=PATH, branch_name=FEATURE)

    spy = _QdrantSpy()
    with patch("services.purge.QdrantService", spy):
        result = await purge_file(str(repository.id), PATH)

    assert isinstance(result, PurgeResult)
    assert not result.failures, f"不应有删除失败：{result.failures}"

    # Qdrant 主 + overlay 调用正确
    assert spy.main_calls == [(str(repository.id), PATH)]
    assert spy.field_calls == [("overlay_feat", "file_path", PATH)]
    assert result.qdrant_overlays == 1

    # FileIndex / ChunkRegistry / ChunkEdge 无残留
    assert await FileIndex.objects.filter(repository_id=repository.id, file_path=PATH).acount() == 0
    assert (
        await ChunkRegistry.objects.filter(repository_id=repository.id, file_path=PATH).acount()
        == 0
    )
    assert await ChunkEdge.objects.filter(target_chunk_id=target.chunk_id).acount() == 0, (
        "pre_delete 信号应清掉指向被删 chunk 的 ChunkEdge"
    )
    # OTHER 上的源 chunk 不应被误删（repository_id 作用域）
    assert (
        await ChunkRegistry.objects.filter(repository_id=repository.id, file_path=OTHER).acount()
        == 1
    )

    # codegraph base + feature 均无残留
    assert await sync_to_async(_codegraph_rows)(str(repository.id), PATH) == 0


async def test_purge_file_idempotent_second_call(repository: Any) -> None:
    """二次 purge 同一文件不抛异常，计数全 0。"""
    from asgiref.sync import sync_to_async

    from repositories.models import FileIndex
    from services.purge import purge_file

    await sync_to_async(FileIndex.objects.create)(
        repository=repository, file_path=PATH, file_hash="h"
    )

    spy = _QdrantSpy()
    with patch("services.purge.QdrantService", spy):
        first = await purge_file(str(repository.id), PATH)
        second = await purge_file(str(repository.id), PATH)

    assert first.file_index_deleted == 1
    assert second.file_index_deleted == 0
    assert second.chunk_registry_deleted == 0
    assert second.codegraph_deleted == 0
    assert not second.failures


async def test_purge_file_never_indexed_no_error(repository: Any) -> None:
    """从未索引的文件调用不抛异常，计数全 0。"""
    from services.purge import purge_file

    spy = _QdrantSpy()
    with patch("services.purge.QdrantService", spy):
        result = await purge_file(str(repository.id), "never/seen.py")

    assert result.file_index_deleted == 0
    assert result.chunk_registry_deleted == 0
    assert result.codegraph_deleted == 0
    assert not result.failures


async def test_incremental_delete_path_converges_on_purge_file(
    repository: Any, tmp_path: Any
) -> None:
    """run_incremental_index 的 DELETE 分支收敛到 purge_file（PF-03 收口）。

    预置一条本地已不存在的 FileIndex（即「被删文件」），跑增量索引，断言其 DELETE
    分支恰以 ``(repository_id, file_path)`` 调一次 ``purge_file``。
    """
    from unittest.mock import AsyncMock

    from asgiref.sync import sync_to_async

    from repositories.models import FileIndex
    from services import indexer as ix
    from services.exclusion import invalidate_matcher_cache
    from services.indexer import IndexerService
    from services.purge import PurgeResult

    await sync_to_async(FileIndex.objects.create)(
        repository=repository, file_path="gone.py", file_hash="old"
    )
    invalidate_matcher_cache(str(repository.id))

    indexer = IndexerService(str(repository.id))

    async def _noop(self: object, *a: object, **kw: object) -> None:
        return None

    mock_purge = AsyncMock(return_value=PurgeResult())
    with (
        patch.object(ix.IndexerService, "_ensure_collection", _noop),
        patch.object(ix, "purge_file", new=mock_purge),
    ):
        result = await indexer.run_incremental_index(str(tmp_path))

    assert result["status"] == "success"
    assert result["deleted"] == 1
    mock_purge.assert_awaited_once_with(str(repository.id), "gone.py")
