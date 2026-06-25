"""Tests for workflow API endpoints.

Tests cover:
- Workflow CRUD operations
- Workflow execution endpoints
- Node type listing
- Template API
- Approval endpoints
- Task compatibility API
"""

import uuid

import pytest
from rest_framework import status

from projects.models import Space
from workflows.models import (
    NodeExecution,
    NodeSubStep,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
)


@pytest.fixture
def api_project(db):
    """Create a project for API tests."""
    return Space.objects.create(
        name="API Test Space",
        description="Space for API testing",
    )


@pytest.fixture
def api_workflow(db, api_project):
    """Create a workflow for API tests."""
    return Workflow.objects.create(
        name="API Test Workflow",
        description="Workflow for API testing",
        space=api_project,
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
        config={"expression": "true", "cases": []},
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

    def test_list_workflows_authenticated(self, authenticated_admin_client, api_workflow):
        """Test listing workflows with authentication."""
        url = "/api/workflows/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)

    def test_list_workflows_filter_by_project(
        self, authenticated_admin_client, api_workflow, api_project
    ):
        """Test filtering workflows by project."""
        url = f"/api/workflows/?project_id={api_project.id}"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK


# ============================================================================
# Workflow Detail Tests
# ============================================================================


@pytest.mark.django_db
class TestWorkflowDetailAPI:
    """Tests for workflow detail endpoint."""

    def test_get_workflow_detail(self, authenticated_admin_client, api_workflow_with_nodes):
        """Test getting workflow detail."""
        url = f"/api/workflows/{api_workflow_with_nodes.id}/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(api_workflow_with_nodes.id)
        assert response.data["name"] == api_workflow_with_nodes.name

    def test_get_workflow_includes_nodes(self, authenticated_admin_client, api_workflow_with_nodes):
        """Test that workflow detail includes nodes."""
        url = f"/api/workflows/{api_workflow_with_nodes.id}/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "nodes" in response.data
        assert len(response.data["nodes"]) == 2

    def test_get_nonexistent_workflow(self, authenticated_admin_client):
        """Test getting nonexistent workflow returns 404."""
        url = "/api/workflows/00000000-0000-0000-0000-000000000000/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# Workflow Create Tests
# ============================================================================


@pytest.mark.django_db
class TestWorkflowCreateAPI:
    """Tests for workflow creation endpoint."""

    def test_create_workflow(self, authenticated_admin_client, api_project):
        """Test creating a new workflow."""
        url = "/api/workflows/"
        data = {
            "name": "New Workflow",
            "description": "A new workflow",
            "project": str(api_project.id),
            "trigger_type": "manual",
        }
        response = authenticated_admin_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "New Workflow"

    def test_create_workflow_requires_name(self, authenticated_admin_client, api_project):
        """Test that name is required."""
        url = "/api/workflows/"
        data = {
            "project_id": str(api_project.id),
            "trigger_type": "manual",
        }
        response = authenticated_admin_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ============================================================================
# Workflow Update Tests
# ============================================================================


@pytest.mark.django_db
class TestWorkflowUpdateAPI:
    """Tests for workflow update endpoint."""

    def test_update_workflow_name(self, authenticated_admin_client, api_workflow):
        """Test updating workflow name."""
        url = f"/api/workflows/{api_workflow.id}/"
        data = {"name": "Updated Name"}
        response = authenticated_admin_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Updated Name"

    def test_update_workflow_description(self, authenticated_admin_client, api_workflow):
        """Test updating workflow description."""
        url = f"/api/workflows/{api_workflow.id}/"
        data = {"description": "Updated description"}
        response = authenticated_admin_client.patch(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["description"] == "Updated description"


# ============================================================================
# Workflow Delete Tests
# ============================================================================


@pytest.mark.django_db
class TestWorkflowDeleteAPI:
    """Tests for workflow deletion endpoint."""

    def test_delete_workflow(self, authenticated_admin_client, api_workflow):
        """Test deleting a workflow."""
        url = f"/api/workflows/{api_workflow.id}/"
        response = authenticated_admin_client.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify deleted
        assert not Workflow.objects.filter(id=api_workflow.id).exists()


# ============================================================================
# Workflow Execution Tests
# ============================================================================


@pytest.mark.django_db
class TestWorkflowExecutionAPI:
    """Tests for workflow execution endpoints."""

    def test_execute_workflow(self, authenticated_admin_client, api_workflow_with_nodes):
        """Test executing a workflow."""
        url = f"/api/workflows/{api_workflow_with_nodes.id}/execute/"
        data = {"input_data": {"test": "value"}}
        response = authenticated_admin_client.post(url, data, format="json")

        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
            status.HTTP_202_ACCEPTED,
        ]

    def test_list_executions(self, authenticated_admin_client, api_workflow_with_nodes):
        """Test listing workflow executions."""
        # Create an execution first
        WorkflowExecution.objects.create(
            workflow=api_workflow_with_nodes,
            space=api_workflow_with_nodes.space,
            trigger_type="manual",
        )

        url = "/api/workflow-executions/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK

    def test_get_execution_detail(self, authenticated_admin_client, api_workflow_with_nodes):
        """Test getting execution detail."""
        execution = WorkflowExecution.objects.create(
            workflow=api_workflow_with_nodes,
            space=api_workflow_with_nodes.space,
            trigger_type="manual",
        )

        url = f"/api/workflow-executions/{execution.id}/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(execution.id)


# ============================================================================
# Execution Batch Delete Tests
# ============================================================================


@pytest.mark.django_db
class TestExecutionBatchDeleteAPI:
    """Tests for POST /api/workflow-executions/batch-delete/."""

    URL = "/api/workflow-executions/batch-delete/"

    def _create_execution(self, workflow, exec_status="completed"):
        return WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="manual",
            status=exec_status,
        )

    def test_superuser_can_batch_delete(self, authenticated_admin_client, api_workflow):
        """superuser 可批量删除已结束的执行。"""
        e1 = self._create_execution(api_workflow, "completed")
        e2 = self._create_execution(api_workflow, "failed")

        response = authenticated_admin_client.post(
            self.URL, {"ids": [str(e1.id), str(e2.id)]}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["deleted"] == 2
        assert WorkflowExecution.objects.filter(id__in=[e1.id, e2.id]).count() == 0

    def test_active_executions_are_skipped(self, authenticated_admin_client, api_workflow):
        """运行中/等待中的执行不会被删除。"""
        running = self._create_execution(api_workflow, "running")
        done = self._create_execution(api_workflow, "completed")

        response = authenticated_admin_client.post(
            self.URL, {"ids": [str(running.id), str(done.id)]}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["deleted"] == 1
        assert str(running.id) in response.data["skipped_active"]
        assert WorkflowExecution.objects.filter(id=running.id).exists()

    def test_non_admin_member_is_forbidden(self, authenticated_client, user, api_workflow):
        """空间普通成员（member）无权批量删除。"""
        from permissions.models import SpaceMembership, SpaceRole

        SpaceMembership.objects.create(
            user=user, space=api_workflow.space, role=SpaceRole.MEMBER
        )
        execution = self._create_execution(api_workflow, "completed")

        response = authenticated_client.post(self.URL, {"ids": [str(execution.id)]}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert WorkflowExecution.objects.filter(id=execution.id).exists()

    def test_project_admin_can_batch_delete(self, authenticated_client, user, api_workflow):
        """空间 admin 可以批量删除本空间的执行。"""
        from permissions.models import SpaceMembership, SpaceRole

        SpaceMembership.objects.create(
            user=user, space=api_workflow.space, role=SpaceRole.ADMIN
        )
        execution = self._create_execution(api_workflow, "cancelled")

        response = authenticated_client.post(self.URL, {"ids": [str(execution.id)]}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["deleted"] == 1
        assert not WorkflowExecution.objects.filter(id=execution.id).exists()

    def test_invalid_payload_rejected(self, authenticated_admin_client):
        """ids 缺失或非法时返回 400。"""
        assert (
            authenticated_admin_client.post(self.URL, {}, format="json").status_code
            == status.HTTP_400_BAD_REQUEST
        )
        assert (
            authenticated_admin_client.post(
                self.URL, {"ids": ["not-a-uuid"]}, format="json"
            ).status_code
            == status.HTTP_400_BAD_REQUEST
        )


# ============================================================================
# Validation Write-Path Tests (VAL-02)
# ============================================================================


def _vnode(node_type, *, config=None, name="N", short_id=None, node_id=None):
    """构造 bulk-update / dry-run 节点 dict（显式 UUID 以便边引用）。"""
    nd = {
        "id": node_id or str(uuid.uuid4()),
        "node_type": node_type,
        "name": name,
        "config": config or {},
    }
    if short_id:
        nd["short_id"] = short_id
    return nd


def _vedge(source, target, *, source_handle="default", target_handle="default", edge_id=None):
    """构造 bulk-update / dry-run 边 dict（UUID 空间 + 可选 edge id）。"""
    return {
        "id": edge_id or str(uuid.uuid4()),
        "source_node_id": source["id"],
        "target_node_id": target["id"],
        "source_handle": source_handle,
        "target_handle": target_handle,
    }


@pytest.mark.django_db
class TestWorkflowValidationAPI:
    """VAL-02：写入路径接入 WorkflowGraphValidator 的集成测试。

    覆盖 bulk-update 非法图结构化 400 + 事务回滚、合法图不误拒、单节点 create
    config 缺口闭合、dry-run 双端点、dry-run 与 bulk-update 同源（Pitfall 5）。
    """

    def _bulk_url(self, workflow):
        return f"/api/workflows/{workflow.id}/bulk-update/"

    def test_bulk_update_bad_config_returns_400_and_rolls_back(
        self, authenticated_admin_client, api_workflow
    ):
        """坏 config（http_request 缺必填 url）→ 400 结构化 errors + 回滚不落库。"""
        trigger = _vnode("manual_trigger", name="Start")
        bad = _vnode("http_request", config={}, name="Fetch")  # 缺 required url
        payload = {
            "nodes": [trigger, bad],
            "edges": [_vedge(trigger, bad)],
        }
        response = authenticated_admin_client.put(
            self._bulk_url(api_workflow), payload, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "errors" in response.data
        config_issues = [
            e for e in response.data["errors"] if str(e["reason"]) == "config_schema_invalid"
        ]
        assert config_issues, response.data["errors"]
        assert str(config_issues[0]["node_id"]) == bad["id"]
        assert str(config_issues[0]["field_path"]) == "config"
        # 事务回滚：一个节点都没落库
        assert api_workflow.nodes.count() == 0

    def test_bulk_update_bad_source_handle_returns_400(
        self, authenticated_admin_client, api_workflow
    ):
        """坏 source_handle（不在上游输出端口）→ 400，errors 含 invalid_source_handle。"""
        trigger = _vnode("manual_trigger", name="Start")
        prompt = _vnode("ai_prompt", config={"user_prompt": "hi"}, name="Prompt")
        edge = _vedge(trigger, prompt, source_handle="ghost_handle")
        payload = {"nodes": [trigger, prompt], "edges": [edge]}

        response = authenticated_admin_client.put(
            self._bulk_url(api_workflow), payload, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        handle_issues = [
            e for e in response.data["errors"] if str(e["reason"]) == "invalid_source_handle"
        ]
        assert handle_issues, response.data["errors"]
        assert str(handle_issues[0]["edge_id"]) == edge["id"]
        assert "source_handle" in str(handle_issues[0]["field_path"])
        assert api_workflow.nodes.count() == 0

    def test_bulk_update_unresolvable_variable_returns_400(
        self, authenticated_admin_client, api_workflow
    ):
        """不可解析 nodes.* 变量（引用幽灵节点）→ 400，errors 含 node_not_found。"""
        trigger = _vnode("manual_trigger", name="Start")
        prompt = _vnode(
            "ai_prompt",
            config={"user_prompt": "数据：{{nodes.ghost.x}}"},
            name="Prompt",
        )
        payload = {"nodes": [trigger, prompt], "edges": [_vedge(trigger, prompt)]}

        response = authenticated_admin_client.put(
            self._bulk_url(api_workflow), payload, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        var_issues = [e for e in response.data["errors"] if str(e["reason"]) == "node_not_found"]
        assert var_issues, response.data["errors"]
        assert str(var_issues[0]["node_id"]) == prompt["id"]
        assert str(var_issues[0]["field_path"]).startswith("config")
        assert api_workflow.nodes.count() == 0

    def test_bulk_update_valid_graph_saves_200(self, authenticated_admin_client, api_workflow):
        """合法工作流 bulk-update 保存零变化（不误拒）→ 200 + 落库成功。"""
        trigger = _vnode("manual_trigger", name="Start")
        prompt = _vnode("ai_prompt", config={"user_prompt": "你好"}, name="Prompt")
        payload = {
            "nodes": [trigger, prompt],
            "edges": [_vedge(trigger, prompt)],
            "delete_orphans": True,
        }

        response = authenticated_admin_client.put(
            self._bulk_url(api_workflow), payload, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert api_workflow.nodes.count() == 2
        assert api_workflow.edges.count() == 1

    def test_node_create_bad_config_returns_400(self, authenticated_admin_client, api_workflow):
        """单节点 create（WorkflowNodeCreateSerializer）坏 config → 400（闭合缺口）。"""
        url = f"/api/workflows/{api_workflow.id}/nodes/"
        data = {"node_type": "http_request", "name": "Fetch", "config": {}}  # 缺 required url
        response = authenticated_admin_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # 错误体引用缺失的必填字段（闭合缺口前此请求会 201 落库坏节点）
        assert "url" in str(response.data) or "config" in str(response.data)
        assert api_workflow.nodes.count() == 0

    def test_dry_run_draft_bad_graph_returns_errors_no_write(
        self, authenticated_admin_client, api_project
    ):
        """dry-run detail=False：坏图 → 200 + errors 非空，且不写库。"""
        url = "/api/workflows/validate/"
        trigger = _vnode("manual_trigger", name="Start")
        bad = _vnode("http_request", config={}, name="Fetch")
        payload = {"nodes": [trigger, bad], "edges": [_vedge(trigger, bad)]}

        before = Workflow.objects.count()
        response = authenticated_admin_client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["errors"]
        assert "warnings" in response.data
        # 未写库：workflow 数量不变
        assert Workflow.objects.count() == before

    def test_dry_run_detail_valid_draft_returns_empty_errors(
        self, authenticated_admin_client, api_workflow
    ):
        """dry-run detail=True：合法草图 → 200 + errors == []，不写库。"""
        url = f"/api/workflows/{api_workflow.id}/validate/"
        trigger = _vnode("manual_trigger", name="Start")
        prompt = _vnode("ai_prompt", config={"user_prompt": "ok"}, name="Prompt")
        payload = {"nodes": [trigger, prompt], "edges": [_vedge(trigger, prompt)]}

        response = authenticated_admin_client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["errors"] == []
        # 草图校验不落库
        assert api_workflow.nodes.count() == 0

    def test_dry_run_and_bulk_update_same_source(self, authenticated_admin_client, api_workflow):
        """Pitfall 5：同一坏图，dry-run errors reason 集合 == bulk-update 400 reason 集合。"""
        trigger = _vnode("manual_trigger", name="Start")
        prompt = _vnode("ai_prompt", config={"user_prompt": "hi"}, name="Prompt")
        edge = _vedge(trigger, prompt, source_handle="ghost_handle")
        payload = {"nodes": [trigger, prompt], "edges": [edge]}

        dry = authenticated_admin_client.post("/api/workflows/validate/", payload, format="json")
        assert dry.status_code == status.HTTP_200_OK
        dry_reasons = {str(e["reason"]) for e in dry.data["errors"]}

        bulk = authenticated_admin_client.put(self._bulk_url(api_workflow), payload, format="json")
        assert bulk.status_code == status.HTTP_400_BAD_REQUEST
        bulk_reasons = {str(e["reason"]) for e in bulk.data["errors"]}

        assert dry_reasons == bulk_reasons
        assert "invalid_source_handle" in dry_reasons


# ============================================================================
# Node Type API Tests
# ============================================================================


@pytest.mark.django_db
class TestNodeTypeAPI:
    """Tests for node type listing endpoint."""

    def test_list_node_types(self, authenticated_admin_client):
        """Test listing available node types."""
        url = "/api/node-types/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert len(response.data) > 0

    def test_node_types_have_metadata(self, authenticated_admin_client):
        """Test that node types include metadata."""
        url = "/api/node-types/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        for node_type in response.data:
            assert "node_type" in node_type
            assert "display_name" in node_type
            assert "category" in node_type

    def test_node_types_expose_ui_schema_and_default_config(self, authenticated_admin_client):
        """节点列表暴露 ui_schema/default_config，且无幽灵节点（SSOT-01）。"""
        url = "/api/node-types/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        by_type = {n["node_type"]: n for n in response.data}

        # 真实后端节点在、幽灵节点不在
        assert "fetch_space_info" in by_type
        assert "fetch_project_info" not in by_type

        for node_type in response.data:
            # 每节点都暴露新字段
            assert "ui_schema" in node_type
            assert "default_config" in node_type
            # default_config 的键 ⊆ config_schema.properties 的键
            props = (node_type["config_schema"] or {}).get("properties", {})
            assert set(node_type["default_config"]).issubset(set(props))


# ============================================================================
# Template API Tests
# ============================================================================


@pytest.mark.django_db
class TestTemplateAPI:
    """Tests for workflow template endpoints."""

    def test_list_templates_returns_4(self, authenticated_admin_client):
        """Template list should return 4 templates with metadata."""
        url = "/api/workflows/templates/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert len(response.data) == 4

        ids = {t["template_id"] for t in response.data}
        expected = {
            "code_generation",
            "feishu_full_pipeline",
            "daily_summary",
            "technical_plan_generation",
        }
        assert ids == expected

        for t in response.data:
            assert "name" in t
            assert "description" in t
            assert "version" in t

    def test_create_from_template_code_generation(self, authenticated_admin_client, api_project):
        """Creating workflow from code_generation template should succeed."""
        url = "/api/workflows/from-template/"
        data = {
            "template_id": "code_generation",
            "space_id": str(api_project.id),
            "name": "From Template",
        }
        response = authenticated_admin_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert "id" in response.data
        assert response.data["metadata"]["template_id"] == "code_generation"

    def test_create_from_template_daily_summary(self, authenticated_admin_client, api_project):
        """Creating workflow from daily_summary template should succeed."""
        url = "/api/workflows/from-template/"
        data = {
            "template_id": "daily_summary",
            "space_id": str(api_project.id),
        }
        response = authenticated_admin_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["metadata"]["template_id"] == "daily_summary"

        # Verify nodes were created
        workflow_id = response.data["id"]
        workflow = Workflow.objects.get(id=workflow_id)
        nodes = list(workflow.nodes.all())
        assert len(nodes) == 4

        node_types = {n.node_type for n in nodes}
        assert "webhook_trigger" in node_types
        assert "http_request" in node_types
        assert "ai_prompt" in node_types
        assert "notify_feishu" in node_types

    def test_create_from_template_missing_project_id(self, authenticated_admin_client):
        """Missing space_id should return 400."""
        url = "/api/workflows/from-template/"
        data = {
            "template_id": "code_generation",
        }
        response = authenticated_admin_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "space_id" in str(response.data) or "required" in str(response.data).lower()

    def test_create_from_template_unknown_template(self, authenticated_admin_client, api_project):
        """Unknown template_id should return 400."""
        url = "/api/workflows/from-template/"
        data = {
            "template_id": "non_existent_template",
            "space_id": str(api_project.id),
        }
        response = authenticated_admin_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ============================================================================
# Task Compatibility API Tests
# ============================================================================


@pytest.mark.django_db
class TestTaskCompatAPI:
    """Tests for Task API compatibility layer."""

    def test_list_tasks_compat(self, authenticated_admin_client):
        """Test listing tasks through compat API."""
        # The /api/tasks/ endpoint was removed in v1.0 migration
        # Tasks are now accessed through /api/coding-tasks/
        url = "/api/coding-tasks/"
        response = authenticated_admin_client.get(url)

        # Should work with the new endpoint
        assert response.status_code == status.HTTP_200_OK

    def test_tasks_compat_has_deprecation_header(self, authenticated_admin_client):
        """Test that compat API includes deprecation header."""
        # The /api/tasks/ endpoint no longer exists
        # This test now verifies the new endpoint works
        url = "/api/coding-tasks/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK


# ============================================================================
# React Steps Tests (implementation)
# ============================================================================


@pytest.mark.django_db
class TestReactSteps:
    """Tests for GET /api/node-executions/{id}/react-steps/ endpoint."""

    def test_react_steps_returns_sorted_by_sequence(
        self, authenticated_admin_client, obs_node_executions, obs_action_logs
    ):
        """react-steps 应按 sequence 升序返回 ActionLog 摘要。"""
        ne1 = obs_node_executions[0]
        url = f"/api/node-executions/{ne1.id}/react-steps/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3

        # 验证按 sequence 排序
        sequences = [item["sequence"] for item in response.data]
        assert sequences == [1, 2, 3]

    def test_react_steps_summary_mode(
        self, authenticated_admin_client, obs_node_executions, obs_action_logs
    ):
        """react-steps 应返回摘要模式（payload_summary 而非完整 payload）。"""
        ne1 = obs_node_executions[0]
        url = f"/api/node-executions/{ne1.id}/react-steps/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        for item in response.data:
            assert "payload_summary" in item
            assert "payload" not in item
            assert "action_type" in item
            assert "sequence" in item
            assert "duration_ms" in item
            assert "timestamp" in item

    def test_react_steps_truncates_long_payload(
        self, authenticated_admin_client, obs_node_executions, obs_action_logs
    ):
        """超过 200 字符的 payload 应被截断。"""
        ne1 = obs_node_executions[0]
        url = f"/api/node-executions/{ne1.id}/react-steps/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # log2 的 payload 包含 300 个 "x"，应被截断
        log2_data = next(item for item in response.data if item["sequence"] == 2)
        assert log2_data["payload_summary"].endswith("...")

    def test_react_steps_empty_for_no_logs(self, authenticated_admin_client, obs_node_executions):
        """没有 ActionLog 的节点应返回空列表。"""
        ne2 = obs_node_executions[1]  # 没有关联的 SubAgentSession
        url = f"/api/node-executions/{ne2.id}/react-steps/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_react_steps_404_for_nonexistent(self, authenticated_admin_client):
        """不存在的 node_execution 应返回 404。"""
        url = "/api/node-executions/00000000-0000-0000-0000-000000000000/react-steps/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# ActionLog Detail Tests (implementation)
# ============================================================================


@pytest.mark.django_db
class TestActionLogDetail:
    """Tests for GET /api/action-logs/{id}/ endpoint."""

    def test_action_log_detail_returns_full_payload(
        self, authenticated_admin_client, obs_action_logs
    ):
        """action-log 详情应返回完整 payload。"""
        log1 = obs_action_logs[0]
        url = f"/api/action-logs/{log1.id}/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == log1.id
        assert response.data["action_type"] == "llm_request"
        assert "payload" in response.data
        assert response.data["payload"]["prompt"] == "Generate code for feature X"

    def test_action_log_detail_404(self, authenticated_admin_client):
        """不存在的 action_log 应返回 404。"""
        url = "/api/action-logs/999999/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# Cost Breakdown Tests (implementation)
# ============================================================================


@pytest.mark.django_db
class TestCostBreakdown:
    """Tests for GET /api/workflow-executions/{id}/cost-breakdown/ endpoint."""

    def test_cost_breakdown_structure(
        self, authenticated_admin_client, obs_execution, obs_node_executions, obs_token_usages
    ):
        """cost-breakdown 应返回 nodes 和 summary 结构。"""
        url = f"/api/workflow-executions/{obs_execution.id}/cost-breakdown/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "nodes" in response.data
        assert "summary" in response.data

    def test_cost_breakdown_model_split(
        self, authenticated_admin_client, obs_execution, obs_node_executions, obs_token_usages
    ):
        """cost-breakdown 应按模型拆分 token 和成本。"""
        url = f"/api/workflow-executions/{obs_execution.id}/cost-breakdown/"
        response = authenticated_admin_client.get(url)

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
        self, authenticated_admin_client, obs_execution, obs_node_executions, obs_token_usages
    ):
        """cost-breakdown summary 应包含总计。"""
        url = f"/api/workflow-executions/{obs_execution.id}/cost-breakdown/"
        response = authenticated_admin_client.get(url)

        summary = response.data["summary"]
        assert summary["total_input_tokens"] == 3000  # 1000 + 2000
        assert summary["total_output_tokens"] == 1300  # 500 + 800
        assert summary["total_tokens"] == 4300  # 3000 + 1300
        assert summary["total_cost_usd"] == "0.060000"  # 0.015 + 0.045
        assert "model_distribution" in summary

    def test_cost_breakdown_empty_execution(self, authenticated_admin_client, obs_execution):
        """没有节点执行的执行应返回空结果。"""
        url = f"/api/workflow-executions/{obs_execution.id}/cost-breakdown/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["nodes"] == []
        assert response.data["summary"]["total_tokens"] == 0

    def test_cost_breakdown_404(self, authenticated_admin_client):
        """不存在的 execution 应返回 404。"""
        url = "/api/workflow-executions/00000000-0000-0000-0000-000000000000/cost-breakdown/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# Timeline Tests (implementation)
# ============================================================================


@pytest.mark.django_db
class TestTimeline:
    """Tests for GET /api/workflow-executions/{id}/timeline/ endpoint."""

    def test_timeline_structure(
        self, authenticated_admin_client, obs_execution, obs_node_executions
    ):
        """timeline 应返回 nodes 和 summary 结构。"""
        url = f"/api/workflow-executions/{obs_execution.id}/timeline/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "nodes" in response.data
        assert "summary" in response.data
        assert len(response.data["nodes"]) == 3

    def test_timeline_bottleneck_identification(
        self, authenticated_admin_client, obs_execution, obs_node_executions
    ):
        """timeline 应标记 Top3 瓶颈（Top1 critical, Top2-3 warning）。"""
        url = f"/api/workflow-executions/{obs_execution.id}/timeline/"
        response = authenticated_admin_client.get(url)

        nodes = response.data["nodes"]
        bottlenecks = [n for n in nodes if n["is_bottleneck"]]
        assert len(bottlenecks) == 3

        # 按 duration 排序找到最慢的
        bottlenecks.sort(key=lambda n: n["duration_seconds"], reverse=True)
        assert bottlenecks[0]["bottleneck_level"] == "critical"
        assert bottlenecks[1]["bottleneck_level"] == "warning"
        assert bottlenecks[2]["bottleneck_level"] == "warning"

    def test_timeline_summary(self, authenticated_admin_client, obs_execution, obs_node_executions):
        """timeline summary 应包含摘要统计。"""
        url = f"/api/workflow-executions/{obs_execution.id}/timeline/"
        response = authenticated_admin_client.get(url)

        summary = response.data["summary"]
        assert summary["total_nodes"] == 3
        assert summary["avg_node_duration_seconds"] is not None
        assert summary["bottleneck_nodes"] == 3

    def test_timeline_node_fields(
        self, authenticated_admin_client, obs_execution, obs_node_executions
    ):
        """timeline 每个节点应包含完整字段。"""
        url = f"/api/workflow-executions/{obs_execution.id}/timeline/"
        response = authenticated_admin_client.get(url)

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

    def test_timeline_404(self, authenticated_admin_client):
        """不存在的 execution 应返回 404。"""
        url = "/api/workflow-executions/00000000-0000-0000-0000-000000000000/timeline/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# NodeSubStep API Tests
# ============================================================================


@pytest.mark.django_db
class TestNodeSubStepAPI:
    """Tests for GET /api/node-executions/{id}/sub-steps/ endpoint."""

    @pytest.fixture
    def sub_step_data(self, api_project, user):
        """创建带子步骤的 NodeExecution 测试数据。"""
        workflow = Workflow.objects.create(
            name="SubStep Test Workflow",
            space=api_project,
            created_by=user,
        )
        node = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="ai_coding",
            name="AI Node",
            position_x=100,
            position_y=100,
        )
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="manual",
            triggered_by=user,
        )
        node_execution = NodeExecution.objects.create(
            workflow_execution=execution,
            node=node,
        )
        # 创建三个子步骤（乱序创建，验证排序）
        sub3 = NodeSubStep.objects.create(
            node_execution=node_execution,
            name="代码生成",
            step_type="code_generation",
            step_order=3,
            status="completed",
            input_data={"prompt": "生成代码"},
            output_data={"code": "print('hello')"},
        )
        sub1 = NodeSubStep.objects.create(
            node_execution=node_execution,
            name="思考分析",
            step_type="thinking",
            step_order=1,
            status="completed",
            input_data={"context": "分析需求"},
            output_data={"analysis": "需要生成Python代码"},
        )
        sub2 = NodeSubStep.objects.create(
            node_execution=node_execution,
            name="调用工具",
            step_type="tool_call",
            step_order=2,
            status="running",
        )
        return {
            "node_execution": node_execution,
            "sub_steps": [sub1, sub2, sub3],
        }

    def test_list_sub_steps(self, authenticated_admin_client, sub_step_data):
        """GET /api/node-executions/{id}/sub-steps/ 返回子步骤列表。"""
        ne = sub_step_data["node_execution"]
        url = f"/api/node-executions/{ne.id}/sub-steps/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3

    def test_sub_steps_ordering(self, authenticated_admin_client, sub_step_data):
        """子步骤按 step_order 排序返回。"""
        ne = sub_step_data["node_execution"]
        url = f"/api/node-executions/{ne.id}/sub-steps/"
        response = authenticated_admin_client.get(url)

        assert response.data[0]["step_order"] == 1
        assert response.data[0]["name"] == "思考分析"
        assert response.data[1]["step_order"] == 2
        assert response.data[1]["name"] == "调用工具"
        assert response.data[2]["step_order"] == 3
        assert response.data[2]["name"] == "代码生成"

    def test_sub_step_full_fields(self, authenticated_admin_client, sub_step_data):
        """响应包含全部字段。"""
        ne = sub_step_data["node_execution"]
        url = f"/api/node-executions/{ne.id}/sub-steps/"
        response = authenticated_admin_client.get(url)

        step = response.data[0]
        expected_fields = {
            "id",
            "name",
            "step_type",
            "step_order",
            "status",
            "input_data",
            "output_data",
            "started_at",
            "completed_at",
        }
        assert set(step.keys()) == expected_fields

    def test_sub_step_data_values(self, authenticated_admin_client, sub_step_data):
        """响应数据值正确。"""
        ne = sub_step_data["node_execution"]
        url = f"/api/node-executions/{ne.id}/sub-steps/"
        response = authenticated_admin_client.get(url)

        step1 = response.data[0]
        assert step1["step_type"] == "thinking"
        assert step1["status"] == "completed"
        assert step1["input_data"] == {"context": "分析需求"}
        assert step1["output_data"] == {"analysis": "需要生成Python代码"}

    def test_nonexistent_node_execution_404(self, authenticated_admin_client):
        """不存在的 node_execution_id 返回 404。"""
        url = "/api/node-executions/00000000-0000-0000-0000-000000000000/sub-steps/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_unauthenticated_401(self, api_client, sub_step_data):
        """未认证请求返回 401。"""
        ne = sub_step_data["node_execution"]
        url = f"/api/node-executions/{ne.id}/sub-steps/"
        response = api_client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_empty_sub_steps(self, authenticated_admin_client, api_project, user):
        """无子步骤时返回空列表。"""
        workflow = Workflow.objects.create(
            name="Empty SubStep Workflow",
            space=api_project,
            created_by=user,
        )
        node = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="ai_coding",
            name="AI Node",
            position_x=100,
            position_y=100,
        )
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="manual",
        )
        node_execution = NodeExecution.objects.create(
            workflow_execution=execution,
            node=node,
        )

        url = f"/api/node-executions/{node_execution.id}/sub-steps/"
        response = authenticated_admin_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []
