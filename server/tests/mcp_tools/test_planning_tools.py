from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from rest_framework.test import APIClient

from interactions.models import InteractionEvent, ModelUsageRecord, RetrievalTrace, ToolCallRecord
from mcp_tools.models import McpCodingPlan, McpCodingPlanVersion, McpRepositoryAnalysis

pytestmark = pytest.mark.django_db


def _canonical_coding_content(repo_id: str, repo_name: str) -> dict[str, object]:
    """合法 §7 MergedPlan content（单仓最小集），含该仓 task + files（src/main.py）。"""
    return {
        "title": "新增 MCP 规划工具",
        "summary": "在 src/main.py 落地 MCP 规划工具入口。",
        "api_contracts": [],
        "dependency_dag": {},
        "data_migrations": [],
        "compat_risks": [],
        "release_order": [repo_id],
        "rollback_plan": {repo_id: "revert PR"},
        "risks": ["需求可能未覆盖所有调用路径"],
        "execution_plan": [
            {
                "id": "t1",
                "name": "实现 MCP 规划工具",
                "description": "新增规划工具入口",
                "repository_id": repo_id,
                "repository_name": repo_name,
                "branch_strategy": "feature",
                "coding_instruction": "在 src/main.py 注册并实现 MCP 规划工具。",
                "files": [{"path": "src/main.py", "action": "modify"}],
                "dependencies": [],
            }
        ],
    }


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UNIFY-04：create_coding_plan 收口到 delegate（canonical 映射）后落库/响应/trace 守护。

    方案生成从确定性 ``build_coding_plan`` 改 delegate 到统一编排，故 monkeypatch
    ``delegate_plan_orchestration`` 返回 canonical DONE → 断言映射后单仓字段 +
    McpCodingPlan(Version) 落库 + 工具调用/召回 trace（ModelUsageRecord 不再由 MCP 层记录，
    编排 adapters 内部承担，移除该断言）。
    """
    client, _plaintext = mcp_client
    repo_id = str(indexed_repository.id)
    analysis_response = client.post(
        "/api/mcp/tools/analyze_repository/",
        {
            "repository_id": repo_id,
            "focus": "MCP planning",
        },
        format="json",
    )
    assert analysis_response.status_code == 200

    async def _fake_delegate(**_kwargs: Any) -> Any:
        from mcp_tools.orchestration_delegate import DelegateResult

        return DelegateResult(
            session=SimpleNamespace(id=uuid.uuid4()),
            status="completed",
            content=_canonical_coding_content(repo_id, indexed_repository.name),
            plan_version_id=str(uuid.uuid4()),
            markdown="**新增 MCP 规划工具**",
        )

    monkeypatch.setattr("mcp_tools.views.delegate_plan_orchestration", _fake_delegate)

    response = client.post(
        "/api/mcp/tools/create_coding_plan/",
        {
            "repository_id": repo_id,
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
    # canonical execution_plan 该仓 task → 映射回旧单仓字段（affected_files/steps）。
    assert "src/main.py" in body["plan"]["affected_files"]
    assert body["plan"]["steps"]
    assert body["status"] == "completed"
    assert body["session_id"]
    assert ToolCallRecord.objects.filter(
        run=version.run,
        tool_name="create_coding_plan",
    ).exists()
    # evidence 由映射后 affected_files 推导 → RetrievalTrace FILE 落库（外形兼容）。
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
