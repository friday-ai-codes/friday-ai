from __future__ import annotations

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_get_repository_returns_metadata(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client

    response = client.post(
        "/api/mcp/tools/get_repository/",
        {"repository_id": str(indexed_repository.id)},
        format="json",
    )

    assert response.status_code == 200
    repo = response.json()["repository"]
    assert repo["repo_id"] == str(indexed_repository.id)
    assert repo["index_status"] == "indexed"
    assert repo["last_indexed_commit_sha"] == "a" * 40
