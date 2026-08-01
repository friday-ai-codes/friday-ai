from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_get_repository_file_reads_indexed_chunks(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    monkeypatch.setattr(
        "services.repo_file_read._scroll_file_from_collection",
        AsyncMock(
            return_value=[
                {
                    "chunk_index": 0,
                    "content": "line1\nline2\nline3",
                    "start_line": 1,
                    "end_line": 3,
                    "language": "python",
                }
            ]
        ),
    )

    response = client.post(
        "/api/mcp/tools/get_repository_file/",
        {
            "repository_id": str(indexed_repository.id),
            "file_path": "src/main.py",
            "start_line": 2,
            "end_line": 3,
            "max_lines": 2,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["file_path"] == "src/main.py"
    assert "line1" in body["content"]
    assert body["total_chunks"] == 1
