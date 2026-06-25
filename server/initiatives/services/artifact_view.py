"""工件在线查看读取/渲染（ARTIFACT-03，后端 API；富前端留 Phase 81 UI-03）。

按载体返回可在线查看的结构化数据：
- ``feishu_doc``：经既有 ``FeishuDocClient.get_document_content`` 读取渲染为 markdown；
- ``feishu_bitable``：经既有 ``BitableClient.list_records`` 读取记录（原始 data，列解析留 v2）；
- ``external_link``：返回元数据 + 跳转 url（外链不读正文）；
- ``markdown`` / ``repo_file``：返回 ``content_ref``（内部工件正文，可读可写经 ArtifactService）。

**只读**（不写库，无 INV-6 约束）。飞书正文经 ``redact_secrets_in_text`` 脱敏；拉取失败
fail-soft（返回 ``error`` 字段 + url，不抛、不阻断查看其他工件）。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = ["aget_artifact_view"]


def _extract_doc_token(url: str) -> str:
    if not url:
        return ""
    value = url.strip()
    if "feishu.cn" in value or "larksuite.com" in value:
        return urlparse(value).path.rstrip("/").split("/")[-1]
    return value


def _parse_bitable_url(url: str) -> tuple[str, str]:
    if not url:
        return "", ""
    parsed = urlparse(url.strip())
    app_token = parsed.path.rstrip("/").split("/")[-1]
    table_id = ""
    qs = parse_qs(parsed.query)
    if qs.get("table"):
        table_id = qs["table"][0]
    return app_token, table_id


async def aget_artifact_view(artifact: Any) -> dict[str, Any]:
    """读取工件在线查看数据（按载体分发，fail-soft）。

    Args:
        artifact: ``Artifact`` 实例（需已 ``select_related("project__space")``）。

    Returns:
        ``{carrier, render_type, ...}`` 结构化查看数据。
    """
    carrier = artifact.carrier
    base = {
        "artifact_id": str(artifact.id),
        "carrier": carrier,
        "title": artifact.title,
        "url": artifact.url,
        "version": artifact.version,
    }

    if carrier in ("markdown", "repo_file"):
        return {
            **base,
            "render_type": "markdown" if carrier == "markdown" else "text",
            "content": redact_secrets_in_text(artifact.content_ref or ""),
        }

    if carrier == "external_link":
        # 外链不读正文，仅元数据 + 跳转 url。
        return {**base, "render_type": "link"}

    space = artifact.project.space

    if carrier == "feishu_doc":
        token = _extract_doc_token(artifact.url)
        if not token:
            return {**base, "render_type": "markdown", "content": "", "error": "无法解析飞书文档链接"}
        try:
            from agents.tools.feishu_doc_tools import (
                create_feishu_doc_client_for_project,
            )

            client = await create_feishu_doc_client_for_project(space)
            markdown, _blocks = await client.get_document_content(token)
            return {
                **base,
                "render_type": "markdown",
                "content": redact_secrets_in_text(markdown or ""),
            }
        except Exception as exc:  # noqa: BLE001 — fail-soft：返回错误不抛
            logger.warning(
                "artifact_view_doc_fetch_failed",
                artifact_id=str(artifact.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {**base, "render_type": "markdown", "content": "", "error": "飞书文档读取失败"}

    if carrier == "feishu_bitable":
        app_token, table_id = _parse_bitable_url(artifact.url)
        if not app_token or not table_id:
            return {**base, "render_type": "records", "records": [], "error": "无法解析飞书表格链接"}
        try:
            from services.feishu_bitable import create_bitable_client_for_project

            client = await create_bitable_client_for_project(space)
            data = await client.list_records(app_token, table_id)
            return {
                **base,
                "render_type": "records",
                "records": data.get("items", []),
                "has_more": data.get("has_more", False),
            }
        except Exception as exc:  # noqa: BLE001 — fail-soft：返回错误不抛
            logger.warning(
                "artifact_view_bitable_fetch_failed",
                artifact_id=str(artifact.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return {**base, "render_type": "records", "records": [], "error": "飞书表格读取失败"}

    return {**base, "render_type": "unknown"}
