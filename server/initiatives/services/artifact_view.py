"""工件在线查看读取/渲染（ARTIFACT-03，后端 API；富前端留 Phase 81 UI-03）。

按载体返回可在线查看的结构化数据：
- ``feishu_doc``：经既有 ``FeishuDocClient.get_document_content`` 读取渲染为 markdown；
- ``feishu_bitable``：经既有 ``BitableClient.list_records`` 读取记录（原始 data，列解析留 v2）；
- ``external_link``：返回元数据 + 跳转 url（外链不读正文）；
- ``markdown`` / ``repo_file``：返回 ``content_ref``（内部工件正文，可读可写经 ArtifactService）。
  其中 ``feature_list`` 类型工件的 ``content_ref`` 是归一 JSON（``{"modules": [...]}``，见
  ``FeatureListService.aset_feature_list`` manual/paste/gitlab 模式）——直接回显是一坨原始
  JSON，在线查看时转成「模块 → 功能点 → 验收」的可读 markdown（转换失败回退原文）。

**只读**（不写库，无 INV-6 约束）。飞书正文经 ``redact_secrets_in_text`` 脱敏；拉取失败
fail-soft（返回 ``error`` 字段 + url，不抛、不阻断查看其他工件）。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = ["aget_artifact_view"]


def _as_bullet(text: str) -> str:
    """归一验收项为列表项：已带 -/* 前缀的保留，多行内容缩进进同一列表项。"""
    t = text.strip()
    if not t.startswith(("- ", "* ")):
        t = f"- {t}"
    return t.replace("\n", "\n  ")


def _strip_duplicate_heading(source: str, name: str) -> str:
    """去掉 source 原文段首与功能点名重复的 markdown 标题行（避免标题两连）。"""
    first_line, _sep, rest = source.partition("\n")
    stripped = first_line.strip()
    if stripped.startswith("#") and name and name in stripped:
        return rest.strip()
    return source


def _feature_list_markdown(content: str) -> str | None:
    """feature_list 工件 ``content_ref`` JSON → 可读 markdown；非该结构返回 None（回退原文）。

    结构契约见 ``FeatureListService._normalize_manual_modules``：
    ``{"modules": [{"module", "summary"?, "features": [{"name", "acceptance", "status"?, "source"?}]}]}``。
    优先渲染 ``source``（解析留存的原文片段，本身是 markdown）；否则渲染验收列表。
    """
    try:
        data = json.loads(content or "")
    except (TypeError, ValueError):
        return None
    modules = data.get("modules") if isinstance(data, dict) else None
    if not isinstance(modules, list):
        return None

    blocks: list[str] = []
    feat_no = 0
    for mod in modules:
        if not isinstance(mod, dict):
            continue
        module_name = str(mod.get("module") or "未分组").strip() or "未分组"
        blocks.append(f"## {module_name}")
        summary = str(mod.get("summary") or "").strip()
        if summary:
            blocks.append(f"> {summary}")
        features = [f for f in (mod.get("features") or []) if isinstance(f, dict)]
        if not features:
            blocks.append("_该模块暂无功能点_")
            continue
        for feat in features:
            name = str(feat.get("name") or "").strip()
            if not name:
                continue
            feat_no += 1
            status = str(feat.get("status") or "").strip()
            heading = f"### {feat_no}. {name}"
            if status:
                heading += f"（{status}）"
            blocks.append(heading)
            source = str(feat.get("source") or "").strip()
            if source:
                blocks.append(_strip_duplicate_heading(source, name))
                continue
            acceptance = [str(a).strip() for a in (feat.get("acceptance") or []) if str(a).strip()]
            if acceptance:
                blocks.append("**验收标准**")
                blocks.append("\n".join(_as_bullet(a) for a in acceptance))
    return "\n\n".join(blocks) if blocks else None


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
        content = artifact.content_ref or ""
        # feature_list 工件存的是归一 JSON——在线查看转可读 markdown（失败回退原文）。
        if getattr(getattr(artifact, "type", None), "key", "") == "feature_list":
            rendered = _feature_list_markdown(content)
            if rendered is not None:
                content = rendered
        return {
            **base,
            "render_type": "markdown" if carrier == "markdown" else "text",
            "content": redact_secrets_in_text(content),
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
            markdown, _blocks = await client.get_document_content_by_url(artifact.url or token)
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
