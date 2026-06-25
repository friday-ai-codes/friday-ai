"""WorkflowExecution 三步租户迁移正确性测试。"""

import pytest
from django.db import connection

from workflows.models.execution import WorkflowExecution
from workflows.models.workflow import Workflow


@pytest.fixture
def workflow(db, project, user):
    """创建测试工作流。"""
    return Workflow.objects.create(
        name="Test Workflow",
        space=project,
        created_by=user,
        trigger_type="manual",
    )


@pytest.fixture
def execution(db, workflow, project, user):
    """创建测试执行实例。"""
    return WorkflowExecution.objects.create(
        workflow=workflow,
        space=project,
        trigger_type="manual",
        triggered_by=user,
    )


class TestWorkflowExecutionTenantMigration:
    """WorkflowExecution 租户迁移正确性测试。"""

    @pytest.mark.django_db
    def test_execution_has_project_field(self, execution):
        """WorkflowExecution 实例必须有 project 字段。"""
        assert hasattr(execution, "space")
        assert execution.space is not None

    @pytest.mark.django_db
    def test_execution_project_not_null(self, workflow, user):
        """创建 WorkflowExecution 时 project 为必填。"""
        # project 为非空 FK，直接创建应该需要提供 project
        exec_instance = WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="manual",
            triggered_by=user,
        )
        exec_instance.refresh_from_db()
        assert exec_instance.space_id is not None

    @pytest.mark.django_db
    def test_backfill_correctness(self, workflow, user):
        """验证 execution.space == execution.workflow.space。"""
        exec_instance = WorkflowExecution.objects.create(
            workflow=workflow,
            space=workflow.space,
            trigger_type="manual",
            triggered_by=user,
        )
        exec_instance.refresh_from_db()
        assert exec_instance.space_id == exec_instance.workflow.space_id

    @pytest.mark.django_db
    def test_execution_project_index_exists(self):
        """project + status 索引存在。"""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='workflow_executions' "
                "AND name LIKE '%space%'"
            )
            indexes = [row[0] for row in cursor.fetchall()]
        assert len(indexes) >= 1, f"Expected at least 1 project index, found: {indexes}"

    @pytest.mark.django_db
    def test_execution_cascade_delete(self, workflow, project, user):
        """删除 Space 后关联的 WorkflowExecution 也被删除。"""
        exec_instance = WorkflowExecution.objects.create(
            workflow=workflow,
            space=project,
            trigger_type="manual",
            triggered_by=user,
        )
        exec_id = exec_instance.id
        project.delete()
        assert not WorkflowExecution.objects.filter(id=exec_id).exists()
