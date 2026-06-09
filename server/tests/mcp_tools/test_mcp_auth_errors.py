from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

from repositories.models import IndexStatus, Repository

pytestmark = pytest.mark.django_db


def test_missing_token_returns_error_code() -> None:
    """匿名 MCP 请求 fail-closed：401（不降级为 403）且 error_code=authentication_failed。

    07-03 把 McpToolView 基类收紧为 IsAuthenticated 后，匿名请求在权限层即被拒，
    经 McpToolView.handle_exception（硬编码 401）返回 authentication_failed
    （resolved Open Question 1）。在此之前由 _begin 返回 authentication_required → RED。
    """
    response = APIClient().post(
        "/api/mcp/tools/get_repository/",
        {"repository_id": str(uuid.uuid4())},
        format="json",
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "authentication_failed"


def test_repository_not_found_error_code(mcp_client: tuple[APIClient, str]) -> None:
    client, _plaintext = mcp_client

    response = client.post(
        "/api/mcp/tools/search_rag_chunks/",
        {"repository_id": str(uuid.uuid4()), "query": "x"},
        format="json",
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "repository_not_found"


def test_repository_not_indexed_error_code(
    mcp_client: tuple[APIClient, str],
    repository: Repository,
) -> None:
    client, _plaintext = mcp_client
    repository.index_status = IndexStatus.NOT_INDEXED
    repository.save(update_fields=["index_status"])

    response = client.post(
        "/api/mcp/tools/search_rag_chunks/",
        {"repository_id": str(repository.id), "query": "x"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "repository_not_indexed"
