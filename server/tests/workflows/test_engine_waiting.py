"""waiting_event / waiting_approval 挂起语义集成测试（Phase 18 ENG-01，主循环侧）。

锁定 CONTEXT 决策"等待即 suspended"：
- 末端 / 带下游的 waiting_event 执行收口一律 SUSPENDED（绝非 COMPLETED）；
- run_sync 立即返回（5s 轮询分支已删，无延时）；
- 挂起触发 execution_suspended hook（WS 广播链路可达）；
- waiting_approval 节点不再热循环（单次执行内节点 execute 恰好一次）；
- stop_before 出口与正常出口共用收口，waiting 非空仍判 SUSPENDED。

范式照抄 test_error_handling.py（run_sync + django_db(transaction=True)），
消费 18-02 conftest 的 engine / engine_test_nodes / waiting_*_workflow 夹具。
"""

import time

import pytest
from asgiref.sync import sync_to_async

from tests.workflows.conftest import WaitApprovalNode
from workflows.models import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
    WorkflowEdge,
    WorkflowNode,
)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestWaitingSuspension:
    """末端/带下游等待与审批挂起的执行收口语义。"""

    async def test_terminal_waiting_event_suspends(
        self, engine, engine_test_nodes, waiting_terminal_workflow
    ):
        """Test 1：末端 waiting_event 节点 → 执行 SUSPENDED（绝非 COMPLETED）。"""
        execution = await engine.start_execution(
            workflow=waiting_terminal_workflow,
            input_data={},
            run_sync=True,
        )

        assert execution.status == ExecutionStatus.SUSPENDED

        waiter_ne = await NodeExecution_for(execution, "Waiter")
        assert waiter_ne is not None
        assert waiter_ne.status == NodeExecutionStatus.WAITING_EVENT

    async def test_waiting_event_with_downstream_suspends_immediately(
        self, engine, engine_test_nodes, waiting_workflow
    ):
        """Test 2：带下游 waiting_event → 立即返回 SUSPENDED（无 5s 轮询延时）。"""
        started = time.monotonic()
        execution = await engine.start_execution(
            workflow=waiting_workflow,
            input_data={},
            run_sync=True,
        )
        elapsed = time.monotonic() - started

        assert execution.status == ExecutionStatus.SUSPENDED
        # 轮询分支删除后立即返回，绝不接近旧的 asyncio.sleep(5)
        assert elapsed < 3, f"run_sync 耗时 {elapsed:.2f}s，疑似残留轮询延时"

        downstream_ne = await NodeExecution_for(execution, "Downstream")
        assert downstream_ne is not None
        # 下游仍 PENDING（未被执行，依赖 waiter 续跑）
        assert downstream_ne.status == NodeExecutionStatus.PENDING

    async def test_execution_suspended_hook_triggered(
        self, engine, engine_test_nodes, waiting_terminal_workflow
    ):
        """Test 3：挂起时 execution_suspended hook 被触发（WS 广播链路可达）。"""
        spy_calls: list[str] = []

        def spy(event, **kwargs):
            execution = kwargs.get("execution")
            spy_calls.append(execution.status if execution is not None else "")

        engine.hooks.register_callback("execution_suspended", spy)

        execution = await engine.start_execution(
            workflow=waiting_terminal_workflow,
            input_data={},
            run_sync=True,
        )

        assert execution.status == ExecutionStatus.SUSPENDED
        assert len(spy_calls) == 1
        assert spy_calls[0] == ExecutionStatus.SUSPENDED

    async def test_waiting_approval_does_not_hot_loop(
        self, engine, engine_test_nodes, engine_project
    ):
        """Test 4：waiting_approval 节点单次执行恰好一次（热循环消灭）。"""
        workflow = await sync_to_async(_build_approval_workflow)(engine_project)

        WaitApprovalNode._exec_count = 0
        execution = await engine.start_execution(
            workflow=workflow,
            input_data={},
            run_sync=True,
        )

        assert execution.status == ExecutionStatus.SUSPENDED
        # 热循环复发时 _exec_count > 1，此断言为防回归锚点
        assert WaitApprovalNode._exec_count == 1

    async def test_stop_before_exit_not_misjudged_completed(
        self, engine, engine_test_nodes, waiting_workflow
    ):
        """Test 5：stop_before 出口不误判完成（waiting 非空仍 SUSPENDED，无 running 残留）。"""
        downstream = await sync_to_async(
            lambda: WorkflowNode.objects.get(workflow=waiting_workflow, name="Downstream")
        )()

        execution = await engine.start_execution(
            workflow=waiting_workflow,
            input_data={},
            run_sync=True,
            stop_before_node_id=str(downstream.id),
        )

        # 绝不 COMPLETED（双出口收口覆盖 Pitfall 5）
        assert execution.status != ExecutionStatus.COMPLETED
        assert execution.status == ExecutionStatus.SUSPENDED

        # 无 running 残留节点
        running_count = await sync_to_async(
            lambda: execution.node_executions.filter(status=NodeExecutionStatus.RUNNING).count()
        )()
        assert running_count == 0


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


async def NodeExecution_for(execution, node_name):
    """按 node__name 查 NodeExecution（范式照抄 test_error_handling.py 模式 E）。"""
    return await NodeExecution.objects.filter(
        workflow_execution=execution, node__name=node_name
    ).afirst()


def _build_approval_workflow(engine_project):
    """trigger → WaitApprovalNode 工作流（同步构造，供热循环断言）。"""
    from workflows.models import Workflow

    workflow = Workflow.objects.create(
        name="Approval Hot-Loop Workflow",
        project=engine_project,
        trigger_type="manual",
    )
    trigger = WorkflowNode.objects.create(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )
    approver = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="test_wait_approval",
        name="Approver",
        position_x=200,
        position_y=0,
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=trigger,
        target_node=approver,
        source_handle="default",
        target_handle="default",
    )
    return workflow
