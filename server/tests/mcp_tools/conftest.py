from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from repositories.models import FileIndex, IndexStatus, Repository


@pytest.fixture
def mcp_client(make_access_token: Any) -> tuple[APIClient, str]:
    _token, plaintext = make_access_token(name="mcp-test-token")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    return client, plaintext


@pytest.fixture
def indexed_repository(repository: Repository) -> Repository:
    repository.index_status = IndexStatus.INDEXED
    repository.description = "用于 MCP 测试的仓库"
    repository.ai_summary = "测试仓库摘要"
    repository.last_indexed_commit_sha = "a" * 40
    repository.save(
        update_fields=[
            "index_status",
            "description",
            "ai_summary",
            "last_indexed_commit_sha",
        ]
    )
    FileIndex.objects.create(
        repository=repository,
        file_path="src/main.py",
        file_hash="hash-main",
    )
    FileIndex.objects.create(
        repository=repository,
        file_path="src/utils/helpers.py",
        file_hash="hash-helper",
    )
    return repository


@pytest.fixture
def auth_headers(mcp_client: tuple[APIClient, str]) -> dict[str, str]:
    _client, plaintext = mcp_client
    return {"HTTP_AUTHORIZATION": f"Bearer {plaintext}"}
