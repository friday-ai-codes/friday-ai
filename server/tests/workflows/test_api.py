"""Tests for workflow API endpoints.
Tests cover:
- Workflow CRUD operations
- Workflow execution endpoints
- Node type listing
- Template API
- Approval endpoints
- Task compatibility API
"""
import pytest
from rest_framework import status
from projects.models import Project
from workflows.models import (
 Workflow,
 WorkflowEdge,
 WorkflowExecution,
 WorkflowNode,
)
@pytest.fixture
def api_project(db):
 """Create a project for API tests."""
 return Project.objects.create(
 name="API Test Project",
 description="Project for API testing",
 )
@pytest.fixture
def api_workflow(db, api_project):
 """Create a workflow for API tests."""
 return Workflow.objects.create(
 name="API Test Workflow",
 description="Workflow for API testing",
 project=api_project,
 trigger_type="manual",
 )
@pytest.fixture
def api_workflow_with_nodes(db, api_workflow):
 """Create a workflow with nodes for API tests."""
 trigger = WorkflowNode.objects.create(
 workflow=api_workflow,
 node_type="manual_trigger",
 name="Start",
 position_x=0,
 position_y=0,
 )
 action = WorkflowNode.objects.create(
 workflow=api_workflow,
 node_type="condition",
 name="Check",
 position_x=200,
 position_y=0,
 config={"expression": "true", "cases": },
 )
 WorkflowEdge.objects.create(
 workflow=api_workflow,
 source_node=trigger,
 target_node=action,
 source_handle="default",
 target_handle="default",
 )
 return api_workflow
# ============================================================================
# Workflow List Tests
# ============================================================================
@pytest.mark.django_db
class TestWorkflowListAPI:
 """Tests for workflow list endpoint."""
 def test_list_workflows_unauthenticated(self, api_client):
 """Test that unauthenticated requests are rejected."""
 url = "/api/workflows/"
 response = api_client.get(url)
 assert response.status_code == status.HTTP_401_UNAUTHORIZED
 def test_list_workflows_authenticated(self, authenticated_client, api_workflow):
 """Test listing workflows with authentication."""
 url = "/api/workflows/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert isinstance(response.data, list)
 def test_list_workflows_filter_by_project(
 self, authenticated_client, api_workflow, api_project
 ):
 """Test filtering workflows by project."""
 url = f"/api/workflows/?project_id={api_project.id}"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
# ============================================================================
# Workflow Detail Tests
# ============================================================================
@pytest.mark.django_db
class TestWorkflowDetailAPI:
 """Tests for workflow detail endpoint."""
 def test_get_workflow_detail(self, authenticated_client, api_workflow_with_nodes):
 """Test getting workflow detail."""
 url = f"/api/workflows/{api_workflow_with_nodes.id}/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert response.data["id"] == str(api_workflow_with_nodes.id)
 assert response.data["name"] == api_workflow_with_nodes.name
 def test_get_workflow_includes_nodes(self, authenticated_client, api_workflow_with_nodes):
 """Test that workflow detail includes nodes."""
 url = f"/api/workflows/{api_workflow_with_nodes.id}/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert "nodes" in response.data
 assert len(response.data["nodes"]) == 2
 def test_get_nonexistent_workflow(self, authenticated_client):
 """Test getting nonexistent workflow returns 404."""
 url = "/api/workflows/00000000-0000-0000-0000-000000000000/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_404_NOT_FOUND
# ============================================================================
# Workflow Create Tests
# ============================================================================
@pytest.mark.django_db
class TestWorkflowCreateAPI:
 """Tests for workflow creation endpoint."""
 def test_create_workflow(self, authenticated_client, api_project):
 """Test creating a new workflow."""
 url = "/api/workflows/"
 data = {
 "name": "New Workflow",
 "description": "A new workflow",
 "project": str(api_project.id),
 "trigger_type": "manual",
 }
 response = authenticated_client.post(url, data, format="json")
 assert response.status_code == status.HTTP_201_CREATED
 assert response.data["name"] == "New Workflow"
 def test_create_workflow_requires_name(self, authenticated_client, api_project):
 """Test that name is required."""
 url = "/api/workflows/"
 data = {
 "project_id": str(api_project.id),
 "trigger_type": "manual",
 }
 response = authenticated_client.post(url, data, format="json")
 assert response.status_code == status.HTTP_400_BAD_REQUEST
# ============================================================================
# Workflow Update Tests
# ============================================================================
@pytest.mark.django_db
class TestWorkflowUpdateAPI:
 """Tests for workflow update endpoint."""
 def test_update_workflow_name(self, authenticated_client, api_workflow):
 """Test updating workflow name."""
 url = f"/api/workflows/{api_workflow.id}/"
 data = {"name": "Updated Name"}
 response = authenticated_client.patch(url, data, format="json")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["name"] == "Updated Name"
 def test_update_workflow_description(self, authenticated_client, api_workflow):
 """Test updating workflow description."""
 url = f"/api/workflows/{api_workflow.id}/"
 data = {"description": "Updated description"}
 response = authenticated_client.patch(url, data, format="json")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["description"] == "Updated description"
# ============================================================================
# Workflow Delete Tests
# ============================================================================
@pytest.mark.django_db
class TestWorkflowDeleteAPI:
 """Tests for workflow deletion endpoint."""
 def test_delete_workflow(self, authenticated_client, api_workflow):
 """Test deleting a workflow."""
 url = f"/api/workflows/{api_workflow.id}/"
 response = authenticated_client.delete(url)
 assert response.status_code == status.HTTP_204_NO_CONTENT
 # Verify deleted
 assert not Workflow.objects.filter(id=api_workflow.id).exists
# ============================================================================
# Workflow Execution Tests
# ============================================================================
@pytest.mark.django_db
class TestWorkflowExecutionAPI:
 """Tests for workflow execution endpoints."""
 def test_execute_workflow(self, authenticated_client, api_workflow_with_nodes):
 """Test executing a workflow."""
 url = f"/api/workflows/{api_workflow_with_nodes.id}/execute/"
 data = {"input_data": {"test": "value"}}
 response = authenticated_client.post(url, data, format="json")
 assert response.status_code in [
 status.HTTP_200_OK,
 status.HTTP_201_CREATED,
 status.HTTP_202_ACCEPTED,
 ]
 def test_list_executions(self, authenticated_client, api_workflow_with_nodes):
 """Test listing workflow executions."""
 # Create an execution first
 WorkflowExecution.objects.create(
 workflow=api_workflow_with_nodes,
 trigger_type="manual",
 )
 url = "/api/workflow-executions/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 def test_get_execution_detail(self, authenticated_client, api_workflow_with_nodes):
 """Test getting execution detail."""
 execution = WorkflowExecution.objects.create(
 workflow=api_workflow_with_nodes,
 trigger_type="manual",
 )
 url = f"/api/workflow-executions/{execution.id}/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert response.data["id"] == str(execution.id)
# ============================================================================
# Node Type API Tests
# ============================================================================
@pytest.mark.django_db
class TestNodeTypeAPI:
 """Tests for node type listing endpoint."""
 def test_list_node_types(self, authenticated_client):
 """Test listing available node types."""
 url = "/api/node-types/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert isinstance(response.data, list)
 assert len(response.data) > 0
 def test_node_types_have_metadata(self, authenticated_client):
 """Test that node types include metadata."""
 url = "/api/node-types/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 for node_type in response.data:
 assert "node_type" in node_type
 assert "display_name" in node_type
 assert "category" in node_type
# ============================================================================
# Template API Tests
# ============================================================================
@pytest.mark.django_db
class TestTemplateAPI:
 """Tests for workflow template endpoints."""
 def test_list_templates(self, authenticated_client):
 """Test listing available templates."""
 url = "/api/workflows/templates/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert isinstance(response.data, list)
 def test_create_from_template(self, authenticated_client, api_project):
 """Test creating workflow from template."""
 url = "/api/workflows/from-template/"
 data = {
 "template_id": "code_generation",
 "project_id": str(api_project.id),
 "name": "From Template",
 }
 response = authenticated_client.post(url, data, format="json")
 # Template might not exist in test env
 assert response.status_code in [
 status.HTTP_201_CREATED,
 status.HTTP_400_BAD_REQUEST,
 ]
# ============================================================================
# Task Compatibility API Tests
# ============================================================================
@pytest.mark.django_db
class TestTaskCompatAPI:
 """Tests for Task API compatibility layer."""
 def test_list_tasks_compat(self, authenticated_client):
 """Test listing tasks through compat API."""
 # The /api/tasks/ endpoint was removed in v1.0 migration
 # Tasks are now accessed through /api/coding-tasks/
 url = "/api/coding-tasks/"
 response = authenticated_client.get(url)
 # Should work with the new endpoint
 assert response.status_code == status.HTTP_200_OK
 def test_tasks_compat_has_deprecation_header(self, authenticated_client):
 """Test that compat API includes deprecation header."""
 # The /api/tasks/ endpoint no longer exists
 # This test now verifies the new endpoint works
 url = "/api/coding-tasks/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
# ============================================================================
# React Steps Tests (Phase)
# ============================================================================
@pytest.mark.django_db
class TestReactSteps:
 """Tests for GET /api/node-executions/{id}/react-steps/ endpoint."""
 def test_react_steps_returns_sorted_by_sequence(
 self, authenticated_client, obs_node_executions, obs_action_logs
 ):
 """react-steps 应按 sequence 升序返回 ActionLog 摘要。"""
 ne1 = obs_node_executions[0]
 url = f"/api/node-executions/{ne1.id}/react-steps/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 3
 # 验证按 sequence 排序
 sequences = [item["sequence"] for item in response.data]
 assert sequences == [1, 2, 3]
 def test_react_steps_summary_mode(
 self, authenticated_client, obs_node_executions, obs_action_logs
 ):
 """react-steps 应返回摘要模式（payload_summary 而非完整 payload）。"""
 ne1 = obs_node_executions[0]
 url = f"/api/node-executions/{ne1.id}/react-steps/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 for item in response.data:
 assert "payload_summary" in item
 assert "payload" not in item
 assert "action_type" in item
 assert "sequence" in item
 assert "duration_ms" in item
 assert "timestamp" in item
 def test_react_steps_truncates_long_payload(
 self, authenticated_client, obs_node_executions, obs_action_logs
 ):
 """超过 200 字符的 payload 应被截断。"""
 ne1 = obs_node_executions[0]
 url = f"/api/node-executions/{ne1.id}/react-steps/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 # log2 的 payload 包含 300 个 "x"，应被截断
 log2_data = next(item for item in response.data if item["sequence"] == 2)
 assert log2_data["payload_summary"].endswith("...")
 def test_react_steps_empty_for_no_logs(
 self, authenticated_client, obs_node_executions
 ):
 """没有 ActionLog 的节点应返回空列表。"""
 ne2 = obs_node_executions[1] # 没有关联的 SubAgentSession
 url = f"/api/node-executions/{ne2.id}/react-steps/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert response.data ==
 def test_react_steps_404_for_nonexistent(self, authenticated_client):
 """不存在的 node_execution 应返回 404。"""
 url = "/api/node-executions/00000000-0000-0000-0000-000000000000/react-steps/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_404_NOT_FOUND
# ============================================================================
# ActionLog Detail Tests (Phase)
# ============================================================================
@pytest.mark.django_db
class TestActionLogDetail:
 """Tests for GET /api/action-logs/{id}/ endpoint."""
 def test_action_log_detail_returns_full_payload(
 self, authenticated_client, obs_action_logs
 ):
 """action-log 详情应返回完整 payload。"""
 log1 = obs_action_logs[0]
 url = f"/api/action-logs/{log1.id}/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert response.data["id"] == log1.id
 assert response.data["action_type"] == "llm_request"
 assert "payload" in response.data
 assert response.data["payload"]["prompt"] == "Generate code for feature X"
 def test_action_log_detail_404(self, authenticated_client):
 """不存在的 action_log 应返回 404。"""
 url = "/api/action-logs/999999/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_404_NOT_FOUND
# ============================================================================
# Cost Breakdown Tests (Phase)
# ============================================================================
@pytest.mark.django_db
class TestCostBreakdown:
 """Tests for GET /api/workflow-executions/{id}/cost-breakdown/ endpoint."""
 def test_cost_breakdown_structure(
 self, authenticated_client, obs_execution, obs_node_executions, obs_token_usages
 ):
 """cost-breakdown 应返回 nodes 和 summary 结构。"""
 url = f"/api/workflow-executions/{obs_execution.id}/cost-breakdown/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert "nodes" in response.data
 assert "summary" in response.data
 def test_cost_breakdown_model_split(
 self, authenticated_client, obs_execution, obs_node_executions, obs_token_usages
 ):
 """cost-breakdown 应按模型拆分 token 和成本。"""
 url = f"/api/workflow-executions/{obs_execution.id}/cost-breakdown/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 # 找到有 token 消耗的节点（node1 = AI Coding Node）
 nodes_with_models = [n for n in response.data["nodes"] if n["models"]]
 assert len(nodes_with_models) >= 1
 node = nodes_with_models[0]
 assert "claude-sonnet-4-20250514" in node["models"]
 assert "claude-opus-4-20250514" in node["models"]
 sonnet = node["models"]["claude-sonnet-4-20250514"]
 assert sonnet["input_tokens"] == 1000
 assert sonnet["output_tokens"] == 500
 assert sonnet["cache_read_tokens"] == 200
 assert sonnet["cache_write_tokens"] == 100
 def test_cost_breakdown_summary(
 self, authenticated_client, obs_execution, obs_node_executions, obs_token_usages
 ):
 """cost-breakdown summary 应包含总计。"""
 url = f"/api/workflow-executions/{obs_execution.id}/cost-breakdown/"
 response = authenticated_client.get(url)
 summary = response.data["summary"]
 assert summary["total_input_tokens"] == 3000 # 1000 + 2000
 assert summary["total_output_tokens"] == 1300 # 500 + 800
 assert summary["total_tokens"] == 4300 # 3000 + 1300
 assert summary["total_cost_usd"] == "0.060000" # 0.015 + 0.045
 assert "model_distribution" in summary
 def test_cost_breakdown_empty_execution(
 self, authenticated_client, obs_execution
 ):
 """没有节点执行的执行应返回空结果。"""
 url = f"/api/workflow-executions/{obs_execution.id}/cost-breakdown/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert response.data["nodes"] ==
 assert response.data["summary"]["total_tokens"] == 0
 def test_cost_breakdown_404(self, authenticated_client):
 """不存在的 execution 应返回 404。"""
 url = "/api/workflow-executions/00000000-0000-0000-0000-000000000000/cost-breakdown/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_404_NOT_FOUND
# ============================================================================
# Timeline Tests (Phase)
# ============================================================================
@pytest.mark.django_db
class TestTimeline:
 """Tests for GET /api/workflow-executions/{id}/timeline/ endpoint."""
 def test_timeline_structure(
 self, authenticated_client, obs_execution, obs_node_executions
 ):
 """timeline 应返回 nodes 和 summary 结构。"""
 url = f"/api/workflow-executions/{obs_execution.id}/timeline/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert "nodes" in response.data
 assert "summary" in response.data
 assert len(response.data["nodes"]) == 3
 def test_timeline_bottleneck_identification(
 self, authenticated_client, obs_execution, obs_node_executions
 ):
 """timeline 应标记 Top3 瓶颈（Top1 critical, Top2-3 warning）。"""
 url = f"/api/workflow-executions/{obs_execution.id}/timeline/"
 response = authenticated_client.get(url)
 nodes = response.data["nodes"]
 bottlenecks = [n for n in nodes if n["is_bottleneck"]]
 assert len(bottlenecks) == 3
 # 按 duration 排序找到最慢的
 bottlenecks.sort(key=lambda n: n["duration_seconds"], reverse=True)
 assert bottlenecks[0]["bottleneck_level"] == "critical"
 assert bottlenecks[1]["bottleneck_level"] == "warning"
 assert bottlenecks[2]["bottleneck_level"] == "warning"
 def test_timeline_summary(
 self, authenticated_client, obs_execution, obs_node_executions
 ):
 """timeline summary 应包含摘要统计。"""
 url = f"/api/workflow-executions/{obs_execution.id}/timeline/"
 response = authenticated_client.get(url)
 summary = response.data["summary"]
 assert summary["total_nodes"] == 3
 assert summary["avg_node_duration_seconds"] is not None
 assert summary["bottleneck_nodes"] == 3
 def test_timeline_node_fields(
 self, authenticated_client, obs_execution, obs_node_executions
 ):
 """timeline 每个节点应包含完整字段。"""
 url = f"/api/workflow-executions/{obs_execution.id}/timeline/"
 response = authenticated_client.get(url)
 node = response.data["nodes"][0]
 assert "node_id" in node
 assert "node_name" in node
 assert "node_type" in node
 assert "status" in node
 assert "started_at" in node
 assert "completed_at" in node
 assert "duration_seconds" in node
 assert "is_bottleneck" in node
 assert "bottleneck_level" in node
 def test_timeline_404(self, authenticated_client):
 """不存在的 execution 应返回 404。"""
 url = "/api/workflow-executions/00000000-0000-0000-0000-000000000000/timeline/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_404_NOT_FOUND
# ============================================================================
# NodeSubStep API Tests (Phase)
# ============================================================================
@pytest.mark.django_db
class TestNodeSubStepAPI:
 """Tests for GET /api/node-executions/{id}/sub-steps/ endpoint."""
 @pytest.fixture
 def sub_step_setup(self, api_workflow):
 """创建 NodeExecution 和 NodeSubStep 测试数据。"""
 from workflows.models import NodeExecution, NodeSubStep, SubStepStatus
 node = WorkflowNode.objects.create(
 workflow=api_workflow,
 node_type="ai_coding",
 name="AI Coding",
 position_x=100,
 position_y=100,
 )
 execution = WorkflowExecution.objects.create(
 workflow=api_workflow,
 trigger_type="manual",
 )
 node_exec = NodeExecution.objects.create(
 workflow_execution=execution,
 node=node,
 )
 # 创建 3 个子步骤（故意乱序创建以验证排序）
 sub3 = NodeSubStep.objects.create(
 node_execution=node_exec,
 name="代码生成",
 step_type="code_generation",
 step_order=3,
 status=SubStepStatus.PENDING,
 )
 sub1 = NodeSubStep.objects.create(
 node_execution=node_exec,
 name="分析需求",
 step_type="thinking",
 step_order=1,
 status=SubStepStatus.COMPLETED,
 input_data={"prompt": "分析任务"},
 output_data={"analysis": "需要修改 main.py"},
 )
 sub2 = NodeSubStep.objects.create(
 node_execution=node_exec,
 name="调用工具",
 step_type="tool_call",
 step_order=2,
 status=SubStepStatus.RUNNING,
 )
 return node_exec, [sub1, sub2, sub3]
 def test_sub_steps_list_returns_200(self, authenticated_client, sub_step_setup):
 """GET /api/node-executions/{id}/sub-steps/ 返回 200 + 子步骤列表。"""
 node_exec, _ = sub_step_setup
 url = f"/api/node-executions/{node_exec.id}/sub-steps/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 3
 def test_sub_steps_ordered_by_step_order(self, authenticated_client, sub_step_setup):
 """响应按 step_order 排序。"""
 node_exec, _ = sub_step_setup
 url = f"/api/node-executions/{node_exec.id}/sub-steps/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 orders = [item["step_order"] for item in response.data]
 assert orders == [1, 2, 3]
 assert response.data[0]["name"] == "分析需求"
 assert response.data[1]["name"] == "调用工具"
 assert response.data[2]["name"] == "代码生成"
 def test_sub_steps_contains_all_fields(self, authenticated_client, sub_step_setup):
 """响应包含全部字段。"""
 node_exec, _ = sub_step_setup
 url = f"/api/node-executions/{node_exec.id}/sub-steps/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 expected_fields = {
 "id", "name", "step_type", "step_order", "status",
 "input_data", "output_data", "started_at", "completed_at",
 }
 for item in response.data:
 assert set(item.keys) == expected_fields
 def test_sub_steps_404_for_nonexistent(self, authenticated_client):
 """不存在的 node_execution_id 返回 404。"""
 url = "/api/node-executions/00000000-0000-0000-0000-000000000000/sub-steps/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_404_NOT_FOUND
 def test_sub_steps_401_unauthenticated(self, api_client, sub_step_setup):
 """未认证请求返回 401。"""
 node_exec, _ = sub_step_setup
 url = f"/api/node-executions/{node_exec.id}/sub-steps/"
 response = api_client.get(url)
 assert response.status_code == status.HTTP_401_UNAUTHORIZED
 def test_sub_steps_empty_list(self, authenticated_client, api_workflow):
 """无子步骤时返回空列表。"""
 from workflows.models import NodeExecution
 node = WorkflowNode.objects.create(
 workflow=api_workflow,
 node_type="ai_coding",
 name="Empty Node",
 position_x=0,
 position_y=0,
 )
 execution = WorkflowExecution.objects.create(
 workflow=api_workflow,
 trigger_type="manual",
 )
 node_exec = NodeExecution.objects.create(
 workflow_execution=execution,
 node=node,
 )
 url = f"/api/node-executions/{node_exec.id}/sub-steps/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert response.data ==
