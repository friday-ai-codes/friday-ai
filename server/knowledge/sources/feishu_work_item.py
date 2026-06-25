"""飞书工作项 → 全量快照单事件 normalizer（Plan 14-05 / INGEST-04）。

source_id 为 natural key 规则表锁定的三元组 ``{project_key}:{work_item_type}:{work_item_id}``
（13-03 轻量锚同 key：本 normalizer 重摄即把锚实体升级为全量快照版本，版本翻转非新实体）。

取材全在后台（Pitfall 3 locked）：webhook 接线只投三元组 ID；get_work_item /
get_work_item_relations / PRD 与技术方案文档正文全部在此（background runner 内）拉取。

降级语义（13 范式：部分缺料降配不 raise）：

- project_key 查无 Space / get_work_item 失败 → 空列表 + warning（源缺失）；
- get_work_item_relations 失败 → 空关联列表 + warning，事件照常产出；
- 单文档（PRD / 技术方案）拉取失败 → 快照不含该正文段 + warning，事件照常产出。

event_time（Pitfall 6）：工作项 fields 更新时间字段（毫秒时间戳）→
``datetime.fromtimestamp(ms / 1000, tz=UTC)``；字段缺失/非法 → ``timezone.now()`` 兜底，
恒 aware（graph_store ``require_aware`` 防线不触发）。

凭证只经 ``create_feishu_client_for_project`` / ``create_feishu_doc_client_for_project``
既有 service 层（DB 加密凭证，零 env 读取）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import structlog
from django.utils import timezone

from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project
from knowledge.ingestion import IngestionEvent, IngestionRequest
from knowledge.models import EntityKind, EntityOrigin
from services.feishu import create_feishu_client_for_project

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]

# 工作项 fields 内的时间字段候选（毫秒时间戳），按序取首个可解析值
_EVENT_TIME_FIELD_KEYS = ("updated_at", "update_time", "updated_time", "created_at")


def _parse_event_time(fields: dict[str, Any]) -> datetime:
    """fields 毫秒时间戳 → aware UTC datetime；缺失/非法 → ``timezone.now()`` 兜底。"""
    for key in _EVENT_TIME_FIELD_KEYS:
        raw = fields.get(key)
        if raw is None:
            continue
        try:
            ms = int(raw)
        except (TypeError, ValueError):
            continue
        if ms <= 0:
            continue
        try:
            return datetime.fromtimestamp(ms / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError):
            continue
    return timezone.now()


def _extract_doc_token(field_value: Any) -> str:
    """字段值（文档 URL 或裸 token）→ doc token；取不出返回空串。

    完整 URL 取末段 path，裸 token 原样返回。经 ``urlparse`` 先剥离
    query string / fragment（WR-03：浏览器复制的 URL 普遍带 ``?from=`` 参数，
    不剥离则 token 携参导致 doc API 必然 404、快照静默缺正文段）。
    """
    if not isinstance(field_value, str) or not field_value.strip():
        return ""
    value = field_value.strip()
    if "feishu.cn" in value or "larksuite.com" in value:
        return urlparse(value).path.rstrip("/").split("/")[-1]
    return value


def _format_custom_fields(fields: dict[str, Any]) -> str:
    """自定义字段 dict → ``- key: value`` 行；复合值 JSON 序列化。"""
    lines: list[str] = []
    for key, value in fields.items():
        if key == "description":
            # description 已单独渲染进正文，不重复进字段表
            continue
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = str(value)
        lines.append(f"- {key}: {rendered}")
    return "\n".join(lines)


async def _resolve_work_item(project_key: str, work_item_type: str, work_item_id_raw: str):
    """定位已落库的 delivery WorkItem（缺则 None；非法 id 不抛）。

    与 ``feishu_document._resolve_work_item`` 同款三元组解析范式（int 转换失败
    返回 None），供评论段投影取材——惰性 import delivery 规避 knowledge→delivery
    循环依赖。
    """
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


def _render_comment_section(tree: list[dict]) -> str:
    """评论树（project_comment_tree 形状）→ 确定性 markdown；空树返回空串。

    严格按 ``project_comment_tree`` 既有排序拍平（不重排），保证评论无变化时
    渲染逐字一致（hash-no-version 守护）。每节点 ``- {author}: {body}``，
    deleted 节点标 ``（已删除）``（保留占位维持线程结构），子回复缩进两空格。
    """
    lines: list[str] = []

    def _walk(nodes: list[dict], depth: int) -> None:
        indent = "  " * depth
        for node in nodes:
            author = node.get("author") or "匿名"
            body = node.get("body") or ""
            deleted = "（已删除）" if node.get("is_deleted") else ""
            lines.append(f"{indent}- {author}{deleted}: {body}")
            children = node.get("children") or []
            if children:
                _walk(children, depth + 1)

    _walk(tree, 0)
    return "\n".join(lines)


def _count_comment_nodes(tree: list[dict]) -> int:
    """递归统计评论树节点数（仅快照元数据，不影响 content hash）。"""
    total = 0
    for node in tree:
        total += 1 + _count_comment_nodes(node.get("children") or [])
    return total


async def _fetch_doc_body(doc_client, token: str, *, request: IngestionRequest, label: str) -> str:
    """拉取单文档正文；失败 warning 降级返回空串（缺段不缺事件）。"""
    if doc_client is None or not token:
        return ""
    try:
        markdown, _blocks = await doc_client.get_document_content(token)
        return markdown
    except Exception as exc:
        logger.warning(
            "knowledge_normalize_doc_fetch_failed",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            doc_label=label,
            doc_token=token,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return ""


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """飞书工作项三元组 → 全量快照单事件；源缺失返回空列表，部分缺料降配。"""
    from feishu.models import KeyFields
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

    try:
        work_item_id: int | str = int(work_item_id_raw)
    except ValueError:
        work_item_id = work_item_id_raw

    try:
        client = create_feishu_client_for_project(project)
        info = await client.get_work_item(
            project_key=project_key,
            work_item_id=work_item_id,
            work_item_type=work_item_type,
        )
    except Exception as exc:
        logger.warning(
            "knowledge_normalize_source_missing",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return []

    fields = info.fields or {}

    try:
        relations = await client.get_work_item_relations(
            project_key=project_key,
            work_item_id=work_item_id,
            work_item_type=work_item_type,
        )
    except Exception as exc:
        relations = []
        logger.warning(
            "knowledge_normalize_relations_fetch_failed",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            error=str(exc),
            error_type=type(exc).__name__,
        )

    prd_url = str(fields.get(KeyFields.PRD_URL) or "")
    tech_doc_url = str(fields.get(KeyFields.TECH_DOC_URL) or "")
    prd_token = _extract_doc_token(prd_url)
    tech_token = _extract_doc_token(tech_doc_url)

    doc_client = None
    if prd_token or tech_token:
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
    prd_body = await _fetch_doc_body(doc_client, prd_token, request=request, label="prd")
    tech_body = await _fetch_doc_body(doc_client, tech_token, request=request, label="tech_doc")

    # content markdown 拼接（## 分段契合 chunker）；缺料段整段省略
    sections: list[str] = [f"# {info.name}"]
    if info.description:
        sections.append(info.description)
    custom_fields_text = _format_custom_fields(fields)
    if custom_fields_text:
        sections.append(f"## 自定义字段\n{custom_fields_text}")
    if prd_body:
        sections.append(f"## PRD\n{prd_body}")
    if tech_body:
        sections.append(f"## 技术方案\n{tech_body}")
    if relations:
        relation_lines = "\n".join(
            f"- {rel.get('relation_type', 'related')}: {rel.get('name', '')}"
            f"（{rel.get('status', '')}）"
            for rel in relations
        )
        sections.append(f"## 关联工作项\n{relation_lines}")

    # 评论段（RREF-02 评论入图）：并入当前评论树文本，使评论经既有检索召回且天然
    # 关联到本 work_item 知识实体（不新增 EntityKind）。降级纪律（§1.4）：无 delivery
    # WorkItem / 无评论 / 投影异常 → content 不含评论段 + warning，事件照常产出
    # （缺段不缺实体），绝不抛、绝不回滚。空树不渲染空段。确定性渲染保证评论无变化
    # 时 content 逐字一致（hash-no-version）。
    comment_count = 0
    try:
        work_item_obj = await _resolve_work_item(project_key, work_item_type, work_item_id_raw)
        if work_item_obj is not None:
            from delivery.services import aproject_comment_tree

            tree = await aproject_comment_tree(work_item_obj)
            rendered = _render_comment_section(tree)
            if rendered:
                sections.append(f"## 评论\n{rendered}")
                comment_count = _count_comment_nodes(tree)
    except Exception as exc:
        logger.warning(
            "knowledge_normalize_comments_unavailable",
            source_kind=request.source_kind,
            source_id=request.source_id,
            trigger=request.trigger,
            error=str(exc),
            error_type=type(exc).__name__,
        )

    content = "\n\n".join(sections)

    return [
        IngestionEvent(
            kind=EntityKind.WORK_ITEM,
            origin=EntityOrigin.FEISHU,
            source_kind="feishu_work_item",
            # 三元组原样回填（natural key 规则表：同 key 重摄即升级 13-03 轻量锚）
            source_id=request.source_id,
            title=info.name,
            content=content,
            payload={
                "name": info.name,
                "status": info.status,
                "work_item_type": work_item_type,
                "work_item_id": work_item_id,
                "prd_url": prd_url,
                "tech_doc_url": tech_doc_url,
                "relation_count": len(relations),
                "comment_count": comment_count,
            },
            # T-14-20：project_id 恒带（Phase 15 检索权限过滤的前提）
            space_id=str(project.id),
            repository_id=None,
            event_time=_parse_event_time(fields),
        )
    ]
