"""死锁诊断纯函数测试（Phase 18 ENG-04，Task 3）。

零 DB：复用 test_engine_routing.py 的 _build_dag helper 手工构造 DAG。
diagnose_deadlock 只含拓扑元数据（名称/short_id/状态/handle），绝不读取节点输出值
（V5 信息泄露防线，T-18-01）。
"""

import json

from tests.workflows.test_engine_routing import _build_dag
from workflows.engine.routing import (
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_WAITING,
    RoutingState,
    diagnose_deadlock,
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
