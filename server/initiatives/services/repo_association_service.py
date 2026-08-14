"""RepoAssociationService —— 业务↔仓库关联选仓编排收口（REPO-01，88-02）。

把 Phase 87 拆分提案语料经 ``RepoRouterV2`` 做 COMBINED 选仓（语义 hybrid + 活跃度
facet 降权 + LLM 树推理 三合一，D-01/D-04，**绝不自写打分**），候选落
``RepoAssociation``(status=proposed)。是「项目↔仓库关联」的**单一写入收口**
（INV-6，由 ``test_repo_association_inv6_guard`` grep 守护）：工作流节点、AI 会话工具、
卡片回调三入口共用本服务，绝不旁路写 ``RepoAssociation`` / ``RepoVerifyTask``。

两段职责：

- :meth:`propose`：解析候选范围（``_resolve_repository_ids`` 限定 ``Space.repositories``，
  防跨项目噪声 Pitfall 6）→ 拼 query（``_build_query`` 消费 ``features_flat`` 的
  name/description/module，D-06）→ ``RepoRouterV2.route`` 选仓 → **章程 + 历史三分量
  融合**（对齐 ``BlueprintRouteAdapter`` brownfield 默认权重）→ 候选落 proposed。
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
from django.utils import timezone

from agents.call_source import CallSource, use_call_source
from common.logging import redact_secrets_in_text
from interactions.ledger import arecord_retrieval_trace

logger = structlog.get_logger(__name__)

__all__ = ["RepoAssociationService"]

_COMPONENT = "repo_association"
# 候选数上限（对齐 RepoRouterV2Adapter 默认；卡片展示 + 逐仓深验数量预算）。
_TOP_K = 5
# query 字符预算——**只剩 DoS 兜底职责**（T-88-02-DOS 的原始意图）。
#
# 历史缺陷（2026-08 实测）：本值原为 4000，本意是「防超大 feature list 塞爆 LLM
# 上下文」，但它被加在**送去检索的 query** 上，于是同时掐死了召回：「高三提分
# 专项」45 个功能点只有 7 个进了 query（9 个模块里的 2 个），测试用例语料
# 100% 未参与；目标仓 study-course 因此从未进入候选，5 次路由 0 次全中。
#
# 现在职责已拆开：
# - 检索侧：`RepoRouterV2` 经 `services.query_embedding.embed_query` 把长语料切块
#   多探针（Qdrant 服务端 RRF 融合，零额外往返），吃全量语料；实际参与召回的量
#   由探针预算 `MAX_PROBES × MAX_SEGMENT_CHARS` 决定，不再由本值决定。
# - prompt 侧：`repo_router_v2.STAGE1_PROMPT_QUERY_MAX_CHARS` 单独约束喂给 LLM
#   的正文长度（lost-in-the-middle，与上下文窗口容量无关）。
#
# 故本值只需挡住病态输入（几十万字的粘贴），取一个远高于真实 feature list 的值。
_QUERY_CHAR_BUDGET = 60000


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
        # Phase 128：画像语料构建检索 query（剔除 acceptance）；画像 degrade 仍可走门禁。
        query = await self._abuild_profile_query(flat, feature_list=feature_list)
        return await self._route_and_persist(
            space=space,
            project=project,
            query=query,
            initiated_by_user_id=initiated_by_user_id,
            event="repo_association_proposed",
            round_no=1,
            feature_list=feature_list,
            features_flat=flat,
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
        query = await self._abuild_profile_query(
            flat, feature_list=feature_list, extra_instruction=extra_instruction
        )
        return await self._route_and_persist(
            space=space,
            project=project,
            query=query,
            initiated_by_user_id=initiated_by_user_id,
            event="repo_association_refined",
            round_no=round_no,
            feature_list=feature_list,
            features_flat=flat,
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
        feature_list: Any = None,
        features_flat: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = perf_counter()
        user_label = (
            str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        )

        repo_ids = await self._resolve_repository_ids(space, project)
        # Phase 128：空/缺 team_core → clarify（D3），禁止静默成功空候选当「无事发生」。
        if not repo_ids:
            logger.info(
                event,
                candidate_count=0,
                router_version="clarify",
                round=round_no,
                query_len=len(query),
                scoped_repo_count=0,
                status="clarify",
                clarify_reason="empty_team_core",
                duration_ms=round((perf_counter() - started) * 1000, 2),
                initiated_by_user_id=user_label,
                component=_COMPONENT,
                category="caller",
            )
            return {
                "candidates": [],
                "router_version": "clarify",
                "auto_selected": False,
                "query_len": len(query),
                "status": "clarify",
                "clarify_reason": "empty_team_core",
                "team_core": [],
                "team_core_count": 0,
            }

        # 索引过滤：挂载仓全无索引 → clarify（TEAM-03）
        from services.process_runtime.team_gate import filter_indexed_repository_ids

        try:
            indexed_ids = await filter_indexed_repository_ids(repo_ids)
        except Exception:  # noqa: BLE001
            indexed_ids = []
        if not indexed_ids:
            logger.info(
                event,
                candidate_count=0,
                router_version="clarify",
                round=round_no,
                query_len=len(query),
                scoped_repo_count=len(repo_ids),
                status="clarify",
                clarify_reason="empty_team_core",
                duration_ms=round((perf_counter() - started) * 1000, 2),
                initiated_by_user_id=user_label,
                component=_COMPONENT,
                category="caller",
            )
            return {
                "candidates": [],
                "router_version": "clarify",
                "auto_selected": False,
                "query_len": len(query),
                "status": "clarify",
                "clarify_reason": "empty_team_core",
                "team_core": [],
                "team_core_count": 0,
            }
        repo_ids = indexed_ids
        team_core_ids = list(repo_ids)

        # Phase 129：在 team_core 范围内 shortlist 收窄（至少 primary/候选不超出 shortlist）
        shortlist_payload: list[dict[str, Any]] = []
        try:
            from services.process_runtime.history_prior import asplit_history_priors
            from services.process_runtime.shortlist import build_shortlist

            history_prior = await asplit_history_priors(
                query=query,
                team_core=repo_ids,
                candidate_repository_ids=repo_ids,
            )
            shortlist_result = await build_shortlist(
                team_core=repo_ids,
                force_include_ids=list(history_prior.force_include_ids or []),
                force_include_reasons_by_id=dict(history_prior.reasons_by_repo or {}),
                top_n=max(_TOP_K, 10),
            )
            narrowed = [
                r["repository_id"]
                for r in (shortlist_result.repositories or [])
                if r.get("repository_id")
            ]
            shortlist_payload = list(shortlist_result.repositories or [])
            if narrowed:
                repo_ids = narrowed
        except Exception:  # noqa: BLE001 — fail-soft：收窄失败仍用 team_core，不回退全库
            pass

        if not query:
            logger.info(
                event,
                candidate_count=0,
                router_version="skipped",
                round=round_no,
                query_len=0,
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
                "query_len": 0,
            }

        # Phase 130：shortlist 后放置单元细落点（三分量降为信号，非唯一决策）
        placements_payload: list[dict[str, Any]] = []
        hard_scope = list(repo_ids)
        placement_unit_count = 0
        try:
            from dataclasses import asdict

            from services.process_runtime.placement_units import build_placement_units
            from services.process_runtime.place_units import place_units

            fl = feature_list if isinstance(feature_list, dict) else {}
            units_result = build_placement_units(
                feature_list=fl or None,
                features_flat=features_flat,
                modules=list(fl.get("modules") or []) if fl else None,
            )
            placement_unit_count = int(getattr(units_result, "unit_count", 0) or 0)
            from codegraph.services.repo_router_v2 import RepoRouterV2

            place_result = await place_units(
                getattr(units_result, "units", None) or [],
                shortlist_ids=repo_ids,
                role_map=None,
                team_core=team_core_ids,
                router=RepoRouterV2,
                use_llm=False,
                top_k=_TOP_K,
            )
            hard_scope = list(getattr(place_result, "hard_scope", None) or repo_ids)
            if hard_scope:
                repo_ids = hard_scope
            for p in getattr(place_result, "placements", None) or []:
                try:
                    placements_payload.append(asdict(p))
                except Exception:  # noqa: BLE001
                    placements_payload.append(
                        {
                            "unit_id": getattr(p, "unit_id", ""),
                            "primary_repo": getattr(p, "primary_repo", None),
                            "supporting_repos": list(
                                getattr(p, "supporting_repos", []) or []
                            ),
                            "confidence": getattr(p, "confidence", ""),
                            "evidence": list(getattr(p, "evidence", []) or []),
                            "open_questions": list(
                                getattr(p, "open_questions", []) or []
                            ),
                        }
                    )
        except Exception as exc:  # noqa: BLE001 — fail-soft：保留 shortlist，不回退全库
            logger.warning(
                "repo_association_placement_failed",
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component=_COMPONENT,
            )

        # COMBINED 选仓：复用 RepoRouterV2；放置后仍在 hard_scope 内取分作信号。
        from codegraph.services.repo_router_v2 import RepoRouterV2

        with use_call_source(CallSource.AUX_REPO_ROUTER):
            result = await RepoRouterV2.route(
                query,
                top_k=_TOP_K,
                repository_ids=repo_ids,
                use_llm=True,
                corpus_kind="requirement",
            )

        candidates = await self._fuse_extended_signals(
            query=query,
            result=result,
            repo_ids=repo_ids,
            initiated_by_user_id=user_label,
        )

        # 以 placements 聚合约束候选：primary ∪ supporting ⊆ hard_scope
        scope_set = set(hard_scope or repo_ids)
        if placements_payload:
            placed_ids: list[str] = []
            seen_p: set[str] = set()
            for p in placements_payload:
                for rid in [p.get("primary_repo"), *(p.get("supporting_repos") or [])]:
                    sid = str(rid or "").strip()
                    if not sid or sid in seen_p:
                        continue
                    if scope_set and sid not in scope_set:
                        continue
                    seen_p.add(sid)
                    placed_ids.append(sid)
            if placed_ids:
                by_id = {
                    str(c.get("repo_id") or c.get("repository_id") or ""): c
                    for c in candidates
                }
                merged: list[dict[str, Any]] = []
                for rid in placed_ids:
                    if rid in by_id:
                        merged.append(by_id[rid])
                    else:
                        merged.append(
                            {
                                "repo_id": rid,
                                "repo_name": "",
                                "score": 0.5,
                                "confidence": "medium",
                                "reason": "placement",
                                "matched_node_paths": [],
                            }
                        )
                # 入围由 placements 决定；三分量 score 仅作排序信号（非唯一决策）
                merged.sort(
                    key=lambda c: (
                        -float(c.get("score") or 0.0),
                        str(c.get("repo_id") or ""),
                    )
                )
                candidates = merged
        else:
            candidates = [
                c
                for c in candidates
                if str(c.get("repo_id") or c.get("repository_id") or "") in scope_set
                or not scope_set
            ]

        await self._record_routing_trace(
            query=query,
            result=result,
            candidates=candidates,
            user_label=user_label,
        )

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
            placement_unit_count=placement_unit_count,
            placement_count=len(placements_payload),
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
            "shortlist": shortlist_payload,
            "shortlist_count": len(shortlist_payload),
            "placements": placements_payload,
            "placement_unit_count": placement_unit_count,
            "hard_scope": list(hard_scope),
        }

    async def _record_routing_trace(
        self,
        *,
        query: str,
        result: Any,
        candidates: list[dict[str, Any]],
        user_label: str,
    ) -> None:
        """写 routing 召回留痕（best-effort，观测失败绝不反噬选仓）。"""
        try:
            await arecord_retrieval_trace(
                kind="routing",
                payload={
                    "query": query,
                    "candidates": candidates,
                    "router_version": result.router_version,
                    "signal_fusion": "charter+history",
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
    # 章程 + 历史三分量融合（CHARTER-02，对齐 BlueprintRouteAdapter）
    # ------------------------------------------------------------------

    async def _fuse_extended_signals(
        self,
        *,
        query: str,
        result: Any,
        repo_ids: list[str],
        initiated_by_user_id: str,
    ) -> list[dict[str, Any]]:
        """能力树 router_base + 章程 + 历史加权融合；best-effort 失败回退纯 router 候选。"""
        started = perf_counter()
        router_candidates = list(getattr(result, "candidates", []) or [])
        fallback = [self._candidate_dict(c) for c in router_candidates]
        if not fallback:
            return []

        try:
            from services.process_runtime.blueprint_charter_match import (
                acollect_charter_candidates,
                aload_charters,
                score_charter_match,
            )
            from services.process_runtime.blueprint_route import (
                DEFAULT_ROUTE_WEIGHTS,
                aload_route_weights,
                build_score_breakdown,
            )
            from services.process_runtime.blueprint_route_history import ascore_history_match

            weights = await aload_route_weights()
            vector = dict(
                (weights or {}).get("brownfield") or DEFAULT_ROUTE_WEIGHTS["brownfield"]
            )
            query_terms = [query]

            raw: list[dict[str, Any]] = []
            for c in router_candidates:
                rid = str(getattr(c, "repo_id", "") or "")
                if not rid:
                    continue
                raw.append(
                    {
                        "repository_id": rid,
                        "repository_name": str(getattr(c, "repo_name", "") or ""),
                        "router_base": float(getattr(c, "score", 0.0) or 0.0),
                        "confidence": str(getattr(c, "confidence", "") or ""),
                        "reasoning": str(getattr(c, "reasoning", "") or ""),
                        "matched_node_paths": list(getattr(c, "matched_node_paths", []) or []),
                        "charter_supplement": False,
                    }
                )

            exclude_ids = {item["repository_id"] for item in raw}
            try:
                supplements = await acollect_charter_candidates(
                    query_terms=query_terms,
                    exclude_repository_ids=exclude_ids,
                    repository_ids=repo_ids,
                    limit=3,
                )
            except Exception:  # noqa: BLE001 — 补入失败退化为无补入
                supplements = []
            for row in supplements or []:
                rid = str(row.get("repository_id") or "")
                if not rid or rid in exclude_ids:
                    continue
                exclude_ids.add(rid)
                raw.append(
                    {
                        "repository_id": rid,
                        "repository_name": str(row.get("repository_name") or ""),
                        "router_base": 0.0,
                        "confidence": "low",
                        "reasoning": "",
                        "matched_node_paths": [],
                        "charter_supplement": True,
                        "_charter_match_raw": float(row.get("charter_match_raw") or 0.0),
                        "_matched_domains": list(row.get("matched_domains") or []),
                    }
                )

            if not raw:
                return fallback

            candidate_ids = [item["repository_id"] for item in raw]
            charters = await aload_charters(candidate_ids)
            acting_user = await self._resolve_acting_user(initiated_by_user_id)
            history = await ascore_history_match(
                query=query,
                candidate_repository_ids=candidate_ids,
                acting_user=acting_user,
            )

            fused: list[dict[str, Any]] = []
            for item in raw:
                rid = item["repository_id"]
                if item.get("charter_supplement"):
                    charter_score = float(item.get("_charter_match_raw") or 0.0)
                    charter_source = "ai_draft"
                    charter_version = 0
                    matched_domains = list(item.get("_matched_domains") or [])
                    violated_boundaries: list[str] = []
                    penalty_reasons: list[str] = []
                else:
                    charter_result = score_charter_match(
                        charters.get(rid), query_terms=query_terms
                    )
                    charter_score = float(charter_result.score or 0.0)
                    charter_source = str(charter_result.charter_source or "")
                    charter_version = int(charter_result.charter_version or 0)
                    matched_domains = list(charter_result.matched_domains or [])
                    violated_boundaries = list(charter_result.violated_boundaries or [])
                    penalty_reasons = list(charter_result.penalty_reasons or [])

                history_score = float(history.scores.get(rid, 0.0))
                breakdown = build_score_breakdown(
                    router_base=item["router_base"],
                    charter_match=charter_score,
                    history_match=history_score,
                    weights=vector,
                    evidence={
                        "router_version": str(getattr(result, "router_version", "") or ""),
                        "auto_selected": bool(getattr(result, "auto_selected", False)),
                        "confidence": item["confidence"],
                        "reasoning": item["reasoning"],
                        "matched_node_paths": item["matched_node_paths"],
                        "charter_source": charter_source,
                        "charter_version": charter_version,
                        "matched_domains": matched_domains,
                        "violated_boundaries": violated_boundaries,
                        "penalty_reasons": penalty_reasons,
                        "history_match_unavailable": history.unavailable_reason,
                        "boundary_override_reason": "",
                        "unjustified_boundary_hit": False,
                        "module_summaries": [],
                    },
                )
                confidence = item["confidence"]
                if violated_boundaries:
                    confidence = "low"
                fused.append(
                    {
                        "repo_id": rid,
                        "repo_name": item["repository_name"],
                        "score": round(float(breakdown["total"]), 4),
                        "confidence": confidence,
                        "reason": item["reasoning"],
                        "matched_node_paths": list(item["matched_node_paths"]),
                        "breakdown": {
                            "router_base": breakdown["router_base"],
                            "charter_match": breakdown["charter_match"],
                            "history_match": breakdown["history_match"],
                            "total": breakdown["total"],
                        },
                        "charter_supplement": bool(item.get("charter_supplement")),
                    }
                )

            fused.sort(key=lambda c: (-float(c["score"]), str(c["repo_id"])))
            top = fused[:_TOP_K]
            logger.info(
                "repo_association_signals_fused",
                candidate_count=len(top),
                supplement_count=sum(1 for c in top if c.get("charter_supplement")),
                history_unavailable=history.unavailable_reason,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                initiated_by_user_id=initiated_by_user_id,
                component=_COMPONENT,
                category="sampling",
            )
            return top
        except Exception as exc:  # noqa: BLE001 — 融合失败回退纯 router，不反噬选仓
            logger.warning(
                "repo_association_signals_fusion_failed",
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                duration_ms=round((perf_counter() - started) * 1000, 2),
                initiated_by_user_id=initiated_by_user_id,
                component=_COMPONENT,
                category="sampling",
            )
            return fallback

    @sync_to_async
    def _resolve_acting_user(self, user_label: str) -> Any:
        """解析历史分量所需 acting user（system/无效 id → None，fail-closed）。"""
        if not user_label or user_label == "system":
            return None
        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            return User.objects.get(pk=user_label)
        except (User.DoesNotExist, ValueError, TypeError):
            return None

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

    async def _abuild_profile_query(
        self,
        features_flat: list[dict[str, Any]],
        *,
        feature_list: Any = None,
        extra_instruction: str | None = None,
    ) -> str:
        """经画像 corpus 构建检索 query（PROF-02：不把 acceptance 当主语料）。"""
        try:
            from services.process_runtime.initiative_profile import select_profile_corpus

            corpus = select_profile_corpus(feature_list, features_flat=features_flat)
            if corpus.sufficient and corpus.texts:
                body = "\n".join(corpus.texts)
                instruction = (extra_instruction or "").strip()
                if instruction:
                    body = f"额外要求：{instruction}\n{body}"
                if len(body) > _QUERY_CHAR_BUDGET:
                    body = body[:_QUERY_CHAR_BUDGET]
                return body
        except Exception:  # noqa: BLE001 — fail-soft 回落旧拼法
            pass
        return self._build_query(features_flat, extra_instruction=extra_instruction)

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

    # ------------------------------------------------------------------
    # 确认 / 逐仓深验编排（REPO-02，88-03）
    # ------------------------------------------------------------------

    async def confirm_repos(
        self,
        *,
        project: Any,
        repo_ids: list[Any],
        initiated_by_user_id: Any = None,
    ) -> list[Any]:
        """用户确认：命中 proposed 候选置 ``status=confirmed``，返回 confirmed 关联列表。

        仅确认 ``repo_ids`` 命中的 proposed 候选（其余 proposed 保留不动，便于后续重确认）；
        条件更新幂等（已 confirmed 重复确认 no-op）。
        """
        user_label = (
            str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        )
        confirmed = await self._confirm_repos_sync(project, repo_ids, user_label)
        # 人工确认 = 该仓的正样本：best-effort 触发 charter 重新起草回灌（confirmed →
        # owned_domains 证据）。durable 幂等键 charter:{repo_id}，重复确认只入队一次。
        await self._reinforce_charters([a.repository_id for a in confirmed], user_label, "confirm")
        return confirmed

    async def _reinforce_charters(
        self, repository_ids: list[Any], user_label: str, action: str
    ) -> None:
        """人工裁决后 best-effort 回灌 charter（正/负样本），绝不反噬选仓主流程。"""
        try:
            from repositories.charter_enqueue import enqueue_charter_draft
        except Exception:  # noqa: BLE001 — 无 charter 管线时静默跳过
            return
        for rid in {str(r) for r in (repository_ids or []) if r}:
            try:
                await enqueue_charter_draft(rid, initiated_by_user_id=user_label)
            except Exception as exc:  # noqa: BLE001 — 单仓失败不阻断其余
                logger.warning(
                    "repo_association_charter_reinforce_failed",
                    repository_id=rid,
                    action=action,
                    reason=redact_secrets_in_text(str(exc))[:200],
                    initiated_by_user_id=user_label,
                    component=_COMPONENT,
                    category="sampling",
                )

    @sync_to_async
    def _confirm_repos_sync(
        self, project: Any, repo_ids: list[Any], initiated_by_user_id: str
    ) -> list[Any]:
        from initiatives.models import RepoAssociation, RepoAssociationStatus

        ids = [str(r) for r in (repo_ids or []) if r]
        if not ids:
            return []
        confirmed: list[Any] = []
        for assoc in RepoAssociation.objects.filter(
            project=project, repository_id__in=ids
        ):
            # 条件更新幂等：仅 proposed → confirmed（已 confirmed/verifying 不回退）
            RepoAssociation.objects.filter(
                id=assoc.id, status=RepoAssociationStatus.PROPOSED
            ).update(status=RepoAssociationStatus.CONFIRMED, updated_at=timezone.now())
            assoc.refresh_from_db()
            confirmed.append(assoc)
        logger.info(
            "repo_association_confirmed",
            confirmed_count=len(confirmed),
            requested_count=len(ids),
            initiated_by_user_id=initiated_by_user_id,
            component=_COMPONENT,
            category="caller",
        )
        return confirmed

    async def reject_candidates(
        self,
        *,
        project: Any,
        repo_ids: list[Any],
        initiated_by_user_id: Any = None,
    ) -> int:
        """用户拒绝候选：命中 proposed 候选置 ``status=rejected``（条件更新幂等）。

        仅作用于 proposed（已 confirmed/verifying/verified 不受影响，回退用
        :meth:`reopen_candidates`）；被拒候选后续 propose/refine 命中时会被更新回
        proposed（既有 upsert 语义），供「知识关联」面板的拒绝分支收口。
        """
        user_label = (
            str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        )
        rejected_count = await self._reject_candidates_sync(project, repo_ids, user_label)
        # 人工拒绝 = 该仓的负样本：best-effort 触发 charter 重新起草回灌（rejected →
        # boundaries 边界候选），让误路由的仓下次被边界排除。
        if rejected_count:
            await self._reinforce_charters(list(repo_ids or []), user_label, "reject")
        return rejected_count

    @sync_to_async
    def _reject_candidates_sync(
        self, project: Any, repo_ids: list[Any], initiated_by_user_id: str
    ) -> int:
        from initiatives.models import RepoAssociation, RepoAssociationStatus

        ids = [str(r) for r in (repo_ids or []) if r]
        if not ids:
            return 0
        rejected = RepoAssociation.objects.filter(
            project=project,
            repository_id__in=ids,
            status=RepoAssociationStatus.PROPOSED,
        ).update(status=RepoAssociationStatus.REJECTED, updated_at=timezone.now())
        logger.info(
            "repo_association_candidates_rejected",
            rejected_count=rejected,
            requested_count=len(ids),
            initiated_by_user_id=initiated_by_user_id,
            component=_COMPONENT,
            category="caller",
        )
        return rejected

    async def dispatch_verify(
        self,
        *,
        project: Any = None,
        confirmed: list[Any],
        node_execution_id: str = "",
        initiated_by_user_id: Any = None,
    ) -> dict[str, Any]:
        """逐仓深验编排：置 ``status=verifying`` → 薄委托 ``RepoVerifyDispatchService.dispatch``。

        ``confirmed`` 为 :meth:`confirm_repos` 返回的 confirmed ``RepoAssociation`` 列表。
        全程 fail-soft（dispatch 内单仓隔离 + runner 离线降级）。
        """
        user_label = (
            str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        )
        items = list(confirmed or [])
        if not items:
            return {"dispatched": [], "failed": [], "runner_offline": False}

        await self._mark_verifying_sync([a.id for a in items])

        from initiatives.services.repo_verify_dispatch import RepoVerifyDispatchService

        dispatcher = RepoVerifyDispatchService(
            association_service=self, node_execution_id=node_execution_id
        )
        return await dispatcher.dispatch(items, initiated_by_user_id=user_label)

    @sync_to_async
    def _mark_verifying_sync(self, association_ids: list[Any]) -> int:
        from initiatives.models import RepoAssociation, RepoAssociationStatus

        return RepoAssociation.objects.filter(
            id__in=association_ids, status=RepoAssociationStatus.CONFIRMED
        ).update(status=RepoAssociationStatus.VERIFYING, updated_at=timezone.now())

    # ------------------------------------------------------------------
    # RepoVerifyTask 状态机 + verdict 落库（INV-6 唯一写入口，88-03）
    # ------------------------------------------------------------------

    async def create_verify_task(
        self,
        association: Any,
        repository: Any,
        *,
        initiated_by_user_id: Any = None,
    ) -> Any:
        """为确认仓建 ``RepoVerifyTask(status=pending)``（get_or_create 幂等，resume 安全）。"""
        user_label = (
            str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        )
        return await self._create_verify_task_sync(association, repository, user_label)

    @sync_to_async
    def _create_verify_task_sync(
        self, association: Any, repository: Any, initiated_by_user_id: str
    ) -> Any:
        from initiatives.models import RepoVerifyTask, RepoVerifyTaskStatus

        task, _created = RepoVerifyTask.objects.get_or_create(
            association=association,
            repository=repository,
            defaults={
                "status": RepoVerifyTaskStatus.PENDING,
                "attempt": 0,
                "initiated_by_user_id": initiated_by_user_id,
            },
        )
        return task

    async def mark_verify_running(self, task: Any, subagent_session: Any) -> None:
        """task.status→running，回填 subagent_session 外键。"""
        await self._mark_verify_running_sync(task, subagent_session)

    @sync_to_async
    def _mark_verify_running_sync(self, task: Any, subagent_session: Any) -> None:
        from initiatives.models import RepoVerifyTaskStatus

        task.status = RepoVerifyTaskStatus.RUNNING
        task.subagent_session = subagent_session
        task.save(update_fields=["status", "subagent_session", "updated_at"])

    async def mark_verify_failed(self, task: Any, error: Any) -> None:
        """task.status→failed，error JSON 落库（正文脱敏；非 dict 包成 {message}）。"""
        await self._mark_verify_failed_sync(task, error)

    @sync_to_async
    def _mark_verify_failed_sync(self, task: Any, error: Any) -> None:
        from initiatives.models import RepoVerifyTaskStatus

        if isinstance(error, dict):
            safe_error = {
                k: redact_secrets_in_text(v) if isinstance(v, str) else v
                for k, v in error.items()
            }
        else:
            safe_error = {"message": redact_secrets_in_text(str(error))}
        task.status = RepoVerifyTaskStatus.FAILED
        task.error = safe_error
        task.save(update_fields=["status", "error", "updated_at"])

    async def _sync_association_graph(
        self, *, association_id: Any, verified: bool, initiated_by_user_id: Any = None
    ) -> None:
        """KDEP-08：verified/unverified 状态流转的单一图谱同步 hook（best-effort）。

        ``verified=True`` → 派生 project→repo ``RELATES_TO`` 边（metadata 携
        source=repo_association 等）；``verified=False`` → 失效对应派生边。整个 hook 吞掉
        一切异常 + 记 ``repo_association_graph_sync_failed``——同步 best-effort，**绝不反噬**
        verdict 落库 / 状态流转主流程（对齐模块 fail-soft 纪律）。
        """
        try:
            from initiatives.models import RepoAssociation
            from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService

            assoc = await sync_to_async(
                lambda: RepoAssociation.objects.select_related("project", "repository")
                .filter(id=association_id)
                .first()
            )()
            if assoc is None:
                return
            project = await sync_to_async(lambda: assoc.project)()
            repository = await sync_to_async(lambda: assoc.repository)()
            if project is None or repository is None:
                return

            svc = ProjectKnowledgeGraphService()
            if verified:
                await svc.link_repository(
                    project=project,
                    repository=repository,
                    metadata={
                        "source": "repo_association",
                        "association_id": str(assoc.id),
                        "score": float(assoc.score or 0.0),
                        "confidence": assoc.confidence or "",
                        "matched_node_paths": list(assoc.matched_node_paths or []),
                    },
                    initiated_by_user_id=initiated_by_user_id,
                )
            else:
                await svc.unlink_repository(
                    project=project,
                    repository=repository,
                    initiated_by_user_id=initiated_by_user_id,
                )
            logger.info(
                "repo_association_graph_synced",
                repo_id=str(getattr(repository, "id", "")),
                verified=verified,
                initiated_by_user_id=str(initiated_by_user_id)
                if initiated_by_user_id
                else "system",
                component=_COMPONENT,
                category="caller",
            )
        except Exception as exc:  # noqa: BLE001 — best-effort，绝不反噬状态流转
            logger.warning(
                "repo_association_graph_sync_failed",
                association_id=str(association_id),
                verified=verified,
                reason=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                component=_COMPONENT,
                category="sampling",
            )

    async def record_verdict(self, task: Any, verdict: dict[str, Any]) -> bool:
        """写 verdict JSON + task.status→done + 同步 per-repo association 状态（幂等）。

        条件更新（排除已 done）保证幂等：重复 ``record_verdict`` 不翻已终态（no-op）。
        verdict ``fit`` → 关联状态：fit→verified / mismatch→rejected / unknown→保持 verifying
        （最终批量确认/回退由 88-05 处理；此处仅 per-repo 落地）。

        落地成功后挂单一图谱同步 hook（KDEP-08）：fit→verified 派生边 / mismatch→失效派生边。
        """
        applied = await self._record_verdict_sync(task, verdict)
        if applied:
            fit = str(self._sanitize_verdict(verdict).get("fit") or "unknown").lower()
            if fit == "fit":
                await self._sync_association_graph(
                    association_id=task.association_id, verified=True
                )
            elif fit == "mismatch":
                await self._sync_association_graph(
                    association_id=task.association_id, verified=False
                )
        return applied

    @sync_to_async
    def _record_verdict_sync(self, task: Any, verdict: dict[str, Any]) -> bool:
        from initiatives.models import (
            RepoAssociation,
            RepoAssociationStatus,
            RepoVerifyTask,
            RepoVerifyTaskStatus,
        )

        safe_verdict = self._sanitize_verdict(verdict)
        updated = (
            RepoVerifyTask.objects.filter(id=task.id)
            .exclude(status=RepoVerifyTaskStatus.DONE)
            .update(
                status=RepoVerifyTaskStatus.DONE,
                verdict=safe_verdict,
                updated_at=timezone.now(),
            )
        )
        if updated != 1:
            return False
        fit = str(safe_verdict.get("fit") or "unknown").lower()
        target = None
        if fit == "fit":
            target = RepoAssociationStatus.VERIFIED
        elif fit == "mismatch":
            target = RepoAssociationStatus.REJECTED
        if target is not None:
            RepoAssociation.objects.filter(
                id=task.association_id, status=RepoAssociationStatus.VERIFYING
            ).update(status=target, updated_at=timezone.now())
        logger.info(
            "repo_verify_verdict_recorded",
            repo_id=str(task.repository_id),
            fit=fit,
            component=_COMPONENT,
            category="caller",
        )
        return True

    @staticmethod
    def _sanitize_verdict(verdict: dict[str, Any]) -> dict[str, Any]:
        """归一 + 脱敏 verdict（fit 受控；summary/mismatch_reasons 正文脱敏 + 截断）。"""
        raw = verdict if isinstance(verdict, dict) else {}
        fit = str(raw.get("fit") or "unknown").lower()
        if fit not in ("fit", "mismatch", "unknown"):
            fit = "unknown"
        reasons = raw.get("mismatch_reasons") or []
        if not isinstance(reasons, list):
            reasons = [reasons]
        return {
            "fit": fit,
            "confidence": str(raw.get("confidence") or ""),
            "summary": redact_secrets_in_text(str(raw.get("summary") or ""))[:4000],
            "evidence_files": [str(f) for f in (raw.get("evidence_files") or [])][:50],
            "mismatch_reasons": [
                redact_secrets_in_text(str(r))[:1000] for r in reasons
            ][:20],
        }

    async def collect_verdicts(self, associations: list[Any]) -> dict[str, Any]:
        """聚合确认批次各仓 verdict → ``{fit, mismatch, unknown, all_terminal}``。

        缺 verdict / 未建 task / 失败仓记 ``unknown``（不阻断终态，D-03 fail-soft）；
        ``all_terminal`` 为各仓 verify task 是否全部终态（done/failed/stale）。
        """
        return await self._collect_verdicts_sync(list(associations or []))

    @sync_to_async
    def _collect_verdicts_sync(self, associations: list[Any]) -> dict[str, Any]:
        from initiatives.models import RepoVerifyTask, RepoVerifyTaskStatus

        terminal = {
            RepoVerifyTaskStatus.DONE,
            RepoVerifyTaskStatus.FAILED,
            RepoVerifyTaskStatus.STALE,
        }
        fit: list[str] = []
        mismatch: list[str] = []
        unknown: list[str] = []
        all_terminal = True
        for assoc in associations:
            repo_id = str(assoc.repository_id)
            task = (
                RepoVerifyTask.objects.filter(association=assoc)
                .order_by("-created_at")
                .first()
            )
            if task is None:
                # 未建 task 的确认仓记 unknown，不阻断
                unknown.append(repo_id)
                continue
            if task.status not in terminal:
                all_terminal = False
            verdict = task.verdict if isinstance(task.verdict, dict) else {}
            fit_val = str(verdict.get("fit") or "").lower()
            if task.status == RepoVerifyTaskStatus.FAILED:
                unknown.append(repo_id)
            elif fit_val == "fit":
                fit.append(repo_id)
            elif fit_val == "mismatch":
                mismatch.append(repo_id)
            else:
                unknown.append(repo_id)
        return {
            "fit": fit,
            "mismatch": mismatch,
            "unknown": unknown,
            "all_terminal": all_terminal,
        }

    # ------------------------------------------------------------------
    # 回退 / 接受 mismatch 状态迁移（INV-6 唯一写入口，88-05）
    # ------------------------------------------------------------------

    async def accept_mismatch(
        self, association: Any, *, initiated_by_user_id: Any = None
    ) -> bool:
        """用户接受 mismatch：把 rejected/verifying 关联置 ``status=verified``（幂等）。

        条件更新（仅 rejected/verifying → verified）保证幂等：已 verified 重复接受 no-op
        返回 ``False``。承载 D-03「发现不符仍接受并继续」的回退分支收口。
        """
        user_label = (
            str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        )
        applied = await self._accept_mismatch_sync(association, user_label)
        if applied:
            await self._sync_association_graph(
                association_id=association.id,
                verified=True,
                initiated_by_user_id=user_label,
            )
        return applied

    @sync_to_async
    def _accept_mismatch_sync(self, association: Any, initiated_by_user_id: str) -> bool:
        from initiatives.models import RepoAssociation, RepoAssociationStatus

        updated = (
            RepoAssociation.objects.filter(id=association.id)
            .filter(
                status__in=[
                    RepoAssociationStatus.REJECTED,
                    RepoAssociationStatus.VERIFYING,
                ]
            )
            .update(status=RepoAssociationStatus.VERIFIED, updated_at=timezone.now())
        )
        if updated == 1:
            logger.info(
                "repo_association_mismatch_accepted",
                repo_id=str(association.repository_id),
                initiated_by_user_id=initiated_by_user_id,
                component=_COMPONENT,
                category="caller",
            )
        return updated == 1

    async def reopen_candidates(
        self, association: Any, *, initiated_by_user_id: Any = None
    ) -> bool:
        """回退重确认：把已流转关联回置 ``status=proposed``（重开候选选择，幂等）。

        条件更新（排除已 proposed）保证幂等：把 confirmed/verifying/verified/rejected 回
        proposed，使用户可重新确认仓库（D-03 发现不符可回退）。
        """
        user_label = (
            str(initiated_by_user_id) if initiated_by_user_id is not None else "system"
        )
        applied = await self._reopen_candidates_sync(association, user_label)
        if applied:
            # 离开任意态→proposed：若之前是 verified 则失效派生边；非 verified 时 unlink 幂等 no-op。
            await self._sync_association_graph(
                association_id=association.id,
                verified=False,
                initiated_by_user_id=user_label,
            )
        return applied

    @sync_to_async
    def _reopen_candidates_sync(
        self, association: Any, initiated_by_user_id: str
    ) -> bool:
        from initiatives.models import RepoAssociation, RepoAssociationStatus

        updated = (
            RepoAssociation.objects.filter(id=association.id)
            .exclude(status=RepoAssociationStatus.PROPOSED)
            .update(status=RepoAssociationStatus.PROPOSED, updated_at=timezone.now())
        )
        if updated == 1:
            logger.info(
                "repo_association_reopened",
                repo_id=str(association.repository_id),
                initiated_by_user_id=initiated_by_user_id,
                component=_COMPONENT,
                category="caller",
            )
        return updated == 1

    # ------------------------------------------------------------------
    # Phase 89 输出契约（D-06，只读查询，不旁路写）
    # ------------------------------------------------------------------

    async def get_verified_associations(
        self, *, project: Any, work_item: Any = None
    ) -> list[dict[str, Any]]:
        """Phase 89 输出契约：返回已确认（verified）仓库关联 + 各仓最新 verdict。

        供 Phase 89 技术方案深化 ``PlanSession.decomposition.include_repos`` 直接消费
        （``repository_id`` 对齐 ``RepoRouterV2Adapter`` include 优先级），verdict 携粗
        「该仓是否适配 + 摘要 + 证据」（精确 feature→repo 分配留 Phase 89，RESEARCH Q1/Q2）。

        Returns:
            ``[{repository_id, repo_name, verdict, matched_node_paths, routed_reason,
            score}]``；仅 ``status=verified`` 关联计入（proposed/confirmed/verifying/
            rejected 不计入），无 verified → 返回 ``[]``。只读不写（INV-6 不涉及）。
        """
        return await self._get_verified_associations_sync(project, work_item)

    @sync_to_async
    def _get_verified_associations_sync(
        self, project: Any, work_item: Any
    ) -> list[dict[str, Any]]:
        from initiatives.models import (
            RepoAssociation,
            RepoAssociationStatus,
            RepoVerifyTask,
        )

        qs = RepoAssociation.objects.filter(
            project=project, status=RepoAssociationStatus.VERIFIED
        ).select_related("repository")
        if work_item is not None:
            qs = qs.filter(work_item=work_item)

        out: list[dict[str, Any]] = []
        for assoc in qs.order_by("-score", "repository_id"):
            task = (
                RepoVerifyTask.objects.filter(association=assoc)
                .order_by("-created_at")
                .first()
            )
            raw = task.verdict if (task and isinstance(task.verdict, dict)) else {}
            repo = getattr(assoc, "repository", None)
            out.append(
                {
                    "repository_id": str(assoc.repository_id),
                    "repo_name": getattr(repo, "name", "") or str(assoc.repository_id),
                    "verdict": {
                        "fit": str(raw.get("fit") or "unknown"),
                        "confidence": str(
                            raw.get("confidence") or assoc.confidence or ""
                        ),
                        "summary": str(raw.get("summary") or ""),
                        "evidence_files": list(raw.get("evidence_files") or []),
                        "mismatch_reasons": list(raw.get("mismatch_reasons") or []),
                    },
                    "matched_node_paths": list(assoc.matched_node_paths or []),
                    "routed_reason": assoc.routed_reason or "",
                    "score": float(assoc.score or 0.0),
                }
            )
        logger.info(
            "repo_association_output_collected",
            verified_count=len(out),
            component=_COMPONENT,
            category="caller",
        )
        return out
