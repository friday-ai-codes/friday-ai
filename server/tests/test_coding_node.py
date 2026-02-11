"""AICodingNode 单元测试。
覆盖 happy path（SubAgent 成功 -> MR 创建 -> completed）
和 error handling（缺少方案 -> failed、所有仓库编码失败 -> failed）。
"""
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from services.git_platform.models import MRCreateResult
from subagent.client import SubAgentResponse
from workflows.nodes.ai.coding import AICodingNode
from workflows.nodes.base import ExecutionContext, NodeResult
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_repo(repo_id: str | None = None, name: str = "test-repo") -> MagicMock:
 """Create a mock Repository object."""
 repo = MagicMock
 repo.id = uuid.UUID(repo_id) if repo_id else uuid.uuid4
 repo.name = name
 repo.git_url = "https://gitlab.example.com/test/repo.git"
 repo.git_platform = "gitlab"
 repo.default_branch = "main"
 repo.is_deleted = False
 credential = MagicMock
 credential.encrypted_token = "encrypted-token-123"
 repo.credential = credential
 return repo
def _make_context(
 input_data: dict[str, Any] | None = None,
 node_config: dict[str, Any] | None = None,
) -> ExecutionContext:
 """Create a minimal ExecutionContext for testing."""
 return ExecutionContext(
 execution_id="exec-test-001",
 node_id="node-coding-001",
 node_config=node_config or {
 "polling_interval": 0,
 "timeout_seconds": 10,
 "chat_id": "",
 },
 input_data=input_data or {},
 workflow_context={},
 previous_outputs={},
 trigger_data={"payload": {"work_item_id": "12345"}},
 workflow_execution=None,
 node_execution=None,
 )
def _make_plan_data(
 repo_id: str,
 task_count: int = 1,
 branch_name: str = "feat/xxxx-m12345-test",
) -> dict[str, Any]:
 """Create valid plan input data for the coding node."""
 execution_plan = [
 {
 "repository_id": repo_id,
 "name": f"Task {i + 1}",
 "description": f"Implement feature {i + 1}",
 "coding_instruction": f"Write code for feature {i + 1}",
 }
 for i in range(task_count)
 ]
 return {
 "plan": {
 "title": "Test Technical Plan",
 "branch_name": branch_name,
 "execution_plan": execution_plan,
 "global_context": "This is a test project.",
 }
 }
# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestAICodingNode:
 """AICodingNode 独立执行行为测试。"""
 async def test_execute_happy_path(self) -> None:
 """提供有效 plan，SubAgent + MR 均成功 -> status=completed。"""
 repo = _make_repo(repo_id="00000000-0000-0000-0000-000000000001")
 repo_id_str = str(repo.id)
 input_data = _make_plan_data(repo_id_str)
 context = _make_context(input_data=input_data)
 subagent_response = SubAgentResponse(
 task_id="task-001",
 status="completed",
 output={"files_changed": 3, "insertions": 50, "deletions": 10},
 )
 mr_result = MRCreateResult(
 success=True,
 mr_url="https://gitlab.example.com/test/repo/-/merge_requests/1",
 mr_id="1",
 has_conflicts=False,
 )
 node = AICodingNode
 with (
 patch.object(
 node, "_fetch_repositories", new_callable=AsyncMock,
 return_value={repo_id_str: repo},
 ),
 patch(
 "workflows.nodes.ai.coding.SubAgentClient"
 ) as MockClient,
 patch(
 "workflows.nodes.ai.coding.get_git_platform_client"
 ) as mock_git_factory,
 patch(
 "workflows.nodes.ai.coding.decrypt_value",
 return_value="decrypted-token",
 ),
 patch("asyncio.sleep", new_callable=AsyncMock),
 ):
 # SubAgent mock
 client_instance = MockClient.return_value
 client_instance.submit_task = AsyncMock(return_value="task-001")
 client_instance.get_task_status = AsyncMock(return_value=subagent_response)
 # Git platform mock
 mock_git_client = MagicMock
 mock_git_client.create_merge_request = AsyncMock(return_value=mr_result)
 mock_git_factory.return_value = mock_git_client
 result: NodeResult = await node.execute(context)
 assert result.status == "completed"
 assert result.next_handle == "default"
 assert "merge_requests" in result.output
 assert len(result.output["merge_requests"]) == 1
 assert result.output["merge_requests"][0]["mr_url"] == mr_result.mr_url
 assert "changes_summary" in result.output
 assert result.output["changes_summary"]["succeeded_repos"] == 1
 async def test_execute_missing_plan(self) -> None:
 """input_data 无 plan -> status=failed。"""
 context = _make_context(input_data={})
 node = AICodingNode
 result: NodeResult = await node.execute(context)
 assert result.status == "failed"
 assert "技术方案数据" in (result.error or "")
 assert result.next_handle == "error"
 async def test_execute_empty_execution_plan(self) -> None:
 """plan 中 execution_plan 为空列表 -> status=failed。"""
 input_data = {
 "plan": {
 "title": "Empty Plan",
 "branch_name": "feat/empty",
 "execution_plan":,
 }
 }
 context = _make_context(input_data=input_data)
 node = AICodingNode
 result: NodeResult = await node.execute(context)
 assert result.status == "failed"
 assert "execution_plan 为空" in (result.error or "")
 assert result.next_handle == "error"
 async def test_execute_subagent_failure(self) -> None:
 """所有仓库 SubAgent 编码失败 -> status=failed。"""
 repo = _make_repo(repo_id="00000000-0000-0000-0000-000000000002")
 repo_id_str = str(repo.id)
 input_data = _make_plan_data(repo_id_str)
 context = _make_context(input_data=input_data)
 subagent_error = SubAgentResponse(
 task_id="task-err",
 status="error",
 error="Container crashed",
 )
 node = AICodingNode
 with (
 patch.object(
 node, "_fetch_repositories", new_callable=AsyncMock,
 return_value={repo_id_str: repo},
 ),
 patch(
 "workflows.nodes.ai.coding.SubAgentClient"
 ) as MockClient,
 patch("asyncio.sleep", new_callable=AsyncMock),
 ):
 client_instance = MockClient.return_value
 client_instance.submit_task = AsyncMock(return_value="task-err")
 client_instance.get_task_status = AsyncMock(return_value=subagent_error)
 result: NodeResult = await node.execute(context)
 assert result.status == "failed"
 assert "所有仓库编码均失败" in (result.error or "")
 assert result.next_handle == "error"
 async def test_execute_partial_success(self) -> None:
 """两个仓库，一个成功一个失败 -> status=completed + failed_details。"""
 repo_a = _make_repo(repo_id="00000000-0000-0000-0000-00000000000a", name="repo-a")
 repo_b = _make_repo(repo_id="00000000-0000-0000-0000-00000000000b", name="repo-b")
 id_a = str(repo_a.id)
 id_b = str(repo_b.id)
 input_data = {
 "plan": {
 "title": "Partial Plan",
 "branch_name": "feat/partial",
 "execution_plan": [
 {"repository_id": id_a, "name": "Task A", "coding_instruction": "code A"},
 {"repository_id": id_b, "name": "Task B", "coding_instruction": "code B"},
 ],
 "global_context": "",
 }
 }
 context = _make_context(input_data=input_data)
 success_response = SubAgentResponse(
 task_id="task-a",
 status="completed",
 output={"files_changed": 2, "insertions": 20, "deletions": 5},
 )
 error_response = SubAgentResponse(
 task_id="task-b",
 status="error",
 error="Build failed",
 )
 mr_result = MRCreateResult(
 success=True, mr_url="https://example.com/mr/1", mr_id="1",
 )
 node = AICodingNode
 # Track which repo is being submitted to return different responses
 submit_call_count = 0
 async def mock_submit(request: Any) -> str:
 nonlocal submit_call_count
 submit_call_count += 1
 return f"task-{submit_call_count}"
 status_responses = {
 "task-1": success_response,
 "task-2": error_response,
 }
 async def mock_get_status(task_id: str) -> SubAgentResponse:
 return status_responses[task_id]
 with (
 patch.object(
 node, "_fetch_repositories", new_callable=AsyncMock,
 return_value={id_a: repo_a, id_b: repo_b},
 ),
 patch("workflows.nodes.ai.coding.SubAgentClient") as MockClient,
 patch("workflows.nodes.ai.coding.get_git_platform_client") as mock_git_factory,
 patch("workflows.nodes.ai.coding.decrypt_value", return_value="token"),
 patch("asyncio.sleep", new_callable=AsyncMock),
 ):
 client_instance = MockClient.return_value
 client_instance.submit_task = AsyncMock(side_effect=mock_submit)
 client_instance.get_task_status = AsyncMock(side_effect=mock_get_status)
 mock_git_client = MagicMock
 mock_git_client.create_merge_request = AsyncMock(return_value=mr_result)
 mock_git_factory.return_value = mock_git_client
 result: NodeResult = await node.execute(context)
 assert result.status == "completed"
 assert result.output["changes_summary"]["succeeded_repos"] >= 1
 assert len(result.output["failed_details"]) >= 1
 def test_group_by_repository(self) -> None:
 """按 repository_id 正确分组任务。"""
 node = AICodingNode
 execution_plan = [
 {"repository_id": "repo-1", "name": "Task 1"},
 {"repository_id": "repo-2", "name": "Task 2"},
 {"repository_id": "repo-1", "name": "Task 3"},
 {"repository_id": "repo-2", "name": "Task 4"},
 {"repository_id": "repo-1", "name": "Task 5"},
 {"name": "Task without repo"}, # no repository_id
 ]
 groups = node._group_by_repository(execution_plan)
 assert "repo-1" in groups
 assert "repo-2" in groups
 assert len(groups["repo-1"]) == 3
 assert len(groups["repo-2"]) == 2
 # 没有 repository_id 的任务不应出现
 assert "" not in groups
 def test_build_output_structure(self) -> None:
 """_build_output 返回包含所有必要字段的输出。"""
 node = AICodingNode
 mr_results = [
 {
 "repository_id": "repo-1",
 "repository_name": "my-repo",
 "mr_url": "https://example.com/mr/1",
 "mr_id": "1",
 "tasks_completed": ["Task A", "Task B"],
 "files_changed": 5,
 "insertions": 100,
 "deletions": 20,
 }
 ]
 failed_repos = [
 {
 "repository_id": "repo-2",
 "repository_name": "failed-repo",
 "error": "Build failed",
 }
 ]
 output = node._build_output(
 mr_results=mr_results,
 failed_repos=failed_repos,
 branch_name="feat/test",
 base_branch="main",
 )
 # 验证顶层键
 assert "merge_requests" in output
 assert "branches" in output
 assert "changes_summary" in output
 assert "failed_details" in output
 # merge_requests 结构
 assert len(output["merge_requests"]) == 1
 mr = output["merge_requests"][0]
 assert mr["repository_id"] == "repo-1"
 assert mr["mr_url"] == "https://example.com/mr/1"
 assert mr["files_changed"] == 5
 assert mr["insertions"] == 100
 assert mr["deletions"] == 20
 # branches 结构
 assert output["branches"]["branch_name"] == "feat/test"
 assert output["branches"]["base_branch"] == "main"
 # changes_summary 结构
 summary = output["changes_summary"]
 assert summary["total_repos"] == 2
 assert summary["succeeded_repos"] == 1
 assert summary["failed_repos"] == 1
 assert summary["total_files_changed"] == 5
 assert summary["total_insertions"] == 100
 assert summary["total_deletions"] == 20
 # failed_details
 assert len(output["failed_details"]) == 1
 assert output["failed_details"][0]["repository_name"] == "failed-repo"
