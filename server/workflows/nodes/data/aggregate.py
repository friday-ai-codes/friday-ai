"""Data aggregation nodes: VariableAggregate."""

from typing import Any

from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node


@register_node
class VariableAggregateNode(BaseNode):
    """变量聚合节点

    将多个上游节点的输出绑定为结构化变量，支持字段提取和冲突覆盖。
    不引入同步语义，仅做数据重组。
    """

    node_type = "aggregate"
    display_name = "变量聚合"
    description = "将多个上游节点输出绑定为结构化变量"
    icon = "combine"
    category = NodeCategory.CONTROL
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "mappings": {
                "type": "array",
                "title": "聚合映射",
                "description": "从上游节点到目标键的映射配置",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_node": {
                            "type": "string",
                            "title": "来源节点",
                            "description": "上游节点 ID",
                        },
                        "output_field": {
                            "type": "string",
                            "title": "输出字段",
                            "description": "要提取的字段名，为空则取整个输出对象",
                            "default": "",
                        },
                        "target_key": {
                            "type": "string",
                            "title": "目标键名",
                            "description": "聚合结果中的键名",
                        },
                    },
                    "required": ["source_node", "target_key"],
                },
            },
        },
        "required": ["mappings"],
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT, required=False)]
    outputs = [NodePort(name="default", label="输出", port_type=PortType.OBJECT)]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """执行变量聚合。

        从 previous_outputs 中按 mappings 配置提取数据，
        采用浅合并策略，字段冲突时后覆盖先。

        Args:
            context: 执行上下文

        Returns:
            NodeResult: 聚合后的结构化输出
        """
        config = context.node_config
        mappings = config.get("mappings", [])
        previous_outputs = context.previous_outputs

        output: dict[str, Any] = {}

        for mapping in mappings:
            source_node = mapping.get("source_node", "")
            output_field = mapping.get("output_field", "")
            target_key = mapping.get("target_key", "")

            if not source_node or not target_key:
                continue

            source_output = previous_outputs.get(source_node, {})

            if output_field:
                # 提取指定字段
                output[target_key] = source_output.get(output_field)
            else:
                # 取整个上游输出对象
                output[target_key] = source_output

        return NodeResult(status="completed", output=output)
