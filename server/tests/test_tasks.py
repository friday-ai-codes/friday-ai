"""任务端点测试。
使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""
import uuid
import pytest
from rest_framework import status
from tasks.models import Task, TaskStatus
# ============================================================================
# 任务列表和创建测试
# ============================================================================
@pytest.mark.django_db
class TestTaskListCreate:
 """任务列表和创建接口测试。"""
 def test_list_tasks_empty(self, authenticated_client, urls):
 """测试空任务列表。"""
 response = authenticated_client.get(urls.task_list)
 assert response.status_code == status.HTTP_200_OK
 assert response.data ==
 def test_list_tasks_with_data(self, authenticated_client, task, urls):
 """测试有数据的任务列表。"""
 response = authenticated_client.get(urls.task_list)
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 1
 assert response.data[0]["title"] == "Test Task"
 def test_list_tasks_filter_by_project(self, authenticated_client, task, project, urls):
 """测试按项目过滤任务。"""
 response = authenticated_client.get(f"{urls.task_list}?project_id={project.id}")
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 1
 def test_list_tasks_filter_by_status(self, authenticated_client, task, urls):
 """测试按状态过滤任务。"""
 response = authenticated_client.get(f"{urls.task_list}?status=pending")
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 1
 def test_create_task(self, authenticated_client, project, repository, urls):
 """测试创建任务。"""
 response = authenticated_client.post(
 urls.task_list,
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
 def test_create_task_duplicate_work_item(self, authenticated_client, task, project, urls):
 """测试创建重复 work_item_id 的任务失败。"""
 response = authenticated_client.post(
 urls.task_list,
 {
 "project_id": str(project.id),
 "work_item_id": task.work_item_id,
 "title": "Duplicate Task",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
# ============================================================================
# 任务详情测试
# ============================================================================
@pytest.mark.django_db
class TestTaskDetail:
 """任务详情接口测试。"""
 def test_get_task(self, authenticated_client, task, urls):
 """测试获取单个任务。"""
 response = authenticated_client.get(urls.task_detail(task.id))
 assert response.status_code == status.HTTP_200_OK
 assert response.data["title"] == "Test Task"
 def test_get_task_by_work_item(self, authenticated_client, task, urls):
 """测试通过 work_item_id 获取任务。"""
 response = authenticated_client.get(urls.task_work_item(task.work_item_id))
 assert response.status_code == status.HTTP_200_OK
 assert response.data["title"] == "Test Task"
 def test_update_task(self, authenticated_client, task, urls):
 """测试更新任务。"""
 response = authenticated_client.patch(
 urls.task_detail(task.id),
 {"title": "Updated Task"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["title"] == "Updated Task"
 def test_delete_task(self, authenticated_client, task, urls):
 """测试删除任务。"""
 response = authenticated_client.delete(urls.task_detail(task.id))
 assert response.status_code == status.HTTP_204_NO_CONTENT
# ============================================================================
# 任务状态转换测试
# ============================================================================
@pytest.mark.django_db
class TestTaskStatusTransition:
 """任务状态转换接口测试。"""
 def test_valid_transition_pending_to_planning(self, authenticated_client, task, urls):
 """测试有效的状态转换：PENDING → PLANNING。"""
 response = authenticated_client.post(urls.task_transition(task.id, "planning"))
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == TaskStatus.PLANNING
 assert response.data["plan_started_at"] is not None
 def test_valid_transition_planning_to_plan_review(self, authenticated_client, task, urls):
 """测试有效的状态转换：PLANNING → PLAN_REVIEW。"""
 # 先转换到 planning
 authenticated_client.post(urls.task_transition(task.id, "planning"))
 response = authenticated_client.post(urls.task_transition(task.id, "plan_review"))
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == TaskStatus.PLAN_REVIEW
 def test_invalid_transition_pending_to_executing(self, authenticated_client, task, urls):
 """测试无效的状态转换：PENDING → EXECUTING。"""
 response = authenticated_client.post(urls.task_transition(task.id, "executing"))
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 assert "Cannot transition" in response.data["detail"]
 def test_transition_to_failed_increments_retry(self, authenticated_client, task, urls):
 """测试转换到 FAILED 状态会增加 retry_count。"""
 initial_retry = task.retry_count
 response = authenticated_client.post(urls.task_transition(task.id, "failed"))
 assert response.status_code == status.HTTP_200_OK
 assert response.data["retry_count"] == initial_retry + 1
# ============================================================================
# 任务执行测试
# ============================================================================
@pytest.mark.django_db
class TestTaskExecution:
 """任务执行接口测试。"""
 def test_execute_task_without_repository(
 self, authenticated_client, project_without_repo, urls
 ):
 """测试无仓库的任务执行失败。"""
 task = Task.objects.create(
 project=project_without_repo,
 work_item_id="no-repo-task",
 title="No Repo Task",
 )
 response = authenticated_client.post(
 urls.task_execute(task.id), {"mode": "plan"}, format="json"
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 assert "repository" in response.data["detail"].lower
 def test_execute_task_wrong_status(self, authenticated_client, task_with_repository, urls):
 """测试错误状态的任务执行失败。"""
 # 先转换到 PLANNING
 authenticated_client.post(urls.task_transition(task_with_repository.id, "planning"))
 response = authenticated_client.post(
 urls.task_execute(task_with_repository.id), {"mode": "plan"}, format="json"
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_stop_task(self, authenticated_client, task, urls):
 """测试停止任务。"""
 response = authenticated_client.post(urls.task_stop(task.id))
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "stopped"
 def test_get_task_logs(self, authenticated_client, task, urls):
 """测试获取任务日志。"""
 response = authenticated_client.get(urls.task_logs(task.id))
 assert response.status_code == status.HTTP_200_OK
 assert "logs" in response.data
 def test_get_container_status(self, authenticated_client, task, urls):
 """测试获取容器状态。"""
 response = authenticated_client.get(urls.task_container_status(task.id))
 assert response.status_code == status.HTTP_200_OK
 assert "container" in response.data
# ============================================================================
# 任务状态回调测试
# ============================================================================
@pytest.mark.django_db
class TestTaskStatusCallback:
 """任务状态回调接口测试（来自容器）。"""
 def test_status_callback_plan_ready(self, api_client, task, urls):
 """测试计划就绪状态回调。"""
 response = api_client.post(
 urls.task_status_callback(task.id),
 {
 "task_id": str(task.id),
 "status": "plan_ready",
 "details": {"plan": "Implementation plan content"},
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["task_status"] == TaskStatus.PLAN_REVIEW
 # 验证任务已更新
 task.refresh_from_db
 assert task.plan_output == "Implementation plan content"
 def test_status_callback_error(self, api_client, task, urls):
 """测试错误状态回调。"""
 response = api_client.post(
 urls.task_status_callback(task.id),
 {
 "task_id": str(task.id),
 "status": "error",
 "message": "Execution failed",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["task_status"] == TaskStatus.FAILED
 def test_status_callback_unknown_task(self, api_client, urls):
 """测试未知任务的状态回调。"""
 response = api_client.post(
 urls.task_status_callback(uuid.uuid4),
 {
 "task_id": "unknown",
 "status": "started",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "ignored"
