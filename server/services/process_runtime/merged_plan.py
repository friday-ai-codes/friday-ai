"""MergedPlan §7 content schema 校验（Phase 40-01 Task 2，DOMAIN §7）。

定义 canonical ``PlanVersion.content`` 的 §7 MergedPlan 形状并做 schema 校验。
``execution_plan`` 子结构**复用** PF-02 已对齐的 ``workflows.schemas.technical_plan``
的 ``validate_technical_plan``（不重复造轮子）——这保证「过 ``validate_merged_plan``
的 content 必能过 ``TechnicalPlanService.create_from`` 内的 ``validate_technical_plan``」
（40-02 落 canonical 不二次失败）。

§7 MergedPlan 形状（``MERGED_PLAN_FIELDS``）：

- ``title`` / ``summary``：必填（technical_plan 必填子集）。
- ``execution_plan[]``：必填非空，每项含 ``repository_id`` + ``coding_instruction``
  + ``dependencies``（technical_plan schema 另强制 id/name/repository_name/branch_strategy）。
- ``api_contracts[]`` / ``dependency_dag`` / ``data_migrations[]`` / ``compat_risks[]``
  / ``release_order[]`` / ``rollback_plan``：跨仓字段，**不在本文件强制必填 / 不做跨仓
  语义校验**（那是 ``plan_validator.validate_plan`` 职责，避免重复 execution_plan 项校验）。
  jsonschema 默认 ``additionalProperties`` 允许，§7 额外字段不会被 technical_plan schema 拒。

本文件仅 import ``workflows.schemas.technical_plan``（守 INV-3 边界，不 import knowledge）。
"""

from __future__ import annotations

from typing import Any

from workflows.schemas.technical_plan import validate_technical_plan

__all__ = ["MERGED_PLAN_FIELDS", "validate_merged_plan"]

# §7 MergedPlan 字段（文档化形状；必填性见模块 docstring，跨仓字段可为空 list）
MERGED_PLAN_FIELDS = (
    "title",
    "summary",
    "api_contracts",
    "dependency_dag",
    "data_migrations",
    "compat_risks",
    "release_order",
    "rollback_plan",
    "execution_plan",
)


def validate_merged_plan(content: Any) -> tuple[bool, str | None]:
    """校验 §7 MergedPlan content 形状（execution_plan 子结构复用 technical_plan）。

    Args:
        content: 半可信 MergedPlan dict（LLM 合成产物）。

    Returns:
        ``(True, None)`` 合法；``(False, error_message)`` 非法。顶层非 dict 等半可信
        输入恒不抛异常（防御性返回 ``(False, ...)``，对齐 verify_plan fail-safe 范式）。
    """
    if not isinstance(content, dict):
        return False, "MergedPlan 必须是对象（dict）"
    # execution_plan 子结构复用 validate_technical_plan：content 含 title/summary/
    # execution_plan 即满足其必填；§7 额外字段（api_contracts 等）jsonschema 默认
    # additionalProperties 允许，不会被拒。
    return validate_technical_plan(content)
