"""NodePort 能力契约字段（shape）单测（SLOT-01，Phase 92 Wave 1）。

纯函数 / 零 DB：仅断言 dataclass 字段默认值、get_schema() 输出键与
KNOWN_PORT_SHAPES 常量集合成员，不使用任何数据库 fixture。

覆盖：
- NodePort.shape 默认空字符串（既有数十处构造零破坏）+ 可赋值。
- get_schema() inputs/outputs 项均含 "shape" 键（默认 ""）。
- KNOWN_PORT_SHAPES 收全 7 个能力契约取值（frozenset，可扩展）。
- GET /api/node-types/ 端到端回传 shape，DRF NodePortSerializer 不再剥离（SLOT-03，Phase 93 Wave 1）。
"""

import pytest
from rest_framework import status
from rest_framework.reverse import reverse

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


class TestDeprecatedNodeRegistration:
    """UNIFY-02：ai_plan_generation 标 deprecated 但保留注册（既有实例向后兼容）。"""

    def test_ai_plan_generation_still_registered_and_deprecated(self):
        """ai_plan_generation 仍经 @register_node 注册，且 deprecated ClassVar 为 True。"""
        node_class = NodeRegistry.get("ai_plan_generation")
        assert node_class is not None, (
            "ai_plan_generation 必须仍注册（既有实例运行依赖 registry 查找）"
        )
        assert node_class.deprecated is True

    def test_ai_plan_research_not_deprecated(self):
        """对照：统一编排入口 ai_plan_research 未被误标 deprecated。"""
        node_class = NodeRegistry.get("ai_plan_research")
        assert node_class is not None
        assert node_class.deprecated is False


def _find_port(ports: list[dict], name: str) -> dict | None:
    """从端口项列表按 name 取出端口 dict（不存在返回 None）。"""
    for item in ports:
        if item.get("name") == name:
            return item
    return None


@pytest.mark.django_db
class TestNodeTypesApiExposesShape:
    """GET /api/node-types/ 端到端暴露端口 shape（DRF 不剥离，BLOCKER 闭合）。

    走真实 DRF APIClient 命中 node-type-list，断言 shape 经序列化器透传——
    补 NodePortSerializer.shape 字段前这些断言会失败（证明真修 BLOCKER 而非掩盖）。
    """

    def _node_types_by_type(self, authenticated_admin_client) -> dict[str, dict]:
        url = reverse("node-type-list")
        response = authenticated_admin_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        # NodeTypeViewSet 直接返回 list（无分页）；防御性兼容 results 包裹。
        payload = response.data
        if isinstance(payload, dict) and "results" in payload:
            payload = payload["results"]
        return {n["node_type"]: n for n in payload}

    def test_ai_plan_research_clarify_port_exposes_shape(self, authenticated_admin_client):
        """ai_plan_research 的 clarify 端口经 API 回传 shape=clarification_request（非空、非剥离）。"""
        by_type = self._node_types_by_type(authenticated_admin_client)
        assert "ai_plan_research" in by_type, "ai_plan_research 应在 /node-types/ 中"
        node = by_type["ai_plan_research"]
        # clarify 为 output 端口（凹槽，需澄清时吐出澄清请求）。
        clarify = _find_port(node["outputs"], "clarify")
        assert clarify is not None, "ai_plan_research 应有 clarify 输出端口"
        assert "shape" in clarify, "DRF 不应剥离 shape 字段"
        assert clarify["shape"] == "clarification_request"

    def test_clarification_card_input_exposes_shape(self, authenticated_admin_client):
        """clarification_card 的 clarification_request 输入端口经 API 回传 shape=clarification_request。"""
        by_type = self._node_types_by_type(authenticated_admin_client)
        assert "clarification_card" in by_type, "clarification_card 应在 /node-types/ 中"
        node = by_type["clarification_card"]
        port = _find_port(node["inputs"], "clarification_request")
        assert port is not None, "clarification_card 应有 clarification_request 输入端口"
        assert port["shape"] == "clarification_request"

    def test_generic_port_shape_is_empty_string(self, authenticated_admin_client):
        """通用 default 端口经 API 回传 shape=''（零回归：空契约通配）。"""
        by_type = self._node_types_by_type(authenticated_admin_client)
        node = by_type["ai_plan_research"]
        default = _find_port(node["outputs"], "default")
        assert default is not None, "ai_plan_research 应有 default 输出端口"
        assert "shape" in default, "DRF 不应剥离 shape 字段"
        assert default["shape"] == ""
