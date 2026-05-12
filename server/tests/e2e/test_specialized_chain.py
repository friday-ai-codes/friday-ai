"""Specialized node chain E2E tests.
Tests the data flow between the four specialized AI nodes:
AIPlanGenerationNode -> PlanApprovalNode -> AICodingNode -> AICodeReviewNode
Strategy: Execute each node individually and manually pass output_data
from upstream to downstream via ExecutionContext.input_data, avoiding
PlanApproval's waiting_event blocking the workflow engine.
OBSOLETE 原因：v21.0 Phase 把所有 AI 节点的 SDKAgentRunner 替换为
LangChainAgentRunner（patch 路径 `workflows.nodes.ai.base_agent.SDKAgentRunner`
已不存在；本测试 4 个用例的 mock 全部失效）。重写这些测试需要按 LangChain
Runner 新契约（Hook + StateGraph + ChatModel）重新搭建 mock 链路，是 phase
级别工作。后续 v24.0 应删本文件并基于 LangChainAgentRunner 重写专用链路 E2E。
"""
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
pytestmark = pytest.mark.skip(
 reason=(
 "OBSOLETE — Phase LangChainAgentRunner 替代 SDKAgentRunner 后，"
 "本测试 patch 路径 workflows.nodes.ai.base_agent.SDKAgentRunner 已不存在。"
 "需在 v24.0 按 LangChain 新契约重写专用链路 E2E。"
 )
)
from agents.core.result import AgentResult
from services.git_platform.models import MRDiffFile, MRDiffResult
from tests.e2e.fixtures.technical_plans import VALID_TECHNICAL_PLAN
from workflows.nodes.ai.code_review import AICodeReviewNode
from workflows.nodes.ai.coding import AICodingNode
from workflows.nodes.ai.plan_approval import PlanApprovalNode
from workflows.nodes.ai.plan_generation import AIPlanGenerationNode
from workflows.nodes.base import ExecutionContext, NodeResult
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_plan_gen_context(
 *,
 user_prompt: str = "实现用户认证模块重构",
) -> ExecutionContext:
 """Build ExecutionContext for AIPlanGenerationNode."""
 mock_project = MagicMock
 mock_project.id = "00000000-0000-0000-0000-000000000001"
 mock_project.feishu_doc_folder_token = "folder_token_123"
 mock_workflow = MagicMock
 mock_workflow.project = mock_project
 mock_execution = MagicMock
 mock_execution.workflow = mock_workflow
 mock_execution.triggered_by = MagicMock(id=1)
 return ExecutionContext(
 execution_id="00000000-0000-0000-0000-000000000003",
 node_id="00000000-0000-0000-0000-000000000013",
 node_config={
 "user_prompt": user_prompt,
 "model": "claude-sonnet-4-20250514",
 "chat_id": "",
 },
 input_data={},
 workflow_context={},
 previous_outputs={},
 workflow_execution=mock_execution,
 )
def _make_approval_context(
 input_data: dict[str, Any],
) -> ExecutionContext:
 """Build ExecutionContext for PlanApprovalNode."""
 mock_project = MagicMock
 mock_project.id = "00000000-0000-0000-0000-000000000001"
 mock_project.feishu_doc_folder_token = "folder_token_123"
 mock_workflow = MagicMock
 mock_workflow.project = mock_project
 mock_execution = MagicMock
 mock_execution.workflow = mock_workflow
 mock_execution.triggered_by = MagicMock(id=1)
 return ExecutionContext(
 execution_id="00000000-0000-0000-0000-000000000003",
 node_id="00000000-0000-0000-0000-000000000014",
 node_config={"chat_id": ""},
 input_data=input_data,
 workflow_context={},
 previous_outputs={},
 workflow_execution=mock_execution,
 )
def _make_coding_context(
 input_data: dict[str, Any],
 repo_id: str,
) -> ExecutionContext:
 """Build ExecutionContext for AICodingNode."""
 return ExecutionContext(
 execution_id="00000000-0000-0000-0000-000000000003",
 node_id="00000000-0000-0000-0000-000000000015",
 node_config={
 "polling_interval": 0,
 "timeout_seconds": 10,
 "chat_id": "",
 },
 input_data=input_data,
 workflow_context={},
 previous_outputs={},
 trigger_data={"payload": {"work_item_id": "12345"}},
 workflow_execution=None,
 node_execution=None,
 )
def _make_review_context(
 input_data: dict[str, Any],
) -> ExecutionContext:
 """Build ExecutionContext for AICodeReviewNode."""
 return ExecutionContext(
 execution_id="00000000-0000-0000-0000-000000000003",
 node_id="00000000-0000-0000-0000-000000000016",
 node_config={
 "model": "claude-sonnet-4-20250514",
 "chat_id": "",
 "max_iterations": 5,
 },
 input_data=input_data,
 workflow_context={},
 previous_outputs={},
 trigger_data={},
 workflow_execution=None,
 node_execution=None,
 )
def _make_repo(repo_id: str, name: str = "e2e-test-repo") -> MagicMock:
 """Create a mock Repository object."""
 repo = MagicMock
 repo.id = uuid.UUID(repo_id)
 repo.name = name
 repo.git_url = "https://gitlab.example.com/test/e2e-repo.git"
 repo.git_platform = "gitlab"
 repo.default_branch = "main"
 repo.is_deleted = False
 credential = MagicMock
 credential.encrypted_token = "encrypted-token-123"
 repo.credential = credential
 return repo
def _make_plan_with_repo(repo_id: str) -> dict[str, Any]:
 """Create a technical plan with tasks bound to a specific repo."""
 return {
 "title": "用户认证模块重构",
 "summary": "重构现有用户认证模块，添加 JWT 刷新令牌支持和多因素认证功能",
 "branch_name": "feat/xxxx-m12345-auth-refactor",
 "execution_plan": [
 {
 "id": "task-001",
 "name": "添加 JWT 刷新令牌支持",
 "description": "实现 JWT 刷新令牌的生成、存储和验证逻辑",
 "repository_id": repo_id,
 "repository_name": "e2e-test-repo",
 "coding_instruction": "实现 JWT 刷新令牌功能",
 "files": [
 {"path": "accounts/models.py", "action": "modify"},
 ],
 "dependencies":,
 },
 ],
 "global_context": "Friday 项目认证模块重构",
 }
def _make_review_report(
 repo_name: str = "e2e-test-repo",
 approved: bool = True,
) -> dict[str, Any]:
 """Create a sample review report JSON."""
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
 "repository": repo_name,
 "summary": "Code review passed" if approved else "Critical issues found",
 "dimensions": {
 "code_quality": {
 "issues": [
 {
 "severity": "info",
 "description": "Consider adding docstring",
 "file": "accounts/models.py",
 "line": "1",
 "suggestion": "Add module docstring",
 }
 ]
 },
 "security": {"issues": issues},
 "plan_compliance": {"issues": },
 },
 }
# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestSpecializedChainE2E:
 """End-to-end chain tests verifying data flow across all four specialized nodes."""
 async def test_data_flow_plan_generation_to_approval(self) -> None:
 """PlanGeneration output.plan -> PlanApproval input.plan.
 Verifies PlanApproval can read the plan from PlanGeneration output
 and returns waiting_event with the same plan.
 """
 # -- Step 1: Execute AIPlanGenerationNode --
 plan_gen_ctx = _make_plan_gen_context
 plan_gen_node = AIPlanGenerationNode
 agent_result = AgentResult(
 output=,
 status="completed",
 final_answer="方案已生成",
 usage={"input_tokens": 1000, "output_tokens": 500},
 metadata={"plan": VALID_TECHNICAL_PLAN},
 )
 with (
 patch("workflows.nodes.ai.base_agent.AgentSession.objects") as mock_session,
 patch("workflows.nodes.ai.base_agent.SDKAgentRunner") as mock_runner_cls,
 patch.object(plan_gen_node, "_get_project", new_callable=AsyncMock, return_value=MagicMock(id="00000000-0000-0000-0000-000000000001", feishu_doc_folder_token="folder_token_123")),
 patch.object(plan_gen_node, "_get_user", new_callable=AsyncMock, return_value=MagicMock(id=1)),
 patch.object(plan_gen_node, "_resolve_api_key_and_model", new_callable=AsyncMock, return_value=("sk-test", "claude-sonnet-4-20250514", "")),
 ):
 mock_session.aupdate_or_create = AsyncMock(return_value=(MagicMock, True))
 mock_runner_instance = MagicMock
 async def _empty_stream(prompt):
 return
 yield # noqa: RET504
 mock_runner_instance.stream = MagicMock(side_effect=_empty_stream)
 mock_runner_instance.result = agent_result
 mock_runner_cls.return_value = mock_runner_instance
 plan_gen_result: NodeResult = await plan_gen_node.execute(plan_gen_ctx)
 assert plan_gen_result.status == "completed"
 assert plan_gen_result.output["plan"] is not None
 plan_output = plan_gen_result.output
 # -- Step 2: Pass plan to PlanApprovalNode --
 # Simulate workflow engine passing upstream output as downstream input
 approval_input = {
 "plan": plan_output["plan"],
 "final_answer": plan_output.get("final_answer", ""),
 "usage": plan_output.get("usage", {}),
 }
 approval_ctx = _make_approval_context(input_data=approval_input)
 approval_node = PlanApprovalNode
 mock_we_instance = MagicMock
 mock_we_instance.workflow = MagicMock(project=MagicMock(id="00000000-0000-0000-0000-000000000001", feishu_doc_folder_token="folder_token_123"))
 with (
 patch("workflows.models.WorkflowExecution.objects") as mock_we_objects,
 patch(
 "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project"
 ) as mock_doc,
 ):
 mock_we_objects.select_related.return_value.aget = AsyncMock(return_value=mock_we_instance)
 mock_doc_client = MagicMock
 mock_doc_client.create_document = AsyncMock(
 return_value={"url": "https://feishu.cn/docs/test", "document_id": "doc1"}
 )
 mock_doc_client.app_id = "app_id"
 mock_doc_client.app_secret = "app_secret"
 mock_doc.return_value = mock_doc_client
 approval_result: NodeResult = await approval_node.execute(approval_ctx)
 # Verify: PlanApproval received plan and returned waiting_event
 assert approval_result.status == "waiting_event"
 assert approval_result.output["plan"] == plan_output["plan"]
 assert approval_result.output["approval_status"] == "pending"
 # The plan data flows correctly from generation to approval
 assert approval_result.output["plan"]["title"] == VALID_TECHNICAL_PLAN["title"]
 async def test_data_flow_approval_to_coding(
 self,
 e2e_repository: Any,
 ) -> None:
 """PlanApproval output.plan (approved) -> AICoding input.plan.
 Verifies AICodingNode correctly reads plan data, dispatches container,
 and returns waiting_event (callback-driven mode).
 """
 repo_id_str = str(e2e_repository.id)
 # Construct approved plan data (simulating approval callback output)
 approved_plan = _make_plan_with_repo(repo_id_str)
 # Simulate workflow engine passing approved plan to coding node
 coding_input = {"plan": approved_plan}
 coding_ctx = _make_coding_context(
 input_data=coding_input,
 repo_id=repo_id_str,
 )
 coding_node = AICodingNode
 # Mock _run_repo_coding to avoid TaskDispatcher and DB sync issues
 mock_repo_result = {
 "status": "waiting_event",
 "session_id": "exec-test123",
 "container_id": "container-001",
 "repository_id": repo_id_str,
 "repository_name": "e2e-test-repo",
 }
 with (
 patch.object(
 coding_node,
 "_run_repo_coding",
 new_callable=AsyncMock,
 return_value=mock_repo_result,
 ),
 patch(
 "workflows.nodes.ai.coding.decrypt_value",
 return_value="mock-token-123",
 ),
 ):
 coding_result: NodeResult = await coding_node.execute(coding_ctx)
 # Verify: AICodingNode returns waiting_event (callback-driven)
 assert coding_result.status == "waiting_event"
 assert "pending_sessions" in coding_result.output
 assert len(coding_result.output["pending_sessions"]) >= 1
 async def test_data_flow_coding_to_review(self) -> None:
 """AICoding output (merge_requests) -> CodeReview input (coding_result).
 Verifies AICodeReviewNode reads MR list, fetches diff, and produces
 a structured review report.
 """
 repo_id = "00000000-0000-0000-0000-000000000001"
 repo_name = "e2e-test-repo"
 # Construct AICodingNode output
 coding_output = {
 "merge_requests": [
 {
 "repository_id": repo_id,
 "repository_name": repo_name,
 "mr_url": "https://gitlab.example.com/test/repo/-/merge_requests/1",
 "mr_id": "1",
 "tasks_completed": ["添加 JWT 刷新令牌支持"],
 "files_changed": 3,
 "insertions": 50,
 "deletions": 10,
 }
 ],
 "branches": {"branch_name": "feat/auth-refactor", "base_branch": "main"},
 "changes_summary": {
 "total_repos": 1,
 "succeeded_repos": 1,
 "failed_repos": 0,
 },
 }
 plan_data = {
 "title": "用户认证模块重构",
 "execution_plan": [
 {
 "repository_id": repo_id,
 "name": "添加 JWT 刷新令牌支持",
 "description": "实现刷新令牌逻辑",
 },
 ],
 }
 # Pass coding output + plan to review node
 review_input = {
 "coding_result": coding_output,
 "plan": plan_data,
 }
 review_ctx = _make_review_context(input_data=review_input)
 review_node = AICodeReviewNode
 review_report = _make_review_report(repo_name=repo_name, approved=True)
 agent_result = AgentResult(
 output=,
 status="completed",
 final_answer=json.dumps(review_report),
 )
 diff_result = MRDiffResult(
 success=True,
 files=[
 MRDiffFile(
 old_path="accounts/models.py",
 new_path="accounts/models.py",
 diff="@@ -1,3 +1,10 @@\n+from django.db import models\n+\n+class RefreshToken(models.Model):\n+ token = models.CharField(max_length=255)\n",
 )
 ],
 truncated=False,
 )
 mock_project = MagicMock
 mock_project.id = "00000000-0000-0000-0000-000000000001"
 mock_user = MagicMock
 mock_user.id = 1
 with (
 patch.object(review_node, "_get_project", new_callable=AsyncMock, return_value=mock_project),
 patch.object(review_node, "_get_user", new_callable=AsyncMock, return_value=mock_user),
 patch.object(review_node, "_resolve_api_key_and_model", new_callable=AsyncMock, return_value=("sk-test", "claude-sonnet-4-20250514", "")),
 patch.object(review_node, "_fetch_mr_diff", new_callable=AsyncMock, return_value=diff_result),
 patch.object(review_node, "_send_review_notification", new_callable=AsyncMock),
 patch("workflows.nodes.ai.code_review.SDKAgentRunner") as MockRunner,
 ):
 mock_runner_instance = MagicMock
 async def _empty_stream(prompt):
 return
 yield # noqa: RET504
 mock_runner_instance.stream = MagicMock(side_effect=_empty_stream)
 mock_runner_instance.result = agent_result
 MockRunner.return_value = mock_runner_instance
 review_result: NodeResult = await review_node.execute(review_ctx)
 # Verify: CodeReview read MR list, produced review report
 assert review_result.status == "completed"
 assert "review_report" in review_result.output
 assert "approved" in review_result.output
 assert review_result.output["approved"] is True
 assert "reviewed_mrs" in review_result.output
 assert len(review_result.output["reviewed_mrs"]) == 1
 assert review_result.output["reviewed_mrs"][0]["mr_id"] == "1"
 assert review_result.output["reviewed_mrs"][0]["repository_name"] == repo_name
 async def test_complete_chain_data_flow(
 self,
 e2e_repository: Any,
 ) -> None:
 """Full chain: PlanGen -> Approval -> Coding -> CodeReview.
 Executes all four nodes sequentially, passing each upstream output
 as downstream input, verifying the complete data flow contract.
 """
 repo_id_str = str(e2e_repository.id)
 # ==================== Step 1: PlanGeneration ====================
 plan_with_repo = _make_plan_with_repo(repo_id_str)
 plan_gen_ctx = _make_plan_gen_context
 plan_gen_node = AIPlanGenerationNode
 gen_agent_result = AgentResult(
 output=,
 status="completed",
 final_answer="方案已生成",
 usage={"input_tokens": 1500, "output_tokens": 800},
 metadata={"plan": plan_with_repo},
 )
 with (
 patch("workflows.nodes.ai.base_agent.AgentSession.objects") as mock_session,
 patch("workflows.nodes.ai.base_agent.SDKAgentRunner") as mock_runner_cls,
 patch.object(plan_gen_node, "_get_project", new_callable=AsyncMock, return_value=MagicMock(id="00000000-0000-0000-0000-000000000001", feishu_doc_folder_token="folder_token_123")),
 patch.object(plan_gen_node, "_get_user", new_callable=AsyncMock, return_value=MagicMock(id=1)),
 patch.object(plan_gen_node, "_resolve_api_key_and_model", new_callable=AsyncMock, return_value=("sk-test", "claude-sonnet-4-20250514", "")),
 ):
 mock_session.aupdate_or_create = AsyncMock(return_value=(MagicMock, True))
 mock_runner_instance = MagicMock
 async def _empty_stream_1(prompt):
 return
 yield # noqa: RET504
 mock_runner_instance.stream = MagicMock(side_effect=_empty_stream_1)
 mock_runner_instance.result = gen_agent_result
 mock_runner_cls.return_value = mock_runner_instance
 plan_gen_result = await plan_gen_node.execute(plan_gen_ctx)
 assert plan_gen_result.status == "completed"
 plan_output = plan_gen_result.output
 assert plan_output["plan"]["title"] == "用户认证模块重构"
 assert len(plan_output["plan"]["execution_plan"]) >= 1
 # ==================== Step 2: PlanApproval ====================
 approval_input = {
 "plan": plan_output["plan"],
 "final_answer": plan_output.get("final_answer", ""),
 "usage": plan_output.get("usage", {}),
 }
 approval_ctx = _make_approval_context(input_data=approval_input)
 approval_node = PlanApprovalNode
 mock_we_instance = MagicMock
 mock_we_instance.workflow = MagicMock(project=MagicMock(id="00000000-0000-0000-0000-000000000001", feishu_doc_folder_token="folder_token_123"))
 with (
 patch("workflows.models.WorkflowExecution.objects") as mock_we_objects,
 patch(
 "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project"
 ) as mock_doc,
 ):
 mock_we_objects.select_related.return_value.aget = AsyncMock(return_value=mock_we_instance)
 mock_doc_client = MagicMock
 mock_doc_client.create_document = AsyncMock(
 return_value={"url": "https://feishu.cn/docs/chain-test", "document_id": "doc-chain"}
 )
 mock_doc_client.app_id = "app_id"
 mock_doc_client.app_secret = "app_secret"
 mock_doc.return_value = mock_doc_client
 approval_result = await approval_node.execute(approval_ctx)
 assert approval_result.status == "waiting_event"
 # Extract the plan from approval output (skip waiting_event, pass directly)
 approved_plan = approval_result.output["plan"]
 assert approved_plan["title"] == plan_with_repo["title"]
 assert approved_plan["branch_name"] == plan_with_repo["branch_name"]
 # ==================== Step 3: AICoding ====================
 coding_input = {"plan": approved_plan}
 coding_ctx = _make_coding_context(
 input_data=coding_input,
 repo_id=repo_id_str,
 )
 coding_node = AICodingNode
 # Mock _run_repo_coding to avoid TaskDispatcher and DB sync issues
 mock_repo_result = {
 "status": "waiting_event",
 "session_id": "exec-chain-test",
 "container_id": "container-chain-001",
 "repository_id": repo_id_str,
 "repository_name": "e2e-test-repo",
 }
 with (
 patch.object(
 coding_node,
 "_run_repo_coding",
 new_callable=AsyncMock,
 return_value=mock_repo_result,
 ),
 patch(
 "workflows.nodes.ai.coding.decrypt_value",
 return_value="mock-token-123",
 ),
 ):
 coding_result = await coding_node.execute(coding_ctx)
 # In callback-driven mode, AICodingNode returns waiting_event
 assert coding_result.status == "waiting_event"
 assert "pending_sessions" in coding_result.output
 # For CodeReview test, we simulate what the callback would produce
 coding_output = {
 "merge_requests": [
 {
 "repository_id": repo_id_str,
 "repository_name": "e2e-test-repo",
 "mr_url": "https://gitlab.example.com/test/repo/-/merge_requests/42",
 "mr_id": "42",
 "tasks_completed": ["Task 1"],
 "files_changed": 5,
 "insertions": 100,
 "deletions": 20,
 }
 ],
 "branches": {"branch_name": "feat/e2e-test", "base_branch": "main"},
 "changes_summary": {
 "total_repos": 1,
 "succeeded_repos": 1,
 "failed_repos": 0,
 "total_files_changed": 5,
 "total_insertions": 100,
 "total_deletions": 20,
 },
 "failed_details":,
 }
 # ==================== Step 4: CodeReview ====================
 review_input = {
 "coding_result": coding_output,
 "plan": approved_plan,
 }
 review_ctx = _make_review_context(input_data=review_input)
 review_node = AICodeReviewNode
 review_report = _make_review_report(
 repo_name="e2e-test-repo",
 approved=True,
 )
 review_agent_result = AgentResult(
 output=,
 status="completed",
 final_answer=json.dumps(review_report),
 )
 diff_result = MRDiffResult(
 success=True,
 files=[
 MRDiffFile(
 old_path="accounts/models.py",
 new_path="accounts/models.py",
 diff="@@ -1,3 +1,15 @@\n+class RefreshToken:\n+ pass\n",
 )
 ],
 truncated=False,
 )
 mock_project = MagicMock
 mock_project.id = "00000000-0000-0000-0000-000000000001"
 mock_user = MagicMock
 mock_user.id = 1
 with (
 patch.object(review_node, "_get_project", new_callable=AsyncMock, return_value=mock_project),
 patch.object(review_node, "_get_user", new_callable=AsyncMock, return_value=mock_user),
 patch.object(review_node, "_resolve_api_key_and_model", new_callable=AsyncMock, return_value=("sk-test", "claude-sonnet-4-20250514", "")),
 patch.object(review_node, "_fetch_mr_diff", new_callable=AsyncMock, return_value=diff_result),
 patch.object(review_node, "_send_review_notification", new_callable=AsyncMock),
 patch("workflows.nodes.ai.code_review.SDKAgentRunner") as MockRunner,
 ):
 mock_runner_instance = MagicMock
 async def _empty_stream_2(prompt):
 return
 yield # noqa: RET504
 mock_runner_instance.stream = MagicMock(side_effect=_empty_stream_2)
 mock_runner_instance.result = review_agent_result
 MockRunner.return_value = mock_runner_instance
 review_result = await review_node.execute(review_ctx)
 # ==================== Final Assertions ====================
 assert review_result.status == "completed"
 assert review_result.output["approved"] is True
 assert "review_report" in review_result.output
 assert review_result.output["review_report"]["conclusion"] == "approved"
 assert len(review_result.output["reviewed_mrs"]) >= 1
 assert review_result.output["reviewed_mrs"][0]["mr_id"] == "42"
 assert review_result.output["severity_breakdown"] is not None
 assert review_result.output["issues_count"] >= 0
