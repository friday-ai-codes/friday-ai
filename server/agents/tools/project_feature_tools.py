"""save_project_feature_list chat agent 工具（#5 Part A）。

项目内 AI 对话生成 / 整理出 feature list 时，把它**绑定到当前会话所绑定的项目**
（``Conversation.bound_project``）。经 ``FeatureListService.aset_feature_list`` 写入项目
feature_list 工件（INV-6 写收口，落 markdown 载体），即在项目大盘 Features 区可见。

薄封装铁律：不写新业务逻辑，只做 ① 由注入的 ``conversation_id`` 反查 ``bound_project``；
② 复用既有 service 写入；③ 标准 ToolResult 映射。未绑项目 / 非成员 → 失败但不抛。
async ORM 用 ``.values()`` / ``afirst`` 标量取，规避裸 lazy-FK。
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.tools.base import ToolResult, tool

logger = structlog.get_logger(__name__)


@tool(
    name="save_project_feature_list",
    description=(
        "把当前对话整理出的 feature list 保存并绑定到「当前项目」。当对话已在某个项目中、"
        "且你已和用户梳理出「模块 → 功能点 → 验收项」结构时调用，将其落库到项目的 feature 清单"
        "（项目大盘 Features 区可见）。仅在对话绑定了项目时有效。"
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "modules": {
                "type": "array",
                "description": (
                    "模块列表。每项 {module: 模块名, features: [{name: 功能点, "
                    "acceptance: [验收项...]}]}。功能点 / 验收项内容请保留用户原意，勿臆造。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "module": {"type": "string"},
                        "features": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "acceptance": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["name"],
                            },
                        },
                    },
                    "required": ["module", "features"],
                },
            },
            "conversation_id": {
                "type": "string",
                "description": "会话 UUID (auto-injected)",
            },
        },
        "required": ["modules", "conversation_id"],
    },
)
async def save_project_feature_list(
    modules: list[dict[str, Any]],
    conversation_id: str,
) -> ToolResult:
    """把 feature list 绑定写入当前会话所绑定的项目。"""
    if not isinstance(modules, list) or not modules:
        return ToolResult(success=False, error="modules 不能为空")

    from django.contrib.auth import get_user_model

    from chat.models import Conversation
    from initiatives.services.feature_list_service import FeatureListService

    row = await (
        Conversation.objects.filter(id=conversation_id)
        .values("bound_project_id", "created_by_id")
        .afirst()
    )
    if not row or not row.get("bound_project_id"):
        return ToolResult(
            success=False,
            error="当前对话未绑定项目，无法保存 feature list（请在项目中发起对话）",
        )
    project_id = row["bound_project_id"]
    actor = None
    if row.get("created_by_id"):
        actor = await get_user_model().objects.filter(id=row["created_by_id"]).afirst()

    try:
        await FeatureListService().aset_feature_list(
            project_id,
            mode="manual",
            modules=modules,
            actor=actor,
            initiated_by_user_id=str(row.get("created_by_id") or "") or None,
        )
    except Exception as exc:  # noqa: BLE001 — 写入失败转工具错误，不抛
        logger.warning(
            "save_project_feature_list_failed",
            conversation_id=conversation_id,
            project_id=str(project_id),
            error_type=type(exc).__name__,
            component="agents.tools",
            category="caller",
        )
        return ToolResult(success=False, error=f"保存 feature list 失败：{exc}")

    feature_count = sum(
        len(m.get("features") or []) for m in modules if isinstance(m, dict)
    )
    logger.info(
        "save_project_feature_list_done",
        conversation_id=conversation_id,
        project_id=str(project_id),
        module_count=len(modules),
        feature_count=feature_count,
        component="agents.tools",
        category="caller",
    )
    return ToolResult(
        success=True,
        output={
            "bound_project_id": str(project_id),
            "module_count": len(modules),
            "feature_count": feature_count,
        },
    )


__all__ = ["save_project_feature_list"]
