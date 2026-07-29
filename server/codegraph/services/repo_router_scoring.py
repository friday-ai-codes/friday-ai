"""仓库路由 v2 纯函数打分核心（Phase 105 三信号 + Phase 106 六信号扩展）。

router（RepoRouterV2）/ 离线 replay / golden harness 三方共用同一份打分
纯函数（per CONTEXT ROUTE-09）——这是「快照回放零网络同结果」的结构保证。

分层契约（Phase 106，per 106-RESEARCH Architectural Responsibility Map）：
- **resolver（I/O，router 层 106-06）**：dense 余弦查询、FileIndex last_commit
  聚合、facet T1/T2 匹配、N_r/N̄ 快照读取——全部 I/O 收在 Stage 0 内，
  解析结果组装成 ``repo_meta`` 以数据形式注入本模块（并进快照供离线回放）。
- **scorer（本模块，纯函数）**：只消费数值。零 I/O、零 ORM、零 Django import、
  零网络——仅 stdlib（math/json/dataclasses/datetime/typing）。

模块契约：
- 输入是 dict（Qdrant node_hits 形状 + repo_meta 元数据），输出是 dataclass；
  同输入必得同输出（稳定 tie-break + math.fsum 消除浮点顺序依赖）。
- 时间锚点 ``now`` 必须参数注入——本模块禁止读取系统当前时间（回放/golden
  确定性）。
- θ 阈值（REPO_ROUTER_CONF_THETA_ABS/MARGIN/MED）与权重/常数由调用方读
  settings 后以参数注入，本模块不读任何配置。
- 本模块不加日志——观测埋点在调用方 router 层。

repo_meta 键契约（权威定义，106-03 resolver 输出 / 106-06 router 组装 /
106-07 replay 从快照还原 / 106-08 golden fixture 同形）::

    repo_meta: dict[str, dict[str, Any]]   # key = repository_id
    {
        "<rid>": {
            "n_r": int | None,             # 该仓能力树节点总数（离线快照）
            "last_commit_at": str | None,  # ISO 8601；naive 视为 UTC
            "dense_cos_max": float | None, # 该仓 dense 余弦 max（O-3 口径）
            "facet_scores": {              # resolver 已做 T1/T2 匹配与多值 max
                "domain" | "stack" | "team": {
                    "score": float | None,  # ∈ [0,1]；None = 信号不可用
                    "layer": "t1" | "t2" | None,  # 来源层（trace 用，scorer 不读）
                },
            },
            "criticality_value": str | None,  # 关键程度 facet 原值（锚点映射）
        },
    }

公式与常数权威来源：.planning/research/ROUTING-RANKING.md（§1.3a margin 规则、
§2.3 聚合三步、§3.4 缺失信号重归一化、§3.5 活跃度指数衰减、§3.6 关键程度
先验、§4 权重初值表与 INV-R1~R4、§6.2 tie-break）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

# 本模块自定义 Confidence，不 import repo_router_v2（防循环依赖）。
Confidence = Literal["high", "medium", "low"]

# breakdown 字典 key——前端信号名映射表与之对齐，禁止改名。
SIGNAL_TEXT = "text"
SIGNAL_BREADTH = "breadth"
SIGNAL_ACTIVITY = "activity"
# Phase 106 新增三信号 key（前端映射表 106-05 与之对齐，禁止改名）。
SIGNAL_DOMAIN = "domain"
SIGNAL_STACK = "stack"
SIGNAL_TEAM = "team"

# Phase 105 临时权重（Σ=1.0）：legacy 路径（repo_meta=None）的默认权重，
# 已有调用方（router/replay/golden）在 106-06/07/08 接线前继续走此路径。
PHASE105_WEIGHTS: dict[str, float] = {
    SIGNAL_TEXT: 0.70,
    SIGNAL_BREADTH: 0.20,
    SIGNAL_ACTIVITY: 0.10,
}

# 活跃度枚举映射（ROUTING-RANKING §4）；无 last_commit_at 时的回退来源。
ACTIVITY_ENUM_MAP: dict[str, float] = {
    "活跃开发": 0.9,
    "维护中": 0.6,
    "低频": 0.3,
    "疑似废弃": 0.1,
}

# 废弃惩罚：从乘性 `score *= 0.5` 改为对活跃度项封顶（per CONTEXT ROUTE-07），
# 惩罚完全落在 activity 一项内，贡献仍可单独拆解展示。
DEPRECATED_ACTIVITY_CAP = 0.10

# 关键程度缺失时的中性档：不奖不罚，与「一般」锚点同值（CONTEXT tie-break 裁决）。
_CRITICALITY_NEUTRAL = 0.4

# S_top 主干口径标识（per-query 单一标尺，进 trace/快照）。
# 校准余弦与 RRF query-local 比值是两套不可比标尺（前者 cos=0.30 → 0.167，
# 后者 rank-1 恒为 1.0），CONTEXT O-3 的「回退 RRF」是**整链路二选一**，
# 绝不允许同一次查询内 per-repo 混用——混用会让「没进 dense top-K」（即
# dense 相似度低）的仓反而拿到最高 S_top，把结构性偏袒换个形状重演。
S_TOP_SOURCE_DENSE = "dense_cosine"
S_TOP_SOURCE_RRF = "rrf_s_hat"

# 默认权重/常数配置——全 phase 唯一默认值来源：
# 106-02 config loader 的回退值、106-07 replay 的兜底值、106-08 golden harness
# 的默认值全部 import 本常量，禁止各处复制字面量。
DEFAULT_WEIGHT_CONFIG: dict[str, Any] = {
    # phase106-v2：S_top 口径由 per-repo 混用改为 per-query 单一标尺（BL-01）
    # ——打分公式变更，与 golden baseline 重建同提交生效。
    "weight_set_version": "phase106-v2",
    # 五信号加性权重（per 106-CONTEXT：C_crit 已裁决为同分带 tie-break，
    # 不进加性和；相对权重经缺失重归一化生效，绝对和 0.95 无须为 1）。
    "weights": {
        SIGNAL_TEXT: 0.55,
        SIGNAL_DOMAIN: 0.15,
        SIGNAL_ACTIVITY: 0.12,
        SIGNAL_STACK: 0.08,
        SIGNAL_TEAM: 0.05,
    },
    "constants": {
        # —— 聚合三步（ROUTING-RANKING §2.3）——
        "p": 2.0,  # 软计数陡度（弱命中不算满分）
        "b": 0.6,  # pivoted size normalization 强度（0=不归一，1=完全按密度）
        "n_cap": 6.0,  # breadth 对数饱和点
        "lam": 0.25,  # breadth 在文本证据中的占比（S_text = (1-λ)·S_top + λ·breadth）
        "n_bar": None,  # 全仓节点数中位数（N̄）——离线快照注入（106-04）；缺失时
        #                 denom_size=1.0（b=0 等价降级路径，breadth 仍有定义）
        # —— 活跃度指数衰减（ROUTING-RANKING §3.5）——
        "half_life_days": 180.0,
        "offset_days": 14.0,
        "activity_floor": 0.05,
        "deprecated_cap": 0.10,  # 「疑似废弃」封顶（跨来源，落在 activity 项内）
        # —— MaxP 主干 affine clip 校准（ROUTING-RANKING §3.2）——
        # s_top_c_lo/c_hi 与 t2_c_lo/c_hi 均为 O-2 校准输出的**初值**
        # （生产实测回填 deferred，per 106-CONTEXT 数据环境标注纪律）。
        "s_top_c_lo": 0.25,
        "s_top_c_hi": 0.55,
        # t2_* 由 resolver（106-03）消费，scorer 仅随配置携带。
        "t2_c_lo": 0.25,
        "t2_c_hi": 0.55,
        # —— 关键程度同分带宽（|ΔS| < crit_band 视为同分带）——
        "crit_band": 0.03,
    },
    # 关键程度锚点四档全保留（Pitfall 1：facet 自动值只有 核心/重要/边缘 三档，
    # 但人工 pin 可出现「一般」）；枚举外值 → criticality=None（不可用）。
    "criticality_anchors": {"核心": 1.0, "重要": 0.7, "一般": 0.4, "边缘": 0.15},
    # 未来若切换 C_crit 为加性方案的开关位（research §4 初值表 0.05）——
    # 当前不参与任何计算（CONTEXT 裁决：tie-break only）。
    "crit_weight_reserved": 0.05,
    # O-2 校准判废弃 T2 通道的 facet 列表（c_hi-c_lo < 0.10 的 facet）。
    "t2_disabled_facets": [],
    # 换 embedding 模型必须重校准并回填（resolver/校准 command 维护）。
    "embedding_model_id": None,
    "calibrated_at": None,
}

# 版本绑定四元组之一（weight_set_version + prompt_hash + model_id + index_version），
# 快照与 golden baseline 都必须记录。单一来源取自 DEFAULT_WEIGHT_CONFIG——
# bump 版本必须与 golden baseline 重建在同一提交生效（Pitfall 8 防呆：门禁版本
# 守护 test_golden_gate_vs_baseline 首个 assert 会拦截不同步的改动）。
WEIGHT_SET_VERSION: str = DEFAULT_WEIGHT_CONFIG["weight_set_version"]

_SENTINEL_UNAVAILABLE = None  # 信号不可用标记（缺失 ≠ 确认不匹配，走权重重归一化）


@dataclass
class ScoredCandidate:
    """一个候选仓库的可拆解打分结果。

    repo_name 容错契约：payload 缺 repo_name（如 replay 从最小字段集快照重建）
    时确定性回退为 repo_id，且分数/breakdown/排序不受 repo_name 有无影响
    （tie-break 键本就不含 name）。

    criticality 是关键程度锚点值（informational 旁路，per CONTEXT 裁决）：
    仅参与同分带 tie-break 排序与 trace/前端展示，**绝不计入 breakdown/score**
    ——Σbreakdown == score 恒等式（INV-R3）不含它。
    """

    repo_id: str
    repo_name: str
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)
    facets: dict[str, Any] = field(default_factory=dict)
    # hits 透传：供 Stage 1 组 prompt / finalize 取 node_path。
    hits: list[dict[str, Any]] = field(default_factory=list)
    # 关键程度锚点值（{核心:1.0, 重要:0.7, 一般:0.4, 边缘:0.15}）；缺失/枚举外 → None。
    criticality: float | None = None
    # 本次查询采用的 S_top 口径（``S_TOP_SOURCE_DENSE`` / ``S_TOP_SOURCE_RRF``）：
    # 同一次打分内全候选恒等（per-query 单一标尺，BL-01），旁路 informational
    # 字段——**不进 breakdown**，供 trace/快照记录「本次用的哪套标尺」。
    s_top_source: str = ""


def _parse_facets(value: Any) -> dict[str, Any]:
    """容错解析 payload.facets（可能是 dict 或 JSON str；坏 JSON → 空 dict）。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _activity_signal(facets: dict[str, Any]) -> float | None:
    """legacy 路径活跃度信号：facet 缺失或值不在映射表 → 不可用（None，非补 0）。

    「未知 ≠ 确认不匹配」（ROUTING-RANKING §3.4）——缺失走权重重归一化。
    """
    raw = facets.get("活跃度")
    if not isinstance(raw, str):
        return _SENTINEL_UNAVAILABLE
    mapped = ACTIVITY_ENUM_MAP.get(raw)
    if mapped is None:
        return _SENTINEL_UNAVAILABLE
    if raw == "疑似废弃":
        return min(mapped, DEPRECATED_ACTIVITY_CAP)
    return mapped


def _is_number(value: Any) -> bool:
    """数值判定（bool 是 int 子类，显式排除）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _merge_constants(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """constants 与默认 merge：缺键补默认，非法值按默认处理（T-106-02）。

    严格校验（拒绝写入）在 106-02 loader / view 层——本函数只做防御性
    回退，保证纯函数在任意注入下不抛、不产出未定义算式（除零/负对数等）。
    """
    base: dict[str, Any] = dict(DEFAULT_WEIGHT_CONFIG["constants"])
    merged = dict(base)
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if key not in base:
                continue  # 未知键忽略
            if key == "n_bar":
                # n_bar 允许 None（缺失 → denom_size=1.0 降级路径）
                if value is None or (_is_number(value) and float(value) > 0.0):
                    merged[key] = None if value is None else float(value)
                continue
            if _is_number(value):
                merged[key] = float(value)
    # 结构性防御：非法取值回退默认（避免除零 / 负底数 / 空带宽）。
    if merged["p"] <= 0.0:
        merged["p"] = base["p"]
    if not 0.0 <= merged["b"] <= 1.0:
        merged["b"] = base["b"]
    if merged["n_cap"] <= 0.0:
        merged["n_cap"] = base["n_cap"]
    if not 0.0 <= merged["lam"] <= 1.0:
        merged["lam"] = base["lam"]
    if merged["half_life_days"] <= 0.0:
        merged["half_life_days"] = base["half_life_days"]
    if merged["offset_days"] < 0.0:
        merged["offset_days"] = base["offset_days"]
    if not 0.0 <= merged["activity_floor"] <= 1.0:
        merged["activity_floor"] = base["activity_floor"]
    if not 0.0 <= merged["deprecated_cap"] <= 1.0:
        merged["deprecated_cap"] = base["deprecated_cap"]
    if merged["s_top_c_hi"] - merged["s_top_c_lo"] <= 0.0:
        merged["s_top_c_lo"] = base["s_top_c_lo"]
        merged["s_top_c_hi"] = base["s_top_c_hi"]
    if merged["crit_band"] <= 0.0:
        merged["crit_band"] = base["crit_band"]
    return merged


def _parse_iso_utc(value: Any) -> datetime | None:
    """ISO 8601 解析；naive 时间戳按 UTC 处理；解析失败 → None（信号不可用）。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _clip01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def resolve_s_top_source(repo_ids: Any, repo_meta: Any) -> str:
    """本次查询的 S_top 口径（per-query 二选一，BL-01）。

    全部参与打分的仓都有可用 ``dense_cos_max`` → ``S_TOP_SOURCE_DENSE``
    （校准余弦口径）；**任一仓缺失** → ``S_TOP_SOURCE_RRF``，整条链路统一
    回退 RRF query-local s_hat（CONTEXT O-3 的「回退」是整链路取舍）。

    纯函数、无副作用：router（记 trace/快照）与 scorer（实际打分）调同一
    函数、喂同一输入，两处口径恒等；回放从快照 ``repo_meta`` 重算亦然
    （快照自包含前提见 BL-02）。
    """
    if not isinstance(repo_meta, dict):
        return S_TOP_SOURCE_RRF
    rids = [str(rid) for rid in repo_ids]
    if not rids:
        return S_TOP_SOURCE_RRF
    for rid in rids:
        meta = repo_meta.get(rid)
        if not isinstance(meta, dict) or not _is_number(meta.get("dense_cos_max")):
            return S_TOP_SOURCE_RRF
    return S_TOP_SOURCE_DENSE


def _s_top_signal(
    meta: dict[str, Any],
    bucket_s_hats: list[float],
    consts: dict[str, Any],
    source: str,
) -> float:
    """MaxP 主干，口径由 ``source`` 统一指定（per-query，绝不 per-repo 混用）。

    - ``S_TOP_SOURCE_DENSE``：dense 余弦 affine clip 校准（全仓都有余弦时）；
    - ``S_TOP_SOURCE_RRF``：桶内 max s_hat（任一仓缺余弦时全仓一律走此口径，
      Pitfall 6 的整链路降级——缺 dense 覆盖的仓不打死，也不因缺失反获高分）。
    """
    if source == S_TOP_SOURCE_DENSE:
        cos = meta.get("dense_cos_max")
        if _is_number(cos):
            c_lo = consts["s_top_c_lo"]
            c_hi = consts["s_top_c_hi"]
            return _clip01((float(cos) - c_lo) / (c_hi - c_lo))
    return max(bucket_s_hats) if bucket_s_hats else 0.0


def _breadth_signal(
    meta: dict[str, Any],
    bucket_s_hats: list[float],
    consts: dict[str, Any],
) -> float:
    """pivoted-size-normalized 对数饱和 breadth（ROUTING-RANKING §2.3 三步）。

    Step 1  n_eff = Σ (s_hat_i / s_hat_bucket_top) ** p   （桶内软计数）
    Step 2  denom_size = 1 - b + b·(N_r/N̄)               （n_r > 0 且 n_bar > 0 时）
            否则 denom_size = 1.0（b=0 等价降级——n_bar/n_r 缺失时 breadth 仍有
            定义；``n_r <= 0`` 按缺失处理，绝不给「体量 0」的仓归一红利）
    Step 3  breadth = min(log1p(n_eff/denom_size) / log1p(n_cap), 1.0)
    """
    top = bucket_s_hats[0] if bucket_s_hats else 0.0
    if top > 0.0:
        n_eff = math.fsum((s / top) ** consts["p"] for s in bucket_s_hats)
    else:
        n_eff = 0.0  # rrf_max<=0 全零退化：无有效命中证据

    n_r = meta.get("n_r")
    n_bar = consts["n_bar"]
    # n_r <= 0 视为**缺失**（denom_size=1.0），绝不当有效值：n_r=0 会让
    # denom_size = 1-b = 0.4，即「体量为 0 的仓」拿到最强的尺寸归一红利
    # （n_bar=60 时 breadth 0.6438 vs 中性 0.3562，+0.29 的凭空加成）。
    # 真实触发路径：快照生成后新索引的仓（Qdrant 已有节点 → 会出现在
    # node_hits，快照里仍是 0）会获得系统性优势——与 ROUTE-03 相反。
    if _is_number(n_r) and float(n_r) > 0.0 and _is_number(n_bar) and float(n_bar) > 0.0:
        b = consts["b"]
        denom_size = 1.0 - b + b * (float(n_r) / float(n_bar))
        if denom_size <= 0.0:
            denom_size = 1.0
    else:
        denom_size = 1.0

    return min(math.log1p(n_eff / denom_size) / math.log1p(consts["n_cap"]), 1.0)


def _activity_signal_v2(
    meta: dict[str, Any],
    facets: dict[str, Any],
    consts: dict[str, Any],
    now_dt: datetime | None,
) -> float | None:
    """活跃度真值表（Pitfall 4，四行全覆盖）：

    1. last_commit_at 与 now 均可解析 → 连续指数衰减：
       ``delta = max(0, (now - last_commit).days - offset_days)``，
       ``A = max(0.5 ** (delta / half_life_days), activity_floor)``。
    2. last_commit_at 不可用 → facets 活跃度枚举映射（ACTIVITY_ENUM_MAP）。
    3. 两者皆无 → 信号不可用（None，走重归一化）。
    4. **无论哪个来源**：facets["活跃度"] == "疑似废弃" → A = min(A, deprecated_cap)
       ——封顶语义接管，惩罚完全落在 activity 项内。
    """
    a_val: float | None = None

    last_dt = _parse_iso_utc(meta.get("last_commit_at"))
    if last_dt is not None and now_dt is not None:
        delta_days = max(0.0, float((now_dt - last_dt).days) - consts["offset_days"])
        a_recency = 0.5 ** (delta_days / consts["half_life_days"])
        a_val = max(a_recency, consts["activity_floor"])
    else:
        raw = facets.get("活跃度")
        if isinstance(raw, str):
            mapped = ACTIVITY_ENUM_MAP.get(raw)
            if mapped is not None:
                a_val = mapped

    if a_val is not None and facets.get("活跃度") == "疑似废弃":
        a_val = min(a_val, consts["deprecated_cap"])
    return a_val


def _facet_signal(meta: dict[str, Any], key: str) -> float | None:
    """domain/stack/team：直接消费 resolver 注入的匹配分。

    scorer 不做任何匹配/max 聚合——多值 max、"未分类"→缺失、团队条件信号
    均在上游 resolver（106-03）落定。float 取值（越界 clip 至 [0,1]，
    trust boundary 容错）；None/键缺失/类型错误 → 信号不可用。
    """
    facet_scores = meta.get("facet_scores")
    if not isinstance(facet_scores, dict):
        return _SENTINEL_UNAVAILABLE
    entry = facet_scores.get(key)
    if not isinstance(entry, dict):
        return _SENTINEL_UNAVAILABLE
    score = entry.get("score")
    if not _is_number(score):
        return _SENTINEL_UNAVAILABLE
    return _clip01(float(score))


def _merge_anchors(overrides: Any) -> dict[str, float]:
    """关键程度锚点表与默认 merge：缺键补默认，非法档位/值忽略（T-106-02）。

    严格校验（拒绝写入）在 106-02 loader / view 层——本函数只做防御性回退，
    保证纯函数在任意注入下不抛。
    """
    merged: dict[str, float] = dict(DEFAULT_WEIGHT_CONFIG["criticality_anchors"])
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if isinstance(key, str) and key and _is_number(value):
                merged[key] = _clip01(float(value))
    return merged


def _criticality_value(meta: dict[str, Any], anchors: dict[str, float]) -> float | None:
    """关键程度锚点映射：缺失/枚举外 → None。**不进 breakdown**。

    ``anchors`` 由调用方注入（router 从 SystemSetting 配置、replay 从快照
    ``weight_config.criticality_anchors``）——锚点表是可外置配置项，硬编默认表
    会让运维改了不生效（配置项存在但是死的，比没有更危险）。
    """
    raw = meta.get("criticality_value")
    if not isinstance(raw, str):
        return None
    return anchors.get(raw)


def aggregate_and_score(
    node_hits: list[dict[str, Any]],
    *,
    weights: dict[str, float] | None = None,
    repo_meta: dict[str, dict[str, Any]] | None = None,
    constants: dict[str, Any] | None = None,
    criticality_anchors: dict[str, float] | None = None,
    now: str | None = None,
) -> list[ScoredCandidate]:
    """按仓库聚合 node_hits 并产出可拆解加性分数（INV-R1/R3）。

    模式判定：
    - ``repo_meta is None`` → **legacy 路径**（Phase 105 三信号，逐字段不变）：
      text（max s_hat）+ breadth（命中广度）+ activity（枚举映射），weights None
      时默认 PHASE105_WEIGHTS，排序 ``(-round(score,6), repo_id)``。
    - ``repo_meta is not None`` → **新路径**（Phase 106 六信号）：weights None
      时默认 ``DEFAULT_WEIGHT_CONFIG["weights"]``，constants 与默认 merge，
      排序带关键程度同分带 tie-break。

    参数：
    - ``repo_meta``：per-repo 元数据注入（键契约见模块 docstring）。
    - ``constants``：新路径常数；None → ``DEFAULT_WEIGHT_CONFIG["constants"]``；
      传入时与默认 merge（缺键补默认，非法值回退默认）。
    - ``criticality_anchors``：关键程度锚点表（tie-break 用），同 merge 语义；
      None → 默认四档。由调用方从配置/快照注入——外置配置必须真生效（MJ-01）。
    - ``now``：ISO 8601 时间锚点（活跃度衰减用）。禁止函数内读取系统当前时间
      （回放/golden 确定性）；naive 时间戳按 UTC 处理，last_commit_at 同规则。

    新路径逐信号（分桶/桶内排序/query-local s_hat 归一与 legacy 共用）：
    1. ``S_top``：口径按 :func:`resolve_s_top_source` **per-query** 定一次
       （全仓都有 dense_cos_max → 校准余弦；任一仓缺失 → 全仓统一回退桶内
       max s_hat）——同一次查询内标尺唯一，口径值随 ``ScoredCandidate
       .s_top_source`` 回传供 trace/快照记录。
    2. ``breadth``：pivoted-size-normalized 对数饱和（§2.3 三步）。
    3. 文本合成 ``S_text = (1-λ)·S_top + λ·breadth``，breakdown 拆两个扁平键：
       ``text`` 贡献 = w_text·(1-λ)·S_top/D、``breadth`` 贡献 = w_text·λ·breadth/D
       （两键之和 = w_text·S_text/D；INV-R3 与机制断言同时成立，前端零结构改动）。
    4. ``activity``：连续衰减 / 枚举回退 / 皆无不可用 + 废弃封顶（真值表）。
    5. ``domain``/``stack``/``team``：消费 facet_scores 匹配分，缺失不可用。
    6. 重归一化：available 信号集合上 D = Σw[j]，breakdown[j] = w[j]·M[j]/D，
       score = fsum(breakdown)——Σbreakdown == score 按构造成立（INV-R3）。
    7. ``criticality``：锚点映射进 ScoredCandidate.criticality 旁路字段。
    8. 排序：同分带（量化桶）内按 criticality 决序，见 :func:`_meta_sort_key`。

    求和一律 ``math.fsum``（对真实和精确舍入，顺序无关）。
    """
    # 1. 分桶 + 桶内稳定排序（legacy / 新路径共用）
    buckets: dict[str, list[dict[str, Any]]] = {}
    for hit in node_hits:
        payload = hit.get("payload") or {}
        rid = str(payload.get("repository_id", "") or "")
        if rid:
            buckets.setdefault(rid, []).append(hit)
    for hits in buckets.values():
        hits.sort(
            key=lambda h: (
                -round(float(h.get("score", 0.0)), 6),
                str((h.get("payload") or {}).get("node_id", "")),
            )
        )

    # 2. query-local max 归一（legacy / 新路径共用）
    all_scores = [float(h.get("score", 0.0)) for hits in buckets.values() for h in hits]
    rrf_max = max(all_scores) if all_scores else 0.0

    def _s_hat(hit: dict[str, Any]) -> float:
        if rrf_max <= 0.0:
            return 0.0  # 防除零：全部退化为 0
        return float(hit.get("score", 0.0)) / rrf_max

    if repo_meta is None:
        return _score_legacy(buckets, _s_hat, weights)
    return _score_with_meta(
        buckets, _s_hat, weights, repo_meta, constants, criticality_anchors, now
    )


def _score_legacy(
    buckets: dict[str, list[dict[str, Any]]],
    s_hat_fn: Any,
    weights: dict[str, float] | None,
) -> list[ScoredCandidate]:
    """legacy 路径（Phase 105 三信号）——行为逐字段保持不变。"""
    w = weights if weights is not None else PHASE105_WEIGHTS

    candidates: list[ScoredCandidate] = []
    for rid, hits in buckets.items():
        top_payload = hits[0].get("payload") or {}
        facets = _parse_facets(top_payload.get("facets"))

        # 三信号（不可用 → None，参与重归一化而非补 0）
        signals: dict[str, float | None] = {
            SIGNAL_TEXT: max(s_hat_fn(h) for h in hits),
            SIGNAL_BREADTH: min(len(hits) - 1, 5) / 5.0,
            SIGNAL_ACTIVITY: _activity_signal(facets),
        }

        # 加性合成 + 缺失重归一化（math.fsum 消除顺序依赖）
        available = {sig: val for sig, val in signals.items() if val is not None}
        denom = math.fsum(w.get(sig, 0.0) for sig in available)
        breakdown: dict[str, float] = {}
        if denom > 0.0:
            breakdown = {sig: w.get(sig, 0.0) * val / denom for sig, val in available.items()}
        score = math.fsum(breakdown.values())

        repo_name = str(top_payload.get("repo_name") or "") or rid
        candidates.append(
            ScoredCandidate(
                repo_id=rid,
                repo_name=repo_name,
                score=score,
                breakdown=breakdown,
                facets=facets,
                hits=hits,
            )
        )

    # 稳定排序：先量化再比较；第二键不可变 repo_id（禁止 name/path）
    candidates.sort(key=lambda c: (-round(c.score, 6), c.repo_id))
    return candidates


def _score_with_meta(
    buckets: dict[str, list[dict[str, Any]]],
    s_hat_fn: Any,
    weights: dict[str, float] | None,
    repo_meta: dict[str, dict[str, Any]],
    constants: dict[str, Any] | None,
    criticality_anchors: dict[str, float] | None,
    now: str | None,
) -> list[ScoredCandidate]:
    """新路径（Phase 106 六信号）：MaxP+breadth 主干 + 元数据三信号 +
    活跃度连续化 + 关键程度同分带 tie-break。"""
    w: dict[str, float] = weights if weights is not None else DEFAULT_WEIGHT_CONFIG["weights"]
    consts = _merge_constants(constants)
    anchors = _merge_anchors(criticality_anchors)
    now_dt = _parse_iso_utc(now)
    lam = consts["lam"]
    # BL-01：S_top 口径在**进入循环前**按全仓 dense 覆盖情况定一次，循环内
    # 全候选共用——同一次查询内标尺唯一，不存在「有余弦的按余弦、没余弦的
    # 按 RRF」的混用。
    s_top_source = resolve_s_top_source(buckets.keys(), repo_meta)

    candidates: list[ScoredCandidate] = []
    for rid, hits in buckets.items():
        top_payload = hits[0].get("payload") or {}
        facets = _parse_facets(top_payload.get("facets"))
        meta_raw = repo_meta.get(rid)
        meta: dict[str, Any] = meta_raw if isinstance(meta_raw, dict) else {}
        bucket_s_hats = [s_hat_fn(h) for h in hits]

        # 1-2. 文本主干两分量（text 信号本身恒可用——候选来自它）
        s_top = _s_top_signal(meta, bucket_s_hats, consts, s_top_source)
        breadth = _breadth_signal(meta, bucket_s_hats, consts)

        # 4-5. 元数据/活跃度信号（不可用 → None，走重归一化，绝不补 0）
        signals: dict[str, float | None] = {
            SIGNAL_ACTIVITY: _activity_signal_v2(meta, facets, consts, now_dt),
            SIGNAL_DOMAIN: _facet_signal(meta, SIGNAL_DOMAIN),
            SIGNAL_STACK: _facet_signal(meta, SIGNAL_STACK),
            SIGNAL_TEAM: _facet_signal(meta, SIGNAL_TEAM),
        }
        available = {sig: val for sig, val in signals.items() if val is not None}

        # 6. 重归一化 + 合成：D 含 text（恒可用）与全部 available 信号的权重。
        denom = math.fsum([w.get(SIGNAL_TEXT, 0.0)] + [w.get(sig, 0.0) for sig in available])
        breakdown: dict[str, float] = {}
        if denom > 0.0:
            w_text = w.get(SIGNAL_TEXT, 0.0)
            # 3. S_text = (1-λ)·S_top + λ·breadth，breakdown 拆两个扁平键
            #    （两键之和 == w_text·S_text/D，INV-R3 与 breadth 机制断言同时成立）
            breakdown[SIGNAL_TEXT] = w_text * (1.0 - lam) * s_top / denom
            breakdown[SIGNAL_BREADTH] = w_text * lam * breadth / denom
            for sig, val in available.items():
                breakdown[sig] = w.get(sig, 0.0) * val / denom
        score = math.fsum(breakdown.values())

        repo_name = str(top_payload.get("repo_name") or "") or rid
        candidates.append(
            ScoredCandidate(
                repo_id=rid,
                repo_name=repo_name,
                score=score,
                breakdown=breakdown,
                facets=facets,
                hits=hits,
                # 7. 关键程度锚点值（旁路字段，不计入 Σbreakdown==score 恒等式）
                criticality=_criticality_value(meta, anchors),
                s_top_source=s_top_source,
            )
        )

    # 8. 同分带 tie-break 排序（CONTEXT 裁决：C_crit 不进加性和，仅带内决序）。
    # 取舍记录：量化桶实现下（score 量化到 crit_band 粒度桶），跨桶边界的
    # 邻近对（如 0.0299 与 0.0301）不触发 tie-break——这是 |ΔS|<0.03 字面语义
    # 的近似；换成显式带内两两比较会破坏排序键的全序性（比较不可传递），
    # 无法与稳定排序共存，故采用量化桶。
    crit_band = consts["crit_band"]

    def _meta_sort_key(c: ScoredCandidate) -> tuple[int, float, float, str]:
        quantized = round(c.score, 6)
        band_bucket = int(math.floor(quantized / crit_band + 1e-9))
        crit_rank = c.criticality if c.criticality is not None else _CRITICALITY_NEUTRAL
        return (-band_bucket, -crit_rank, -quantized, c.repo_id)

    candidates.sort(key=_meta_sort_key)
    return candidates


def derive_confidence(
    sorted_scores: list[float],
    *,
    theta_abs: float,
    theta_margin: float,
    theta_med: float,
) -> Confidence:
    """确定性 confidence 推导（RELY-04，ROUTING-RANKING §1.3a）。

    ``S(1) >= θ_abs 且 margin >= θ_margin → high；S(1) >= θ_med → medium；
    否则 low``。空列表 → low；单候选时 margin = S(1)（s2 视为 0.0）。
    """
    if not sorted_scores:
        return "low"
    s1 = sorted_scores[0]
    s2 = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
    margin = s1 - s2
    if s1 >= theta_abs and margin >= theta_margin:
        return "high"
    if s1 >= theta_med:
        return "medium"
    return "low"


def apply_llm_adjustment(deterministic: Confidence, llm: Confidence | None) -> Confidence:
    """LLM confidence 调节：只降不升（per CONTEXT RELY-04）。

    llm 为 None 或非法值 → 返回 deterministic；否则取两者中较低档
    （min 语义）——LLM 绝不能把 low/medium 升为 high。
    """
    order = {"low": 0, "medium": 1, "high": 2}
    if llm not in order:
        return deterministic
    return llm if order[llm] < order[deterministic] else deterministic


__all__ = [
    "ACTIVITY_ENUM_MAP",
    "Confidence",
    "DEFAULT_WEIGHT_CONFIG",
    "DEPRECATED_ACTIVITY_CAP",
    "PHASE105_WEIGHTS",
    "S_TOP_SOURCE_DENSE",
    "S_TOP_SOURCE_RRF",
    "SIGNAL_ACTIVITY",
    "SIGNAL_BREADTH",
    "SIGNAL_DOMAIN",
    "SIGNAL_STACK",
    "SIGNAL_TEAM",
    "SIGNAL_TEXT",
    "ScoredCandidate",
    "WEIGHT_SET_VERSION",
    "aggregate_and_score",
    "apply_llm_adjustment",
    "derive_confidence",
    "resolve_s_top_source",
]
