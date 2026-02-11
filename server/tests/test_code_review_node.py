"""AICodeReviewNode 单元测试。
覆盖 happy path（diff 获取成功 -> Agent 审查 -> 结构化报告）
和 error handling（缺少 coding_result -> failed、空 merge_requests -> failed）。
"""
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from agents.core.result import AgentResult
from services.git_platform.models import MRDiffFile, MRDiffResult
from workflows.nodes.ai.code_review import (
 AICodeReviewNode,
 _count_issues,
 _extract_json_from_text,
)
from workflows.nodes.base import ExecutionContext, NodeResult
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_context(
 input_data: dict[str, Any] | None = None,
 node_config: dict[str, Any] | None = None,
) -> ExecutionContext:
 """Create a minimal ExecutionContext for testing."""
 return ExecutionContext(
 execution_id="exec-review-001",
 node_id="node-review-001",
 node_config=node_config or {
 "model": "claude-sonnet-4-20250514",
 "chat_id": "",
 "max_iterations": 5,
 },
 input_data=input_data or {},
 workflow_context={},
 previous_outputs={},
 trigger_data={},
 workflow_execution=None,
 node_execution=None,
 )
def _make_review_report(
 approved: bool = True,
 repository: str = "test-repo",
) -> dict[str, Any]:
 """Create a sample review report JSON for Agent output."""
 issues: list[dict[str, Any]] =
 if not approved:
 issues.append({
 "severity": "critical",
 "description": "SQL injection vulnerability",
 "file": "src/db.py",
 "line": "42",
 "suggestion": "Use parameterized queries",
 })
 return {
 "repository": repository,
 "summary": "Code looks good" if approved else "Critical issues found",
 "dimensions": {
 "code_quality": {
 "issues": [
 {
 "severity": "info",
 "description": "Consider adding docstring",
 "file": "src/main.py",
 "line": "10",
 "suggestion": "Add module docstring",
 }
 ]
 },
 "security": {"issues": issues},
 "plan_compliance": {"issues": },
 },
 }
def _make_coding_result(
 mr_count: int = 1,
 repo_id: str = "00000000-0000-0000-0000-000000000001",
 repo_name: str = "test-repo",
) -> dict[str, Any]:
 """Create a coding_result input matching AICodingNode output."""
 merge_requests = [
 {
 "repository_id": repo_id,
 "repository_name": repo_name,
 "mr_url": f"https://gitlab.example.com/test/repo/-/merge_requests/{i + 1}",
 "mr_id": str(i + 1),
 "tasks_completed": [f"Task {i + 1}"],
 "files_changed": 3,
 "insertions": 50,
 "deletions": 10,
 }
 for i in range(mr_count)
 ]
 return {
 "coding_result": {
 "merge_requests": merge_requests,
 "branches": {"branch_name": "feat/test", "base_branch": "main"},
 "changes_summary": {
 "total_repos": mr_count,
 "succeeded_repos": mr_count,
 },
 }
 }
# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestAICodeReviewNode:
 """AICodeReviewNode 独立执行行为测试。"""
 async def test_execute_happy_path_approved(self) -> None:
 """Agent 返回无 critical issue 的审查报告 -> approved=True。"""
 report = _make_review_report(approved=True)
 input_data = _make_coding_result
 context = _make_context(input_data=input_data)
 agent_result = AgentResult(
 output=,
 status="completed",
 final_answer=json.dumps(report),
 )
 diff_result = MRDiffResult(
 success=True,
 files=[
 MRDiffFile(
 old_path="src/main.py",
 new_path="src/main.py",
 diff="@@ -1,3 +1,5 @@\n+import os\n+\n def main:\n pass",
 )
 ],
 truncated=False,
 )
 node = AICodeReviewNode
 mock_project = MagicMock
 mock_project.id = 1
 mock_user = MagicMock
 mock_user.id = 1
 mock_provider = MagicMock
 with (
 patch.object(node, "_get_project", new_callable=AsyncMock, return_value=mock_project),
 patch.object(node, "_get_user", new_callable=AsyncMock, return_value=mock_user),
 patch.object(node, "_get_provider", new_callable=AsyncMock, return_value=mock_provider),
 patch.object(node, "_fetch_mr_diff", new_callable=AsyncMock, return_value=diff_result),
 patch.object(node, "_send_review_notification", new_callable=AsyncMock),
 patch("workflows.nodes.ai.code_review.AgentLoop") as MockLoop,
 ):
 loop_instance = MockLoop.return_value
 loop_instance.run = AsyncMock(return_value=agent_result)
 result: NodeResult = await node.execute(context)
 assert result.status == "completed"
 assert result.next_handle == "default"
 assert result.output["approved"] is True
 assert result.output["issues_count"] >= 0
 assert "review_report" in result.output
 assert "severity_breakdown" in result.output
 async def test_execute_happy_path_rejected(self) -> None:
 """Agent 返回含 critical issue 的报告 -> approved=False。"""
 report = _make_review_report(approved=False)
 input_data = _make_coding_result
 context = _make_context(input_data=input_data)
 agent_result = AgentResult(
 output=,
 status="completed",
 final_answer=json.dumps(report),
 )
 diff_result = MRDiffResult(
 success=True,
 files=[
 MRDiffFile(
 old_path="src/db.py",
 new_path="src/db.py",
 diff="@@ -1 +1 @@\n-safe_query\n+unsafe_query(user_input)",
 )
 ],
 )
 node = AICodeReviewNode
 mock_project = MagicMock
 mock_project.id = 1
 mock_user = MagicMock
 mock_user.id = 1
 mock_provider = MagicMock
 with (
 patch.object(node, "_get_project", new_callable=AsyncMock, return_value=mock_project),
 patch.object(node, "_get_user", new_callable=AsyncMock, return_value=mock_user),
 patch.object(node, "_get_provider", new_callable=AsyncMock, return_value=mock_provider),
 patch.object(node, "_fetch_mr_diff", new_callable=AsyncMock, return_value=diff_result),
 patch.object(node, "_send_review_notification", new_callable=AsyncMock),
 patch("workflows.nodes.ai.code_review.AgentLoop") as MockLoop,
 ):
 loop_instance = MockLoop.return_value
 loop_instance.run = AsyncMock(return_value=agent_result)
 result: NodeResult = await node.execute(context)
 assert result.status == "completed"
 assert result.output["approved"] is False
 assert result.output["severity_breakdown"]["critical"] >= 1
 async def test_execute_missing_coding_result(self) -> None:
 """无 coding_result 输入 -> status=failed。"""
 context = _make_context(input_data={})
 node = AICodeReviewNode
 result: NodeResult = await node.execute(context)
 assert result.status == "failed"
 assert "coding_result" in (result.error or "")
 assert result.next_handle == "error"
 async def test_execute_empty_merge_requests(self) -> None:
 """coding_result.merge_requests 为空列表 -> status=failed。"""
 input_data = {
 "coding_result": {
 "merge_requests":,
 "branches": {"branch_name": "feat/test", "base_branch": "main"},
 }
 }
 context = _make_context(input_data=input_data)
 node = AICodeReviewNode
 result: NodeResult = await node.execute(context)
 assert result.status == "failed"
 assert "merge_requests" in (result.error or "")
 assert result.next_handle == "error"
 def test_extract_json_from_markdown(self) -> None:
 """从 ```json 包裹的 JSON 中正确提取。"""
 raw_report = {"repository": "test", "summary": "ok", "dimensions": {}}
 text = f"Here is the review:\n```json\n{json.dumps(raw_report)}\n```\nDone."
 extracted = _extract_json_from_text(text)
 assert extracted is not None
 assert extracted["repository"] == "test"
 assert extracted["summary"] == "ok"
 def test_extract_json_from_braces(self) -> None:
 """从文本中嵌入的 JSON（无 markdown 标记）中正确提取。"""
 raw_report = {"repository": "my-repo", "summary": "looks good", "dimensions": {}}
 text = f"The review result is: {json.dumps(raw_report)} -- end of review"
 extracted = _extract_json_from_text(text)
 assert extracted is not None
 assert extracted["repository"] == "my-repo"
 assert extracted["summary"] == "looks good"
 def test_count_issues(self) -> None:
 """_count_issues 正确统计不同 severity 的 issue 数量。"""
 report: dict[str, Any] = {
 "dimensions": {
 "code_quality": {
 "issues": [
 {"severity": "critical", "description": "Bug"},
 {"severity": "warning", "description": "Smell"},
 {"severity": "info", "description": "Style"},
 ]
 },
 "security": {
 "issues": [
 {"severity": "critical", "description": "SQLi"},
 ]
 },
 "plan_compliance": {
 "issues": [
 {"severity": "warning", "description": "Missing feature"},
 {"severity": "unknown_severity", "description": "Edge case"},
 ]
 },
 }
 }
 total, breakdown = _count_issues(report)
 assert total == 6
 assert breakdown["critical"] == 2
 assert breakdown["warning"] == 2
 # "unknown_severity" falls back to "info" per implementation
 assert breakdown["info"] == 2
