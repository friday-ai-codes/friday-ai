from __future__ import annotations
from typing import Any
import pytest
from rest_framework.test import APIClient
from interactions.models import RetrievalTrace, ToolCallRecord
from mcp_tools.models import McpWorkItemContext
from mcp_tools.work_item_context_service import extract_feishu_doc_refs
from services.feishu import WorkItemInfo
pytestmark = pytest.mark.django_db
class _FakeFeishuClient:
 async def get_work_item(
 self,
 project_key: str,
 work_item_id: int,
 work_item_type: str = "story",
 fields: list[str] | None = None,
 ) -> WorkItemInfo:
 return WorkItemInfo(
 id=work_item_id,
 name="登录超时 Bug",
 description="复现步骤见 https://example.feishu.cn/docx/DOC123abc",
 status="doing",
 project_key=project_key,
 work_item_type=work_item_type,
 fields={
 "owner": "ou_owner",
 "role_owners": [{"role": "dev", "owners": ["ou_dev"]}],
 "description": "关联文档 doxcnPlainToken123",
 },
 raw_response='{"err_code": 0, "data": [{"id": 42}]}',
 )
 async def get_work_item_relations(
 self,
 project_key: str,
 work_item_id: int,
 work_item_type: str,
 ) -> list[dict[str, Any]]:
 return [
 {
 "relation_type": "related",
 "work_item_id": 41,
 "work_item_type": "story",
 "name": "相关需求",
 "status": "done",
 }
 ]
 async def get_comments(
 self,
 project_key: str,
 work_item_id: int,
 work_item_type: str,
 ) -> list[dict[str, Any]]:
 return [{"id": "c1", "content": "评论补充", "author": "dev"}]
class _FakeDocClient:
 async def get_document_content(self, document_id: str) -> tuple[str, list[dict[str, Any]]]:
 return f"# {document_id}\n\n文档内容", [{"block_id": "b1"}]
def test_extract_feishu_doc_refs_from_nested_values -> None:
 refs = extract_feishu_doc_refs(
 {
 "text": "查看 https://example.feishu.cn/docx/DOC123abc 和 doxcnPlainToken123",
 "nested": [{"url": "https://example.feishu.cn/wiki/WIKI456"}],
 }
 )
 assert refs == [
 {"document_id": "DOC123abc", "url": "https://example.feishu.cn/docx/DOC123abc"},
 {"document_id": "doxcnPlainToken123", "url": ""},
 {"document_id": "WIKI456", "url": "https://example.feishu.cn/wiki/WIKI456"},
 ]
def test_get_feishu_work_item_context_creates_snapshot_and_trace(
 mcp_client: tuple[APIClient, str],
 project,
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 client, _plaintext = mcp_client
 monkeypatch.setattr(
 "mcp_tools.work_item_context_service.create_feishu_client_for_project",
 lambda _project: _FakeFeishuClient,
 )
 async def _doc_client(_project):
 return _FakeDocClient
 monkeypatch.setattr(
 "mcp_tools.work_item_context_service.create_feishu_doc_client_for_project",
 _doc_client,
 )
 response = client.post(
 "/api/mcp/tools/get_feishu_work_item_context/",
 {
 "project_key": project.feishu_project_key,
 "work_item_type": "bug",
 "work_item_id": 42,
 "include_comments": True,
 },
 format="json",
 )
 assert response.status_code == 200
 body = response.json
 assert body["work_item"]["id"] == 42
 assert body["work_item"]["owners"][0]["value"] == "ou_owner"
 assert body["relations"][0]["work_item_id"] == 41
 assert {doc["status"] for doc in body["documents"]} == {"ok"}
 assert body["comments"][0]["id"] == "c1"
 assert body["status"] == "completed"
 context = McpWorkItemContext.objects.get(id=body["context_id"])
 assert context.run.run_id.hex == body["run_id"].replace("-", "")
 assert context.tool_call_id is not None
 assert context.work_item_type == "bug"
 assert context.context["summary"]["document_ok_count"] == 2
 assert ToolCallRecord.objects.filter(tool_name="get_feishu_work_item_context").count == 1
 assert RetrievalTrace.objects.filter(kind="file").count == 3
def test_get_feishu_work_item_context_partial_when_doc_client_missing(
 mcp_client: tuple[APIClient, str],
 project,
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 client, _plaintext = mcp_client
 monkeypatch.setattr(
 "mcp_tools.work_item_context_service.create_feishu_client_for_project",
 lambda _project: _FakeFeishuClient,
 )
 async def _missing_doc_client(_project):
 raise ValueError("doc credentials missing")
 monkeypatch.setattr(
 "mcp_tools.work_item_context_service.create_feishu_doc_client_for_project",
 _missing_doc_client,
 )
 response = client.post(
 "/api/mcp/tools/get_feishu_work_item_context/",
 {
 "project_key": project.feishu_project_key,
 "work_item_type": "bug",
 "work_item_id": 42,
 },
 format="json",
 )
 assert response.status_code == 200
 body = response.json
 assert body["status"] == "partial"
 assert {doc["status"] for doc in body["documents"]} == {"skipped"}
 assert McpWorkItemContext.objects.get(id=body["context_id"]).status == "partial"
