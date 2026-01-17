"""API endpoint tests."""
import pytest
from httpx import AsyncClient
@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
 """Test health check endpoint."""
 response = await client.get("/health")
 assert response.status_code == 200
 data = response.json
 assert data["status"] == "ok"
@pytest.mark.asyncio
async def test_create_project(client: AsyncClient):
 """Test project creation."""
 project_data = {
 "name": "Test Project",
 "feishu_project_key": "test-feishu-123",
 }
 response = await client.post("/api/projects/", json=project_data)
 assert response.status_code == 201
 data = response.json
 assert data["name"] == "Test Project"
 assert data["feishu_project_key"] == "test-feishu-123"
 assert "id" in data
@pytest.mark.asyncio
async def test_list_projects(client: AsyncClient):
 """Test project listing."""
 # Create a project first
 project_data = {
 "name": "List Test Project",
 }
 create_resp = await client.post("/api/projects/", json=project_data)
 assert create_resp.status_code == 201
 # List projects
 response = await client.get("/api/projects/")
 assert response.status_code == 200
 data = response.json
 assert isinstance(data, list)
 assert len(data) >= 1
@pytest.mark.asyncio
async def test_get_project(client: AsyncClient):
 """Test getting a single project."""
 # Create a project first
 project_data = {
 "name": "Get Test Project",
 }
 create_response = await client.post("/api/projects/", json=project_data)
 assert create_response.status_code == 201
 project_id = create_response.json["id"]
 # Get the project
 response = await client.get(f"/api/projects/{project_id}")
 assert response.status_code == 200
 data = response.json
 assert data["id"] == project_id
 assert data["name"] == "Get Test Project"
@pytest.mark.asyncio
async def test_get_nonexistent_project(client: AsyncClient):
 """Test getting a non-existent project."""
 response = await client.get("/api/projects/nonexistent-id")
 assert response.status_code == 404
@pytest.mark.asyncio
async def test_create_task(client: AsyncClient):
 """Test task creation."""
 # Create a project first
 project_data = {
 "name": "Task Test Project",
 }
 project_response = await client.post("/api/projects/", json=project_data)
 assert project_response.status_code == 201
 project_id = project_response.json["id"]
 # Create a task
 task_data = {
 "project_id": project_id,
 "work_item_id": "work-item-123",
 "feature_id": "F001",
 "title": "Test Task",
 "description": "This is a test task",
 }
 response = await client.post("/api/tasks/", json=task_data)
 assert response.status_code == 201
 data = response.json
 assert data["title"] == "Test Task"
 assert data["status"] == "pending"
 assert data["project_id"] == project_id
@pytest.mark.asyncio
async def test_task_status_transition(client: AsyncClient):
 """Test task status transitions."""
 # Create a project and task
 project_data = {
 "name": "Transition Test Project",
 }
 project_response = await client.post("/api/projects/", json=project_data)
 assert project_response.status_code == 201
 project_id = project_response.json["id"]
 task_data = {
 "project_id": project_id,
 "work_item_id": "transition-work-item",
 "feature_id": "F002",
 "title": "Transition Test Task",
 }
 task_response = await client.post("/api/tasks/", json=task_data)
 assert task_response.status_code == 201
 task_id = task_response.json["id"]
 # Transition to planning
 response = await client.post(f"/api/tasks/{task_id}/transition/planning")
 assert response.status_code == 200
 assert response.json["status"] == "planning"
 # Transition to plan_review
 response = await client.post(f"/api/tasks/{task_id}/transition/plan_review")
 assert response.status_code == 200
 assert response.json["status"] == "plan_review"
@pytest.mark.asyncio
async def test_invalid_task_transition(client: AsyncClient):
 """Test invalid task status transition."""
 # Create a project and task
 project_data = {
 "name": "Invalid Transition Project",
 }
 project_response = await client.post("/api/projects/", json=project_data)
 assert project_response.status_code == 201
 project_id = project_response.json["id"]
 task_data = {
 "project_id": project_id,
 "work_item_id": "invalid-transition-item",
 "feature_id": "F003",
 "title": "Invalid Transition Task",
 }
 task_response = await client.post("/api/tasks/", json=task_data)
 assert task_response.status_code == 201
 task_id = task_response.json["id"]
 # Try invalid transition (pending -> executing)
 response = await client.post(f"/api/tasks/{task_id}/transition/executing")
 assert response.status_code == 400
@pytest.mark.asyncio
async def test_feishu_webhook_challenge(client: AsyncClient):
 """Test Feishu webhook challenge verification."""
 challenge_data = {
 "challenge": "test-challenge-token",
 "token": "test_token",
 "type": "url_verification",
 }
 response = await client.post("/api/webhook/feishu", json=challenge_data)
 assert response.status_code == 200
 data = response.json
 assert data["challenge"] == "test-challenge-token"
