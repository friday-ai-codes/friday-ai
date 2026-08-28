"""Feishu work item context builder for MCP tools."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project
from interactions.models import InteractionRun
from interactions.redaction import redact_for_ledger
from mcp_tools.models import McpWorkItemContext
from projects.models import Space
from services.feishu import create_feishu_client_for_project
from services.feishu_doc import (
    DocumentNotFoundError,
    FeishuDocAPIError,
    PermissionDeniedError,
    RateLimitError,
    truncate_doc_content,
)


class WorkItemContextError(Exception):
    """Recoverable setup or upstream error while building work item context."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class WorkItemContextResult:
    artifact: McpWorkItemContext
    output: dict[str, Any]
    traces: list[tuple[str, dict[str, Any]]]


_URL_RE = re.compile(r"https?://[^\s<>)\"']+")
_DOC_PATH_RE = re.compile(r"/(?:docx|docs|doc|wiki)/([A-Za-z0-9_-]+)")
_PLAIN_DOC_RE = re.compile(r"\b(?:doxcn|doccn|docx|wiki)[A-Za-z0-9_-]{6,}\b")


def extract_feishu_doc_refs(value: Any) -> list[dict[str, str]]:
    """Extract Feishu document references from nested Feishu field values."""

    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(document_id: str, url: str = "") -> None:
        doc = document_id.strip().strip(".,;:，。；：")
        if not doc:
            return
        key = (doc, url)
        if key in seen:
            return
        seen.add(key)
        refs.append({"document_id": doc, "url": url})

    def _scan_text(text: str) -> None:
        for raw_url in _URL_RE.findall(text):
            url = raw_url.rstrip(".,;:，。；：")
            match = _DOC_PATH_RE.search(url)
            if match:
                _add(match.group(1), url)
        for doc_id in _PLAIN_DOC_RE.findall(text):
            _add(doc_id)

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            _scan_text(node)
        elif isinstance(node, dict):
            for nested in node.values():
                _walk(nested)
        elif isinstance(node, (list, tuple)):
            for nested in node:
                _walk(nested)

    _walk(value)
    return refs


async def _resolve_project(
    *,
    project_id: str | None,
    project_key: str,
) -> Space:
    if project_id:
        project = await Space.objects.filter(id=project_id).afirst()
        if project is None:
            raise WorkItemContextError("project_not_found", "项目不存在")
        return project
    project = await Space.objects.filter(feishu_project_key=project_key).afirst()
    if project is None:
        raise WorkItemContextError(
            "project_not_found",
            "找不到匹配 feishu_project_key 的 Friday 项目，请提供 project_id 或配置项目飞书空间",
        )
    return project


async def _resolve_blueprint_project_id(context: McpWorkItemContext) -> str:
    """把 legacy Space 上下文换算为 canonical initiatives.Project UUID。"""
    try:
        from services.process_runtime.blueprint_intake import aresolve_project_id

        return await aresolve_project_id(entry="mcp", work_item_context=context)
    except Exception:  # noqa: BLE001 — 上下文快照仍可返回，蓝图入口自身继续 fail-closed
        return ""


def _json_from_raw(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw_response": raw}
    return data if isinstance(data, dict) else {"raw_response": data}


def _owners_from_fields(fields: dict[str, Any]) -> list[dict[str, Any]]:
    owners: list[dict[str, Any]] = []
    owner = fields.get("owner")
    if owner:
        owners.append({"field": "owner", "value": owner})
    role_owners = fields.get("role_owners")
    if isinstance(role_owners, list):
        for item in role_owners:
            if isinstance(item, dict):
                owners.append(
                    {
                        "field": "role_owners",
                        "role": item.get("role", ""),
                        "owners": item.get("owners") or [],
                    }
                )
    return owners


async def _read_documents(project: Space, refs: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not refs:
        return []
    try:
        client = await create_feishu_doc_client_for_project(project)
    except ValueError as exc:
        return [
            {
                **ref,
                "status": "skipped",
                "error_code": "doc_client_not_configured",
                "error": str(exc),
            }
            for ref in refs
        ]

    documents: list[dict[str, Any]] = []
    for ref in refs:
        document_id = ref["document_id"]
        try:
            markdown, blocks = await client.get_document_content(document_id)
            content, truncated = truncate_doc_content(markdown)
            documents.append(
                {
                    **ref,
                    "status": "ok",
                    "content": content,
                    "truncated": truncated,
                    "block_count": len(blocks),
                    "content_length": len(markdown),
                }
            )
        except PermissionDeniedError as exc:
            documents.append({**ref, "status": "permission_denied", "error": str(exc)})
        except DocumentNotFoundError as exc:
            documents.append({**ref, "status": "not_found", "error": str(exc)})
        except RateLimitError as exc:
            documents.append({**ref, "status": "rate_limited", "error": str(exc)})
        except FeishuDocAPIError as exc:
            documents.append({**ref, "status": "error", "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - one bad document should not drop the work item snapshot.
            documents.append({**ref, "status": "error", "error": str(exc)})
    return documents


async def build_work_item_context(
    *,
    run: InteractionRun,
    project_id: str | None,
    project_key: str,
    work_item_type: str,
    work_item_id: int,
    fields: list[str],
    include_comments: bool,
) -> WorkItemContextResult:
    project = await _resolve_project(project_id=project_id, project_key=project_key)
    effective_project_key = project_key or str(project.feishu_project_key or "")
    try:
        client = create_feishu_client_for_project(project)
    except ValueError as exc:
        raise WorkItemContextError("feishu_project_not_configured", str(exc)) from exc

    try:
        item = await client.get_work_item(
            effective_project_key,
            work_item_id,
            work_item_type=work_item_type,
            fields=fields or None,
        )
    except Exception as exc:  # noqa: BLE001 - upstream Feishu errors are surfaced as MCP errors.
        raise WorkItemContextError("feishu_work_item_error", str(exc)) from exc

    relation_error = ""
    try:
        relations = await client.get_work_item_relations(
            effective_project_key,
            item.id,
            work_item_type,
        )
    except Exception as exc:  # noqa: BLE001 - relation lookup is useful but not required for context.
        relations = []
        relation_error = str(exc)

    comment_error = ""
    if include_comments:
        try:
            comments = await client.get_comments(effective_project_key, item.id, work_item_type)
        except Exception as exc:  # noqa: BLE001 - comments should degrade the snapshot to partial.
            comments = []
            comment_error = str(exc)
    else:
        comments = []
    doc_refs = extract_feishu_doc_refs(
        {
            "description": item.description,
            "fields": item.fields,
            "comments": comments,
        }
    )
    documents = await _read_documents(project, doc_refs)
    owners = _owners_from_fields(item.fields)
    work_item = {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "status": item.status,
        "project_key": item.project_key,
        "work_item_type": item.work_item_type,
        "owners": owners,
        "fields": item.fields,
        "source": {
            "project_key": effective_project_key,
            "work_item_type": work_item_type,
            "work_item_id": item.id,
            "url": f"https://project.feishu.cn/{effective_project_key}/issue/detail/{item.id}",
        },
    }
    context = {
        "work_item": work_item,
        "relations": relations,
        "documents": documents,
        "comments": comments,
        "summary": {
            "relation_count": len(relations),
            "document_count": len(documents),
            "document_ok_count": sum(1 for doc in documents if doc.get("status") == "ok"),
            "comment_count": len(comments),
            "relation_error": relation_error,
            "comment_error": comment_error,
        },
    }
    has_doc_errors = any(doc.get("status") not in ("ok",) for doc in documents)
    has_context_errors = bool(relation_error or comment_error)
    status = (
        McpWorkItemContext.Status.PARTIAL
        if has_doc_errors or has_context_errors
        else McpWorkItemContext.Status.COMPLETED
    )
    stored_owners = redact_for_ledger(owners)
    stored_fields = redact_for_ledger(item.fields)
    stored_relations = redact_for_ledger(relations)
    stored_documents = redact_for_ledger(documents)
    stored_comments = redact_for_ledger(comments)
    stored_context = redact_for_ledger(context)
    stored_raw_response = redact_for_ledger(_json_from_raw(item.raw_response))
    safe_work_item = redact_for_ledger(work_item)
    artifact = await McpWorkItemContext.objects.acreate(
        run=run,
        space=project,
        feishu_project_key=effective_project_key,
        work_item_type=work_item_type,
        work_item_id=item.id,
        name=item.name[:500],
        status=status,
        work_item_status=item.status,
        description=redact_for_ledger(item.description),
        owners=stored_owners,
        fields=stored_fields,
        relations=stored_relations,
        documents=stored_documents,
        comments=stored_comments,
        context=stored_context,
        raw_response=stored_raw_response,
    )
    blueprint_project_id = await _resolve_blueprint_project_id(artifact)
    output = {
        "context_id": str(artifact.id),
        # legacy alias：历史调用方的 project_id 实际是 projects.Space.id。
        "project_id": str(project.id),
        "space_id": str(project.id),
        "blueprint_project_id": blueprint_project_id,
        "work_item": safe_work_item,
        "relations": stored_relations,
        "documents": stored_documents,
        "comments": stored_comments,
        "context": stored_context,
        "status": status,
        "run_id": str(run.run_id),
    }
    traces = [
        (
            "file",
            {
                "source": "feishu_work_item",
                "project_key": effective_project_key,
                "work_item_type": work_item_type,
                "work_item_id": item.id,
                "name": item.name,
                "status": item.status,
            },
        )
    ]
    traces.extend(
        (
            "file",
            {
                "source": "feishu_document",
                "document_id": doc.get("document_id", ""),
                "url": doc.get("url", ""),
                "status": doc.get("status", ""),
            },
        )
        for doc in documents
    )
    return WorkItemContextResult(artifact=artifact, output=output, traces=traces)
