"""PlaygroundSearchView API 测试 —— 覆盖。
测试端点：POST /api/codegraph/playground/search/
"""
from typing import Any
from unittest.mock import AsyncMock, patch
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from codegraph.services.layered_search import LayeredSearchResult, LayerResult
from services.retrieval.types import (
 HybridSearchResult,
 LayerSnapshot,
 NeighborMetadata,
)
User = get_user_model
def _make_mock_search_result(with_l4_orm: bool = False) -> LayeredSearchResult:
 """构造 LayeredSearchService.search 的模拟返回值。"""
 l1 = LayerResult(layer="L1", status="ok", result_count=1, items=[{"repo_id": "test-repo-1"}])
 l2 = LayerResult(layer="L2", status="ok", result_count=0, items=)
 l3 = LayerResult(layer="L3", status="ok", result_count=2, items=)
 if with_l4_orm:
 # 模拟 L4 items 包含 Symbol ORM 对象（待手动序列化的场景）
 class FakeSymbol:
 id = "fake-uuid-1234-5678-9012-123456789abc"
 name = "process_data"
 symbol_type = "FUNCTION"
 file_path = "src/core.py"
 l4: LayerResult = LayerResult(
 layer="L4",
 status="ok",
 result_count=1,
 items=[{"symbol": FakeSymbol, "depth": 1, "relationship": "callee"}],
 )
 else:
 l4 = LayerResult(layer="L4", status="skipped", result_count=0, items=)
 l5 = LayerResult(layer="L5", status="ok", result_count=500)
 return LayeredSearchResult(
 query="test query",
 repository_ids=["test-repo-1"],
 layers=[l1, l2, l3, l4, l5],
 final_context="# Test Context\n\nThis is a test context.",
 total_tokens=500,
 )
@pytest.fixture
def admin_user(db):
 return User.objects.create_superuser(
 username="playground_admin",
 email="playground_admin@example.com",
 password="adminpassword",
 )
@pytest.fixture
def regular_user(db):
 return User.objects.create_user(
 username="playground_regular",
 email="playground_regular@example.com",
 password="testpassword",
 )
@pytest.fixture
def admin_client(admin_user):
 client = APIClient
 client.force_authenticate(user=admin_user)
 return client
@pytest.fixture
def regular_client(regular_user):
 client = APIClient
 client.force_authenticate(user=regular_user)
 return client
PLAYGROUND_URL = "/api/codegraph/playground/search/"
@pytest.mark.django_db
def test_playground_requires_admin(regular_client):
 """: 非 admin 用户访问 playground/search/ 返回 403（T- 权限防护）。"""
 response = regular_client.post(
 PLAYGROUND_URL,
 {"query": "test"},
 format="json",
 )
 assert response.status_code == 403
@pytest.mark.django_db
def test_playground_unauthenticated:
 """: 未认证请求返回 401/403。"""
 client = APIClient
 response = client.post(PLAYGROUND_URL, {"query": "test"}, format="json")
 assert response.status_code in (401, 403)
@pytest.mark.django_db
def test_playground_returns_layers(admin_client):
 """: admin POST {query: "test"} → 200，含 layers 列表和 final_context 字符串。"""
 mock_result = _make_mock_search_result
 with patch(
 "codegraph.playground_views.LayeredSearchService.search",
 new=AsyncMock(return_value=mock_result),
 ):
 response = admin_client.post(
 PLAYGROUND_URL,
 {"query": "test query"},
 format="json",
 )
 assert response.status_code == 200
 data = response.json
 assert "layers" in data
 assert isinstance(data["layers"], list)
 assert len(data["layers"]) == 5
 assert "final_context" in data
 assert isinstance(data["final_context"], str)
 assert "query" in data
 assert "total_tokens" in data
@pytest.mark.django_db
def test_playground_l4_no_orm_objects(admin_client):
 """: L4 层 items 中无 Symbol ORM 对象 —— 手动序列化为 dict（T-）。"""
 mock_result = _make_mock_search_result(with_l4_orm=True)
 with patch(
 "codegraph.playground_views.LayeredSearchService.search",
 new=AsyncMock(return_value=mock_result),
 ):
 response = admin_client.post(
 PLAYGROUND_URL,
 {"query": "test query"},
 format="json",
 )
 assert response.status_code == 200
 data = response.json
 # 找到 L4 层
 l4_layer = next((layer for layer in data["layers"] if layer["layer"] == "L4"), None)
 assert l4_layer is not None
 assert l4_layer["status"] == "ok"
 assert len(l4_layer["items"]) == 1
 item = l4_layer["items"][0]
 # 验证已序列化为 dict，含 symbol_id 字符串
 assert "symbol_id" in item, "L4 item 应含 symbol_id 字符串"
 assert isinstance(item["symbol_id"], str), "symbol_id 应为字符串而非 ORM 对象"
 assert "name" in item
 assert "symbol_type" in item
 assert "depth" in item
 assert "relationship" in item
 # 确保没有 Symbol ORM 对象泄漏
 assert "symbol" not in item, "L4 item 不应含原始 symbol ORM 字段"
@pytest.mark.django_db
def test_playground_empty_query(admin_client):
 """POST 空 query 返回 400。"""
 response = admin_client.post(PLAYGROUND_URL, {"query": ""}, format="json")
 assert response.status_code == 400
@pytest.mark.django_db
def test_playground_response_structure(admin_client):
 """: 响应包含 query / repository_ids / layers / final_context / total_tokens。"""
 mock_result = _make_mock_search_result
 with patch(
 "codegraph.playground_views.LayeredSearchService.search",
 new=AsyncMock(return_value=mock_result),
 ):
 response = admin_client.post(
 PLAYGROUND_URL,
 {"query": "check structure", "repository_ids": ["test-repo-1"]},
 format="json",
 )
 assert response.status_code == 200
 data = response.json
 required_fields = {"query", "repository_ids", "layers", "final_context", "total_tokens"}
 assert required_fields.issubset(data.keys), f"响应缺少字段: {required_fields - data.keys}"
 assert isinstance(data["repository_ids"], list)
 assert data["total_tokens"] == 500
# ============================================================================
# Phase Plan：graph enrichment 字段透传（hop1/hop2/graph_context）
# ============================================================================
@pytest.mark.django_db
def test_search_passes_through_hop_neighbors_when_hybrid_result(admin_client):
 """Phase: HybridSearchResult 路径透传 hop1/hop2/graph_context 三字段。"""
 hop1 = NeighborMetadata(
 chunk_id="chunk-hop1-aaa",
 file_path="src/auth/login.py",
 line_start=10,
 line_end=42,
 edge_type="CALL",
 weight=0.85,
 reason="L3 命中 chunk 调用 verify_password",
 hop=1,
 )
 hop2 = NeighborMetadata(
 chunk_id="chunk-hop2-bbb",
 file_path="src/auth/utils.py",
 line_start=None,
 line_end=None,
 edge_type="IMPORT",
 weight=0.42,
 reason="二跳：通过 verify_password 间接 import bcrypt 工具",
 hop=2,
 )
 mock_result = HybridSearchResult(
 query="auth login",
 repository_ids=["test-repo-1"],
 layers=[
 LayerSnapshot(layer="L1", status="ok", result_count=1, items=),
 LayerSnapshot(layer="L2", status="ok", result_count=0, items=),
 LayerSnapshot(layer="L3", status="ok", result_count=2, items=),
 LayerSnapshot(layer="L4", status="skipped", result_count=0, items=),
 LayerSnapshot(layer="L5", status="ok", result_count=300),
 ],
 final_context="# context",
 total_tokens=300,
 graph_context="### Graph Context\nverify_password -> bcrypt",
 hop1_neighbors=[hop1],
 hop2_neighbors=[hop2],
 )
 with patch(
 "codegraph.playground_views.LayeredSearchService.search",
 new=AsyncMock(return_value=mock_result),
 ):
 response = admin_client.post(
 PLAYGROUND_URL,
 {"query": "auth login"},
 format="json",
 )
 assert response.status_code == 200
 data = response.json
 assert "hop1_neighbors" in data
 assert "hop2_neighbors" in data
 assert "graph_context" in data
 assert data["graph_context"] == "### Graph Context\nverify_password -> bcrypt"
 assert isinstance(data["hop1_neighbors"], list)
 assert len(data["hop1_neighbors"]) == 1
 item1: dict[str, Any] = data["hop1_neighbors"][0]
 assert item1["chunk_id"] == "chunk-hop1-aaa"
 assert item1["edge_type"] == "CALL"
 assert item1["weight"] == 0.85
 assert item1["hop"] == 1
 assert item1["file_path"] == "src/auth/login.py"
 assert item1["line_start"] == 10
 assert item1["line_end"] == 42
 assert item1["reason"].startswith("L3 命中")
 assert len(data["hop2_neighbors"]) == 1
 item2: dict[str, Any] = data["hop2_neighbors"][0]
 assert item2["chunk_id"] == "chunk-hop2-bbb"
 assert item2["edge_type"] == "IMPORT"
 assert item2["hop"] == 2
 assert item2["line_start"] is None
 assert item2["line_end"] is None
@pytest.mark.django_db
def test_search_falls_back_to_empty_when_legacy_layered_result(admin_client):
 """Phase: LayeredSearchResult 路径无 graph 字段 → 降级空 list / 空字符串。"""
 mock_result = _make_mock_search_result
 with patch(
 "codegraph.playground_views.LayeredSearchService.search",
 new=AsyncMock(return_value=mock_result),
 ):
 response = admin_client.post(
 PLAYGROUND_URL,
 {"query": "legacy"},
 format="json",
 )
 assert response.status_code == 200
 data = response.json
 # 旧 4 字段不变
 assert data["query"] == "test query"
 assert data["repository_ids"] == ["test-repo-1"]
 assert isinstance(data["layers"], list)
 assert len(data["layers"]) == 5
 assert data["final_context"] == "# Test Context\n\nThis is a test context."
 assert data["total_tokens"] == 500
 # 新 3 字段降级为空
 assert data["hop1_neighbors"] ==
 assert data["hop2_neighbors"] ==
 assert data["graph_context"] == ""
# ============================================================================
# Phase Code Review Fix（work item： / ）
# ============================================================================
@pytest.mark.django_db
def test_serialize_neighbor_falls_back_when_partial_mock(admin_client):
 """ 后端兜底：partial mock weight=None / reason=None / hop=None →
 序列化 weight=0.0 / reason='' / hop=1，避免前端 null.toFixed TypeError。"""
 class PartialMockNeighbor:
 chunk_id = "chunk-partial"
 file_path = "src/partial.py"
 line_start = None
 line_end = None
 edge_type = "CALL"
 weight = None # 缺失字段
 reason = None
 hop = None
 mock_result = HybridSearchResult(
 query="partial mock test",
 repository_ids=["test-repo-1"],
 layers=[LayerSnapshot(layer="L3", status="ok", result_count=0, items=)],
 final_context="",
 total_tokens=0,
 graph_context="",
 hop1_neighbors=[PartialMockNeighbor], # type: ignore[list-item]
 hop2_neighbors=,
 )
 with patch(
 "codegraph.playground_views.LayeredSearchService.search",
 new=AsyncMock(return_value=mock_result),
 ):
 response = admin_client.post(
 PLAYGROUND_URL,
 {"query": "test"},
 format="json",
 )
 assert response.status_code == 200
 data = response.json
 item = data["hop1_neighbors"][0]
 assert item["weight"] == 0.0
 assert item["reason"] == ""
 assert item["hop"] == 1
@pytest.mark.django_db
def test_max_tokens_invalid_returns_400(admin_client):
 """：max_tokens 传入非整数字符串 → 400 Bad Request 而非 500 Internal Server Error。"""
 response = admin_client.post(
 PLAYGROUND_URL,
 {"query": "test", "max_tokens": "abc"},
 format="json",
 )
 assert response.status_code == 400
 assert "max_tokens" in response.json.get("detail", "")
