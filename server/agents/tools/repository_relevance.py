"""``analyze_repository_relevance`` agent tool —— implementation。

在 chat 模式向 LLM 暴露的「跨仓相关性识别」工具。AI 在回答跨仓需求 / 创建编码
方案前主动调用本工具，传入 query 返回排序后的 candidate 仓库列表 + score +
evidence + 是否自动选中。

**关键设计**：

- 不重新实现召回：复用 legacy 落地的 ``HybridSearchService.search()``（5 倍
  冗余多召回 → 按 repo 聚合 max score → 取 top_k）。
- evidence 三段生成：优先文件名 hint → 反向 ``CrossRepoApiCall`` 计数 →
  score 兜底。
- 每次调用都写一行 ``RepositoryRoutingTrace``（``triggered_by=chat_tool``），
  trace_id 透传 ``ToolResult.output['data']`` 让前端能引用。

公开 helper ``_analyze_relevance_core(triggered_by=..., agent_session_id=...)``
为 plan（deep_analysis_completion 路径）预留扩展点：deep_analysis 容器完成
回调时复用同一段聚合逻辑，仅切换 ``triggered_by`` / ``agent_session_id`` 两参数
即可。@tool 装饰的 ``analyze_repository_relevance`` 走 chat_tool 默认路径。
helper 返回 ``RepositoryRelevanceAnalysis``（候选 + trace_id + 四个**结果级事实**），
调用方按需取用；工具出参把这四件套原样带进 ``ToolResult.output['data']``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from pydantic import ValidationError

from agents.tools.base import ToolResult, tool
from agents.tools.schemas.repository_relevance import (
    RepositoryRelevanceCandidate,
    RepositoryRelevanceInput,
    RepositoryRelevanceOutput,
)
from services.code_intel import get_provider
from services.retrieval import HybridSearchService

logger = structlog.get_logger(__name__)


_TOOL_DESCRIPTION = (
    "分析当前 query 与空间下各仓库的相关性，返回每个仓库的 relevance_score + "
    "level（high/medium/low）+ evidence + 是否自动选中。\n"
    "\n"
    "使用时机：用户提出代码理解 / 功能是怎么实现 / 架构梳理 / 跨仓需求 / "
    "编码方案前 → 调用本工具识别相关仓库 → 用结果指导后续检索，或作为 "
    "create_coding_plan（把编排产出的方案版本投影为编码方案）的 "
    "recommended_repository_ids（自动预填）。\n"
    "尤其当问题提到 app、子应用、业务名、中文功能名，或当前仓库只是入口 / "
    "桥接 / 跳转 / SDK 包装时，必须在 search_repository_code 之前调用本工具，"
    "先确认真正实现可能在哪些仓库。\n"
    "\n"
    "底层复用 legacy GraphRAG / HybridSearch 多仓召回 + 按 repo 聚合排序；每次调用都"
    "会落 RepositoryRoutingTrace 审计（triggered_by=chat_tool）。\n"
    "\n"
    "不要用本工具替代 search_repository_code —— 后者返回具体代码 chunk；本工具返回"
    "仓库粒度的相关性排名。"
)


_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "用户的跨仓需求 query，单一概念优先。",
        },
        "space_id": {
            "type": "string",
            "description": "空间 UUID（chat_runner 自动注入）。",
        },
        "conversation_id": {
            "type": "string",
            "description": "会话 UUID（chat_runner 自动注入）。",
        },
        "top_k": {
            "type": "integer",
            "minimum": 1,
            "maximum": 20,
            "default": 5,
            "description": "返回的相关仓库数量上限。",
        },
        "threshold": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "default": 0.5,
            "description": "自动选中阈值（≥ threshold 的仓库 selected_by_ai=True）。",
        },
    },
    "required": ["query", "space_id", "conversation_id"],
}


@dataclass
class RepositoryRelevanceAnalysis:
    """一次相关性分析的完整结果（候选 + **结果级事实**）。

    结果级四件套（``router_version`` / ``degraded`` / ``degrade_reason`` /
    ``block_order``）与 ``RepositoryRoutingTrace`` 落库的是同一组值。它们必须随
    candidates 一起离开本 helper：只回 ``(candidates, trace_id)`` 的话，工具输出里就
    没有这四个键，前端在 SSE ``part_completed`` 解析到的恒是 ``undefined``——降级横幅
    与分组分区在对话进行中完全不出现（BL-02）。
    """

    candidates: list[RepositoryRelevanceCandidate]
    trace_id: str
    router_version: str = "legacy_hybrid"
    degraded: bool = False
    degrade_reason: str = ""
    block_order: list[str] = field(default_factory=list)


def _truncate_by_group_quota(
    candidates: list[RepositoryRelevanceCandidate], top_k: int
) -> list[RepositoryRelevanceCandidate]:
    """把候选截到 ``top_k``，但**每个非空组至少保留 1 条**，其余名额按原顺序补齐。

    输入已按全局 ``score_ranked`` 降序（router 侧 ``_apply_presentation`` 的产物），
    输出保持该相对顺序不变——只做取舍，不重排。

    为什么不能直接 ``[:top_k]``：全局组分数整体占优时前 ``top_k`` 可能一条
    ``in_project`` 都不剩，而 ``block_order`` 仍报长度 2，前端启用分组后该分区因
    ``total == 0`` 被过滤，用户看到的是「分组开着但只有一个区」。
    """
    if top_k <= 0 or len(candidates) <= top_k:
        return list(candidates[: max(top_k, 0)])
    kept: list[RepositoryRelevanceCandidate] = []
    seen_groups: set[str] = set()
    # 第一轮：每个组的最高分候选各占一个名额（输入已排序，首次出现即该组最高分）。
    for c in candidates:
        group = c.group or "global"
        if group not in seen_groups and len(kept) < top_k:
            seen_groups.add(group)
            kept.append(c)
    # 第二轮：剩余名额按全局顺序补齐。
    kept_ids = {id(c) for c in kept}
    for c in candidates:
        if len(kept) >= top_k:
            break
        if id(c) not in kept_ids:
            kept.append(c)
            kept_ids.add(id(c))
    # 恢复输入的全局降序（第一轮的配额挑选会打乱相对顺序）。
    order = {id(c): idx for idx, c in enumerate(candidates)}
    kept.sort(key=lambda c: order[id(c)])
    return kept


async def _apply_charter_signal(
    query: str, candidates: list[RepositoryRelevanceCandidate]
) -> list[RepositoryRelevanceCandidate]:
    """给 v2 候选叠加章程意图面：改分 + 补证据 + 补入章程命中的仓（CHARTER-01）。

    能力树只回答「这个仓现在有什么」，章程回答「这个仓该放什么、不放什么」——对话链
    此前只有前者。触及章程禁区的候选强制取消自动选中：让「章程说别放这」真的能拦住
    AI 预填，而不只是加一行说明文字。

    `breakdown` 与 `score_ranked` 同步调整：前者要维持「各项之和 == score」的前端
    分数分解恒等式，后者是前端实际排序依据（`score_ranked ?? score`），只改 `score`
    的话章程完全影响不到用户看到的顺序。无章程的仓（章程分为 0）逐字段零扰动。

    best-effort：任何异常原样返回入参。
    """
    from services.charter_route_signal import aapply_charter_signal, resolve_charter_weight

    try:
        items = await aapply_charter_signal(
            query=query,
            candidates=[(c.repository_id, c.repository_name, c.score) for c in candidates],
        )
    except Exception as exc:  # noqa: BLE001 — 章程失效不影响能力树路由结果
        logger.warning("repository_relevance_charter_signal_failed", error=str(exc))
        return candidates

    weight = resolve_charter_weight()
    by_id = {c.repository_id: c for c in candidates}
    merged: list[RepositoryRelevanceCandidate] = []
    for item in items:
        base = by_id.get(item.repository_id)
        if base is None:
            merged.append(
                RepositoryRelevanceCandidate(
                    repository_id=item.repository_id,
                    repository_name=item.repository_name or item.repository_id,
                    score=item.blended_score,
                    level="low",
                    evidence=item.evidence,
                    # 补入候选恒不自动选中：它没有任何代码证据支撑，只有意图面声明
                    selected_by_ai=False,
                    selected_by_user_final=False,
                    breakdown={"charter_match": item.blended_score},
                )
            )
            continue
        base.score = item.blended_score
        if base.score_ranked is not None:
            base.score_ranked = max(0.0, min(1.0, base.score_ranked + item.charter_score * weight))
        if base.breakdown and item.charter_score:
            # 差值而非直接写 weight*charter_score：blended 被 clamp 到 [0,1] 时，
            # 只有取差值才能维持「各项之和 == score」这条前端分数分解的恒等式。
            base.breakdown = {
                **base.breakdown,
                "charter_match": item.blended_score - sum(base.breakdown.values()),
            }
        if item.evidence:
            base.evidence = f"{base.evidence}；{item.evidence}" if base.evidence else item.evidence
        if item.violated_boundaries:
            base.selected_by_ai = False
            base.selected_by_user_final = False
        merged.append(base)

    # `_truncate_by_group_quota` 的前提是入参已按前端实际排序键降序，而前端用的是
    # `score_ranked ?? score` —— 两个键分别混了章程分，顺序不一定一致，必须重排。
    merged.sort(
        key=lambda c: (
            -(c.score_ranked if c.score_ranked is not None else c.score),
            c.repository_id,
        )
    )
    return merged


async def _apply_module_summary_signal(
    query: str, candidates: list[RepositoryRelevanceCandidate]
) -> list[RepositoryRelevanceCandidate]:
    """给候选追加模块摘要 evidence（MOD-04 / D-15）；默认不改分数。

    best-effort：任何异常原样返回入参。
    """
    from services.module_summary_signal import aapply_module_summary_signal

    try:
        items = await aapply_module_summary_signal(
            query=query,
            candidates=[(c.repository_id, c.repository_name, c.score) for c in candidates],
        )
    except Exception as exc:  # noqa: BLE001 — 摘要失效不影响章程/能力树结果
        try:
            from common.logging import redact_secrets_in_text

            logger.warning(
                "repository_relevance_module_summary_signal_failed",
                error=redact_secrets_in_text(str(exc)),
                category="sampling",
                component="agents",
            )
        except Exception:  # noqa: BLE001 — 观测失败不反噬
            pass
        return candidates

    by_id = {c.repository_id: c for c in candidates}
    for item in items:
        base = by_id.get(item.repository_id)
        if base is None or not item.evidence:
            continue
        base.evidence = f"{base.evidence}；{item.evidence}" if base.evidence else item.evidence
    return candidates


def _score_to_level(score: float) -> Literal["high", "medium", "low"]:
    """三档阈值映射：0.7 / 0.4。"""
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


async def _build_evidence(
    *,
    repository_id: str,
    hits: list[dict[str, Any]],
    top_score: float,
) -> str:
    """evidence 三段 fallback：文件名 → 反向 CrossRepoApiCall 计数 → score 兜底。"""
    parts: list[str] = []

    files: list[str] = []
    seen: set[str] = set()
    for h in hits:
        payload = h.get("payload") or {}
        file_path = payload.get("file_path") or ""
        if file_path and file_path not in seen:
            seen.add(file_path)
            files.append(file_path)
        if len(files) >= 3:
            break

    if files:
        parts.append(f"命中 {len(files)} 个相关文件：{' / '.join(files[:3])}")

    try:
        from codegraph.models import CrossRepoApiCall

        cross_count = await CrossRepoApiCall.objects.filter(
            endpoint__repository_id=repository_id
        ).acount()
    except Exception as exc:  # noqa: BLE001 — 反向计数失败不阻塞 evidence
        logger.warning(
            "cross_repo_api_call_count_failed",
            repository_id=repository_id,
            error=str(exc),
        )
        cross_count = 0

    if cross_count > 0:
        parts.append(f"反向追踪 {cross_count} 个 API 调用")

    if not parts:
        return f"语义相关度 score={top_score:.2f}"

    return "；".join(parts)


async def _analyze_relevance_core(
    *,
    query: str,
    space_id: str,
    conversation_id: str,
    top_k: int = 5,
    threshold: float = 0.5,
    triggered_by: str | None = None,
    agent_session_id: str | None = None,
) -> RepositoryRelevanceAnalysis:
    """公开 helper：跑相关性聚合 + 写一行 RepositoryRoutingTrace。

    复用方：

    - chat_tool 路径（``analyze_repository_relevance`` @tool 装饰函数本身）：
      ``triggered_by=CHAT_TOOL`` / ``agent_session_id=None``。
    - deep_analysis_completion 路径（plan ``_handle_completed`` 回调）：
      ``triggered_by=DEEP_ANALYSIS_COMPLETION`` /
      ``agent_session_id=main_session.id``。

    Returns:
        ``RepositoryRelevanceAnalysis`` —— candidates 按 score 倒序，``trace_id`` 是
        新写入的 ``RepositoryRoutingTrace`` 主键 UUID 字符串，另附四个**结果级事实**
        （与该 trace 落库的同一组值）供实时链路直接渲染。

    Raises:
        ValueError: space / conversation 不存在或空间下无 indexed repo。
    """
    # lazy import 仅针对 Django ORM 模型避免 app registry race；服务类已在
    # 模块顶层 import（测试 monkeypatch 需要从本模块取 HybridSearchService）。
    from chat.models import Conversation, RepositoryRoutingTrace, derive_routing_degraded
    from projects.models import Space
    from repositories.models import Repository

    triggered_by = triggered_by or RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL

    try:
        project = await Space.objects.aget(id=space_id)
    except Space.DoesNotExist as exc:
        raise ValueError(f"Space not found: {space_id}") from exc

    try:
        await Conversation.objects.aget(id=conversation_id)
    except Conversation.DoesNotExist as exc:
        raise ValueError(f"Conversation not found: {conversation_id}") from exc

    repos: list[Repository] = [
        repo
        async for repo in Repository.objects.filter(
            spaces=project,
            is_deleted=False,
            index_status="indexed",
        )
    ]
    if not repos:
        raise ValueError("No indexed repositories found in space")

    repo_ids = [str(r.id) for r in repos]
    repo_by_id = {str(r.id): r for r in repos}

    # PageIndex v2 树推理路由优先：节点级粗筛 + LLM 推理，evidence 为
    # "命中能力节点路径 + 推理理由"，置信度直接映射 level/selected_by_ai。
    # v2 不可用（无树索引/LLM 失败回落 v1_fallback）时走 legacy 聚合。
    router_version = "legacy_hybrid"
    v2_candidates: list[RepositoryRelevanceCandidate] | None = None
    # 结果级降级/分组事实（107-08）：在 try 之外初始化为列默认值，legacy 路径与 v2
    # 任意失败回落都落这两个默认值；v2 成功时才被 router 结果覆盖。
    v2_degrade_reason = ""
    v2_block_order: list[str] = []
    try:
        from codegraph.services.repo_group_scope import aresolve_grouping_repo_ids
        from codegraph.services.repo_router_v2 import RepoRouterV2

        # D-1：空间关联仓从「硬过滤」改为「分组依据」——继续当硬过滤传的话候选集从一
        # 开始就只有空间内仓，global 分区恒空、ROUTE-01/02 上线即无效果（Pitfall 2）。
        # T-107-01 前提：沿用 mcp_tools 的 RouteRepositoriesView 与
        # repositories/route_views.py 两个已上线全库入口的既有判断（二者只有
        # IsAuthenticated、无 per-user/per-space 过滤）→ 本改动不绕过任何现存权限检查。
        # 注意透出面不止仓名：下面组装的 evidence 还含跨组仓的能力树节点路径、
        # sub_project 与 LLM reasoning，对空间成员是一个新的元数据面。要收窄的话，
        # group == global 是现成判据，改动面只在 evidence 映射那一处。
        grouping_ids = await aresolve_grouping_repo_ids(space_id=space_id)
        v2_result = await RepoRouterV2.route(
            query,
            top_k=top_k,
            repository_ids=None,
            grouping_repository_ids=(None if grouping_ids is None else sorted(grouping_ids)),
        )
        if v2_result.router_version in ("v2", "v2_stage0_only") and v2_result.candidates:
            router_version = v2_result.router_version
            v2_degrade_reason = v2_result.degrade_reason
            v2_block_order = list(v2_result.block_order or [])
            v2_candidates = []
            for c in v2_result.candidates:
                # 防御性跳过：repo_id 为空的候选无法映射（正常路径不会出现）。
                if not c.repo_id:
                    continue
                repo = repo_by_id.get(c.repo_id)
                # 跨组候选必然不在 repo_by_id 里（后者只装空间内仓）。此处若沿用旧写法
                # 「查不到就丢弃」，global 分区会在映射阶段被清空——与硬过滤同一个后果
                # （Pitfall 2 的第二个入口）。故用候选自带的仓名兜底。
                repo_name = repo.name if repo is not None else (c.repo_name or c.repo_id)
                evidence_parts: list[str] = []
                if c.matched_node_paths:
                    evidence_parts.append("命中能力节点: " + " / ".join(c.matched_node_paths[:3]))
                if c.reasoning:
                    evidence_parts.append(c.reasoning)
                if c.sub_project:
                    evidence_parts.append(f"子应用: {c.sub_project}")
                score = max(0.0, min(1.0, float(c.score)))
                selected = c.confidence == "high" or (
                    c.confidence == "medium" and score >= threshold
                )
                v2_candidates.append(
                    RepositoryRelevanceCandidate(
                        repository_id=c.repo_id,
                        repository_name=repo_name,
                        score=score,
                        level=c.confidence,
                        evidence="；".join(evidence_parts) or f"语义相关度 score={score:.2f}",
                        selected_by_ai=selected,
                        selected_by_user_final=selected,
                        sub_project=c.sub_project,
                        sub_project_paths=c.sub_project_paths,
                        # ROUTE-07：v2 候选 breakdown 透传（105-03 后必有该字段），
                        # 经 trace.candidates JSON 一路可达前端分数分解展开区。
                        breakdown=dict(c.breakdown or {}),
                        # ROUTE-01/02：分组事实同路透传（107-03 落的 router 侧字段）。
                        group=c.group,
                        trust=c.trust,
                        score_ranked=c.score_ranked,
                    )
                )
            if not v2_candidates:
                v2_candidates = None
    except Exception as exc:  # noqa: BLE001 — v2 任意失败都静默回落 legacy
        logger.warning("repository_relevance_v2_failed", error=str(exc))
        v2_candidates = None

    if v2_candidates is not None:
        # 返回上限仍是 top_k（它是 LLM 可见的公开参数「返回的相关仓库数量上限」，
        # 悄悄改成 2*top_k 会单方面变更工具契约与 total_candidates 语义），但截断改为
        # **按组配额**而非全局前 N：router 按组各取 top_k 后并集并按全局 score_ranked
        # 排序，全局组分数整体占优时，简单的 `[:top_k]` 会把 in_project 组整组截空，
        # 而落库的 block_order 来自 router 结果、仍报长度 2 → 前端启用分组却发现该组
        # total == 0 被过滤掉，ROUTE-01「组内各展示 Top-3」在 top_k 较小时无法保证。
        # 章程叠加必须在按组配额截断**之前**：截断后再改分会让被截掉的、章程明确
        # 声明拥有的仓永远没机会进候选，而那正是章程要解决的问题。
        v2_candidates = await _apply_charter_signal(query, v2_candidates)
        # MOD-04：模块摘要 evidence 旁路（不改分；失败原样）
        v2_candidates = await _apply_module_summary_signal(query, v2_candidates)
        candidates = _truncate_by_group_quota(v2_candidates, top_k)
        trace = await RepositoryRoutingTrace.objects.acreate(
            agent_session_id=agent_session_id,
            conversation_id=conversation_id,
            query=query,
            candidates=[c.model_dump() for c in candidates],
            threshold=threshold,
            triggered_by=triggered_by,
            router_version=router_version,
            # 写入侧接线（RELY-03 / ROUTE-01）：这两个赋值缺失时模型与 payload 测试
            # 依旧全绿，而生产两列恒为列默认值 —— degraded 虽仍由 router_version 派生
            # 为 True，但降级原因行永不出现、block_order 恒空使前端永远走平铺，
            # 分组呈现上线即无效果。值只来自 router 结果，此处不做任何再分类。
            degrade_reason=v2_degrade_reason,
            block_order=v2_block_order,
        )
        logger.info(
            "analyze_repository_relevance_trace_written",
            trace_id=str(trace.id),
            candidate_count=len(candidates),
            triggered_by=triggered_by,
            router_version=router_version,
            degrade_reason=v2_degrade_reason,
            block_order=v2_block_order,
            agent_session_id=agent_session_id,
        )
        return RepositoryRelevanceAnalysis(
            candidates=candidates,
            trace_id=str(trace.id),
            router_version=router_version,
            # 与 detail / override 两处 payload 同一个派生点，绝不在工具侧另写一遍
            # 版本字面判定——两条链路给出不同 degraded 会让「刷新前后降级状态不一致」。
            degraded=derive_routing_degraded(router_version),
            degrade_reason=v2_degrade_reason,
            block_order=list(v2_block_order),
        )

    # ---- legacy 路径：HybridSearchService 多召回（top_k * 5 冗余）+ 按 repo 聚合 ----
    service = HybridSearchService(get_provider())
    try:
        result = await service.search(query, repository_ids=repo_ids, top_k=top_k * 5)
    except Exception as exc:  # noqa: BLE001 — 召回失败统一外抛 ValueError
        raise ValueError(f"HybridSearchService failed: {exc}") from exc

    # 收集 L3 命中并按 repository_id 分桶
    buckets: dict[str, list[dict[str, Any]]] = {}
    for layer in result.layers:
        if getattr(layer, "layer", None) != "L3":
            continue
        if getattr(layer, "status", None) != "ok":
            continue
        for item in layer.items:
            rid = (
                item.get("repository_id") or (item.get("payload") or {}).get("repository_id") or ""
            )
            rid = str(rid)
            if rid and rid in repo_by_id:
                buckets.setdefault(rid, []).append(item)

    # 每仓取 max(score) 作为 candidate score；hits 按 score 倒序保留前 5 给 evidence
    candidates: list[RepositoryRelevanceCandidate] = []
    for rid, hits in buckets.items():
        hits_sorted = sorted(hits, key=lambda x: float(x.get("score", 0.0)), reverse=True)
        top_score = float(hits_sorted[0].get("score", 0.0)) if hits_sorted else 0.0
        # score 截断到 [0, 1] 适配 Pydantic 校验（HybridSearch 偶尔 > 1.0）
        score = max(0.0, min(1.0, top_score))
        evidence = await _build_evidence(
            repository_id=rid,
            hits=hits_sorted[:5],
            top_score=score,
        )
        selected = score >= threshold
        repo = repo_by_id[rid]
        candidates.append(
            RepositoryRelevanceCandidate(
                repository_id=rid,
                repository_name=repo.name,
                score=score,
                level=_score_to_level(score),
                evidence=evidence,
                selected_by_ai=selected,
                selected_by_user_final=selected,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    candidates = candidates[:top_k]

    # legacy 聚合路径（router_version == "legacy_hybrid"）刻意不传新增两列：这条链没有
    # 分组事实也没有降级分类，留列默认值（"" / []）即与历史行等价，前端渲染不变。
    trace = await RepositoryRoutingTrace.objects.acreate(
        agent_session_id=agent_session_id,
        conversation_id=conversation_id,
        query=query,
        candidates=[c.model_dump() for c in candidates],
        threshold=threshold,
        triggered_by=triggered_by,
        router_version=router_version,
    )

    logger.info(
        "analyze_repository_relevance_trace_written",
        trace_id=str(trace.id),
        candidate_count=len(candidates),
        triggered_by=triggered_by,
        router_version=router_version,
        agent_session_id=agent_session_id,
    )

    return RepositoryRelevanceAnalysis(
        candidates=candidates,
        trace_id=str(trace.id),
        router_version=router_version,
        degraded=derive_routing_degraded(router_version),
    )


@tool(
    name="analyze_repository_relevance",
    description=_TOOL_DESCRIPTION,
    category="RETRIEVAL",
    parameters=_TOOL_PARAMETERS,
)
async def analyze_repository_relevance(
    query: str,
    space_id: str,
    conversation_id: str,
    top_k: int = 5,
    threshold: float = 0.5,
) -> ToolResult:
    """分析当前 query 与空间下各仓库的相关性。"""
    logger.info(
        "analyze_repository_relevance_called",
        query=query[:120],
        space_id=space_id,
        conversation_id=conversation_id,
        top_k=top_k,
        threshold=threshold,
    )

    try:
        RepositoryRelevanceInput(
            query=query,
            space_id=space_id,
            conversation_id=conversation_id,
            top_k=top_k,
            threshold=threshold,
        )
    except ValidationError as exc:
        logger.warning(
            "analyze_repository_relevance_invalid_input",
            error=str(exc),
        )
        return ToolResult(success=False, error=str(exc))

    try:
        analysis = await _analyze_relevance_core(
            query=query,
            space_id=space_id,
            conversation_id=conversation_id,
            top_k=top_k,
            threshold=threshold,
            triggered_by=None,  # 走默认 CHAT_TOOL
            agent_session_id=None,
        )
    except ValueError as exc:
        logger.warning(
            "analyze_repository_relevance_failed",
            error=str(exc),
        )
        return ToolResult(success=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001 — 永不冒泡到 agent runtime
        logger.exception("analyze_repository_relevance_unexpected", error=str(exc))
        return ToolResult(success=False, error=f"Unexpected error: {exc}")

    # 结果级四件套随 data 一并出参：前端 SSE part_completed 解析的就是这个
    # model_dump()，少一个键就少一个实时可见的能力（BL-02）。
    output_model = RepositoryRelevanceOutput(
        candidates=analysis.candidates,
        threshold=threshold,
        total_candidates=len(analysis.candidates),
        trace_id=analysis.trace_id,
        router_version=analysis.router_version,
        degraded=analysis.degraded,
        degrade_reason=analysis.degrade_reason,
        block_order=analysis.block_order,
    )

    return ToolResult(
        success=True,
        output={
            "data": output_model.model_dump(),
            "metadata": {
                "searched_repositories": len(analysis.candidates),
                "trace_id": analysis.trace_id,
            },
        },
    )


__all__ = [
    "RepositoryRelevanceAnalysis",
    "_analyze_relevance_core",
    "analyze_repository_relevance",
]
