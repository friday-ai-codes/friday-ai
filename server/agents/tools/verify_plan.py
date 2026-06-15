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
                "description": "待验证的技术方案，需包含 title 和 execution_plan 字段",
            },
        },
        "required": ["plan"],
    },
)
async def verify_plan(plan: dict[str, Any]) -> ToolResult:
    """Validate a technical plan with three-layer checks.

    PF-02：校验字段对齐 canonical ``execution_plan`` schema（``technical_plan.py`` +
    DOMAIN §7 MergedPlan.execution_plan：每任务含 ``repository_id`` + ``coding_instruction``）。
    本 phase 只做最小 schema 对齐；契约一致/依赖成环/回滚完整等扩展校验留
    Phase 40 PlanValidator（在此基础上扩展）。工具自身恒 ``success=True``，
    校验结论在 output；output 形状恒为 ``{valid, errors, warnings, summary}``。
    """
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    # === Layer 1: Structure validation (blocking) ===
    # 半可信输入：逐项 isinstance 校验 + .get 取值，非法结构落 errors 不抛异常
    # （工具恒 success=True，security mitigation T-36-01-01）。
    required_fields = ["title", "execution_plan"]
    for f in required_fields:
        if f not in plan or not plan[f]:
            errors.append({"field": f, "message": f"缺少必填字段: {f}"})

    execution_plan = plan.get("execution_plan", [])
    if not isinstance(execution_plan, list):
        # execution_plan 为真值但非数组（str/dict/int 等常见 LLM 误产）：显式记结构错误
        # 并归一为 []，避免 Layer 2 对 str/dict 抛 AttributeError、对 int 抛 TypeError
        # （守 fail-safe 契约 T-36-01-01：工具恒 success=True，非法结构落 errors 不抛异常）。
        # 假值（""/0/{}/None/[]）已被上方必填校验记「缺少必填字段」，此处不重复记。
        if plan.get("execution_plan"):
            errors.append({"field": "execution_plan", "message": "execution_plan 必须是数组"})
        execution_plan = []
    else:
        for i, item in enumerate(execution_plan):
            if not isinstance(item, dict):
                errors.append({"field": f"execution_plan[{i}]", "message": "任务必须是对象"})
                continue
            if not item.get("repository_id"):
                errors.append(
                    {
                        "field": f"execution_plan[{i}].repository_id",
                        "message": "任务缺少 repository_id",
                    }
                )
            if not item.get("coding_instruction"):
                errors.append(
                    {
                        "field": f"execution_plan[{i}].coding_instruction",
                        "message": "任务缺少 coding_instruction",
                    }
                )

    # === Layer 2: Quality validation (warning) ===
    if not errors:
        title = plan.get("title", "")
        if len(title) < 5:
            warnings.append({"field": "title", "message": "标题过短，建议至少 5 个字符"})

        for i, item in enumerate(execution_plan):
            instruction = item.get("coding_instruction", "")
            if len(instruction) < 20:
                warnings.append(
                    {
                        "field": f"execution_plan[{i}].coding_instruction",
                        "message": f"coding_instruction 过短 ({len(instruction)} 字符)，建议至少 20 字符以确保清晰",
                    }
                )

    # === Layer 3: Semantic validation (reserved) ===
    # Future: custom rules, dependency checks, etc.

    valid = len(errors) == 0
    summary = "验证通过" if valid else f"验证失败: {len(errors)} 个错误"
    if warnings:
        summary += f", {len(warnings)} 个警告"

    return ToolResult(
        success=True,  # Tool itself always succeeds; validation result is in output
        output={
            "valid": valid,
            "errors": errors,
            "warnings": warnings,
            "summary": summary,
        },
    )
