"""飞书响应防御式解析 + 字段保留/提取 共享 helper（纯函数，Django-free）。

本模块把飞书取数链路中"可纯函数化"的解析逻辑一次性收敛，供
`server/services/feishu.py` 与 `server/feishu/client.py` 两份 client 共同调用，
消除解析漂移（Phase 27 CONTEXT 决策：consolidate fixed parsing into a shared
helper used by BOTH client copies）。

设计约束：
- **绝不依赖 Django**：本模块只 import 标准库 + httpx + structlog，
  字段 key 常量在此处定义为唯一事实源（`feishu.models.KeyFields` 反向 import
  本模块，避免 services→Django-models 的层级倒置）。
- **防御式解析**：所有面向不可信飞书响应的 `.json()` 都经 `safe_response_json` /
  `strict_response_json` 包裹，非 JSON（HTML/空/Extra data）fail-soft 返回 None
  或抛带上下文的 `FeishuResponseError`，绝不让解析崩进调用栈（T-27-01）。
- **日志脱敏**：错误信息只放 `response.text[:200]` 截断片段，绝不放
  X-PLUGIN-TOKEN / X-USER-KEY / plugin_secret（T-27-02）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


# === 字段 key / alias 常量（唯一事实源；feishu.models.KeyFields 反向 import）===

PRD_URL_FIELD_KEY = "field_000001"  # 需求文档链接
TECH_DOC_URL_FIELD_KEY = "field_000009"  # 技术方案文档链接
DESCRIPTION_FIELD_KEY = "description"  # 需求描述
PRD_URL_ALIAS = "prd_url"  # 需求文档字段别名

# 错误日志中 body 截断长度（绝不全量，避免泄漏 + 日志膨胀）
_BODY_SNIPPET_LIMIT = 200


class FeishuResponseError(Exception):
    """飞书响应防御式解析硬失败时抛出（带 body 截断片段，禁含凭证）。"""


def _response_snippet(response: httpx.Response) -> str:
    """取响应 body 的截断片段用于日志/异常（脱敏：仅前 200 字符）。"""
    try:
        return response.text[:_BODY_SNIPPET_LIMIT]
    except Exception:  # pragma: no cover - text 解码异常兜底
        return "<unreadable body>"


def _looks_like_json(response: httpx.Response) -> bool:
    """content-type 是否声明为 JSON。"""
    content_type = response.headers.get("content-type", "")
    return "json" in content_type.lower()


def safe_response_json(
    response: httpx.Response,
    *,
    log_event: str,
    expect: type | tuple[type, ...] | None = None,
    **log_ctx: Any,
) -> Any | None:
    """content-type 校验 + try/except 包裹 `response.json()`（fail-soft）。

    非 JSON（content-type 不含 json，或 `.json()` 抛 JSONDecodeError/ValueError）
    → 记 `logger.warning(log_event, ...)` 并返回 `None`，绝不冒泡异常。

    当传入 `expect` 时，对"合法 JSON 但类型不符"（如期望 dict 却返回 `[]`/标量）
    同样按软失败处理：记 warning 并返回 `None`，避免调用方对非期望类型执行
    `data.get(...)` 时抛 `AttributeError`（WR-01）。

    Args:
        response: 待解析的 httpx 响应（不可信外部输入）。
        log_event: 结构化日志事件名。
        expect: 期望的解析结果类型（如 `dict`）；不符时 fail-soft 返回 None。
        **log_ctx: 附加日志上下文（绝不传凭证）。

    Returns:
        解析后的 JSON 对象，或非 JSON / 类型不符时返回 None。
    """
    if not _looks_like_json(response):
        logger.warning(
            log_event,
            reason="non_json_content_type",
            content_type=response.headers.get("content-type", ""),
            status_code=response.status_code,
            body_snippet=_response_snippet(response),
            **log_ctx,
        )
        return None

    try:
        parsed = response.json()
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            log_event,
            reason="json_decode_error",
            status_code=response.status_code,
            body_snippet=_response_snippet(response),
            **log_ctx,
        )
        return None

    if expect is not None and not isinstance(parsed, expect):
        logger.warning(
            log_event,
            reason="unexpected_payload_type",
            payload_type=type(parsed).__name__,
            status_code=response.status_code,
            body_snippet=_response_snippet(response),
            **log_ctx,
        )
        return None

    return parsed


def strict_response_json(
    response: httpx.Response,
    *,
    log_event: str,
    **log_ctx: Any,
) -> Any:
    """content-type 校验 + try/except 包裹 `response.json()`（硬失败路径）。

    非 JSON → 记 warning 并抛 `FeishuResponseError`（带 body 截断片段，禁含凭证）。
    用于"取数硬失败需要 fail-loud"的关键调用。

    Args:
        response: 待解析的 httpx 响应（不可信外部输入）。
        log_event: 结构化日志事件名。
        **log_ctx: 附加日志上下文（绝不传凭证）。

    Returns:
        解析后的 JSON 对象。

    Raises:
        FeishuResponseError: 响应非 JSON 时抛出。
    """
    snippet = _response_snippet(response)
    if not _looks_like_json(response):
        logger.warning(
            log_event,
            reason="non_json_content_type",
            content_type=response.headers.get("content-type", ""),
            status_code=response.status_code,
            body_snippet=snippet,
            **log_ctx,
        )
        raise FeishuResponseError(f"飞书响应非 JSON（content-type 不符）: {snippet}")

    try:
        return response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            log_event,
            reason="json_decode_error",
            status_code=response.status_code,
            body_snippet=snippet,
            **log_ctx,
        )
        raise FeishuResponseError(f"飞书响应 JSON 解析失败: {snippet}") from exc


# === 富文本 → Markdown（由两份 client 的 _parse_rich_text/_parse_paragraph 上移）===


def rich_text_to_markdown(rich_text: Any) -> str:
    """解析飞书富文本为 Markdown（纯函数，行为等价于 client._parse_rich_text）。

    Args:
        rich_text: 飞书 API 返回的富文本对象（str / dict / 其它）。

    Returns:
        Markdown 格式字符串。
    """
    if isinstance(rich_text, str):
        return rich_text

    if not isinstance(rich_text, dict):
        return str(rich_text) if rich_text else ""

    content = rich_text.get("content", [])
    if not content:
        return ""

    result = []
    for block in content:
        block_type = block.get("type", "")

        if block_type == "paragraph":
            text = _paragraph_to_text(block)
            result.append(text)

        elif block_type == "heading":
            level = block.get("attrs", {}).get("level", 1)
            text = _paragraph_to_text(block)
            result.append(f"{'#' * level} {text}")

        elif block_type == "bullet_list":
            items = block.get("content", [])
            for item in items:
                text = _paragraph_to_text(item)
                result.append(f"- {text}")

        elif block_type == "ordered_list":
            items = block.get("content", [])
            for i, item in enumerate(items, 1):
                text = _paragraph_to_text(item)
                result.append(f"{i}. {text}")

        elif block_type == "code_block":
            code = _paragraph_to_text(block)
            lang = block.get("attrs", {}).get("language", "")
            result.append(f"```{lang}\n{code}\n```")

        elif block_type == "image":
            result.append("[Image]")

    return "\n".join(result)


def _paragraph_to_text(block: dict) -> str:
    """解析段落内容为文本（行为等价于 client._parse_paragraph）。"""
    content = block.get("content", [])
    texts = []

    for node in content:
        if node.get("type") == "text":
            text = node.get("text", "")
            marks = node.get("marks", [])

            for mark in marks:
                mark_type = mark.get("type")
                if mark_type == "bold":
                    text = f"**{text}**"
                elif mark_type == "italic":
                    text = f"*{text}*"
                elif mark_type == "code":
                    text = f"`{text}`"
                elif mark_type == "link":
                    href = mark.get("attrs", {}).get("href", "")
                    text = f"[{text}]({href})"

            texts.append(text)

    return "".join(texts)


# === 字段保留 / 拍平 / 提取 ===


def build_feishu_fields(raw_fields: list[dict]) -> list[dict]:
    """保留完整字段对象数组（FIX-04 核心，不丢元数据）。

    每项保留 5 个键：`field_key` / `field_name` / `field_value` /
    `field_type_key` / `field_alias`（对齐 DOMAIN §16 字段对象形状）。

    Args:
        raw_fields: 飞书工作项响应的 `fields[]` 原始数组。

    Returns:
        归一后的完整字段对象列表。
    """
    result: list[dict] = []
    for raw in raw_fields or []:
        if not isinstance(raw, dict):
            continue
        result.append(
            {
                "field_key": raw.get("field_key"),
                "field_name": raw.get("field_name"),
                "field_value": raw.get("field_value"),
                "field_type_key": raw.get("field_type_key"),
                "field_alias": raw.get("field_alias"),
            }
        )
    return result


def flatten_fields(raw_fields: list[dict]) -> dict[str, Any]:
    """向后兼容拍平 `{field_key: field_value}`（保持既有调用方语义）。

    Args:
        raw_fields: 飞书工作项响应的 `fields[]` 原始数组。

    Returns:
        `{field_key: field_value}` 字典。
    """
    out: dict[str, Any] = {}
    for raw in raw_fields or []:
        if not isinstance(raw, dict):
            continue
        key = raw.get("field_key")
        if key:
            out[key] = raw.get("field_value")
    return out


def find_field(
    feishu_fields: list[dict],
    *,
    key: str | None = None,
    alias: str | None = None,
) -> dict | None:
    """按 `field_key` 或 `field_alias` 查字段对象。

    Args:
        feishu_fields: `build_feishu_fields` 产出的完整字段对象列表。
        key: 目标 `field_key`。
        alias: 目标 `field_alias`。

    Returns:
        命中的字段对象，未命中返回 None。
    """
    for fld in feishu_fields or []:
        if not isinstance(fld, dict):
            continue
        if key is not None and fld.get("field_key") == key:
            return fld
        if alias is not None and fld.get("field_alias") == alias:
            return fld
    return None


def extract_select_label(field_value: Any) -> str | None:
    """select 类字段值 `{label, value}` 取 label。

    Args:
        field_value: 字段值（select 类为 `{label, value}`）。

    Returns:
        label 字符串，形状不符返回 None。
    """
    if isinstance(field_value, dict):
        label = field_value.get("label")
        if isinstance(label, str):
            return label
    return None


def extract_related_ids(field_value: Any) -> list[int]:
    """关联类字段值 `[id...]` 归一为 int 列表。

    兼容 list 内为 int / 数字字符串 / `{id|value}` 字典三种形态；
    非 list 或无法归一的项被跳过（fail-soft）。

    Args:
        field_value: 字段值（关联类为 `[id...]`）。

    Returns:
        int 类型的目标 id 列表。
    """
    if not isinstance(field_value, list):
        return []

    ids: list[int] = []
    for item in field_value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            ids.append(item)
        elif isinstance(item, str):
            text = item.strip()
            if text.lstrip("-").isdigit():
                ids.append(int(text))
        elif isinstance(item, dict):
            raw = item.get("id")
            if raw is None:
                raw = item.get("value")
            if isinstance(raw, bool):
                continue
            if isinstance(raw, int):
                ids.append(raw)
            elif isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
                ids.append(int(raw.strip()))
    return ids


def extract_prd_url(feishu_fields: list[dict]) -> str:
    """提取需求文档链接：alias `prd_url` 或 key `field_000001`。

    Args:
        feishu_fields: `build_feishu_fields` 产出的完整字段对象列表。

    Returns:
        prd_url 字符串，未命中返回空串。
    """
    fld = find_field(feishu_fields, alias=PRD_URL_ALIAS)
    if fld is None:
        fld = find_field(feishu_fields, key=PRD_URL_FIELD_KEY)
    return _field_value_as_url(fld)


def extract_tech_doc_url(feishu_fields: list[dict]) -> str:
    """提取技术方案文档链接：key `field_000009`。

    Args:
        feishu_fields: `build_feishu_fields` 产出的完整字段对象列表。

    Returns:
        tech_doc_url 字符串，未命中返回空串。
    """
    fld = find_field(feishu_fields, key=TECH_DOC_URL_FIELD_KEY)
    return _field_value_as_url(fld)


def _field_value_as_url(fld: dict | None) -> str:
    """从字段对象取链接字符串（link 类可能为 str 或 `{label,value}` / `{url}`）。"""
    if fld is None:
        return ""
    value = fld.get("field_value")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for candidate_key in ("url", "value", "link", "href"):
            candidate = value.get(candidate_key)
            if isinstance(candidate, str) and candidate:
                return candidate
    return ""


# === 关系派生（FIX-02 / PF-10）===

# 关联字段 → 关系类型映射（DOMAIN §16 实测；未命中归 related）
RELATION_TYPE_BY_FIELD: dict[str, str] = {
    "field_000008": "belongs_to_project",  # 所属项目（父）
    "planning_sprint": "sprint",  # 所属迭代
    "planning_version": "version",  # 规划版本
    "actual_online_version": "version",  # 上车版本
}

# 触发关系派生的字段类型（关联多选）
RELATION_FIELD_TYPE_KEY = "work_item_related_multi_select"


@dataclass
class RelationSpec:
    """派生自飞书关联字段的关系规格（对齐 DOMAIN §12.3 WorkItemRelation）。

    本 phase 只产出"派生 RelationSpec 结构"，不落库（落库是 Phase 28）。
    """

    relation_type: str
    source_field_key: str
    target_external_id: int
    origin: str = "feishu_field"


def derive_relations_from_fields(feishu_fields: list[dict]) -> list[RelationSpec]:
    """从关联多选字段派生关系规格（FIX-02 主路径，纯函数、无 DB、无网络）。

    仅遍历 `field_type_key == work_item_related_multi_select` 的字段，对每个
    `target_external_id` 产出一条 `RelationSpec`：relation_type 经
    `RELATION_TYPE_BY_FIELD` 映射、未命中归 `related`；origin 固定 `feishu_field`。
    空 `[]` 关联值不产出关系；非关联类型字段被忽略。

    Args:
        feishu_fields: `build_feishu_fields` 产出的完整字段对象列表。

    Returns:
        派生出的 `RelationSpec` 列表（DOMAIN §12.3）。
    """
    specs: list[RelationSpec] = []
    for fld in feishu_fields or []:
        if not isinstance(fld, dict):
            continue
        if fld.get("field_type_key") != RELATION_FIELD_TYPE_KEY:
            continue
        source_field_key = fld.get("field_key")
        if not source_field_key:
            continue
        relation_type = RELATION_TYPE_BY_FIELD.get(source_field_key, "related")
        for target_id in extract_related_ids(fld.get("field_value")):
            specs.append(
                RelationSpec(
                    relation_type=relation_type,
                    source_field_key=source_field_key,
                    target_external_id=target_id,
                    origin="feishu_field",
                )
            )
    return specs


# === 评论解析（FIX-03 / PF-11）===


def parse_comments(data: Any) -> list[dict]:
    """对齐飞书 `comment/list` 形状逐条解析评论（fail-soft）。

    容错读取 `data["data"]["comments"]`（兼容现状 `data.get("data",{})
    .get("comments",[])`）；逐条取 `id` / `content`(经 rich_text_to_markdown) /
    `created_at` / `author`(author.name 缺省 "Unknown") / `thread_parent_id`
    （父评论 id，无则空串）。`data` 为 None / 形状不符 → 返回 `[]`，不抛异常。

    Args:
        data: 飞书评论列表接口的解析后响应（可能为 None / 畸形）。

    Returns:
        扁平评论字典列表。
    """
    if not isinstance(data, dict):
        return []

    payload = data.get("data")
    if not isinstance(payload, dict):
        return []

    raw_comments = payload.get("comments")
    if not isinstance(raw_comments, list):
        return []

    comments: list[dict] = []
    for item in raw_comments:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        author_name = "Unknown"
        if isinstance(author, dict):
            author_name = author.get("name") or "Unknown"
        comments.append(
            {
                "id": item.get("id"),
                "content": rich_text_to_markdown(item.get("content", {})),
                "created_at": item.get("created_at"),
                "author": author_name,
                "thread_parent_id": item.get("parent_id") or item.get("thread_parent_id") or "",
            }
        )
    return comments
