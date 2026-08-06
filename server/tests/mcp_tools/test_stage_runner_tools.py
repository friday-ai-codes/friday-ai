"""蓝图环节单跑 MCP 工具面测试（stage sandbox 家族五工具）。

守三件事：

1. dry-run 面（route / spec）：入参校验、路由契约键透传、run_id 留痕。
2. research 沙箱两段式：start（indirect 轻量合成）→ get 轮询；不存在会话中性 404。
3. apply_repo_association：唯一写回路径 —— 成员可 bind（缺省默认分支），非成员 403。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from interactions.models import InteractionRun, RetrievalTrace

pytestmark = pytest.mark.django_db

_ROUTING_TOP_LEVEL_KEYS = {
    "router_version",
    "auto_selected",
    "intent",
    "weights_used",
    "charter_supplement_count",
    "unjustified_boundary_hit_count",
    "candidates",
    "citations",
    "run_id",
}


def test_route_blueprint_repos_dry_run(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    monkeypatch.setattr(
        "codegraph.services.repo_router_v2.RepoRouterV2.route",
        AsyncMock(
            return_value=SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        repo_id=str(indexed_repository.id),
                        repo_name=indexed_repository.name,
                        score=0.8,
                        confidence="high",
                        reasoning="命中能力节点",
                        matched_node_paths=["认证模块 > 登录"],
                    )
                ],
                router_version="v2",
                auto_selected=True,
            )
        ),
    )
    # 历史分量不打外部检索：置为不可得（adapter 对该分量本就容忍缺席）
    from services.process_runtime.blueprint_route_history import HistoryMatchResult

    monkeypatch.setattr(
        "services.process_runtime.blueprint_route.ascore_history_match",
        AsyncMock(return_value=HistoryMatchResult(unavailable_reason="test_disabled")),
    )

    response = client.post(
        "/api/mcp/tools/route_blueprint_repos/",
        {"requirement_text": "登录页改造", "ignore_pin": True, "top_k": 5},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert _ROUTING_TOP_LEVEL_KEYS <= set(body)
    assert body["router_version"] == "v2"
    candidate = body["candidates"][0]
    assert candidate["repository_id"] == str(indexed_repository.id)
    assert set(candidate["breakdown"]) == {"router_base", "charter_match", "history_match"}
    assert candidate["evidence"]["matched_node_paths"] == ["认证模块 > 登录"]
    assert InteractionRun.objects.filter(run_id=body["run_id"]).exists()
    assert RetrievalTrace.objects.filter(kind=RetrievalTrace.Kind.ROUTING).count() == 1


def test_route_blueprint_repos_requires_input(mcp_client: tuple[APIClient, str]) -> None:
    client, _plaintext = mcp_client
    response = client.post("/api/mcp/tools/route_blueprint_repos/", {}, format="json")
    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_params"


def test_generate_requirement_spec_provided_points(
    mcp_client: tuple[APIClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    monkeypatch.setattr(
        "services.process_runtime.blueprint_ambiguity_score.ascore_ambiguity",
        AsyncMock(
            return_value={
                "dimensions": {
                    d: {"score": 0.0, "reason": "清晰"}
                    for d in ("goal", "boundary", "constraint", "acceptance")
                },
                "questions": [],
            }
        ),
    )
    response = client.post(
        "/api/mcp/tools/generate_requirement_spec/",
        {
            "requirement_text": "修复登录闪退",
            "feature_points": [{"title": "登录闪退修复", "intent": "fix"}],
            "classify_intents": False,
        },
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "provided"
    points = body["requirement_spec"]["feature_points"]
    assert points[0]["title"] == "登录闪退修复"
    assert points[0]["intent"] == "fix"
    assert body["ambiguity"]["above_threshold"] is False
    assert InteractionRun.objects.filter(run_id=body["run_id"]).exists()


def test_start_and_get_repo_research_light_path(
    mcp_client: tuple[APIClient, str],
    repository,
) -> None:
    client, _plaintext = mcp_client
    started = client.post(
        "/api/mcp/tools/start_repo_research/",
        {
            "requirement_text": "登录页改造",
            "repositories": [{"repository_id": str(repository.id), "role": "indirect"}],
        },
        format="json",
    )
    assert started.status_code == 200
    body = started.json()
    assert body["synthesized"] == 1
    assert body["dispatched"] == 0
    assert body["tasks"]

    polled = client.post(
        "/api/mcp/tools/get_repo_research/",
        {"session_id": body["session_id"]},
        format="json",
    )
    assert polled.status_code == 200
    poll_body = polled.json()
    assert poll_body["all_terminal"] is True
    task = poll_body["tasks"][0]
    assert task["repository_id"] == str(repository.id)
    assert task["status"] == "done"
    assert task["research"]["fitness"]["verdict"] == "partial"

    missing = client.post(
        "/api/mcp/tools/get_repo_research/",
        {"session_id": str(uuid4())},
        format="json",
    )
    assert missing.status_code == 404


def test_apply_repo_association_bind_unbind_and_permission(
    mcp_client: tuple[APIClient, str],
    repository,
    user,
) -> None:
    from initiatives.models import BranchSource, Project, ProjectBranch, ProjectMember
    from projects.models import Space

    client, _plaintext = mcp_client
    space = Space.objects.create(name="S-apply")
    project = Project.objects.create(space=space, name="P-apply")
    ProjectMember.objects.create(project=project, user=user)

    bound = client.post(
        "/api/mcp/tools/apply_repo_association/",
        {"project_id": str(project.id), "bindings": [{"repository_id": str(repository.id)}]},
        format="json",
    )
    assert bound.status_code == 200
    body = bound.json()
    assert body["results"][0]["ok"] is True
    # branch_name 缺省取仓库默认分支
    assert body["results"][0]["branch_name"] == repository.default_branch
    assert ProjectBranch.objects.filter(
        project=project,
        repository=repository,
        branch_name=repository.default_branch,
        source=BranchSource.MANUAL,
    ).exists()

    unbound = client.post(
        "/api/mcp/tools/apply_repo_association/",
        {
            "project_id": str(project.id),
            "action": "unbind",
            "bindings": [{"repository_id": str(repository.id)}],
        },
        format="json",
    )
    assert unbound.status_code == 200
    assert unbound.json()["results"][0]["removed"] is True
    assert not ProjectBranch.objects.filter(project=project, repository=repository).exists()

    # 非项目成员整体 403（写恒守成员闸 fail-closed）
    stranger_project = Project.objects.create(space=space, name="P-noperm")
    denied = client.post(
        "/api/mcp/tools/apply_repo_association/",
        {
            "project_id": str(stranger_project.id),
            "bindings": [{"repository_id": str(repository.id)}],
        },
        format="json",
    )
    assert denied.status_code == 403
