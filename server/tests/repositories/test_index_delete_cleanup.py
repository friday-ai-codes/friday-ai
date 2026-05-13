"""删除索引时清理所有会影响重建的本地索引状态。"""
from __future__ import annotations
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest
from rest_framework.test import APIRequestFactory
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
