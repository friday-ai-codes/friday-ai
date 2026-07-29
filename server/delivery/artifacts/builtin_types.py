"""内置 artifact_type 注册（Chassis v2 · P1；Phase 111-01 加 blueprint/v1 判别分支）。

``technical_plan`` 首个注册：content 校验复用 ``workflows.schemas.technical_plan``
（§7 MergedPlan schema），markdown 渲染复用既有 ``render_merged_plan_markdown``。

blueprint/v1（DESIGN §3.1：不新增 artifact_type，按 ``schema_version`` 判别）：
content 带 ``schema_version == "blueprint/v1"`` 时改走 ``validate_blueprint``
——这是蓝图 content 落 ArtifactVersion 的唯一接线点（SCHEMA-01 强制入库门）；
无该字段的旧 v0 content 路径零变化。renderer 分支归 115/116，本相位不做。
"""

from __future__ import annotations

from delivery.artifacts.registry import register_artifact_type

ARTIFACT_TYPE_TECHNICAL_PLAN = "technical_plan"


def _validate_technical_plan(content: dict) -> tuple[bool, str | None]:
    if isinstance(content, dict) and content.get("schema_version"):
        # 判别常量与校验器同源懒 import（MN-10）：本模块不再复制 "blueprint/v1"
        # 字面量，避免 schema 演进时漏改一处导致新版蓝图静默走 v0 校验路径。
        from services.process_runtime.blueprint_schema import (
            BLUEPRINT_SCHEMA_VERSION,
            validate_blueprint,
        )

        if content.get("schema_version") == BLUEPRINT_SCHEMA_VERSION:
            return validate_blueprint(content)
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
