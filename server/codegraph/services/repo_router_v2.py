"""推理式仓库路由 v2（PageIndex 化）。

Stage 0 — 节点级 hybrid 粗筛：query 对 `repo_index_nodes`（能力树节点）做
dense+sparse RRF 检索，按 repository_id 聚合打分（纯函数打分核心
``repo_router_scoring.aggregate_and_score``：query-local 归一 + 三信号加性合成，
每候选携带 breakdown 且 Σ贡献 == score）取 Top-N 候选仓库。节点粒度远细于
v1 的"一仓一向量点"，模块/能力命中即召回。

Stage 1 — LLM 树推理：query + 各候选仓库的树骨架（overview + 命中节点及其
祖先路径）喂给快速模型，输出结构化选择：repo + sub_project + confidence +
reasoning + matched_node_paths。

置信度分级（RELY-04）：由分数 margin 确定性推导（``derive_confidence``），
LLM 的 confidence 输出只能把确定性分级降级（``apply_llm_adjustment`` 只降
不升）；``auto_selected`` 由确定性 confidence 驱动（首位最终 high → True），
Stage 1 可用与不可用两条路径语义一致——Stage 1 失联不再导致编排停摆。

降级链（结果带 ``degraded`` 标志，Stage 1 未参与时为 True）：
- LLM 失败/超时 → Stage 0 聚合分数直接出结果（仍优于 v1：节点级检索）
- repo_index_nodes 无命中 → 回落 v1 RepoRouter（repo_summaries 单点检索）

分面信号：节点 payload 的 facets 参与排序——活跃度经枚举映射进加性活跃度项，
疑似废弃仓库的惩罚为活跃度项封顶（非乘性惩罚，贡献仍可单独拆解展示）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from asgiref.sync import sync_to_async

from codegraph.services.repo_index_tree import COLLECTION_NAME
from codegraph.services.repo_router_scoring import (
    WEIGHT_SET_VERSION,
    aggregate_and_score,
    apply_llm_adjustment,
    derive_confidence,
)
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from services.sparse_encoder import SparseEncoderService

logger = structlog.get_logger(__name__)

Confidence = Literal["high", "medium", "low"]

STAGE0_NODE_K = 50
STAGE0_REPO_K = 12

# Stage 1 调参从 settings 读（支持环境变量覆盖），取值时机为调用时而非导入时，
# 便于按供应商速度调整而不必改代码发版。默认见 friday/settings.py。
_STAGE1_DEFAULTS = {
    "REPO_ROUTER_STAGE1_TIMEOUT_SECONDS": 90.0,
    "REPO_ROUTER_STAGE1_MAX_CANDIDATES": 8,
    "REPO_ROUTER_STAGE1_HITS_PER_REPO": 4,
}


def _stage1_conf(key: str):
    from django.conf import settings

    return getattr(settings, key, _STAGE1_DEFAULTS[key])


# confidence θ 阈值默认值（与 friday/settings.py 一致；ROUTING-RANKING §1.3a 初值）。
_CONF_THETA_DEFAULTS = {
    "REPO_ROUTER_CONF_THETA_ABS": 0.55,
    "REPO_ROUTER_CONF_THETA_MARGIN": 0.08,
    "REPO_ROUTER_CONF_THETA_MED": 0.35,
}


def _conf_thresholds() -> tuple[float, float, float]:
    """读取确定性 confidence 的 θ 阈值（照 ``_stage1_conf`` 模式，调用时读取）。

    Returns:
        ``(theta_abs, theta_margin, theta_med)``——golden set 校准后可经环境
        变量调整，不必改代码发版。
    """
    from django.conf import settings

    return tuple(  # type: ignore[return-value]
        float(getattr(settings, key, default))
        for key, default in _CONF_THETA_DEFAULTS.items()
    )


@dataclass
class RepoRouteCandidateV2:
    """v2 路由候选结果。"""

    repo_id: str
    repo_name: str
    score: float
    confidence: Confidence
    reasoning: str
    sub_project: str = ""
    sub_project_paths: list[str] = field(default_factory=list)
    matched_node_paths: list[str] = field(default_factory=list)
    # 分数可拆解（ROUTE-07）：信号名 → 贡献值，Σ贡献 == score（打分核心保证）。
    breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "repo_name": self.repo_name,
            "score": round(self.score, 4),
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "sub_project": self.sub_project,
            "sub_project_paths": self.sub_project_paths,
            "matched_node_paths": self.matched_node_paths,
            "breakdown": {k: round(v, 6) for k, v in self.breakdown.items()},
        }


@dataclass
class RepoRouteResultV2:
    """v2 路由整体结果。"""

    candidates: list[RepoRouteCandidateV2]
    router_version: str  # "v2" | "v2_stage0_only" | "v1_fallback"
    auto_selected: bool  # 首位确定性最终 confidence == high 时自动选定
    # Stage 1 未参与（use_llm=False / LLM 失败 / v1 回落）时为 True（RELY-04 数据底座）。
    degraded: bool = False
    # Stage 0 快照材料 + versions（ROUTE-09 数据底座；stage1 材料由 105-05 补充，
    # 落 ConvergenceSessionEvent 由 105-07 处理——本结构只保证材料随结果携带）。
    snapshot: dict[str, Any] = field(default_factory=dict)


class RepoRouterV2:
    """两阶段推理式仓库路由器。"""

    @classmethod
    async def route(
        cls,
        query: str,
        *,
        top_k: int = 3,
        repository_ids: list[str] | None = None,
        use_llm: bool = True,
    ) -> RepoRouteResultV2:
        """执行推理式路由。

        Args:
            query: 用户提问 / 需求文本。
            top_k: 返回候选数上限。
            repository_ids: 限定候选仓库范围（如空间内仓库）；None 为全库。
            use_llm: False 时仅跑 Stage 0（纯检索 API 用）。
        """
        # ---- Stage 0: 节点级 hybrid 粗筛 ----
        started = time.monotonic()
        node_hits = await cls._stage0_node_search(query, repository_ids)
        if not node_hits:
            return await cls._fallback_v1(query, top_k)

        stage0_candidates = cls._stage0_candidates(node_hits, top_k=STAGE0_REPO_K)
        # 桶仅供 Stage 1 组 prompt 取命中节点用；打分聚合已在纯函数核心内完成。
        repo_buckets = cls._aggregate_by_repo(node_hits)

        if not use_llm:
            return cls._stage0_only_result(query, node_hits, stage0_candidates, top_k, started)

        # ---- Stage 1: LLM 树推理 ----
        try:
            llm_candidates = await cls._stage1_llm_reasoning(
                query, stage0_candidates, repo_buckets, top_k
            )
        except Exception as exc:  # noqa: BLE001 — LLM 任意失败都降级 Stage 0
            logger.warning(
                "repo_router_v2_stage1_failed",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
                timeout_seconds=_stage1_conf("REPO_ROUTER_STAGE1_TIMEOUT_SECONDS"),
                category="sampling",
                component="repo_router_v2",
            )
            llm_candidates = None

        if not llm_candidates:
            # 降级路径同样产出确定性分级，margin 达标即可 auto_selected（RELY-04 解锁点）。
            return cls._stage0_only_result(query, node_hits, stage0_candidates, top_k, started)

        # LLM 只降不升已在 _stage1_llm_reasoning 内应用；auto_selected 由最终
        # （确定性 + LLM 调节后）confidence 驱动——与降级路径语义一致。
        final = llm_candidates[:top_k]
        auto_selected = bool(final) and final[0].confidence == "high"
        result = RepoRouteResultV2(
            candidates=final,
            router_version="v2",
            auto_selected=auto_selected,
            degraded=False,
            snapshot=cls._build_snapshot(query, node_hits, final),
        )
        cls._log_scored(result, started)
        return result

    # ------------------------------------------------------------------
    # Stage 0
    # ------------------------------------------------------------------

    @classmethod
    async def _stage0_node_search(
        cls, query: str, repository_ids: list[str] | None
    ) -> list[dict[str, Any]]:
        query_sparse = await sync_to_async(
            SparseEncoderService.encode, thread_sensitive=False
        )(query)
        if not query_sparse.get("indices"):
            return []
        query_dense = await EmbeddingService.generate_embedding(query)
        if not query_dense:
            return []

        filters: dict[str, Any] | None = None
        if repository_ids:
            filters = {"repository_id": [str(r) for r in repository_ids]}

        hits = await sync_to_async(
            QdrantService.hybrid_search_by_name, thread_sensitive=False
        )(
            COLLECTION_NAME,
            query_dense,
            query_sparse,
            top_k=STAGE0_NODE_K,
            filters=filters,
        )
        return hits or []

    @classmethod
    def _aggregate_by_repo(
        cls, node_hits: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """按仓分桶——仅供 Stage 1 组 prompt 取命中节点用（打分聚合走纯函数核心）。

        桶内排序 ``(-round(score, 6), node_id)``：先量化再比较 + 不可变第二键，
        消除 Qdrant 返回序依赖（ROUTE-09）。
        """
        buckets: dict[str, list[dict[str, Any]]] = {}
        for hit in node_hits:
            payload = hit.get("payload", {})
            rid = str(payload.get("repository_id", ""))
            if rid:
                buckets.setdefault(rid, []).append(hit)
        for hits in buckets.values():
            hits.sort(
                key=lambda h: (
                    -round(float(h.get("score", 0.0)), 6),
                    str((h.get("payload") or {}).get("node_id", "")),
                )
            )
        return buckets

    @classmethod
    def _stage0_candidates(
        cls, node_hits: list[dict[str, Any]], *, top_k: int
    ) -> list[dict[str, Any]]:
        """Stage 0 聚合打分薄封装——调纯函数打分核心（105-01）。

        分桶/归一/三信号加性合成/稳定排序全部在 ``aggregate_and_score`` 内完成；
        本方法只把 ``ScoredCandidate`` 转回既有 dict 形状（repo_id/repo_name/
        score/facets/hits + breakdown）并截取 top_k。
        """
        scored = aggregate_and_score(node_hits)
        return [
            {
                "repo_id": c.repo_id,
                "repo_name": c.repo_name,
                "score": c.score,
                "breakdown": c.breakdown,
                "facets": c.facets,
                "hits": c.hits,
            }
            for c in scored[:top_k]
        ]

    @classmethod
    def _deterministic_confidence(
        cls, sorted_scores: list[float], rank: int
    ) -> Confidence:
        """按 stage0 排序位置推导确定性 confidence（RELY-04）。

        规则：rank-1 候选用 ``derive_confidence``（margin 规则——high 仅
        rank-1 可得，margin 语义只对首位有定义）；rank>1 候选
        ``score >= θ_med → medium``，否则 low。
        """
        theta_abs, theta_margin, theta_med = _conf_thresholds()
        if rank <= 0:
            return derive_confidence(
                sorted_scores,
                theta_abs=theta_abs,
                theta_margin=theta_margin,
                theta_med=theta_med,
            )
        score = sorted_scores[rank] if rank < len(sorted_scores) else 0.0
        return "medium" if score >= theta_med else "low"

    @classmethod
    def _finalize_stage0(
        cls, stage0_candidates: list[dict[str, Any]], top_k: int
    ) -> list[RepoRouteCandidateV2]:
        """Stage 0 候选定稿：确定性 confidence 分级 + breakdown 透传。

        score 直接用打分核心的归一化分（S ∈ [0,1] 按构造成立，无需截断）；
        confidence 按 ``_deterministic_confidence`` 规则赋值——降级路径也能
        产出 high 并驱动 auto_selected（RELY-04 解锁点）。
        """
        sorted_scores = [float(c["score"]) for c in stage0_candidates]
        out: list[RepoRouteCandidateV2] = []
        for rank, c in enumerate(stage0_candidates[:top_k]):
            matched_paths = [
                str(h.get("payload", {}).get("node_path", ""))
                for h in c["hits"][:3]
            ]
            top_payload = c["hits"][0].get("payload", {})
            sub_project = str(top_payload.get("sub_project", "") or "")
            out.append(
                RepoRouteCandidateV2(
                    repo_id=c["repo_id"],
                    repo_name=c["repo_name"],
                    score=float(c["score"]),
                    confidence=cls._deterministic_confidence(sorted_scores, rank),
                    reasoning="命中能力节点: " + "; ".join(p for p in matched_paths if p),
                    sub_project=sub_project,
                    sub_project_paths=cls._sub_project_paths_from_hits(
                        c["hits"], sub_project
                    ),
                    matched_node_paths=[p for p in matched_paths if p],
                    breakdown=dict(c.get("breakdown") or {}),
                )
            )
        return out

    @classmethod
    def _stage0_only_result(
        cls,
        query: str,
        node_hits: list[dict[str, Any]],
        stage0_candidates: list[dict[str, Any]],
        top_k: int,
        started: float,
    ) -> RepoRouteResultV2:
        """Stage 1 未参与（use_llm=False / 失联降级）的统一出口。

        与 v2 路径语义一致：首位确定性 confidence == high → auto_selected=True，
        margin 达标时编排照常自动推进；``degraded=True`` 标记 Stage 1 未参与。
        """
        finalized = cls._finalize_stage0(stage0_candidates, top_k)
        result = RepoRouteResultV2(
            candidates=finalized,
            router_version="v2_stage0_only",
            auto_selected=bool(finalized) and finalized[0].confidence == "high",
            degraded=True,
            snapshot=cls._build_snapshot(query, node_hits, finalized),
        )
        cls._log_scored(result, started)
        return result

    @classmethod
    def _build_snapshot(
        cls,
        query: str,
        node_hits: list[dict[str, Any]],
        candidates: list[RepoRouteCandidateV2],
    ) -> dict[str, Any]:
        """组装 Stage 0 快照材料（ROUTE-09 数据底座）。

        node_hits 只存重算所需最小字段集（禁存全量 payload——防 payload 无界
        膨胀）；``index_version`` 为参与候选各仓 ``built_at`` 按 repo_id 排序
        拼接的 sha256。stage1 材料由 105-05 补充，落库由 105-07 处理。
        """
        minimal_hits: list[dict[str, Any]] = []
        for hit in node_hits:
            payload = hit.get("payload") or {}
            facets = cls._parse_json_field(payload.get("facets"), {})
            minimal_hits.append(
                {
                    "node_id": str(payload.get("node_id", "")),
                    "repository_id": str(payload.get("repository_id", "")),
                    "score": float(hit.get("score", 0.0)),
                    "node_path": str(payload.get("node_path", "")),
                    "activity_facet": facets.get("活跃度"),
                }
            )
        candidate_ids = {c.repo_id for c in candidates}
        built_at_by_repo: dict[str, str] = {}
        for hit in node_hits:
            payload = hit.get("payload") or {}
            rid = str(payload.get("repository_id", ""))
            if rid in candidate_ids and rid not in built_at_by_repo:
                built_at_by_repo[rid] = str(payload.get("built_at", ""))
        material = "|".join(
            f"{rid}:{built_at_by_repo[rid]}" for rid in sorted(built_at_by_repo)
        )
        return {
            "stage0": {"query": query, "node_hits": minimal_hits},
            "candidates": [c.to_dict() for c in candidates],
            "versions": {
                "weight_set_version": WEIGHT_SET_VERSION,
                "index_version": hashlib.sha256(material.encode("utf-8")).hexdigest(),
            },
        }

    @classmethod
    def _log_scored(cls, result: RepoRouteResultV2, started: float) -> None:
        """Stage 0 打分完成观测（debug 级——route 属高频内部步骤，禁 INFO 刷屏）。"""
        try:
            top = result.candidates[0] if result.candidates else None
            logger.debug(
                "repo_router_v2_scored",
                candidate_count=len(result.candidates),
                top_score=round(top.score, 6) if top else 0.0,
                confidence=top.confidence if top else "low",
                degraded=result.degraded,
                duration_ms=int((time.monotonic() - started) * 1000),
                category="sampling",
                component="repo_router_v2",
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
            pass

    # ------------------------------------------------------------------
    # Stage 1
    # ------------------------------------------------------------------

    @classmethod
    async def _stage1_llm_reasoning(
        cls,
        query: str,
        stage0_candidates: list[dict[str, Any]],
        repo_buckets: dict[str, list[dict[str, Any]]],
        top_k: int,
    ) -> list[RepoRouteCandidateV2] | None:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.llm_factory import build_chat_model
        from services.provider_config import (
            ProviderConfigService,
            ProviderMissingError,
            aget_claude_code_runtime_config,
        )

        resolved = await ProviderConfigService.aresolve_or_error()
        if isinstance(resolved, ProviderMissingError):
            # 静默返回 None 会让上层降级 Stage 0 且无任何痕迹——路由质量塌成全 low
            # 却查不出原因（线上实测踩过）。降级原因必须留证。
            logger.warning(
                "repo_router_v2_stage1_skipped",
                reason="provider_missing",
                category="sampling",
                component="repo_router_v2",
            )
            return None

        # 快速模型解析：优先系统设置里 Claude Code 模型映射的 haiku 档（用户可配的"小/快模型"），
        # 回退当前解析凭证的 default_model。
        # 历史 bug：此处曾读 resolved.extra.get("haiku_model")/("small_model")——但
        # aresolve_or_error().extra 只含 default_model（haiku/small 属于 Claude Code
        # 运行时配置 claude_code_config.model_mapping，不在通用 extra 里），导致用户在系统
        # 设置里配的 haiku 档永不生效、Stage 1 总是退到慢的主模型（mimo-v2.5-pro）。
        model_name = ""
        try:
            cc_rt = await aget_claude_code_runtime_config()
            model_name = (cc_rt.get("haiku_model") or "").strip()
        except Exception:  # noqa: BLE001 — CC 配置读失败不阻断，回退 default_model
            model_name = ""
        if not model_name:
            model_name = (resolved.extra or {}).get("default_model", "")
        if not model_name:
            logger.warning(
                "repo_router_v2_stage1_skipped",
                reason="no_model_configured",
                category="sampling",
                component="repo_router_v2",
            )
            return None

        timeout_seconds = float(_stage1_conf("REPO_ROUTER_STAGE1_TIMEOUT_SECONDS"))
        max_candidates = int(_stage1_conf("REPO_ROUTER_STAGE1_MAX_CANDIDATES"))
        hits_per_repo = int(_stage1_conf("REPO_ROUTER_STAGE1_HITS_PER_REPO"))

        # 快速失败即降级：max_retries=0 —— 路由是启发式，超时无需 3× 重试空等
        # （旧行为：langchain 默认 max_retries=2 → 30s×3≈90s 才放弃再回落 Stage 0）。
        model = build_chat_model(
            resolved,
            model_name,
            streaming=False,
            timeout_seconds=timeout_seconds,
            max_retries=0,
        )

        # 只把高分候选喂给 LLM：prompt 越短越快，尾部低分候选本就选不中；
        # Stage 0 仍保留完整候选集供降级时使用。
        stage0_candidates = stage0_candidates[:max_candidates]

        context_blocks: list[str] = []
        for idx, c in enumerate(stage0_candidates, 1):
            lines = [f"### 候选 {idx}: {c['repo_name']} (repo_id={c['repo_id']})"]
            facets = {
                k: v for k, v in (c.get("facets") or {}).items()
                if not k.startswith("_")
            }
            if facets:
                lines.append(f"分面: {json.dumps(facets, ensure_ascii=False)}")
            for hit in c["hits"][:hits_per_repo]:
                p = hit.get("payload", {})
                node_path = p.get("node_path", "")
                summary = p.get("summary", "")
                sub = p.get("sub_project", "")
                sub_part = f" [子应用: {sub}]" if sub else ""
                lines.append(f"- {node_path}{sub_part}: {summary}")
            context_blocks.append("\n".join(lines))

        system = SystemMessage(
            content=(
                "你是仓库路由助手。根据用户需求与各候选仓库的能力树命中节点，"
                "推理出最该改动的仓库（和 monorepo 子应用）。\n"
                "严格输出 JSON 数组（不要 markdown 包裹），每项：\n"
                '{"repo_id": str, "sub_project": str（非 monorepo 填 ""), '
                '"confidence": "high"|"medium"|"low", '
                '"reasoning": "一句中文推理理由（引用命中的能力节点路径）", '
                '"matched_node_paths": [str]}\n'
                "规则：\n"
                "- 按相关度降序，最多输出 " + str(max(top_k, 3)) + " 项，无关候选不要输出\n"
                "- 只有当需求明确指向唯一仓库时首位才给 high\n"
                "- 活跃度=疑似废弃的仓库除非别无选择，否则降级或剔除\n"
                "- repo_id 必须从候选中选取，禁止编造"
            )
        )
        human = HumanMessage(
            content=f"用户需求：{query}\n\n候选仓库及命中节点：\n\n" + "\n\n".join(context_blocks)
        )

        # 硬性上限：不管客户端/代理如何处理超时，Stage 1 绝不超过配置的超时值。
        # 超时抛 TimeoutError → 上层 route() 捕获后降级 Stage 0（0.2s 出结果），
        # 避免慢模型把整个"仓库分级路由"拖成分钟级。
        started = time.monotonic()
        response = await asyncio.wait_for(model.ainvoke([system, human]), timeout=timeout_seconds)
        from agents.llm_factory import content_to_text

        parsed = cls._parse_llm_json_array(content_to_text(response.content))
        logger.info(
            "repo_router_v2_stage1_completed",
            model=model_name,
            candidate_count=len(stage0_candidates),
            parsed_count=len(parsed or []),
            duration_ms=int((time.monotonic() - started) * 1000),
            category="sampling",
            component="repo_router_v2",
        )
        if not parsed:
            logger.warning(
                "repo_router_v2_stage1_skipped",
                reason="unparsable_llm_output",
                model=model_name,
                category="sampling",
                component="repo_router_v2",
            )
            return None

        by_id = {c["repo_id"]: c for c in stage0_candidates}
        rank_by_id = {c["repo_id"]: i for i, c in enumerate(stage0_candidates)}
        sorted_scores = [float(c["score"]) for c in stage0_candidates]
        candidates: list[RepoRouteCandidateV2] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("repo_id", ""))
            base = by_id.get(rid)
            if base is None:
                continue  # LLM 编造的 repo_id 直接丢弃
            # LLM confidence 不再直接采信（RELY-04）：先按该候选在 stage0 排序中的
            # 位置算确定性分级，LLM 输出只能降级（apply_llm_adjustment 只降不升）。
            llm_conf_raw = str(item.get("confidence", "")).lower()
            llm_conf: Confidence | None = (
                llm_conf_raw if llm_conf_raw in ("high", "medium", "low") else None  # type: ignore[assignment]
            )
            deterministic = cls._deterministic_confidence(sorted_scores, rank_by_id[rid])
            confidence = apply_llm_adjustment(deterministic, llm_conf)
            sub_project = str(item.get("sub_project", "") or "")
            matched = [
                str(p) for p in item.get("matched_node_paths", []) if str(p).strip()
            ]
            candidates.append(
                RepoRouteCandidateV2(
                    repo_id=rid,
                    repo_name=base["repo_name"],
                    score=float(base["score"]),
                    confidence=confidence,
                    reasoning=str(item.get("reasoning", "")),
                    sub_project=sub_project,
                    sub_project_paths=cls._sub_project_paths_from_hits(
                        base["hits"], sub_project
                    ),
                    matched_node_paths=matched
                    or [
                        str(h.get("payload", {}).get("node_path", ""))
                        for h in base["hits"][:3]
                    ],
                    breakdown=dict(base.get("breakdown") or {}),
                )
            )
        return candidates or None

    # ------------------------------------------------------------------
    # 降级与工具
    # ------------------------------------------------------------------

    @classmethod
    async def _fallback_v1(cls, query: str, top_k: int) -> RepoRouteResultV2:
        """repo_index_nodes 无命中 → 回落 v1 单点摘要路由。"""
        from codegraph.services.repo_router import RepoRouter

        v1_results = await RepoRouter.route(query, top_k=top_k)
        # getattr 防御：测试/调用方可能给出仅含核心字段的 stub 结果
        candidates = [
            RepoRouteCandidateV2(
                repo_id=str(r.repo_id),
                repo_name=str(getattr(r, "repo_name", "") or ""),
                score=float(getattr(r, "final_score", 0.0)),
                confidence="low",
                reasoning=str(getattr(r, "match_reason", "") or ""),
            )
            for r in v1_results
        ]
        return RepoRouteResultV2(
            candidates=candidates,
            router_version="v1_fallback",
            auto_selected=False,
            degraded=True,  # Stage 1 未参与（v1 无节点级分数，confidence 保持 low）
        )

    @classmethod
    def _sub_project_paths_from_hits(
        cls, hits: list[dict[str, Any]], sub_project: str
    ) -> list[str]:
        """从命中节点 payload 提取该子应用的根目录 paths。"""
        if not sub_project:
            return []
        paths: set[str] = set()
        for hit in hits:
            p = hit.get("payload", {})
            if str(p.get("sub_project", "")) != sub_project:
                continue
            if str(p.get("node_type", "")) == "sub_app":
                paths.update(cls._parse_json_field(p.get("paths"), []))
        if not paths:
            # 子应用根节点未命中时，退而取该子应用任意节点的首段路径
            for hit in hits:
                p = hit.get("payload", {})
                if str(p.get("sub_project", "")) != sub_project:
                    continue
                for raw in cls._parse_json_field(p.get("paths"), []):
                    segs = str(raw).strip("/").split("/")
                    if len(segs) >= 2:
                        paths.add("/".join(segs[:2]))
        return sorted(paths)[:5]

    @staticmethod
    def _parse_json_field(value: Any, default: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str) and value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return default
        return default

    @staticmethod
    def _parse_llm_json_array(raw: str) -> list[Any] | None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\[[\s\S]*\]", raw)
            if not match:
                return None
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return data if isinstance(data, list) else None


__all__ = ["RepoRouterV2", "RepoRouteCandidateV2", "RepoRouteResultV2"]
