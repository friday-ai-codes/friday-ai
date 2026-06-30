"""创建项目（工作区）节点（#4）。

``CreateProjectWorkspaceNode``：在工作流中直接创建 ``initiatives.Project``（自动经
``ProjectService.create`` 触发 5 个工作区文件 provision：MEMORY/STATE/MILESTONES/RESEARCH/
PREFLIGHT），并可：

- **拆分 / 绑定 feature list**：上游连入结构化 ``modules``（``feature_list`` shape 端口）则直接
  绑定；否则可填整篇文档文本由 AI 解析拆分为「模块→功能点→验收项」后绑定
  （``FeatureListService.aset_feature_list``，内容逐字保留原文）。
- **依赖 / 知识关联**：建好后 best-effort 同步操作态关系到知识图谱
  （``ProjectKnowledgeGraphService.sync_relations_from_operational``）；feature list 落库后
  项目星图 / 外部依赖 / 知识关联读时自动派生（galaxy 端点读 feature-list/work-items/KLINK）。

与既有 ``create_project``（飞书看板专用）区分：本节点面向「手动 / AI 直接建项目」路径。
写入全部经既有 service（INV-6），不旁路写表；feature list / 依赖同步均 best-effort 不反噬建项目。
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async

from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger(__name__)


@register_node
class CreateProjectWorkspaceNode(BaseNode):
    """创建项目（工作区）+ 5 文件 + 绑定/拆分 feature list + 依赖知识关联。"""

    node_type = "create_project_workspace"
    display_name = "创建项目（工作区）"
    description = "创建项目并建 5 个工作区文件，可绑定/AI 拆分 feature list 并关联依赖与知识"
    icon = "folder-plus"
    category = NodeCategory.INTEGRATION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "title": "项目名称",
                "description": "项目名称，支持模板变量",
                "default": "",
            },
            "description": {
                "type": "string",
                "title": "项目描述",
                "description": "可选项目描述，支持模板变量",
                "default": "",
            },
            "space_identifier": {
                "type": "string",
                "title": "空间标识",
                "description": "空间 ID 或飞书项目 Key（留空则用工作流绑定空间）",
                "default": "",
            },
            "feature_list_text": {
                "type": "string",
                "title": "feature list 文档（AI 解析）",
                "description": (
                    "可选：粘贴整篇需求 / feature 文档，由 AI 拆分为结构化 feature list 并绑定"
                    "（内容逐字保留原文）。若上游已连入结构化 feature list 则优先用上游。"
                ),
                "default": "",
            },
            "associate_dependencies": {
                "type": "boolean",
                "title": "关联依赖 / 知识",
                "description": "建好后同步项目操作态关系到知识图谱（星图/依赖/知识关联读时派生）",
                "default": True,
            },
        },
        "required": ["name"],
    }

    inputs = [
        NodePort(name="default", label="输入", port_type=PortType.OBJECT, required=False),
        NodePort(
            name="feature_list",
            label="feature list",
            port_type=PortType.OBJECT,
            required=False,
            shape="feature_list",
            description="上游拆分出的结构化 feature list（modules）",
        ),
    ]
    outputs = [
        NodePort(
            name="default",
            label="成功",
            port_type=PortType.OBJECT,
            description="含 project_id / created / feature_list_applied / name",
        ),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config
        log = logger.bind(node_id=context.node_id)

        name = context.render_template(config.get("name", "")).strip()
        if not name:
            return NodeResult(
                status="failed", error="缺少项目名称（name）", next_handle="error"
            )
        description = context.render_template(config.get("description", "")).strip()
        space_identifier = context.render_template(
            config.get("space_identifier", "")
        ).strip()

        space = await self._resolve_space(context, space_identifier)
        if space is None:
            return NodeResult(
                status="failed",
                error="未找到空间（请配置 space_identifier 或为工作流绑定空间）",
                next_handle="error",
            )

        from initiatives.services import ProjectService

        try:
            project, created = await ProjectService().create(
                space=space,
                name=name,
                description=description,
                initiated_by_user_id="system",
            )
        except Exception as exc:  # noqa: BLE001 — 建项目失败转 error handle
            log.warning("create_project_workspace_failed", error=str(exc))
            return NodeResult(
                status="failed", error=f"创建项目失败：{exc}", next_handle="error"
            )

        # feature list：优先上游结构化 modules，否则文档文本 AI 解析。
        feature_list_applied = await self._maybe_bind_feature_list(
            context, project_id=project.id
        )

        # 依赖 / 知识关联（best-effort，不反噬建项目）。
        if config.get("associate_dependencies", True):
            await self._maybe_sync_relations(project)

        log.info(
            "create_project_workspace_completed",
            project_id=str(project.id),
            created=created,
            feature_list_applied=feature_list_applied,
        )
        return NodeResult(
            status="completed",
            output={
                "project_id": str(project.id),
                "created": created,
                "name": project.name,
                "feature_list_applied": feature_list_applied,
                "source": "create_project_workspace",
            },
            next_handle="default",
        )

    async def _maybe_bind_feature_list(
        self, context: ExecutionContext, *, project_id: Any
    ) -> bool:
        """绑定 feature list：上游结构化 modules 优先，否则配置文档文本走 AI 解析。best-effort。"""
        modules = context.get_input("modules")
        if not isinstance(modules, list) or not modules:
            fl = context.get_input("feature_list")
            if isinstance(fl, dict) and isinstance(fl.get("modules"), list):
                modules = fl["modules"]
            elif isinstance(fl, list):
                modules = fl
        text = context.render_template(context.get_config("feature_list_text", "") or "").strip()

        if not (isinstance(modules, list) and modules) and not text:
            return False

        from initiatives.services.feature_list_service import FeatureListService

        try:
            if isinstance(modules, list) and modules:
                await FeatureListService().aset_feature_list(
                    project_id, mode="manual", modules=modules, initiated_by_user_id="system"
                )
            else:
                await FeatureListService().aset_feature_list(
                    project_id, mode="paste", paste_text=text, initiated_by_user_id="system"
                )
            return True
        except Exception as exc:  # noqa: BLE001 — feature list 绑定 best-effort，不反噬建项目
            logger.warning(
                "create_project_workspace_feature_list_failed",
                project_id=str(project_id),
                error=str(exc),
            )
            return False

    @staticmethod
    async def _maybe_sync_relations(project: Any) -> None:
        try:
            from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService

            await ProjectKnowledgeGraphService().sync_relations_from_operational(
                project=project, initiated_by_user_id="system"
            )
        except Exception as exc:  # noqa: BLE001 — 关系同步 best-effort
            logger.warning(
                "create_project_workspace_sync_relations_failed",
                project_id=str(getattr(project, "id", "") or ""),
                error=str(exc),
            )

    async def _resolve_space(self, context: ExecutionContext, space_identifier: str):
        """解析 Space（显式标识 → 工作流绑定空间）。"""
        import uuid as uuid_mod

        from projects.models import Space

        if space_identifier:
            try:
                uuid_mod.UUID(space_identifier)
                space = await Space.objects.filter(id=space_identifier).afirst()
                if space:
                    return space
            except ValueError:
                pass
            space = await Space.objects.filter(
                feishu_project_key=space_identifier
            ).afirst()
            if space:
                return space

        execution = context.workflow_execution
        if execution is None:
            return None
        return await sync_to_async(lambda: execution.workflow.space)()
