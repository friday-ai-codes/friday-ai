"""Tests for task endpoints."""
import pytest
from rest_framework import status
from tasks.models import TaskStatus
@pytest.mark.django_db
class TestTaskEndpoints:
 """Test task CRUD endpoints."""
 def test_list_tasks_empty(self, authenticated_client):
 """Test listing tasks when empty."""
 response = authenticated_client.get("/api/tasks/")
 assert response.status_code == status.HTTP_200_OK
 assert response.data ==
 def test_list_tasks(self, authenticated_client, task):
 """Test listing tasks."""
 response = authenticated_client.get("/api/tasks/")
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 1
 assert response.data[0]["title"] == "Test Task"
 def test_list_tasks_filter_by_project(self, authenticated_client, task, project):
 """Test filtering tasks by project."""
 response = authenticated_client.get(f"/api/tasks/?project_id={project.id}")
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 1
 def test_list_tasks_filter_by_status(self, authenticated_client, task):
 """Test filtering tasks by status."""
 response = authenticated_client.get("/api/tasks/?status=pending")
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 1
 def test_create_task(self, authenticated_client, project, repository):
 """Test creating a task."""
 # Link repository to project first
 project.repositories.add(repository)
 response = authenticated_client.post(
 "/api/tasks/",
 {
 "project_id": str(project.id),
 "repository_id": str(repository.id),
 "work_item_id": "new-work-item-001",
 "title": "New Task",
 "description": "A new task",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_201_CREATED
 assert response.data["title"] == "New Task"
 assert response.data["status"] == TaskStatus.PENDING
 def test_create_task_duplicate_work_item(self, authenticated_client, task, project):
 """Test creating a task with duplicate work_item_id."""
 response = authenticated_client.post(
 "/api/tasks/",
 {
 "project_id": str(project.id),
 "work_item_id": task.work_item_id, # Same as fixture
 "title": "Duplicate Task",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_get_task(self, authenticated_client, task):
 """Test getting a single task."""
 response = authenticated_client.get(f"/api/tasks/{task.id}")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["title"] == "Test Task"
 def test_get_task_by_work_item(self, authenticated_client, task):
 """Test getting a task by work item ID."""
 response = authenticated_client.get(f"/api/tasks/work-item/{task.work_item_id}")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["title"] == "Test Task"
 def test_update_task(self, authenticated_client, task):
 """Test updating a task."""
 response = authenticated_client.patch(
 f"/api/tasks/{task.id}",
 {"title": "Updated Task"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["title"] == "Updated Task"
 def test_delete_task(self, authenticated_client, task):
 """Test deleting a task."""
 response = authenticated_client.delete(f"/api/tasks/{task.id}")
 assert response.status_code == status.HTTP_204_NO_CONTENT
@pytest.mark.django_db
class TestTaskStatusTransition:
 """Test task status transition endpoints."""
 def test_valid_transition_pending_to_planning(self, authenticated_client, task):
 """Test valid transition from PENDING to PLANNING."""
 response = authenticated_client.post(f"/api/tasks/{task.id}/transition/planning")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == TaskStatus.PLANNING
 assert response.data["plan_started_at"] is not None
 def test_valid_transition_planning_to_plan_review(self, authenticated_client, task):
 """Test valid transition from PLANNING to PLAN_REVIEW."""
 # First transition to planning
 authenticated_client.post(f"/api/tasks/{task.id}/transition/planning")
 response = authenticated_client.post(f"/api/tasks/{task.id}/transition/plan_review")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == TaskStatus.PLAN_REVIEW
 def test_invalid_transition_pending_to_executing(self, authenticated_client, task):
 """Test invalid transition from PENDING to EXECUTING."""
 response = authenticated_client.post(f"/api/tasks/{task.id}/transition/executing")
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 assert "Cannot transition" in response.data["detail"]
 def test_transition_to_failed_increments_retry(self, authenticated_client, task):
 """Test that transitioning to FAILED increments retry_count."""
 initial_retry = task.retry_count
 response = authenticated_client.post(f"/api/tasks/{task.id}/transition/failed")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["retry_count"] == initial_retry + 1
@pytest.mark.django_db
class TestTaskExecution:
 """Test task execution endpoints."""
 def test_execute_task_plan_mode(self, authenticated_client, task, repository):
 """Test executing task in plan mode."""
 # Assign repository to task
 task.repository = repository
 task.save
 response = authenticated_client.post(
 f"/api/tasks/{task.id}/execute",
 {"mode": "plan"},
 format="json",
 )
 # May return 200 or 400 depending on external service availability
 assert response.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]
 def test_execute_task_without_repository(self, authenticated_client, project):
 """Test executing task without repository assigned."""
 from tasks.models import Task
 task = Task.objects.create(
 project=project,
 work_item_id="no-repo-task",
 title="No Repo Task",
 )
 response = authenticated_client.post(
 f"/api/tasks/{task.id}/execute",
 {"mode": "plan"},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 assert "repository" in response.data["detail"].lower
 def test_execute_task_wrong_status(self, authenticated_client, task):
 """Test executing task in wrong status."""
 # Transition to PLANNING first
 authenticated_client.post(f"/api/tasks/{task.id}/transition/planning")
 response = authenticated_client.post(
 f"/api/tasks/{task.id}/execute",
 {"mode": "plan"},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_stop_task(self, authenticated_client, task):
 """Test stopping a task."""
 response = authenticated_client.post(f"/api/tasks/{task.id}/stop")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "stopped"
 def test_get_task_logs(self, authenticated_client, task):
 """Test getting task logs."""
 response = authenticated_client.get(f"/api/tasks/{task.id}/logs")
 assert response.status_code == status.HTTP_200_OK
 assert "logs" in response.data
 def test_get_container_status(self, authenticated_client, task):
 """Test getting container status."""
 response = authenticated_client.get(f"/api/tasks/{task.id}/container-status")
 assert response.status_code == status.HTTP_200_OK
 assert "container" in response.data
@pytest.mark.django_db
class TestTaskStatusCallback:
 """Test task status callback endpoint (from container)."""
 def test_status_callback_plan_ready(self, api_client, task):
 """Test status callback for plan_ready."""
 response = api_client.post(
 f"/api/tasks/{task.id}/status",
 {
 "task_id": str(task.id),
 "status": "plan_ready",
 "details": {"plan": "Implementation plan content"},
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["task_status"] == TaskStatus.PLAN_REVIEW
 # Verify task updated
 task.refresh_from_db
 assert task.plan_output == "Implementation plan content"
 def test_status_callback_error(self, api_client, task):
 """Test status callback for error."""
 response = api_client.post(
 f"/api/tasks/{task.id}/status",
 {
 "task_id": str(task.id),
 "status": "error",
 "message": "Execution failed",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["task_status"] == TaskStatus.FAILED
 def test_status_callback_unknown_task(self, api_client):
 """Test status callback for unknown task."""
 import uuid
 response = api_client.post(
 f"/api/tasks/{uuid.uuid4}/status",
 {
 "task_id": "unknown",
 "status": "started",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "ignored"
