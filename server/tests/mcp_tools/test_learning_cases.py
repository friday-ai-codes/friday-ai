from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from interactions.ledger import create_interaction_run
from mcp_tools.models import (
    McpLearningCase,
    McpWorkItemContext,
    McpWorkItemRepoTask,
    McpWorkItemTechnicalPlan,
)
from runners.models import hash_token

pytestmark = pytest.mark.django_db


def _context(project, *, name: str = "登录超时 Bug") -> McpWorkItemContext:
    run = create_interaction_run(
        token_fingerprint=hash_token(f"learning-context-{name}"),
        source="mcp",
    )
    return McpWorkItemContext.objects.create(
        run=run,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="bug",
        work_item_id=99,
        name=name,
        status=McpWorkItemContext.Status.COMPLETED,
        work_item_status="done",
        description="登录超时后错误提示不清晰，需要修复 token 刷新边界。",
        documents=[
            {
                "document_id": "doxcnLoginBug",
                "status": "ok",
                "content": "登录超时后前端显示空白。",
            }
        ],
        context={
            "work_item": {
                "source": {
                    "project_key": project.feishu_project_key,
                    "work_item_type": "bug",
                    "work_item_id": 99,
                }
            }
        },
    )


def _technical_plan(project, indexed_repository) -> McpWorkItemTechnicalPlan:
    run = create_interaction_run(
        token_fingerprint=hash_token("learning-plan"),
        source="mcp",
    )
    context = _context(project)
    task_body = {
        "order": 1,
        "repository_id": str(indexed_repository.id),
        "repository_name": indexed_repository.name,
        "base_branch": indexed_repository.default_branch,
        "planned_branch": "feat/feishu-bug-99-login-timeout",
        "change_goal": "修复登录超时提示和 token 刷新边界",
        "candidate_files": ["src/auth/session.py", "tests/test_session.py"],
        "steps": ["修复 session 判断", "补充回归测试"],
        "test_strategy": ["pytest tests/test_session.py -q"],
        "risks": ["登录态兼容性"],
        "rollback": "revert commit",
    }
    plan = McpWorkItemTechnicalPlan.objects.create(
        run=run,
        context=context,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="bug",
        work_item_id=99,
        title="登录超时 Bug 技术方案",
        status=McpWorkItemTechnicalPlan.Status.COMPLETED,
        plan_body={"repository_task_matrix": [task_body]},
        markdown="# 登录超时 Bug 技术方案\n",
        repository_tasks=[task_body],
        feishu_document_id="doxcnLoginPlan",
        feishu_document_url="https://feishu.cn/docx/doxcnLoginPlan",
    )
    McpWorkItemRepoTask.objects.create(
        run=run,
        technical_plan=plan,
        repository=indexed_repository,
        order=1,
        status=McpWorkItemRepoTask.Status.COMPLETED,
        branch_name="feat/feishu-bug-99-login-timeout",
        target_branch=indexed_repository.default_branch,
        task_body=task_body,
        commit_sha="b" * 40,
        mr_url="https://example.com/mr/login-timeout",
        result={"tests": ["pytest tests/test_session.py -q"]},
        recovery_state={"retryable": False},
    )
    return plan


def test_create_and_search_learning_case_from_technical_plan(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client
    plan = _technical_plan(project, indexed_repository)

    create_response = client.post(
        "/api/mcp/tools/create_learning_case/",
        {
            "technical_plan_id": str(plan.id),
            "outcome": "merged",
            "root_cause": "session token 过期边界判断遗漏",
            "solution_notes": "统一刷新 token 后再显示超时提示。",
            "tests": ["pytest tests/test_session.py -q"],
        },
        format="json",
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["case"]["outcome"] == "merged"
    assert "src/auth/session.py" in created["case"]["files"]
    assert McpLearningCase.objects.get(id=created["learning_case_id"]).tool_call_id is not None

    search_response = client.post(
        "/api/mcp/tools/search_learning_cases/",
        {
            "query": "登录超时 token 刷新",
            "work_item_type": "bug",
            "repo_hints": [indexed_repository.name],
            "file_hints": ["src/auth/session.py"],
        },
        format="json",
    )

    assert search_response.status_code == 200
    body = search_response.json()
    assert body["total"] == 1
    assert body["results"][0]["case_id"] == created["learning_case_id"]
    assert body["results"][0]["score"] > 0


def test_create_feishu_technical_plan_auto_includes_similar_learning_case(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    plan = _technical_plan(project, indexed_repository)
    client.post(
        "/api/mcp/tools/create_learning_case/",
        {
            "technical_plan_id": str(plan.id),
            "outcome": "merged",
            "root_cause": "session token 过期边界判断遗漏",
            "solution_notes": "统一刷新 token 后再显示超时提示。",
        },
        format="json",
    )
    new_context = _context(project, name="登录超时相似 Bug")

    # UNIFY-03：方案生成 delegate 到统一编排——monkeypatch delegate 返回 DONE（确定性，不触发
    # 真实编排）；学习案例自动召回（search_learning_cases）独立于 delegate，落 evidence + artifact。
    from mcp_tools.orchestration_delegate import DelegateResult

    async def _fake_delegate(**_kwargs: object) -> DelegateResult:
        return DelegateResult(
            session=type("S", (), {"id": "00000000-0000-0000-0000-000000000001"})(),
            status="completed",
            content={
                "title": "登录超时相似 Bug 技术方案",
                "summary": "复用既有 token 刷新边界修复经验。",
                "execution_plan": [
                    {
                        "id": "t1",
                        "name": "修复刷新边界",
                        "repository_id": str(indexed_repository.id),
                        "repository_name": indexed_repository.name,
                        "branch_strategy": "feature",
                    }
                ],
            },
            plan_version_id="00000000-0000-0000-0000-000000000002",
            markdown="**登录超时相似 Bug 技术方案**",
        )

    monkeypatch.setattr(
        "mcp_tools.technical_plan_service.delegate_plan_orchestration", _fake_delegate
    )

    response = client.post(
        "/api/mcp/tools/create_feishu_technical_plan/",
        {
            "context_id": str(new_context.id),
            "repository_ids": [str(indexed_repository.id)],
            "context_chunks": [
                {
                    "chunk_id": "chunk-login",
                    "repository_id": str(indexed_repository.id),
                    "file_path": "src/auth/session.py",
                    "content": "def refresh_session(): ...",
                }
            ],
            "create_document": False,
            "write_comment": False,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    # 相似学习案例经召回落 evidence（learning_case 源），不再内联 canonical plan content。
    learning_evidence = [item for item in body["evidence"] if item.get("source") == "learning_case"]
    assert learning_evidence
    assert learning_evidence[0]["title"] == "登录超时 Bug 技术方案"
