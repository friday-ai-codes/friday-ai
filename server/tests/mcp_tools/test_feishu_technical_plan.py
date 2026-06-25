from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from interactions.ledger import create_interaction_run
from interactions.models import ToolCallRecord
from mcp_tools.models import McpWorkItemContext, McpWorkItemTechnicalPlan
from repositories.models import FileIndex
from runners.models import hash_token

pytestmark = pytest.mark.django_db


class _FakeDocClient:
    async def create_document(
        self,
        title: str,
        folder_token: str,
        content: str,
    ) -> dict[str, str]:
        assert title
        assert folder_token == "folder_tech_plan"
        assert "仓库任务矩阵" in content
        return {
            "document_id": "doxcnTechnicalPlan",
            "url": "https://feishu.cn/docx/doxcnTechnicalPlan",
        }


class _FakeFeishuClient:
    comments: list[dict[str, Any]] = []

    async def add_comment(
        self,
        project_key: str,
        work_item_id: int,
        work_item_type: str,
        content: str,
    ) -> bool:
        self.comments.append(
            {
                "project_key": project_key,
                "work_item_id": work_item_id,
                "work_item_type": work_item_type,
                "content": content,
            }
        )
        return True


def _context(project) -> McpWorkItemContext:
    run = create_interaction_run(
        token_fingerprint=hash_token("technical-plan-context"),
        source="mcp",
    )
    return McpWorkItemContext.objects.create(
        run=run,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="bug",
        work_item_id=42,
        name="登录超时 Bug",
        status=McpWorkItemContext.Status.COMPLETED,
        work_item_status="doing",
        description="登录超过 30 秒后 token 过期。",
        fields={"owner": "ou_owner"},
        relations=[{"work_item_id": 41, "name": "认证重构"}],
        documents=[
            {
                "document_id": "doxcnRequirement",
                "status": "ok",
                "content": "# 需求\n\n登录超时后提示不清晰。",
            }
        ],
        context={
            "work_item": {
                "source": {
                    "project_key": project.feishu_project_key,
                    "work_item_type": "bug",
                    "work_item_id": 42,
                    "url": "https://project.feishu.cn/demo/issue/detail/42",
                }
            }
        },
    )


def test_create_feishu_technical_plan_writes_doc_comment_and_artifact(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    project.feishu_doc_folder_token = "folder_tech_plan"
    project.save(update_fields=["feishu_doc_folder_token"])
    context = _context(project)
    _FakeFeishuClient.comments.clear()

    async def _doc_client(_project):
        return _FakeDocClient()

    monkeypatch.setattr(
        "mcp_tools.technical_plan_service.create_feishu_doc_client_for_project",
        _doc_client,
    )
    monkeypatch.setattr(
        "mcp_tools.technical_plan_service.create_feishu_client_for_project",
        lambda _project: _FakeFeishuClient(),
    )

    response = client.post(
        "/api/mcp/tools/create_feishu_technical_plan/",
        {
            "context_id": str(context.id),
            "repository_ids": [str(indexed_repository.id)],
            "context_chunks": [
                {
                    "chunk_id": "chunk-1",
                    "repository_id": str(indexed_repository.id),
                    "file_path": "src/auth/session.py",
                    "content": "def validate_session(): ...",
                    "score": 0.91,
                }
            ],
            "similar_cases": [
                {
                    "case_id": "case-1",
                    "title": "登录态过期修复",
                    "outcome": "merged",
                    "reuse_judgement": "可复用 token 刷新边界判断",
                }
            ],
            "title": "登录超时 Bug 技术方案",
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["feishu_document"]["status"] == "created"
    assert body["comment"]["status"] == "written"
    assert body["retry_state"]["retryable"] is False
    assert body["repository_tasks"][0]["repository_id"] == str(indexed_repository.id)
    assert body["repository_tasks"][0]["planned_branch"].startswith("feat/feishu-bug-42")
    assert "src/auth/session.py" in body["repository_tasks"][0]["candidate_files"]
    assert "登录态过期修复" in body["markdown"]

    artifact = McpWorkItemTechnicalPlan.objects.get(id=body["technical_plan_id"])
    assert artifact.context == context
    assert artifact.tool_call_id is not None
    assert artifact.feishu_document_url == "https://feishu.cn/docx/doxcnTechnicalPlan"
    assert artifact.repository_tasks[0]["repository_name"] == indexed_repository.name
    assert ToolCallRecord.objects.filter(tool_name="create_feishu_technical_plan").count() == 1
    assert _FakeFeishuClient.comments[0]["work_item_id"] == 42
    assert "https://feishu.cn/docx/doxcnTechnicalPlan" in _FakeFeishuClient.comments[0]["content"]


def test_create_feishu_technical_plan_preserves_partial_doc_writeback_failure(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client
    project.feishu_doc_folder_token = ""
    project.save(update_fields=["feishu_doc_folder_token"])
    context = _context(project)
    FileIndex.objects.get_or_create(
        repository=indexed_repository,
        file_path="src/auth/session.py",
        defaults={"file_hash": "hash-auth"},
    )

    response = client.post(
        "/api/mcp/tools/create_feishu_technical_plan/",
        {
            "context_id": str(context.id),
            "repository_ids": [str(indexed_repository.id)],
            "create_document": True,
            "write_comment": False,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["feishu_document"]["status"] == "error"
    assert body["retry_state"]["retryable"] is True
    assert body["retry_state"]["failed_stage"] == "document_writeback"
    assert body["comment"]["status"] == "skipped"

    artifact = McpWorkItemTechnicalPlan.objects.get(id=body["technical_plan_id"])
    assert artifact.status == McpWorkItemTechnicalPlan.Status.PARTIAL
    assert artifact.error_stage == "document_writeback"
    assert artifact.repository_tasks
