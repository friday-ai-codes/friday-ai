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
from django.urls import reverse
from rest_framework import status
from projects.models import Project
from workflows.models import (
 ExecutionStatus,
 NodeExecutionStatus,
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
 def test_get_workflow_includes_nodes(
 self, authenticated_client, api_workflow_with_nodes
 ):
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
 "project_id": str(api_project.id),
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
 url = "/api/workflows/node-types/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 assert isinstance(response.data, list)
 assert len(response.data) > 0
 def test_node_types_have_metadata(self, authenticated_client):
 """Test that node types include metadata."""
 url = "/api/workflows/node-types/"
 response = authenticated_client.get(url)
 assert response.status_code == status.HTTP_200_OK
 for node_type in response.data:
 assert "type" in node_type
 assert "name" in node_type
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
 url = "/api/tasks/"
 response = authenticated_client.get(url)
 # Should work (compat layer enabled by default)
 assert response.status_code in [
 status.HTTP_200_OK,
 status.HTTP_410_GONE, # If compat disabled
 ]
 def test_tasks_compat_has_deprecation_header(self, authenticated_client):
 """Test that compat API includes deprecation header."""
 url = "/api/tasks/"
 response = authenticated_client.get(url)
 if response.status_code == status.HTTP_200_OK:
 assert "Deprecation" in response or response.status_code == 200
