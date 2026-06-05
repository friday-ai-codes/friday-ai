from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from interactions.models import RetrievalTrace

pytestmark = pytest.mark.django_db


def test_list_repository_files_collapses_directories(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client

    response = client.post(
        "/api/mcp/tools/list_repository_files/",
        {"repository_id": str(indexed_repository.id), "path": "src", "recursive": False},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    items = {(item["path"], item["type"]) for item in body["items"]}
    assert ("src/main.py", "file") in items
    assert ("src/utils", "directory") in items
    assert RetrievalTrace.objects.filter(kind=RetrievalTrace.Kind.FILE).exists()
