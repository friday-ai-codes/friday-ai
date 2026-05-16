"""Phase: CrossRepo RAG 端到端集成测试。
需要本地运行的 Qdrant（http://localhost:6333）+ 已配置 Embedding 服务。
双重 skipif 保护：外部服务不可用时自动跳过，不阻塞 CI。
运行（本地）：cd server && uv run pytest -m integration tests/services/test_endpoint_rag_integration.py -v
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch
import pytest
# ---------------------------------------------------------------------------
# 外部服务可用性探测
# ---------------------------------------------------------------------------
def _qdrant_available -> bool:
 """检测 Qdrant 是否在 localhost:6333 运行。"""
 try:
 import httpx
 resp = httpx.get("http://localhost:6333/healthz", timeout=2.0)
 return resp.status_code == 200
 except Exception:
 return False
def _embedding_configured -> bool:
 """检测 Embedding API 是否已配置（通过 Django ORM）。"""
 try:
 import django
 django.setup
 from system.models import SettingKeys, SystemSetting
 setting = SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_API_URL).first
 return bool(setting and setting.value)
 except Exception:
 return False
# ---------------------------------------------------------------------------
# 集成测试
# ---------------------------------------------------------------------------
@dataclass
class _FakeEndpointData:
 """最小化 EndpointData 替身。"""
 http_method: str
 url_path: str | None
 handler_name: str
 file_path: str
 line_number: int
 view_type: str = "FUNCTION_VIEW"
 metadata: dict[str, Any] | None = field(default=None)
@pytest.mark.integration
@pytest.mark.skipif(
 not _qdrant_available,
 reason="Qdrant 未运行于 http://localhost:6333",
)
@pytest.mark.asyncio
class TestCrossRagEndToEnd:
 """: 端到端 write endpoint → Qdrant → 可被 search 召回。"""
 TEST_REPO_ID = "work-item"
 TEST_REPO_NAME = "study-course-test"
 @pytest.fixture(autouse=True)
 async def setup_and_teardown(self):
 """创建测试 collection，测试结束后清理。"""
 from services.qdrant_service import QdrantService
 # 清理可能残留的旧 collection
 try:
 client = QdrantService.get_client
 col_name = QdrantService.get_collection_name(self.TEST_REPO_ID)
 if client.collection_exists(col_name):
 client.delete_collection(col_name)
 except Exception:
 pass
 yield
 # 清理测试 collection
 try:
 client = QdrantService.get_client
 col_name = QdrantService.get_collection_name(self.TEST_REPO_ID)
 if client.collection_exists(col_name):
 client.delete_collection(col_name)
 except Exception:
 pass
 async def test_write_then_search_endpoint(self):
 """写入 api_endpoint 文档后，可通过 Qdrant 按 payload 找到对应记录。"""
 from services.endpoint_rag_writer import write_endpoint_rag_docs
 from services.qdrant_service import QdrantService
 ep = _FakeEndpointData(
 http_method="POST",
 url_path="/api/users",
 handler_name="userHandler.CreateUser",
 file_path="handlers/users.go",
 line_number=42,
 )
 # 创建 collection（dense-only，使用小向量维度用于测试）
 # mock embedding 返回固定向量
 fake_emb = [0.1] * 1536
 col_name = QdrantService.get_collection_name(self.TEST_REPO_ID)
 QdrantService.create_collection_by_name(col_name, vector_size=len(fake_emb), hybrid=False)
 with patch(
 "services.endpoint_rag_writer.EmbeddingService.generate_embeddings_batch",
 return_value=[fake_emb],
 ):
 count = await write_endpoint_rag_docs(
 endpoints_with_sigs=[(ep, "func CreateUser(c *gin.Context)")],
 repository_id=self.TEST_REPO_ID,
 repo_name=self.TEST_REPO_NAME,
 hybrid_enabled=False,
 )
 assert count == 1, f"应写入 1 个点，实际 {count}"
 # 通过 Qdrant scroll 验证 payload
 client = QdrantService.get_client
 scroll_result, _ = client.scroll(
 collection_name=col_name,
 with_payload=True,
 limit=10,
 )
 assert len(scroll_result) == 1
 payload = scroll_result[0].payload or {}
 #: content_type 字段
 assert payload.get("content_type") == "api_endpoint"
 assert payload.get("http_method") == "POST"
 assert payload.get("url_path") == "/api/users"
 assert payload.get("handler_name") == "userHandler.CreateUser"
 #: content 含关键字段
 content = payload.get("content", "")
 assert "POST" in content
 assert "/api/users" in content
 assert self.TEST_REPO_NAME in content
 assert "userHandler.CreateUser" in content
 async def test_idempotent_reindex(self):
 """重索引同一 endpoint 不产生重复点（点 ID 幂等）。"""
 from services.endpoint_rag_writer import write_endpoint_rag_docs
 from services.qdrant_service import QdrantService
 ep = _FakeEndpointData(
 http_method="GET",
 url_path="/api/topics",
 handler_name="topicHandler.List",
 file_path="handlers/topic.go",
 line_number=10,
 )
 fake_emb = [0.2] * 1536
 col_name = QdrantService.get_collection_name(self.TEST_REPO_ID)
 QdrantService.create_collection_by_name(col_name, vector_size=len(fake_emb), hybrid=False)
 with patch(
 "services.endpoint_rag_writer.EmbeddingService.generate_embeddings_batch",
 return_value=[fake_emb],
 ):
 count1 = await write_endpoint_rag_docs(
 endpoints_with_sigs=[(ep, "")],
 repository_id=self.TEST_REPO_ID,
 repo_name=self.TEST_REPO_NAME,
 )
 count2 = await write_endpoint_rag_docs(
 endpoints_with_sigs=[(ep, "")],
 repository_id=self.TEST_REPO_ID,
 repo_name=self.TEST_REPO_NAME,
 )
 # 两次写入都应成功
 assert count1 == 1
 assert count2 == 1
 # Qdrant collection 中仍只有 1 个点（UUID 相同 → upsert 覆盖）
 client = QdrantService.get_client
 scroll_result, _ = client.scroll(
 collection_name=col_name,
 with_payload=False,
 limit=10,
 )
 assert len(scroll_result) == 1, f"重索引后应只有 1 个点，实际 {len(scroll_result)}"
