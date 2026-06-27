"""NodePort 能力契约字段（shape）单测（SLOT-01，Phase 92 Wave 1）。

纯函数 / 零 DB：仅断言 dataclass 字段默认值、get_schema() 输出键与
KNOWN_PORT_SHAPES 常量集合成员，不使用任何数据库 fixture。

覆盖：
- NodePort.shape 默认空字符串（既有数十处构造零破坏）+ 可赋值。
- get_schema() inputs/outputs 项均含 "shape" 键（默认 ""）。
- KNOWN_PORT_SHAPES 收全 7 个能力契约取值（frozenset，可扩展）。
"""

from workflows.nodes.base import NodePort
from workflows.nodes.registry import NodeRegistry
from workflows.nodes.shapes import KNOWN_PORT_SHAPES


class TestNodePortShapeField:
    """NodePort.shape 契约字段基本契约。"""

    def test_default_shape_is_empty_string(self):
        """不传 shape 仍可构造，shape == ""（既有构造零破坏，向后兼容通配）。"""
        port = NodePort(name="x", label="y")
        assert port.shape == ""

    def test_shape_can_be_assigned(self):
        """显式赋 shape 取值生效。"""
        port = NodePort(name="x", label="y", shape="clarification_request")
        assert port.shape == "clarification_request"


class TestGetSchemaShapeKey:
    """get_schema() inputs/outputs 输出 shape 键（前端可从 /api/node-types/ 读到）。"""

    def test_input_output_items_contain_shape_key(self):
        """任一稳定已注册节点 get_schema() 的 inputs[0]/outputs[0] 均含 shape 键。"""
        node_class = NodeRegistry.get("ai_plan_research")
        assert node_class is not None
        schema = node_class.get_schema()
        assert schema["inputs"], "ai_plan_research 应有输入端口"
        assert schema["outputs"], "ai_plan_research 应有输出端口"
        for item in schema["inputs"]:
            assert "shape" in item
        for item in schema["outputs"]:
            assert "shape" in item


class TestKnownPortShapes:
    """KNOWN_PORT_SHAPES 能力契约常量集合。"""

    def test_contains_seven_capability_shapes(self):
        """收全 7 个能力契约取值（frozenset，可扩展）。"""
        assert isinstance(KNOWN_PORT_SHAPES, frozenset)
        assert {
            "clarification_request",
            "clarification_answer",
            "feishu_message",
            "technical_plan",
            "coding_assignment",
            "feishu_document",
            "approval_result",
        } <= KNOWN_PORT_SHAPES
