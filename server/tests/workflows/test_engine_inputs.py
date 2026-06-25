"""输入归集测试（Phase 18 ENG-05）。

- ``TestCollectInputsUnit``：零 DB 纯函数单测（18-01 产出），复用
  test_engine_routing.py 的 _build_dag helper，按 RESEARCH Pattern 5 归集。
- ``TestTargetHandleIntegration``：经真实调度（run_sync）的 target_handle 端到端
  集成测试（18-02 产出），锁定"端口键整包 + 扁平保底并存"在运行时闭环。
"""

import pytest
from asgiref.sync import sync_to_async

from tests.workflows.conftest import BranchNode
from tests.workflows.test_engine_routing import _build_dag
from workflows.engine.routing import collect_inputs
from workflows.models import (
    ExecutionStatus,
    NodeExecution,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)


class TestCollectInputsUnit:
    """target_handle 归集规则：扁平保底 + 同名键不覆盖 + 端口键补齐。"""

    def test_flat_merge_when_default_handle(self):
        """I1：无 target_handle（"default"）的边 → 逐上游 update 扁平合并（现状语义）。"""
        dag = _build_dag(
            [
                ("a", "T", "default", "default"),
                ("b", "T", "default", "default"),
            ]
        )
        node_outputs = {"a": {"x": 1}, "b": {"y": 2}}
        inputs = collect_inputs(dag, "T", node_outputs)
        assert inputs == {"x": 1, "y": 2}

    def test_plan_chain_no_double_nesting(self):
        """I2：plan_generation→ai_coding 真实形状——同名键不覆盖，inputs["plan"] 仍是方案对象。

        characterization：plan_generation.map_output 输出顶层含 "plan" 键
        （plan_generation.py:329-352）；ai_coding 读 get_input("plan") 期望方案对象本身
        （coding.py:706-712）。边 target_handle="plan" 时不得变成 {"plan": {"plan": ...}}。
        """
        plan_object = {"summary": "实现 X 功能", "tasks": [{"id": 1, "title": "建模"}]}
        node_outputs = {
            "plan_gen": {
                "plan": plan_object,
                "final_answer": "方案已生成",
                "usage": {"input_tokens": 100},
            }
        }
        dag = _build_dag([("plan_gen", "coding", "default", "plan")])
        inputs = collect_inputs(dag, "coding", node_outputs)

        # 同名键不覆盖：inputs["plan"] 是方案对象本身，绝非双层嵌套
        assert inputs["plan"] is plan_object
        assert inputs["plan"] == plan_object
        assert "plan" not in inputs["plan"]

    def test_coding_result_chain_hits_port_key(self):
        """I3：ai_coding→ai_code_review——上游顶层无 "coding_result"，端口键补齐为完整输出。

        characterization：ai_coding 输出顶层无 "coding_result" 键（coding.py:706-712）；
        ai_code_review 读 get_input("coding_result") 期望整个上游输出对象
        （code_review.py:308-322）。
        """
        coding_output = {
            "merge_requests": [{"repo": "svc", "mr_url": "http://x/1"}],
            "session_ids": ["s1"],
        }
        node_outputs = {"coding": coding_output}
        dag = _build_dag([("coding", "review", "default", "coding_result")])
        inputs = collect_inputs(dag, "review", node_outputs)

        assert inputs["coding_result"] == coding_output
        # 扁平保底键仍在（兜底兼容分支可用）
        assert inputs["merge_requests"] == coding_output["merge_requests"]

    def test_multi_upstream_deterministic_by_source_id(self):
        """I4：两上游同名扁平键 → 按 source_id 字符串排序处理，重复调用稳定。"""
        dag = _build_dag(
            [
                ("a", "T", "default", "default"),
                ("b", "T", "default", "default"),
            ]
        )
        node_outputs = {"a": {"k": "from_a"}, "b": {"k": "from_b"}}
        first = collect_inputs(dag, "T", node_outputs)
        second = collect_inputs(dag, "T", node_outputs)
        # 排序后 "b" 最后处理胜出，结果稳定
        assert first == {"k": "from_b"}
        assert first == second

    def test_unknown_node_returns_empty(self):
        dag = _build_dag([("a", "T", "default", "default")])
        assert collect_inputs(dag, "missing", {"a": {"x": 1}}) == {}


# ============================================================================
# 集成测试：target_handle 经真实调度端到端归集（django_db + run_sync，ENG-05）
# ============================================================================


def _build_target_handle_workflow(project, target_handle: str) -> Workflow:
    """手建 trigger → Source(test_branch) → Sink(test_echo_inputs)，Source→Sink 边带定制 target_handle。

    Source 用 test_branch（输出 {"branch": "true"}、next_handle="true"），Source→Sink 边
    source_handle="true" 保证被选中；target_handle 由参数注入。定制 target_handle 边仅
    本测试用，故工作流就地手建（不进 conftest）。
    """
    workflow = Workflow.objects.create(
        name=f"TargetHandle Workflow ({target_handle})",
        space=project,
        trigger_type="manual",
    )
    trigger = WorkflowNode.objects.create(
        workflow=workflow, node_type="manual_trigger", name="Start", position_x=0, position_y=0
    )
    node_a = WorkflowNode.objects.create(
        workflow=workflow, node_type="test_branch", name="Source", position_x=200, position_y=0
    )
    node_b = WorkflowNode.objects.create(
        workflow=workflow, node_type="test_echo_inputs", name="Sink", position_x=400, position_y=0
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=trigger,
        target_node=node_a,
        source_handle="default",
        target_handle="default",
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_a,
        target_node=node_b,
        source_handle="true",
        target_handle=target_handle,
    )
    return workflow


async def _echoed_inputs(execution, name: str) -> dict:
    """取指定节点回显的归集输入（NodeExecution.output_data["echoed_inputs"]）。"""
    ne = await NodeExecution.objects.filter(workflow_execution=execution, node__name=name).afirst()
    assert ne is not None, f"节点 {name} 无执行记录"
    return (ne.output_data or {}).get("echoed_inputs", {})


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestTargetHandleIntegration:
    """target_handle 经真实调度端到端：端口键整包 + 扁平保底并存（ENG-05 运行时落点）。"""

    async def test_port_key_holds_full_upstream_output(
        self, engine, engine_test_nodes, engine_project
    ):
        """Test 1：target_handle="custom_port" → Sink.echoed_inputs["custom_port"] 为 Source 完整输出 dict。"""
        BranchNode._next_handle = "true"
        workflow = await sync_to_async(_build_target_handle_workflow)(engine_project, "custom_port")
        execution = await engine.start_execution(workflow, run_sync=True)

        assert execution.status == ExecutionStatus.COMPLETED
        echoed = await _echoed_inputs(execution, "Sink")
        # 端口键为上游完整输出 dict（整包语义），非单字段
        assert echoed["custom_port"] == {"branch": "true"}

    async def test_flat_key_coexists_with_port_key(self, engine, engine_test_nodes, engine_project):
        """Test 2：同一执行中扁平键 "branch"（现状保底）与端口键并存。"""
        BranchNode._next_handle = "true"
        workflow = await sync_to_async(_build_target_handle_workflow)(engine_project, "custom_port")
        execution = await engine.start_execution(workflow, run_sync=True)

        assert execution.status == ExecutionStatus.COMPLETED
        echoed = await _echoed_inputs(execution, "Sink")
        assert echoed["branch"] == "true"
        assert "custom_port" in echoed

    async def test_default_handle_no_port_key(self, engine, engine_test_nodes, engine_project):
        """Test 3：target_handle="default" → 仅扁平键，无 "default" 端口键。"""
        BranchNode._next_handle = "true"
        workflow = await sync_to_async(_build_target_handle_workflow)(engine_project, "default")
        execution = await engine.start_execution(workflow, run_sync=True)

        assert execution.status == ExecutionStatus.COMPLETED
        echoed = await _echoed_inputs(execution, "Sink")
        assert echoed["branch"] == "true"
        assert "default" not in echoed
