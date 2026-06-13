"""DAGNode 入边明细测试（Phase 18 ENG-02，Task 1）。

``TestDagIncomingEdges``：经 ORM 构建 DAG 后入边明细 incoming_edges 的收集
正确性（django_db，参照 test_dag.py 建工作流）。

routing.py 纯函数零 DB 单测在 Task 2 追加到本文件。
"""

import pytest

from projects.models import Project
from workflows.engine.dag import DAG, DAGNode
from workflows.models import Workflow, WorkflowEdge, WorkflowNode


@pytest.mark.django_db
class TestDagIncomingEdges:
    """经 DAG.from_workflow 构建后入边明细收集正确性。"""

    def _make_workflow(self):
        return Workflow.objects.create(
            name="Incoming Edges Workflow",
            project=Project.objects.create(name="Routing Test Project"),
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
