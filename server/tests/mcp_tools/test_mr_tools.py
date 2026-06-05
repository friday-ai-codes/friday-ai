from __future__ import annotations

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from common.encryption import encrypt_value
from interactions.ledger import create_interaction_run
from interactions.models import InteractionEvent, ToolCallRecord
from mcp_tools.models import McpCodingExecutionTrace, McpCodingPlan, McpCodingPlanVersion
from repositories.models import AuthType, GitCredential
from runners.models import hash_token
from services.git_platform.models import (
    BranchCompareResult,
    CompareFileEntry,
    MRCreateRequest,
    MRCreateResult,
)

pytestmark = pytest.mark.django_db


class FakeGitClient:
    def __init__(self, *, mr_success: bool = True) -> None:
        self.mr_success = mr_success
        self.last_request: MRCreateRequest | None = None

    async def compare_branches(
        self,
        source_branch: str,
        target_branch: str,
        max_files: int = 50,
    ) -> BranchCompareResult:
        return BranchCompareResult(
            success=True,
            ahead_by=1,
            behind_by=0,
            files=[
                CompareFileEntry(
                    path="src/main.py",
                    change_type="modified",
                    additions=2,
                    deletions=1,
                )
            ],
            total_additions=2,
            total_deletions=1,
        )

    async def create_merge_request(self, request: MRCreateRequest) -> MRCreateResult:
        self.last_request = request
        if self.mr_success:
            return MRCreateResult(
                success=True,
                mr_id="42",
                mr_url="https://example.com/mr/42",
            )
        return MRCreateResult(success=False, error="branch already has an open MR")

    async def get_user_id_by_username(self, username: str) -> int | None:
        return 1

    async def branch_exists(self, branch_name: str) -> bool:
        return False

    async def get_merge_request_diff(
        self,
        mr_id: str,
        max_files: int = 50,
        max_diff_lines: int = 500,
    ) -> Any:
        return None


def _create_plan(client: APIClient, repository_id: str) -> dict[str, Any]:
    response = client.post(
        "/api/mcp/tools/create_coding_plan/",
        {
            "repository_id": repository_id,
            "requirement": "准备 MR 创建工具",
            "context_chunks": [
                {
                    "chunk_id": str(uuid.uuid4()),
                    "file_path": "src/main.py",
                    "content": "def main(): pass",
                }
            ],
        },
        format="json",
    )
    assert response.status_code == 200
    return response.json()


def _create_execution_trace(client: APIClient, indexed_repository) -> McpCodingExecutionTrace:
    plan_body = _create_plan(client, str(indexed_repository.id))
    plan = McpCodingPlan.objects.get(id=plan_body["plan_id"])
    version = McpCodingPlanVersion.objects.get(id=plan_body["version_id"])
    run = create_interaction_run(
        token_fingerprint=hash_token("mr-trace"),
        source="mcp",
    )
    return McpCodingExecutionTrace.objects.create(
        run=run,
        plan=plan,
        plan_version=version,
        repository=indexed_repository,
        status=McpCodingExecutionTrace.Status.COMPLETED,
        branch_name="feat20260604.mcp-mr",
        target_branch="main",
        commit_sha="c" * 40,
        file_changes=["src/main.py"],
        push_result={"pushed": True, "remote": "origin"},
    )


def _credential(indexed_repository) -> None:
    GitCredential.objects.create(
        repository=indexed_repository,
        auth_type=AuthType.ACCESS_TOKEN,
        encrypted_token=encrypt_value("ghp_test_token"),
    )


def test_summarize_branch_persists_summary_and_mr_draft(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    _credential(indexed_repository)
    trace = _create_execution_trace(client, indexed_repository)
    monkeypatch.setattr(
        "mcp_tools.merge_request_service.get_git_platform_client",
        lambda repo, token: FakeGitClient(),
    )

    response = client.post(
        "/api/mcp/tools/summarize_branch/",
        {"execution_id": str(trace.id)},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    trace.refresh_from_db()
    assert body["summary"]["files"][0]["path"] == "src/main.py"
    assert body["summary"]["commits"][0]["sha"] == "c" * 40
    assert body["mr_draft"]["title"]
    assert trace.branch_summary["source_branch"] == "feat20260604.mcp-mr"
    assert ToolCallRecord.objects.filter(
        run__run_id=body["run_id"],
        tool_name="summarize_branch",
    ).exists()
    assert InteractionEvent.objects.filter(
        run__run_id=body["run_id"],
        event_type=InteractionEvent.EventType.AGENT_DECISION,
    ).exists()


def test_create_merge_request_persists_success_result(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    _credential(indexed_repository)
    trace = _create_execution_trace(client, indexed_repository)
    monkeypatch.setattr(
        "mcp_tools.merge_request_service.get_git_platform_client",
        lambda repo, token: FakeGitClient(mr_success=True),
    )

    response = client.post(
        "/api/mcp/tools/create_merge_request/",
        {
            "execution_id": str(trace.id),
            "title": "Ship MCP MR tool",
            "description": "Creates a merge request.",
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    trace.refresh_from_db()
    assert body["mr"]["success"] is True
    assert body["mr"]["mr_url"] == "https://example.com/mr/42"
    assert trace.mr_result["mr_id"] == "42"
    assert trace.status == McpCodingExecutionTrace.Status.COMPLETED
    assert trace.recovery_state["retryable"] is False


def test_create_merge_request_failure_marks_execution_partial(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    _credential(indexed_repository)
    trace = _create_execution_trace(client, indexed_repository)
    monkeypatch.setattr(
        "mcp_tools.merge_request_service.get_git_platform_client",
        lambda repo, token: FakeGitClient(mr_success=False),
    )

    response = client.post(
        "/api/mcp/tools/create_merge_request/",
        {"execution_id": str(trace.id)},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    trace.refresh_from_db()
    assert body["mr"]["success"] is False
    assert body["execution_status"] == "partial"
    assert trace.status == McpCodingExecutionTrace.Status.PARTIAL
    assert trace.mr_result["error"] == "branch already has an open MR"
    assert trace.recovery_state["retryable"] is True
