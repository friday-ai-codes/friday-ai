from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

from interactions.models import InteractionEvent, ModelUsageRecord, RetrievalTrace, ToolCallRecord
from mcp_tools.models import McpCodingPlan, McpCodingPlanVersion, McpRepositoryAnalysis

pytestmark = pytest.mark.django_db


def _chunk(file_path: str = "src/main.py") -> dict[str, object]:
    return {
        "chunk_id": str(uuid.uuid4()),
        "file_path": file_path,
        "line_start": 1,
        "line_end": 20,
        "score": 0.92,
        "content": "def main():\n    return 'ok'",
    }


def test_analyze_repository_persists_artifact_and_replayable_trace(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client

    response = client.post(
        "/api/mcp/tools/analyze_repository/",
        {
            "repository_id": str(indexed_repository.id),
            "focus": "认证入口",
            "context_chunks": [_chunk()],
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    artifact = McpRepositoryAnalysis.objects.get(id=body["analysis_id"])
    assert artifact.repository_id == indexed_repository.id
    assert body["analysis"]["architecture_summary"]
    assert body["analysis"]["key_modules"]
    assert ToolCallRecord.objects.filter(
        run=artifact.run,
        tool_name="analyze_repository",
    ).exists()
    assert ModelUsageRecord.objects.filter(run=artifact.run).exists()
    assert InteractionEvent.objects.filter(
        run=artifact.run,
        event_type=InteractionEvent.EventType.AGENT_DECISION,
    ).exists()
    assert RetrievalTrace.objects.filter(
        run=artifact.run,
        kind=RetrievalTrace.Kind.CHUNK,
    ).exists()
    assert RetrievalTrace.objects.filter(
        run=artifact.run,
        kind=RetrievalTrace.Kind.FILE,
    ).exists()


def test_create_coding_plan_stores_version_and_evidence(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client
    analysis_response = client.post(
        "/api/mcp/tools/analyze_repository/",
        {
            "repository_id": str(indexed_repository.id),
            "focus": "MCP planning",
        },
        format="json",
    )
    assert analysis_response.status_code == 200

    response = client.post(
        "/api/mcp/tools/create_coding_plan/",
        {
            "repository_id": str(indexed_repository.id),
            "analysis_id": analysis_response.json()["analysis_id"],
            "requirement": "新增 src/main.py 的 MCP 规划工具",
            "context_chunks": [_chunk()],
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    plan = McpCodingPlan.objects.get(id=body["plan_id"])
    version = McpCodingPlanVersion.objects.get(id=body["version_id"])
    assert plan.current_version == 1
    assert version.version == 1
    assert "src/main.py" in body["plan"]["affected_files"]
    assert body["plan"]["steps"]
    assert body["plan"]["test_plan"]
    assert ToolCallRecord.objects.filter(
        run=version.run,
        tool_name="create_coding_plan",
    ).exists()
    assert ModelUsageRecord.objects.filter(run=version.run).exists()
    assert RetrievalTrace.objects.filter(run=version.run).exists()


def test_improve_coding_plan_appends_new_version(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client
    create_response = client.post(
        "/api/mcp/tools/create_coding_plan/",
        {
            "repository_id": str(indexed_repository.id),
            "requirement": "调整 src/main.py 的错误处理",
            "context_chunks": [_chunk()],
        },
        format="json",
    )
    assert create_response.status_code == 200
    plan_id = create_response.json()["plan_id"]

    response = client.post(
        "/api/mcp/tools/improve_coding_plan/",
        {
            "plan_id": plan_id,
            "feedback": "请增加回滚步骤并优先补错误码测试",
            "context_chunks": [_chunk("src/utils/helpers.py")],
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    plan = McpCodingPlan.objects.get(id=plan_id)
    assert plan.current_version == 2
    assert McpCodingPlanVersion.objects.filter(plan=plan).count() == 2
    assert body["version"] == 2
    assert "回滚步骤" in body["change_summary"]
    assert body["risk_delta"]["added"]
    assert ToolCallRecord.objects.filter(
        run__run_id=body["run_id"],
        tool_name="improve_coding_plan",
    ).exists()
    assert ModelUsageRecord.objects.filter(run__run_id=body["run_id"]).exists()
