"""内置 artifact_type 注册（Chassis v2 · P1）。

``technical_plan`` 首个注册：content 校验复用 ``workflows.schemas.technical_plan``
（§7 MergedPlan schema），markdown 渲染复用既有 ``render_merged_plan_markdown``。
"""

from __future__ import annotations

from delivery.artifacts.registry import register_artifact_type

ARTIFACT_TYPE_TECHNICAL_PLAN = "technical_plan"


def _validate_technical_plan(content: dict) -> tuple[bool, str | None]:
    from workflows.schemas.technical_plan import validate_technical_plan

    return validate_technical_plan(content)


def _render_technical_plan(content: dict) -> str:
    from services.process_runtime.render import render_merged_plan_markdown

    return render_merged_plan_markdown(content)


register_artifact_type(
    ARTIFACT_TYPE_TECHNICAL_PLAN,
    validator=_validate_technical_plan,
    renderer=_render_technical_plan,
)
