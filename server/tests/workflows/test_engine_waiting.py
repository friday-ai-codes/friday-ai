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

from tests.workflows.conftest import ResumableWaitEventNode, WaitApprovalNode
from workflows.models import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
    Workflow,
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


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestCallbackResume:
    """回调续跑：重建状态重入主循环（ENG-01/02，18-04）。

    锁定 CONTEXT 决策"恢复后语义与主循环一致" + 容器回调断裂修复（A1）+ 执行级互斥。
    """

    async def test_callback_resume_completes_downstream(
        self, engine, engine_test_nodes, waiting_workflow
    ):
        """Test 1：挂起后 Waiter 事件到达（手工 amark_completed）→ 续跑入口推进下游至完成。"""
        execution = await engine.start_execution(
            workflow=waiting_workflow,
            input_data={},
            run_sync=True,
        )
        assert execution.status == ExecutionStatus.SUSPENDED

        waiter_ne = await NodeExecution_for(execution, "Waiter")
        assert waiter_ne is not None
        # 模拟 wait_feishu 事件到达：节点终态
        await waiter_ne.amark_completed({})

        await engine._continue_after_node(execution, waiter_ne)

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED

        downstream_ne = await NodeExecution_for(execution, "Downstream")
        assert downstream_ne is not None
        assert downstream_ne.status == NodeExecutionStatus.COMPLETED

    async def test_dual_path_consistency(
        self, engine, engine_test_nodes, branch_workflow, engine_project
    ):
        """Test 2（ENG-02 锚点）：同一分支结构走主循环 vs 挂起-续跑，最终 NE 状态集合一致。"""
        # 路径 A：纯主循环
        exec_a = await engine.start_execution(
            workflow=branch_workflow, input_data={}, run_sync=True
        )
        await exec_a.arefresh_from_db()
        assert exec_a.status == ExecutionStatus.COMPLETED
        states_a = await _ne_status_map(exec_a)

        # 路径 B：分支节点前插 ResumableWait，挂起后回调续跑
        wf_b = await sync_to_async(_build_wait_branch_workflow)(engine_project)
        exec_b = await engine.start_execution(workflow=wf_b, input_data={}, run_sync=True)
        assert exec_b.status == ExecutionStatus.SUSPENDED

        wait_ne = await NodeExecution_for(exec_b, "Waiter")
        assert wait_ne is not None
        marked = dict(wait_ne.output_data or {})
        marked["_resume_from_callback"] = True
        wait_ne.output_data = marked
        await wait_ne.asave(update_fields=["output_data"])

        await engine._continue_after_node(exec_b, wait_ne)
        await exec_b.arefresh_from_db()
        assert exec_b.status == ExecutionStatus.COMPLETED
        states_b = await _ne_status_map(exec_b)

        # 分支区域节点（两图共有）最终状态逐一一致
        for name in ("Branch", "TrueSide", "FalseSide", "Join"):
            assert states_a[name] == states_b[name], (
                f"双路径 {name} 状态漂移：A={states_a[name]} B={states_b[name]}"
            )
        assert states_a["TrueSide"] == NodeExecutionStatus.COMPLETED
        assert states_a["FalseSide"] == NodeExecutionStatus.SKIPPED

    async def test_marked_node_rerun_fixes_broken_chain(
        self, engine, engine_test_nodes, engine_project
    ):
        """Test 3（A1 断裂修复，红测先行）：带 _resume_from_callback 标记且仍 WAITING_EVENT
        的节点被续跑入口重新 execute（计数器+1）且执行推进；修复前节点不重跑、下游不执行。"""
        wf = await sync_to_async(_build_resumable_wait_workflow)(engine_project)
        ResumableWaitEventNode._exec_count = 0

        execution = await engine.start_execution(workflow=wf, input_data={}, run_sync=True)
        assert execution.status == ExecutionStatus.SUSPENDED
        assert ResumableWaitEventNode._exec_count == 1

        waiter_ne = await NodeExecution_for(execution, "Waiter")
        marked = dict(waiter_ne.output_data or {})
        marked["_resume_from_callback"] = True
        waiter_ne.output_data = marked
        await waiter_ne.asave(update_fields=["output_data"])

        await engine._continue_after_node(execution, waiter_ne)

        await execution.arefresh_from_db()
        # A1：节点被重跑（消费标记）且执行推进
        assert ResumableWaitEventNode._exec_count == 2
        assert execution.status == ExecutionStatus.COMPLETED

        downstream_ne = await NodeExecution_for(execution, "Downstream")
        assert downstream_ne.status == NodeExecutionStatus.COMPLETED

    async def test_concurrent_resume_mutex_no_double_exec(
        self, engine, engine_test_nodes, engine_project
    ):
        """Test 4（并发互斥）：同一挂起执行连续两次续跑——第二次执行已终态，放弃续跑，
        节点不被重复执行（execute 恰好一次重跑）。"""
        wf = await sync_to_async(_build_resumable_wait_workflow)(engine_project)
        ResumableWaitEventNode._exec_count = 0

        execution = await engine.start_execution(workflow=wf, input_data={}, run_sync=True)
        assert execution.status == ExecutionStatus.SUSPENDED
        assert ResumableWaitEventNode._exec_count == 1

        waiter_ne = await NodeExecution_for(execution, "Waiter")
        marked = dict(waiter_ne.output_data or {})
        marked["_resume_from_callback"] = True
        waiter_ne.output_data = marked
        await waiter_ne.asave(update_fields=["output_data"])

        # 第一次：抢锁成功 → 重跑节点一次 → 完成
        await engine._continue_after_node(execution, waiter_ne)
        # 第二次（模拟并发到达的第二个回调）：执行已终态 → 放弃续跑，不重复执行
        await engine._continue_after_node(execution, waiter_ne)

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.COMPLETED
        # 重跑恰一次（互斥/终态守卫防双执行）
        assert ResumableWaitEventNode._exec_count == 2


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


async def NodeExecution_for(execution, node_name):
    """按 node__name 查 NodeExecution（范式照抄 test_error_handling.py 模式 E）。"""
    return await NodeExecution.objects.filter(
        workflow_execution=execution, node__name=node_name
    ).afirst()


async def _ne_status_map(execution) -> dict[str, str]:
    """返回 {node_name: NE.status} 映射，供双路径一致性逐节点比对。"""
    return {
        ne.node.name: ne.status
        async for ne in NodeExecution.objects.filter(workflow_execution=execution).select_related(
            "node"
        )
    }


def _build_resumable_wait_workflow(engine_project):
    """trigger → ResumableWait(Waiter) → Downstream（续跑断裂/互斥用）。"""
    workflow = Workflow.objects.create(
        name="Resumable Wait Workflow",
        space=engine_project,
        trigger_type="manual",
    )
    trigger = WorkflowNode.objects.create(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )
    waiter = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="test_resumable_wait",
        name="Waiter",
        position_x=200,
        position_y=0,
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


def _build_wait_branch_workflow(engine_project):
    """trigger → ResumableWait(Waiter) → Branch → TrueSide/FalseSide → Join（双路径一致性 B 路径）。"""
    workflow = Workflow.objects.create(
        name="Wait Branch Workflow",
        space=engine_project,
        trigger_type="manual",
    )
    trigger = WorkflowNode.objects.create(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )
    waiter = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="test_resumable_wait",
        name="Waiter",
        position_x=200,
        position_y=0,
    )
    branch = WorkflowNode.objects.create(
        workflow=workflow, node_type="test_branch", name="Branch", position_x=400, position_y=0
    )
    true_side = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="test_echo_inputs",
        name="TrueSide",
        position_x=600,
        position_y=-100,
    )
    false_side = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="test_echo_inputs",
        name="FalseSide",
        position_x=600,
        position_y=100,
    )
    join = WorkflowNode.objects.create(
        workflow=workflow, node_type="test_echo_inputs", name="Join", position_x=800, position_y=0
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


def _build_approval_workflow(engine_project):
    """trigger → WaitApprovalNode 工作流（同步构造，供热循环断言）。"""
    from workflows.models import Workflow

    workflow = Workflow.objects.create(
        name="Approval Hot-Loop Workflow",
        space=engine_project,
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
