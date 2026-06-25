"""调试基础设施测试 — NodeExecution 日志、错误码、序列化器、引擎映射。

覆盖 work item / work item 需求：
- WorkflowErrorCode 枚举完整性
- NodeExecution._append_log / aappend_log 行为
- 日志上限 100 条截断
- mark_failed / amark_failed error_code 参数
- WorkflowEngine._map_error_code 异常映射
- NodeExecutionSerializer 暴露 logs / error_code
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from projects.models import Space
    from workflows.models.node import WorkflowNode
    from workflows.models.workflow import Workflow

from workflows.engine.scheduler import WorkflowEngine
from workflows.models.execution import NodeExecution, WorkflowErrorCode, WorkflowExecution


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def workflow(db: None, project: "Space") -> "Workflow":
    """创建测试工作流。"""
    from workflows.models.workflow import Workflow

    return Workflow.objects.create(name="Test Workflow", space=project)


@pytest.fixture
def workflow_node(db: None, workflow: "Workflow") -> "WorkflowNode":
    """创建测试工作流节点。"""
    from workflows.models.node import WorkflowNode

    return WorkflowNode.objects.create(
        workflow=workflow,
        node_type="ai_plan_generation",
        name="Test AI Node",
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


# ============================================================================
# WorkflowErrorCode
# ============================================================================


@pytest.mark.django_db
class TestWorkflowErrorCode:
    def test_enum_values(self) -> None:
        assert WorkflowErrorCode.TIMEOUT == "timeout"
        assert WorkflowErrorCode.PERMISSION == "permission"
        assert WorkflowErrorCode.RESOURCE == "resource"
        assert WorkflowErrorCode.API == "api"
        assert WorkflowErrorCode.RUNTIME == "runtime"
        assert WorkflowErrorCode.UNKNOWN == "unknown"

    def test_choices_length(self) -> None:
        assert len(WorkflowErrorCode.choices) == 6


# ============================================================================
# NodeExecution Logs
# ============================================================================


@pytest.mark.django_db
class TestNodeExecutionLogs:
    def test_append_log_sync(self, workflow_execution: WorkflowExecution, workflow_node: "WorkflowNode") -> None:
        ne = NodeExecution.objects.create(
            workflow_execution=workflow_execution,
            node=workflow_node,
        )
        ne._append_log("INFO", "test message", {"key": "value"})
        ne.refresh_from_db()
        assert len(ne.logs) == 1
        assert ne.logs[0]["level"] == "INFO"
        assert ne.logs[0]["message"] == "test message"
        assert ne.logs[0]["context"] == {"key": "value"}
        assert "timestamp" in ne.logs[0]

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_aappend_log_async(self, workflow_execution: WorkflowExecution, workflow_node: "WorkflowNode") -> None:
        ne = await NodeExecution.objects.acreate(
            workflow_execution=workflow_execution,
            node=workflow_node,
        )
        await ne.aappend_log("ERROR", "async test")
        await ne.arefresh_from_db()
        assert len(ne.logs) == 1
        assert ne.logs[0]["level"] == "ERROR"

    def test_log_max_100_entries(self, workflow_execution: WorkflowExecution, workflow_node: "WorkflowNode") -> None:
        ne = NodeExecution.objects.create(
            workflow_execution=workflow_execution,
            node=workflow_node,
        )
        for i in range(105):
            ne._append_log("INFO", f"log {i}")
        ne.refresh_from_db()
        assert len(ne.logs) == 100
        assert ne.logs[-1]["message"] == "log 104"

    def test_mark_failed_with_error_code(self, workflow_execution: WorkflowExecution, workflow_node: "WorkflowNode") -> None:
        ne = NodeExecution.objects.create(
            workflow_execution=workflow_execution,
            node=workflow_node,
        )
        ne.mark_failed("something broke", error_code="runtime")
        ne.refresh_from_db()
        assert ne.error_code == "runtime"
        assert ne.status == "failed"


# ============================================================================
# Error Code Mapping
# ============================================================================


@pytest.mark.django_db
class TestErrorCodeMapping:
    def test_timeout_error_maps_to_timeout(self) -> None:
        exc = asyncio.TimeoutError()
        assert WorkflowEngine._map_error_code(exc) == "timeout"

    def test_generic_exception_maps_to_runtime(self) -> None:
        exc = ValueError("test")
        assert WorkflowEngine._map_error_code(exc) == "runtime"

    def test_os_error_maps_to_resource(self) -> None:
        exc = OSError("no space")
        assert WorkflowEngine._map_error_code(exc) == "resource"

    def test_permission_denied_maps_to_permission(self) -> None:
        from rest_framework.exceptions import PermissionDenied

        exc = PermissionDenied("denied")
        assert WorkflowEngine._map_error_code(exc) == "permission"

    @pytest.mark.skip("httpx may not be installed in test env")
    def test_httpx_error_maps_to_api(self) -> None:
        import httpx

        exc = httpx.ConnectError("connection failed")
        assert WorkflowEngine._map_error_code(exc) == "api"


# ============================================================================
# NodeExecutionSerializer
# ============================================================================


@pytest.mark.django_db
class TestNodeExecutionSerializer:
    def test_logs_field_present(self, workflow_execution: WorkflowExecution, workflow_node: "WorkflowNode") -> None:
        from workflows.api.serializers import NodeExecutionSerializer

        ne = NodeExecution.objects.create(
            workflow_execution=workflow_execution,
            node=workflow_node,
        )
        serializer = NodeExecutionSerializer(ne)
        assert "logs" in serializer.data
        assert "error_code" in serializer.data
