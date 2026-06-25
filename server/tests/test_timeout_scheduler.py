"""超时调度器 check_timeouts management command 测试。

覆盖 work item 需求：
- 无超时订阅时命令正常执行
- timeout_action=fail → NodeExecution.status=timeout, WorkflowExecution.status=timeout
- timeout_action=skip → NodeExecution.status=skipped
- 处理后 is_active=False
- 已 inactive 的订阅不被处理
- timeout_at 未到达的订阅不被处理
- timeout_at 为 null 的订阅不被处理
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from django.core.management import call_command
from django.utils import timezone

if TYPE_CHECKING:
    from projects.models import Space
    from workflows.models.node import WorkflowNode
    from workflows.models.workflow import Workflow

from workflows.models.execution import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
    WorkflowEventSubscription,
    WorkflowExecution,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def workflow(db: None, project: "Space") -> "Workflow":
    """创建测试工作流。"""
    from workflows.models.workflow import Workflow

    return Workflow.objects.create(name="Timeout Workflow", space=project)


@pytest.fixture
def workflow_node(db: None, workflow: "Workflow") -> "WorkflowNode":
    """创建测试工作流节点。"""
    from workflows.models.node import WorkflowNode

    return WorkflowNode.objects.create(
        workflow=workflow,
        node_type="ai_plan_generation",
        name="Test Node",
        config={},
    )


@pytest.fixture
def workflow_execution(db: None, workflow: "Workflow") -> WorkflowExecution:
    """创建测试工作流执行实例。"""
    return WorkflowExecution.objects.create(
        workflow=workflow,
        space=workflow.space,
        status="running",
    )


@pytest.fixture
def node_execution(
    db: None,
    workflow_execution: WorkflowExecution,
    workflow_node: "WorkflowNode",
) -> NodeExecution:
    """创建测试节点执行记录。"""
    return NodeExecution.objects.create(
        workflow_execution=workflow_execution,
        node=workflow_node,
        status="waiting_event",
    )


def _create_subscription(
    wf_exec: WorkflowExecution,
    node_exec: NodeExecution,
    timeout_at: object = None,
    action: str = "fail",
    is_active: bool = True,
) -> WorkflowEventSubscription:
    """创建测试订阅。"""
    return WorkflowEventSubscription.objects.create(
        workflow_execution=wf_exec,
        node_execution=node_exec,
        event_type="TestEvent",
        project_key="TEST",
        timeout_at=timeout_at,
        timeout_action=action,
        is_active=is_active,
    )


# ============================================================================
# Tests
# ============================================================================


@pytest.mark.django_db
class TestCheckTimeouts:
    def test_no_expired_subscriptions(self) -> None:
        """无超时订阅时命令正常执行输出 0。"""
        out = StringIO()
        call_command("check_timeouts", stdout=out)
        assert "处理了 0 个超时订阅" in out.getvalue()

    def test_fail_action(
        self,
        workflow_execution: WorkflowExecution,
        node_execution: NodeExecution,
    ) -> None:
        """timeout_action=fail → NodeExecution.status=timeout, WorkflowExecution.status=timeout。"""
        sub = _create_subscription(
            workflow_execution,
            node_execution,
            timeout_at=timezone.now() - timedelta(minutes=5),
            action="fail",
        )

        out = StringIO()
        call_command("check_timeouts", stdout=out)
        assert "处理了 1 个超时订阅" in out.getvalue()

        node_execution.refresh_from_db()
        assert node_execution.status == NodeExecutionStatus.TIMEOUT

        workflow_execution.refresh_from_db()
        assert workflow_execution.status == ExecutionStatus.TIMEOUT
        assert workflow_execution.completed_at is not None
        assert "超时" in workflow_execution.error_message

        sub.refresh_from_db()
        assert sub.is_active is False

    def test_skip_action(
        self,
        workflow_execution: WorkflowExecution,
        node_execution: NodeExecution,
    ) -> None:
        """timeout_action=skip → NodeExecution.status=skipped。"""
        sub = _create_subscription(
            workflow_execution,
            node_execution,
            timeout_at=timezone.now() - timedelta(minutes=5),
            action="skip",
        )

        out = StringIO()
        call_command("check_timeouts", stdout=out)
        assert "处理了 1 个超时订阅" in out.getvalue()

        node_execution.refresh_from_db()
        assert node_execution.status == NodeExecutionStatus.SKIPPED

        sub.refresh_from_db()
        assert sub.is_active is False

    def test_inactive_not_processed(
        self,
        workflow_execution: WorkflowExecution,
        node_execution: NodeExecution,
    ) -> None:
        """已 inactive 的订阅不被处理。"""
        _create_subscription(
            workflow_execution,
            node_execution,
            timeout_at=timezone.now() - timedelta(minutes=5),
            action="fail",
            is_active=False,
        )

        out = StringIO()
        call_command("check_timeouts", stdout=out)
        assert "处理了 0 个超时订阅" in out.getvalue()

        # NodeExecution 状态不变
        node_execution.refresh_from_db()
        assert node_execution.status == NodeExecutionStatus.WAITING_EVENT

    def test_future_timeout_not_processed(
        self,
        workflow_execution: WorkflowExecution,
        node_execution: NodeExecution,
    ) -> None:
        """timeout_at 在未来的订阅不被处理。"""
        _create_subscription(
            workflow_execution,
            node_execution,
            timeout_at=timezone.now() + timedelta(hours=1),
            action="fail",
        )

        out = StringIO()
        call_command("check_timeouts", stdout=out)
        assert "处理了 0 个超时订阅" in out.getvalue()

        node_execution.refresh_from_db()
        assert node_execution.status == NodeExecutionStatus.WAITING_EVENT

    def test_null_timeout_not_processed(
        self,
        workflow_execution: WorkflowExecution,
        node_execution: NodeExecution,
    ) -> None:
        """timeout_at 为 null 的订阅不被处理。"""
        _create_subscription(
            workflow_execution,
            node_execution,
            timeout_at=None,
            action="fail",
        )

        out = StringIO()
        call_command("check_timeouts", stdout=out)
        assert "处理了 0 个超时订阅" in out.getvalue()

        node_execution.refresh_from_db()
        assert node_execution.status == NodeExecutionStatus.WAITING_EVENT

    def test_subscription_marked_inactive_after_processing(
        self,
        workflow_execution: WorkflowExecution,
        node_execution: NodeExecution,
    ) -> None:
        """处理后订阅标记为 is_active=False。"""
        sub = _create_subscription(
            workflow_execution,
            node_execution,
            timeout_at=timezone.now() - timedelta(minutes=1),
            action="skip",
        )

        call_command("check_timeouts")

        sub.refresh_from_db()
        assert sub.is_active is False
