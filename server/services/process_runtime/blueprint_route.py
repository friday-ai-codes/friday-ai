"""BlueprintRouteAdapter —— 双面路由（能力树 + 章程 + 历史三分量融合，CHARTER-02 / FLOW-04）。

本 adapter **不重写路由逻辑**：`RepoRouterV2.route` 的原样输出即 `router_base` 分量，
融合只在本层做（章程分量 → `blueprint_charter_match`，历史分量 →
`blueprint_route_history`），按 feature_point `intent` 取权重向量加权。

**§13.2 冻结面**：`codegraph/services/repo_router_v2.py` 零改动、只调不改；也绝不把
章程/历史证据塞进它的 Stage1 prompt。`router_base` 是**单一不可拆分量**——
`RepoRouteCandidateV2` 没有 breakdown 字段且 `score` 已被 `min(..., 1.0)` 截顶，
外部可见的原始信号只有一个 `score`。v0.19.0 Phase 105 落地分数分解后，只需把
`router_base` 展开为其内部各信号，**本层的组装契约不变**。

**INV-6**：本文件零 ORM 写。`stage_state["routing"]` 由 112-05 的 handler 以
`StageOutcome(event="routed", stage_state_update={"routing": route() 返回值})` 落盘；
事件持久化经 `ConvergenceSessionService._emit_event`（service 单点写入），不裸写 ORM。

**降级可观测**：`router_version` 必须进 breakdown 证据——`v1_fallback` 路径下
`matched_node_paths` 恒为空且 `score` 与 v2 不同源，没有 `router_version` 前端无法
解释「为什么这个候选没有能力节点证据」。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from services.process_runtime import blueprint_charter_match as _charter_module
from services.process_runtime.blueprint_route_history import ascore_history_match

logger = structlog.get_logger(__name__)

__all__ = [
    "BlueprintRouteAdapter",
    "build_score_breakdown",
    "aload_route_weights",
    "resolve_boundary_override",
    "DEFAULT_ROUTE_WEIGHTS",
]

# 按 intent 的权重向量默认值（与 SettingKeys.BLUEPRINT_ROUTE_WEIGHTS 注释逐字一致）。
# greenfield 净新增：能力树无节点可依，重章程（应该归谁）与历史（同类需求上次落哪）；
# brownfield/fix 改造与修复：改的是**既有代码**，能力树命中才是硬证据 → router_base 主导。
DEFAULT_ROUTE_WEIGHTS: dict[str, dict[str, float]] = {
    "greenfield": {"router_base": 0.40, "charter_match": 0.35, "history_match": 0.25},
    "brownfield": {"router_base": 0.60, "charter_match": 0.20, "history_match": 0.20},
    "fix": {"router_base": 0.70, "charter_match": 0.15, "history_match": 0.15},
}

_COMPONENT_KEYS = ("router_base", "charter_match", "history_match")

# breakdown 证据的固定键清单（112-04/05 的读取面，逐字对齐 112-03-PLAN 契约表）。
_EVIDENCE_KEYS = (
    "router_version",
    "auto_selected",
    "confidence",
    "reasoning",
    "matched_node_paths",
    "charter_source",
    "charter_version",
    "matched_domains",
    "violated_boundaries",
    "penalty_reasons",
    "history_match_unavailable",
    "boundary_override_reason",
    "unjustified_boundary_hit",
    # Phase 125 / MOD-04：社区模块摘要（evidence only，不进三分量打分）
    "module_summaries",
)

_VALID_INTENTS = ("greenfield", "brownfield", "fix")
# 平票时取的保守 intent（混合需求不当纯 greenfield 处理，见 _resolve_dominant_intent）
_TIE_BREAK_INTENT = "brownfield"

_DEFAULT_TOP_K = 5
_MAX_QUERY_CHARS = 2000
_MAX_REASON_CHARS = 300
_MAX_SUPPLEMENT_CANDIDATES = 5

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


# ── 权重加载 ──────────────────────────────────────────────────────────────


async def aload_route_weights() -> dict[str, dict[str, float]]:
    """读 `blueprint.route.weights` 并逐项归一（T-112-12：极端配置绝不反噬排序）。

    逐 intent 逐分量 `float()` 强转、负值取 0、缺分量回该 intent 默认、
    intent 值非 dict 回该 intent 默认、整段非 dict 回全默认；任何异常回全默认，**绝不抛**。
    """
    try:
        from system.models import SettingKeys
        from system.settings_service import aget_json_setting

        raw = await aget_json_setting(SettingKeys.BLUEPRINT_ROUTE_WEIGHTS, DEFAULT_ROUTE_WEIGHTS)
    except Exception as exc:  # noqa: BLE001 — 配置读失败回默认，绝不阻断路由
        logger.warning(
            "blueprint_route_weights_load_failed",
            error=str(exc),
            category="sampling",
            component="process_runtime",
        )
        raw = DEFAULT_ROUTE_WEIGHTS

    if not isinstance(raw, dict):
        return {intent: dict(vec) for intent, vec in DEFAULT_ROUTE_WEIGHTS.items()}

    resolved: dict[str, dict[str, float]] = {}
    for intent, defaults in DEFAULT_ROUTE_WEIGHTS.items():
        candidate = raw.get(intent)
        if not isinstance(candidate, dict):
            resolved[intent] = dict(defaults)
            continue
        vector: dict[str, float] = {}
        for key, default in defaults.items():
            if key not in candidate:
                vector[key] = default
                continue
            try:
                value = float(candidate[key])
            except (TypeError, ValueError):
                value = default
            vector[key] = max(0.0, value)
        resolved[intent] = vector
    return resolved


def _weights_for(weights: dict, intent: str) -> dict[str, float]:
    """取某 intent 的权重向量（缺失回该 intent 默认，非法 intent 回 brownfield 默认）。"""
    defaults = DEFAULT_ROUTE_WEIGHTS.get(intent) or DEFAULT_ROUTE_WEIGHTS[_TIE_BREAK_INTENT]
    vector = (weights or {}).get(intent)
    if not isinstance(vector, dict):
        return dict(defaults)
    return {key: float(vector.get(key, defaults[key])) for key in _COMPONENT_KEYS}


# ── breakdown 组装（本 plan 最重要的可验证纯函数） ──────────────────────────


def build_score_breakdown(
    *,
    router_base: float,
    charter_match: float,
    history_match: float,
    weights: dict,
    evidence: dict,
) -> dict:
    """三分量加权组装（**纯函数**）：`total` 恒等于三项加权值之和。

    `total = sum(components.values())` —— 由**同一批浮点值**求和得出，绝不另算一遍：
    「各项之和等于总分」是恒等式（CHARTER-02 的可拆解要求）而非近似。
    """
    vector = {
        key: float((weights or {}).get(key, DEFAULT_ROUTE_WEIGHTS[_TIE_BREAK_INTENT][key]))
        for key in _COMPONENT_KEYS
    }
    components = {
        "router_base": vector["router_base"] * float(router_base or 0.0),
        "charter_match": vector["charter_match"] * float(charter_match or 0.0),
        "history_match": vector["history_match"] * float(history_match or 0.0),
    }
    return {
        **components,
        "total": sum(components.values()),
        "weights": vector,
        "evidence": _normalize_evidence(evidence),
    }


def _normalize_evidence(evidence: dict | None) -> dict:
    """证据补齐为固定键清单（缺键给中性默认，下游无需 `.get` 兜底）。"""
    src = evidence if isinstance(evidence, dict) else {}
    defaults: dict[str, Any] = {
        "router_version": "",
        "auto_selected": False,
        "confidence": "",
        "reasoning": "",
        "matched_node_paths": [],
        "charter_source": "",
        "charter_version": 0,
        "matched_domains": [],
        "violated_boundaries": [],
        "penalty_reasons": [],
        "history_match_unavailable": "",
        "boundary_override_reason": "",
        "unjustified_boundary_hit": False,
        "module_summaries": [],
    }
    return {key: src.get(key, defaults[key]) for key in _EVIDENCE_KEYS}


# ── 禁区候选的显式保留理由（ROADMAP SC2 后半） ─────────────────────────────


def resolve_boundary_override(
    *,
    violated_boundaries: list[str],
    router_reasoning: str = "",  # noqa: ARG001 — 仅保留签名兼容，判定不认它（见 docstring）
    llm_reason: str = "",
) -> tuple[str, bool]:
    """判定禁区命中候选的保留理由（**纯函数**，T-112-14b）。

    候选**只降权不淘汰**，因此凡留在候选列表里的禁区命中仓都必须有一条显式理由；
    拿不到理由就打 `unjustified_boundary_hit` 标记——不允许「命中禁区却无人解释为何还留着」。

    **只认针对禁区的判断**：理由唯一来源是 sanity-check LLM 的 `llm_reason`。路由器的
    `router_reasoning` 是能力树命中说明（形如 `"命中能力节点: ..."`），与「为什么明令
    不承接却还留着」毫无关系，且对召回的候选恒非空——拿它当理由会让
    `unjustified_boundary_hit` 几乎永远为 False，「LLM 必须给显式理由」只在形式上成立。
    该字段仅作展示留在 evidence 里，不参与判定。

    Returns:
        `(boundary_override_reason, unjustified_boundary_hit)`。未命中禁区恒
        `("", False)`；命中禁区时**恰有其一为真**（`bool(reason) != unjustified`）。
    """
    if not violated_boundaries:
        return "", False
    reason = str(llm_reason or "").strip()
    if reason:
        return reason[:_MAX_REASON_CHARS], False
    return "", True


def _boundary_explain_system_prompt() -> str:
    return (
        "你是代码仓库归属评审助手。给定若干「命中了自身章程禁区规则、但仍被路由器保留为候选」"
        "的仓库，请为每个仓库给出**一句话**的保留理由（为什么本次需求仍可能落在它身上），"
        "或明确说明无法给出理由。\n"
        '只输出 JSON 对象，形如 {"<repository_id>": "<一句话理由>"}；'
        "无法给出理由的仓库直接省略该键，不要编造。不要输出 JSON 以外的任何内容。"
    )


def _boundary_explain_prompt(pending: list[dict]) -> str:
    lines: list[str] = []
    for item in pending:
        rules = "; ".join(str(r) for r in item.get("violated_boundaries") or [])
        lines.append(
            f"### {item.get('repository_id', '')}\n"
            f"- 仓库名: {item.get('repository_name', '')}\n"
            f"- 命中的章程禁区: {rules[:_MAX_REASON_CHARS]}"
        )
    return "\n".join(lines)


def _parse_reason_map(text: str) -> dict[str, str]:
    """从 LLM 文本解析 `{repository_id: reason}`（```json 围栏 + 裸 JSON 双路，失败返 {}）。"""
    raw = str(text or "").strip()
    if not raw:
        return {}
    fenced = _JSON_FENCE.search(raw)
    payloads = [fenced.group(1)] if fenced else []
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        payloads.append(raw[start : end + 1])
    for payload in payloads:
        try:
            parsed = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    return {}


def _content_to_text(content: Any) -> str:
    """LLM 响应 content 归一为文本（兼容 reasoning 模型的 content_blocks 列表）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


async def _aexplain_boundary_overrides(pending: list[dict]) -> dict[str, str]:
    """**单次** sanity-check LLM 调用为全部待补候选补保留理由（绝不逐候选调）。

    白名单归一：只保留入参内的 `repository_id`、理由截断 300。
    `call_source` 复用路由族已注册的 `BLUEPRINT_REROUTE`（`agents/call_source.py`
    不在本相位可改文件内，不新增枚举值），日志/事件 kv 用
    `reason_kind="boundary_override"` 区分子用途。整段吞异常返 `{}`（best-effort）。
    """
    if not pending:
        return {}

    started = time.monotonic()
    allowed = {str(item.get("repository_id", "")) for item in pending}
    logger.info(
        "blueprint_route_boundary_explain_started",
        pending_count=len(pending),
        reason_kind="boundary_override",
        category="sampling",
        component="process_runtime",
    )
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.warning(
                "blueprint_route_boundary_explain_failed",
                reason="no_default_model",
                reason_kind="boundary_override",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                category="sampling",
                component="process_runtime",
            )
            return {}

        model = build_chat_model(resolved, model_name, streaming=False)
        messages = [
            SystemMessage(content=_boundary_explain_system_prompt()),
            HumanMessage(content=_boundary_explain_prompt(pending)),
        ]
        with use_call_source(CallSource.BLUEPRINT_REROUTE):
            response = await model.ainvoke(messages)

        parsed = _parse_reason_map(_content_to_text(getattr(response, "content", "")))
        reasons = {
            repository_id: reason.strip()[:_MAX_REASON_CHARS]
            for repository_id, reason in parsed.items()
            if repository_id in allowed and str(reason or "").strip()
        }
        logger.info(
            "blueprint_route_boundary_explain_completed",
            pending_count=len(pending),
            explained_count=len(reasons),
            reason_kind="boundary_override",
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            category="sampling",
            component="process_runtime",
        )
        return reasons
    except Exception as exc:  # noqa: BLE001 — best-effort：LLM 不可得不阻断路由
        from common.logging import redact_secrets_in_text

        logger.warning(
            "blueprint_route_boundary_explain_failed",
            error=redact_secrets_in_text(str(exc)),
            reason_kind="boundary_override",
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            category="sampling",
            component="process_runtime",
        )
        return {}


# ── 需求文本抽取 ──────────────────────────────────────────────────────────


def _blocks_to_text(blocks: Any) -> str:
    """Block[] → 纯文本（只取 paragraph/list 的 text，路由只需语义文本不需渲染）。"""
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, list):
            parts.extend(entry for entry in text if isinstance(entry, str) and entry)
        elif isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


def _collect_query_terms(requirement_spec: dict) -> list[str]:
    """规范化出章程/历史命中判定用的 query_terms（goal + 各功能点 title/description）。"""
    terms: list[str] = []
    goal = _blocks_to_text(requirement_spec.get("goal"))
    if goal:
        terms.append(goal)
    for point in requirement_spec.get("feature_points") or []:
        if not isinstance(point, dict):
            continue
        title = str(point.get("title") or "").strip()
        if title:
            terms.append(title)
        description = _blocks_to_text(point.get("description"))
        if description:
            terms.append(description)
    return terms


def _resolve_dominant_intent(requirement_spec: dict) -> str:
    """主导 intent：单功能点取其 intent；多功能点取多数；**平票取保守的 brownfield**。

    平票取 brownfield 而非 greenfield 是刻意的：混合需求里只要有改造分量，把整单当
    「纯净新增」处理会过度放大章程权重，让「章程写了但代码里啥都没有」的仓压过真正
    要改的仓。保守方向 = 更信能力树。
    """
    counts: dict[str, int] = {}
    for point in requirement_spec.get("feature_points") or []:
        if not isinstance(point, dict):
            continue
        intent = str(point.get("intent") or "").strip().lower()
        if intent in _VALID_INTENTS:
            counts[intent] = counts.get(intent, 0) + 1
    if not counts:
        return _TIE_BREAK_INTENT
    top = max(counts.values())
    winners = [intent for intent, count in counts.items() if count == top]
    if len(winners) == 1:
        return winners[0]
    return _TIE_BREAK_INTENT


@sync_to_async
def _load_spec_from_artifact_sync(session) -> dict:
    """从当前产物版本读 `requirement_spec`（同步 ORM + FK 经 sync_to_async）。"""
    version = session.current_artifact_version
    if version is None:
        return {}
    content = version.content if isinstance(version.content, dict) else {}
    spec = content.get("requirement_spec")
    return spec if isinstance(spec, dict) else {}


async def _aresolve_requirement_spec(session) -> dict:
    """三级解析当前蓝图 `requirement_spec`：stage_state.blueprint → stage_state → 产物版本。

    在途蓝图（intake/decompose/spec_gate 阶段产物）挂 `stage_state`，已落版本的蓝图
    在 `current_artifact_version.content`；两处都读不到返回 `{}`（route 会短路）。
    """
    stage_state = getattr(session, "stage_state", None) or {}
    if isinstance(stage_state, dict):
        for holder in (stage_state.get("blueprint"), stage_state):
            if not isinstance(holder, dict):
                continue
            spec = holder.get("requirement_spec")
            if isinstance(spec, dict) and spec:
                return spec
    if getattr(session, "current_artifact_version_id", None):
        try:
            return await _load_spec_from_artifact_sync(session)
        except Exception as exc:  # noqa: BLE001 — best-effort：读产物失败按无 spec 处理
            from common.logging import redact_secrets_in_text

            logger.warning(
                "blueprint_route_spec_load_failed",
                session_id=str(getattr(session, "id", "")),
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component="process_runtime",
            )
    return {}


# ── adapter ───────────────────────────────────────────────────────────────


class BlueprintRouteAdapter:
    """蓝图 `route` stage 依赖：能力树路由 + 章程分量 + 历史分量的融合 adapter。

    策略全 keyword-only 可注入（测试注 mock，生产零参构造）：`router` 需有
    `route(query, top_k=, repository_ids=, use_llm=)`；`charter` 需有
    `aload_charters` / `acollect_charter_candidates` / `score_charter_match`；
    `history` 是 `ascore_history_match` 形状的 async 函数。
    """

    def __init__(self, *, router=None, charter=None, history=None, top_k: int = _DEFAULT_TOP_K):
        self._router = router
        self._charter = charter or _charter_module
        self._history = history or ascore_history_match
        self.top_k = top_k

    def _resolve_router(self):
        if self._router is not None:
            return self._router
        from codegraph.services.repo_router_v2 import RepoRouterV2

        return RepoRouterV2

    async def route(
        self,
        session,
        *,
        exclude_repository_ids: set[str] | None = None,
        ignore_pin: bool = False,
    ) -> dict:
        """双面路由主入口，返回 `stage_state["routing"]` 契约摘要（顶层 8 键）。

        `exclude_repository_ids` 供 reroute 轮**补候选**复用本入口：被判 `unsuitable`
        的仓与已试过的仓一律排除在外，路由器候选与章程补入候选**两条来源同时剔除**，
        使重路由真的能取到「排除集之外的新仓」。默认 `None` ⇒ 与首轮调用逐字同行为。

        `ignore_pin`（stage 单跑层专用）：`True` 时跳过项目手动绑定的固定路由短路，
        走完整三分量自动路由——供「对比人工绑定 vs 自动路由」的能力测试用。
        缺省 `False` ⇒ 正式编排调用点行为逐字不变。
        """
        started = time.monotonic()
        excluded = {str(rid) for rid in (exclude_repository_ids or set()) if str(rid or "")}
        requirement_spec = await self._aresolve_requirement_spec(session)
        query_terms = _collect_query_terms(requirement_spec)
        # 节点重跑的操作员补充指令（quick 260806）：拼进路由 query，参与能力树检索与
        # 章程/历史命中判定——「带着这段话重新路由」的落点。无指令时零扰动。
        from services.process_runtime.blueprint_stage_rerun import operator_instruction

        instruction = operator_instruction(session)
        if instruction:
            query_terms = [*query_terms, instruction]
        query = "\n".join(query_terms)[:_MAX_QUERY_CHARS]
        intent = _resolve_dominant_intent(requirement_spec)
        weights = await aload_route_weights()

        if not query.strip():
            # 空需求短路：不调路由器、不打库；形状与正常路径完全一致（下游无需判空分支）
            return self._empty_result(intent="", weights_used={})

        # 固定路由（repo binding pin）：项目已在项目级手动绑定仓库+分支时，人工关联即
        # 最终裁决——跳过能力树检索与 LLM 路由，候选集就是绑定仓（尊重 reroute 的排除集，
        # ⛔ 绑定项目**不补新仓**：固定的意义正是仓库集不随重路由漂移）。
        pinned = None if ignore_pin else await self._aresolve_pinned(session, excluded=excluded)
        if pinned is not None:
            summary = self._pinned_summary(
                pinned,
                intent=intent,
                weights_used=_weights_for(weights, intent),
            )
            await self._emit_scored(session, summary)
            logger.info(
                "blueprint_route_pinned_by_project_binding",
                session_id=str(getattr(session, "id", "")),
                candidate_count=len(summary["candidates"]),
                excluded_count=len(excluded),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                category="sampling",
                component="process_runtime",
            )
            return summary

        repository_ids = await self._resolve_repository_ids(session)
        router = self._resolve_router()
        result = await router.route(
            query, top_k=self.top_k, repository_ids=repository_ids, use_llm=True
        )
        router_version = str(getattr(result, "router_version", "") or "")
        auto_selected = bool(getattr(result, "auto_selected", False))

        # 逐字段显式映射（不 to_dict() 整包透传：新增分量时形状变更点唯一）
        raw_candidates: list[dict] = [
            {
                "repository_id": str(getattr(c, "repo_id", "") or ""),
                "repository_name": str(getattr(c, "repo_name", "") or ""),
                "router_base": float(getattr(c, "score", 0.0) or 0.0),
                "confidence": str(getattr(c, "confidence", "") or ""),
                "reasoning": str(getattr(c, "reasoning", "") or ""),
                "matched_node_paths": list(getattr(c, "matched_node_paths", []) or []),
                "charter_supplement": False,
            }
            for c in getattr(result, "candidates", []) or []
            if str(getattr(c, "repo_id", "") or "")
            and str(getattr(c, "repo_id", "")) not in excluded
        ]

        supplements = await self._collect_supplements(
            query_terms=query_terms,
            exclude_repository_ids={c["repository_id"] for c in raw_candidates} | excluded,
            repository_ids=repository_ids,
        )
        raw_candidates.extend(supplements)
        # 118（LIVE-02）：召回一完成就发一条活动事件——打分/调研可能要跑好几十秒，
        # 在此之前用户此前看到的只有一个转圈。⛔ best-effort，绝不反噬路由。
        await self._emit_recalled(
            session,
            candidate_count=len(raw_candidates),
            router_candidate_count=len(raw_candidates) - len(supplements),
            charter_supplement_count=len(supplements),
            scope_repository_count=len(repository_ids or []),
            router_version=router_version,
            intent=intent,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        if not raw_candidates:
            # 路由器与章程都没给出候选：透传真实 router_version（不谎报 "skipped"，
            # 「跑了但没召回」与「没跑」对 115 排障是两件事）
            return self._empty_result(
                intent=intent,
                weights_used=_weights_for(weights, intent),
                router_version=router_version,
            )

        candidate_ids = [c["repository_id"] for c in raw_candidates]
        charters = await self._aload_charters(candidate_ids)
        history = await self._ascore_history(
            query=query, candidate_ids=candidate_ids, session=session
        )
        module_by_repo = await self._aload_module_summaries(
            candidate_ids, query=query
        )

        vector = _weights_for(weights, intent)
        citations: list[dict] = []
        seen_citations: set[str] = set()
        candidates: list[dict] = []
        for raw in raw_candidates:
            repository_id = raw["repository_id"]
            charter_result = self._score_charter(charters.get(repository_id), query_terms)
            history_score = float(history.scores.get(repository_id, 0.0))
            evidence = {
                "router_version": router_version,
                "auto_selected": auto_selected,
                "confidence": raw["confidence"],
                "reasoning": raw["reasoning"],
                "matched_node_paths": raw["matched_node_paths"],
                "charter_source": charter_result.charter_source,
                "charter_version": charter_result.charter_version,
                "matched_domains": charter_result.matched_domains or raw.get("matched_domains", []),
                "violated_boundaries": charter_result.violated_boundaries,
                "penalty_reasons": charter_result.penalty_reasons,
                "history_match_unavailable": history.unavailable_reason,
                "boundary_override_reason": "",
                "unjustified_boundary_hit": False,
                "module_summaries": module_by_repo.get(repository_id, []),
            }
            breakdown = build_score_breakdown(
                router_base=raw["router_base"],
                charter_match=charter_result.score,
                history_match=history_score,
                weights=vector,
                evidence=evidence,
            )
            candidates.append(
                {
                    "repository_id": repository_id,
                    "repository_name": raw["repository_name"],
                    "confidence": raw["confidence"],
                    "total": breakdown["total"],
                    "breakdown": {key: breakdown[key] for key in _COMPONENT_KEYS},
                    "evidence": breakdown["evidence"],
                }
            )
            self._collect_citations(
                citations,
                seen_citations,
                repository_id=repository_id,
                charter_result=charter_result,
            )

        self._collect_history_citations(citations, seen_citations, history=history)
        candidates.sort(key=lambda c: (-c["total"], c["repository_id"]))
        unjustified_count = await self._apply_boundary_overrides(candidates)
        for candidate in candidates:
            candidate["role_suggestion"] = _role_suggestion(candidate)

        summary = {
            "router_version": router_version,
            "auto_selected": auto_selected,
            "intent": intent,
            "weights_used": vector,
            "charter_supplement_count": len(supplements),
            "unjustified_boundary_hit_count": unjustified_count,
            "candidates": candidates,
            "citations": citations,
        }
        await self._emit_scored(session, summary)
        logger.info(
            "blueprint_route_completed",
            session_id=str(getattr(session, "id", "")),
            candidate_count=len(candidates),
            router_version=router_version,
            intent=intent,
            charter_supplement_count=len(supplements),
            unjustified_boundary_hit_count=unjustified_count,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            category="sampling",
            component="process_runtime",
        )
        return summary

    # ── 内部步骤（各自 best-effort，单个依赖失败不拖垮路由） ──────────────

    async def _aresolve_pinned(self, session, *, excluded: set[str]) -> list[dict] | None:
        """解析项目手动绑定的固定候选（repo binding pin）。

        Returns:
            ``None`` = 项目无手动绑定 → 走既有自动路由；
            ``list``（可为空）= 项目有绑定 → 固定路由短路。空列表出现在 reroute 排除集
            覆盖了全部绑定仓时——固定项目**不补新仓**，补候选为空由确认门升人裁决。
        """
        from services.process_runtime.repo_binding_pin import asession_pinned_bindings

        bindings = await asession_pinned_bindings(session)
        if not bindings:
            return None
        return [b for b in bindings if b["repository_id"] not in excluded]

    @staticmethod
    def _pinned_summary(pinned: list[dict], *, intent: str, weights_used: dict) -> dict:
        """把固定绑定映射为 112-03 契约摘要（形状与自动路由逐键一致，下游零改动）。

        绑定仓一律 ``confidence="high"`` / ``role_suggestion="direct"``（人工关联即
        最高置信，全部深调研）；分量恒 ``router_base=1.0``、章程/历史 0（未参与打分，
        breakdown 如实反映「没跑」而不是伪造分数）。
        """
        from services.process_runtime.repo_binding_pin import PINNED_ROUTER_VERSION

        candidates = [
            {
                "repository_id": b["repository_id"],
                "repository_name": b["repository_name"],
                "confidence": "high",
                "total": 1.0,
                "breakdown": {"router_base": 1.0, "charter_match": 0.0, "history_match": 0.0},
                "evidence": _normalize_evidence(
                    {
                        "router_version": PINNED_ROUTER_VERSION,
                        "auto_selected": True,
                        "confidence": "high",
                        "reasoning": (
                            f"项目已手动绑定该仓库（分支 {b['branch_name']}），"
                            "按人工关联结果固定路由，未经自动仓库路由"
                        ),
                    }
                ),
                "role_suggestion": "direct",
                "pinned_branch": b["branch_name"],
            }
            for b in pinned
        ]
        return {
            "router_version": PINNED_ROUTER_VERSION,
            "auto_selected": True,
            "intent": intent,
            "weights_used": weights_used,
            "charter_supplement_count": 0,
            "unjustified_boundary_hit_count": 0,
            "candidates": candidates,
            "citations": [],
        }

    @staticmethod
    def _empty_result(*, intent: str, weights_used: dict, router_version: str = "skipped") -> dict:
        """空候选结果（形状与正常路径逐键一致，112-04/05 无需判空分支）。"""
        return {
            "router_version": router_version or "skipped",
            "auto_selected": False,
            "intent": intent,
            "weights_used": weights_used,
            "charter_supplement_count": 0,
            "unjustified_boundary_hit_count": 0,
            "candidates": [],
            "citations": [],
        }

    async def _aresolve_requirement_spec(self, session) -> dict:
        return await _aresolve_requirement_spec(session)

    async def _collect_supplements(
        self, *, query_terms: list[str], exclude_repository_ids: set[str], repository_ids
    ) -> list[dict]:
        """章程补入候选 → 内部候选形状（`router_base=0.0`、`confidence="low"`）。"""
        try:
            collected = await self._charter.acollect_charter_candidates(
                query_terms=query_terms,
                exclude_repository_ids=exclude_repository_ids,
                repository_ids=repository_ids,
                limit=_MAX_SUPPLEMENT_CANDIDATES,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort：补入失败退化为「无补入」
            logger.warning(
                "blueprint_route_charter_supplement_failed",
                error=str(exc),
                category="sampling",
                component="process_runtime",
            )
            return []
        return [
            {
                "repository_id": str(item.get("repository_id", "")),
                "repository_name": str(item.get("repository_name", "")),
                # 能力树未召回 → router_base 恒 0.0，排序差异完全归因章程分量
                "router_base": 0.0,
                "confidence": "low",
                "reasoning": "章程 owned_domains 命中（能力树未召回）",
                "matched_node_paths": [],
                "matched_domains": item.get("matched_domains") or [],
                "charter_supplement": True,
            }
            for item in collected or []
            if str(item.get("repository_id", ""))
        ]

    async def _aload_charters(self, candidate_ids: list[str]) -> dict[str, dict]:
        try:
            return await self._charter.aload_charters(candidate_ids)
        except Exception as exc:  # noqa: BLE001 — 章程读失败 → 章程分量全 0，不阻断路由
            logger.warning(
                "blueprint_route_charter_load_failed",
                error=str(exc),
                category="sampling",
                component="process_runtime",
            )
            return {}

    async def _aload_module_summaries(
        self, candidate_ids: list[str], *, query: str
    ) -> dict[str, list[dict]]:
        """fail-soft 加载仓模块摘要进 evidence（MOD-04 / D-14）；失败 → 各仓 []。"""
        try:
            from services.module_summary_signal import aload_module_summaries_for_repos

            return await aload_module_summaries_for_repos(
                candidate_ids, query=query
            )
        except Exception as exc:  # noqa: BLE001 — 摘要读失败不阻断路由
            from common.logging import redact_secrets_in_text

            logger.warning(
                "blueprint_route_module_summary_load_failed",
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component="process_runtime",
            )
            return {str(rid): [] for rid in candidate_ids}

    def _score_charter(self, charter: dict | None, query_terms: list[str]):
        try:
            return self._charter.score_charter_match(charter, query_terms=query_terms)
        except Exception as exc:  # noqa: BLE001 — 单仓打分失败按「无章程」处理
            logger.warning(
                "blueprint_route_charter_score_failed",
                error=str(exc),
                category="sampling",
                component="process_runtime",
            )
            return _charter_module.CharterMatchResult(penalty_reasons=["charter_score_error"])

    async def _ascore_history(self, *, query: str, candidate_ids: list[str], session):
        from services.process_runtime.blueprint_route_history import HistoryMatchResult

        try:
            return await self._history(
                query=query, candidate_repository_ids=candidate_ids, session=session
            )
        except Exception as exc:  # noqa: BLE001 — 历史分量失败显式标记，不静默当 0 分
            logger.warning(
                "blueprint_route_history_score_failed",
                error=str(exc),
                category="sampling",
                component="process_runtime",
            )
            return HistoryMatchResult(unavailable_reason="retrieval_error")

    async def _apply_boundary_overrides(self, candidates: list[dict]) -> int:
        """禁区命中候选的显式保留理由（SC2 后半）：单次 LLM 覆盖全部禁区命中候选。

        **全部**禁区命中候选都进 sanity-check 批次（不再按路由器 `reasoning` 是否为空筛
        —— 那是能力树命中说明，不是禁区保留理由，且恒非空，会让这条 LLM 路径变成死代码）；
        拿不到理由的候选被打 `unjustified_boundary_hit` 标记（只降权不淘汰，但不允许
        无人解释地保留）。
        """
        hits = [c for c in candidates if c["evidence"]["violated_boundaries"]]
        if not hits:
            return 0

        pending = [
            {
                "repository_id": c["repository_id"],
                "repository_name": c["repository_name"],
                "violated_boundaries": c["evidence"]["violated_boundaries"],
            }
            for c in hits
        ]
        llm_reasons = await _aexplain_boundary_overrides(pending)

        unjustified = 0
        for candidate in hits:
            evidence = candidate["evidence"]
            reason, flagged = resolve_boundary_override(
                violated_boundaries=evidence["violated_boundaries"],
                router_reasoning=str(evidence["reasoning"] or ""),
                llm_reason=llm_reasons.get(candidate["repository_id"], ""),
            )
            evidence["boundary_override_reason"] = reason
            evidence["unjustified_boundary_hit"] = flagged
            if flagged:
                unjustified += 1
                # 禁区规则正文不进日志（T-112-13），只记关联键与计数
                logger.warning(
                    "blueprint_route_unjustified_boundary_hit",
                    repository_id=candidate["repository_id"],
                    violated_count=len(evidence["violated_boundaries"]),
                    category="sampling",
                    component="process_runtime",
                )
        return unjustified

    @staticmethod
    def _collect_citations(
        citations: list[dict],
        seen: set[str],
        *,
        repository_id: str,
        charter_result,
    ) -> None:
        """章程被引用 → `source_type=repo_charter` 引用条目（只产条目，不写蓝图）。"""
        for entry in charter_result.matched_domains or []:
            domain = str(entry.get("domain", "")) if isinstance(entry, dict) else ""
            citation_id = f"cit_charter_{repository_id}_{domain}"
            if not domain or citation_id in seen:
                continue
            seen.add(citation_id)
            citations.append(
                {
                    "citation_id": citation_id,
                    "source_type": "repo_charter",
                    "source_id": repository_id,
                    "locator": {"domain": domain},
                }
            )

    @staticmethod
    def _collect_history_citations(citations: list[dict], seen: set[str], *, history) -> None:
        """history 命中 → `source_type=knowledge_entity` 引用条目。"""
        for entity_id in history.citation_ids or []:
            citation_id = f"cit_knowledge_{entity_id}"
            if citation_id in seen:
                continue
            seen.add(citation_id)
            citations.append(
                {
                    "citation_id": citation_id,
                    "source_type": "knowledge_entity",
                    "source_id": str(entity_id),
                    "locator": {},
                }
            )

    async def _emit_recalled(self, session, **fields) -> None:
        """写 `blueprint.route.recalled`（118，LIVE-02）：召回规模与来源构成，整段吞异常。"""
        try:
            from delivery.services.convergence_session_service import ConvergenceSessionService
            from delivery.services.event_taxonomy import EVENT_BLUEPRINT_ROUTE_RECALLED

            await ConvergenceSessionService().aemit_event(
                EVENT_BLUEPRINT_ROUTE_RECALLED, session, dict(fields)
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬路由主流程
            pass

    async def _emit_scored(self, session, summary: dict) -> None:
        """写 `blueprint.route.scored` 事件（供 115 展开），整段吞异常。

        118 起每个候选**补齐 ``repository_name`` / ``confidence`` / ``role_suggestion``**：
        前端进度文案本来就按 ``repository_name`` 插值，而此前 payload 只有
        ``repository_id`` ⇒ 文案一路退化成无参兜底（「正在调研…」而不是「正在调研 xxx 仓」）。
        补的都是标量/枚举，不触碰 INV-5。
        """
        try:
            from delivery.services.convergence_session_service import ConvergenceSessionService
            from delivery.services.event_taxonomy import EVENT_BLUEPRINT_ROUTE_SCORED

            payload = {
                "candidate_count": len(summary["candidates"]),
                "router_version": summary["router_version"],
                "auto_selected": summary["auto_selected"],
                "charter_supplement_count": summary["charter_supplement_count"],
                "unjustified_boundary_hit_count": summary["unjustified_boundary_hit_count"],
                "intent": summary["intent"],
                "weights_used": summary["weights_used"],
                "candidates": [
                    {
                        "repository_id": c["repository_id"],
                        "repository_name": c.get("repository_name", ""),
                        "confidence": c.get("confidence", ""),
                        "role_suggestion": c.get("role_suggestion", ""),
                        "total": c["total"],
                        "router_base": c["breakdown"]["router_base"],
                        "charter_match": c["breakdown"]["charter_match"],
                        "history_match": c["breakdown"]["history_match"],
                    }
                    for c in summary["candidates"]
                ],
            }
            await ConvergenceSessionService().aemit_event(
                EVENT_BLUEPRINT_ROUTE_SCORED, session, payload
            )
            await self._emit_plan_drafted(session, summary)
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬路由主流程
            pass

    async def _emit_plan_drafted(self, session, summary: dict) -> None:
        """写 `blueprint.route.plan_drafted`（118，LIVE-02）：初步仓库路由方案。

        与 ``route.scored`` 的分工：scored 是**打分明细**（三分量与权重），本事件是**结论**
        ——每个仓建议承担什么角色、凭什么证据（命中的能力树节点数 / 章程域数 / 触碰的边界数
        / 引用 id）。前端据此在路由阶段直接展示「仓 1、仓 2、仓 3」的初步方案，而不必等
        确认门开出来才第一次看到仓库集。

        ⛔ **不带 `reasoning` 自由文本**：路由理由的正文归蓝图 content 的
        ``repo_associations[].reason``（查看器已渲染）与 citation 池，事件流只给指针。
        """
        try:
            from delivery.services.convergence_session_service import ConvergenceSessionService
            from delivery.services.event_taxonomy import EVENT_BLUEPRINT_ROUTE_PLAN_DRAFTED

            citation_ids_by_repo: dict[str, list[str]] = {}
            for citation in summary.get("citations") or []:
                if not isinstance(citation, dict):
                    continue
                source_id = str(citation.get("source_id") or "")
                citation_id = str(citation.get("citation_id") or "")
                if source_id and citation_id:
                    citation_ids_by_repo.setdefault(source_id, []).append(citation_id)

            repositories = []
            for candidate in summary.get("candidates") or []:
                evidence = candidate.get("evidence") or {}
                repository_id = str(candidate.get("repository_id") or "")
                repositories.append(
                    {
                        "repository_id": repository_id,
                        "repository_name": str(candidate.get("repository_name") or ""),
                        "role_suggestion": str(candidate.get("role_suggestion") or ""),
                        "confidence": str(candidate.get("confidence") or ""),
                        "total": candidate.get("total"),
                        "matched_node_path_count": len(evidence.get("matched_node_paths") or []),
                        "matched_domain_count": len(evidence.get("matched_domains") or []),
                        "violated_boundary_count": len(evidence.get("violated_boundaries") or []),
                        "citation_ids": citation_ids_by_repo.get(repository_id, []),
                        # 固定路由时带上绑定分支：它是「这个仓凭什么在这里」的**唯一**证据
                        # （自动路由的证据计数在固定路由下必然全 0，见下方 router_version）。
                        "pinned_branch": str(candidate.get("pinned_branch") or ""),
                    }
                )

            await ConvergenceSessionService().aemit_event(
                EVENT_BLUEPRINT_ROUTE_PLAN_DRAFTED,
                session,
                {
                    "repository_count": len(repositories),
                    # ⭐ `project_binding` ⇒ 固定路由（打分没跑，全 0 证据是事实而非缺陷）。
                    # 前端据此标注来源，⛔ 不要让用户把「没跑」误读成「跑出来是 0 分」。
                    "router_version": str(summary.get("router_version") or ""),
                    "repositories": repositories,
                },
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬路由主流程
            pass

    async def _resolve_repository_ids(self, session) -> list[str] | None:
        """候选范围三级解析：① 显式 include_repos → ② work_item.space 仓 → ③ None（全库）。"""
        stage_state = getattr(session, "stage_state", None) or {}
        include = None
        if isinstance(stage_state, dict):
            blueprint_state = stage_state.get("blueprint")
            if isinstance(blueprint_state, dict):
                include = blueprint_state.get("include_repos")
            if not include:
                include = stage_state.get("include_repos")
            if not include:
                decomposition = stage_state.get("decomposition")
                if isinstance(decomposition, dict):
                    include = decomposition.get("include_repos")
        if include:
            return [str(r) for r in include]
        if getattr(session, "work_item_id", None) is not None:
            try:
                project_repos = await self._project_repository_ids(session.work_item_id)
            except Exception as exc:  # noqa: BLE001 — 范围解析失败退化为全库
                logger.warning(
                    "blueprint_route_scope_resolve_failed",
                    error=str(exc),
                    category="sampling",
                    component="process_runtime",
                )
                return None
            if project_repos:
                return project_repos
        return None

    @sync_to_async
    def _project_repository_ids(self, work_item_id) -> list[str] | None:
        """取 work_item 所属 space 的仓库 id（同步 ORM 经 sync_to_async，防裸 lazy-FK）。"""
        from delivery.models import WorkItem

        work_item = WorkItem.objects.select_related("space").filter(id=work_item_id).first()
        if work_item is None or work_item.space is None:
            return None
        repo_ids = [str(r) for r in work_item.space.repositories.values_list("id", flat=True)]
        return repo_ids or None


def _role_suggestion(candidate: dict) -> str:
    """路由期初判（契约表确定规则）：high confidence 或章程正分 → direct，否则 indirect。

    保守方向是 `indirect`：不确定的仓走轻量合成而不是起容器深调研，代价更低。
    """
    if candidate["confidence"] == "high" or candidate["breakdown"]["charter_match"] > 0:
        return "direct"
    return "indirect"
