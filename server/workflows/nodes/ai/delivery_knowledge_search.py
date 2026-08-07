"""交付知识检索 workflow 节点（Phase 16-03 EXPO-02）。"""

from __future__ import annotations

from typing import Any

import structlog

from knowledge.exposure import format_search_results_markdown, parse_as_of, serialize_search_results
from knowledge.retrieval import DeliveryKnowledgeSearchService
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

_service = DeliveryKnowledgeSearchService()


async def _get_workflow_user(context: ExecutionContext):
    if context.workflow_execution is None:
        return None
    from workflows.models import WorkflowExecution

    we = await WorkflowExecution.objects.select_related("triggered_by").aget(
        id=context.workflow_execution.id
    )
    return we.triggered_by


@register_node
class DeliveryKnowledgeSearchNode(BaseNode):
    """检索相似历史交付并输出 markdown 上下文。"""

    node_type = "delivery_knowledge_search"
    display_name = "交付知识检索"
    description = "检索相似历史需求/方案/代码变更，注入下游节点"
    icon = "search"
    category = NodeCategory.AI
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "title": "检索 query",
                "description": "支持模板变量，如 {{global.requirement_text}}",
            },
            "top_k": {
                "type": "integer",
                "title": "返回数量",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
            },
            "project_ids": {
                "type": "array",
                "title": "项目范围",
                "items": {"type": "string"},
                "default": [],
            },
            "repository_ids": {
                "type": "array",
                "title": "仓库范围",
                "items": {"type": "string"},
                "default": [],
            },
            "entity_kinds": {
                "type": "array",
                "title": "实体类型",
                "items": {"type": "string"},
                "default": [],
            },
            "as_of": {
                "type": "string",
                "title": "历史时点",
                "description": "ISO8601 可选",
                "default": "",
            },
            "include_superseded": {
                "type": "boolean",
                "title": "含已取代版本",
                "default": False,
            },
        },
        "required": ["query"],
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT, required=False)]
    outputs = [
        NodePort(
            name="default",
            label="检索结果",
            port_type=PortType.OBJECT,
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "total": {"type": "integer"},
                    "formatted_context": {"type": "string"},
                    "results": {"type": "array"},
                },
            },
        ),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config
        query = context.render_template(config.get("query", "")).strip()
        if not query:
            return NodeResult(
                status="failed",
                error="检索 query 不能为空",
                next_handle="error",
            )

        user = await _get_workflow_user(context)
        if user is None:
            return NodeResult(
                status="completed",
                output={
                    "query": query,
                    "total": 0,
                    "formatted_context": "",
                    "results": [],
                },
                next_handle="default",
            )

        try:
            as_of_raw = context.render_template(config.get("as_of", "") or "")
            as_of = parse_as_of(as_of_raw or None)
        except ValueError as exc:
            return NodeResult(status="failed", error=str(exc), next_handle="error")

        project_ids = [str(p) for p in config.get("project_ids") or []] or None
        repository_ids = [str(r) for r in config.get("repository_ids") or []] or None
        entity_kinds = [str(k) for k in config.get("entity_kinds") or []] or None
        top_k = int(config.get("top_k") or 5)

        try:
            results = await _service.search_similar(
                query,
                user=user,
                top_k=top_k,
                project_ids=project_ids,
                repository_ids=repository_ids,
                entity_kinds=entity_kinds,
                as_of=as_of,
                include_superseded=bool(config.get("include_superseded")),
                # KDEP-02 同款取舍：工件/物化文档/上线记录是 kind=document 实体，
                # 不开此 flag 在本节点永远召不回。权限不放宽。
                include_document_kind=True,
            )
            serialized = serialize_search_results(results)
            formatted = format_search_results_markdown(results, as_of=as_of)
            return NodeResult(
                status="completed",
                output={
                    "query": query,
                    "total": len(serialized),
                    "formatted_context": formatted,
                    "results": serialized,
                },
                next_handle="default",
            )
        except Exception as exc:
            logger.warning("knowledge_workflow_search_failed", error=str(exc))
            return NodeResult(
                status="completed",
                output={
                    "query": query,
                    "total": 0,
                    "formatted_context": "",
                    "results": [],
                },
                next_handle="default",
            )
