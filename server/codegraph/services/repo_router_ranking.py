"""仓库路由的分组呈现与有界重排纯函数（Phase 107-01，ROUTE-01/02 + RELY-05）。

本模块是 Phase 106 定版打分口径的**外层包装**——`repo_router_scoring` 的
`score` / `breakdown` 一行不改，也绝不被本模块覆盖：

- 组别与 trust 只进候选的独立字段，**绝不进分数**（107-CONTEXT / ROUTING-RANKING
  §5.1）。给本项目仓加分数偏移会让两组分数不可比，「跨组分更低」变成自我实现预言；
- 凸组合的结果是旁路取值（调用方写进新字段，如 `score_ranked`），`α·S_llm` 不是
  任何信号的贡献，塞进 `breakdown` 会打断 `Σbreakdown == score` 恒等式（INV-R3）。

纪律（与 `repo_router_config` / `repo_router_eval` 同款）：零 I/O、零配置读取、
零 Django 依赖——所有阈值由 router 层读 settings 后以参数注入。这样这些判定才能
进 golden 门禁与单测，并满足幂等断言（同一输入恒等输出）。
"""

from __future__ import annotations

import math
from typing import Any

# 分组与信任标注取值（受控闭集；前端按枚举映射文案，不渲染后端自由文本）。
GROUP_IN_PROJECT = "in_project"
GROUP_GLOBAL = "global"
TRUST_TRUSTED = "trusted"
TRUST_NEEDS_CONFIRMATION = "needs_confirmation"

# 跨组候选的标注文案（后端留痕用；前端渲染走自己的常量映射，T-107-06）。
CROSS_GROUP_NOTE = "未关联当前平台，可能涉及跨组协作"

# 降级原因的 6 值受控闭集。基数受控才能当指标维度用；非降级路径返回空串。
DEGRADE_REASONS = frozenset(
    {
        "timeout",
        "upstream_error",
        "provider_missing",
        "unparsable",
        "no_node_index",
        "unknown",
    }
)

# 内部 skipped_reason → 粗粒度枚举（107-RESEARCH §6 映射表）。
_SKIPPED_REASON_MAP: dict[str, str] = {
    "provider_missing": "provider_missing",
    "no_model_configured": "provider_missing",
    "unparsable_llm_output": "unparsable",
    "no_valid_candidates_in_llm_output": "unparsable",
    "v1_fallback": "no_node_index",
    # 数据缺失与主动纯检索都不是「上游不可用」，不该给用户看降级原因行。
    "no_stage0_candidates": "",
    "use_llm_false": "",
}

# 异常类型名 → 枚举的子串匹配表（只吃类型名，不吃异常实例/消息）。
_TIMEOUT_TOKENS = ("Timeout",)
_UPSTREAM_TOKENS = ("Connect", "APIStatus", "APIError", "HTTPStatus", "BadRequest")

# 参数 clamp 的兜底默认（与 settings 默认一致；非有限值时回退到这里）。
_DEFAULT_GROUP_DELTA = 0.15
_DEFAULT_STAGE1_ALPHA = 0.35
_DEFAULT_RANK_BUDGET_K = 3


def annotate_groups(
    repo_ids: list[str],
    *,
    project_repo_ids: frozenset[str] | None,
) -> dict[str, tuple[str, str]]:
    """归属标注：`repo_id → (group, trust)`。

    `project_repo_ids is None` = 调用方无项目上下文（MCP / REST 全局入口）→ 全部
    记 `global` 且不抛（107-CONTEXT 明确要求这条降级路径不得报错）。

    返回值**只含组别与信任字符串**：这是「组别绝不进分数」的机制守护点——本函数
    结构上无法返回任何分数偏移。
    """
    if project_repo_ids is None:
        return {rid: (GROUP_GLOBAL, TRUST_NEEDS_CONFIRMATION) for rid in repo_ids}
    return {
        rid: (
            (GROUP_IN_PROJECT, TRUST_TRUSTED)
            if rid in project_repo_ids
            else (GROUP_GLOBAL, TRUST_NEEDS_CONFIRMATION)
        )
        for rid in repo_ids
    }


def decide_block_order(
    in_project_top: float | None,
    global_top: float | None,
    *,
    delta: float,
    has_project_context: bool,
) -> list[str]:
    """block ranking 置顶决策（delta 迟滞比较，纯函数可幂等断言）。

    - 无项目上下文 → `[GROUP_GLOBAL]`（长度 1）；
    - 有项目上下文 → **恒返回长度 2**，即使某组或两组为空。前端据 `len == 2`
      判定是否启用分组呈现（UI-SPEC covered 11 的后端契约），这也是区分
      「无项目上下文」与「有上下文但本项目组恰好为空」两种 all-global 场景的
      唯一依据；
    - 两组都有值时用 `>= delta` 比较：迟滞是必须的，用 `> 0` 会让 0.001 级分数
      波动反复翻转置顶顺序，破坏幂等与体验（ROUTING-RANKING §5.2）。
    """
    if not has_project_context:
        return [GROUP_GLOBAL]
    if in_project_top is None and global_top is None:
        # 两组皆空：无任何证据支持置顶全局组，取确定的默认顺序（必须恒定）。
        return [GROUP_IN_PROJECT, GROUP_GLOBAL]
    if in_project_top is None:
        return [GROUP_GLOBAL, GROUP_IN_PROJECT]
    if global_top is None:
        return [GROUP_IN_PROJECT, GROUP_GLOBAL]
    if (global_top - in_project_top) >= delta:
        return [GROUP_GLOBAL, GROUP_IN_PROJECT]
    return [GROUP_IN_PROJECT, GROUP_GLOBAL]


def clamp_llm_permutation(
    llm_order: list[str], stage0_order: list[str], *, k: int
) -> tuple[list[str], int]:
    """把 LLM 排列裁剪回 rank-swap 预算内，返回 `(裁剪后排列, 违规数)`。

    base rank 取「**被 LLM 返回的那个子集**」内的 Stage 0 相对位次，而不是全量
    `stage0_order` 的绝对下标。原因：`repo_router_v2` 的最终候选只由 LLM 返回的
    `parsed` 构造——未被返回的 Stage 0 仓被整体丢弃——而喂给 LLM 的窗口默认有 8
    个候选。若拿裁剪后排列的下标（域 0..len(rids)-1）去减全量窗口的下标（域 0..7），
    LLM 只返回窗口末尾几位时位移恒大于预算，修复循环无法收敛并整体回退到全量窗口，
    结果是最常见情形下 LLM 重排被完全丢弃、而违规数稳定报非零「看起来像裁剪在工作」。
    两侧必须同集合、同长度、同下标域。

    后置条件（可断言、可穷举）：返回排列中每个 rid 满足
    `|order.index(rid) - base_order.index(rid)| <= k`。算法细节可换，
    **后置条件、base 的子集相对语义、违规数留痕三者不可换**
    （ROUTING-RANKING §1.3b 要的是「损害有硬上界且可测」）。

    违规数 = 裁剪前 LLM 请求的位移超出预算的元素个数（供留痕；不是修复轮数）。
    """
    budget = max(0, int(k))
    allowed = set(stage0_order)
    # 白名单过滤 + 去重（防御；调用方也会过滤）——LLM 编造的 repo_id 不进子集。
    rids: list[str] = []
    seen: set[str] = set()
    for rid in llm_order:
        if rid in allowed and rid not in seen:
            seen.add(rid)
            rids.append(rid)
    if not rids:
        return [], 0

    base_order = [rid for rid in stage0_order if rid in seen]
    base = {rid: idx for idx, rid in enumerate(base_order)}

    violations = sum(1 for idx, rid in enumerate(rids) if abs(idx - base[rid]) > budget)

    desired = {
        rid: min(max(idx, base[rid] - budget), base[rid] + budget) for idx, rid in enumerate(rids)
    }
    order = sorted(rids, key=lambda rid: (desired[rid], base[rid]))

    # 修复循环：把最早的越界元素移回其 base 位置（其余顺移），至多 len(order) 轮。
    for _ in range(len(order)):
        offender = next(
            (rid for idx, rid in enumerate(order) if abs(idx - base[rid]) > budget),
            None,
        )
        if offender is None:
            return order, violations
        order.remove(offender)
        order.insert(base[offender], offender)

    if all(abs(idx - base[rid]) <= budget for idx, rid in enumerate(order)):
        return order, violations
    # 兜底回退到 base_order（**不是全量 stage0_order**）：元素集合必须与输入子集
    # 一致，否则会凭空引入没有对应候选的 repo_id。
    return list(base_order), violations


def blend_ranked_scores(
    stage0_scores: dict[str, float], llm_order: list[str], *, alpha: float
) -> dict[str, float]:
    """凸组合 `S_ranked = (1-α)·S_final + α·S_llm`，`S_llm = 1 - idx/(N-1)`。

    - `N <= 1`（单候选无重排空间）或 `alpha <= 0`（Stage 1 降级）→ 恒等返回
      `S_final` 的副本，兼作除零短路；
    - `llm_order` 中不在 `stage0_scores` 的 id 被跳过（防御）。

    返回值是**旁路取值**：调用方必须写进新字段，绝不覆盖 `score`
    （107-CONTEXT D-3；覆盖会打断两条既有 `Σbreakdown == score` 断言与前端容差校验）。
    """
    n = len(llm_order)
    out: dict[str, float] = dict(stage0_scores)
    if n <= 1 or alpha <= 0.0:
        return out
    for idx, rid in enumerate(llm_order):
        if rid not in stage0_scores:
            continue
        s_llm = 1.0 - idx / (n - 1)
        out[rid] = (1.0 - alpha) * stage0_scores[rid] + alpha * s_llm
    return out


def classify_degrade_reason(skipped_reason: str, *, exc_type_name: str | None = None) -> str:
    """把内部降级原因映射为 6 值受控枚举；非降级路径返回空串。

    只接受 `skipped_reason` 与**异常类型名**两个字符串——结构上无法接收异常实例
    或异常消息（T-107-02 的脱敏边界：原文脱敏由调用侧用 `redact_secrets_in_text`
    完成后只进事件 payload / 系统日志，绝不流向用户可见字段）。

    返回值恒 ∈ `DEGRADE_REASONS | {""}`。
    """
    mapped = _SKIPPED_REASON_MAP.get(skipped_reason)
    if mapped is not None:
        return mapped
    if exc_type_name:
        if any(token in exc_type_name for token in _TIMEOUT_TOKENS):
            return "timeout"
        if any(token in exc_type_name for token in _UPSTREAM_TOKENS):
            return "upstream_error"
    return "unknown"


def _clamp_unit(value: Any, fallback: float) -> float:
    """clamp 到 [0,1]；非数值/非有限值回退 fallback。绝不抛。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(num):
        return fallback
    return min(max(num, 0.0), 1.0)


def clamp_ranking_params(*, delta: float, alpha: float, k: int) -> tuple[float, float, int]:
    """参数 fail-safe：clamp 到 `delta, alpha ∈ [0,1]`、`k >= 0`，**绝不抛**。

    运维把 delta/α 设成极端值（或 env 里写了非数值）不得让排序退化或让路由抛异常
    ——照 `repo_router_config._CONSTANT_RULES` 的同款 fail-safe 纪律（T-107-05）。
    """
    safe_delta = _clamp_unit(delta, _DEFAULT_GROUP_DELTA)
    safe_alpha = _clamp_unit(alpha, _DEFAULT_STAGE1_ALPHA)
    try:
        safe_k = int(k)
    except (TypeError, ValueError):
        safe_k = _DEFAULT_RANK_BUDGET_K
    return safe_delta, safe_alpha, max(0, safe_k)


__all__ = [
    "CROSS_GROUP_NOTE",
    "DEGRADE_REASONS",
    "GROUP_GLOBAL",
    "GROUP_IN_PROJECT",
    "TRUST_NEEDS_CONFIRMATION",
    "TRUST_TRUSTED",
    "annotate_groups",
    "blend_ranked_scores",
    "clamp_llm_permutation",
    "clamp_ranking_params",
    "classify_degrade_reason",
    "decide_block_order",
]
