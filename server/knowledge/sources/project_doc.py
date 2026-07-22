"""项目工作区 5 文件正文 → knowledge document 投影 normalizer（CTX-01/02）。

镜像 ``sources/artifact.py`` 范式：把 ``ProjectDoc``（DOC-01~05 五文件）的最近同步快照正文
（``last_synced_snapshot``）全文摄取进 ``delivery_knowledge``——产 ``KnowledgeEntity(kind=
document, source_kind="project_doc")`` + ``文件→REFERENCES→项目图谱节点`` 出边（KLINK-01：
项目↔知识；可索引 + 关联扩充）。

「项目上下文逻辑隔离」口径（A1 锁定）：复用既有 ``delivery_knowledge`` collection（与 per-repo
代码 RAG collection 物理分离），用新 ``source_kind="project_doc"`` + 既有 ``EntityKind.DOCUMENT``
做逻辑隔离；visibility 隔离由 ``space_id`` 维度承载，读侧（Plan 02）按项目 visibility 过滤召回。

降级语义（fail-soft，缺段不缺实体）：
- 文件不存在 → 返回空列表（warning，绝不抛）；
- 正文（``last_synced_snapshot``）为空 → 正文空串 + warning，实体与边照常产出（不抛、不阻断写）。

**脱敏不可绕过**：正文经 ``redact_secrets_in_text`` 脱敏后才入图。
观测：``project_doc_rag_normalize_started/completed`` + ``duration_ms`` + 正文长度 + 事件数
（category=sampling, component=knowledge）；日志只记 id/计数/长度，绝不记正文。
"""

from __future__ import annotations

import time

import structlog

from common.logging import redact_secrets_in_text
from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]


def _doc_title(body: str, fallback: str) -> str:
    """取正文首个 markdown 标题作 title；缺正文降级用 fallback（镜像 artifact source）。"""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:500]
        return stripped[:500]
    return fallback[:500]


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """ProjectDoc UUID → 单 document 事件（携 REFERENCES→项目节点 出边）；文件不存在返回空。

    KNOW-06（Phase 102）：STATE 类型文档在 snapshot 正文之外追加 live「API 清单」内容
    （``METHOD path — status`` 行，直查 ``ProjectStateApi`` 表）——API 行只存在于表 +
    飞书系统区、不在 ``last_synced_snapshot`` 里，这是 ProjectStateApi 不可检索的断链根因。
    非 STATE 文档行为逐字不变。
    """
    from initiatives.models import DocType, ProjectDoc, ProjectStateApi
    from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService

    started = time.perf_counter()
    logger.info(
        "project_doc_rag_normalize_started",
        source_id=request.source_id,
        trigger=request.trigger,
        component="knowledge",
        category="sampling",
    )

    doc = (
        await ProjectDoc.objects.select_related("project", "project__space")
        .filter(id=request.source_id)
        .afirst()
    )
    if doc is None:
        logger.warning(
            "project_doc_rag_source_missing",
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []

    project = doc.project
    raw_body = doc.last_synced_snapshot or ""
    if not raw_body:
        logger.warning(
            "project_doc_rag_empty_body",
            doc_id=str(doc.id),
            doc_type=doc.doc_type,
            trigger=request.trigger,
        )
    # KNOW-06：STATE 文档追加 live API 清单行（渲染格式对齐
    # DocContentService._resolve_system_text：``METHOD path — status``）。
    # live 来源必须直查 ProjectStateApi 表——get_doc_render 的 rendered_markdown
    # 同样来自 snapshot 缓存，不能作为 live API 来源。行数上限 500 防极端膨胀。
    state_api_count = 0
    if doc.doc_type == DocType.STATE:
        lines: list[str] = []
        async for row in (
            ProjectStateApi.objects.filter(project_id=doc.project_id)
            .order_by("path")
            .values("method", "path", "status")[:500]
        ):
            lines.append(f"{row['method']} {row['path']} — {row['status']}")
        state_api_count = len(lines)
        if lines:
            raw_body = raw_body + "\n\n## API 清单\n" + "\n".join(lines)
    # 脱敏不可绕过：正文/异常文本入图前经 redact_secrets_in_text（对拼接后全文执行）。
    body = redact_secrets_in_text(raw_body)

    # 项目图谱节点（KLINK-01 锚）：文件→REFERENCES→项目节点出边需目标实体先存在。
    project_node_id = await ProjectKnowledgeGraphService().ensure_project_node(project)

    event = IngestionEvent(
        kind=EntityKind.DOCUMENT,
        origin=EntityOrigin.PROJECT,
        source_kind="project_doc",
        source_id=str(doc.id),
        title=_doc_title(body, f"{doc.doc_type} {project.name}"),
        content=body,
        payload={"project_id": str(project.id), "doc_type": doc.doc_type},
        space_id=str(project.space_id) if project.space_id else None,
        repository_id=None,
        event_time=doc.updated_at,
        edges=(EdgeSpec(relation=EdgeRelation.REFERENCES, target_entity_id=project_node_id),),
    )

    logger.info(
        "project_doc_rag_normalize_completed",
        doc_id=str(doc.id),
        doc_type=doc.doc_type,
        content_length=len(body),
        state_api_count=state_api_count,
        event_count=1,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        trigger=request.trigger,
        component="knowledge",
        category="sampling",
    )
    return [event]
