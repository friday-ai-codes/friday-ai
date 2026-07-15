"""McpRepositoryAnalysis → document 单事件 normalizer（Phase 100 / KNOW-03）。

kind 复用既有值 ``document``（locked decision：kind 按内容归类、来源经
source_kind 区分，不为 MCP 产物扩新 kind）；natural key 见
``knowledge/models.py generate_entity_id`` 规则表：
``mcp_repository_analysis`` → source_id = ``str(McpRepositoryAnalysis.id)``。

content 为 summary JSON 的 markdown 组装（str/list 值逐段落），payload 只放
摘要字段（repository_id/branch/focus/status/evidence_count），不复制 summary 全文。
"""

from __future__ import annotations

import json

import structlog

from knowledge.ingestion import IngestionEvent, IngestionRequest
from knowledge.models import EntityKind, EntityOrigin

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]


def _format_item(item: object) -> str:
    """列表项 → 单行文本（dict 走确定性 JSON，保证重摄 content 逐字节稳定）。"""
    if isinstance(item, str):
        return item
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def _build_content(title: str, summary: dict, evidence: list) -> str:
    """summary JSON → markdown（遍历 str/list 值拼段落；evidence 取 file_path+reason）。"""
    lines: list[str] = [f"# {title}", ""]
    for key, value in (summary or {}).items():
        if isinstance(value, str) and value.strip():
            lines += [f"## {key}", "", value.strip(), ""]
        elif isinstance(value, list) and value:
            lines += [f"## {key}", ""]
            lines += [f"- {_format_item(item)}" for item in value]
            lines.append("")
    evidence_lines = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file_path") or "")
        reason = str(item.get("reason") or "")
        if file_path:
            evidence_lines.append(f"- {file_path}" + (f"：{reason}" if reason else ""))
    if evidence_lines:
        lines += ["## 证据文件", "", *evidence_lines, ""]
    return "\n".join(lines).rstrip() + "\n"


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """McpRepositoryAnalysis → document 单事件；源缺失返回空列表 + warning。"""
    from mcp_tools.models import McpRepositoryAnalysis

    analysis = (
        await McpRepositoryAnalysis.objects.select_related("repository")
        .filter(id=request.source_id)
        .afirst()
    )
    if analysis is None:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
        )
        return []

    focus = (analysis.focus or "").strip()
    title = f"{analysis.repository.name} 仓库分析" + (f"（{focus}）" if focus else "")
    summary = analysis.summary if isinstance(analysis.summary, dict) else {}
    evidence = analysis.evidence if isinstance(analysis.evidence, list) else []
    event = IngestionEvent(
        kind=EntityKind.DOCUMENT,
        origin=EntityOrigin.MCP,
        source_kind="mcp_repository_analysis",
        source_id=str(analysis.id),
        title=title,
        content=_build_content(title, summary, evidence),
        # 摘要纪律：payload 不复制 summary 全文，只放定位字段
        payload={
            "repository_id": str(analysis.repository_id),
            "branch": analysis.branch,
            "focus": analysis.focus,
            "status": analysis.status,
            "evidence_count": len(evidence),
        },
        space_id=None,
        repository_id=str(analysis.repository_id),
        event_time=analysis.created_at,
    )
    return [event]
