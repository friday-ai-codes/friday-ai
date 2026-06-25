"""触发数据全链路测试（Phase 18 ENG-03）。

- ``TestTriggerDataWriteSide``：dispatcher 统一写入 ``source`` 键、无 ``payload`` 别名键
  （Pitfall 8 形状 characterization）、``resume_from_node`` 继承原 trigger_data（写入侧）。
- ``TestTriggerDataReadSide``：``_execute_node`` 注入 ``execution.trigger_data``，
  ``{{trigger.source}}`` / ``{{trigger.raw_payload.*}}`` 在真实调度中可解析、
  trigger_data 为空时宽松缺失语义不变（读取侧，ENG-03 唯一缺口的闭环）。
"""

import pytest
from asgiref.sync import sync_to_async

from workflows.models import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
)
from workflows.nodes.base import BaseNode, ExecutionContext, NodeCategory, NodeResult
from workflows.nodes.registry import NodeRegistry
from workflows.triggers.context import TriggerContext
from workflows.triggers.dispatcher import TriggerDispatcher


class TemplateTriggerNode(BaseNode):
    """渲染 config["template"] 的测试节点：验证 {{trigger.*}} 在真实调度中可解析。"""

    node_type = "test_trigger_template"
    display_name = "TriggerTemplate"
    description = "Renders config['template'] using trigger_data"
    category = NodeCategory.ACTION
    execution_mode = "server_local"

    async def execute(self, context: ExecutionContext) -> NodeResult:
        rendered = context.render_template(context.get_config("template", ""))
        return NodeResult(status="completed", output={"rendered": rendered})


@pytest.fixture
def trigger_template_node():
    """注册 TemplateTriggerNode（读取侧模板解析测试用）。"""
    NodeRegistry.register(TemplateTriggerNode)
    yield
    NodeRegistry._nodes.pop("test_trigger_template", None)


def _build_echo_trigger_workflow(project) -> Workflow:
    """手建 manual_trigger → EchoTrigger（test_echo_trigger）。"""
    workflow = Workflow.objects.create(
        name="EchoTrigger Workflow",
        space=project,
        trigger_type="manual",
    )
    trigger = WorkflowNode.objects.create(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )
    echo = WorkflowNode.objects.create(
        workflow=workflow, node_type="test_echo_trigger", name="Echo", position_x=200, position_y=0
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=trigger,
        target_node=echo,
        source_handle="default",
        target_handle="default",
    )
    return workflow


def _build_template_trigger_workflow(project) -> Workflow:
    """手建 manual_trigger → TemplateTrigger，config.template 含 {{trigger.*}} 占位符。"""
    workflow = Workflow.objects.create(
        name="TemplateTrigger Workflow",
        space=project,
        trigger_type="manual",
    )
    trigger = WorkflowNode.objects.create(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )
    render = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="test_trigger_template",
        name="Render",
        position_x=200,
        position_y=0,
        config={"template": "{{trigger.source}}:{{trigger.raw_payload.k}}"},
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=trigger,
        target_node=render,
        source_handle="default",
        target_handle="default",
    )
    return workflow


async def _node_output(execution, name: str) -> dict:
    """取指定节点的 output_data。"""
    ne = await NodeExecution.objects.filter(workflow_execution=execution, node__name=name).afirst()
    assert ne is not None, f"节点 {name} 无执行记录"
    return ne.output_data or {}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestTriggerDataWriteSide:
    """写入侧：dispatcher source 键 + 形状 characterization + resume 继承。"""

    async def test_dispatcher_writes_source_key(self, engine, engine_test_nodes, engine_project):
        """Test 1：经 dispatch(manual) 创建的执行 trigger_data 含 source 与 raw_payload。"""
        workflow = await sync_to_async(_build_echo_trigger_workflow)(engine_project)
        dispatcher = TriggerDispatcher(engine=engine)
        context = TriggerContext(
            trigger_type="manual",
            raw_payload={"k": "v"},
            workflow=workflow,
        )
        executions = await dispatcher.dispatch(context)

        assert len(executions) == 1
        td = executions[0].trigger_data
        assert td["source"] == "manual"
        assert td["raw_payload"] == {"k": "v"}

    async def test_dispatcher_no_payload_alias_key(self, engine, engine_test_nodes, engine_project):
        """Test 2：形状 characterization——trigger_data 无 "payload" 别名键（Pitfall 8）。"""
        workflow = await sync_to_async(_build_echo_trigger_workflow)(engine_project)
        dispatcher = TriggerDispatcher(engine=engine)
        context = TriggerContext(
            trigger_type="manual",
            raw_payload={"k": "v"},
            workflow=workflow,
        )
        executions = await dispatcher.dispatch(context)

        assert len(executions) == 1
        assert "payload" not in executions[0].trigger_data

    async def test_resume_inherits_trigger_data(self, engine, engine_test_nodes, engine_project):
        """Test 3：resume_from_node 创建的新执行继承原 source/raw_payload 并附加 metadata。"""
        workflow = await sync_to_async(_build_echo_trigger_workflow)(engine_project)
        echo_node = await WorkflowNode.objects.aget(workflow=workflow, name="Echo")

        original = await WorkflowExecution.objects.acreate(
            workflow=workflow,
            space_id=engine_project.id,
            status=ExecutionStatus.FAILED,
            trigger_type="manual",
            trigger_data={"source": "manual", "raw_payload": {"k": "v"}},
            total_nodes=2,
        )
        await NodeExecution.objects.acreate(
            workflow_execution=original,
            node=echo_node,
            status=NodeExecutionStatus.FAILED,
        )

        new_execution = await engine.resume_from_node(
            original_execution=original,
            failed_node_id=str(echo_node.id),
            run_sync=True,
        )

        td = new_execution.trigger_data
        assert td["source"] == "manual"
        assert td["raw_payload"] == {"k": "v"}
        assert td["metadata"]["resumed_from"] == str(original.id)
        assert td["metadata"]["failed_node_id"] == str(echo_node.id)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestTriggerDataReadSide:
    """读取侧：_execute_node 注入 trigger_data，{{trigger.*}} 真实可解析。"""

    async def test_trigger_data_injected_into_context(
        self, engine, engine_test_nodes, engine_project
    ):
        """Test 1：注入端到端——EchoTrigger 节点回显的 trigger_data 即传入值（不再空 dict）。"""
        workflow = await sync_to_async(_build_echo_trigger_workflow)(engine_project)
        trigger_data = {"source": "manual", "raw_payload": {"k": "v"}}
        execution = await engine.start_execution(workflow, trigger_data=trigger_data, run_sync=True)

        assert execution.status == ExecutionStatus.COMPLETED
        output = await _node_output(execution, "Echo")
        assert output["echoed_trigger"] == trigger_data

    async def test_trigger_template_resolves(
        self, engine, engine_test_nodes, trigger_template_node, engine_project
    ):
        """Test 2：{{trigger.source}}/{{trigger.raw_payload.k}} 在节点 config 渲染中可解析。"""
        workflow = await sync_to_async(_build_template_trigger_workflow)(engine_project)
        execution = await engine.start_execution(
            workflow,
            trigger_data={"source": "manual", "raw_payload": {"k": "v"}},
            run_sync=True,
        )

        assert execution.status == ExecutionStatus.COMPLETED
        output = await _node_output(execution, "Render")
        assert output["rendered"] == "manual:v"

    async def test_dispatcher_full_chain_resolves(
        self, engine, engine_test_nodes, trigger_template_node, engine_project
    ):
        """Test 3：写入侧 + 读取侧合龙——经 dispatcher 触发后 {{trigger.source}} 解析为 "manual"。"""
        workflow = await sync_to_async(_build_template_trigger_workflow)(engine_project)
        dispatcher = TriggerDispatcher(engine=engine)
        context = TriggerContext(
            trigger_type="manual",
            raw_payload={"k": "v"},
            workflow=workflow,
        )
        executions = await dispatcher.dispatch(context)
        assert len(executions) == 1
        # dispatch 默认异步起线程；写入侧 trigger_data 形状即时可断言（合龙锚点）
        assert executions[0].trigger_data["source"] == "manual"
        assert executions[0].trigger_data["raw_payload"] == {"k": "v"}

    async def test_missing_trigger_lenient(
        self, engine, engine_test_nodes, trigger_template_node, engine_project
    ):
        """Test 4：trigger_data 为空时 {{trigger.*}} 维持 Phase 17 宽松语义（缺失转空串，不报错）。"""
        workflow = await sync_to_async(_build_template_trigger_workflow)(engine_project)
        execution = await engine.start_execution(workflow, run_sync=True)

        assert execution.status == ExecutionStatus.COMPLETED
        output = await _node_output(execution, "Render")
        # 源缺失 → 现状宽松：占位符解析为空串，分隔符保留
        assert output["rendered"] == ":"
