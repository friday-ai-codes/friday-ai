"""Condition node for branching."""
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
class ConditionNode(BaseNode):
 """条件分支节点
 根据条件表达式决定走哪个分支。
 """
 node_type = "condition"
 display_name = "条件分支"
 description = "根据条件判断走不同的分支"
 icon = "git-branch"
 category = NodeCategory.CONTROL
 execution_mode = "server_local"
 config_schema = {
 "type": "object",
 "properties": {
 "conditions": {
 "type": "array",
 "title": "条件列表",
 "items": {
 "type": "object",
 "properties": {
 "name": {
 "type": "string",
 "title": "分支名称",
 },
 "expression": {
 "type": "object",
 "title": "条件表达式",
 "properties": {
 "field": {"type": "string"},
 "operator": {
 "type": "string",
 "enum": [
 "eq",
 "ne",
 "gt",
 "gte",
 "lt",
 "lte",
 "contains",
 "not_contains",
 "starts_with",
 "ends_with",
 "is_empty",
 "is_not_empty",
 "is_true",
 "is_false",
 ],
 },
 "value": {},
 },
 },
 },
 },
 "default":,
 },
 "default_branch": {
 "type": "string",
 "title": "默认分支",
 "description": "当所有条件都不满足时走的分支",
 "default": "else",
 },
 },
 }
 inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
 outputs = # 动态输出，根据条件数量决定
 @classmethod
 def get_dynamic_outputs(cls, config: dict) -> list[NodePort]:
 """根据配置动态生成输出端口"""
 outputs =
 for i, condition in enumerate(config.get("conditions", )):
 outputs.append(
 NodePort(
 name=f"branch_{i}",
 label=condition.get("name", f"分支 {i + 1}"),
 port_type=PortType.OBJECT,
 )
 )
 outputs.append(
 NodePort(
 name=config.get("default_branch", "else"),
 label="默认",
 port_type=PortType.OBJECT,
 )
 )
 return outputs
 async def execute(self, context: ExecutionContext) -> NodeResult:
 config = context.node_config
 conditions = config.get("conditions", )
 input_data = context.input_data
 # 评估每个条件
 for i, condition in enumerate(conditions):
 if self._evaluate_condition(condition.get("expression", {}), input_data):
 return NodeResult(
 status="completed",
 output=input_data,
 next_handle=f"branch_{i}",
 )
 # 走默认分支
 return NodeResult(
 status="completed",
 output=input_data,
 next_handle=config.get("default_branch", "else"),
 )
 def _evaluate_condition(self, expression: dict, data: dict) -> bool:
 """评估条件表达式"""
 field = expression.get("field", "")
 operator = expression.get("operator", "eq")
 expected = expression.get("value")
 # 获取字段值（支持嵌套路径）
 actual = self._get_nested_value(data, field)
 # 评估
 if operator == "eq":
 return actual == expected
 elif operator == "ne":
 return actual != expected
 elif operator == "gt":
 return actual > expected
 elif operator == "gte":
 return actual >= expected
 elif operator == "lt":
 return actual < expected
 elif operator == "lte":
 return actual <= expected
 elif operator == "contains":
 return expected in str(actual)
 elif operator == "not_contains":
 return expected not in str(actual)
 elif operator == "starts_with":
 return str(actual).startswith(str(expected))
 elif operator == "ends_with":
 return str(actual).endswith(str(expected))
 elif operator == "is_empty":
 return not actual
 elif operator == "is_not_empty":
 return bool(actual)
 elif operator == "is_true":
 return actual is True
 elif operator == "is_false":
 return actual is False
 return False
 def _get_nested_value(self, data: dict, path: str):
 """获取嵌套字段值"""
 keys = path.split(".")
 value = data
 for key in keys:
 if isinstance(value, dict):
 value = value.get(key)
 else:
 return None
 return value
