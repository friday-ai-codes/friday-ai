"""AI 自动建分支节点（#4）。

``AICreateBranchNode``：基于技术方案 / feature list / 需求文本，给一个或多个仓库创建分支并
**绑定到项目**。与本地 ``create_branch`` 节点区分：本节点经
``BranchProvisionService.provision_and_bind``（token 注入 push + ``ProjectBranchService.bind``
绑 仓库↔分支↔项目，INV-6 单一编排收口）。

分支名解析顺序：
1. 配置 ``branch_name``（支持模板）非空 → 直接用；
2. 否则取技术方案 / 需求文本（配置 ``plan_text`` 或上游 ``plan_markdown`` / ``plan``），
   经 ``agenerate_default_branch_name`` 由 AI 生成（``feat/...`` 等规范名）；
3. 仍无 → 失败 error handle。

``base_branch`` 默认 ``master``（可配置）。项目从配置 ``project_id`` 或上游输出 ``project_id`` 解析；
无项目无法绑定 → error handle（建分支应绑项目，回接 IDE 闭环）。
"""

from __future__ import annotations

import uuid as uuid_mod
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
    normalize_repositories,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger(__name__)


@register_node
class AICreateBranchNode(BaseNode):
    """基于方案/feature list AI 生成分支名，多仓建分支 + 推送 + 绑项目。"""

    node_type = "ai_create_branch"
    display_name = "AI 创建分支"
    description = "基于技术方案/feature list 给多仓创建分支并推送、绑定到项目（分支名可 AI 生成）"
    icon = "git-branch-plus"
    category = NodeCategory.ACTION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "repositories": {
                "type": "array",
                "title": "目标仓库",
                "description": "仓库 ID / 名称列表，支持 {{global.repositories}} 等模板",
                "items": {"type": "string"},
                "default": [],
            },
            "project_id": {
                "type": "string",
                "title": "绑定项目 ID",
                "description": "建分支后绑定的项目 ID，支持模板（如 {{nodes.创建项目.project_id}}）",
                "default": "",
            },
            "branch_name": {
                "type": "string",
                "title": "分支名",
                "description": "留空则由 AI 基于技术方案/需求文本生成；支持模板变量",
                "default": "",
            },
            "base_branch": {
                "type": "string",
                "title": "基础分支",
                "description": "从其拉出新分支的基础分支（默认 master）",
                "default": "master",
            },
            "plan_text": {
                "type": "string",
                "title": "方案/需求文本",
                "description": "可选：技术方案或需求文本，供 AI 生成分支名（留空则取上游 plan_markdown）",
                "default": "",
            },
        },
        "required": [],
    }

    inputs = [
        NodePort(name="default", label="输入", port_type=PortType.OBJECT, required=False),
        NodePort(
            name="plan",
            label="技术方案",
            port_type=PortType.OBJECT,
            required=False,
            shape="technical_plan",
            description="上游技术方案产物（供 AI 解析分支名）",
        ),
    ]
    outputs = [
        NodePort(
            name="default",
            label="成功",
            port_type=PortType.OBJECT,
            description="含 branch_name / succeeded / failed / all_succeeded",
        ),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config
        log = logger.bind(node_id=context.node_id)

        # 1. 仓库解析
        repos = await self._resolve_repositories(config, context)
        if not repos:
            return NodeResult(
                status="failed", error="未解析到目标仓库", next_handle="error"
            )

        # 2. 项目解析（绑定目标）
        project = await self._resolve_project(config, context)
        if project is None:
            return NodeResult(
                status="failed",
                error="未找到绑定项目（请配置 project_id 或连入创建项目节点）",
                next_handle="error",
            )

        # 3. 分支名：配置优先，否则 AI 从方案/需求文本生成
        branch_name = context.render_template(config.get("branch_name", "") or "").strip()
        if not branch_name:
            branch_name = await self._ai_branch_name(config, context)
        if not branch_name:
            return NodeResult(
                status="failed",
                error="无法确定分支名（请填写 branch_name 或提供技术方案/需求文本供 AI 生成）",
                next_handle="error",
            )

        base_branch = (
            context.render_template(config.get("base_branch", "master") or "master").strip()
            or "master"
        )

        # 4. 逐仓建分支 + 推送 + 绑项目（BranchProvisionService 单一编排收口）
        from initiatives.services.branch_provision_service import BranchProvisionService

        result = await BranchProvisionService().provision_and_bind(
            project=project,
            repositories=repos,
            branch_names=branch_name,
            base_branch=base_branch,
            initiated_by_user_id="system",
            feishu_board_id=str(getattr(project, "feishu_board_id", "") or ""),
        )

        log.info(
            "ai_create_branch_completed",
            project_id=str(project.id),
            branch_name=branch_name,
            base_branch=base_branch,
            succeeded=len(result.get("succeeded", [])),
            failed=len(result.get("failed", [])),
        )
        # 全失败 → error handle；部分/全成功 → 成功（单仓 fail-soft 已在 result.failed）
        if not result.get("succeeded"):
            return NodeResult(
                status="failed",
                error="所有仓库建分支失败",
                output={"branch_name": branch_name, **result},
                next_handle="error",
            )
        return NodeResult(
            status="completed",
            output={
                "branch_name": branch_name,
                "base_branch": base_branch,
                "project_id": str(project.id),
                **result,
                "source": "ai_create_branch",
            },
            next_handle="default",
        )

    async def _resolve_repositories(
        self, config: dict, context: ExecutionContext
    ) -> list[Any]:
        """解析为 Repository 实例列表（按 id / name 命中，规避裸 lazy-FK）。"""
        from repositories.models import Repository

        repo_dicts = normalize_repositories(config, context)
        identifiers = [str(d.get("id")) for d in repo_dicts if d.get("id")]
        if not identifiers:
            return []
        uuids: list[str] = []
        names: list[str] = []
        for ident in identifiers:
            try:
                uuid_mod.UUID(ident)
                uuids.append(ident)
            except ValueError:
                names.append(ident)

        def _query() -> list[Any]:
            from django.db.models import Q

            q = Q()
            if uuids:
                q |= Q(id__in=uuids)
            if names:
                q |= Q(name__in=names)
            if not q:
                return []
            return list(Repository.objects.filter(q))

        return await sync_to_async(_query)()

    async def _resolve_project(self, config: dict, context: ExecutionContext) -> Any:
        """解析绑定项目（配置 project_id → 上游输出 project_id）。"""
        from initiatives.models import Project

        pid = context.render_template(config.get("project_id", "") or "").strip()
        if not pid:
            upstream = context.get_input("project_id")
            pid = str(upstream).strip() if upstream else ""
        if not pid:
            return None
        try:
            uuid_mod.UUID(pid)
        except ValueError:
            return None
        return await Project.objects.filter(id=pid).afirst()

    async def _ai_branch_name(self, config: dict, context: ExecutionContext) -> str:
        """从方案/需求文本经 AI 生成规范分支名（best-effort，失败返回空）。"""
        text = context.render_template(config.get("plan_text", "") or "").strip()
        if not text:
            for key in ("plan_markdown", "plan", "requirement_text"):
                val = context.get_input(key)
                if isinstance(val, str) and val.strip():
                    text = val.strip()
                    break
        if not text:
            return ""
        try:
            from chat.branch_service import agenerate_default_branch_name

            branch_name, _btype, _desc = await agenerate_default_branch_name(text)
            return (branch_name or "").strip()
        except Exception as exc:  # noqa: BLE001 — AI 生成失败 fail-soft，返回空交由上层报错
            logger.warning(
                "ai_create_branch_name_failed",
                node_id=context.node_id,
                error=str(exc),
            )
            return ""
