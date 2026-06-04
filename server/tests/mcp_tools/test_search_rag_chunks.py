from __future__ import annotations
from unittest.mock import AsyncMock
import pytest
from rest_framework.test import APIClient
from interactions.models import RetrievalTrace
from services.retrieval.types import HybridSearchResult, LayerSnapshot, NeighborMetadata
pytestmark = pytest.mark.django_db
def _mock_result -> HybridSearchResult:
 return HybridSearchResult(
 query="auth",
 repository_ids=["repo"],
 layers=[
 LayerSnapshot(
 layer="L3",
 status="ok",
 result_count=1,
 items=[
 {
 "id": "11111111-1111-1111-1111-111111111111",
 "score": 0.9,
 "payload": {
 "file_path": "src/main.py",
 "content": "def main: pass",
 "start_line": 1,
 "end_line": 2,
 "language": "python",
 },
 }
 ],
 )
 ],
 final_context="ctx",
 total_tokens=12,
 hop1_neighbors=[
 NeighborMetadata(
 chunk_id="22222222-2222-2222-2222-222222222222",
 file_path="src/utils/helpers.py",
 line_start=5,
 line_end=8,
 edge_type="CALL",
 weight=0.8,
 reason="via direct call",
 hop=1,
 )
 ],
 )
def test_search_rag_chunks_returns_chunks_edges_and_trace(
 mcp_client: tuple[APIClient, str],
 indexed_repository,
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 client, _plaintext = mcp_client
 search_mock = AsyncMock(return_value=_mock_result)
 monkeypatch.setattr(
 "services.retrieval.hybrid_search.HybridSearchService.search",
 search_mock,
 )
 response = client.post(
 "/api/mcp/tools/search_rag_chunks/",
 {"repository_id": str(indexed_repository.id), "query": "auth"},
 format="json",
 )
 assert response.status_code == 200
 body = response.json
 assert body["results"][0]["chunk_id"] == "11111111-1111-1111-1111-111111111111"
 assert body["related_edges"][0]["edge_type"] == "CALL"
 assert search_mock.await_args.kwargs["branch_name"] is None
 assert RetrievalTrace.objects.filter(kind=RetrievalTrace.Kind.CHUNK).exists
 assert RetrievalTrace.objects.filter(kind=RetrievalTrace.Kind.EDGE).exists
