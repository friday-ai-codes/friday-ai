"""项目工件 → knowledge document 投影 normalizer（ARTIFACT-04）。

镜像 ``sources/feishu_document.py`` 范式：``ragable=True`` 且文字载体（飞书 doc/表格/md/
仓库文件）的工件正文全文摄取进 ``delivery_knowledge``——产 ``KnowledgeEntity(kind=document,
source_kind="artifact")`` + ``工件→REFERENCES→项目图谱节点`` 出边（KLINK-01：项目↔知识）。

**UI 稿（figma/mastergo）等图形外链元数据-only 登记**（``ragable=False`` / ``external_link``）——
产 ``vectorize=False`` 的 document 事件（KDEP-01）：仍建 ``KnowledgeEntity(kind=document)``
+ ``工件→REFERENCES→项目节点`` 边，承载 title/type/carrier/url 元数据，但**不进 Qdrant 向量**
（无正文可 embed，多模态留 v2 PROJX-01）。保证总览计数/搜索/树视图覆盖全部类型零遗漏。

降级语义（fail-soft，缺段不缺实体）：
- 工件不存在 → 返回空列表（warning）；
- 飞书正文拉取失败 → 正文空串 + warning，实体与边照常产出（不抛、不回滚、不阻断工件创建）。

**脱敏不可绕过**：飞书 doc/表格正文经 ``redact_secrets_in_text`` 脱敏后才入图。
观测：``artifact_rag_normalize_started/completed/failed`` + ``duration_ms`` + 正文长度 + 事件数
（category=sampling, component=knowledge）。
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import structlog
from django.utils import timezone

from common.logging import redact_secrets_in_text
from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]

# 与 initiatives.models.ArtifactCarrier 对齐的文字载体（可全文 RAG）。
_TEXT_CARRIERS = frozenset({"feishu_doc", "feishu_bitable", "markdown", "repo_file"})


def _artifact_title(artifact) -> str:
    """Knowledge entity title must remain the artifact/document name.

    Body headings are often section titles such as "版本追溯表" or "项目背景";
    using them as the entity title makes graph/search results unreadable.
    """
    return (artifact.title or f"工件 {artifact.id}")[:500]


def _extract_doc_token(url: str) -> str:
    """飞书文档 URL → doc token（取末段 path，剥 query/fragment）；裸 token 原样。"""
    if not url:
        return ""
    value = url.strip()
    if "feishu.cn" in value or "larksuite.com" in value:
        return urlparse(value).path.rstrip("/").split("/")[-1]
    return value


def _parse_bitable_url(url: str) -> tuple[str, str]:
    """飞书多维表格 URL → (app_token, table_id)；解析失败返回 ("","")。

    形如 ``https://xxx.feishu.cn/base/{app_token}?table={table_id}&view=...``。
    """
    if not url:
        return "", ""
    parsed = urlparse(url.strip())
    app_token = parsed.path.rstrip("/").split("/")[-1]
    table_id = ""
    qs = parse_qs(parsed.query)
    if qs.get("table"):
        table_id = qs["table"][0]
    return app_token, table_id


def _records_to_text(data: dict) -> str:
    """Bitable 记录原始 data → 纯文本（每记录一段 ``key: value`` 行）。"""
    items = data.get("items") or []
    lines: list[str] = []
    for item in items:
        fields = item.get("fields") or {}
        for key, value in fields.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    return "\n".join(lines).strip()


async def _fetch_bitable_text(client, app_token: str, table_id: str) -> str:
    """Fetch one or more Bitable tables and render records as text."""
    table_ids: list[str] = []
    if table_id:
        table_ids = [table_id]
    else:
        data = await client.list_tables(app_token)
        for item in data.get("items") or []:
            tid = item.get("table_id")
            if tid:
                table_ids.append(str(tid))

    sections: list[str] = []
    for tid in table_ids:
        page_token: str | None = None
        items: list[dict] = []
        while True:
            data = await client.list_records(app_token, tid, page_token=page_token)
            items.extend(data.get("items") or [])
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break
        text = _records_to_text({"items": items})
        if text:
            sections.append(f"## Table {tid}\n\n{text}" if len(table_ids) > 1 else text)
    return "\n\n".join(sections).strip()


async def _fetch_body(artifact, space, *, request: IngestionRequest) -> str:
    """按载体拉取工件正文（fail-soft：失败返回空串 + warning）。"""
    carrier = artifact.carrier
    if carrier in ("markdown", "repo_file"):
        # md/内部工件正文即 content_ref；仓库文件引用也走 content_ref（内联或路径快照）。
        return artifact.content_ref or ""

    if carrier == "feishu_doc":
        token = _extract_doc_token(artifact.url)
        if not token:
            return ""
        try:
            from agents.tools.feishu_doc_tools import (
                create_feishu_doc_client_for_project,
            )

            client = await create_feishu_doc_client_for_project(space)
            markdown, _blocks = await client.get_document_content_by_url(artifact.url or token)
            return markdown or ""
        except Exception as exc:  # noqa: BLE001 — fail-soft 降级空正文
            logger.warning(
                "artifact_rag_doc_fetch_failed",
                artifact_id=str(artifact.id),
                trigger=request.trigger,
                doc_token=token,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return ""

    if carrier == "feishu_bitable":
        app_token, table_id = _parse_bitable_url(artifact.url)
        if not app_token:
            return ""
        try:
            from services.feishu_bitable import create_bitable_client_for_project

            client = await create_bitable_client_for_project(space)
            return await _fetch_bitable_text(client, app_token, table_id)
        except Exception as exc:  # noqa: BLE001 — fail-soft 降级空正文
            logger.warning(
                "artifact_rag_bitable_fetch_failed",
                artifact_id=str(artifact.id),
                trigger=request.trigger,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return ""

    return ""


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """工件 UUID → 单 document 事件（携 REFERENCES→项目节点 出边）；非 ragable 返回空。"""
    from initiatives.models import TEXT_CARRIERS, Artifact
    from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService

    started = time.perf_counter()
    logger.info(
        "artifact_rag_normalize_started",
        source_id=request.source_id,
        trigger=request.trigger,
        component="knowledge",
        category="sampling",
    )

    artifact = (
        await Artifact.objects.select_related("project", "project__space", "type")
        .filter(id=request.source_id)
        .afirst()
    )
    if artifact is None:
        logger.warning(
            "artifact_rag_source_missing",
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []

    project = artifact.project
    space = project.space

    # 是否文字载体可全文 RAG：ragable 类型 + 文字载体（飞书 doc/表格/md/repo_file）。
    # 非 ragable（UI 稿 external_link 等）走元数据-only 分支：仍登记实体 + 边，但不进 Qdrant 向量（KDEP-01）。
    vectorize = bool(artifact.type.ragable) and artifact.carrier in TEXT_CARRIERS

    event_time = timezone.now()
    if artifact.updated_at and artifact.updated_at > event_time:
        event_time = artifact.updated_at

    # 项目图谱节点（KLINK-01 锚）：工件→REFERENCES→项目节点出边需目标实体先存在。
    project_node_id = await ProjectKnowledgeGraphService().ensure_project_node(project)

    if vectorize:
        raw_body = await _fetch_body(artifact, space, request=request)
        # 脱敏不可绕过：飞书正文/异常文本入图前经 redact_secrets_in_text。
        content = redact_secrets_in_text(raw_body or "")
    else:
        # 元数据-only：content 为确定性元数据文本（title/type/carrier/url 拼接），
        # 仅作 content_hash 幂等锚（title/url/carrier 变更 → hash 变 → 版本翻转），不会被 embed。
        raw_meta = "\n".join(
            [
                artifact.title or "",
                artifact.type.name or artifact.type.key,
                artifact.carrier or "",
                artifact.url or "",
            ]
        )
        content = redact_secrets_in_text(raw_meta)

    event = IngestionEvent(
        kind=EntityKind.DOCUMENT,
        origin=EntityOrigin.ARTIFACT,
        source_kind="artifact",
        source_id=str(artifact.id),
        title=_artifact_title(artifact),
        content=content,
        payload={
            "artifact_id": str(artifact.id),
            "project_id": str(project.id),
            "type": artifact.type.key,
            "carrier": artifact.carrier,
            "url": artifact.url,
            "version": artifact.version,
        },
        space_id=str(project.space_id) if project.space_id else None,
        repository_id=None,
        event_time=event_time,
        edges=(EdgeSpec(relation=EdgeRelation.REFERENCES, target_entity_id=project_node_id),),
        vectorize=vectorize,
    )

    logger.info(
        "artifact_rag_normalize_completed",
        artifact_id=str(artifact.id),
        carrier=artifact.carrier,
        vectorize=vectorize,
        content_length=len(content),
        event_count=1,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        trigger=request.trigger,
        component="knowledge",
        category="sampling",
    )
    return [event]
