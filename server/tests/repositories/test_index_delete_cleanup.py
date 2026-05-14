"""删除索引时清理所有会影响重建的本地索引状态。"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
from rest_framework.test import APIRequestFactory
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from codegraph.models import Endpoint, ImportEdge, Symbol
from repositories.index_views import IndexDeleteView
from repositories.models import FileIndex, IndexStatus, Repository
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]
async def test_delete_index_clears_file_resume_anchors_and_graph_state -> None:
 """删除索引后再次新建必须全量重建，不能被旧 FileIndex hash 命中跳过。"""
 repo = await Repository.objects.acreate(
 name="delete-cleanup-repo",
 git_url="https://github.com/example/delete-cleanup.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXED,
 last_indexed_commit_sha="a" * 40,
 remote_head_sha="a" * 40,
 remote_head_checked_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
 behind_commits=0,
 behind_commits_calculated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
 indexed_files_processed=1,
 indexed_files_total=1,
 )
 await FileIndex.objects.acreate(
 repository=repo,
 file_path="src/main.ts",
 file_hash="hash-main",
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
 factory = APIRequestFactory
 request = factory.delete(f"/api/repositories/{repo.id}/index/")
 request.user = MagicMock
 with patch("repositories.index_views.QdrantService.delete_collection", return_value=True):
 response = await IndexDeleteView.delete(request, repo.id)
 assert response.status_code == 204
 await repo.arefresh_from_db
 assert repo.index_status == IndexStatus.NOT_INDEXED
 assert repo.last_indexed_commit_sha == ""
 assert repo.remote_head_sha == ""
 assert repo.remote_head_checked_at is None
 assert repo.behind_commits is None
 assert repo.behind_commits_calculated_at is None
 assert repo.indexed_files_processed == 0
 assert repo.indexed_files_total == 0
 assert await FileIndex.objects.filter(repository=repo).acount == 0
 assert await Symbol.objects.filter(repository=repo).acount == 0
 assert await ImportEdge.objects.filter(repository=repo).acount == 0
 assert await Endpoint.objects.filter(repository=repo).acount == 0
async def _make_chunk_registry(
 repo: Repository, file_path: str, chunk_index: int
) -> ChunkRegistry:
 return await ChunkRegistry.objects.acreate(
 chunk_id=uuid.uuid4,
 content_hash=f"hash-{chunk_index}",
 repository=repo,
 file_path=file_path,
 chunk_index=chunk_index,
 )
async def _make_chunk_edge(
 repo: Repository, source: ChunkRegistry, target: ChunkRegistry
) -> ChunkEdge:
 return await ChunkEdge.objects.acreate(
 source_chunk_id=source.chunk_id,
 target_chunk_id=target.chunk_id,
 edge_type=EdgeType.SAME_FILE,
 weight=0.5,
 repository=repo,
 )
async def test_cleanup_index_returns_accurate_counts -> None:
 """cleanup_index 直接调用应返回每类对象的删除计数（CleanupReport）。"""
 from repositories.services.index_cleanup import CleanupReport, cleanup_index
 repo = await Repository.objects.acreate(
 name="cleanup-counts-repo",
 git_url="https://github.com/example/cleanup-counts.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXED,
 )
 # 2 ChunkRegistry / 3 ChunkEdge / 1 FileIndex / 1 Symbol / 1 ImportEdge / 1 Endpoint
 cr1 = await _make_chunk_registry(repo, "src/a.ts", 0)
 cr2 = await _make_chunk_registry(repo, "src/b.ts", 0)
 await _make_chunk_edge(repo, cr1, cr2)
 await _make_chunk_edge(
 repo,
 cr1,
 await _make_chunk_registry(repo, "src/c.ts", 0),
 )
 # 第三条边复用 cr2 → 新 chunk
 cr4 = await _make_chunk_registry(repo, "src/d.ts", 0)
 await _make_chunk_edge(repo, cr2, cr4)
 # 注意：上面共造了 4 个 ChunkRegistry，但本测试期望计数 == 实际造数
 await FileIndex.objects.acreate(
 repository=repo, file_path="src/a.ts", file_hash="h"
 )
 await Symbol.objects.acreate(
 repository=repo,
 name="foo",
 symbol_type=Symbol.SymbolType.FUNCTION,
 file_path="src/a.ts",
 start_line=1,
 end_line=2,
 )
 await ImportEdge.objects.acreate(
 repository=repo,
 source_file="src/a.ts",
 target_module="vue",
 imported_names=["ref"],
 )
 await Endpoint.objects.acreate(
 repository=repo,
 http_method="GET",
 url_path="/api/x/",
 handler_name="x",
 view_type=Endpoint.ViewType.FUNCTION_VIEW,
 file_path="src/a.ts",
 line_number=1,
 )
 with patch(
 "repositories.services.index_cleanup.QdrantService.delete_collection",
 return_value=True,
 ):
 report = await cleanup_index(str(repo.id))
 assert isinstance(report, CleanupReport)
 assert report.qdrant_collection_deleted is True
 assert report.file_indexes_deleted == 1
 assert report.symbols_deleted == 1
 assert report.import_edges_deleted == 1
 assert report.endpoints_deleted == 1
 assert report.chunk_edges_deleted == 3
 assert report.chunk_registries_deleted == 4
 assert await ChunkEdge.objects.filter(repository=repo).acount == 0
 assert await ChunkRegistry.objects.filter(repository=repo).acount == 0
 assert await FileIndex.objects.filter(repository=repo).acount == 0
 assert await Symbol.objects.filter(repository=repo).acount == 0
async def test_cleanup_index_isolates_qdrant_failure -> None:
 """Qdrant 删除抛错时 cleanup_index 不向上传播，ORM 清理仍执行。"""
 from repositories.services.index_cleanup import cleanup_index
 repo = await Repository.objects.acreate(
 name="cleanup-isolation-repo",
 git_url="https://github.com/example/cleanup-isolation.git",
 git_platform="github",
 default_branch="main",
 index_status=IndexStatus.INDEXED,
 )
 cr = await _make_chunk_registry(repo, "src/x.ts", 0)
 await _make_chunk_edge(repo, cr, cr) # 自环边即可证明清理覆盖
 await FileIndex.objects.acreate(
 repository=repo, file_path="src/x.ts", file_hash="hx"
 )
 with patch(
 "repositories.services.index_cleanup.QdrantService.delete_collection",
 side_effect=RuntimeError("qdrant down"),
 ):
 report = await cleanup_index(str(repo.id))
 assert report.qdrant_collection_deleted is False
 # ORM 清理仍执行
 assert report.chunk_edges_deleted == 1
 assert report.chunk_registries_deleted == 1
 assert report.file_indexes_deleted == 1
 assert await ChunkRegistry.objects.filter(repository=repo).acount == 0
 assert await ChunkEdge.objects.filter(repository=repo).acount == 0
 assert await FileIndex.objects.filter(repository=repo).acount == 0
