from __future__ import annotations

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from agents.models import AgentSession
from chat.models import CodingSession
from interactions.models import InteractionEvent, ToolCallRecord
from mcp_tools.models import McpCodingExecutionTrace
from subagent.models import SubAgentSession, TaskResult

pytestmark = pytest.mark.django_db


def _create_plan(client: APIClient, repository_id: str) -> dict[str, Any]:
    response = client.post(
        "/api/mcp/tools/create_coding_plan/",
        {
            "repository_id": repository_id,
            "requirement": "修改 src/main.py 并提交执行结果",
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


def _patch_successful_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_dispatch(
        coding_session: CodingSession,
        task_type: str = "coding",
        extra_metadata: dict[str, str] | None = None,
        prompt: str = "",
    ) -> str:
        agent = await AgentSession.objects.acreate(
            session_id=f"agent-mcp-{uuid.uuid4().hex[:8]}",
            space=coding_session.conversation.space,
            status=AgentSession.Status.RUNNING,
            metadata={
                "source": "mcp_execute_test",
                "task_type": task_type,
                "prompt_preview": prompt[:40],
                "extra_metadata": extra_metadata or {},
            },
        )
        sub = await SubAgentSession.objects.acreate(
            session_id=f"coding-mcp-{uuid.uuid4().hex[:8]}",
            main_session=agent,
            task_type=SubAgentSession.TaskType.CODING,
            status=SubAgentSession.Status.RUNNING,
            repo_url=coding_session.repository.git_url,
            last_output={
                "logs": [{"type": "progress", "content": "runner started"}],
            },
        )
        coding_session.subagent_session = sub
        await coding_session.asave(update_fields=["subagent_session", "updated_at"])
        return sub.session_id

    monkeypatch.setattr("mcp_tools.execution_service.dispatch_coding_task", _fake_dispatch)


def test_execute_coding_plan_dispatches_coding_session_and_trace(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    _patch_successful_dispatch(monkeypatch)
    plan_body = _create_plan(client, str(indexed_repository.id))

    response = client.post(
        "/api/mcp/tools/execute_coding_plan/",
        {
            "plan_id": plan_body["plan_id"],
            "branch_name": "feat20260604.mcp-exec",
            "timeout_seconds": 600,
        },
        format="json",
    )

    assert response.status_code == 202
    body = response.json()
    trace = McpCodingExecutionTrace.objects.get(id=body["execution_id"])
    assert trace.status == McpCodingExecutionTrace.Status.RUNNING
    assert trace.coding_session is not None
    assert trace.subagent_session is not None
    assert trace.branch_name == "feat20260604.mcp-exec"
    assert body["subagent_session_id"].startswith("coding-mcp-")
    assert ToolCallRecord.objects.filter(
        run=trace.run,
        tool_name="execute_coding_plan",
    ).exists()
    assert InteractionEvent.objects.filter(
        run=trace.run,
        event_type=InteractionEvent.EventType.AGENT_DECISION,
    ).exists()


def test_get_coding_execution_refreshes_commit_push_logs_and_diff(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    _patch_successful_dispatch(monkeypatch)
    plan_body = _create_plan(client, str(indexed_repository.id))
    execute_response = client.post(
        "/api/mcp/tools/execute_coding_plan/",
        {"plan_id": plan_body["plan_id"], "branch_name": "feat20260604.mcp-refresh"},
        format="json",
    )
    assert execute_response.status_code == 202
    execution_id = execute_response.json()["execution_id"]
    trace = McpCodingExecutionTrace.objects.get(id=execution_id)
    assert trace.subagent_session is not None
    TaskResult.objects.create(
        session=trace.subagent_session,
        result_type=TaskResult.ResultType.GIT,
        branch_name=trace.branch_name,
        commit_sha="b" * 40,
        modified_files=["src/main.py"],
        raw_output={
            "push_result": {"pushed": True, "remote": "origin"},
            "diff_summary": {"files": [{"path": "src/main.py", "additions": 2}]},
            "test_results": [{"command": "pytest tests/mcp_tools", "status": "passed"}],
        },
        duration_ms=1234,
    )
    trace.subagent_session.status = SubAgentSession.Status.COMPLETED
    trace.subagent_session.save(update_fields=["status", "updated_at"])

    response = client.post(
        "/api/mcp/tools/get_coding_execution/",
        {"execution_id": execution_id},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["commit_sha"] == "b" * 40
    assert body["file_changes"] == ["src/main.py"]
    assert body["push_result"]["pushed"] is True
    assert body["last_diff"]["files"][0]["path"] == "src/main.py"
    assert body["runner_logs"][0]["content"] == "runner started"
    assert body["test_results"][0]["status"] == "passed"


def test_execute_coding_plan_persists_dispatch_failure_as_recoverable_trace(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client

    async def _fail_dispatch(*args: object, **kwargs: object) -> str:
        raise RuntimeError("没有可用的 Runner")

    monkeypatch.setattr("mcp_tools.execution_service.dispatch_coding_task", _fail_dispatch)
    plan_body = _create_plan(client, str(indexed_repository.id))

    response = client.post(
        "/api/mcp/tools/execute_coding_plan/",
        {
            "plan_id": plan_body["plan_id"],
            "branch_name": "feat20260604.mcp-fail",
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    trace = McpCodingExecutionTrace.objects.get(id=body["execution_id"])
    assert trace.status == McpCodingExecutionTrace.Status.FAILED
    assert "没有可用的 Runner" in body["error"]
    assert body["recovery_state"]["retryable"] is True
    assert trace.coding_session is not None
