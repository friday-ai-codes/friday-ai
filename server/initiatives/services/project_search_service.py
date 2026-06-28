"""ProjectSearchService —— 项目基础模糊搜索（WB-05，84-01；召回链路强制可观测）。

本期接「基础关键词」召回（项目域 DB：工作项 / API 清单 / 工件 / 记忆）+ 复用知识检索
（``DeliveryKnowledgeSearchService``）做项目域兜底，每条结果带 ``locator``（属哪个 repo/project）。
深度项目域 RAG 标注留 Phase 85（UI 预留 RAG 结果位）。

可观测性（强制召回链路）：发 ``project_search_started`` / ``project_search_completed``（带
``duration_ms`` / 召回条数 / 分层耗时 / top score）/ ``project_search_failed``；写 ``RetrievalTrace``
（payload 经 ledger ``redact_for_ledger`` 脱敏），``category=caller``、
``component=initiatives.search``。只读：不写业务表。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db.models import Q

from initiatives.models import (
    Artifact,
    ProjectDoc,
    ProjectMemory,
    ProjectMemoryStatus,
    ProjectStateApi,
    ProjectWorkItemLink,
)

logger = structlog.get_logger(__name__)

__all__ = ["ProjectSearchService"]

_COMPONENT = "initiatives.search"
_SOURCE = "project_search"
_SNIPPET_MAX = 160


class ProjectSearchService:
    """项目基础模糊搜索（关键词 + 知识检索兜底，只读，召回可观测）。"""

    async def search(
        self,
        *,
        project: Any,
        query: str,
        user: Any,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        started = time.monotonic()
        uid = getattr(user, "id", None)
        logger.info(
            "project_search_started",
            project_id=str(project.id),
            query_len=len(query),
            top_k=top_k,
            initiated_by_user_id=str(uid) if uid else "system",
            component=_COMPONENT,
            category="caller",
        )

        local_started = time.monotonic()
        local = await self._keyword_search(project, query, top_k)
        local_ms = round((time.monotonic() - local_started) * 1000, 2)

        knowledge_started = time.monotonic()
        knowledge = await self._knowledge_fallback(project, query, user, top_k)
        knowledge_ms = round((time.monotonic() - knowledge_started) * 1000, 2)

        results = (local + knowledge)[:top_k]
        top_score = results[0]["score"] if results else 0.0

        await self._record_trace(query, results, uid)

        logger.info(
            "project_search_completed",
            project_id=str(project.id),
            result_count=len(results),
            local_count=len(local),
            knowledge_count=len(knowledge),
            local_ms=local_ms,
            knowledge_ms=knowledge_ms,
            top_score=round(top_score, 4),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            initiated_by_user_id=str(uid) if uid else "system",
            component=_COMPONENT,
            category="caller",
        )
        return results

    # ---- 项目域关键词召回（DB 模糊匹配，只读）----

    @sync_to_async
    def _keyword_search(
        self, project: Any, query: str, top_k: int
    ) -> list[dict[str, Any]]:
        project_id = project.id
        locator = {
            "project_id": str(project_id),
            "project_name": getattr(project, "name", "") or "",
            "repository_id": None,
        }
        out: list[dict[str, Any]] = []

        # 工作项（title / 内部备注）。
        for link in (
            ProjectWorkItemLink.objects.filter(project_id=project_id)
            .select_related("work_item")
            .filter(
                Q(work_item__title__icontains=query)
                | Q(work_item__internal_note__icontains=query)
            )[:top_k]
        ):
            wi = link.work_item
            out.append(
                self._item(
                    kind="work_item",
                    title=wi.title,
                    snippet=wi.internal_note or wi.title,
                    query=query,
                    locator=locator,
                )
            )

        # API 清单（method/path）。
        for api in ProjectStateApi.objects.filter(project_id=project_id).filter(
            Q(method__icontains=query) | Q(path__icontains=query)
        )[:top_k]:
            out.append(
                self._item(
                    kind="state_api",
                    title=f"{api.method} {api.path}",
                    snippet=f"{api.method} {api.path} — {api.status}",
                    query=query,
                    locator=locator,
                )
            )

        # 工件（title / 正文引用）。
        for art in Artifact.objects.filter(project_id=project_id).filter(
            Q(title__icontains=query) | Q(content_ref__icontains=query)
        )[:top_k]:
            out.append(
                self._item(
                    kind="artifact",
                    title=art.title,
                    snippet=art.content_ref or art.title,
                    query=query,
                    locator=locator,
                )
            )

        # 项目记忆（active 正文）。
        for mem in ProjectMemory.objects.filter(
            project_id=project_id, status=ProjectMemoryStatus.ACTIVE
        ).filter(content__icontains=query)[:top_k]:
            out.append(
                self._item(
                    kind="memory",
                    title="项目记忆",
                    snippet=mem.content,
                    query=query,
                    locator=locator,
                )
            )

        # 工作区 5 文件正文（last_synced_snapshot；CTX-01 ProjectDoc 正文 grep 覆盖）。
        for doc in ProjectDoc.objects.filter(project_id=project_id).filter(
            last_synced_snapshot__icontains=query
        )[:top_k]:
            out.append(
                self._item(
                    kind="project_doc",
                    title=doc.doc_type,
                    snippet=doc.last_synced_snapshot or doc.doc_type,
                    query=query,
                    locator=locator,
                )
            )

        out.sort(key=lambda r: r["score"], reverse=True)
        return out[:top_k]

    @staticmethod
    def _item(
        *, kind: str, title: str, snippet: str, query: str, locator: dict[str, Any]
    ) -> dict[str, Any]:
        title = title or ""
        snippet = (snippet or "")[:_SNIPPET_MAX]
        # 标题命中权重高于正文命中（基础相关度，足够本期排序）。
        score = 1.0 if query.lower() in title.lower() else 0.6
        return {
            "kind": kind,
            "title": title,
            "snippet": snippet,
            "score": score,
            "source": "project_db",
            "locator": dict(locator),
        }

    # ---- 知识检索兜底（项目域 RAG，best-effort fail-soft）----

    async def _knowledge_fallback(
        self, project: Any, query: str, user: Any, top_k: int
    ) -> list[dict[str, Any]]:
        try:
            from knowledge.retrieval import DeliveryKnowledgeSearchService

            results = await DeliveryKnowledgeSearchService().search_similar(
                query,
                user=user,
                top_k=top_k,
                project_ids=[str(project.id)],
                # 项目搜索的知识兜底应纳入 Artifact/ProjectDoc 物化出的 DOCUMENT。
                include_document_kind=True,
            )
        except Exception as exc:  # noqa: BLE001 — 知识检索不可用 fail-soft（本期低量，不反噬）
            logger.warning(
                "project_search_knowledge_degraded",
                project_id=str(project.id),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="sampling",
            )
            return []

        out: list[dict[str, Any]] = []
        for r in results or []:
            entity = getattr(r, "entity", None)
            out.append(
                {
                    "kind": "knowledge",
                    "title": getattr(entity, "title", "") or "",
                    "snippet": "",
                    "score": float(getattr(r, "score", 0.0) or 0.0),
                    "source": "knowledge",
                    "locator": {
                        "project_id": str(
                            getattr(entity, "project_id", "") or project.id
                        ),
                        "project_name": getattr(project, "name", "") or "",
                        "repository_id": getattr(entity, "repository_id", None),
                    },
                }
            )
        return out

    # ---- 召回留痕（RetrievalTrace，ledger 内部 redact_for_ledger 脱敏）----

    @staticmethod
    async def _record_trace(
        query: str, results: list[dict[str, Any]], uid: Any
    ) -> None:
        try:
            from interactions.ledger import arecord_retrieval_trace

            await arecord_retrieval_trace(
                kind="chunk",
                payload={
                    "query": query,
                    "result_count": len(results),
                    "scores": [r["score"] for r in results[:10]],
                    "kinds": [r["kind"] for r in results[:10]],
                },
                user_id=str(uid) if uid else None,
                source=_SOURCE,
            )
        except Exception as exc:  # noqa: BLE001 — 留痕失败 best-effort 不反噬召回主流程
            logger.warning(
                "project_search_trace_failed",
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="sampling",
            )
