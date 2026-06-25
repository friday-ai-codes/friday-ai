"""死锁诊断纯函数测试（Phase 18 ENG-04，Task 3）。

零 DB：复用 test_engine_routing.py 的 _build_dag helper 手工构造 DAG。
diagnose_deadlock 只含拓扑元数据（名称/short_id/状态/handle），绝不读取节点输出值
（V5 信息泄露防线，T-18-01）。

另含 TestDeadlockIntegration（18-03）：直接调 engine._finalize_run_state 注入人造
死锁状态，验证 scheduler 写入侧的完整链路（FAILED + 结构化 error_message + hook），
以及挂起优先于死锁的判定优先级。
"""

import json

import pytest

from tests.workflows.test_engine_routing import _build_dag
from workflows.engine.dag import DAG
from workflows.engine.routing import (
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_WAITING,
    RoutingState,
    diagnose_deadlock,
)
from workflows.models import (
    ExecutionStatus,
    NodeExecution,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
)


class TestDiagnoseDeadlockUnit:
    """死锁三条件判定 + 结构化诊断形状。"""

    def test_mutual_dependency_is_deadlock(self):
        """D1：pending 两节点互为 forward 依赖、无 waiting/running、无 ready → 结构化诊断。"""
        # A <-> B 默认环（default→default 不算 back-edge，构成真实互锁）
        dag = _build_dag(
            [
                ("A", "B", "default", "default"),
                ("B", "A", "default", "default"),
            ]
        )
        state = RoutingState(statuses={"A": STATUS_PENDING, "B": STATUS_PENDING}, handles={})
        result = diagnose_deadlock(dag, state, {"A", "B"})

        assert result is not None
        assert set(result.keys()) == {"reason", "pending"}
        assert result["reason"] == "deadlock"
        assert len(result["pending"]) == 2
        for item in result["pending"]:
            assert set(item.keys()) == {"node", "short_id", "waiting_on"}
            assert len(item["waiting_on"]) == 1
            dep = item["waiting_on"][0]
            assert set(dep.keys()) == {"node", "short_id", "status", "handle"}
            assert dep["status"] == STATUS_PENDING
            assert dep["handle"] == "default"

    def test_waiting_or_running_returns_none(self):
        """D2：存在 status==waiting 或 running 的节点 → None（不误报）。"""
        dag = _build_dag(
            [
                ("A", "B", "default", "default"),
                ("B", "A", "default", "default"),
            ]
        )
        for blocking in (STATUS_WAITING, STATUS_RUNNING):
            state = RoutingState(statuses={"A": STATUS_PENDING, "B": blocking}, handles={})
            assert diagnose_deadlock(dag, state, {"A", "B"}) is None

    def test_ready_node_returns_none(self):
        """D3：pending 中存在 ready 节点 → None。"""
        # A completed → B ready；C 仍 pending。pending 含 ready 节点 B → 非死锁
        dag = _build_dag(
            [
                ("A", "B", "default", "default"),
                ("X", "C", "default", "default"),
            ]
        )
        state = RoutingState(statuses={"A": STATUS_COMPLETED, "X": STATUS_PENDING}, handles={})
        assert diagnose_deadlock(dag, state, {"B", "C"}) is None

    def test_empty_pending_returns_none(self):
        dag = _build_dag([("A", "B", "default", "default")])
        assert diagnose_deadlock(dag, RoutingState(), set()) is None

    def test_diagnosis_serializable_without_output_values(self):
        """D4：诊断 dict json.dumps(ensure_ascii=False) 后不含任何节点 output 值。"""
        secret_value = "TOP_SECRET_OUTPUT_VALUE_xyz"
        # 即便上游产出含敏感值，diagnose_deadlock 也不接收 node_outputs，无从泄露
        node_outputs = {"A": {"leaked": secret_value}, "B": {"leaked": secret_value}}
        dag = _build_dag(
            [
                ("A", "B", "default", "default"),
                ("B", "A", "default", "default"),
            ]
        )
        state = RoutingState(statuses={"A": STATUS_PENDING, "B": STATUS_PENDING}, handles={})
        result = diagnose_deadlock(dag, state, {"A", "B"})
        assert result is not None

        serialized = json.dumps(result, ensure_ascii=False)
        assert secret_value not in serialized
        # 最后一行（整体即一行）可独立 json.loads（Phase 21 错误展示消费）
        assert json.loads(serialized)["reason"] == "deadlock"
        # node_outputs 仅作泄露反证，未传入诊断函数
        assert secret_value in str(node_outputs)


def _build_cyclic_workflow(engine_project):
    """构造默认环工作流 A⇄B（default→default 不算 back-edge，构成真实互锁）。

    18-02 级联修复后正常图结构不再能自然死锁——死锁守卫是针对状态不一致等异常态
    的防御网，故用一个无入口（互为依赖）的 2 节点环验证收口写入侧链路。
    """
    workflow = Workflow.objects.create(
        name="Deadlock Workflow",
        space=engine_project,
        trigger_type="manual",
    )
    node_a = WorkflowNode.objects.create(
        workflow=workflow, node_type="condition", name="NodeA", position_x=0, position_y=0
    )
    node_b = WorkflowNode.objects.create(
        workflow=workflow, node_type="condition", name="NodeB", position_x=200, position_y=0
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_a,
        target_node=node_b,
        source_handle="default",
        target_handle="default",
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_b,
        target_node=node_a,
        source_handle="default",
        target_handle="default",
    )
    execution = WorkflowExecution.objects.create(
        workflow=workflow,
        space=engine_project,
        trigger_type="manual",
        status=ExecutionStatus.RUNNING,
    )
    return workflow, execution, str(node_a.id), str(node_b.id)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDeadlockIntegration:
    """收口判定写 FAILED + 结构化诊断 + 挂起优先级（ENG-04 主循环侧）。"""

    async def test_finalize_writes_failed_with_structured_diagnosis(self, engine, engine_project):
        """Test 1：人造死锁入参 → execution FAILED，error_message 末行结构化可解析。"""
        from asgiref.sync import sync_to_async

        _wf, execution, a_id, b_id = await sync_to_async(_build_cyclic_workflow)(engine_project)
        workflow = await Workflow.objects.aget(pk=_wf.pk)
        dag = await DAG.afrom_workflow(workflow)

        node_statuses = {a_id: STATUS_PENDING, b_id: STATUS_PENDING}
        await engine._finalize_run_state(
            execution,
            dag,
            pending={a_id, b_id},
            waiting=set(),
            failed=set(),
            completed=set(),
            node_statuses=node_statuses,
            node_handles={},
            node_outputs={},
        )

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.FAILED

        lines = execution.error_message.strip().splitlines()
        # 首行中文一句话
        assert "工作流死锁" in lines[0]
        # 末行可独立 json.loads（Phase 21 直接消费）
        payload = json.loads(lines[-1])
        assert payload["reason"] == "deadlock"
        assert len(payload["pending"]) == 2
        first = payload["pending"][0]
        assert set(first.keys()) == {"node", "short_id", "waiting_on"}
        assert len(first["waiting_on"]) >= 1
        dep = first["waiting_on"][0]
        assert set(dep.keys()) == {"node", "short_id", "status", "handle"}

    async def test_diagnosis_excludes_output_values(self, engine, engine_project):
        """Test 2：node_outputs 含哨兵串 → error_message 全文不含（V5 信息泄露防线端到端）。"""
        from asgiref.sync import sync_to_async

        sentinel = "SECRET_OUTPUT_VALUE"
        _wf, execution, a_id, b_id = await sync_to_async(_build_cyclic_workflow)(engine_project)
        workflow = await Workflow.objects.aget(pk=_wf.pk)
        dag = await DAG.afrom_workflow(workflow)

        await engine._finalize_run_state(
            execution,
            dag,
            pending={a_id, b_id},
            waiting=set(),
            failed=set(),
            completed=set(),
            node_statuses={a_id: STATUS_PENDING, b_id: STATUS_PENDING},
            node_handles={},
            node_outputs={a_id: {"leaked": sentinel}, b_id: {"leaked": sentinel}},
        )

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.FAILED
        assert sentinel not in execution.error_message

    async def test_waiting_takes_priority_over_deadlock(self, engine, engine_project):
        """Test 3：同样死锁状态但 waiting 非空 → SUSPENDED 而非 FAILED（判定优先级锚定）。"""
        from asgiref.sync import sync_to_async

        _wf, execution, a_id, b_id = await sync_to_async(_build_cyclic_workflow)(engine_project)
        workflow = await Workflow.objects.aget(pk=_wf.pk)
        dag = await DAG.afrom_workflow(workflow)

        await engine._finalize_run_state(
            execution,
            dag,
            pending={a_id, b_id},
            waiting={a_id},
            failed=set(),
            completed=set(),
            node_statuses={a_id: STATUS_WAITING, b_id: STATUS_PENDING},
            node_handles={},
            node_outputs={},
        )

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.SUSPENDED

    async def test_reentry_pure_deadlock_after_cancelled_dep_fails(self, engine, engine_project):
        """Test 5（重建路径死锁兜底）：续跑入口重建后，节点 X 前置依赖 CANCELLED（非终态
        解析集合、非 waiting/running）→ 纯死锁 → execution FAILED 且 error_message 末行
        reason==deadlock（而非静默挂死）。"""
        from asgiref.sync import sync_to_async

        execution, dep_ne_id, _x_id = await sync_to_async(_build_cancelled_dep_execution)(
            engine_project
        )
        dep_ne = await NodeExecution.objects.select_related("node").aget(id=dep_ne_id)

        # 续跑入口重建（execution 处 SUSPENDED → 抢锁成功 → 重入暴露纯死锁）
        await engine._continue_after_node(execution, dep_ne)

        await execution.arefresh_from_db()
        assert execution.status == ExecutionStatus.FAILED
        last_line = execution.error_message.strip().splitlines()[-1]
        payload = json.loads(last_line)
        assert payload["reason"] == "deadlock"


def _build_cancelled_dep_execution(engine_project):
    """构造 NodeDep → NodeX 工作流，execution SUSPENDED；NodeDep NE CANCELLED、NodeX NE PENDING。

    重入续跑后 X 的唯一前置 CANCELLED（不可解析、非 waiting/running）→ 纯死锁兜底。
    """
    from workflows.models import NodeExecution, NodeExecutionStatus

    workflow = Workflow.objects.create(
        name="Cancelled Dep Workflow",
        space=engine_project,
        trigger_type="manual",
    )
    node_dep = WorkflowNode.objects.create(
        workflow=workflow, node_type="condition", name="NodeDep", position_x=0, position_y=0
    )
    node_x = WorkflowNode.objects.create(
        workflow=workflow, node_type="condition", name="NodeX", position_x=200, position_y=0
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_dep,
        target_node=node_x,
        source_handle="default",
        target_handle="default",
    )
    execution = WorkflowExecution.objects.create(
        workflow=workflow,
        space=engine_project,
        trigger_type="manual",
        status=ExecutionStatus.SUSPENDED,
    )
    dep_ne = NodeExecution.objects.create(
        workflow_execution=execution,
        node=node_dep,
        status=NodeExecutionStatus.CANCELLED,
    )
    NodeExecution.objects.create(
        workflow_execution=execution,
        node=node_x,
        status=NodeExecutionStatus.PENDING,
    )
    return execution, dep_ne.id, str(node_x.id)
