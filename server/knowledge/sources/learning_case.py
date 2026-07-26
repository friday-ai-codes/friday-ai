"""McpLearningCase → [work_item 锚, learning_case] 双事件 normalizer（Phase 100 / KNOW-01）。

- learning_case 主实体：content 取 ``embedding_text``（向量文本主料，提炼产物），
  为空时回退 markdown 组装（title/problem/root_cause/solution/outcome + 列表拼接）；
  payload 为摘要不复制全文（task_result.py T-14-24 同款纪律）；
- work_item 锚实体：source_id 按 natural key 规则表锁定的三元组拼接
  ``{feishu_project_key}:{work_item_type}:{work_item_id}``（mcp_plan.py 同款，
  禁止自造锚格式），content 为轻量锚（name + description）；
- work_item —RELATES_TO→ learning_case 出边挂锚事件（**非 exclusive**：一个
  work_item 可关联多条案例，与 HAS_PLAN 单方案语义不同）；
- learning_case —REFERENCES→ tech_plan（mcp_technical_plan 实体）出边挂主事件，
  目标 id 经 ``generate_entity_id`` 唯一入口派生（目标实体由 mcp_plan.py
  normalizer 负责入图，边阶段幂等，两端实体不齐时写入失败仅 warning 不 raise）。

事件顺序锁定：work_item 锚在前（mcp_plan.py 事件顺序约定）；
锚料任一缺失（context 为 None / feishu_project_key / work_item_type /
work_item_id 缺失）→ 降级单事件，learning_case 实体仍入图不报错。
"""

from __future__ import annotations

import structlog

from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin, generate_entity_id

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]


def _fallback_content(case) -> str:
    """embedding_text 为空时的 markdown 组装回退（Claude's Discretion 定案格式）。"""
    sections = [
        f"# {case.title}",
        f"## 问题\n{case.problem}",
        f"## 根因\n{case.root_cause}",
        f"## 解法\n{case.solution}",
        f"## 结果\n{case.outcome}",
    ]
    if case.repositories:
        sections.append("## 仓库\n" + "\n".join(f"- {item}" for item in case.repositories))
    if case.files:
        sections.append("## 文件\n" + "\n".join(f"- {item}" for item in case.files))
    if case.tests:
        sections.append("## 测试\n" + "\n".join(f"- {item}" for item in case.tests))
    return "\n\n".join(sections)


async def _resolve_single_repository_id(case) -> str | None:
    """双 None 单仓回填（quick-260726-q3z D-04）：repositories 恰 1 名称且该名称在
    Repository 表恰好匹配 1 行时返回其 id，否则 None。

    repositories 字段是**仓库名称列表**（learning_case_service 取 task.repository.name，
    Repository.name 无唯一约束）——名称撞行（≥2 行）视为不可唯一解析，不回填。
    """
    repositories = case.repositories if isinstance(case.repositories, list) else []
    if len(repositories) != 1:
        return None
    from repositories.models import Repository

    matches = [
        str(rid)
        async for rid in Repository.objects.filter(name=repositories[0]).values_list(
            "id", flat=True
        )[:2]
    ]
    if len(matches) != 1:
        return None
    return matches[0]


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """McpLearningCase → 双事件；源缺失返回空列表，锚缺料只产出 learning_case。"""
    from mcp_tools.models import McpLearningCase

    case = (
        await McpLearningCase.objects.select_related("context", "technical_plan")
        .filter(id=request.source_id)
        .afirst()
    )
    if case is None:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            component="knowledge",
            category="sampling",
        )
        return []

    context = case.context
    if context is not None and context.space_id:
        space_id = str(context.space_id)
    elif case.technical_plan is not None and case.technical_plan.space_id:
        space_id = str(case.technical_plan.space_id)
    else:
        space_id = None

    # D-04（quick-260726-q3z）：仅 space_id is None（双 None，现状永不可召回）时尝试
    # 单仓回填 repository_id——吃向量召回 project 闸的可见仓库逃生口（D-01），只增不减。
    # **space_id 非 None 时绝不回填**：space 已有的案例靠 demand 分路空串支对「可见项目
    # 但不可见该仓库」的用户可见，回填真实 repo id 会反把这类用户挡掉（回归陷阱）。
    # 存量说明：既有实体的 space_id/repository_id 不会自动更新（_persist_sync 更新分支
    # 只动 title/event_time/current_version，勿改——通用行为变更超出本次范围）；双 None
    # 存量向量点按 D-04 接受现状，仅保证增量正确 + warning 可见，无需 rebuild/迁移。
    repository_id: str | None = None
    if space_id is None:
        repository_id = await _resolve_single_repository_id(case)
        if repository_id is None:
            repositories = case.repositories if isinstance(case.repositories, list) else []
            logger.warning(
                "knowledge_normalize_unanchored",
                source_kind=request.source_kind,
                source_id=request.source_id,
                trigger=request.trigger,
                repositories_count=len(repositories),
                component="knowledge",
                category="sampling",
            )

    edges: tuple[EdgeSpec, ...] = ()
    if case.technical_plan_id:
        # REQUIREMENTS KNOW-01：learning_case —REFERENCES→ tech_plan（mcp_technical_plan）。
        # 目标实体由 mcp_plan.py normalizer 负责入图；边阶段（ingest_events 阶段 B）幂等，
        # 目标未入图时该边写入失败仅 warning 不 raise（先建边后补实体，task_result.py 同款语义）。
        edges = (
            EdgeSpec(
                relation=EdgeRelation.REFERENCES,
                target_entity_id=generate_entity_id(
                    "tech_plan", "mcp_technical_plan", str(case.technical_plan_id)
                ),
            ),
        )

    learning_case_event = IngestionEvent(
        kind=EntityKind.LEARNING_CASE,
        origin=EntityOrigin.MCP,
        source_kind="learning_case",
        source_id=str(case.id),
        title=case.title,
        content=case.embedding_text or _fallback_content(case),
        payload={
            "work_item_type": case.work_item_type,
            "work_item_id": case.work_item_id,
            "outcome": case.outcome,
            "repositories": case.repositories,
            "files": case.files,
            "symbols": case.symbols,
            "mr_urls": case.mr_urls,
            "technical_plan_id": str(case.technical_plan_id) if case.technical_plan_id else "",
        },
        space_id=space_id,
        repository_id=repository_id,  # 案例跨仓不绑单仓；仅双 None 单仓可解析时回填（D-04）
        # updated_at 而非 created_at：版本翻转要求 invalid_at 严格大于旧版 valid_at
        # （kversion_valid_range CHECK），created_at 不随内容变更推进会使重摄翻版被拒
        # （coding_plan.py 用 updated_at 同款先例）。
        event_time=case.updated_at,
        edges=edges,
    )

    # 锚料判定：context 非 None 且 feishu_project_key / work_item_type / work_item_id 三者齐备
    if context is None or not (
        context.feishu_project_key and case.work_item_type and case.work_item_id
    ):
        logger.warning(
            "knowledge_normalize_anchor_context_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            component="knowledge",
            category="sampling",
        )
        return [learning_case_event]

    work_item_event = IngestionEvent(
        kind=EntityKind.WORK_ITEM,
        origin=EntityOrigin.MCP,
        source_kind="feishu_work_item",
        # natural key 规则表（knowledge/models.py generate_entity_id docstring）锁定格式
        source_id=f"{context.feishu_project_key}:{case.work_item_type}:{case.work_item_id}",
        title=context.name,
        content=f"{context.name}\n\n{context.description or ''}",
        payload={
            "name": context.name,
            "work_item_status": context.work_item_status,
            "feishu_project_key": context.feishu_project_key,
            "work_item_type": case.work_item_type,
            "work_item_id": case.work_item_id,
        },
        space_id=space_id,
        repository_id=None,
        event_time=case.updated_at,
        edges=(
            EdgeSpec(
                relation=EdgeRelation.RELATES_TO,
                target_entity_id=generate_entity_id("learning_case", "learning_case", str(case.id)),
                # 非 exclusive：一个 work_item 可关联多条案例（与 HAS_PLAN 单方案语义不同）
            ),
        ),
    )
    return [work_item_event, learning_case_event]
