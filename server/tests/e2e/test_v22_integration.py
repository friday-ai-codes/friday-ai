"""v22.0 跨 Phase 端到端集成测试。

覆盖三个跨 phase 联动场景：
- 场景 1 — Smoke 链路（work item / work item / work item）
- 场景 2 — 新节点链路（work item / work item）
- 场景 3 — 回放数据契约（work item）
"""

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from django.utils import timezone
from rest_framework import status

from projects.models import Space
from workflows.api.serializers import WorkflowExecutionSerializer
from workflows.engine.scheduler import WorkflowEngine
from workflows.hooks.builtin import AlertRuleHook
from workflows.models import (
    AlertRule,
    AlertRuleExecution,
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
)
from workflows.models.execution import WorkflowErrorCode
from workflows.nodes.base import BaseNode, ExecutionContext, NodeCategory, NodeResult
from workflows.nodes.registry import NodeRegistry


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _TestPassThroughNode(BaseNode):
    """透传节点：将 input 原样输出，用于构造简洁 DAG。"""

    node_type = "test_pass_through"
    display_name = "Pass Through"
    description = "Returns input as output"
    category = NodeCategory.ACTION
    execution_mode = "server_local"

    async def execute(self, context: ExecutionContext) -> NodeResult:
        return NodeResult(status="completed", output=context.input_data)


class _TestFailOnceNode(BaseNode):
    """只失败一次的节点，用于测试 on_error=ignore 容错。"""

    node_type = "test_fail_once"
    display_name = "Fail Once"
    description = "Fails on first call then succeeds"
    category = NodeCategory.ACTION
    execution_mode = "server_local"
    supports_retry = True

    _call_count = 0

    async def execute(self, context: ExecutionContext) -> NodeResult:
        _TestFailOnceNode._call_count += 1
        if _TestFailOnceNode._call_count == 1:
            raise RuntimeError("Intentional first failure")
        return NodeResult(status="completed", output={"recovered": True})


def _register_test_nodes():
    """注册测试专用节点类型到 NodeRegistry。"""
    registry = NodeRegistry()
    if registry.get("test_pass_through") is None:
        registry.register(_TestPassThroughNode)
    if registry.get("test_fail_once") is None:
        registry.register(_TestFailOnceNode)


# ---------------------------------------------------------------------------
# Scenario 1 — Smoke 链路（work item / work item / work item）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestSmokeChain:
    """场景 1：模板创建 → 执行 → 结构化日志 / 错误码 → AlertRule 触发 → 告警历史。"""

    def test_create_workflow_from_template_api(self, authenticated_admin_client, project):
        """从模板创建工作流：POST /api/workflows/from-template/ 返回 201。"""
        url = "/api/workflows/from-template/"
        data = {
            "template_id": "daily_summary",
            "space_id": str(project.id),
        }
        response = authenticated_admin_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["metadata"]["template_id"] == "daily_summary"
        assert "id" in response.data

    @pytest.mark.asyncio
    async def test_execution_generates_logs_and_error_code(self, db, user):
        """手动触发执行后，NodeExecution 包含结构化日志和合法 error_code。"""
        _register_test_nodes()

        project = await Space.objects.acreate(name="Smoke Test Space")
        workflow = await Workflow.objects.acreate(
            name="Smoke Workflow",
            space=project,
            trigger_type="manual",
        )
        trigger = await WorkflowNode.objects.acreate(
            workflow=workflow,
            node_type="manual_trigger",
            name="Start",
            position_x=0,
            position_y=0,
        )
        action = await WorkflowNode.objects.acreate(
            workflow=workflow,
            node_type="test_pass_through",
            name="Action",
            position_x=200,
            position_y=0,
        )
        await WorkflowEdge.objects.acreate(
            workflow=workflow,
            source_node=trigger,
            target_node=action,
            source_handle="default",
            target_handle="default",
        )

        engine = WorkflowEngine()
        execution = await engine.start_execution(
            workflow=workflow,
            input_data={"test": "smoke"},
            trigger_type="manual",
            run_sync=True,
        )

        assert execution.status == ExecutionStatus.COMPLETED

        # 验证 NodeExecution 记录存在且包含结构化日志字段
        node_exec = await NodeExecution.objects.filter(
            workflow_execution=execution,
        ).afirst()
        assert node_exec is not None
        assert isinstance(node_exec.logs, list)
        # error_code 为 null 或合法枚举值
        assert node_exec.error_code is None or node_exec.error_code in dict(
            WorkflowErrorCode.choices
        )

    @pytest.mark.asyncio
    async def test_alert_rule_triggers_and_records_execution(self, db, user):
        """AlertRuleHook 条件评估通过并生成 AlertRuleExecution 记录。"""
        project = await Space.objects.acreate(name="Alert Test Space")
        workflow = await Workflow.objects.acreate(
            name="Alert Workflow",
            space=project,
            trigger_type="manual",
        )
        now = timezone.now()
        failed_execution = await WorkflowExecution.objects.acreate(
            workflow=workflow,
            space=project,
            trigger_type="manual",
            triggered_by=user,
            status="failed",
            started_at=now - timedelta(seconds=60),
            completed_at=now,
        )

        rule = await AlertRule.objects.acreate(
            workflow=workflow,
            space=project,
            name="E2E Failed Alert",
            condition_type="execution_failed",
            action_type="webhook",
            action_config={"url": "https://example.com/hook"},
        )

        hook = AlertRuleHook()
        with patch.object(hook, "_send_webhook", new_callable=AsyncMock) as mock_send:
            await hook._execute_action(rule, failed_execution, "execution_failed")
            mock_send.assert_awaited_once()

        # 验证 AlertRuleExecution 记录已生成
        record = await AlertRuleExecution.objects.filter(
            alert_rule=rule,
            workflow_execution=failed_execution,
        ).afirst()
        assert record is not None
        assert record.status in ("triggered", "delivered", "failed")


# ---------------------------------------------------------------------------
# Scenario 2 — 新节点链路（work item / work item）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestNewNodeChain:
    """场景 2：ForEach + Code + Aggregate + on_error=ignore 端到端链路。"""

    @pytest.mark.asyncio
    async def test_foreach_node_execution(self, db):
        """ForEach 节点在引擎上下文中串行/并发模式正常迭代。"""
        from workflows.nodes.control.loop import ForEachNode

        node = ForEachNode()
        context = ExecutionContext(
            execution_id="exec-001",
            node_id="node-001",
            node_config={
                "list_source": "{{input.items}}",
                "execution_mode": "sequential",
                "max_concurrency": 5,
                "on_iteration_error": "abort",
            },
            input_data={"items": [10, 20, 30]},
            workflow_context={},
            previous_outputs={},
        )

        result = await node.execute(context)
        assert result.status == "completed"
        assert result.output["success_count"] == 3
        assert result.output["results"] == [10, 20, 30]

    @pytest.mark.asyncio
    async def test_code_node_sandbox_execution(self, db):
        """Code 节点沙箱执行通过 AST 校验并返回正确结果。"""
        from workflows.nodes.actions.code import CodeNode

        node = CodeNode()
        context = ExecutionContext(
            execution_id="exec-002",
            node_id="node-002",
            node_config={"code": "context['output'] = {'sum': 1 + 2 + 3}"},
            input_data={},
            workflow_context={},
            previous_outputs={},
        )

        result = await node.execute(context)
        assert result.status == "completed"
        assert result.output == {"sum": 6}

    @pytest.mark.asyncio
    async def test_aggregate_node_data_restructuring(self, db):
        """变量聚合节点对上游输出进行 shallow merge。"""
        from workflows.nodes.data.aggregate import VariableAggregateNode

        node = VariableAggregateNode()
        context = ExecutionContext(
            execution_id="exec-003",
            node_id="node-003",
            node_config={
                "mappings": [
                    {"source_node": "node_a", "output_field": "", "target_key": "a"},
                    {"source_node": "node_b", "output_field": "data", "target_key": "b"},
                ],
            },
            input_data={},
            workflow_context={},
            previous_outputs={
                "node_a": {"value": 1},
                "node_b": {"data": {"nested": True}},
            },
        )

        result = await node.execute(context)
        assert result.status == "completed"
        assert result.output["a"] == {"value": 1}
        assert result.output["b"] == {"nested": True}

    @pytest.mark.asyncio
    async def test_on_error_ignore_with_fallback_in_engine(self, db, user):
        """on_error=ignore + fallback_values 在引擎中使下游继续执行。"""
        _register_test_nodes()
        _TestFailOnceNode._call_count = 0

        project = await Space.objects.acreate(name="Ignore Test Space")
        workflow = await Workflow.objects.acreate(
            name="Ignore Workflow",
            space=project,
            trigger_type="manual",
        )
        trigger = await WorkflowNode.objects.acreate(
            workflow=workflow,
            node_type="manual_trigger",
            name="Start",
            position_x=0,
            position_y=0,
        )
        fail_node = await WorkflowNode.objects.acreate(
            workflow=workflow,
            node_type="test_fail_once",
            name="Fail Once",
            position_x=200,
            position_y=0,
            on_error="ignore",
            fallback_values={"recovered": False},
        )
        downstream = await WorkflowNode.objects.acreate(
            workflow=workflow,
            node_type="test_pass_through",
            name="Downstream",
            position_x=400,
            position_y=0,
        )
        await WorkflowEdge.objects.acreate(
            workflow=workflow, source_node=trigger, target_node=fail_node,
        )
        await WorkflowEdge.objects.acreate(
            workflow=workflow, source_node=fail_node, target_node=downstream,
        )

        engine = WorkflowEngine()
        execution = await engine.start_execution(workflow, run_sync=True)

        assert execution.status == ExecutionStatus.COMPLETED

        # 失败节点在 DB 中状态仍为 FAILED
        fail_ne = await NodeExecution.objects.filter(
            workflow_execution=execution,
            node__node_type="test_fail_once",
        ).afirst()
        assert fail_ne is not None
        assert fail_ne.status == NodeExecutionStatus.FAILED


# ---------------------------------------------------------------------------
# Scenario 3 — 回放数据契约（work item）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestReplayContract:
    """场景 3：执行历史序列化包含回放所需的完整字段。"""

    def test_execution_serializer_contains_all_fields(self, db, user):
        """WorkflowExecutionSerializer 包含 node_executions、logs、error_code 等字段。"""
        project = Space.objects.create(name="Replay Test Space")
        workflow = Workflow.objects.create(
            name="Replay Workflow",
            space=project,
            trigger_type="manual",
        )
        node = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="manual_trigger",
            name="Start",
            position_x=0,
            position_y=0,
        )
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=project,
            trigger_type="manual",
            triggered_by=user,
            status="completed",
            workflow_definition={"nodes": [{"id": str(node.id), "type": "manual_trigger"}]},
        )
        node_exec = NodeExecution.objects.create(
            workflow_execution=execution,
            node=node,
            status="completed",
            input_data={"key": "value"},
            output_data={"result": "ok"},
            logs=[
                {"timestamp": "2026-05-01T12:00:00Z", "level": "INFO", "message": "Started"},
                {"timestamp": "2026-05-01T12:00:01Z", "level": "INFO", "message": "Done"},
            ],
            error_code=None,
        )

        serializer = WorkflowExecutionSerializer(execution)
        data = serializer.data

        # 顶层字段
        assert "id" in data
        assert "workflow_name" in data
        assert "status" in data
        assert "workflow_definition" in data

        # node_executions 包含完整回放字段
        assert "node_executions" in data
        assert len(data["node_executions"]) == 1
        ne_data = data["node_executions"][0]
        assert "input_data" in ne_data
        assert "output_data" in ne_data
        assert "logs" in ne_data
        assert "error_code" in ne_data
        assert ne_data["input_data"] == {"key": "value"}
        assert ne_data["output_data"] == {"result": "ok"}
        assert len(ne_data["logs"]) == 2
        assert ne_data["error_code"] is None

    def test_node_snapshots_is_json_serializable(self, db, user):
        """node_snapshots 可序列化，json.dumps() 不抛异常。"""
        project = Space.objects.create(name="Snapshot Test Space")
        workflow = Workflow.objects.create(
            name="Snapshot Workflow",
            space=project,
            trigger_type="manual",
        )
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=project,
            trigger_type="manual",
            triggered_by=user,
            status="completed",
            context={
                "node_snapshots": {
                    "n_abc123": {
                        "model": "claude-3-5-sonnet-20241022",
                        "provider": "anthropic",
                    },
                    "n_def456": {
                        "model": "gpt-4o",
                        "provider": "openai",
                    },
                }
            },
        )

        serializer = WorkflowExecutionSerializer(execution)
        data = serializer.data

        # 完整序列化不抛异常
        serialized = json.dumps(data, default=str)
        assert isinstance(serialized, str)
        assert "node_snapshots" in serialized

    def test_replay_mode_data_contract(self, db, user):
        """replayMode 数据契约：logs / error_code / input_data / output_data 完整。"""
        project = Space.objects.create(name="Contract Test Space")
        workflow = Workflow.objects.create(
            name="Contract Workflow",
            space=project,
            trigger_type="manual",
        )
        node_ok = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="manual_trigger",
            name="OK Node",
            position_x=0,
            position_y=0,
        )
        node_fail = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="condition",
            name="Fail Node",
            position_x=200,
            position_y=0,
        )
        execution = WorkflowExecution.objects.create(
            workflow=workflow,
            space=project,
            trigger_type="manual",
            triggered_by=user,
            status="failed",
            error_message="Node execution failed",
        )

        NodeExecution.objects.create(
            workflow_execution=execution,
            node=node_ok,
            status="completed",
            input_data={},
            output_data={"ok": True},
            logs=[{"timestamp": "2026-05-01T12:00:00Z", "level": "INFO", "message": "OK"}],
            error_code=None,
        )
        NodeExecution.objects.create(
            workflow_execution=execution,
            node=node_fail,
            status="failed",
            input_data={},
            output_data={},
            logs=[
                {"timestamp": "2026-05-01T12:00:01Z", "level": "ERROR", "message": "Failed"},
            ],
            error_code="NODE_EXECUTION_ERROR",
            error_message="Something went wrong",
        )

        serializer = WorkflowExecutionSerializer(execution)
        data = serializer.data

        # 验证两个节点的完整字段
        assert len(data["node_executions"]) == 2
        ne_list = {ne["node_name"]: ne for ne in data["node_executions"]}

        assert ne_list["OK Node"]["error_code"] is None
        assert ne_list["OK Node"]["output_data"] == {"ok": True}
        assert len(ne_list["OK Node"]["logs"]) == 1

        assert ne_list["Fail Node"]["error_code"] == "NODE_EXECUTION_ERROR"
        assert ne_list["Fail Node"]["error_message"] == "Something went wrong"
        assert len(ne_list["Fail Node"]["logs"]) == 1
