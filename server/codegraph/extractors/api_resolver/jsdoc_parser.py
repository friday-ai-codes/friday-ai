"""JSDoc 元数据解析器 —— 从 /** ... */ 注释提取结构化元数据。

解析 @description / @author / @date / yapi URL pattern。
yapi URL pattern: https://{yapi_host}/project/{pid}/interface/api/{iid}

yapi 域名通过环境变量 ``FRIDAY_YAPI_HOST`` 配置（默认占位 ``yapi.example.com``）；
自托管部署时设为自己的 yapi 域名即可解析对应链接，代码不硬编码任何具体实例地址。
"""

from __future__ import annotations

import os
import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# yapi 域名：运行时从环境变量读取，缺省用通用占位（避免在代码中硬编码具体实例）
_YAPI_HOST = os.environ.get("FRIDAY_YAPI_HOST", "yapi.example.com").strip() or "yapi.example.com"

# yapi URL pattern（host 可配置）
_YAPI_URL = re.compile(
    rf"https?://{re.escape(_YAPI_HOST)}/project/(\d+)/interface/api/(\d+)",
    re.IGNORECASE,
)

# @description: 匹配到下一个 @tag 或 */
_JSDOC_DESCRIPTION = re.compile(
    r"@description\s+(.+?)(?=\n\s*\*\s*@|\n\s*\*/|\*/)",
    re.DOTALL,
)

# @author: 一个单词（可含中文）
_JSDOC_AUTHOR = re.compile(r"@author\s+(\S+)")

# @date: 日期字符串（如 2023-05-12）
_JSDOC_DATE = re.compile(r"@date\s+(\S+)")


def parse_jsdoc(comment_text: str | None) -> dict[str, Any] | None:
    """解析 JSDoc /** ... */ 注释，返回 metadata dict 或 None。

    可解析字段：
    - description: @description 描述文本（str）
    - author: @author 作者名（str）
    - date: @date 日期字符串（str）
    - yapi: yapi URL 元数据 dict（{pid, iid, url}）

    Args:
        comment_text: 原始注释文本（含 /** 和 */）

    Returns:
        非空 metadata dict，或 None（无可解析内容）
    """
    if not comment_text:
        return None

    stripped = comment_text.strip()
    if not stripped.startswith("/**"):
        return None

    result: dict[str, Any] = {}

    # @description
    if m := _JSDOC_DESCRIPTION.search(comment_text):
        desc = m.group(1).strip()
        # 清理行首 * 号（多行 description 中每行 " * " 前缀）
        desc = re.sub(r"\n\s*\*\s*", " ", desc).strip()
        # 去末尾句号
        desc = desc.rstrip(".")
        if desc:
            result["description"] = desc

    # @author
    if m := _JSDOC_AUTHOR.search(comment_text):
        result["author"] = m.group(1)

    # @date
    if m := _JSDOC_DATE.search(comment_text):
        result["date"] = m.group(1)

    # yapi URL（搜索整个注释文本，包含 @description 内嵌的 URL）
    if m := _YAPI_URL.search(comment_text):
        pid = int(m.group(1))
        iid = int(m.group(2))
        yapi_url = f"https://{_YAPI_HOST}/project/{pid}/interface/api/{iid}"
        result["yapi"] = {"pid": pid, "iid": iid, "url": yapi_url}

    return result if result else None


def enrich_wrapper_metadata(wrappers: list) -> list:
    """对 ApiWrapperData 列表做 JSDoc 富集，in-place 写入 metadata。

    消费 _jsdoc_text 临时字段，完成后将其清除（设为 None）。
    如 JSDoc 解析成功且返回非空 dict，写入 wrapper.metadata。

    Args:
        wrappers: ApiWrapperData 列表

    Returns:
        同一列表（已 in-place 修改）
    """
    enriched_count = 0
    for wrapper in wrappers:
        jsdoc_text: str | None = getattr(wrapper, "_jsdoc_text", None)
        if jsdoc_text:
            metadata = parse_jsdoc(jsdoc_text)
            if metadata:
                wrapper.metadata = metadata
                enriched_count += 1
                logger.debug(
                    "api_wrapper_jsdoc_enriched",
                    func_name=wrapper.function_symbol,
                    has_yapi="yapi" in metadata,
                    has_description="description" in metadata,
                )
        # 清理临时字段
        wrapper._jsdoc_text = None

    if enriched_count > 0:
        logger.info(
            "api_resolver_jsdoc_enrichment_complete",
            enriched=enriched_count,
            total=len(wrappers),
        )

    return wrappers


__all__ = ["parse_jsdoc", "enrich_wrapper_metadata"]
