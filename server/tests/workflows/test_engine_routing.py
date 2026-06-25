"""路由核心测试（Phase 18 ENG-02）。

包含两部分：
- ``TestDagIncomingEdges``：经 ORM 构建 DAG 后入边明细 incoming_edges 的收集
  正确性（django_db，参照 test_dag.py 建工作流）。
- ``TestEvaluateNodeReadiness`` / ``TestSelectSuccessors`` / ``TestComputeSkippable``：
  routing.py 纯函数零 DB 单测，手工构造 DAG，不标 django_db。

模块级 helper ``_build_dag`` 供 test_engine_deadlock.py / test_engine_inputs.py 复用
（本地 import，不进 conftest——conftest 工厂归 18-02）。
"""

import pytest

from projects.models import Space
from tests.workflows.conftest import BranchNode
from workflows.engine.dag import DAG, DAGNode
from workflows.engine.routing import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SKIPPED,
    STATUS_TOLERATED,
    STATUS_WAITING,
    RoutingState,
    compute_skippable,
    evaluate_node_readiness,
    select_successors,
)
from workflows.models import (
    ExecutionStatus,
    NodeExecution,
    NodeExecutionStatus,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)

# ============================================================================
# Task 1: DAGNode.incoming_edges（django_db）
# ============================================================================


@pytest.mark.django_db
class TestDagIncomingEdges:
    """经 DAG.from_workflow 构建后入边明细收集正确性。"""

    def _make_workflow(self):
        return Workflow.objects.create(
            name="Incoming Edges Workflow",
            space=Space.objects.create(name="Routing Test Space"),
            trigger_type="manual",
        )

    def test_incoming_edges_triple_matches_incoming_set(self):
        """incoming_edges 含 (source_id, source_handle, target_handle) 且与 incoming 一一对应。"""
        workflow = self._make_workflow()
        node_a = WorkflowNode.objects.create(
            workflow=workflow, node_type="manual_trigger", name="A", position_x=0, position_y=0
        )
        node_b = WorkflowNode.objects.create(
            workflow=workflow, node_type="condition", name="B", position_x=200, position_y=0
        )
        WorkflowEdge.objects.create(
            workflow=workflow,
            source_node=node_a,
            target_node=node_b,
            source_handle="true",
            target_handle="plan",
        )

        dag = DAG.from_workflow(workflow)
        b = dag.nodes[str(node_b.id)]

        assert b.incoming_edges == [(str(node_a.id), "true", "plan")]
        # source_id 为 str(UUID)，与 incoming 集合成员一一对应
        assert {e[0] for e in b.incoming_edges} == b.incoming
        assert all(isinstance(e[0], str) for e in b.incoming_edges)

    def test_multiple_handles_each_independent_no_dedup(self):
        """同一对节点间多条不同 handle 的边各自独立成元组（不去重）。"""
        workflow = self._make_workflow()
        node_a = WorkflowNode.objects.create(
            workflow=workflow, node_type="condition", name="A", position_x=0, position_y=0
        )
        node_b = WorkflowNode.objects.create(
            workflow=workflow, node_type="http_request", name="B", position_x=200, position_y=0
        )
        WorkflowEdge.objects.create(
            workflow=workflow,
            source_node=node_a,
            target_node=node_b,
            source_handle="true",
            target_handle="default",
        )
        WorkflowEdge.objects.create(
            workflow=workflow,
            source_node=node_a,
            target_node=node_b,
            source_handle="false",
            target_handle="default",
        )

        dag = DAG.from_workflow(workflow)
        b = dag.nodes[str(node_b.id)]

        assert len(b.incoming_edges) == 2
        handles = sorted(e[1] for e in b.incoming_edges)
        assert handles == ["false", "true"]
        # 去重后 incoming 集合只有一个源
        assert b.incoming == {str(node_a.id)}

    def test_manual_dag_default_empty_list(self):
        """手工构造 DAG（不经 ORM）时 incoming_edges 默认空 list，旧调用零回退。"""
        dag = DAG()
        dag.nodes["n1"] = DAGNode(node=object())
        assert dag.nodes["n1"].incoming_edges == []


# ============================================================================
# 纯函数零 DB 测试辅助
# ============================================================================


class _StubNode:
    """轻量节点 stub（仅 routing 纯函数需要的 id/short_id/name）。"""

    def __init__(self, node_id: str, name: str | None = None, short_id: str | None = None):
        self.id = node_id
        self.name = name or f"node-{node_id}"
        self.short_id = short_id or node_id


def _build_dag(edges: list[tuple], extra_nodes: list[str] | None = None) -> DAG:
    """从 (source_id, target_id, source_handle, target_handle) 边列表手工构造 DAG。

    供 routing/deadlock/inputs 三个测试文件复用（本地 import，不进 conftest——
    conftest 工厂归 18-02）。
    """
    dag = DAG()
    # 保持插入顺序（源先于目标、入口节点最先）——_detect_back_edges 的 DFS 起点
    # 依赖节点字典顺序，无序集合会让反馈环识别变得不确定。
    node_ids: dict[str, None] = {nid: None for nid in (extra_nodes or [])}
    for src, tgt, *_ in edges:
        node_ids.setdefault(src, None)
        node_ids.setdefault(tgt, None)
    for nid in node_ids:
        dag.nodes[nid] = DAGNode(node=_StubNode(nid))
    for src, tgt, source_handle, target_handle in edges:
        dag.nodes[tgt].incoming.add(src)
        dag.nodes[tgt].incoming_edges.append((src, source_handle, target_handle))
        dag.nodes[src].outgoing.setdefault(source_handle, set()).add(tgt)
    dag._detect_back_edges()
    return dag


# ============================================================================
# Task 2: evaluate_node_readiness（纯函数，零 DB）
# ============================================================================


class TestEvaluateNodeReadiness:
    """边感知就绪判定四枚举：ready / skip_failed / skip_unselected / blocked。"""

    def test_branch_selected_and_unselected(self):
        """Test 1：条件节点 completed 且 handle="true" → true 支 ready、false 支 skip_unselected。"""
        dag = _build_dag(
            [
                ("A", "Bt", "true", "default"),
                ("A", "Cf", "false", "default"),
            ]
        )
        state = RoutingState(statuses={"A": STATUS_COMPLETED}, handles={"A": "true"})
        assert evaluate_node_readiness(dag, "Bt", state) == "ready"
        assert evaluate_node_readiness(dag, "Cf", state) == "skip_unselected"

    def test_default_fallback_selected(self):
        """Test 2：源 next_handle="success" 但只有 default 出边 → default 边视为选中，后继 ready。"""
        dag = _build_dag([("A", "B", "default", "default")])
        state = RoutingState(statuses={"A": STATUS_COMPLETED}, handles={"A": "success"})
        assert evaluate_node_readiness(dag, "B", state) == "ready"

    def test_diamond_join_one_alive_one_skipped_ready(self):
        """Test 3：菱形汇合 B completed、C skipped → D ready（CONTEXT：一条活路即执行）。"""
        dag = _build_dag(
            [
                ("A", "B", "true", "default"),
                ("A", "C", "false", "default"),
                ("B", "D", "default", "default"),
                ("C", "D", "default", "default"),
            ]
        )
        state = RoutingState(
            statuses={
                "A": STATUS_COMPLETED,
                "B": STATUS_COMPLETED,
                "C": STATUS_SKIPPED,
            },
            handles={"A": "true"},
        )
        assert evaluate_node_readiness(dag, "D", state) == "ready"

    def test_diamond_join_both_skipped_skip_unselected(self):
        """Test 4：双支全 skip → D skip_unselected。"""
        dag = _build_dag(
            [
                ("B", "D", "default", "default"),
                ("C", "D", "default", "default"),
            ]
        )
        state = RoutingState(statuses={"B": STATUS_SKIPPED, "C": STATUS_SKIPPED}, handles={})
        assert evaluate_node_readiness(dag, "D", state) == "skip_unselected"

    def test_predecessor_failed_skip_failed(self):
        """Test 5：任一 forward 依赖 failed（非 tolerated）→ skip_failed（保留 ANY 语义）。"""
        dag = _build_dag(
            [
                ("A", "C", "default", "default"),
                ("B", "C", "default", "default"),
            ]
        )
        state = RoutingState(statuses={"A": STATUS_COMPLETED, "B": STATUS_FAILED}, handles={})
        assert evaluate_node_readiness(dag, "C", state) == "skip_failed"

    def test_tolerated_is_resolved_and_selected(self):
        """Test 6：依赖 tolerated → 边已解析、按 default 选中，后继可 ready。"""
        dag = _build_dag([("A", "B", "default", "default")])
        state = RoutingState(statuses={"A": STATUS_TOLERATED}, handles={})
        assert evaluate_node_readiness(dag, "B", state) == "ready"

    def test_back_edge_does_not_block(self):
        """Test 7：含反馈环（非 default handle 指向祖先）节点仅按 forward 入边判定。"""
        # A -> B (default), B -> A (false, 指向 DFS 祖先 A，被识别为 back-edge)
        dag = _build_dag(
            [
                ("A", "B", "default", "default"),
                ("B", "A", "false", "default"),
            ]
        )
        # B 是 A 的 back_edge_source —— A 应忽略该环边按入口节点 ready
        assert "B" in dag.nodes["A"].back_edge_sources
        state = RoutingState(statuses={}, handles={})
        assert evaluate_node_readiness(dag, "A", state) == "ready"

    def test_blocked_when_dependency_unresolved(self):
        """Test 8：任一 forward 入边源仍 pending/running/waiting → blocked。"""
        dag = _build_dag([("A", "B", "default", "default")])
        for status in (STATUS_PENDING, STATUS_RUNNING, STATUS_WAITING):
            state = RoutingState(statuses={"A": status}, handles={})
            assert evaluate_node_readiness(dag, "B", state) == "blocked"

    def test_entry_node_always_ready(self):
        """无 forward 入边的入口节点恒 ready。"""
        dag = _build_dag([("A", "B", "default", "default")])
        state = RoutingState(statuses={}, handles={})
        assert evaluate_node_readiness(dag, "A", state) == "ready"

    def test_return_value_is_one_of_four_enum(self):
        """四值枚举闭集断言（覆盖 ready/skip_failed/skip_unselected/blocked）。"""
        seen = set()
        # ready
        d1 = _build_dag([("A", "B", "default", "default")])
        seen.add(evaluate_node_readiness(d1, "A", RoutingState()))
        seen.add(evaluate_node_readiness(d1, "B", RoutingState(statuses={"A": STATUS_COMPLETED})))
        # blocked
        seen.add(evaluate_node_readiness(d1, "B", RoutingState(statuses={"A": STATUS_PENDING})))
        # skip_failed
        seen.add(evaluate_node_readiness(d1, "B", RoutingState(statuses={"A": STATUS_FAILED})))
        # skip_unselected
        seen.add(evaluate_node_readiness(d1, "B", RoutingState(statuses={"A": STATUS_SKIPPED})))
        assert seen == {"ready", "blocked", "skip_failed", "skip_unselected"}


class TestSelectSuccessors:
    """select_successors：handle 命中 + default 回退（与 scheduler.py:1411-1420 等价）。"""

    def test_handle_hit_returns_bucket(self):
        dag = _build_dag(
            [
                ("A", "Bt", "true", "default"),
                ("A", "Cf", "false", "default"),
            ]
        )
        succ = select_successors(dag, "A", "true")
        assert [s.id for s in succ] == ["Bt"]

    def test_fallback_to_default_when_handle_missing(self):
        """未命中且 handle != "default" → 回退 default 桶。"""
        dag = _build_dag([("A", "B", "default", "default")])
        succ = select_successors(dag, "A", "success")
        assert [s.id for s in succ] == ["B"]

    def test_no_fallback_when_handle_is_default(self):
        """handle == "default" 未命中则不回退（无歧义）。"""
        dag = _build_dag([("A", "Bt", "true", "default")])
        assert select_successors(dag, "A", "default") == []


class TestComputeSkippable:
    """compute_skippable：fixpoint 级联标记，不修改入参 state。"""

    def test_chain_cascade_fixpoint(self):
        """链式下游 fixpoint 全部标记 skip_unselected。"""
        dag = _build_dag(
            [
                ("A", "B", "true", "default"),
                ("A", "C", "false", "default"),
                ("C", "D", "default", "default"),
                ("D", "E", "default", "default"),
            ]
        )
        state = RoutingState(statuses={"A": STATUS_COMPLETED}, handles={"A": "true"})
        pending = {"B", "C", "D", "E"}
        result = compute_skippable(dag, state, pending)
        # B 选中（true 支）不 skip；C/D/E 级联 skip
        assert set(result) == {"C", "D", "E"}
        assert all(reason == "skip_unselected" for reason in result.values())

    def test_does_not_mutate_input_state(self):
        dag = _build_dag(
            [
                ("A", "B", "true", "default"),
                ("A", "C", "false", "default"),
            ]
        )
        statuses = {"A": STATUS_COMPLETED}
        state = RoutingState(statuses=statuses, handles={"A": "true"})
        compute_skippable(dag, state, {"B", "C"})
        assert statuses == {"A": STATUS_COMPLETED}
        assert state.statuses == {"A": STATUS_COMPLETED}

    def test_failed_predecessor_records_skip_failed(self):
        dag = _build_dag([("A", "B", "default", "default")])
        state = RoutingState(statuses={"A": STATUS_FAILED}, handles={})
        result = compute_skippable(dag, state, {"B"})
        assert result == {"B": "skip_failed"}


# ============================================================================
# 集成测试：主循环按 routing 纯函数真路由（django_db + run_sync）
# ============================================================================


async def _ne_status(execution, name: str):
    """按 node__name 查询 NodeExecution 状态（不存在返回 None）。"""
    ne = await NodeExecution.objects.filter(workflow_execution=execution, node__name=name).afirst()
    return ne.status if ne else None


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestBranchRoutingIntegration:
    """条件分支主循环真路由 + 未选中支级联 skipped + 完成判定（消费 conftest 夹具）。"""

    async def test_true_branch_selected_false_skipped(
        self, engine, engine_test_nodes, branch_workflow
    ):
        """Test 1：_next_handle="true" → TrueSide COMPLETED、FalseSide SKIPPED、Join COMPLETED。"""
        BranchNode._next_handle = "true"
        execution = await engine.start_execution(branch_workflow, run_sync=True)

        assert execution.status == ExecutionStatus.COMPLETED
        assert await _ne_status(execution, "Branch") == NodeExecutionStatus.COMPLETED
        assert await _ne_status(execution, "TrueSide") == NodeExecutionStatus.COMPLETED
        assert await _ne_status(execution, "FalseSide") == NodeExecutionStatus.SKIPPED
        # 菱形汇合一活一死照常执行
        assert await _ne_status(execution, "Join") == NodeExecutionStatus.COMPLETED

    async def test_false_branch_selected_true_skipped(
        self, engine, engine_test_nodes, branch_workflow
    ):
        """Test 2（对称）：_next_handle="false" → FalseSide COMPLETED、TrueSide SKIPPED、Join COMPLETED。"""
        BranchNode._next_handle = "false"
        execution = await engine.start_execution(branch_workflow, run_sync=True)

        assert execution.status == ExecutionStatus.COMPLETED
        assert await _ne_status(execution, "FalseSide") == NodeExecutionStatus.COMPLETED
        assert await _ne_status(execution, "TrueSide") == NodeExecutionStatus.SKIPPED
        assert await _ne_status(execution, "Join") == NodeExecutionStatus.COMPLETED

    async def test_skipped_counts_toward_completion_no_pending_residue(
        self, engine, engine_test_nodes, branch_workflow
    ):
        """Test 3：skipped 参与完成判定——执行 COMPLETED，全部 NE 终态（无 PENDING 残留）。"""
        BranchNode._next_handle = "true"
        execution = await engine.start_execution(branch_workflow, run_sync=True)

        assert execution.status == ExecutionStatus.COMPLETED
        terminal = {
            NodeExecutionStatus.COMPLETED,
            NodeExecutionStatus.SKIPPED,
            NodeExecutionStatus.FAILED,
        }
        statuses = [
            ne.status async for ne in NodeExecution.objects.filter(workflow_execution=execution)
        ]
        assert statuses, "应有节点执行记录"
        assert all(s in terminal for s in statuses), f"存在非终态 NE: {statuses}"
        assert NodeExecutionStatus.PENDING not in statuses

    async def test_no_matching_handle_cascades_all_skipped(
        self, engine, engine_test_nodes, branch_workflow
    ):
        """Test 4：无匹配 handle 且无 default 边 → 两支 + Join 全 SKIPPED，执行 COMPLETED（无死锁/无 running 残留）。"""
        BranchNode._next_handle = "nonexistent_handle"
        execution = await engine.start_execution(branch_workflow, run_sync=True)

        assert execution.status == ExecutionStatus.COMPLETED
        assert await _ne_status(execution, "Branch") == NodeExecutionStatus.COMPLETED
        assert await _ne_status(execution, "TrueSide") == NodeExecutionStatus.SKIPPED
        assert await _ne_status(execution, "FalseSide") == NodeExecutionStatus.SKIPPED
        assert await _ne_status(execution, "Join") == NodeExecutionStatus.SKIPPED
