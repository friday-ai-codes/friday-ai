"""`GET /api/repositories/<id>/chunk-at/` 守护测试（IDX-02，per 25-02 plan Task 2）。

覆盖（对齐 plan done / threat_model）：
- 命中：返回 chunk_id + 行范围 200。
- 缺 path / 缺 line / 非法 line → 400。
- 未认证 → 401/403（T-25-06）。
- 不存在仓库 → 404。
- 被排除文件 → 空 chunks 200（与无命中同形，不泄漏存在性，T-25-05）。
"""

from __future__ import annotations

import uuid

import pytest

from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

CHUNK_AT_URL = "/api/repositories/{repo_id}/chunk-at/"


def _make_row(repository, *, file_path, line_start, line_end, chunk_index=0, branch_name=""):
    from code_relations.models import ChunkRegistry

    return ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="a" * 64,
        repository=repository,
        file_path=file_path,
        chunk_index=chunk_index,
        branch_name=branch_name,
        line_start=line_start,
        line_end=line_end,
    )


class TestChunkAtView:
    def test_hit_returns_chunk(self, authenticated_client, repository: Repository) -> None:
        row = _make_row(repository, file_path="src/a.py", line_start=10, line_end=30)
        resp = authenticated_client.get(
            CHUNK_AT_URL.format(repo_id=repository.id), {"path": "src/a.py", "line": 15}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "src/a.py"
        assert data["line"] == 15
        assert len(data["chunks"]) == 1
        assert data["chunks"][0]["chunk_id"] == str(row.chunk_id)
        assert data["chunks"][0]["line_start"] == 10
        assert data["chunks"][0]["line_end"] == 30

    def test_no_hit_returns_empty(self, authenticated_client, repository: Repository) -> None:
        _make_row(repository, file_path="src/a.py", line_start=10, line_end=30)
        resp = authenticated_client.get(
            CHUNK_AT_URL.format(repo_id=repository.id), {"path": "src/a.py", "line": 999}
        )
        assert resp.status_code == 200
        assert resp.json()["chunks"] == []

    def test_missing_path_400(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.get(
            CHUNK_AT_URL.format(repo_id=repository.id), {"line": 5}
        )
        assert resp.status_code == 400

    def test_missing_line_400(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.get(
            CHUNK_AT_URL.format(repo_id=repository.id), {"path": "src/a.py"}
        )
        assert resp.status_code == 400

    def test_non_integer_line_400(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.get(
            CHUNK_AT_URL.format(repo_id=repository.id), {"path": "src/a.py", "line": "abc"}
        )
        assert resp.status_code == 400

    def test_non_positive_line_400(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.get(
            CHUNK_AT_URL.format(repo_id=repository.id), {"path": "src/a.py", "line": 0}
        )
        assert resp.status_code == 400

    def test_unauthenticated_blocked(self, api_client, repository: Repository) -> None:
        resp = api_client.get(
            CHUNK_AT_URL.format(repo_id=repository.id), {"path": "src/a.py", "line": 5}
        )
        assert resp.status_code in (401, 403)

    def test_missing_repo_404(self, authenticated_client) -> None:
        resp = authenticated_client.get(
            CHUNK_AT_URL.format(repo_id="00000000-0000-0000-0000-000000000001"),
            {"path": "src/a.py", "line": 5},
        )
        assert resp.status_code == 404

    def test_excluded_file_no_existence_leak(
        self, authenticated_client, repository: Repository
    ) -> None:
        # 被排除文件（.env）即便有 chunk 也返回空 chunks，与无命中同形（T-25-05）
        _make_row(repository, file_path=".env", line_start=1, line_end=5)
        resp = authenticated_client.get(
            CHUNK_AT_URL.format(repo_id=repository.id), {"path": ".env", "line": 3}
        )
        assert resp.status_code == 200
        assert resp.json()["chunks"] == []
