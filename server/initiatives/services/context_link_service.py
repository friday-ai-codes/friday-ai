"""ContextLinkService —— 「生成知识关联」统一编排 + 人工编辑收口。

feature list 补齐后一键生成项目的高相关上下文候选，四类目标一次跑完：

- **仓库**：委托 ``RepoAssociationService.propose``（``RepoAssociation`` 仍是项目↔仓库
  关联唯一真相源，INV-6，绝不旁路写）；接受/拒绝分别走 ``confirm_repos`` /
  ``reject_candidates``。
- **知识实体 / 外部工件**：feature 语料拼 query 走 ``DeliveryKnowledgeSearchService``
  混合检索（access_scope fail-closed），命中工件（``entity.artifact``）落 artifact 候选、
  其余落 knowledge 候选；排除本项目自身实体防自环。
- **MR/PR**：在空间仓库范围内按 feature 名命中 MR 标题（轻量相关性，无 LLM），
  排除已挂本项目的 MR。

候选统一落 ``ProjectContextLink(status=proposed, origin=ai)``，人审接受/拒绝；人工添加
``origin=manual`` 直接 accepted。**生成幂等纪律**：已 accepted/rejected/manual 的记录
绝不被再次生成覆盖或复活，仅 AI proposed 记录会被刷新。

接受 knowledge/artifact 候选时 best-effort 同步项目→实体 ``REFERENCES`` 图谱边
（复用 ``ProjectKnowledgeGraphService.link_knowledge``，失败吞掉不反噬）。

观测：结构化事件 ``context_link_generated/decided/added/removed``（caller，
+duration_ms/counts/initiated_by_user_id）；生成召回写 RetrievalTrace（kind=
``context_link``，best-effort）。日志仅记数量/长度，不回显 feature 正文。
"""

from __future__ import annotations

import uuid
from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from common.logging import redact_secrets_in_text
from interactions.ledger import arecord_retrieval_trace

logger = structlog.get_logger(__name__)

__all__ = ["ContextLinkError", "ContextLinkService"]

_COMPONENT = "context_link"
# 知识/工件候选检索 top_k（两类共享一次召回）。
_SEARCH_TOP_K = 12
# 单类候选数上限（面板展示预算）。
_KIND_LIMIT = 8
# MR 相关性扫描窗口（近更新优先）。
_MR_SCAN_LIMIT = 300
# 知识检索 query 字符预算（防超大 feature list 塞爆 embedding/rerank）。
_QUERY_CHAR_BUDGET = 2000


class ContextLinkError(Exception):
    """上下文关联业务异常（校验失败/目标不存在等，视图层转 400/404）。"""


class ContextLinkService:
    """项目上下文关联的单一写入/编排收口（无状态）。"""

    # ------------------------------------------------------------------
    # 生成（AI 候选编排）
    # ------------------------------------------------------------------

    async def agenerate(
        self,
        project: Any,
        *,
        user: Any,
        initiated_by_user_id: Any = None,
    ) -> dict[str, Any]:
        """一键生成四类关联候选；全程 fail-soft，单类失败不拖垮整体。"""
        started = perf_counter()
        user_label = str(initiated_by_user_id) if initiated_by_user_id is not None else "system"

        flat = await self._afeature_corpus(project)
        query = self._build_query(project, flat)

        repo_result = await self._propose_repos(
            project, flat, initiated_by_user_id=initiated_by_user_id
        )
        knowledge_cands, artifact_cands = await self._search_knowledge_candidates(
            project, query, user=user
        )
        mr_cands = await self._mr_candidates(project, flat)

        candidates = knowledge_cands + artifact_cands + mr_cands
        created, refreshed, skipped = await self._upsert_candidates(project, candidates, user_label)

        await self._record_trace(
            project=project,
            query=query,
            candidates=candidates,
            repo_result=repo_result,
            user_label=user_label,
        )

        summary = {
            "repo_candidates": len(repo_result.get("candidates") or []),
            "knowledge_candidates": len(knowledge_cands),
            "artifact_candidates": len(artifact_cands),
            "mr_candidates": len(mr_cands),
            "created": created,
            "refreshed": refreshed,
            "skipped": skipped,
        }
        logger.info(
            "context_link_generated",
            project_id=str(project.id),
            query_len=len(query),
            feature_count=len(flat),
            duration_ms=round((perf_counter() - started) * 1000, 2),
            initiated_by_user_id=user_label,
            component=_COMPONENT,
            category="caller",
            **summary,
        )
        return summary

    async def _afeature_corpus(self, project: Any) -> list[dict[str, Any]]:
        """feature list 树 → 扁平语料（module/name/description）；失败/为空返回 []。"""
        try:
            from initiatives.services.feature_list_service import FeatureListService

            tree = await FeatureListService().build_tree(project.id)
        except Exception as exc:  # noqa: BLE001 —— 构树失败 fail-soft，降级用项目名/描述
            logger.warning(
                "context_link_feature_corpus_failed",
                project_id=str(project.id),
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return []
        flat: list[dict[str, Any]] = []
        for mod in tree.get("modules", []):
            module_name = str(mod.get("module") or "")
            for feat in mod.get("features", []):
                name = str(feat.get("name") or "").strip()
                if not name:
                    continue
                acceptance = " ".join(
                    str(a).strip() for a in (feat.get("acceptance") or []) if str(a).strip()
                )
                flat.append({"module": module_name, "name": name, "description": acceptance[:200]})
        return flat

    @staticmethod
    def _build_query(project: Any, flat: list[dict[str, Any]]) -> str:
        """拼知识检索 query：feature 语料优先，缺省降级项目名+描述；截断预算。"""
        parts: list[str] = []
        seen: set[str] = set()
        for feat in flat:
            for key in ("module", "name", "description"):
                text = str(feat.get(key) or "").strip()
                if text and text not in seen:
                    seen.add(text)
                    parts.append(text)
        if not parts:
            name = str(getattr(project, "name", "") or "").strip()
            description = str(getattr(project, "description", "") or "").strip()
            parts = [p for p in (name, description) if p]
        return " ".join(parts)[:_QUERY_CHAR_BUDGET]

    async def _propose_repos(
        self, project: Any, flat: list[dict[str, Any]], *, initiated_by_user_id: Any
    ) -> dict[str, Any]:
        """委托 RepoAssociationService 选仓（唯一写入口，INV-6）；失败返回空提案。"""
        try:
            from initiatives.services.repo_association_service import (
                RepoAssociationService,
            )

            space = await sync_to_async(lambda: project.space)()
            return await RepoAssociationService().propose(
                space=space,
                features_flat=flat,
                project=project,
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception as exc:  # noqa: BLE001 —— 选仓失败 fail-soft，其余类型照常生成
            logger.warning(
                "context_link_repo_propose_failed",
                project_id=str(project.id),
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return {"candidates": [], "router_version": "failed", "auto_selected": False}

    async def _search_knowledge_candidates(
        self, project: Any, query: str, *, user: Any
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """混合检索知识实体 + 外部工件候选（一次召回两类分流）；失败返回空。"""
        if not query:
            return [], []
        try:
            from knowledge.retrieval import DeliveryKnowledgeSearchService

            hits = await DeliveryKnowledgeSearchService().search_similar(
                query,
                user=user,
                top_k=_SEARCH_TOP_K,
                include_document_kind=True,
            )
        except Exception as exc:  # noqa: BLE001 —— 检索失败 fail-soft
            logger.warning(
                "context_link_knowledge_search_failed",
                project_id=str(project.id),
                query_len=len(query),
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return [], []

        from initiatives.models import ContextLinkKind

        project_id = str(project.id)
        knowledge: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        for hit in hits:
            entity = hit.entity
            artifact_meta = entity.artifact or None
            if artifact_meta is not None:
                # 本项目自己的工件不作候选（已天然归属，防自环噪声）。
                if str(artifact_meta.get("project_id") or "") == project_id:
                    continue
                artifact_id = self._as_uuid(artifact_meta.get("artifact_id"))
                if artifact_id is None or len(artifacts) >= _KIND_LIMIT:
                    continue
                artifacts.append(
                    {
                        "target_kind": ContextLinkKind.ARTIFACT,
                        "target_id": artifact_id,
                        "title": entity.title or "",
                        "url": str(artifact_meta.get("url") or ""),
                        "score": float(hit.score),
                        "reason": self._hit_reason(hit, artifact_meta),
                    }
                )
                continue
            # 排除项目实体自身（kind=project 且 source_id 即本项目）。
            if entity.entity_kind == "project" and entity.source_id == project_id:
                continue
            if len(knowledge) >= _KIND_LIMIT:
                continue
            knowledge.append(
                {
                    "target_kind": ContextLinkKind.KNOWLEDGE,
                    "target_id": entity.entity_id,
                    "title": entity.title or "",
                    "url": "",
                    "score": float(hit.score),
                    "reason": self._hit_reason(hit, None),
                }
            )
        return knowledge, artifacts

    @staticmethod
    def _hit_reason(hit: Any, artifact_meta: dict | None) -> str:
        """生成候选理由（类型 + 分数 + 可选章节路径 / 工件类型），供面板展示。"""
        entity = hit.entity
        if artifact_meta is not None:
            type_name = str(artifact_meta.get("type_name") or "外部工件")
            project_name = str(artifact_meta.get("project_name") or "")
            suffix = f"，来自项目「{project_name}」" if project_name else ""
            return f"语义检索命中{type_name}（score {hit.score:.2f}{suffix}）"
        toc = " > ".join(hit.toc_path) if getattr(hit, "toc_path", None) else ""
        suffix = f"，章节 {toc}" if toc else ""
        return f"语义检索命中 {entity.entity_kind}（score {hit.score:.2f}{suffix}）"

    async def _mr_candidates(
        self, project: Any, flat: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """空间仓库范围内按 feature 名命中 MR 标题（轻量相关性）；失败返回空。"""
        names = [str(f.get("name") or "").strip().lower() for f in flat]
        names = [n for n in names if len(n) >= 2]
        if not names:
            return []
        try:
            return await self._mr_candidates_sync(project, names)
        except Exception as exc:  # noqa: BLE001 —— MR 匹配失败 fail-soft
            logger.warning(
                "context_link_mr_match_failed",
                project_id=str(project.id),
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="caller",
            )
            return []

    @sync_to_async
    def _mr_candidates_sync(self, project: Any, feature_names: list[str]) -> list[dict[str, Any]]:
        from initiatives.models import ContextLinkKind, MergeRequest

        repo_ids = list(project.space.repositories.values_list("id", flat=True))
        if not repo_ids:
            return []
        mrs = (
            MergeRequest.objects.filter(repository_id__in=repo_ids)
            .exclude(project_id=project.id)
            .exclude(title="")
            .order_by("-updated_at")[:_MR_SCAN_LIMIT]
        )
        scored: list[tuple[int, Any, list[str]]] = []
        for mr in mrs:
            title = mr.title.lower()
            matched = [n for n in feature_names if n in title]
            if matched:
                scored.append((len(matched), mr, matched))
        scored.sort(key=lambda item: item[0], reverse=True)
        out: list[dict[str, Any]] = []
        for match_count, mr, matched in scored[:_KIND_LIMIT]:
            hint = "、".join(matched[:3])
            out.append(
                {
                    "target_kind": ContextLinkKind.MERGE_REQUEST,
                    "target_id": mr.id,
                    "title": mr.title,
                    "url": mr.url,
                    "score": float(match_count),
                    "reason": f"MR 标题命中功能点：{hint}",
                }
            )
        return out

    @sync_to_async
    def _upsert_candidates(
        self, project: Any, candidates: list[dict[str, Any]], user_label: str
    ) -> tuple[int, int, int]:
        """候选落库：新建 proposed；仅刷新 AI proposed；accepted/rejected/manual 绝不动。"""
        from initiatives.models import (
            ContextLinkOrigin,
            ContextLinkStatus,
            ProjectContextLink,
        )

        created = refreshed = skipped = 0
        for cand in candidates:
            try:
                existing = ProjectContextLink.objects.filter(
                    project=project,
                    target_kind=cand["target_kind"],
                    target_id=cand["target_id"],
                ).first()
                if existing is None:
                    ProjectContextLink.objects.create(
                        project=project,
                        target_kind=cand["target_kind"],
                        target_id=cand["target_id"],
                        title=str(cand.get("title") or "")[:500],
                        url=str(cand.get("url") or "")[:1000],
                        score=float(cand.get("score") or 0.0),
                        reason=str(cand.get("reason") or ""),
                        origin=ContextLinkOrigin.AI,
                        status=ContextLinkStatus.PROPOSED,
                        initiated_by_user_id=user_label,
                    )
                    created += 1
                elif (
                    existing.status == ContextLinkStatus.PROPOSED
                    and existing.origin == ContextLinkOrigin.AI
                ):
                    existing.title = str(cand.get("title") or "")[:500]
                    existing.url = str(cand.get("url") or "")[:1000]
                    existing.score = float(cand.get("score") or 0.0)
                    existing.reason = str(cand.get("reason") or "")
                    existing.updated_at = timezone.now()
                    existing.save(update_fields=["title", "url", "score", "reason", "updated_at"])
                    refreshed += 1
                else:
                    # accepted（含 manual）/rejected：人工裁决优先，生成不覆盖不复活。
                    skipped += 1
            except Exception as exc:  # noqa: BLE001 —— 单候选落库失败 fail-soft
                logger.warning(
                    "context_link_candidate_persist_failed",
                    target_kind=str(cand.get("target_kind")),
                    reason=redact_secrets_in_text(str(exc)),
                    error_type=type(exc).__name__,
                    component=_COMPONENT,
                    category="caller",
                )
                continue
        return created, refreshed, skipped

    async def _record_trace(
        self,
        *,
        project: Any,
        query: str,
        candidates: list[dict[str, Any]],
        repo_result: dict[str, Any],
        user_label: str,
    ) -> None:
        """生成召回留痕（best-effort，观测失败绝不反噬生成）。"""
        try:
            await arecord_retrieval_trace(
                kind="context_link",
                payload={
                    "project_id": str(project.id),
                    "query": query,
                    "repo_candidates": repo_result.get("candidates") or [],
                    "candidates": [
                        {
                            "target_kind": str(c.get("target_kind")),
                            "target_id": str(c.get("target_id")),
                            "title": str(c.get("title") or ""),
                            "score": float(c.get("score") or 0.0),
                        }
                        for c in candidates
                    ],
                },
                user_id=user_label,
                source=_COMPONENT,
            )
        except Exception as exc:  # noqa: BLE001 —— 观测 best-effort，吞掉一切
            logger.debug(
                "context_link_observability_failed",
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="sampling",
            )

    # ------------------------------------------------------------------
    # 查询 / 人工编辑
    # ------------------------------------------------------------------

    @sync_to_async
    def list_links(self, project: Any) -> dict[str, Any]:
        """面板数据：``links``（本模型全量）+ ``repos``（RepoAssociation 非 rejected + proposed 全貌）。"""
        from initiatives.models import ProjectContextLink, RepoAssociation

        links = list(
            ProjectContextLink.objects.filter(project=project).order_by(
                "status", "-score", "-created_at"
            )
        )
        repos: list[dict[str, Any]] = []
        associations = (
            RepoAssociation.objects.filter(project=project)
            .select_related("repository")
            .order_by("-score")
        )
        for assoc in associations:
            repos.append(
                {
                    "association_id": str(assoc.id),
                    "repository_id": str(assoc.repository_id),
                    "repository_name": assoc.repository.name,
                    "git_url": assoc.repository.git_url,
                    "status": assoc.status,
                    "score": assoc.score,
                    "confidence": assoc.confidence,
                    "reason": assoc.routed_reason,
                }
            )
        return {"links": links, "repos": repos}

    async def adecide(
        self,
        project: Any,
        link_id: Any,
        *,
        action: str,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> Any:
        """接受/拒绝一条候选（幂等）；接受 knowledge/artifact 时 best-effort 同步图谱边。"""
        from initiatives.models import ContextLinkStatus, ProjectContextLink

        if action not in ("accept", "reject"):
            raise ContextLinkError("action 必须是 accept 或 reject")
        link = await ProjectContextLink.objects.filter(pk=link_id, project=project).afirst()
        if link is None:
            raise ContextLinkError("关联记录不存在")
        user_label = str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        new_status = (
            ContextLinkStatus.ACCEPTED if action == "accept" else ContextLinkStatus.REJECTED
        )
        await ProjectContextLink.objects.filter(pk=link.pk).aupdate(
            status=new_status, updated_at=timezone.now()
        )
        link.status = new_status
        logger.info(
            "context_link_decided",
            project_id=str(project.id),
            link_id=str(link.pk),
            target_kind=link.target_kind,
            action=action,
            initiated_by_user_id=user_label,
            component=_COMPONENT,
            category="caller",
        )
        if action == "accept":
            await self._sync_graph_edge(project, link, actor=actor, user_label=user_label)
        return link

    async def aadd_manual(
        self,
        project: Any,
        *,
        target_kind: str,
        target_id: Any = None,
        title: str = "",
        url: str = "",
        reason: str = "",
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> Any:
        """人工添加关联：目标存在性校验 + 幂等 upsert，直接 accepted（origin=manual）。"""
        from initiatives.models import ContextLinkKind

        if target_kind not in ContextLinkKind.values:
            raise ContextLinkError(f"不支持的关联类型：{target_kind}")
        if target_kind == ContextLinkKind.EXTERNAL:
            if not (title or "").strip() or not (url or "").strip():
                raise ContextLinkError("外部链接需提供标题与 url")
            target_uuid = None
        else:
            target_uuid = self._as_uuid(target_id)
            if target_uuid is None:
                raise ContextLinkError("target_id 必须为合法 UUID")
            resolved_title = await self._averify_target(target_kind, target_uuid)
            title = (title or "").strip() or resolved_title
        user_label = str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        link = await self._aupsert_manual(
            project,
            target_kind=target_kind,
            target_id=target_uuid,
            title=title,
            url=url,
            reason=reason,
            actor=actor,
            user_label=user_label,
        )
        logger.info(
            "context_link_added",
            project_id=str(project.id),
            link_id=str(link.pk),
            target_kind=target_kind,
            initiated_by_user_id=user_label,
            component=_COMPONENT,
            category="caller",
        )
        if target_kind in ("knowledge", "artifact"):
            await self._sync_graph_edge(project, link, actor=actor, user_label=user_label)
        return link

    @sync_to_async
    def _aupsert_manual(
        self,
        project: Any,
        *,
        target_kind: str,
        target_id: uuid.UUID | None,
        title: str,
        url: str,
        reason: str,
        actor: Any,
        user_label: str,
    ) -> Any:
        from initiatives.models import (
            ContextLinkOrigin,
            ContextLinkStatus,
            ProjectContextLink,
        )

        defaults = {
            "title": (title or "")[:500],
            "url": (url or "")[:1000],
            "reason": reason or "",
            "origin": ContextLinkOrigin.MANUAL,
            "status": ContextLinkStatus.ACCEPTED,
            "initiated_by_user_id": user_label,
            "created_by": actor if getattr(actor, "pk", None) else None,
        }
        if target_id is None:
            # external 无幂等键，直接新建。
            return ProjectContextLink.objects.create(
                project=project, target_kind=target_kind, target_id=None, **defaults
            )
        link, _created = ProjectContextLink.objects.update_or_create(
            project=project,
            target_kind=target_kind,
            target_id=target_id,
            defaults=defaults,
        )
        return link

    async def _averify_target(self, target_kind: str, target_id: uuid.UUID) -> str:
        """校验目标存在并返回标题快照（knowledge/artifact/merge_request）。"""
        from initiatives.models import Artifact, ContextLinkKind, MergeRequest

        if target_kind == ContextLinkKind.KNOWLEDGE:
            from knowledge.models import KnowledgeEntity

            entity = await KnowledgeEntity.objects.filter(id=target_id).afirst()
            if entity is None:
                raise ContextLinkError(f"知识实体 {target_id} 不存在")
            return entity.title or str(target_id)
        if target_kind == ContextLinkKind.ARTIFACT:
            artifact = await Artifact.objects.filter(id=target_id).afirst()
            if artifact is None:
                raise ContextLinkError(f"工件 {target_id} 不存在")
            return artifact.title
        if target_kind == ContextLinkKind.MERGE_REQUEST:
            mr = await MergeRequest.objects.filter(id=target_id).afirst()
            if mr is None:
                raise ContextLinkError(f"MR {target_id} 不存在")
            return mr.title or mr.url
        return str(target_id)

    async def aremove(
        self, project: Any, link_id: Any, *, initiated_by_user_id: Any = None
    ) -> bool:
        """删除一条关联记录（人工编辑；被删的 AI 候选后续生成可能重新提议）。"""
        from initiatives.models import ProjectContextLink

        user_label = str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        deleted, _detail = await ProjectContextLink.objects.filter(
            pk=link_id, project=project
        ).adelete()
        if deleted:
            logger.info(
                "context_link_removed",
                project_id=str(project.id),
                link_id=str(link_id),
                initiated_by_user_id=user_label,
                component=_COMPONENT,
                category="caller",
            )
        return bool(deleted)

    async def adecide_repo(
        self,
        project: Any,
        repository_id: Any,
        *,
        action: str,
        initiated_by_user_id: Any = None,
    ) -> bool:
        """仓库候选裁决：accept → confirm_repos；reject → reject_candidates（均走唯一收口）。"""
        from initiatives.services.repo_association_service import RepoAssociationService

        if action not in ("accept", "reject"):
            raise ContextLinkError("action 必须是 accept 或 reject")
        service = RepoAssociationService()
        if action == "accept":
            confirmed = await service.confirm_repos(
                project=project,
                repo_ids=[repository_id],
                initiated_by_user_id=initiated_by_user_id,
            )
            return bool(confirmed)
        rejected = await service.reject_candidates(
            project=project,
            repo_ids=[repository_id],
            initiated_by_user_id=initiated_by_user_id,
        )
        return rejected > 0

    # ------------------------------------------------------------------
    # 图谱同步（best-effort）
    # ------------------------------------------------------------------

    async def _sync_graph_edge(
        self, project: Any, link: Any, *, actor: Any, user_label: str
    ) -> None:
        """接受 knowledge/artifact 关联时同步项目→实体 REFERENCES 边（失败吞掉）。"""
        from initiatives.models import ContextLinkKind

        if link.target_kind not in (ContextLinkKind.KNOWLEDGE, ContextLinkKind.ARTIFACT):
            return
        try:
            entity_id = link.target_id
            if link.target_kind == ContextLinkKind.ARTIFACT:
                from knowledge.models import EntityKind, generate_entity_id

                entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(link.target_id))
            from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService

            await ProjectKnowledgeGraphService().link_knowledge(
                project=project,
                entity_id=entity_id,
                relation="REFERENCES",
                actor=actor,
                initiated_by_user_id=user_label,
            )
        except Exception as exc:  # noqa: BLE001 —— 图谱同步 best-effort，绝不反噬审阅
            logger.debug(
                "context_link_graph_sync_failed",
                link_id=str(link.pk),
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="sampling",
            )

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _as_uuid(value: Any) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            return None
