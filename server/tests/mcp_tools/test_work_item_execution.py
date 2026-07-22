from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from rest_framework.test import APIClient

from interactions.ledger import create_interaction_run
from interactions.models import ToolCallRecord
from mcp_tools.models import (
    McpCodingExecutionTrace,
    McpWorkItemContext,
    McpWorkItemRepoTask,
    McpWorkItemTechnicalPlan,
)
from repositories.models import FileIndex, IndexStatus, Repository
from runners.models import hash_token

pytestmark = pytest.mark.django_db


class _FakeDocClient:
    appended: list[dict[str, str]] = []

    async def append_markdown(self, document_id: str, content: str) -> dict[str, Any]:
        self.appended.append({"document_id": document_id, "content": content})
        return {"document_id": document_id, "appended_blocks": 3}


class _FailingDocClient:
    async def append_markdown(self, document_id: str, content: str) -> dict[str, Any]:
        raise RuntimeError("feishu doc append unavailable")


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
        token_fingerprint=hash_token("work-item-execution-context"),
        source="mcp",
    )
    return McpWorkItemContext.objects.create(
        run=run,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="story",
        work_item_id=88,
        name="多仓登录链路改造",
        status=McpWorkItemContext.Status.COMPLETED,
        work_item_status="doing",
        description="需要同时修改 web 和 server。",
        context={
            "work_item": {
                "source": {
                    "project_key": project.feishu_project_key,
                    "work_item_type": "story",
                    "work_item_id": 88,
                }
            }
        },
    )


def _technical_plan(project, repos: list[Repository]) -> McpWorkItemTechnicalPlan:
    run = create_interaction_run(
        token_fingerprint=hash_token("work-item-execution-plan"),
        source="mcp",
    )
    context = _context(project)
    matrix = []
    for index, repo in enumerate(repos, start=1):
        matrix.append(
            {
                "order": index,
                "repository_id": str(repo.id),
                "repository_name": repo.name,
                "base_branch": repo.default_branch,
                "planned_branch": f"feat/feishu-story-88-{repo.name}",
                "change_goal": f"修改 {repo.name} 登录链路",
                "candidate_files": [f"src/{repo.name}.py"],
                "steps": ["修改代码", "补测试"],
                "test_strategy": ["运行相关测试"],
                "risks": ["跨仓发布顺序"],
                "rollback": "revert commit",
            }
        )
    return McpWorkItemTechnicalPlan.objects.create(
        run=run,
        context=context,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="story",
        work_item_id=88,
        title="多仓登录链路改造技术方案",
        status=McpWorkItemTechnicalPlan.Status.COMPLETED,
        plan_body={"repository_task_matrix": matrix},
        markdown="# 多仓登录链路改造技术方案\n",
        repository_tasks=matrix,
        feishu_document_id="doxcnPlan",
        feishu_document_url="https://feishu.cn/docx/doxcnPlan",
    )


def _second_repo(project) -> Repository:
    repo = Repository.objects.create(
        name="server-api",
        git_url="https://example.com/server-api.git",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )
    project.repositories.add(repo)
    FileIndex.objects.create(
        repository=repo,
        file_path="src/server-api.py",
        file_hash="hash-server-api",
    )
    return repo


def test_create_work_item_repo_tasks_from_technical_plan(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client
    plan = _technical_plan(project, [indexed_repository])

    response = client.post(
        "/api/mcp/tools/create_work_item_repo_tasks/",
        {"technical_plan_id": str(plan.id)},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["tasks"][0]["technical_plan_id"] == str(plan.id)
    assert body["tasks"][0]["status"] == "pending"

    task = McpWorkItemRepoTask.objects.get(id=body["tasks"][0]["task_id"])
    assert task.tool_call_id is not None
    assert task.branch_name.startswith("feat/feishu-story-88")
    assert ToolCallRecord.objects.filter(tool_name="create_work_item_repo_tasks").count() == 1


def test_create_work_item_repo_tasks_preserves_completed_task_state(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client
    plan = _technical_plan(project, [indexed_repository])

    first_response = client.post(
        "/api/mcp/tools/create_work_item_repo_tasks/",
        {"technical_plan_id": str(plan.id)},
        format="json",
    )
    assert first_response.status_code == 200
    task = McpWorkItemRepoTask.objects.get(
        id=first_response.json()["tasks"][0]["task_id"],
    )
    task.status = McpWorkItemRepoTask.Status.COMPLETED
    task.branch_name = "feat/already-merged"
    task.mr_url = "https://example.com/mr/done"
    task.result = {"mr": {"success": True}}
    task.recovery_state = {"retryable": False, "stage": "completed"}
    task.save(update_fields=["status", "branch_name", "mr_url", "result", "recovery_state"])

    matrix = list(plan.repository_tasks)
    matrix[0] = {**matrix[0], "planned_branch": "feat/changed-after-completion"}
    plan.repository_tasks = matrix
    plan.save(update_fields=["repository_tasks"])

    second_response = client.post(
        "/api/mcp/tools/create_work_item_repo_tasks/",
        {"technical_plan_id": str(plan.id)},
        format="json",
    )

    assert second_response.status_code == 200
    body = second_response.json()
    assert body["tasks"][0]["status"] == "completed"
    assert body["tasks"][0]["branch_name"] == "feat/already-merged"
    assert body["tasks"][0]["mr_url"] == "https://example.com/mr/done"

    task.refresh_from_db()
    assert task.status == McpWorkItemRepoTask.Status.COMPLETED
    assert task.branch_name == "feat/already-merged"
    assert task.recovery_state == {"retryable": False, "stage": "completed"}


def test_execute_work_item_repo_tasks_skips_completed_task_with_mr(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    plan = _technical_plan(project, [indexed_repository])
    create_response = client.post(
        "/api/mcp/tools/create_work_item_repo_tasks/",
        {"technical_plan_id": str(plan.id)},
        format="json",
    )
    assert create_response.status_code == 200
    task = McpWorkItemRepoTask.objects.get(id=create_response.json()["tasks"][0]["task_id"])
    task.status = McpWorkItemRepoTask.Status.COMPLETED
    task.mr_url = "https://example.com/mr/done"
    task.result = {"mr": {"success": True}}
    task.recovery_state = {"retryable": False, "stage": "completed"}
    task.save(update_fields=["status", "mr_url", "result", "recovery_state"])

    async def _unexpected_call(*args, **kwargs):
        raise AssertionError("completed task should not be dispatched or create another MR")

    monkeypatch.setattr("mcp_tools.work_item_execution_service.dispatch_execution", _unexpected_call)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.summarize_branch", _unexpected_call)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.create_merge_request", _unexpected_call)

    response = client.post(
        "/api/mcp/tools/execute_work_item_repo_tasks/",
        {
            "technical_plan_id": str(plan.id),
            "create_missing": True,
            "dispatch": True,
            "create_merge_requests": True,
            "write_back": False,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["summary"]["completed"] == 1
    assert body["tasks"][0]["mr_url"] == "https://example.com/mr/done"


def test_execute_work_item_repo_tasks_records_partial_multi_repo_results(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    repo_b = _second_repo(project)
    plan = _technical_plan(project, [indexed_repository, repo_b])
    _FakeDocClient.appended.clear()
    _FakeFeishuClient.comments.clear()

    async def _dispatch_execution(
        *,
        trace: McpCodingExecutionTrace,
        plan,
        version,
        branch_name: str,
        target_branch: str,
        timeout_seconds: int,
    ):
        trace.status = McpCodingExecutionTrace.Status.COMPLETED
        trace.branch_name = branch_name
        trace.target_branch = target_branch
        trace.commit_sha = "a" * 40
        trace.push_result = {"pushed": True}
        await trace.asave(
            update_fields=[
                "status",
                "branch_name",
                "target_branch",
                "commit_sha",
                "push_result",
                "updated_at",
            ]
        )

    async def _refresh(trace: McpCodingExecutionTrace) -> McpCodingExecutionTrace:
        return trace

    async def _summary(
        *,
        repository: Repository,
        source_branch: str,
        target_branch: str,
        max_files: int,
        trace: McpCodingExecutionTrace | None = None,
    ) -> dict[str, Any]:
        return {
            "repository_id": str(repository.id),
            "source_branch": source_branch,
            "target_branch": target_branch,
            "files": [{"path": f"src/{repository.name}.py"}],
            "mr_draft": {
                "title": f"{repository.name} MR",
                "description": "执行结果",
            },
        }

    async def _mr(
        *,
        repository: Repository,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewer_usernames: list[str],
        remove_source_branch: bool,
        trace: McpCodingExecutionTrace | None = None,
    ) -> dict[str, Any]:
        if repository.id == repo_b.id:
            return {
                "success": False,
                "error": "branch already has an open MR",
                "source_branch": source_branch,
                "target_branch": target_branch,
            }
        return {
            "success": True,
            "mr_id": "1",
            "mr_url": "https://example.com/mr/1",
            "source_branch": source_branch,
            "target_branch": target_branch,
        }

    async def _doc_client(_project):
        return _FakeDocClient()

    monkeypatch.setattr("mcp_tools.work_item_execution_service.dispatch_execution", _dispatch_execution)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.refresh_execution_trace", _refresh)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.summarize_branch", _summary)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.create_merge_request", _mr)
    # LOOP-01：飞书客户端调用已收敛到公共回写层，patch 点随迁（断言不变）。
    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_doc_client_for_project",
        _doc_client,
    )
    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_client_for_project",
        lambda _project: _FakeFeishuClient(),
    )

    response = client.post(
        "/api/mcp/tools/execute_work_item_repo_tasks/",
        {
            "technical_plan_id": str(plan.id),
            "create_missing": True,
            "dispatch": True,
            "create_merge_requests": True,
            "write_back": True,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["summary"] == {
        "total": 2,
        "completed": 1,
        "partial": 1,
        "failed": 0,
        "running": 0,
    }
    assert body["document_update"]["status"] == "appended"
    assert body["comment"]["status"] == "written"
    assert _FakeDocClient.appended[0]["document_id"] == "doxcnPlan"
    assert "https://example.com/mr/1" in _FakeFeishuClient.comments[0]["content"]

    tasks = list(McpWorkItemRepoTask.objects.order_by("order"))
    assert tasks[0].status == McpWorkItemRepoTask.Status.COMPLETED
    assert tasks[0].mr_url == "https://example.com/mr/1"
    assert tasks[0].execution_trace_id is not None
    assert tasks[1].status == McpWorkItemRepoTask.Status.PARTIAL
    assert tasks[1].recovery_state["stage"] == "merge_request"
    assert tasks[1].error == "branch already has an open MR"

    plan.refresh_from_db()
    assert "execution_results" in plan.plan_body
    assert "执行结果" in plan.markdown


def test_execute_work_item_repo_tasks_reports_partial_when_feishu_writeback_fails(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    plan = _technical_plan(project, [indexed_repository])
    _FakeFeishuClient.comments.clear()

    async def _dispatch_execution(
        *,
        trace: McpCodingExecutionTrace,
        plan,
        version,
        branch_name: str,
        target_branch: str,
        timeout_seconds: int,
    ):
        trace.status = McpCodingExecutionTrace.Status.COMPLETED
        trace.branch_name = branch_name
        trace.target_branch = target_branch
        trace.commit_sha = "b" * 40
        await trace.asave(
            update_fields=["status", "branch_name", "target_branch", "commit_sha", "updated_at"]
        )

    async def _refresh(trace: McpCodingExecutionTrace) -> McpCodingExecutionTrace:
        return trace

    async def _summary(
        *,
        repository: Repository,
        source_branch: str,
        target_branch: str,
        max_files: int,
        trace: McpCodingExecutionTrace | None = None,
    ) -> dict[str, Any]:
        return {
            "repository_id": str(repository.id),
            "source_branch": source_branch,
            "target_branch": target_branch,
            "files": [{"path": f"src/{repository.name}.py"}],
            "mr_draft": {"title": "MR", "description": "执行结果"},
        }

    async def _mr(
        *,
        repository: Repository,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewer_usernames: list[str],
        remove_source_branch: bool,
        trace: McpCodingExecutionTrace | None = None,
    ) -> dict[str, Any]:
        return {
            "success": True,
            "mr_id": "1",
            "mr_url": "https://example.com/mr/1",
            "source_branch": source_branch,
            "target_branch": target_branch,
        }

    async def _doc_client(_project):
        return _FailingDocClient()

    monkeypatch.setattr("mcp_tools.work_item_execution_service.dispatch_execution", _dispatch_execution)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.refresh_execution_trace", _refresh)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.summarize_branch", _summary)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.create_merge_request", _mr)
    # LOOP-01：飞书客户端调用已收敛到公共回写层，patch 点随迁（断言不变）。
    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_doc_client_for_project",
        _doc_client,
    )
    monkeypatch.setattr(
        "delivery.services.coding_completion.create_feishu_client_for_project",
        lambda _project: _FakeFeishuClient(),
    )

    response = client.post(
        "/api/mcp/tools/execute_work_item_repo_tasks/",
        {
            "technical_plan_id": str(plan.id),
            "create_missing": True,
            "dispatch": True,
            "create_merge_requests": True,
            "write_back": True,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["summary"]["completed"] == 1
    assert body["document_update"]["status"] == "error"
    assert body["comment"]["status"] == "written"
    assert body["tasks"][0]["status"] == "completed"

    plan.refresh_from_db()
    assert plan.status == McpWorkItemTechnicalPlan.Status.PARTIAL
    assert plan.error_stage == "execution_writeback"


def test_writeback_delegates_to_common_service_and_keeps_partial_flip(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回写路径经公共 service；error 时 MCP 层 PARTIAL + retry_state 翻转仍在（LOOP-01）。"""
    from delivery.services.coding_completion import CompletionWritebackService

    client, _plaintext = mcp_client
    plan = _technical_plan(project, [indexed_repository])
    create_response = client.post(
        "/api/mcp/tools/create_work_item_repo_tasks/",
        {"technical_plan_id": str(plan.id)},
        format="json",
    )
    assert create_response.status_code == 200
    task = McpWorkItemRepoTask.objects.get(id=create_response.json()["tasks"][0]["task_id"])
    task.status = McpWorkItemRepoTask.Status.COMPLETED
    task.mr_url = "https://example.com/mr/done"
    task.result = {"mr": {"success": True}}
    task.recovery_state = {"retryable": False, "stage": "completed"}
    task.save(update_fields=["status", "mr_url", "result", "recovery_state"])

    async def _unexpected_call(*args, **kwargs):
        raise AssertionError("completed task should not be dispatched or create another MR")

    monkeypatch.setattr("mcp_tools.work_item_execution_service.dispatch_execution", _unexpected_call)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.summarize_branch", _unexpected_call)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.create_merge_request", _unexpected_call)

    awrite_back_calls: list[dict[str, Any]] = []

    async def _fake_awrite_back(self, **kwargs):
        awrite_back_calls.append(kwargs)
        return {"status": "error", "error": "boom"}, {"status": "skipped"}

    monkeypatch.setattr(CompletionWritebackService, "awrite_back", _fake_awrite_back)

    response = client.post(
        "/api/mcp/tools/execute_work_item_repo_tasks/",
        {
            "technical_plan_id": str(plan.id),
            "create_missing": True,
            "dispatch": True,
            "create_merge_requests": True,
            "write_back": True,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document_update"] == {"status": "error", "error": "boom"}
    assert body["comment"] == {"status": "skipped"}

    # 回写确实经公共 service（入参三元组透传）。
    assert len(awrite_back_calls) == 1
    assert awrite_back_calls[0]["feishu_project_key"] == plan.feishu_project_key
    assert awrite_back_calls[0]["work_item_id"] == 88
    assert awrite_back_calls[0]["work_item_type"] == "story"

    # MCP 层专属状态翻转仍在：PARTIAL + retry_state failed_stage。
    plan.refresh_from_db()
    assert plan.status == McpWorkItemTechnicalPlan.Status.PARTIAL
    assert plan.retry_state["retryable"] is True
    assert plan.retry_state["failed_stage"] == "execution_writeback"
    assert plan.error_stage == "execution_writeback"
    assert plan.error == "boom"


# ---------------------------------------------------------------------------
# LOOP-03（101-03）：learning case 提炼锚点
# ---------------------------------------------------------------------------


def _completed_dispatch_with_session(repo_failed_id=None):
    """构造 dispatch fake：目标仓 COMPLETED 且挂 SubAgentSession；repo_failed_id 仓 FAILED。"""

    async def _dispatch_execution(
        *,
        trace: McpCodingExecutionTrace,
        plan,
        version,
        branch_name: str,
        target_branch: str,
        timeout_seconds: int,
    ):
        if repo_failed_id is not None and trace.repository_id == repo_failed_id:
            trace.status = McpCodingExecutionTrace.Status.FAILED
            trace.error = "container exploded"
            await trace.asave(update_fields=["status", "error", "updated_at"])
            return

        from agents.models import AgentSession
        from subagent.models import SubAgentSession

        main = await AgentSession.objects.acreate(metadata={"test_learning_case": True})
        sub = await SubAgentSession.objects.acreate(
            session_id=f"sub-mcp-{trace.repository_id.hex[:8]}",
            main_session=main,
            repo_url="https://example.com/repo.git",
            task_type="coding",
            status=SubAgentSession.Status.COMPLETED,
        )
        trace.status = McpCodingExecutionTrace.Status.COMPLETED
        trace.branch_name = branch_name
        trace.target_branch = target_branch
        trace.commit_sha = "c" * 40
        trace.subagent_session = sub
        await trace.asave(
            update_fields=[
                "status",
                "branch_name",
                "target_branch",
                "commit_sha",
                "subagent_session",
                "updated_at",
            ]
        )

    return _dispatch_execution


def _patch_execution_io(monkeypatch: pytest.MonkeyPatch, dispatch) -> None:
    async def _refresh(trace: McpCodingExecutionTrace) -> McpCodingExecutionTrace:
        return trace

    async def _summary(
        *,
        repository: Repository,
        source_branch: str,
        target_branch: str,
        max_files: int,
        trace: McpCodingExecutionTrace | None = None,
    ) -> dict[str, Any]:
        return {
            "repository_id": str(repository.id),
            "source_branch": source_branch,
            "target_branch": target_branch,
            "files": [{"path": f"src/{repository.name}.py"}],
            "mr_draft": {"title": f"{repository.name} MR", "description": "执行结果"},
        }

    async def _mr(
        *,
        repository: Repository,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewer_usernames: list[str],
        remove_source_branch: bool,
        trace: McpCodingExecutionTrace | None = None,
    ) -> dict[str, Any]:
        return {
            "success": True,
            "mr_id": "1",
            "mr_url": "https://example.com/mr/1",
            "source_branch": source_branch,
            "target_branch": target_branch,
        }

    monkeypatch.setattr("mcp_tools.work_item_execution_service.dispatch_execution", dispatch)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.refresh_execution_trace", _refresh)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.summarize_branch", _summary)
    monkeypatch.setattr("mcp_tools.work_item_execution_service.create_merge_request", _mr)


def test_execute_tasks_schedules_learning_case_extraction(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COMPLETED（含 mr + trace.subagent_session）→ 每仓一次调度且入参正确；FAILED 仓不调度。"""
    client, _plaintext = mcp_client
    repo_b = _second_repo(project)
    plan = _technical_plan(project, [indexed_repository, repo_b])
    _patch_execution_io(
        monkeypatch, _completed_dispatch_with_session(repo_failed_id=repo_b.id)
    )

    scheduled: list[dict[str, Any]] = []

    def _fake_run_in_background(factory, *, name=None, initiated_by_user_id=None):
        scheduled.append(
            {"factory": factory, "name": name, "initiated_by_user_id": initiated_by_user_id}
        )
        return MagicMock()

    monkeypatch.setattr("services.background_runner.run_in_background", _fake_run_in_background)

    extract_calls: list[tuple[str, dict[str, Any]]] = []

    async def _fake_extract(sid: str, **kwargs: Any) -> None:
        extract_calls.append((sid, kwargs))

    monkeypatch.setattr("mcp_tools.learning_case_extraction.aextract_for_session", _fake_extract)

    response = client.post(
        "/api/mcp/tools/execute_work_item_repo_tasks/",
        {
            "technical_plan_id": str(plan.id),
            "create_missing": True,
            "dispatch": True,
            "create_merge_requests": True,
            "write_back": False,
        },
        format="json",
    )

    assert response.status_code == 200
    # 仅 COMPLETED 仓调度（FAILED 仓不调度）。
    assert len(scheduled) == 1
    expected_sid = f"sub-mcp-{indexed_repository.id.hex[:8]}"
    assert scheduled[0]["name"] == f"learning-case-{expected_sid}"

    # 执行 factory 验证提炼入参（session_id / 三元组 / pr_url 透传）。
    asyncio.run(scheduled[0]["factory"]())
    assert len(extract_calls) == 1
    sid, kwargs = extract_calls[0]
    assert sid == expected_sid
    assert kwargs["requirement_text"] == plan.title
    assert kwargs["work_item_type"] == "story"
    assert kwargs["work_item_id"] == 88
    assert kwargs["pr_url"] == "https://example.com/mr/1"


def test_execute_tasks_extraction_skipped_without_execution_trace(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """COMPLETED 但无 execution_trace（存量已完成任务）→ 不调度提炼。"""
    client, _plaintext = mcp_client
    plan = _technical_plan(project, [indexed_repository])
    create_response = client.post(
        "/api/mcp/tools/create_work_item_repo_tasks/",
        {"technical_plan_id": str(plan.id)},
        format="json",
    )
    assert create_response.status_code == 200
    task = McpWorkItemRepoTask.objects.get(id=create_response.json()["tasks"][0]["task_id"])
    task.status = McpWorkItemRepoTask.Status.COMPLETED
    task.mr_url = "https://example.com/mr/done"
    task.result = {"mr": {"success": True}}
    task.recovery_state = {"retryable": False, "stage": "completed"}
    task.save(update_fields=["status", "mr_url", "result", "recovery_state"])

    scheduled: list[Any] = []
    monkeypatch.setattr(
        "services.background_runner.run_in_background",
        lambda *args, **kwargs: scheduled.append(args) or MagicMock(),
    )

    response = client.post(
        "/api/mcp/tools/execute_work_item_repo_tasks/",
        {
            "technical_plan_id": str(plan.id),
            "create_missing": True,
            "dispatch": True,
            "create_merge_requests": True,
            "write_back": False,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert scheduled == []


def test_execute_tasks_extraction_failure_does_not_affect_result(
    mcp_client: tuple[APIClient, str],
    project,
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """调度块抛异常（run_in_background raise）→ 不影响 execute 返回值（fail-soft）。"""
    client, _plaintext = mcp_client
    plan = _technical_plan(project, [indexed_repository])
    _patch_execution_io(monkeypatch, _completed_dispatch_with_session())

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("background runner down")

    monkeypatch.setattr("services.background_runner.run_in_background", _boom)

    response = client.post(
        "/api/mcp/tools/execute_work_item_repo_tasks/",
        {
            "technical_plan_id": str(plan.id),
            "create_missing": True,
            "dispatch": True,
            "create_merge_requests": True,
            "write_back": False,
        },
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["summary"]["completed"] == 1


def test_execution_results_markdown_delegates_to_common_renderer(
    indexed_repository,
) -> None:
    """markdown 渲染委托公共层后模板不漂移：标题 + 表头 + 反引号行格式。"""
    from mcp_tools.work_item_execution_service import _execution_results_markdown

    task = McpWorkItemRepoTask(
        repository=indexed_repository,
        status=McpWorkItemRepoTask.Status.COMPLETED,
        branch_name="feat/login",
        commit_sha="abc123",
        mr_url="https://example.com/mr/1",
        error="",
    )
    markdown = _execution_results_markdown([task])

    assert markdown.startswith("## 执行结果\n")
    assert "| 仓库 | 状态 | 分支 | Commit | PR/MR | 错误 |" in markdown
    assert "|---|---|---|---|---|---|" in markdown
    assert "`feat/login`" in markdown
    assert "`abc123`" in markdown
    assert markdown.endswith("|\n")
