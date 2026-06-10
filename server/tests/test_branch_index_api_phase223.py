"""GET /api/repositories/<uuid>/branch-indexes/ 只读列表。"""

import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from repositories.models import BranchIndexStatus, Repository, RepositoryBranchIndex


@pytest.mark.django_db
class TestBranchIndexListAPI:
    """分支索引列表 API。"""

    def test_authenticated_returns_200_and_fields(
        self, authenticated_client: APIClient, repository: Repository
    ) -> None:
        now = timezone.now()
        RepositoryBranchIndex.objects.create(
            repository=repository,
            branch_name="main",
            is_base_branch=True,
            is_stale=False,
            last_indexed_commit_sha="deadbeef" * 2,
            last_indexed_at=now,
            effective_chunks_count=42,
            status=BranchIndexStatus.INDEXED,
        )
        url = f"/api/repositories/{repository.id}/branch-indexes/"
        resp = authenticated_client.get(url)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        row = data[0]
        assert row["branch_name"] == "main"
        assert row["is_base_branch"] is True
        assert row["is_stale"] is False
        assert row["last_indexed_commit_sha"] == "deadbeef" * 2
        assert row["effective_chunks_count"] == 42
        assert row["last_indexed_at"] is not None

    def test_multiple_branches_ordered(self, authenticated_client: APIClient) -> None:
        repo = Repository.objects.create(
            name="multi-branch",
            git_url="https://github.com/test/mb.git",
        )
        RepositoryBranchIndex.objects.create(
            repository=repo, branch_name="z-last", is_base_branch=False
        )
        RepositoryBranchIndex.objects.create(
            repository=repo, branch_name="a-first", is_base_branch=True
        )
        url = f"/api/repositories/{repo.id}/branch-indexes/"
        resp = authenticated_client.get(url)
        assert resp.status_code == 200
        names = [r["branch_name"] for r in resp.json()]
        assert names == ["a-first", "z-last"]

    def test_unauthenticated_returns_401(self, api_client: APIClient, repository: Repository) -> None:
        url = f"/api/repositories/{repository.id}/branch-indexes/"
        resp = api_client.get(url)
        assert resp.status_code == 401

    def test_unknown_repository_returns_404(
        self, authenticated_client: APIClient
    ) -> None:
        url = f"/api/repositories/{uuid.uuid4()}/branch-indexes/"
        resp = authenticated_client.get(url)
        assert resp.status_code == 404
