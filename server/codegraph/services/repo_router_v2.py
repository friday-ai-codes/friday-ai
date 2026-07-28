"""推理式仓库路由 v2（PageIndex 化）。

Stage 0 — 节点级 hybrid 粗筛：query 对 `repo_index_nodes`（能力树节点）做
dense+sparse RRF 检索，按 repository_id 聚合（max score + 命中节点数加权）
取 Top-N 候选仓库。节点粒度远细于 v1 的"一仓一向量点"，模块/能力命中即召回。

Stage 1 — LLM 树推理：query + 各候选仓库的树骨架（overview + 命中节点及其
祖先路径）喂给快速模型，输出结构化选择：repo + sub_project + confidence +
reasoning + matched_node_paths。

置信度分流：high 自动选定；medium 预选 + 理由；low 返回多候选让用户选。

降级链：
- LLM 失败/超时 → Stage 0 聚合分数直接出结果（仍优于 v1：节点级检索）
- repo_index_nodes 无命中 → 回落 v1 RepoRouter（repo_summaries 单点检索）

分面信号：节点 payload 的 facets 参与排序——活跃度=疑似废弃的仓库降权，
关键程度在分数接近时作 tie-breaker。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from asgiref.sync import sync_to_async

from codegraph.services.repo_index_tree import COLLECTION_NAME
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from services.sparse_encoder import SparseEncoderService

logger = structlog.get_logger(__name__)

Confidence = Literal["high", "medium", "low"]

STAGE0_NODE_K = 50
STAGE0_REPO_K = 12
DEPRECATED_PENALTY = 0.5  # 活跃度=疑似废弃 的聚合分惩罚系数

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
        }


@dataclass
class RepoRouteResultV2:
    """v2 路由整体结果。"""

    candidates: list[RepoRouteCandidateV2]
    router_version: str  # "v2" | "v2_stage0_only" | "v1_fallback"
    auto_selected: bool  # high confidence 首位自动选定


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
        node_hits = await cls._stage0_node_search(query, repository_ids)
        if not node_hits:
            return await cls._fallback_v1(query, top_k)

        repo_buckets = cls._aggregate_by_repo(node_hits)
        stage0_candidates = cls._stage0_candidates(repo_buckets, top_k=STAGE0_REPO_K)

        if not use_llm:
            return RepoRouteResultV2(
                candidates=cls._finalize_stage0(stage0_candidates, top_k),
                router_version="v2_stage0_only",
                auto_selected=False,
            )

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
            return RepoRouteResultV2(
                candidates=cls._finalize_stage0(stage0_candidates, top_k),
                router_version="v2_stage0_only",
                auto_selected=False,
            )

        auto_selected = bool(llm_candidates) and llm_candidates[0].confidence == "high"
        return RepoRouteResultV2(
            candidates=llm_candidates[:top_k],
            router_version="v2",
            auto_selected=auto_selected,
        )

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
        buckets: dict[str, list[dict[str, Any]]] = {}
        for hit in node_hits:
            payload = hit.get("payload", {})
            rid = str(payload.get("repository_id", ""))
            if rid:
                buckets.setdefault(rid, []).append(hit)
        for hits in buckets.values():
            hits.sort(key=lambda h: float(h.get("score", 0.0)), reverse=True)
        return buckets

    @classmethod
    def _stage0_candidates(
        cls, repo_buckets: dict[str, list[dict[str, Any]]], *, top_k: int
    ) -> list[dict[str, Any]]:
        """聚合打分：max score * (1 + 0.1 * min(命中数-1, 5))，废弃仓库降权。"""
        scored: list[dict[str, Any]] = []
        for rid, hits in repo_buckets.items():
            top_hit = hits[0]
            payload = top_hit.get("payload", {})
            max_score = float(top_hit.get("score", 0.0))
            bonus = 1.0 + 0.1 * min(len(hits) - 1, 5)
            score = max_score * bonus

            facets = cls._parse_json_field(payload.get("facets"), {})
            if facets.get("活跃度") == "疑似废弃":
                score *= DEPRECATED_PENALTY

            scored.append(
                {
                    "repo_id": rid,
                    "repo_name": str(payload.get("repo_name", "unknown")),
                    "score": score,
                    "facets": facets,
                    "hits": hits,
                }
            )
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    @classmethod
    def _finalize_stage0(
        cls, stage0_candidates: list[dict[str, Any]], top_k: int
    ) -> list[RepoRouteCandidateV2]:
        out: list[RepoRouteCandidateV2] = []
        for c in stage0_candidates[:top_k]:
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
                    score=min(c["score"], 1.0),
                    confidence="low",
                    reasoning="命中能力节点: " + "; ".join(p for p in matched_paths if p),
                    sub_project=sub_project,
                    sub_project_paths=cls._sub_project_paths_from_hits(
                        c["hits"], sub_project
                    ),
                    matched_node_paths=[p for p in matched_paths if p],
                )
            )
        return out

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
        candidates: list[RepoRouteCandidateV2] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("repo_id", ""))
            base = by_id.get(rid)
            if base is None:
                continue  # LLM 编造的 repo_id 直接丢弃
            confidence_raw = str(item.get("confidence", "low")).lower()
            confidence: Confidence = (
                confidence_raw if confidence_raw in ("high", "medium", "low") else "low"
            )
            sub_project = str(item.get("sub_project", "") or "")
            matched = [
                str(p) for p in item.get("matched_node_paths", []) if str(p).strip()
            ]
            candidates.append(
                RepoRouteCandidateV2(
                    repo_id=rid,
                    repo_name=base["repo_name"],
                    score=min(float(base["score"]), 1.0),
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
