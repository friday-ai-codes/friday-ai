"""McpCodingPlan → tech_plan 事件 normalizer（Phase 100 / KNOW-03）。

kind 复用既有值 ``tech_plan``（locked decision：kind 按内容归类、来源经
source_kind 区分）；natural key：``mcp_coding_plan`` → source_id =
``str(McpCodingPlan.id)``。与 chat ``coding_plan`` 保持**不同实体 + 边显式
关联**（RELATES_TO），不做硬去重（STATE 定版）。

事件结构：

- 主事件（tech_plan）：content 取**最新** ``McpCodingPlanVersion`` 的 markdown
  组装；出边 a. ``REFERENCES`` → mcp_repository_analysis 实体（analysis_id 非空时）；
  b. ``RELATES_TO`` → chat coding_plan 实体（best-effort：经 McpWorkItemRepoTask
  反查 work_item 三元组，再查与同一 work_item 锚有活跃边的 chat 方案实体，
  任一环节缺料静默跳过——无 work_item 挂载是常态，不 warning 刷屏）。
- work_item 锚双事件（三元组齐备时）：照抄 mcp_plan.py 锚构造
  （``feishu_work_item`` source_kind + 三元组 source_id + 轻量锚 content）。

**锚边禁用 HAS_PLAN 的决策存档（T-100-07）**：HAS_PLAN 是 exclusive 单方案语义
（mcp_plan.py 的 work_item —HAS_PLAN→ mcp_technical_plan 出边带
``exclusive=True``），若此处复用 HAS_PLAN，重摄取会把 work_item 既有的
HAS_PLAN→mcp_technical_plan 活跃边逐条 invalidate（apply_edge_specs exclusive
分支）——等于 MCP 编码方案入图悄悄打失效技术方案关联。故锚出边强制
``RELATES_TO``（非排他），与既有 HAS_PLAN 边共存。

``build_plan_event`` 是公开纯构造函数：mcp_execution_trace.py 的 plan 锚事件
**必须复用它**（task_result.py L229「锚事件短路重摄同源拼法」纪律——content
逐字节一致才不会两个 normalizer 互相翻版本 ping-pong）。
"""

from __future__ import annotations

import json

import structlog
from django.db.models import Q

from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import (
    EdgeRelation,
    EntityKind,
    EntityOrigin,
    KnowledgeEdge,
    generate_entity_id,
)

logger = structlog.get_logger(__name__)

__all__ = ["build_plan_event", "normalize"]


def _format_items(items: object) -> str:
    """JSON 列表 → markdown 列表（dict 走确定性 JSON，保证 content 逐字节稳定）。"""
    lines: list[str] = []
    for item in items if isinstance(items, list) else []:
        text = (
            item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, sort_keys=True)
        )
        lines.append(f"- {text}")
    return "\n".join(lines) if lines else "（无）"


def build_plan_event(
    plan,
    version,
    *,
    edges: tuple[EdgeSpec, ...] = (),
    space_id: str | None = None,
) -> IngestionEvent:
    """McpCodingPlan + 最新 McpCodingPlanVersion → tech_plan IngestionEvent 纯构造。

    同源拼法纪律：mcp_execution_trace.py 的 plan 锚事件复用本函数，content
    逐字节一致 → 重摄走 hash 短路，不翻版本。素材版本由调用方查好传入
    （normalize 与 trace 锚都取 ``plan.versions.order_by("-version").afirst()``）。

    ``space_id``（quick-260726-q3z D-03）：work_item 可解析且 technical_plan 带
    space 时由调用方传入；不参与 content/hash（byte-equal 守护恒绿），仅进
    IngestionEvent.space_id 供权限面可见性使用。
    """
    content = (
        f"# {plan.title}\n\n"
        f"## 需求\n{plan.requirement}\n\n"
        f"## 步骤\n{_format_items(version.steps)}\n\n"
        f"## 测试计划\n{_format_items(version.test_plan)}\n\n"
        f"## 风险\n{_format_items(version.risks)}"
    )
    return IngestionEvent(
        kind=EntityKind.TECH_PLAN,
        origin=EntityOrigin.MCP,
        source_kind="mcp_coding_plan",
        source_id=str(plan.id),
        title=plan.title,
        content=content,
        payload={
            "requirement": plan.requirement[:500],
            "affected_files": version.affected_files,
            "version": version.version,
            "repository_id": str(plan.repository_id),
            "branch": plan.branch,
            "status": plan.status,
            "analysis_id": str(plan.analysis_id) if plan.analysis_id else "",
        },
        space_id=space_id,
        repository_id=str(plan.repository_id),
        # updated_at 而非 created_at：版本翻转要求 invalid_at 严格大于旧版 valid_at
        # （kversion_valid_range CHECK）；improve 路径 plan.asave(update_fields=[...,
        # "updated_at"]) 会推进 auto_now，created_at 永不推进会使重摄翻版被拒并被吞成
        # knowledge_ingest_concurrent_conflict（learning_case.py 同款纪律）。
        # 本函数是锚同源拼法的共享构造（mcp_execution_trace 锚复用），在此统一修。
        event_time=plan.updated_at,
        edges=edges,
    )


async def _resolve_work_item(plan_id) -> tuple[str, object, object] | None:
    """经 McpWorkItemRepoTask 反查 work_item 三元组（缺料返回 None，静默）。

    Returns:
        (三元组 source_id, technical_plan, context) 或 None。
    """
    from mcp_tools.models import McpWorkItemRepoTask

    task = (
        await McpWorkItemRepoTask.objects.filter(coding_plan_id=plan_id)
        .select_related("technical_plan", "technical_plan__context")
        .order_by("created_at")
        .afirst()
    )
    if task is None:
        return None
    tp = task.technical_plan
    if not (tp.feishu_project_key and tp.work_item_type and tp.work_item_id):
        return None
    context = tp.context
    if context is None:
        return None
    triple = f"{tp.feishu_project_key}:{tp.work_item_type}:{tp.work_item_id}"
    return triple, tp, context


async def _chat_plan_relates_edges(triple: str) -> list[EdgeSpec]:
    """反查与同一 work_item 锚有活跃边的 chat coding_plan 实体 → RELATES_TO 出边。

    best-effort（locked：「如可反查到同 work_item」）：锚实体未入图 /
    无 chat 方案关联时返回空列表，不 warning（常态）。
    """
    anchor_id = generate_entity_id("work_item", "feishu_work_item", triple)
    chat_filter = {"kind": EntityKind.TECH_PLAN, "source_kind": "coding_plan"}
    linked: set = set()
    async for edge in KnowledgeEdge.objects.filter(
        invalid_at__isnull=True, expired_at__isnull=True
    ).filter(
        Q(
            source_entity_id=anchor_id,
            target_entity__kind=chat_filter["kind"],
            target_entity__source_kind=chat_filter["source_kind"],
        )
        | Q(
            target_entity_id=anchor_id,
            source_entity__kind=chat_filter["kind"],
            source_entity__source_kind=chat_filter["source_kind"],
        )
    ):
        linked.add(
            edge.target_entity_id if edge.source_entity_id == anchor_id else edge.source_entity_id
        )
    return [
        EdgeSpec(relation=EdgeRelation.RELATES_TO, target_entity_id=entity_id)
        for entity_id in sorted(linked, key=str)
    ]


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """McpCodingPlan → [work_item 锚, tech_plan] 双事件；锚缺料降级单事件。"""
    from mcp_tools.models import McpCodingPlan

    plan = (
        await McpCodingPlan.objects.select_related("repository")
        .filter(id=request.source_id)
        .afirst()
    )
    if plan is None:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            component="knowledge",
            category="sampling",
        )
        return []
    version = await plan.versions.order_by("-version").afirst()
    if version is None:
        logger.warning(
            "knowledge_normalize_plan_version_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            component="knowledge",
            category="sampling",
        )
        return []

    edges: list[EdgeSpec] = []
    if plan.analysis_id:
        edges.append(
            EdgeSpec(
                relation=EdgeRelation.REFERENCES,
                target_entity_id=generate_entity_id(
                    "document", "mcp_repository_analysis", str(plan.analysis_id)
                ),
            )
        )
    resolved = await _resolve_work_item(plan.id)
    if resolved is not None:
        edges.extend(await _chat_plan_relates_edges(resolved[0]))

    # D-03（quick-260726-q3z）：work_item 可解析且 technical_plan 带 space 时，主事件
    # 携带 space_id（与锚事件同款来源）；space_id 不进 content/hash，重摄零翻版。
    plan_space_id: str | None = None
    if resolved is not None and resolved[1].space_id:
        plan_space_id = str(resolved[1].space_id)

    plan_event = build_plan_event(plan, version, edges=tuple(edges), space_id=plan_space_id)
    if resolved is None:
        return [plan_event]

    triple, tp, context = resolved
    work_item_event = IngestionEvent(
        kind=EntityKind.WORK_ITEM,
        origin=EntityOrigin.MCP,
        # 锚构造照抄 mcp_plan.py（同 natural key 同源拼法：content 逐字节一致不翻版本）
        source_kind="feishu_work_item",
        source_id=triple,
        title=context.name,
        content=f"{context.name}\n\n{context.description or ''}",
        payload={
            "name": context.name,
            "work_item_status": context.work_item_status,
            "feishu_project_key": tp.feishu_project_key,
            "work_item_type": tp.work_item_type,
            "work_item_id": tp.work_item_id,
        },
        space_id=str(tp.space_id) if tp.space_id else None,
        repository_id=None,
        # 同 build_plan_event：updated_at 随内容变更推进，锚 content（context.name/
        # description）变化时翻版不撞 kversion_valid_range CHECK。
        event_time=plan.updated_at,
        edges=(
            # 禁用 HAS_PLAN：exclusive 语义会打失效既有 HAS_PLAN→mcp_technical_plan
            # 活跃边（模块 docstring 决策存档，T-100-07）；RELATES_TO 非排他，安全共存。
            EdgeSpec(
                relation=EdgeRelation.RELATES_TO,
                target_entity_id=generate_entity_id("tech_plan", "mcp_coding_plan", str(plan.id)),
            ),
        ),
    )
    return [work_item_event, plan_event]
