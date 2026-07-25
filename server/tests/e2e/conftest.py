"""E2E test configuration and fixtures.

This module provides comprehensive fixtures for end-to-end workflow testing,
including project/repository setup, complete workflow fixtures, and helper
functions for webhook simulation and execution status polling.
"""

import json
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.test import Client
from rest_framework.test import APIClient

from common.encryption import encrypt_value
from projects.models import Space
from repositories.models import AuthType, GitCredential, Repository
from workflows.models import (
    ExecutionStatus,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
    WorkflowTrigger,
)

# Mock fixtures are auto-discovered via tests/e2e/fixtures/mock_services.py
# (fixtures registered as pytest fixtures are available to all tests in this directory)


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
def e2e_repository(db) -> Repository:
    """Create a test repository for E2E tests.

    Returns:
        Repository with git credentials configured
    """
    repo = Repository.objects.create(
        name="e2e-test-repo",
        git_url="https://gitlab.example.com/test/e2e-repo.git",
        git_platform="gitlab",
        default_branch="main",
    )

    # Add git credential
    GitCredential.objects.create(
        repository=repo,
        auth_type=AuthType.ACCESS_TOKEN,
        encrypted_token=encrypt_value("glpat-test-contract"),
    )

    return repo


@pytest.fixture
def e2e_project(db, e2e_repository: Repository) -> Space:
    """Create a test project for E2E tests.

    Returns:
        Space with Feishu integration configured and repository linked
    """
    project = Space.objects.create(
        name="E2E Test Space",
        description="Space for E2E workflow testing",
        feishu_project_key="e2e-test-project",
        feishu_webhook_token="e2e-webhook-contract",
    )
    project.repositories.add(e2e_repository)
    return project


@pytest.fixture
def e2e_workflow(
    db,
    e2e_project: Space,
    e2e_repository: Repository,
) -> Workflow:
    """Create a complete E2E workflow with all node types.

    The workflow chain:
    1. feishu_event_trigger - Triggers on Feishu work item creation
    2. ai_plan_research - Generates technical plan from requirements
    3. wait_feishu_field - Waits for approval status
    4. ai_coding_dispatcher - Dispatches coding tasks

    Returns:
        Workflow with nodes and edges configured
    """
    workflow = Workflow.objects.create(
        name="E2E Test Workflow",
        space=e2e_project,
        trigger_type="feishu_event",
        description="Complete E2E workflow for testing",
        is_active=True,
    )

    # Node 1: Feishu Event Trigger
    trigger_node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="feishu_event_trigger",
        name="Feishu Trigger",
        position_x=0,
        position_y=100,
        config={
            "event_types": ["WorkitemCreateEvent"],
            "work_item_types": ["story"],
        },
    )

    # Node 2: AI 方案编排调研（Chassis v2 起取代已删除的 ai_plan_generation；
    # config 形态对齐 AIPlanResearchNode.config_schema，与迁移 0034 的产物一致）
    plan_node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="ai_plan_research",
        name="AI Plan Research",
        position_x=250,
        position_y=100,
        config={
            "requirement_text": "",
            "include_repos": [],
            "work_item_id": "",
            "chat_id": "",
            "use_custom_api": False,
            "api_base_url": "",
            "api_key": "",
            "model": "claude-3-5-sonnet-20241022",
        },
    )

    # Node 3: Wait for Feishu Field (approval)
    wait_node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="wait_feishu_field",
        name="Wait for Approval",
        position_x=500,
        position_y=100,
        config={
            "work_item_id": "{{trigger.work_item_id}}",
            "work_item_type": "story",
            "project_key": "{{trigger.project_key}}",
            "condition": {
                "field": "status",
                "operator": "equals",
                "value": "approved",
            },
            "timeout_seconds": 86400,  # 24 hours
            "timeout_action": "fail",
        },
    )

    # Node 4: AI Coding Dispatcher
    dispatcher_node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="ai_coding_dispatcher",
        name="Dispatch Coding Tasks",
        position_x=750,
        position_y=100,
        config={
            "merge_same_branch": True,
        },
    )

    # Create edges connecting the nodes
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=trigger_node,
        target_node=plan_node,
        source_handle="default",
        target_handle="default",
    )

    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=plan_node,
        target_node=wait_node,
        source_handle="default",
        target_handle="default",
    )

    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=wait_node,
        target_node=dispatcher_node,
        source_handle="matched",
        target_handle="plan",
    )

    # Create WorkflowTrigger to enable Feishu event triggering
    # The FeishuEventHandler uses WorkflowTrigger to match events to workflows
    # Empty filter_config means it matches all WorkitemCreateEvent events for this project
    WorkflowTrigger.objects.create(
        workflow=workflow,
        event_type="WorkitemCreateEvent",
        name="E2E Test Trigger",
        description="Trigger for E2E testing",
        is_active=True,
        filter_config={},  # Match all events of this type
    )

    return workflow


@pytest.fixture
def e2e_simple_workflow(db, e2e_project: Space) -> Workflow:
    """Create a simple two-node workflow for basic E2E tests.

    Returns:
        Workflow with trigger and condition nodes only
    """
    workflow = Workflow.objects.create(
        name="Simple E2E Workflow",
        space=e2e_project,
        trigger_type="manual",
        is_active=True,
    )

    trigger_node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="manual_trigger",
        name="Manual Start",
        position_x=0,
        position_y=0,
    )

    condition_node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="condition",
        name="Check Condition",
        position_x=200,
        position_y=0,
        config={"expression": "true", "cases": []},
    )

    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=trigger_node,
        target_node=condition_node,
        source_handle="default",
        target_handle="default",
    )

    return workflow


# ============================================================================
# API Client Fixtures
# ============================================================================


@pytest.fixture
def e2e_api_client() -> APIClient:
    """Create an API client for E2E tests."""
    return APIClient()


# ============================================================================
# Helper Functions
# ============================================================================


def simulate_feishu_webhook(
    api_client: APIClient | Client,
    project: Space,
    event_type: str,
    payload: dict[str, Any],
) -> Any:
    """Simulate a Feishu webhook call to the API.

    Args:
        api_client: Django test client or DRF APIClient
        project: Space with Feishu configuration
        event_type: Feishu event type (WorkitemCreateEvent, etc.)
        payload: Complete webhook payload dict

    Returns:
        Response from the webhook endpoint
    """
    # Ensure header has correct event type
    if "header" in payload:
        payload["header"]["event_type"] = event_type
        payload["header"]["token"] = project.feishu_webhook_token or ""

    response = api_client.post(
        "/api/feishu/webhook",
        data=json.dumps(payload),
        content_type="application/json",
    )

    return response


async def wait_for_execution_status(
    execution: WorkflowExecution,
    target_statuses: list[ExecutionStatus] | list[str],
    timeout: float = 10.0,
    poll_interval: float = 0.2,
) -> str:
    """Wait for execution to reach one of the target statuses.

    Args:
        execution: WorkflowExecution instance to poll
        target_statuses: List of statuses to wait for
        timeout: Maximum time to wait in seconds
        poll_interval: Time between polls in seconds

    Returns:
        Final execution status as string

    Raises:
        TimeoutError: If timeout is reached before target status
    """
    import asyncio

    # Convert string statuses to ExecutionStatus if needed
    targets = []
    for status in target_statuses:
        if isinstance(status, str):
            targets.append(ExecutionStatus(status))
        else:
            targets.append(status)

    elapsed = 0.0

    while elapsed < timeout:
        await execution.arefresh_from_db()

        if execution.status in targets:
            return execution.status

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    raise TimeoutError(
        f"Execution {execution.id} did not reach {targets} within {timeout}s. "
        f"Current status: {execution.status}"
    )


async def wait_for_node_execution_status(
    execution: WorkflowExecution,
    node_type: str,
    target_status: str,
    timeout: float = 10.0,
    poll_interval: float = 0.2,
) -> Any:
    """Wait for a specific node execution to reach target status.

    Args:
        execution: WorkflowExecution instance
        node_type: Type of node to wait for
        target_status: Status to wait for
        timeout: Maximum time to wait in seconds
        poll_interval: Time between polls in seconds

    Returns:
        NodeExecution instance when status is reached

    Raises:
        TimeoutError: If timeout is reached
    """
    import asyncio

    elapsed = 0.0

    while elapsed < timeout:
        node_exec = await sync_to_async(
            lambda: execution.node_executions.filter(
                node__node_type=node_type,
                status=target_status,
            ).first()
        )()

        if node_exec:
            return node_exec

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    raise TimeoutError(
        f"Node {node_type} did not reach status {target_status} within {timeout}s"
    )


def get_execution_node_outputs(execution: WorkflowExecution) -> dict[str, Any]:
    """Get all node outputs from an execution.

    Args:
        execution: WorkflowExecution instance

    Returns:
        Dict mapping node names to their outputs
    """
    outputs = {}

    for node_exec in execution.node_executions.select_related("node").all():
        node_name = node_exec.node.name
        outputs[node_name] = node_exec.output_data

    return outputs


async def trigger_workflow_sync(
    workflow: Workflow,
    input_data: dict[str, Any],
    trigger_type: str = "feishu",
    trigger_data: dict[str, Any] | None = None,
) -> WorkflowExecution:
    """Trigger workflow execution synchronously for testing.

    Unlike webhook-triggered execution which runs in a background thread,
    this runs the workflow in the current async context, ensuring:
    1. Database transaction is shared with test
    2. Mocks patched in test context are visible
    3. No race conditions with test assertions

    Args:
        workflow: Workflow to execute
        input_data: Input data for the workflow
        trigger_type: Trigger type (default: "feishu")
        trigger_data: Optional trigger metadata

    Returns:
        WorkflowExecution after completion/suspension
    """
    from workflows.engine.scheduler import WorkflowEngine

    engine = WorkflowEngine()
    execution = await engine.start_execution(
        workflow=workflow,
        input_data=input_data,
        trigger_type=trigger_type,
        trigger_data=trigger_data or {},
        run_sync=True,  # Run in same context as test
    )
    return execution
