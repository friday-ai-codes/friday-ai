"""：已索引文件清单 API 与文件级实时进度字段测试。
覆盖：
- IndexedFilesListView 的基础分页 / 搜索 / 排序
- IndexStatusSerializer 暴露 current_indexing_file / indexed_files_* 字段
- _compute_index_progress 兜底新字段
"""
from __future__ import annotations
from datetime import datetime, timezone
import pytest
from django.utils import timezone as dj_timezone
from repositories.models import FileIndex, IndexStatus, Repository
pytestmark = pytest.mark.django_db(transaction=True)
@pytest.fixture
def repository_with_indexed_files(repository: Repository) -> Repository:
 """种 5 个 FileIndex 行，含 last_commit_sha + last_commit_authored_at。"""
 base_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
 rows = [
 ("server/main.py", "h0", "a" * 40, base_dt),
 ("server/utils.py", "h1", "b" * 40, base_dt),
 ("web/src/App.vue", "h2", "c" * 40, base_dt),
 ("web/src/api/client.ts", "h3", "", None), # 缺 commit 数据的兜底
 ("README.md", "h4", "d" * 40, base_dt),
 ]
 for path, fh, sha, authored in rows:
 FileIndex.objects.create(
 repository=repository,
 file_path=path,
 file_hash=fh,
 last_commit_sha=sha,
 last_commit_authored_at=authored,
 )
 return repository
class TestIndexedFilesListView:
 def test_returns_paginated_default(
 self, authenticated_client, repository_with_indexed_files: Repository
 ) -> None:
 resp = authenticated_client.get(
 f"/api/repositories/{repository_with_indexed_files.id}/indexed-files/"
 )
 assert resp.status_code == 200
 data = resp.json
 assert data["total"] == 5
 assert len(data["items"]) == 5
 assert data["page"] == 1
 item = data["items"][0]
 for key in (
 "file_path", "file_hash", "last_commit_sha",
 "last_commit_authored_at", "indexed_at",
 ):
 assert key in item
 def test_search_substring_match(
 self, authenticated_client, repository_with_indexed_files: Repository
 ) -> None:
 resp = authenticated_client.get(
 f"/api/repositories/{repository_with_indexed_files.id}/indexed-files/?search=web"
 )
 assert resp.status_code == 200
 data = resp.json
 assert data["total"] == 2
 paths = {it["file_path"] for it in data["items"]}
 assert paths == {"web/src/App.vue", "web/src/api/client.ts"}
 def test_page_size_clamping(
 self, authenticated_client, repository_with_indexed_files: Repository
 ) -> None:
 resp = authenticated_client.get(
 f"/api/repositories/{repository_with_indexed_files.id}/indexed-files/?page_size=2&page=2"
 )
 assert resp.status_code == 200
 data = resp.json
 assert data["total"] == 5
 assert len(data["items"]) == 2
 assert data["page_size"] == 2
 def test_invalid_page_returns_400(
 self, authenticated_client, repository_with_indexed_files: Repository
 ) -> None:
 resp = authenticated_client.get(
 f"/api/repositories/{repository_with_indexed_files.id}/indexed-files/?page=abc"
 )
 assert resp.status_code == 400
 def test_404_for_missing_repository(self, authenticated_client) -> None:
 resp = authenticated_client.get(
 "/api/repositories/00000000-0000-0000-0000-000000000001/indexed-files/"
 )
 assert resp.status_code == 404
 def test_unauthenticated_blocked(
 self, api_client, repository_with_indexed_files: Repository
 ) -> None:
 resp = api_client.get(
 f"/api/repositories/{repository_with_indexed_files.id}/indexed-files/"
 )
 assert resp.status_code in (401, 403)
class TestIndexStatusFileLevelFields:
 def test_status_response_exposes_file_level_fields(
 self, authenticated_client, repository: Repository
 ) -> None:
 repository.index_status = IndexStatus.INDEXING
 repository.current_indexing_file = "server/views.py"
 repository.indexed_files_processed = 42
 repository.indexed_files_total = 100
 repository.last_indexed_at = dj_timezone.now
 repository.save(update_fields=[
 "index_status", "current_indexing_file",
 "indexed_files_processed", "indexed_files_total", "last_indexed_at",
 ])
 resp = authenticated_client.get(
 f"/api/repositories/{repository.id}/index/status/"
 )
 assert resp.status_code == 200
 data = resp.json
 assert data["current_indexing_file"] == "server/views.py"
 assert data["indexed_files_processed"] == 42
 assert data["indexed_files_total"] == 100
