"""initial implementation plan：cleanup_index keep_graph 双路径单测。

覆盖（work item-01..03）：

1. ``test_default_keep_graph_false_clears_both``：默认调用清 6 张表 + Qdrant +
   ``CleanupReport.graph_artifacts_cleared is True``。
2. ``test_keep_graph_true_preserves_graph``：``keep_graph=True`` 时仅清向量轨
   （Qdrant / FileIndex / ChunkEdge / ChunkRegistry），保 Symbol / ImportEdge /
   Endpoint 三件套 + ``graph_artifacts_cleared is False``。
3. ``test_report_field_position``：``CleanupReport`` 末位字段必须为
   ``graph_artifacts_cleared``（@dataclass 字段顺序兼容，避免现有 ``asdict``
   调用方字段顺序漂移，per context contract / plan 关键约束）。
4. ``test_internal_helpers_exist``：拆分私有 helper ``_cleanup_vector_artifacts``
   / ``_cleanup_graph_artifacts`` 必须可从模块直接导入。
5. ``test_vector_artifacts_order``：mock ``_delete_count`` + ``_delete_chunk_registries_raw``
   + Qdrant，断言向量段调用顺序 Qdrant → FileIndex → ChunkEdge → ChunkRegistry
   （initial implementation contract 不变量：ChunkEdge 必须先于 ChunkRegistry）。
6. ``test_index_delete_view_keep_graph_query`` (security mitigation-3 端到端)：``DELETE
   /api/repositories/{id}/index/delete/?keep_graph=true`` Symbol 行不变；
   不带参数 Symbol 全清。
"""

from __future__ import annotations

import uuid
from dataclasses import fields
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from rest_framework.test import APIRequestFactory

from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from codegraph.models import Endpoint, ImportEdge, Symbol
from repositories.index_views import IndexDeleteView
from repositories.models import FileIndex, IndexStatus, Repository

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# 内部辅助 — 减少样板：批量造 6 张表数据
# ---------------------------------------------------------------------------


async def _seed_full_repo(repo: Repository) -> dict[str, int]:
    """在 repo 下造满 6 张表各 ≥ 1 行，返回各表种子计数 map。"""

    await FileIndex.objects.acreate(
        repository=repo, file_path="src/main.ts", file_hash="hash-main"
    )
    await Symbol.objects.acreate(
        repository=repo,
        name="main",
        symbol_type=Symbol.SymbolType.FUNCTION,
        file_path="src/main.ts",
        start_line=1,
        end_line=3,
    )
    await ImportEdge.objects.acreate(
        repository=repo,
        source_file="src/main.ts",
        target_module="vue",
        imported_names=["ref"],
    )
    await Endpoint.objects.acreate(
        repository=repo,
        http_method="GET",
        url_path="/api/demo/",
        handler_name="demo",
        view_type=Endpoint.ViewType.FUNCTION_VIEW,
        file_path="src/main.ts",
        line_number=1,
    )
    cr_a = await ChunkRegistry.objects.acreate(
        chunk_id=uuid.uuid4(),
        content_hash="hash-a",
        repository=repo,
        file_path="src/main.ts",
        chunk_index=0,
    )
    cr_b = await ChunkRegistry.objects.acreate(
        chunk_id=uuid.uuid4(),
        content_hash="hash-b",
        repository=repo,
        file_path="src/main.ts",
        chunk_index=1,
    )
    await ChunkEdge.objects.acreate(
        source_chunk_id=cr_a.chunk_id,
        target_chunk_id=cr_b.chunk_id,
        edge_type=EdgeType.SAME_FILE,
        weight=0.42,
        repository=repo,
    )
    return {
        "file_indexes": 1,
        "symbols": 1,
        "import_edges": 1,
        "endpoints": 1,
        "chunk_registries": 2,
        "chunk_edges": 1,
    }


async def _make_repo(name: str) -> Repository:
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://github.com/example/{name}.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
        last_indexed_commit_sha="a" * 40,
        remote_head_sha="a" * 40,
        remote_head_checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# 1. 默认 keep_graph=False → 双段都清 + report.graph_artifacts_cleared=True
# ---------------------------------------------------------------------------


async def test_default_keep_graph_false_clears_both() -> None:
    """默认调用 cleanup_index 应清空 6 张表 + Qdrant，且 graph_artifacts_cleared=True。"""

    from repositories.services.index_cleanup import CleanupReport, cleanup_index

    repo = await _make_repo("cleanup-default")
    seeds = await _seed_full_repo(repo)

    with patch(
        "repositories.services.index_cleanup.QdrantService.delete_collection",
        return_value=True,
    ):
        report = await cleanup_index(str(repo.id))

    assert isinstance(report, CleanupReport)
    assert report.qdrant_collection_deleted is True
    assert report.file_indexes_deleted == seeds["file_indexes"]
    assert report.symbols_deleted == seeds["symbols"]
    assert report.import_edges_deleted == seeds["import_edges"]
    assert report.endpoints_deleted == seeds["endpoints"]
    assert report.chunk_edges_deleted == seeds["chunk_edges"]
    assert report.chunk_registries_deleted == seeds["chunk_registries"]
    assert report.graph_artifacts_cleared is True

    # 6 张表全 0
    assert await FileIndex.objects.filter(repository=repo).acount() == 0
    assert await Symbol.objects.filter(repository=repo).acount() == 0
    assert await ImportEdge.objects.filter(repository=repo).acount() == 0
    assert await Endpoint.objects.filter(repository=repo).acount() == 0
    assert await ChunkEdge.objects.filter(repository=repo).acount() == 0
    assert await ChunkRegistry.objects.filter(repository=repo).acount() == 0


# ---------------------------------------------------------------------------
# 2. keep_graph=True → 仅清向量轨，图谱三件套保留 + graph_artifacts_cleared=False
# ---------------------------------------------------------------------------


async def test_keep_graph_true_preserves_graph() -> None:
    """keep_graph=True 时跳过 graph 段：Symbol/ImportEdge/Endpoint 行不变。"""

    from repositories.services.index_cleanup import cleanup_index

    repo = await _make_repo("cleanup-keep-graph")
    await _seed_full_repo(repo)

    with patch(
        "repositories.services.index_cleanup.QdrantService.delete_collection",
        return_value=True,
    ):
        report = await cleanup_index(str(repo.id), keep_graph=True)

    # 向量轨清空
    assert report.qdrant_collection_deleted is True
    assert report.file_indexes_deleted == 1
    assert report.chunk_edges_deleted == 1
    assert report.chunk_registries_deleted == 2
    assert await FileIndex.objects.filter(repository=repo).acount() == 0
    assert await ChunkEdge.objects.filter(repository=repo).acount() == 0
    assert await ChunkRegistry.objects.filter(repository=repo).acount() == 0

    # 图谱三件套保留 → 行数不变 + report 字段为 0
    assert report.symbols_deleted == 0
    assert report.import_edges_deleted == 0
    assert report.endpoints_deleted == 0
    assert report.graph_artifacts_cleared is False
    assert await Symbol.objects.filter(repository=repo).acount() == 1
    assert await ImportEdge.objects.filter(repository=repo).acount() == 1
    assert await Endpoint.objects.filter(repository=repo).acount() == 1


# ---------------------------------------------------------------------------
# 3. CleanupReport 字段位置兼容：graph_artifacts_cleared 必须末位
# ---------------------------------------------------------------------------


def test_report_field_position() -> None:
    """CleanupReport 末位字段必须为 graph_artifacts_cleared（@dataclass 顺序兼容）。"""

    from repositories.services.index_cleanup import CleanupReport

    field_names = [f.name for f in fields(CleanupReport)]
    assert field_names[-1] == "graph_artifacts_cleared", (
        "末位字段顺序漂移：CleanupReport 现状字段顺序 = "
        + ", ".join(field_names)
    )


# ---------------------------------------------------------------------------
# 4. 私有 helper 必须可导入
# ---------------------------------------------------------------------------


def test_internal_helpers_exist() -> None:
    """_cleanup_vector_artifacts / _cleanup_graph_artifacts 必须可从模块导入。"""

    from repositories.services.index_cleanup import (
        _cleanup_graph_artifacts,
        _cleanup_vector_artifacts,
    )

    assert callable(_cleanup_vector_artifacts)
    assert callable(_cleanup_graph_artifacts)


# ---------------------------------------------------------------------------
# 5. 向量段调用顺序：Qdrant → FileIndex → ChunkEdge → ChunkRegistry
# ---------------------------------------------------------------------------


async def test_vector_artifacts_order() -> None:
    """断言 _cleanup_vector_artifacts 内部子步骤调用顺序（initial implementation contract 不变量）。"""

    from repositories.services import index_cleanup
    from repositories.services.index_cleanup import _cleanup_vector_artifacts

    calls: list[str] = []

    async def _fake_qdrant(_repo_id: str) -> bool:
        calls.append("qdrant")
        return True

    async def _fake_delete_count(model: type, _repo_id: str, *, label: str) -> int:
        calls.append(label)
        return 0

    async def _fake_chunk_raw(_repo_id: str) -> int:
        calls.append("chunk_registries")
        return 0

    with (
        patch.object(
            index_cleanup, "_delete_qdrant_collection", _fake_qdrant
        ),
        patch.object(index_cleanup, "_delete_count", _fake_delete_count),
        patch.object(
            index_cleanup,
            "_delete_chunk_registries_raw",
            _fake_chunk_raw,
        ),
    ):
        await _cleanup_vector_artifacts("any-repo-id")

    assert calls == [
        "qdrant",
        "file_indexes",
        "chunk_edges",
        "chunk_registries",
    ], f"向量段调用顺序错误：{calls}"


# ---------------------------------------------------------------------------
# 6. 端到端：DELETE /api/repositories/{id}/index/delete/?keep_graph=true
#    （security mitigation-3 acceptance）
# ---------------------------------------------------------------------------


async def test_index_delete_view_keep_graph_query() -> None:
    """DELETE ?keep_graph=true 透传 cleanup_index(keep_graph=True)，Symbol 不变。"""

    repo_keep = await _make_repo("idv-keep")
    await _seed_full_repo(repo_keep)

    factory = APIRequestFactory()
    request = factory.delete(
        f"/api/repositories/{repo_keep.id}/index/delete/?keep_graph=true"
    )
    request.user = MagicMock()

    with patch(
        "repositories.services.index_cleanup.QdrantService.delete_collection",
        return_value=True,
    ):
        response = await IndexDeleteView().delete(request, repo_keep.id)

    assert response.status_code == 204
    # 图谱三件套保留
    assert await Symbol.objects.filter(repository=repo_keep).acount() == 1
    assert await ImportEdge.objects.filter(repository=repo_keep).acount() == 1
    assert await Endpoint.objects.filter(repository=repo_keep).acount() == 1
    # 向量轨清空
    assert await FileIndex.objects.filter(repository=repo_keep).acount() == 0
    assert await ChunkEdge.objects.filter(repository=repo_keep).acount() == 0
    assert await ChunkRegistry.objects.filter(repository=repo_keep).acount() == 0


async def test_index_delete_view_default_clears_graph() -> None:
    """DELETE 不带 keep_graph → 默认级联清图谱三件套（向后兼容）。"""

    repo_default = await _make_repo("idv-default")
    await _seed_full_repo(repo_default)

    factory = APIRequestFactory()
    request = factory.delete(f"/api/repositories/{repo_default.id}/index/delete/")
    request.user = MagicMock()

    with patch(
        "repositories.services.index_cleanup.QdrantService.delete_collection",
        return_value=True,
    ):
        response = await IndexDeleteView().delete(request, repo_default.id)

    assert response.status_code == 204
    assert await Symbol.objects.filter(repository=repo_default).acount() == 0
    assert await ImportEdge.objects.filter(repository=repo_default).acount() == 0
    assert await Endpoint.objects.filter(repository=repo_default).acount() == 0
