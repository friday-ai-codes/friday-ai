"""条件表达式求值器
支持 AND/OR 组合逻辑和多种运算符。
条件表达式格式：
{
 "logic": "and", # "and" | "or"
 "conditions": [
 {"field": "status", "operator": "eq", "value": "approved"},
 {"field": "priority", "operator": "gte", "value": 3}
 ],
 "groups": [ # 嵌套条件组
 {"logic": "or", "conditions": [...]}
 ]
}
"""
import re
from typing import Any, Callable
import structlog
logger = structlog.get_logger
# 运算符定义
OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
 "eq": lambda a, b: a == b,
 "ne": lambda a, b: a != b,
 "gt": lambda a, b: float(a) > float(b) if _is_numeric(a, b) else str(a) > str(b),
 "gte": lambda a, b: float(a) >= float(b) if _is_numeric(a, b) else str(a) >= str(b),
 "lt": lambda a, b: float(a) < float(b) if _is_numeric(a, b) else str(a) < str(b),
 "lte": lambda a, b: float(a) <= float(b) if _is_numeric(a, b) else str(a) <= str(b),
 "contains": lambda a, b: str(b) in str(a),
 "not_contains": lambda a, b: str(b) not in str(a),
 "is_empty": lambda a, _: not a,
 "is_not_empty": lambda a, _: bool(a),
 "regex": lambda a, b: bool(re.search(str(b), str(a))),
}
def _is_numeric(a: Any, b: Any) -> bool:
 """检查两个值是否都可以转为数字"""
 try:
 float(a)
 float(b)
 return True
 except (ValueError, TypeError):
 return False
def _get_field_value(data: dict, field: str) -> Any:
 """从数据中获取字段值，支持点号分隔的嵌套路径"""
 if not field:
 return None
 parts = field.split(".")
 value: Any = data
 for part in parts:
 if isinstance(value, dict):
 value = value.get(part)
 elif isinstance(value, list) and part.isdigit:
 idx = int(part)
 value = value[idx] if 0 <= idx < len(value) else None
 else:
 return None
 if value is None:
 return None
 return value
def _evaluate_single_condition(condition: dict, data: dict) -> bool:
 """求值单个条件"""
 field = condition.get("field", "")
 operator = condition.get("operator", "eq")
 expected_value = condition.get("value")
 # 获取实际值
 actual_value = _get_field_value(data, field)
 # 获取运算符函数
 op_func = OPERATORS.get(operator)
 if not op_func:
 logger.warning("unknown_operator", operator=operator)
 return False
 try:
 result = op_func(actual_value, expected_value)
 logger.debug(
 "condition_evaluated",
 field=field,
 operator=operator,
 actual=actual_value,
 expected=expected_value,
 result=result,
 )
 return result
 except Exception as e:
 logger.warning("condition_evaluation_error", error=str(e), condition=condition)
 return False
def evaluate_condition(expression: dict, data: dict) -> bool:
 """求值条件表达式
 Args:
 expression: 条件表达式（包含 logic, conditions, groups）
 data: 要匹配的数据
 Returns:
 是否匹配
 """
 if not expression:
 return True # 空条件视为匹配
 logic = expression.get("logic", "and")
 conditions = expression.get("conditions", )
 groups = expression.get("groups", )
 # 收集所有结果
 results: list[bool] =
 # 求值直接条件
 for condition in conditions:
 results.append(_evaluate_single_condition(condition, data))
 # 求值嵌套组（递归）
 for group in groups:
 results.append(evaluate_condition(group, data))
 if not results:
 return True
 # 根据逻辑运算符组合结果
 if logic == "or":
 return any(results)
 else: # "and"
 return all(results)
