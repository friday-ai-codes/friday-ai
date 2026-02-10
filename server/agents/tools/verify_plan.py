"""verify_plan tool - validates technical plans against structure and quality rules.
Three-layer validation:
1. Structure validation (blocking errors)
2. Quality validation (warnings)
3. Semantic validation (reserved for future extension)
"""
from typing import Any
from agents.tools.base import ToolResult, tool
@tool(
 name="verify_plan",
 description="验证技术方案是否符合规范。返回结构化验证结果，包含错误（阻断）和警告（建议）。",
 category="GENERAL",
 parameters={
 "type": "object",
 "properties": {
 "plan": {
 "type": "object",
 "description": "待验证的技术方案，需包含 title 和 tasks 字段",
 },
 },
 "required": ["plan"],
 },
)
async def verify_plan(plan: dict[str, Any]) -> ToolResult:
 """Validate a technical plan with three-layer checks."""
 errors: list[dict[str, str]] =
 warnings: list[dict[str, str]] =
 # === Layer 1: Structure validation (blocking) ===
 required_fields = ["title", "tasks"]
 for f in required_fields:
 if f not in plan or not plan[f]:
 errors.append({"field": f, "message": f"缺少必填字段: {f}"})
 tasks = plan.get("tasks", )
 if isinstance(tasks, list):
 for i, task in enumerate(tasks):
 if not isinstance(task, dict):
 errors.append({"field": f"tasks[{i}]", "message": "任务必须是对象"})
 continue
 if not task.get("instruction"):
 errors.append(
 {"field": f"tasks[{i}].instruction", "message": "任务缺少 instruction"}
 )
 # === Layer 2: Quality validation (warning) ===
 if not errors:
 title = plan.get("title", "")
 if len(title) < 5:
 warnings.append({"field": "title", "message": "标题过短，建议至少 5 个字符"})
 for i, task in enumerate(tasks):
 instruction = task.get("instruction", "")
 if len(instruction) < 20:
 warnings.append(
 {
 "field": f"tasks[{i}].instruction",
 "message": f"instruction 过短 ({len(instruction)} 字符)，建议至少 20 字符以确保清晰",
 }
 )
 # === Layer 3: Semantic validation (reserved) ===
 # Future: custom rules, dependency checks, etc.
 valid = len(errors) == 0
 summary = "验证通过" if valid else f"验证失败: {len(errors)} 个错误"
 if warnings:
 summary += f", {len(warnings)} 个警告"
 return ToolResult(
 success=True, # Tool itself always succeeds; validation result is in output
 output={
 "valid": valid,
 "errors": errors,
 "warnings": warnings,
 "summary": summary,
 },
 )
