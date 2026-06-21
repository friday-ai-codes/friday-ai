"""工作流测试共享 fixtures。

提供 Workflow、WorkflowNode、WorkflowExecution、NodeExecution、
SubAgentSession、ActionLog、TokenUsage 等测试数据工厂。
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from agents.models import AgentSession
from projects.models import Project
from subagent.models import ActionLog, SubAgentSession, TokenUsage
from workflows.engine.scheduler import WorkflowEngine
from workflows.models import (
    NodeExecution,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
)
from workflows.nodes.base import BaseNode, ExecutionContext, NodeCategory, NodeResult
from workflows.nodes.registry import NodeRegistry


@pytest.fixture
def obs_project(db):
    """可观测性测试用项目。"""
    return Project.objects.create(
        name="Obs Test Project",
        description="Project for observability API tests",
    )


@pytest.fixture
def obs_workflow(db, obs_project, user):
    """可观测性测试用工作流。"""
    return Workflow.objects.create(
        name="Obs Test Workflow",
        project=obs_project,
        created_by=user,
    )


@pytest.fixture
def obs_nodes(obs_workflow):
    """创建 3 个测试节点（用于 timeline 瓶颈标识测试）。"""
    _now = timezone.now()
    node1 = WorkflowNode.objects.create(
        workflow=obs_workflow,
        node_type="ai_coding",
        name="AI Coding Node",
        position_x=100,
        position_y=100,
    )
    node2 = WorkflowNode.objects.create(
        workflow=obs_workflow,
        node_type="create_branch",
        name="Create Branch",
        position_x=300,
        position_y=100,
    )
    node3 = WorkflowNode.objects.create(
        workflow=obs_workflow,
        node_type="ai_coding",
        name="AI Coding",
        position_x=500,
        position_y=100,
    )
    return node1, node2, node3


@pytest.fixture
def obs_execution(obs_workflow, user):
    """可观测性测试用工作流执行。"""
    now = timezone.now()
    return WorkflowExecution.objects.create(
        workflow=obs_workflow,
        project=obs_workflow.project,
        trigger_type="manual",
        triggered_by=user,
        status="completed",
        started_at=now - timedelta(seconds=300),
        completed_at=now,
    )


@pytest.fixture
def obs_node_executions(obs_execution, obs_nodes):
    """创建 3 个节点执行（不同耗时，用于 timeline 瓶颈标识）。"""
    node1, node2, node3 = obs_nodes
    now = timezone.now()

    ne1 = NodeExecution.objects.create(
        workflow_execution=obs_execution,
        node=node1,
        status="completed",
        started_at=now - timedelta(seconds=200),
        completed_at=now - timedelta(seconds=100),  # 100s duration (最慢 -> critical)
    )
    ne2 = NodeExecution.objects.create(
        workflow_execution=obs_execution,
        node=node2,
        status="completed",
        started_at=now - timedelta(seconds=100),
        completed_at=now - timedelta(seconds=60),  # 40s duration (第二 -> warning)
    )
    ne3 = NodeExecution.objects.create(
        workflow_execution=obs_execution,
        node=node3,
        status="completed",
        started_at=now - timedelta(seconds=60),
        completed_at=now - timedelta(seconds=40),  # 20s duration (第三 -> warning)
    )
    return ne1, ne2, ne3


@pytest.fixture
def obs_agent_session(db, obs_project, user):
    """创建 AgentSession（SubAgentSession 的 FK 依赖）。"""
    return AgentSession.objects.create(
        session_id="test-agent-session-001",
        project=obs_project,
        user=user,
        status="completed",
    )


@pytest.fixture
def obs_subagent_session(obs_agent_session, obs_node_executions):
    """创建关联到第一个 NodeExecution 的 SubAgentSession。"""
    ne1 = obs_node_executions[0]
    return SubAgentSession.objects.create(
        session_id="sub-test-001",
        main_session=obs_agent_session,
        repo_url="https://github.com/test/repo.git",
        task_type="coding",
        status="completed",
        node_execution=ne1,
    )


@pytest.fixture
def obs_action_logs(obs_subagent_session):
    """创建 3 条 ActionLog 记录。"""
    now = timezone.now()
    log1 = ActionLog.objects.create(
        session=obs_subagent_session,
        action_type="llm_request",
        timestamp=now - timedelta(seconds=10),
        sequence=1,
        payload={"prompt": "Generate code for feature X"},
        duration_ms=500,
    )
    log2 = ActionLog.objects.create(
        session=obs_subagent_session,
        action_type="tool_call",
        timestamp=now - timedelta(seconds=8),
        sequence=2,
        payload={"tool": "write_file", "path": "src/feature.py", "content": "x" * 300},
        duration_ms=200,
    )
    log3 = ActionLog.objects.create(
        session=obs_subagent_session,
        action_type="llm_response",
        timestamp=now - timedelta(seconds=5),
        sequence=3,
        payload={"response": "Code generated successfully"},
        duration_ms=1000,
    )
    return log1, log2, log3


@pytest.fixture
def obs_token_usages(obs_subagent_session):
    """创建 2 条 TokenUsage 记录（不同模型）。"""
    usage1 = TokenUsage.objects.create(
        session=obs_subagent_session,
        input_tokens=1000,
        output_tokens=500,
        cache_read_tokens=200,
        cache_write_tokens=100,
        total_cost_usd=Decimal("0.015000"),
        model="claude-sonnet-4-20250514",
    )
    usage2 = TokenUsage.objects.create(
        session=obs_subagent_session,
        input_tokens=2000,
        output_tokens=800,
        cache_read_tokens=300,
        cache_write_tokens=150,
        total_cost_usd=Decimal("0.045000"),
        model="claude-opus-4-20250514",
    )
    return usage1, usage2


# ===========================================================================
# 引擎集成测试共享基建（Phase 18，18-02/03/04/05 共用）
#
# 可控测试节点 + 工作流工厂 + engine 夹具。范式照抄
# test_error_handling.py（可控节点 + 注册/注销）与 test_engine.py（工厂三件套）。
# 注意：节点注册夹具 `engine_test_nodes` 为具名 fixture（非 autouse）——
# conftest 级 autouse 会污染全目录测试。
# ===========================================================================


class BranchNode(BaseNode):
    """条件分支测试节点：按类属性 `_next_handle` 返回 next_handle（可控旋钮）。"""

    node_type = "test_branch"
    display_name = "Branch"
    description = "Returns a controllable next_handle for branch routing tests"
    category = NodeCategory.CONTROL
    execution_mode = "server_local"

    _next_handle = "true"

    async def execute(self, context: ExecutionContext) -> NodeResult:
        return NodeResult(
            status="completed",
            output={"branch": type(self)._next_handle},
            next_handle=type(self)._next_handle,
        )


class WaitEventNode(BaseNode):
    """等待外部事件测试节点：返回 waiting_event，类属性 `_exec_count` 计数。"""

    node_type = "test_wait_event"
    display_name = "WaitEvent"
    description = "Returns waiting_event to suspend the workflow"
    category = NodeCategory.ACTION
    execution_mode = "server_local"

    _exec_count = 0

    async def execute(self, context: ExecutionContext) -> NodeResult:
        type(self)._exec_count += 1
        return NodeResult(status="waiting_event", output={})


class WaitApprovalNode(BaseNode):
    """等待审批测试节点：返回 waiting_approval，类属性 `_exec_count` 计数（18-03 热循环断言用）。"""

    node_type = "test_wait_approval"
    display_name = "WaitApproval"
    description = "Returns waiting_approval to suspend the workflow"
    category = NodeCategory.ACTION
    execution_mode = "server_local"

    _exec_count = 0

    async def execute(self, context: ExecutionContext) -> NodeResult:
        type(self)._exec_count += 1
        return NodeResult(status="waiting_approval", output={})


class ResumableWaitEventNode(BaseNode):
    """可恢复等待节点：首次执行返回 waiting_event 挂起；当 NE.output_data 含恢复标记
    ``_resume_from_callback`` 时返回 completed。

    模拟容器回调到达后 ai_coding "消费恢复标记 → 重跑节点终态" 的范式（18-04 A1
    断裂修复用）。类属性 ``_exec_count`` 记录 execute 调用次数，断言节点确被重跑。
    """

    node_type = "test_resumable_wait"
    display_name = "ResumableWait"
    description = "Waits until a resume marker is present, then completes"
    category = NodeCategory.ACTION
    execution_mode = "server_local"

    _exec_count = 0

    async def execute(self, context: ExecutionContext) -> NodeResult:
        type(self)._exec_count += 1
        ne = context.node_execution
        output_data = (ne.output_data or {}) if ne is not None else {}
        if output_data.get("_resume_from_callback"):
            return NodeResult(status="completed", output={"resumed": True})
        return NodeResult(status="waiting_event", output={})


class EchoInputsNode(BaseNode):
    """回显输入测试节点：输出 `context.input_data` 供输入归集断言。"""

    node_type = "test_echo_inputs"
    display_name = "EchoInputs"
    description = "Echoes the node's collected input_data"
    category = NodeCategory.ACTION
    execution_mode = "server_local"

    async def execute(self, context: ExecutionContext) -> NodeResult:
        return NodeResult(
            status="completed",
            output={"echoed_inputs": dict(context.input_data)},
        )


class EchoTriggerDataNode(BaseNode):
    """回显触发数据测试节点：输出 `context.trigger_data`（18-05 消费）。"""

    node_type = "test_echo_trigger"
    display_name = "EchoTrigger"
    description = "Echoes the execution's trigger_data"
    category = NodeCategory.ACTION
    execution_mode = "server_local"

    async def execute(self, context: ExecutionContext) -> NodeResult:
        return NodeResult(
            status="completed",
            output={"echoed_trigger": dict(context.trigger_data)},
        )


@pytest.fixture
def engine():
    """WorkflowEngine 实例（照抄 test_error_handling.py:134-137）。"""
    return WorkflowEngine()


@pytest.fixture
def engine_project(db):
    """引擎集成测试用项目。"""
    return Project.objects.create(
        name="Engine Integration Test Project",
        description="Project for engine integration tests",
    )


@pytest.fixture
def engine_test_nodes():
    """注册五个可控测试节点，测试结束后逐个注销并复位类属性旋钮/计数器。

    具名 fixture（非 autouse）——仅显式请求的测试加载，避免污染全目录。
    """
    # 复位可控旋钮 / 计数器，保证用例间隔离
    BranchNode._next_handle = "true"
    WaitEventNode._exec_count = 0
    WaitApprovalNode._exec_count = 0
    ResumableWaitEventNode._exec_count = 0

    NodeRegistry.register(BranchNode)
    NodeRegistry.register(WaitEventNode)
    NodeRegistry.register(WaitApprovalNode)
    NodeRegistry.register(ResumableWaitEventNode)
    NodeRegistry.register(EchoInputsNode)
    NodeRegistry.register(EchoTriggerDataNode)
    yield
    NodeRegistry._nodes.pop("test_branch", None)
    NodeRegistry._nodes.pop("test_wait_event", None)
    NodeRegistry._nodes.pop("test_wait_approval", None)
    NodeRegistry._nodes.pop("test_resumable_wait", None)
    NodeRegistry._nodes.pop("test_echo_inputs", None)
    NodeRegistry._nodes.pop("test_echo_trigger", None)
    # 注销后复位旋钮/计数器，避免跨测试残留
    BranchNode._next_handle = "true"
    WaitEventNode._exec_count = 0
    WaitApprovalNode._exec_count = 0
    ResumableWaitEventNode._exec_count = 0


@pytest.fixture
def branch_workflow(db, engine_project):
    """菱形分支工作流：manual_trigger → Branch → TrueSide / FalseSide → Join。

    - Branch 出边 source_handle 分别为 "true"/"false"；
    - TrueSide/FalseSide → Join 均 default（菱形汇合，一条活路即执行）。
    节点 name 唯一且语义化，便于按 node__name 查询 NE 状态断言。
    """
    workflow = Workflow.objects.create(
        name="Branch Workflow",
        project=engine_project,
        trigger_type="manual",
    )
    trigger = WorkflowNode.objects.create(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )
    branch = WorkflowNode.objects.create(
        workflow=workflow, node_type="test_branch", name="Branch", position_x=200, position_y=0
    )
    true_side = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="test_echo_inputs",
        name="TrueSide",
        position_x=400,
        position_y=-100,
    )
    false_side = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="test_echo_inputs",
        name="FalseSide",
        position_x=400,
        position_y=100,
    )
    join = WorkflowNode.objects.create(
        workflow=workflow, node_type="test_echo_inputs", name="Join", position_x=600, position_y=0
    )

    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=trigger,
        target_node=branch,
        source_handle="default",
        target_handle="default",
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=branch,
        target_node=true_side,
        source_handle="true",
        target_handle="default",
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=branch,
        target_node=false_side,
        source_handle="false",
        target_handle="default",
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=true_side,
        target_node=join,
        source_handle="default",
        target_handle="default",
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=false_side,
        target_node=join,
        source_handle="default",
        target_handle="default",
    )
    return workflow


@pytest.fixture
def waiting_workflow(db, engine_project):
    """挂起工作流：manual_trigger → WaitEvent → Downstream（18-03 消费）。"""
    workflow = Workflow.objects.create(
        name="Waiting Workflow",
        project=engine_project,
        trigger_type="manual",
    )
    trigger = WorkflowNode.objects.create(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )
    waiter = WorkflowNode.objects.create(
        workflow=workflow, node_type="test_wait_event", name="Waiter", position_x=200, position_y=0
    )
    downstream = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="test_echo_inputs",
        name="Downstream",
        position_x=400,
        position_y=0,
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=trigger,
        target_node=waiter,
        source_handle="default",
        target_handle="default",
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=waiter,
        target_node=downstream,
        source_handle="default",
        target_handle="default",
    )
    return workflow


@pytest.fixture
def waiting_terminal_workflow(db, engine_project):
    """末端挂起工作流：manual_trigger → WaitEvent（无下游，18-03 消费）。"""
    workflow = Workflow.objects.create(
        name="Waiting Terminal Workflow",
        project=engine_project,
        trigger_type="manual",
    )
    trigger = WorkflowNode.objects.create(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )
    waiter = WorkflowNode.objects.create(
        workflow=workflow, node_type="test_wait_event", name="Waiter", position_x=200, position_y=0
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=trigger,
        target_node=waiter,
        source_handle="default",
        target_handle="default",
    )
    return workflow
