"""输入归集纯函数测试（Phase 18 ENG-05，Task 3）。

零 DB：复用 test_engine_routing.py 的 _build_dag helper。collect_inputs 按 RESEARCH
Pattern 5 非破坏性叠加规则归集，I2/I3 为两条真实节点链 characterization。
"""

from tests.workflows.test_engine_routing import _build_dag
from workflows.engine.routing import collect_inputs


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
