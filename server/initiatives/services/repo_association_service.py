"""RepoAssociationService —— 业务↔仓库关联选仓编排收口（REPO-01，88-02）。

把 Phase 87 拆分提案语料经 ``RepoRouterV2`` 做 COMBINED 选仓（语义 hybrid + 活跃度
facet 降权 + LLM 树推理 三合一，D-01/D-04，**绝不自写打分**），候选落
``RepoAssociation``(status=proposed)。是「项目↔仓库关联」的**单一写入收口**
（INV-6，由 ``test_repo_association_inv6_guard`` grep 守护）：工作流节点、AI 会话工具、
卡片回调三入口共用本服务，绝不旁路写 ``RepoAssociation`` / ``RepoVerifyTask``。

两段职责：

- :meth:`propose`：解析候选范围（``_resolve_repository_ids`` 限定 ``Space.repositories``，
  防跨项目噪声 Pitfall 6）→ 拼 query（``_build_query`` 消费 ``features_flat`` 的
  name/description/module，D-06）→ ``RepoRouterV2.route`` 选仓 → 候选落 proposed。
- :meth:`refine`：把用户澄清 ``extra_instruction`` 并进 query 重 route（多轮 RAG 细化，
  D-01 首版 = 重 route），刷新 proposed 候选集；每轮各写一条 RetrievalTrace。

观测（强制，``RepoRouterV2`` 历史缺埋点 Pitfall 7）：route 调用包
``use_call_source(CallSource.AUX_REPO_ROUTER)``；route 后写
``arecord_retrieval_trace(kind="routing", payload={query, candidates})``（payload 入库
经 ledger 内部 ``redact_for_ledger``），多轮每轮各写一条（覆盖 AI 对话召回链）。结构化
事件 ``repo_association_proposed`` / ``_refined``（caller，+duration_ms / candidate_count /
router_version / initiated_by_user_id），埋点失败记 ``_route_observability_failed``
（sampling, debug）。日志仅记 query 长度 / 候选数，不回显 feature 正文。

全程 fail-soft：``RepoRouterV2`` 自带降级链（LLM 失败→Stage0、无命中→v1）；候选范围为空
/ query 为空 / route 候选为空 → 返回空提案不抛；``arecord_retrieval_trace`` best-effort
不反噬选仓。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from agents.call_source import CallSource, use_call_source
from common.logging import redact_secrets_in_text
from interactions.ledger import arecord_retrieval_trace

logger = structlog.get_logger(__name__)

__all__ = ["RepoAssociationService"]

_COMPONENT = "repo_association"
# 候选数上限（对齐 RepoRouterV2Adapter 默认；卡片展示 + 逐仓深验数量预算）。
_TOP_K = 5
# query 字符预算（防超大 feature list 塞爆 LLM 上下文，T-88-02-DOS）。
_QUERY_CHAR_BUDGET = 4000


class RepoAssociationService:
    """业务↔仓库关联选仓的单一编排收口（无状态，多入口共用，INV-6）。"""

    async def propose(
        self,
        *,
        space: Any,
        feature_list: Any = None,
        features_flat: list[dict[str, Any]] | None = None,
        project: Any = None,
        initiated_by_user_id: Any = None,
    ) -> dict[str, Any]:
        """COMBINED 选仓提案：拼 query → RepoRouterV2.route → 候选落 proposed。

        Args:
            space: ``projects.models.Space`` 实例（候选范围 = ``Space.repositories``）。
            feature_list: Phase 87 拆分提案（``{modules, features_flat, ...}`` 或
                ``features_flat`` 列表）；与 ``features_flat`` 二选一。
            features_flat: 直接给定的 feature 扁平列表（优先于 ``feature_list``）。
            project: ``initiatives.Project`` 实例；缺省时从 ``space`` 解析（落库锚点）。
            initiated_by_user_id: 触发用户 id（审计/可观测绑定；缺记 system）。

        Returns:
            ``{candidates, router_version, auto_selected, query_len}``；候选为
            ``[{repo_id, repo_name, score, confidence, reason, matched_node_paths}]``。
        """
        flat = self._normalize_features(feature_list, features_flat)
        query = self._build_query(flat)
        return await self._route_and_persist(
            space=space,
            project=project,
            query=query,
            initiated_by_user_id=initiated_by_user_id,
            event="repo_association_proposed",
            round_no=1,
        )

    async def refine(
        self,
        *,
        space: Any,
        project: Any = None,
        feature_list: Any = None,
        features_flat: list[dict[str, Any]] | None = None,
        extra_instruction: str | None = None,
        initiated_by_user_id: Any = None,
        round_no: int = 2,
    ) -> dict[str, Any]:
        """多轮 RAG 细化：把 ``extra_instruction`` 并进 query 重 route，刷新候选。

        用户输入仅作「筛选/澄清要求」附加约束并进 query（V5 输入校验——不构造执行
        指令）；复用 propose 的 route + 观测 + 落库（命中更新、新候选新建，旧候选保留但
        不在新结果中）。每轮各写一条 RetrievalTrace。
        """
        flat = self._normalize_features(feature_list, features_flat)
        query = self._build_query(flat, extra_instruction=extra_instruction)
        return await self._route_and_persist(
            space=space,
            project=project,
            query=query,
            initiated_by_user_id=initiated_by_user_id,
            event="repo_association_refined",
            round_no=round_no,
        )

    # ------------------------------------------------------------------
    # 核心编排（propose / refine 共用）
    # ------------------------------------------------------------------

    async def _route_and_persist(
        self,
        *,
        space: Any,
        project: Any,
        query: str,
        initiated_by_user_id: Any,
        event: str,
        round_no: int,
    ) -> dict[str, Any]:
        started = perf_counter()
        user_label = (
            str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        )

        repo_ids = await self._resolve_repository_ids(space, project)
        # 候选范围限定 Space.repositories：为空或无 query 时绝不全库检索（Pitfall 6），
        # 直接返回空提案（fail-soft）。
        if not repo_ids or not query:
            logger.info(
                event,
                candidate_count=0,
                router_version="skipped",
                round=round_no,
                query_len=len(query),
                scoped_repo_count=len(repo_ids or []),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                initiated_by_user_id=user_label,
                component=_COMPONENT,
                category="caller",
            )
            return {
                "candidates": [],
                "router_version": "skipped",
                "auto_selected": False,
                "query_len": len(query),
            }

        # COMBINED 选仓：复用 RepoRouterV2（语义+活跃度+LLM 三合一），包 call_source 补埋点。
        from codegraph.services.repo_router_v2 import RepoRouterV2

        with use_call_source(CallSource.AUX_REPO_ROUTER):
            result = await RepoRouterV2.route(
                query, top_k=_TOP_K, repository_ids=repo_ids, use_llm=True
            )

        candidates = [self._candidate_dict(c) for c in result.candidates]

        # 召回留痕（routing 链，覆盖 AI 对话）；best-effort 不反噬选仓。
        await self._record_routing_trace(
            query=query,
            result=result,
            user_label=user_label,
        )

        # 候选落 RepoAssociation(proposed)（**唯一**写入口，INV-6）；无 project 仅返回不落库。
        persisted = await self._persist_candidates(
            space=space,
            project=project,
            candidates=candidates,
            initiated_by_user_id=user_label,
        )

        logger.info(
            event,
            candidate_count=len(candidates),
            persisted_count=persisted,
            router_version=result.router_version,
            auto_selected=result.auto_selected,
            round=round_no,
            query_len=len(query),
            scoped_repo_count=len(repo_ids),
            duration_ms=round((perf_counter() - started) * 1000, 2),
            initiated_by_user_id=user_label,
            component=_COMPONENT,
            category="caller",
        )
        return {
            "candidates": candidates,
            "router_version": result.router_version,
            "auto_selected": result.auto_selected,
            "query_len": len(query),
        }

    async def _record_routing_trace(
        self, *, query: str, result: Any, user_label: str
    ) -> None:
        """写 routing 召回留痕（best-effort，观测失败绝不反噬选仓）。"""
        try:
            await arecord_retrieval_trace(
                kind="routing",
                payload={
                    "query": query,
                    "candidates": [c.to_dict() for c in result.candidates],
                    "router_version": result.router_version,
                },
                user_id=user_label,
                source=_COMPONENT,
            )
        except Exception as exc:  # noqa: BLE001 —— 观测 best-effort，吞掉一切
            logger.debug(
                "repo_association_route_observability_failed",
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="sampling",
            )

    # ------------------------------------------------------------------
    # 候选范围 / query / 候选映射
    # ------------------------------------------------------------------

    async def _resolve_repository_ids(
        self, space: Any, project: Any
    ) -> list[str] | None:
        """候选范围 = ``Space.repositories`` id 集（限定防全库噪声 Pitfall 6）。"""
        return await self._space_repository_ids(space)

    @sync_to_async
    def _space_repository_ids(self, space: Any) -> list[str] | None:
        """取 space 仓库 id 列表（同步 ORM 经 sync_to_async）。"""
        if space is None:
            return None
        try:
            repo_ids = [
                str(r) for r in space.repositories.values_list("id", flat=True)
            ]
        except Exception:  # noqa: BLE001 —— stub/未关联仓库时返回空，不抛
            return None
        return repo_ids or None

    @staticmethod
    def _normalize_features(
        feature_list: Any, features_flat: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        """归一 feature 语料来源：features_flat 优先，否则解析 feature_list。"""
        if features_flat:
            return list(features_flat)
        if isinstance(feature_list, dict):
            return list(feature_list.get("features_flat") or [])
        if isinstance(feature_list, list):
            return list(feature_list)
        return []

    @staticmethod
    def _build_query(
        features_flat: list[dict[str, Any]], *, extra_instruction: str | None = None
    ) -> str:
        """拼 name/description/module 为选仓 query（去重 + 截断 token 预算）。

        ``extra_instruction``（多轮澄清）作为附加约束并进 query 头部——仅作筛选要求，
        不构造执行指令（V5 输入校验）。正文不入日志（仅记长度）。
        """
        parts: list[str] = []
        seen: set[str] = set()
        instruction = (extra_instruction or "").strip()
        if instruction:
            parts.append(f"额外要求：{instruction}")
        for feature in features_flat:
            if not isinstance(feature, dict):
                continue
            name = str(feature.get("name") or "").strip()
            description = str(feature.get("description") or "").strip()
            module = str(feature.get("module") or "").strip()
            segment = " / ".join(p for p in (module, name, description) if p)
            if not segment or segment in seen:
                continue
            seen.add(segment)
            parts.append(segment)
        query = "\n".join(parts)
        if len(query) > _QUERY_CHAR_BUDGET:
            query = query[:_QUERY_CHAR_BUDGET]
        return query

    @staticmethod
    def _candidate_dict(candidate: Any) -> dict[str, Any]:
        """RepoRouteCandidateV2 → 对外候选 dict（reasoning → reason）。"""
        return {
            "repo_id": candidate.repo_id,
            "repo_name": candidate.repo_name,
            "score": round(float(candidate.score), 4),
            "confidence": candidate.confidence,
            "reason": candidate.reasoning,
            "matched_node_paths": list(candidate.matched_node_paths),
        }

    # ------------------------------------------------------------------
    # 落库（INV-6 唯一写入口）
    # ------------------------------------------------------------------

    async def _persist_candidates(
        self,
        *,
        space: Any,
        project: Any,
        candidates: list[dict[str, Any]],
        initiated_by_user_id: str,
    ) -> int:
        """逐候选落 RepoAssociation(proposed)（**唯一** 写入口，INV-6，幂等）。

        无 project（无法锚定业务）→ 仅 warning 跳过落库（候选仍返回，fail-soft）。
        """
        resolved_project = project if project is not None else await self._aresolve_project(space)
        if resolved_project is None:
            logger.warning(
                "repo_association_persist_skipped",
                reason="no_project_for_space",
                candidate_count=len(candidates),
                component=_COMPONENT,
                category="caller",
            )
            return 0
        if not candidates:
            return 0
        return await self._awrite_candidates(
            resolved_project, candidates, initiated_by_user_id
        )

    @sync_to_async
    def _awrite_candidates(
        self,
        project: Any,
        candidates: list[dict[str, Any]],
        initiated_by_user_id: str,
    ) -> int:
        """同步写 RepoAssociation（update_or_create on (project, repository)，INV-6）。"""
        from initiatives.models import RepoAssociation, RepoAssociationStatus

        written = 0
        for cand in candidates:
            repo_id = str(cand.get("repo_id") or "")
            if not repo_id:
                continue
            try:
                obj, _created = RepoAssociation.objects.update_or_create(
                    project=project,
                    repository_id=repo_id,
                    defaults={
                        "status": RepoAssociationStatus.PROPOSED,
                        "score": float(cand.get("score") or 0.0),
                        "confidence": str(cand.get("confidence") or ""),
                        "routed_reason": str(cand.get("reason") or ""),
                        "matched_node_paths": list(
                            cand.get("matched_node_paths") or []
                        ),
                        "source": "router_v2",
                        "initiated_by_user_id": initiated_by_user_id,
                    },
                )
                # 显式状态收口（守护 writer-actually-writes 正向断言 + 重置回 proposed）。
                obj.status = RepoAssociationStatus.PROPOSED
                written += 1
            except Exception as exc:  # noqa: BLE001 —— 单候选落库失败 fail-soft，不拖垮整体
                logger.warning(
                    "repo_association_candidate_persist_failed",
                    repo_id=repo_id,
                    reason=redact_secrets_in_text(str(exc)),
                    error_type=type(exc).__name__,
                    component=_COMPONENT,
                    category="caller",
                )
                continue
        return written

    @sync_to_async
    def _aresolve_project(self, space: Any) -> Any:
        """解析 space 对应的 Project（优先 feishu_project_key 命中，否则首个）。"""
        if space is None:
            return None
        from initiatives.models import Project

        qs = Project.objects.filter(space=space)
        project_key = getattr(space, "feishu_project_key", "") or ""
        if project_key:
            matched = qs.filter(feishu_project_key=project_key).first()
            if matched is not None:
                return matched
        return qs.first()
