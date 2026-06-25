"""飞书文档（PRD/技术方案 docx）→ 操作态 Document + knowledge document 投影 normalizer
（Plan 30-03 / DOC-02）。

source_id 与 ``feishu_work_item`` 同锚——natural key 规则表锁定的工作项三元组
``{project_key}:{work_item_type}:{work_item_id}``：本 normalizer 经三元组定位工作项
及其 ``prd_url`` / ``tech_doc_url``，从中提取飞书 doc token（复用
``_extract_doc_token``），经既有 ``create_feishu_doc_client_for_project`` +
``get_document_content`` 拉正文（不重写取材路径）。

产出两层（INV-3 双层并存）：

- **操作态** ``Document`` / ``DocumentVersion``——经 30-02 ``DocumentService``
  单一写入入口（INV-6）+ ``work_item`` FK 关联；
- **knowledge 投影** ``KnowledgeEntity(kind=document)`` + ``KnowledgeEdge(REFERENCES)``
  连 work_item 实体 → document 实体（方向 work_item→document，与 mcp_plan
  HAS_PLAN 双事件出边范式一致）。

work_item 锚事件复用 ``feishu_work_item.normalize`` 产出（content 逐字一致、hash
相等不翻版本），既有 work_item 全量快照不被本 normalizer clobber（INV-3）；
``feishu_work_item.py`` 不修改。

降级语义（§1.4 / 复用 ``_fetch_doc_body`` 降配）：doc 拉取失败 → 正文空串 + warning，
Document/实体仍建（缺段不缺实体），不抛、不回滚；操作态写入异常仅 warning，不阻断
knowledge 投影产出。

凭证只经 ``create_feishu_doc_client_for_project`` 既有 service 层（DB 加密凭证，零 env）。
"""

from __future__ import annotations

import dataclasses

import structlog

from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project
from delivery.services import DocumentService, derive_feishu_tenant
from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin, generate_entity_id
from knowledge.sources import feishu_work_item
from knowledge.sources.feishu_work_item import _extract_doc_token, _fetch_doc_body

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]

# document_type → (payload 字段名, 中文 label) —— 与 DocumentType / SyncFacet 映射对齐
_DOC_TYPES = (
    ("prd", "prd_url", "PRD"),
    ("tech_plan", "tech_doc_url", "技术方案"),
)


def _doc_title(body: str, fallback: str) -> str:
    """取文档首个 markdown 标题作 title；缺正文降级用 fallback（work_item 名 + 文档类型）。"""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:500]
        return stripped[:500]
    return fallback[:500]


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """飞书工作项三元组 → [work_item 锚（携 REFERENCES 出边）, *document 事件]。

    源缺失 / 无文档 token → 复用 work_item 锚事件原样返回（缺段不缺实体）；
    doc 拉取失败降级正文空串，document 实体与 REFERENCES 边照常产出。
    """
    from projects.models import Space

    parts = request.source_id.split(":", 2)
    if len(parts) != 3 or not all(parts):
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []
    project_key, work_item_type, work_item_id_raw = parts

    project = await Space.objects.filter(feishu_project_key=project_key).afirst()
    if project is None:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []

    # work_item 锚事件复用既有产出（content 逐字一致，hash 相等不 clobber 既有快照，INV-3）。
    wi_events = await feishu_work_item.normalize(request)
    if not wi_events:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []
    wi_event = wi_events[0]

    # doc token 取自 work_item 锚事件 payload 内的 prd_url / tech_doc_url 字面值（不重复 get_work_item）。
    targets: list[tuple[str, str, str]] = []  # (document_type, token, canonical_url)
    for document_type, payload_key, _label in _DOC_TYPES:
        canonical_url = str(wi_event.payload.get(payload_key) or "")
        token = _extract_doc_token(canonical_url)
        if token:
            targets.append((document_type, token, canonical_url))

    if not targets:
        # 无文档：work_item 锚事件原样返回（事件照常，缺段不缺实体）。
        return list(wi_events)

    doc_client = None
    try:
        doc_client = await create_feishu_doc_client_for_project(project)
    except Exception as exc:
        logger.warning(
            "knowledge_normalize_doc_client_unavailable",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            error=str(exc),
            error_type=type(exc).__name__,
        )

    # 操作态落库定位：已落库的 delivery WorkItem（缺则 None 占位，缺脊柱不缺文档实体）。
    work_item_obj = await _resolve_work_item(project_key, work_item_type, work_item_id_raw)

    label_by_type = {dt: lbl for dt, _key, lbl in _DOC_TYPES}
    document_events: list[IngestionEvent] = []
    reference_edges: list[EdgeSpec] = []

    for document_type, token, canonical_url in targets:
        label = label_by_type[document_type]
        body = await _fetch_doc_body(doc_client, token, request=request, label=label)
        tenant = derive_feishu_tenant(canonical_url)

        # 操作态写入（INV-6 单一入口）：异常仅 warning，不阻断 knowledge 投影（降级不回滚）。
        try:
            await DocumentService().upsert_from_feishu(
                work_item=work_item_obj,
                document_type=document_type,
                doc_token=token,
                content=body,
                canonical_url=canonical_url,
                feishu_tenant=tenant,
                source="manual",
            )
        except Exception as exc:
            logger.warning(
                "knowledge_normalize_document_upsert_failed",
                source_kind=request.source_kind,
                source_id=request.source_id,
                trigger=request.trigger,
                document_type=document_type,
                doc_token=token,
                error=str(exc),
                error_type=type(exc).__name__,
            )

        document_events.append(
            IngestionEvent(
                kind=EntityKind.DOCUMENT,
                origin=EntityOrigin.FEISHU,
                source_kind="feishu_document",
                source_id=token,
                title=_doc_title(body, f"{wi_event.title}·{label}"),
                content=body,
                payload={
                    "document_type": document_type,
                    "project_key": project_key,
                    "work_item_type": work_item_type,
                    "work_item_id": work_item_id_raw,
                    "canonical_url": canonical_url,
                    "feishu_tenant": tenant,
                },
                space_id=str(project.id),
                repository_id=None,
                event_time=wi_event.event_time,
            )
        )
        reference_edges.append(
            EdgeSpec(
                relation=EdgeRelation.REFERENCES,
                target_entity_id=generate_entity_id("document", "feishu_document", token),
            )
        )

    # REFERENCES 出边挂到 work_item 锚事件（frozen dataclass → replace）；
    # 顺序不限：ingest_events 先持久化全部实体再统一处理边（两端实体保证已存在）。
    wi_event_with_edges = dataclasses.replace(wi_event, edges=(*wi_event.edges, *reference_edges))
    return [wi_event_with_edges, *document_events]


async def _resolve_work_item(project_key: str, work_item_type: str, work_item_id_raw: str):
    """定位已落库的 delivery WorkItem（缺则 None；非法 id 不抛）。"""
    from delivery.models import WorkItem

    try:
        work_item_id = int(work_item_id_raw)
    except (TypeError, ValueError):
        return None
    return await WorkItem.objects.filter(
        feishu_project_key=project_key,
        work_item_type=work_item_type,
        work_item_id=work_item_id,
    ).afirst()
