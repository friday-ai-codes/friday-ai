"""AICodeReviewNode 单元测试（Phase 迁移后）。
覆盖 happy path（diff 获取成功 -> Agent 审查 -> 结构化报告）和 error handling
（缺少 coding_result -> failed、空 merge_requests -> failed），以及
合并后 新增 3 项契约：
- per-MR Runner session_id 独立性
- resolved 循环外一次解析
- sub_step 三子步骤 emit 序列
mock 迁移：
- 删除老 Runner mock.patch 调用点（见 Summary）
- 替换为 conftest ``fake_chat_model_factory`` seam + ``mock_aresolve_ok`` +
 ``make_minimal_context`` 4 公共 fixture（ Task 3 落地； 弥补）
"""
from __future__ import annotations
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
import pytest
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
 execution_id: str = "exec-review-001",
 node_id: str = "node-review-001",
) -> ExecutionContext:
 """Create a minimal ExecutionContext for testing."""
 return ExecutionContext(
 execution_id=execution_id,
 node_id=node_id,
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
def _make_single_diff -> MRDiffResult:
 """构造单个 MR 的 diff 结果（用于 _fetch_mr_diff 替身）。"""
 return MRDiffResult(
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
def _patch_common(monkeypatch: pytest.MonkeyPatch, node: AICodeReviewNode) -> None:
 """统一替身：_get_project / _get_user / _fetch_mr_diff / _send_review_notification。
 ``mock_project.id`` 使用合法 UUID 字符串，避免 ``render_prompt`` 下游
 ``Prompt.objects.filter(project_id=...)`` 的 UUID 校验失败。
 """
 mock_project = MagicMock
 mock_project.id = "00000000-0000-0000-0000-000000000001"
 mock_user = MagicMock
 mock_user.id = 1
 monkeypatch.setattr(
 node, "_get_project", AsyncMock(return_value=mock_project)
 )
 monkeypatch.setattr(node, "_get_user", AsyncMock(return_value=mock_user))
 monkeypatch.setattr(
 node,
 "_fetch_mr_diff",
 AsyncMock(return_value=_make_single_diff),
 )
 monkeypatch.setattr(
 node,
 "_send_review_notification",
 AsyncMock(return_value=None),
 )
# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestAICodeReviewNode:
 """AICodeReviewNode 独立执行行为测试（ 迁移后）。"""
 async def test_execute_happy_path_approved(
 self,
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """Agent 返回无 critical issue 的审查报告 -> approved=True。"""
 report = _make_review_report(approved=True)
 fake_chat_model_factory(responses=[json.dumps(report)])
 mock_aresolve_ok(source="system")
 input_data = _make_coding_result
 context = _make_context(input_data=input_data)
 node = AICodeReviewNode
 _patch_common(monkeypatch, node)
 result: NodeResult = await node.execute(context)
 assert result.status == "completed"
 assert result.next_handle == "default"
 assert result.output["approved"] is True
 assert result.output["issues_count"] >= 0
 assert "review_report" in result.output
 assert "severity_breakdown" in result.output
 async def test_execute_happy_path_rejected(
 self,
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 monkeypatch: pytest.MonkeyPatch,
 ) -> None:
 """Agent 返回含 critical issue 的报告 -> approved=False。"""
 report = _make_review_report(approved=False)
 fake_chat_model_factory(responses=[json.dumps(report)])
 mock_aresolve_ok(source="system")
 input_data = _make_coding_result
 context = _make_context(input_data=input_data)
 node = AICodeReviewNode
 _patch_common(monkeypatch, node)
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
# ---------------------------------------------------------------------------
# 合并后新增：per-MR 独立性 / resolved 复用 / sub_step 三态序列
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_code_review_per_mr_independent_session_id(
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """：3 MR 场景 -> 3 个 Runner 实例，session_id 各不同且均以 ``review-`` 开头。"""
 from agents.langchain_runner import LangChainAgentRunner, LangChainRunnerConfig
 captured_configs: list[LangChainRunnerConfig] =
 _orig_init = LangChainAgentRunner.__init__
 def _capturing_init(self: LangChainAgentRunner, cfg: LangChainRunnerConfig) -> None: # type: ignore[no-redef]
 captured_configs.append(cfg)
 _orig_init(self, cfg)
 monkeypatch.setattr(
 "workflows.nodes.ai.code_review.LangChainAgentRunner.__init__",
 _capturing_init,
 )
 # 3 MR 每 MR 一次 LLM 调用
 report_json = json.dumps(_make_review_report(approved=True))
 fake_chat_model_factory(responses=[report_json, report_json, report_json])
 mock_aresolve_ok(source="system")
 input_data = _make_coding_result(mr_count=3)
 context = _make_context(
 input_data=input_data,
 execution_id="exec-test",
 node_id="code-review-n1",
 )
 node = AICodeReviewNode
 _patch_common(monkeypatch, node)
 result = await node.execute(context)
 assert result.status == "completed"
 assert len(captured_configs) == 3, (
 f"应创建 3 个 Runner 实例，实际 {len(captured_configs)}"
 )
 session_ids = [cfg.session_id for cfg in captured_configs]
 assert len(set(session_ids)) == 3, f"3 session_id 应全不同：{session_ids}"
 for sid in session_ids:
 assert sid.startswith("review-"), (
 f"session_id 应以 'review-' 开头：{sid}"
 )
 assert "exec-test" in sid
 assert "code-review-n1" in sid
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_code_review_resolved_reused_across_mrs(
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """：resolved 在循环外一次解析 —— _resolve_api_key_and_model 调用 1 次 for 3 MR。"""
 from workflows.nodes.ai.base_agent import AIAgentBaseNode
 resolve_call_count = 0
 orig_resolve = AIAgentBaseNode._resolve_api_key_and_model
 async def _counting_resolve(self: AIAgentBaseNode, *a: Any, **kw: Any) -> Any: # type: ignore[no-redef]
 nonlocal resolve_call_count
 resolve_call_count += 1
 return await orig_resolve(self, *a, **kw)
 monkeypatch.setattr(
 "workflows.nodes.ai.base_agent.AIAgentBaseNode._resolve_api_key_and_model",
 _counting_resolve,
 )
 report_json = json.dumps(_make_review_report(approved=True))
 fake_chat_model_factory(responses=[report_json, report_json, report_json])
 mock_aresolve_ok(source="system")
 input_data = _make_coding_result(mr_count=3)
 context = _make_context(input_data=input_data)
 node = AICodeReviewNode
 _patch_common(monkeypatch, node)
 result = await node.execute(context)
 assert result.status == "completed"
 assert resolve_call_count == 1, (
 f"_resolve_api_key_and_model 应循环外一次解析，实际 {resolve_call_count} 次（ 违反）"
 )
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_code_review_sub_step_emit_order(
 fake_chat_model_factory: Any,
 mock_aresolve_ok: Any,
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """ /：fetch_diff / ai_review / send_notification 三子步骤按序 emit。
 单 MR 场景覆盖 RUNNING -> COMPLETED 两态，并断言三子步骤顺序。
 status 值使用 SubStepStatus 枚举（TextChoices，实际值为小写 'running' / 'completed'）。
 """
 emit_log: list[tuple[str, str]] =
 async def _fake_emit(
 self: Any,
 context: ExecutionContext,
 step_type: str,
 status: str,
 output_data: dict[str, Any] | None = None,
 ) -> None:
 # 兼容 SubStepStatus TextChoices：.value 或直接字符串
 status_str = str(getattr(status, "value", status))
 emit_log.append((step_type, status_str))
 monkeypatch.setattr(
 "workflows.nodes.ai.sub_step_mixin.SubStepMixin.emit_sub_step",
 _fake_emit,
 )
 report_json = json.dumps(_make_review_report(approved=True))
 fake_chat_model_factory(responses=[report_json])
 mock_aresolve_ok(source="system")
 input_data = _make_coding_result(mr_count=1)
 context = _make_context(input_data=input_data)
 node = AICodeReviewNode
 _patch_common(monkeypatch, node)
 result = await node.execute(context)
 assert result.status == "completed"
 step_names = [name for name, _ in emit_log]
 assert "fetch_diff" in step_names, f"应 emit fetch_diff，实际 {emit_log}"
 assert "ai_review" in step_names, f"应 emit ai_review，实际 {emit_log}"
 assert "send_notification" in step_names, (
 f"应 emit send_notification，实际 {emit_log}"
 )
 idx_fetch = step_names.index("fetch_diff")
 idx_review = step_names.index("ai_review")
 idx_notify = step_names.index("send_notification")
 assert idx_fetch < idx_review < idx_notify, (
 f"三子步骤顺序应为 fetch_diff -> ai_review -> send_notification，实际 {step_names}"
 )
 # 每子步骤应有 RUNNING + COMPLETED 两态（status 值为小写 'running' / 'completed'）
 for name in ("fetch_diff", "ai_review", "send_notification"):
 statuses = [s.lower for n, s in emit_log if n == name]
 assert "running" in statuses, (
 f"{name} 应 emit RUNNING，实际 {statuses}"
 )
 assert "completed" in statuses, (
 f"{name} 应 emit COMPLETED，实际 {statuses}"
 )
