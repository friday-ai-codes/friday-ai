from __future__ import annotations
import uuid
import importlib
from unittest.mock import AsyncMock
import pytest
from rest_framework.test import APIClient
from code_relations.models import ChunkRegistry
from interactions.models import RetrievalTrace
from services.retrieval.types import NeighborMetadata
pytestmark = pytest.mark.django_db
def test_find_related_chunks_resolves_file_path_and_records_edges(
 mcp_client: tuple[APIClient, str],
 indexed_repository,
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 client, _plaintext = mcp_client
 chunk_id = uuid.uuid4
 ChunkRegistry.objects.create(
 chunk_id=chunk_id,
 content_hash="hash",
 repository=indexed_repository,
 branch_name="",
 file_path="src/main.py",
 chunk_index=0,
 )
 find_mock = AsyncMock(
 return_value=[
 NeighborMetadata(
 chunk_id=str(uuid.uuid4),
 file_path="src/utils/helpers.py",
 line_start=1,
 line_end=2,
 edge_type="CALL",
 weight=0.7,
 reason="via direct call",
 hop=1,
 )
 ]
 )
 find_related_module = importlib.import_module("services.retrieval.find_related")
 monkeypatch.setattr(find_related_module, "find_related", find_mock)
 response = client.post(
 "/api/mcp/tools/find_related_chunks/",
 {
 "repository_id": str(indexed_repository.id),
 "file_path": "src/main.py",
 "hops": 1,
 },
 format="json",
 )
 assert response.status_code == 200
 body = response.json
 assert body["source"]["chunk_id"] == str(chunk_id)
 assert body["related_chunks"][0]["edge_type"] == "CALL"
 assert RetrievalTrace.objects.filter(kind=RetrievalTrace.Kind.EDGE).exists
def test_find_related_chunks_requires_exactly_one_source(
 mcp_client: tuple[APIClient, str],
 indexed_repository,
) -> None:
 client, _plaintext = mcp_client
 response = client.post(
 "/api/mcp/tools/find_related_chunks/",
 {"repository_id": str(indexed_repository.id)},
 format="json",
 )
 assert response.status_code == 400
 assert response.json["error_code"] == "invalid_params"
