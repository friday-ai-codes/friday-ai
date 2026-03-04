"""Resume behavior tests for paused workflow executions."""
from __future__ import annotations
import pytest
from rest_framework import status
from projects.models import Project
from workflows.engine.scheduler import ResumeExecutionNotSupportedError, WorkflowEngine
from workflows.models import ExecutionStatus, Workflow, WorkflowExecution
@pytest.fixture
def paused_execution(db, user):
 project = Project.objects.create(name="Resume API Project")
 workflow = Workflow.objects.create(
 name="Resume API Workflow",
 project=project,
 trigger_type="manual",
 created_by=user,
 )
 return WorkflowExecution.objects.create(
 workflow=workflow,
 trigger_type="manual",
 triggered_by=user,
 status=ExecutionStatus.PAUSED,
 )
@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_engine_resume_returns_not_supported(paused_execution):
 engine = WorkflowEngine
 with pytest.raises(ResumeExecutionNotSupportedError):
 await engine.resume_execution(paused_execution)
 await paused_execution.arefresh_from_db
 assert paused_execution.status == ExecutionStatus.PAUSED
@pytest.mark.django_db
def test_resume_api_returns_501_for_paused_execution(authenticated_client, paused_execution):
 response = authenticated_client.post(
 f"/api/workflow-executions/{paused_execution.id}/resume/",
 {},
 format="json",
 )
 paused_execution.refresh_from_db
 assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED
 assert paused_execution.status == ExecutionStatus.PAUSED
