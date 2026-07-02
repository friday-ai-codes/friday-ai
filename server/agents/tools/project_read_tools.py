"""项目级对话的项目只读工具集（project-scoped read tools）。

项目级对话（``Conversation.bound_project`` 非空）里，让 LLM 能"以项目视角"主动查看：

- ``get_project_overview``   —— 项目概览（名称/描述/状态/所属空间 + 各类资产计数）
- ``list_project_features``  —— Feature 清单（模块 → 功能点，含进度灯）
- ``get_project_feature``    —— 单个功能点详情（验收项/进度/所属模块/原文）
- ``list_project_artifacts`` —— 工件清单（类型/标题/载体/链接/版本）
- ``get_project_artifact``   —— 单个工件内容（正文 / 链接 / 元数据）
- ``get_project_related``    —— 项目关联（关联项目 + 交付知识图谱邻居）

**薄封装铁律**：不写新业务逻辑，复用既有 service / model；由注入的 ``conversation_id``
反查 ``bound_project`` 并做权限 fail-closed（成员任意可见性可读，非成员仅 ``public_org``
可读，否则零结果零泄漏，与 ``pack_project_context`` 同口径）。async ORM 走 ``.values()`` /
``afirst`` / ``acount`` / 异步迭代，规避裸 lazy-FK。观测 best-effort，绝不反噬对话主流程。
"""

from __future__ import annotations

from typing import Any

import structlog

from agents.tools.base import ToolResult, tool

logger = structlog.get_logger(__name__)

_COMPONENT = "agents.tools"

_SCOPE_ERRORS = {
    "missing_conversation_id": "缺少会话上下文，无法定位项目",
    "not_bound": "当前对话未绑定项目（请在项目中发起对话后再使用项目工具）",
    "project_not_found": "会话绑定的项目不存在或已删除",
    "forbidden": "你不是该项目成员且项目非全员可读，无权查看（fail-closed）",
}


async def _resolve_project_scope(conversation_id: str) -> tuple[Any, Any, str]:
    """由注入的 ``conversation_id`` 反查 ``bound_project`` 并做读权限 fail-closed。

    Returns:
        ``(project, user, reason)``。``project`` 非空表示放行；为空时 ``reason`` 为
        ``_SCOPE_ERRORS`` 键，供工具映射标准错误。
    """
    if not conversation_id:
        return None, None, "missing_conversation_id"

    from django.contrib.auth import get_user_model

    from chat.models import Conversation
    from initiatives.models import Project, ProjectMember, ProjectVisibility

    row = await (
        Conversation.objects.filter(id=conversation_id)
        .values("bound_project_id", "created_by_id")
        .afirst()
    )
    if not row or not row.get("bound_project_id"):
        return None, None, "not_bound"

    project = await (
        Project.objects.select_related("space").filter(pk=row["bound_project_id"]).afirst()
    )
    if project is None:
        return None, None, "project_not_found"

    user = None
    if row.get("created_by_id"):
        user = await get_user_model().objects.filter(pk=row["created_by_id"]).afirst()

    # 读权限：成员（任意可见性）放行；非成员仅 public_org 放行；否则 fail-closed。
    allowed = False
    if user is not None:
        allowed = await ProjectMember.objects.filter(
            project_id=project.id, user_id=user.id
        ).aexists()
    if not allowed and getattr(project, "visibility", "") == ProjectVisibility.PUBLIC_ORG:
        allowed = True
    if not allowed:
        return None, None, "forbidden"

    return project, user, ""


def _deny(reason: str) -> ToolResult:
    return ToolResult(success=False, error=_SCOPE_ERRORS.get(reason, "无权访问该项目"))


def _log(event: str, conversation_id: str, project: Any, **kv: Any) -> None:
    logger.info(
        event,
        conversation_id=conversation_id,
        project_id=str(getattr(project, "id", "")),
        component=_COMPONENT,
        category="caller",
        **kv,
    )


# 会话 id 注入参数（各工具复用；由 chat_runner 从 args_schema 剔除后闭包注入）。
_CONV_ID_PARAM = {
    "conversation_id": {
        "type": "string",
        "description": "会话 UUID (auto-injected)",
    },
}


@tool(
    name="get_project_overview",
    description=(
        "查看「当前项目」的概览：项目名称、描述、状态、所属空间，以及 Feature 模块数 / 功能点数 / "
        "工件数 / 项目记忆数 / 关联需求数 / 关联项目数。回答「这是什么项目 / 项目在做什么 / "
        "项目有哪些资产」时优先调用。仅在对话绑定了项目时有效。"
    ),
    category="KNOWLEDGE",
    parameters={
        "type": "object",
        "properties": dict(_CONV_ID_PARAM),
        "required": ["conversation_id"],
    },
)
async def get_project_overview(conversation_id: str = "") -> ToolResult:
    project, _user, reason = await _resolve_project_scope(conversation_id)
    if project is None:
        return _deny(reason)

    from initiatives.models import (
        Artifact,
        ProjectMemory,
        ProjectMemoryStatus,
        ProjectRelation,
        ProjectWorkItemLink,
    )
    from initiatives.services.feature_list_service import FeatureListService

    space = getattr(project, "space", None)
    artifact_count = await Artifact.objects.filter(project_id=project.id).acount()
    memory_count = await ProjectMemory.objects.filter(
        project_id=project.id, status=ProjectMemoryStatus.ACTIVE
    ).acount()
    requirement_count = await ProjectWorkItemLink.objects.filter(
        project_id=project.id
    ).acount()
    related_out = await ProjectRelation.objects.filter(source_id=project.id).acount()
    related_in = await ProjectRelation.objects.filter(target_id=project.id).acount()

    module_count = 0
    feature_count = 0
    try:
        tree = await FeatureListService().build_tree(project.id)
        modules = tree.get("modules") or []
        module_count = len(modules)
        feature_count = sum(len(m.get("features") or []) for m in modules)
    except Exception:  # noqa: BLE001 — feature 树 best-effort
        pass

    output = {
        "id": str(project.id),
        "name": getattr(project, "name", "") or "",
        "description": getattr(project, "description", "") or "",
        "status": project.get_status_display() if hasattr(project, "get_status_display") else "",
        "visibility": project.get_visibility_display()
        if hasattr(project, "get_visibility_display")
        else "",
        "space": getattr(space, "name", "") or "" if space else "",
        "counts": {
            "feature_modules": module_count,
            "features": feature_count,
            "artifacts": artifact_count,
            "memories": memory_count,
            "requirements": requirement_count,
            "related_projects": related_out + related_in,
        },
    }
    _log("get_project_overview_done", conversation_id, project)
    return ToolResult(success=True, output=output)


@tool(
    name="list_project_features",
    description=(
        "列出「当前项目」的 Feature 清单：按模块分组，含每个模块的介绍与功能点（名称 + 进度灯）。"
        "回答「项目有哪些功能 / 做到哪了 / 有哪些模块」时调用。仅在对话绑定了项目时有效。"
    ),
    category="KNOWLEDGE",
    parameters={
        "type": "object",
        "properties": dict(_CONV_ID_PARAM),
        "required": ["conversation_id"],
    },
)
async def list_project_features(conversation_id: str = "") -> ToolResult:
    project, _user, reason = await _resolve_project_scope(conversation_id)
    if project is None:
        return _deny(reason)

    from initiatives.services.feature_list_service import FeatureListService

    try:
        tree = await FeatureListService().build_tree(project.id)
    except Exception as exc:  # noqa: BLE001 — 拉取失败转工具错误，不抛
        logger.warning(
            "list_project_features_failed",
            conversation_id=conversation_id,
            project_id=str(project.id),
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error=f"读取 feature 清单失败：{exc}")

    modules_out: list[dict[str, Any]] = []
    for mod in tree.get("modules") or []:
        feats = mod.get("features") or []
        modules_out.append(
            {
                "module": str(mod.get("module") or "未分组"),
                "summary": str(mod.get("summary") or ""),
                "feature_count": len(feats),
                "features": [
                    {
                        "name": str(f.get("name") or ""),
                        "progress": str(f.get("progress") or ""),
                        "status_display_name": str(f.get("status_display_name") or ""),
                        "acceptance_count": len(f.get("acceptance") or []),
                    }
                    for f in feats
                ],
            }
        )
    feature_total = sum(m["feature_count"] for m in modules_out)
    _log(
        "list_project_features_done",
        conversation_id,
        project,
        module_count=len(modules_out),
        feature_count=feature_total,
    )
    return ToolResult(
        success=True,
        output={
            "module_count": len(modules_out),
            "feature_count": feature_total,
            "modules": modules_out,
        },
    )


@tool(
    name="get_project_feature",
    description=(
        "查看「当前项目」中某个功能点的详情：所属模块、进度、验收项列表、原文。"
        "已知功能点名称、需要看它的验收标准 / 进度时调用。仅在对话绑定了项目时有效。"
    ),
    category="KNOWLEDGE",
    parameters={
        "type": "object",
        "properties": {
            "feature_name": {
                "type": "string",
                "description": "功能点名称（支持部分匹配，大小写不敏感）",
            },
            **_CONV_ID_PARAM,
        },
        "required": ["feature_name", "conversation_id"],
    },
)
async def get_project_feature(feature_name: str = "", conversation_id: str = "") -> ToolResult:
    if not (feature_name or "").strip():
        return ToolResult(success=False, error="feature_name 不能为空")
    project, _user, reason = await _resolve_project_scope(conversation_id)
    if project is None:
        return _deny(reason)

    from initiatives.services.feature_list_service import FeatureListService

    try:
        tree = await FeatureListService().build_tree(project.id)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(success=False, error=f"读取 feature 清单失败：{exc}")

    needle = feature_name.strip().lower()
    matches: list[dict[str, Any]] = []
    for mod in tree.get("modules") or []:
        module_name = str(mod.get("module") or "未分组")
        for f in mod.get("features") or []:
            name = str(f.get("name") or "")
            if needle in name.lower():
                matches.append(
                    {
                        "module": module_name,
                        "name": name,
                        "progress": str(f.get("progress") or ""),
                        "status_display_name": str(f.get("status_display_name") or ""),
                        "acceptance": [str(a) for a in (f.get("acceptance") or [])],
                        "source": str(f.get("source") or ""),
                    }
                )
    if not matches:
        return ToolResult(
            success=False,
            error=f"未找到名称包含「{feature_name}」的功能点（可先用 list_project_features 查看全部）",
        )
    _log("get_project_feature_done", conversation_id, project, match_count=len(matches))
    return ToolResult(success=True, output={"matches": matches, "total": len(matches)})


@tool(
    name="list_project_artifacts",
    description=(
        "列出「当前项目」的工件（需求文档 / feature list / 研发 Spec / UI 稿 / 埋点 / 复盘 等）："
        "含类型、标题、载体、链接、版本。回答「项目有哪些文档 / 工件」时调用。"
        "拿到工件 id 后可用 get_project_artifact 看正文。仅在对话绑定了项目时有效。"
    ),
    category="KNOWLEDGE",
    parameters={
        "type": "object",
        "properties": dict(_CONV_ID_PARAM),
        "required": ["conversation_id"],
    },
)
async def list_project_artifacts(conversation_id: str = "") -> ToolResult:
    project, _user, reason = await _resolve_project_scope(conversation_id)
    if project is None:
        return _deny(reason)

    from initiatives.models import Artifact

    rows: list[dict[str, Any]] = []
    async for a in (
        Artifact.objects.filter(project_id=project.id)
        .select_related("type")
        .order_by("-created_at")[:100]
    ):
        rows.append(
            {
                "id": str(a.id),
                "type_key": a.type.key,
                "type_name": a.type.name,
                "title": a.title,
                "carrier": a.carrier,
                "url": a.url or "",
                "version": a.version,
                "has_content": bool((a.content_ref or "").strip()),
            }
        )
    _log("list_project_artifacts_done", conversation_id, project, artifact_count=len(rows))
    return ToolResult(success=True, output={"artifacts": rows, "total": len(rows)})


@tool(
    name="get_project_artifact",
    description=(
        "查看「当前项目」中某个工件的内容与元数据：正文（markdown 载体）、链接（飞书/外链载体）、"
        "类型、载体、版本。传 artifact_id（优先，来自 list_project_artifacts）或 title（部分匹配）。"
        "仅在对话绑定了项目时有效。"
    ),
    category="KNOWLEDGE",
    parameters={
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string", "description": "工件 UUID（优先）"},
            "title": {"type": "string", "description": "工件标题（部分匹配，artifact_id 为空时用）"},
            **_CONV_ID_PARAM,
        },
        "required": ["conversation_id"],
    },
)
async def get_project_artifact(
    artifact_id: str = "", title: str = "", conversation_id: str = ""
) -> ToolResult:
    project, _user, reason = await _resolve_project_scope(conversation_id)
    if project is None:
        return _deny(reason)
    if not (artifact_id or "").strip() and not (title or "").strip():
        return ToolResult(success=False, error="需提供 artifact_id 或 title 之一")

    from initiatives.models import Artifact

    # 始终以 project_id 收口查询，杜绝跨项目越权读取。
    qs = Artifact.objects.filter(project_id=project.id).select_related("type")
    artifact = None
    if (artifact_id or "").strip():
        artifact = await qs.filter(id=artifact_id.strip()).afirst()
    if artifact is None and (title or "").strip():
        artifact = await qs.filter(title__icontains=title.strip()).order_by("-created_at").afirst()
    if artifact is None:
        return ToolResult(success=False, error="未找到匹配的工件（可先用 list_project_artifacts 查看）")

    content = (artifact.content_ref or "")
    truncated = len(content) > 8000
    output = {
        "id": str(artifact.id),
        "type_key": artifact.type.key,
        "type_name": artifact.type.name,
        "title": artifact.title,
        "carrier": artifact.carrier,
        "url": artifact.url or "",
        "version": artifact.version,
        "content": content[:8000],
        "content_truncated": truncated,
    }
    _log("get_project_artifact_done", conversation_id, project, artifact_id=str(artifact.id))
    return ToolResult(success=True, output=output)


@tool(
    name="get_project_related",
    description=(
        "查看「当前项目」的关联：显式关联的其他项目（含备注），以及交付知识图谱中的邻居实体"
        "（需求/方案/代码变更等）。回答「相关项目有哪些 / 项目关联了什么」时调用。"
        "仅在对话绑定了项目时有效。"
    ),
    category="KNOWLEDGE",
    parameters={
        "type": "object",
        "properties": dict(_CONV_ID_PARAM),
        "required": ["conversation_id"],
    },
)
async def get_project_related(conversation_id: str = "") -> ToolResult:
    project, _user, reason = await _resolve_project_scope(conversation_id)
    if project is None:
        return _deny(reason)

    from initiatives.models import ProjectRelation

    related_projects: list[dict[str, Any]] = []
    async for rel in (
        ProjectRelation.objects.filter(source_id=project.id)
        .select_related("target")[:50]
    ):
        related_projects.append(
            {
                "direction": "out",
                "project_id": str(rel.target_id),
                "name": getattr(rel.target, "name", "") or "",
                "note": rel.note or "",
            }
        )
    async for rel in (
        ProjectRelation.objects.filter(target_id=project.id)
        .select_related("source")[:50]
    ):
        related_projects.append(
            {
                "direction": "in",
                "project_id": str(rel.source_id),
                "name": getattr(rel.source, "name", "") or "",
                "note": rel.note or "",
            }
        )

    knowledge: list[dict[str, Any]] = []
    try:
        from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService

        nodes = await ProjectKnowledgeGraphService().query_graph(
            project=project, direction="both", max_hops=1
        )
        knowledge = [
            {"kind": n.get("kind", ""), "title": n.get("title", "")}
            for n in nodes
            if n.get("title")
        ][:50]
    except Exception:  # noqa: BLE001 — 图谱召回 best-effort，失败降级空
        knowledge = []

    _log(
        "get_project_related_done",
        conversation_id,
        project,
        related_project_count=len(related_projects),
        knowledge_count=len(knowledge),
    )
    return ToolResult(
        success=True,
        output={
            "related_projects": related_projects,
            "knowledge": knowledge,
            "total": len(related_projects) + len(knowledge),
        },
    )


__all__ = [
    "get_project_overview",
    "list_project_features",
    "get_project_feature",
    "list_project_artifacts",
    "get_project_artifact",
    "get_project_related",
]
