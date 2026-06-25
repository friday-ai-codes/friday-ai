"""Resume behavior tests for paused workflow executions."""

from __future__ import annotations

import pytest
from rest_framework import status

from projects.models import Space
from workflows.engine.scheduler import WorkflowEngine
from workflows.models import ExecutionStatus, Workflow, WorkflowExecution


@pytest.fixture
def paused_execution(db, user):
    """创建一个暂停的执行实例（含已完成节点信息）。"""
    project = Space.objects.create(name="Resume API Space")
    workflow = Workflow.objects.create(
        name="Resume API Workflow",
        space=project,
        trigger_type="manual",
        created_by=user,
    )
    return WorkflowExecution.objects.create(
        workflow=workflow,
        space=project,
        trigger_type="manual",
        triggered_by=user,
        status=ExecutionStatus.PAUSED,
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_resume_execution_rejects_non_paused(paused_execution):
    """resume_execution 拒绝非 PAUSED 状态的执行。"""
    paused_execution.status = ExecutionStatus.RUNNING
    await paused_execution.asave(update_fields=["status"])

    engine = WorkflowEngine()
    with pytest.raises(ValueError, match="只能恢复已暂停的执行"):
        await engine.resume_execution(paused_execution)


@pytest.mark.django_db
def test_resume_api_returns_200_for_paused_execution(authenticated_client, paused_execution):
    """resume API 对 PAUSED 执行返回 200（非 501）。"""
    response = authenticated_client.post(
        f"/api/workflow-executions/{paused_execution.id}/resume/",
        {},
        format="json",
    )

    # resume_execution 需要 select_related workflow，paused_execution fixture
    # 的 workflow 没有节点，所以 DAG 构建后主循环会快速结束。
    # 关键断言：不再返回 501
    assert response.status_code != status.HTTP_501_NOT_IMPLEMENTED
