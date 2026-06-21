"""workflow NodeExecution → [work_item 锚, tech_plan] 双事件 normalizer（Plan 14-04 / INGEST-01）。

source_id 恒为生成节点 key ``{execution_id}:{node_id}``（OQ-2 规划定案）：审批触发
（trigger="workflow_plan_approved"）同样以生成节点 key 重摄同一 tech_plan 实体，
key 换算由审批接线处（scheduler.approve_node）完成，normalizer 保持单纯不做节点回溯。

- tech_plan 实体：content 取生成节点 output_data["plan"]（title/summary/execution_plan
  的 markdown 拼接，``##`` 分段契合既有 chunker）；审批触发时在 content 尾部追加
  审批段落（Pitfall 5 locked：审批信息必须进 content——hash 变化才产生新版本，
  只写 payload 会被 content_hash 短路吞掉），event_time 改取 approved_at（aware 化）。
- work_item 锚实体：trigger_data 飞书 payload（id + work_item_type_key）与
  project.feishu_project_key 三者齐备才建锚（T-14-14：缺任一退 tech_plan 单事件 +
  warning），三元组 source_id 与 natural key 规则表逐字一致；HAS_PLAN exclusive
  出边目标 id 经 ``generate_entity_id`` 唯一入口派生。

事件顺序锁定：work_item 锚在前（mcp_plan.py 同款）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import structlog
from django.utils import timezone

from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin, generate_entity_id

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]


def _parse_source_id(source_id: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """解析 ``{execution_id}:{node_id}``；任一段非 UUID 返回 None（畸形输入防御）。"""
    execution_part, sep, node_part = source_id.rpartition(":")
    if not sep or not execution_part:
        return None
    try:
        return uuid.UUID(execution_part), uuid.UUID(node_part)
    except ValueError:
        return None


def _aware(value: datetime | None) -> datetime | None:
    """naive datetime 补当前时区（graph_store ``require_aware`` 防线前置）。"""
    if value is None:
        return None
    return timezone.make_aware(value) if timezone.is_naive(value) else value


def _parse_approved_at(raw: str) -> datetime | None:
    """isoformat 审批时间 → aware datetime；解析失败返回 None（占位降级）。"""
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return _aware(parsed)


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """workflow 方案（生成/审批两形态）→ 双事件；源缺失返回空列表，锚缺料只产出 tech_plan。"""
    from workflows.models.execution import NodeExecution, NodeExecutionStatus

    parsed = _parse_source_id(request.source_id)
    if parsed is None:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []
    execution_id, node_id = parsed

    node_execution = (
        await NodeExecution.objects.select_related(
            "workflow_execution",
            "workflow_execution__workflow",
            "workflow_execution__project",
            "node",
        )
        .filter(
            workflow_execution_id=execution_id,
            node_id=node_id,
            status=NodeExecutionStatus.COMPLETED,
        )
        .afirst()
    )
    plan = (node_execution.output_data or {}).get("plan") if node_execution else None
    if node_execution is None or not isinstance(plan, dict):
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []

    execution = node_execution.workflow_execution
    project = execution.project
    # T-14-13：project_id 恒从 execution 关联 project 取；无 project 时显式 None
    project_id = str(execution.project_id) if execution.project_id else None

    title = str(plan.get("title") or "技术方案")
    summary = str(plan.get("summary") or "")
    execution_plan = plan.get("execution_plan") or []
    if isinstance(execution_plan, str):
        execution_plan_text = execution_plan
    else:
        execution_plan_text = json.dumps(execution_plan, ensure_ascii=False, indent=2)
    content = f"# {title}\n\n## 摘要\n{summary}\n\n## 执行计划\n{execution_plan_text}"
    event_time = _aware(node_execution.completed_at) or timezone.now()
    payload: dict = {
        "title": title,
        "execution_id": str(execution_id),
        "node_id": str(node_id),
    }

    if request.trigger == "workflow_plan_approved":
        approval_execution = (
            await NodeExecution.objects.filter(
                workflow_execution_id=execution_id,
                node__node_type="human_approval",
                status=NodeExecutionStatus.COMPLETED,
            )
            .order_by("-completed_at")
            .afirst()
        )
        approval_data = (approval_execution.approval_data or {}) if approval_execution else {}
        # 缺失字段用占位（防 KeyError）；审批段进 content 是 Pitfall 5 的快照语义防线
        approver_name = approval_data.get("approver_name") or "未知审批人"
        approved_at_raw = approval_data.get("approved_at") or ""
        content += f"\n\n## 审批\n已通过 by {approver_name} at {approved_at_raw or '未知时间'}"
        document_url = approval_data.get("document_url")
        if document_url:
            payload["document_url"] = document_url
        approved_at = _parse_approved_at(approved_at_raw)
        if approved_at is not None:
            event_time = approved_at

    tech_plan_event = IngestionEvent(
        kind=EntityKind.TECH_PLAN,
        origin=EntityOrigin.WORKFLOW,
        source_kind="workflow_plan",
        source_id=request.source_id,
        title=title,
        content=content,
        payload=payload,
        project_id=project_id,
        repository_id=None,
        event_time=event_time,
    )

    trigger_data = execution.trigger_data or {}
    feishu_payload = trigger_data.get("raw_payload") or trigger_data.get("payload") or {}
    if not isinstance(feishu_payload, dict):
        feishu_payload = {}
    work_item_id = feishu_payload.get("id")
    work_item_type = feishu_payload.get("work_item_type_key")
    feishu_project_key = project.feishu_project_key if project else ""
    if not (work_item_id and work_item_type and feishu_project_key):
        # 防御（T-14-14）：手动触发 / payload 畸形——三字段齐备才建锚，缺锚不拖垮方案入图
        logger.warning(
            "knowledge_normalize_anchor_payload_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return [tech_plan_event]

    work_item_name = str(feishu_payload.get("name") or f"工作项 {work_item_id}")
    work_item_event = IngestionEvent(
        kind=EntityKind.WORK_ITEM,
        origin=EntityOrigin.WORKFLOW,
        source_kind="feishu_work_item",
        # natural key 规则表（knowledge/models.py generate_entity_id docstring）锁定格式
        source_id=f"{feishu_project_key}:{work_item_type}:{work_item_id}",
        title=work_item_name,
        content=work_item_name,
        payload={
            "name": work_item_name,
            "feishu_project_key": feishu_project_key,
            "work_item_type": work_item_type,
            "work_item_id": work_item_id,
        },
        project_id=project_id,
        repository_id=None,
        event_time=event_time,
        edges=(
            EdgeSpec(
                relation=EdgeRelation.HAS_PLAN,
                target_entity_id=generate_entity_id(
                    "tech_plan", "workflow_plan", request.source_id
                ),
                exclusive=True,
            ),
        ),
    )
    return [work_item_event, tech_plan_event]
