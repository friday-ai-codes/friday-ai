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
注意「首位」是按凸组合 ``score_ranked`` 排序后的首位，故 α 会参与 auto_selected
判定，但方向单调安全（只抑制、不误开），被抑制的场景由
``auto_selected_suppressed_by_alpha`` 上报——详见 ``route`` 内该变量处的注释。

降级链（结果带 ``degraded`` 标志，Stage 1 未参与时为 True）：
- LLM 失败/超时 → Stage 0 聚合分数直接出结果（仍优于 v1：节点级检索）
- repo_index_nodes 无命中 → 回落 v1 RepoRouter（repo_summaries 单点检索）

分面信号：节点 payload 的 facets 参与排序——活跃度经枚举映射进加性活跃度项，
疑似废弃仓库的惩罚为活跃度项封顶（非乘性惩罚，贡献仍可单独拆解展示）。

Stage 1 幂等三件套（ROUTE-09）：(1) 输入哈希缓存——key 绑定 model_id /
PROMPT_TEMPLATE_VERSION / canonical stage0_input / decode 参数 / index_version，
命中零 LLM 调用；(2) LLM 只输出排列（有序数组 + 文本字段），禁止数值分数——离散
低熵输出对 logits 微扰鲁棒；(3) decode 参数全固定（temperature=0/top_p=1/固定
seed）。Stage 1 调用统一包 use_call_source(AUX_REPO_ROUTER) 作用域。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import structlog
from asgiref.sync import sync_to_async
from django.core.cache import cache

from agents.call_source import CallSource, use_call_source
from codegraph.services.repo_index_tree import COLLECTION_NAME
from codegraph.services.repo_router_config import (
    aload_alias_dict,
    aload_nr_snapshot,
    aload_weight_config,
)
from codegraph.services.repo_router_metadata import (
    FACET_CRITICALITY,
    FACET_DOMAIN,
    FACET_STACK,
    LAYER_T2,
    FacetT2Matcher,
    resolve_facet_scores,
    warm_facet_vectors,
)
from codegraph.services.repo_router_ranking import (
    CROSS_GROUP_NOTE,
    GROUP_GLOBAL,
    GROUP_IN_PROJECT,
    TRUST_NEEDS_CONFIRMATION,
    annotate_groups,
    blend_ranked_scores,
    clamp_llm_permutation,
    clamp_ranking_params,
    classify_degrade_reason,
    decide_block_order,
    is_retryable_upstream_failure,
)
from codegraph.services.repo_router_scoring import (
    DEFAULT_WEIGHT_CONFIG,
    aggregate_and_score,
    apply_llm_adjustment,
    derive_confidence,
    resolve_s_top_source,
    select_stage0_pool,
)
from common.logging import redact_secrets_in_text
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from services.query_embedding import embed_query
from services.sparse_encoder import SparseEncoderService

logger = structlog.get_logger(__name__)

Confidence = Literal["high", "medium", "low"]

# Stage 0 全局节点召回预算。50 是历史值，实测偏小：30 仓空间下「高三提分专项」
# 语料把 study-course 的最佳节点压到全局 #80，它因此**从未进入候选**，Stage 1 的
# LLM 再强也无从挽回（reranker/LLM 救不回没见过的文档——一阶召回即天花板）。
# 200 覆盖实测所需深度且仍是单次 query_points 调用（服务端 RRF，零额外往返）。
# 运维可经 settings 覆盖而不必改代码发版。
_STAGE0_NODE_K_DEFAULT = 200
STAGE0_REPO_K = 12


def _stage0_node_k() -> int:
    """全局节点召回预算（调用时读 settings，非数值/非正一律回退默认，绝不抛）。"""
    from django.conf import settings

    try:
        value = int(float(getattr(settings, "REPO_ROUTER_STAGE0_NODE_K", _STAGE0_NODE_K_DEFAULT)))
    except (TypeError, ValueError, OverflowError):
        return _STAGE0_NODE_K_DEFAULT
    return value if value >= 1 else _STAGE0_NODE_K_DEFAULT


# 向后兼容：既有调用方/测试直接读模块常量（v1 回退路径也用它）。
STAGE0_NODE_K = _STAGE0_NODE_K_DEFAULT

# dense 余弦探测的召回预算，与节点召回预算同值。
#
# ⚠️ 调大它会**改变 S_top 的口径**，不是单纯多召回一点：`resolve_s_top_source`
# 要求**全部**分桶仓都拿到 dense_cos_max 才启用校准余弦，只要缺一个就全仓回退
# `rrf_s_hat`。实测本实例 30 仓空间下 top_k=200/400 → 覆盖 19/20 仓（走 RRF），
# 800 → 20/20（切到余弦）。
#
# 2026-08 实测结论：切到余弦口径当前**弊大于利**——校准常数 s_top_c_lo/c_hi
# （0.25/0.55）是从未回填的占位初值，而 doubao-embedding-text 的真实 dense_cos_max
# 落在 0.72~0.86，**100% 落在 c_hi 之上**，全部 clip 成 1.0 → text 退化为常数、
# 零区分度，排序改由 breadth/activity 主导。校准窗口修正为 p5/p95（0.737/0.815）
# 后 text 恢复区分度（饱和率 100%→5.4%），但端到端 candidate_recall 无变化
# （0.9167），收益未经证实，故两项都未采纳。
#
# 要启用余弦口径，必须**先**用 `.planning/quick/260809-repo-route-eval/
# calibrate_s_top.py` 重新校准并跑多轮召回评测确认收益，再一起上。
STAGE0_DENSE_K = _STAGE0_NODE_K_DEFAULT

# 接入 cross-encoder 精排时先取的**宽**候选池，精排后再收窄回 STAGE0_REPO_K。
#
# 为什么需要它（2026-08 实测）：六信号打分含 `breadth`（命中广度）分量，而多探针
# 检索把这个信号放大了——泛泛相关的仓在 8 个探针上各捞几个节点，累积出 20~27 个；
# 专精仓只在少数探针上强命中，只有 9 个。结果 study-course 在融合节点里排 #58
# （稳稳在 top-200 内），却因节点数少而挤不进仓级 top-12，Stage 1 的 LLM 从未见过它。
# cross-encoder 拿 query 与文档**联合**打分，不吃「你出现了多少次」，正是这一偏置的解药。
STAGE0_REPO_K_WIDE = 30

# 每仓取几个命中节点拼成 rerank 文档（够表达该仓与需求的关系，又不撑爆 pair 长度）。
_RERANK_REPO_DOC_HITS = 6
# cross-encoder 的 query 侧预算。它同样是 transformer，pair 总长受限；且实测**短
# query 反而更准**（一句话摘要能把 study-course 从"未进候选"直接拉到 #1）。
_RERANK_QUERY_MAX_CHARS = 2000
# 双序融合的 RRF 常数（社区默认 k=60）。
#
# 为什么是融合而不是「精排全权定序」：实测两个极端都会漏。让精排主导中后段能把
# study-course 从 #11 提到 #9（进了 LLM 视野），但同时把 onion-practice 挤出
# top-12，换进两个无关仓——净收益为负。六信号里有 cross-encoder 看不到的事实
# （活跃度、关键度、子应用结构），两路必须互补而非相互取代。
# RRF 融合下四个目标仓**全部**落在 top-12 内（study-course #11），代价只是
# Stage 1 得看得到第 11 名 —— 见 REPO_ROUTER_STAGE1_MAX_CANDIDATES。
_RERANK_RRF_K = 60

# 仓库级 last_commit 聚合缓存 TTL（MJ-05）：活跃度是天级衰减信号，60s 陈旧
# 完全可接受；键含候选仓集合，命中即省掉一次 FileIndex 全量聚合。
_LAST_COMMIT_CACHE_TTL_SECONDS = 60

# 单次路由的 T2 embedding 调用硬上限（MJ-06）：缓存冷启动时逐值串行 embedding
# 会把 Stage 0 拖到秒级；超限静默降级 T1-only（T2 绝不阻塞路由）。
STAGE0_T2_EMBED_BUDGET = 16

# Stage 1 prompt 模板版本（ROUTE-09 幂等三件套）：参与输入哈希缓存 key 与
# snapshot 的 prompt_hash 版本绑定四元组。system/human prompt 文案（含排列输出
# 指令）任何变更都必须递增此版本——否则旧模板下缓存的排列会冒充新模板输出。
# v2：Stage 1 prompt 的需求正文改为独立截断（见 STAGE1_PROMPT_QUERY_MAX_CHARS）。
# 长查询下渲染出的 human 消息与 v1 不同，必须递增以让旧模板缓存自然失效。
PROMPT_TEMPLATE_VERSION = "stage1-permutation-v2"

# Stage 1 prompt 里需求正文的字符上界。**只管 prompt，不管检索**——这正是历史
# 缺陷的根因：`RepoAssociationService._QUERY_CHAR_BUDGET=4000` 本是为「防超大
# feature list 塞爆 LLM 上下文」而设，却被加在了检索入参上，把 45 个功能点截到
# 只剩 7 个，检索侧 85% 的语料从未参与召回。两者职责必须分开：检索吃全量（切块
# 多探针），prompt 吃截断版。
#
# 取 8000 而非贴着模型上限：opus 4.8 有 1M 上下文，28k 字符只占约 2%，容量根本
# 不是约束；限制的理由是「lost in the middle」——prompt 越长，中部信息越容易被
# 忽略，且延迟线性上涨。
STAGE1_PROMPT_QUERY_MAX_CHARS = 8000

# Stage 1 固定 decode 参数（幂等第三道防线；主防线是输入哈希缓存 + 排列输出）。
# temperature=0 / top_p=1 / 固定 seed——候选按 Stage 0 分数降序喂入（固定顺序，
# 位置偏置恒定可复现，105-03 已保证）。此 dict 参与缓存 key。
_STAGE1_DECODE_PARAMS: dict[str, Any] = {"temperature": 0.0, "top_p": 1.0, "seed": 42}

# Stage 1 调参从 settings 读（支持环境变量覆盖），取值时机为调用时而非导入时，
# 便于按供应商速度调整而不必改代码发版。默认见 friday/settings.py。
_STAGE1_DEFAULTS = {
    "REPO_ROUTER_STAGE1_TIMEOUT_SECONDS": 90.0,
    # 实测不要调大：8→12 后平均命中从 3.00 掉到 1.20（onion-practice 5/5→0/5）。
    # 容量不是原因（12 仓 × 4 节点对 1M 上下文毫无压力），是 lost-in-the-middle
    # ——候选越多，LLM 越容易被聚合分高的假阳性淹没。名额要靠**精排提高前 8 名的
    # 质量**来用好，而不是靠放宽。
    # 8→10：多探针下专精仓（如 study-course）常落在聚合分 #10~#14；
    # 配合 ``select_stage0_pool(diversify_breadth=True)`` 去 breadth 入选后，
    # Stage 1 需要看到第 10 名才能覆盖。再往 12 实测会触发 lost-in-the-middle
    # （平均命中 3.00→1.20），故停在 10。
    "REPO_ROUTER_STAGE1_MAX_CANDIDATES": 10,
    "REPO_ROUTER_STAGE1_HITS_PER_REPO": 4,
    "REPO_ROUTER_STAGE1_CACHE_TTL_SECONDS": 86400,
    # 107-01 落地：首调与 1 次重试**共享**的总延迟上界（per-call 超时语义不变，
    # 且本 phase 不下调——A5 要求先有 O-6 生产实测）。
    "REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS": 120.0,
    # 指数退避基数；实际睡眠额外受剩余预算封顶。
    "REPO_ROUTER_STAGE1_RETRY_BACKOFF_SECONDS": 2.0,
}


def _stage1_conf(key: str):
    from django.conf import settings

    return getattr(settings, key, _STAGE1_DEFAULTS[key])


def _stage1_seconds(key: str) -> float:
    """读取 Stage 1 的秒级时长参数，非数值/非有限/非正值一律回退默认，**绝不抛**。

    运维把总预算写成 ``""`` 或负数不得让路由报错，也不得让预算退化成 0 从而
    「一次调用都不发」——照 ``clamp_ranking_params`` 的同款 fail-safe 纪律
    （T-107-05）。
    """
    fallback = float(_STAGE1_DEFAULTS[key])
    try:
        value = float(_stage1_conf(key))
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(value) or value <= 0.0:
        return fallback
    return value


def _stage1_int(key: str, *, minimum: int = 1) -> int:
    """读取 Stage 1 的整数参数，非数值/非有限/低于下界一律回退默认，**绝不抛**。

    与 ``_stage1_seconds`` 同款 fail-safe：裸 ``int(_stage1_conf(...))`` 时运维把任一项
    写成 ``""`` 或非数值就抛 ``ValueError``，被 ``route()`` 的兜底 except 吃掉 → 每次
    路由都静默降级 Stage 0，且降级原因是 ``unknown``（``ValueError`` 不命中任何判据），
    排查方向被彻底带偏。
    """
    fallback = int(_STAGE1_DEFAULTS[key])
    try:
        value = int(float(_stage1_conf(key)))
    except (TypeError, ValueError, OverflowError):
        return fallback
    return value if value >= minimum else fallback


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


# 分组呈现与有界重排三参数默认值（与 friday/settings.py 一致，107-01 落地）。
_RANKING_DEFAULTS = {
    "REPO_ROUTER_GROUP_DELTA": 0.15,
    "REPO_ROUTER_STAGE1_ALPHA": 0.35,
    "REPO_ROUTER_STAGE1_RANK_BUDGET_K": 3,
}


def _ranking_conf() -> tuple[float, float, int]:
    """读取分组置顶 delta / 凸组合 α / rank-swap 预算 K（照 ``_stage1_conf`` 模式）。

    调用时读取以保持「改配置即生效」；取值一律经 ``clamp_ranking_params`` 收敛到
    合法域且**绝不抛**——运维把参数设成极端值或写成非数值不得让路由退化或报错
    （T-107-05，与 ``repo_router_config`` 的 fail-safe 同款）。

    Returns:
        ``(delta, alpha, k)``——clamp 后的合法三元组。
    """
    from django.conf import settings

    return clamp_ranking_params(
        delta=getattr(
            settings, "REPO_ROUTER_GROUP_DELTA", _RANKING_DEFAULTS["REPO_ROUTER_GROUP_DELTA"]
        ),
        alpha=getattr(
            settings,
            "REPO_ROUTER_STAGE1_ALPHA",
            _RANKING_DEFAULTS["REPO_ROUTER_STAGE1_ALPHA"],
        ),
        k=getattr(
            settings,
            "REPO_ROUTER_STAGE1_RANK_BUDGET_K",
            _RANKING_DEFAULTS["REPO_ROUTER_STAGE1_RANK_BUDGET_K"],
        ),
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
    # 关键程度锚点值（CONTEXT 裁决：tie-break only）——旁路展示字段，
    # **不进 breakdown**，前端 Σ贡献==score 校验不受影响。
    criticality: float | None = None
    # 分层呈现字段（107-03，ROUTE-01/02）——沿用 criticality 的旁路纪律：
    # 全部带默认值（8 个消费方按具名字段读取，位置参数构造的替身不炸），
    # 且**一律不进 breakdown**。
    # 归属组别：`""` = 未标注（消费方按 global 处理）；取值见 repo_router_ranking.GROUP_*。
    group: str = ""
    # 信任标注：取值见 repo_router_ranking.TRUST_*。
    trust: str = ""
    # 跨组说明：**后端留痕/排障用**。前端一律用前端常量渲染文案、不渲染本字段，
    # 后端自由文本不进 DOM（T-107-06）。
    cross_group_note: str = ""
    # 旁路排序分（D-3 硬约束）：**绝不覆盖 `score`**。`None` = 未重排 → 排序回退
    # `score`（唯一取值口径见模块级 `_rank_value`）。凸组合里 LLM 排名那一项不是
    # 任何信号的贡献，塞进 `breakdown` 会让「分数分解」变成假的，并打断
    # `Σbreakdown == score` 的两条既有断言与前端 1e-6 容差校验（ROUTE-07 承诺）。
    score_ranked: float | None = None

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
            "criticality": self.criticality,
            "group": self.group,
            "trust": self.trust,
            "cross_group_note": self.cross_group_note,
            # None 原样透出（不折成 0.0）：「未重排」与「重排后分数为 0」语义不同。
            "score_ranked": (None if self.score_ranked is None else round(self.score_ranked, 4)),
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
    # 分区呈现顺序（107-03）：有分组上下文时**恒长度 2**（即使某组为空），无上下文时
    # `["global"]`。前端据 `len == 2` 判定是否启用分组呈现，这是唯一依据
    # （UI-SPEC covered 11），也是区分「无项目上下文」与「有上下文但本项目组为空」
    # 两种 all-global 场景的唯一依据。
    block_order: list[str] = field(default_factory=list)
    # 用户可见降级原因：`repo_router_ranking.DEGRADE_REASONS` 的 6 值闭集 ∪ `""`
    # （`""` = 无用户可见原因行）。基数受控才能当指标维度用。
    degrade_reason: str = ""
    # α 抑制了自动推进（MJ-02 的可观测面）：存在 confidence == high 的候选，但凸组合
    # 排序把另一个候选顶到了首位，于是 auto_selected 由 True 变 False。方向单调安全
    # （α 只会抑制、不会误开，见 auto_selected 计算处注释），但「本该自动推进却被 α
    # 静默拦下」与「本来就不该自动推进」在指标上必须能区分，否则无从判断 α 的代价。
    auto_selected_suppressed_by_alpha: bool = False


def _is_decode_param_rejection(exc: BaseException) -> bool:
    """上游 400 是否在拒绝 **decode 参数本身**（而非 prompt / 鉴权等真客户端错误）。

    网关模型目录常年变动（同一实例上就有 81 个模型），「哪个模型不收 temperature」
    没法靠 fixture 枚举——枚举必然滞后，且新模型上架当天就静默降级。故按上游回执
    判定：400 且消息点名了某个 decode 参数，即认定该模型不接受这些参数，调用方据此
    丢掉 decode 参数重试一次。

    判据刻意收紧到「400 + 点名参数 + 拒绝性措辞」三者同时成立：只匹配参数名会把
    「prompt 里恰好出现 temperature 一词」的业务性 400 误判成可重试。
    """
    from interactions.ledger import parse_upstream_status

    status = parse_upstream_status(exc)
    text = str(exc).lower()
    if status is not None:
        if status != 400:
            return False
    elif "400" not in text:
        return False
    if not any(name in text for name in _STAGE1_DECODE_PARAMS):
        return False
    return any(
        word in text
        for word in ("deprecated", "unsupported", "not supported", "unrecognized", "invalid")
    )


def _is_retryable_stage1_error(exc: BaseException) -> bool:
    """Stage 1 失败是否值得重试——**优先按 HTTP 状态码**，类名子串只作兜底。

    判据在 ``repo_router_ranking.is_retryable_upstream_failure`` 内单一维护：429/5xx
    （含 529 Overloaded）与连接/超时类可重试；4xx 客户端错误（参数错误、鉴权、404、
    422 等确定性失败）直接上抛——重试一次结果一样，只会白白吃掉总预算、多一行
    ``ModelUsageRecord``，并把用户可见降级推迟一个 RTT。

    不能只看类名：``APIStatusError`` 是 SDK 基类，实际抛的 ``RateLimitError`` /
    ``InternalServerError`` / ``OverloadedError`` 名字里都不含它，按子串匹配会把最该
    重试的那批全判成不可重试。
    """
    from interactions.ledger import parse_upstream_status

    return is_retryable_upstream_failure(
        exc_type_name=type(exc).__name__,
        status_code=parse_upstream_status(exc),
    )


def _stage1_usage_metadata(response: Any) -> dict[str, Any]:
    """尽力从 LLM 响应取 token 用量；取不到返回空 dict（调用方据此记 0，绝不猜）。"""
    try:
        meta = getattr(response, "usage_metadata", None)
        if isinstance(meta, dict):
            return meta
    except Exception:  # noqa: BLE001 — 取值 best-effort
        pass
    return {}


async def _record_stage1_usage(
    *,
    provider: str,
    model: str,
    duration_ms: int,
    failure_type: str = "",
    upstream_status_code: int | None = None,
    usage: dict[str, Any] | None = None,
) -> None:
    """Stage 1 每次**上游调用**收尾落一行 ``ModelUsageRecord``（LOGGING-SPEC §9）。

    口径：**一次上游调用一行**——重试算两次请求（QPS/错误率按请求数统计才对得
    上）；**缓存命中零行**（未发上游调用，与 ``repo_router_v2_stage1_completed``
    同口径）。与 ``SystemLogEntry.payload.duration_ms``（107-02 的 O-6 数据源）
    是两个口径：前者是事件日志、受运行时采样配置影响；本表可直接复用
    ``system/metrics_query.py`` 的既有分位聚合，无需新写查询。

    非流式调用不填首字延迟（不伪造指标）；token 取不到一律记 0。整块 best-effort：
    写库/取值任何异常都吞掉——观测绝不反噬路由主流程（与 ``_load_repo_meta``
    的既成纪律一致）。
    """
    try:
        from interactions.ledger import arecord_llm_usage

        ctx = structlog.contextvars.get_contextvars()
        user_id = str(ctx.get("user_id") or "system")
        metadata = usage or {}
        await arecord_llm_usage(
            # Stage 1 无 InteractionRun 上下文 → run 可选入口，独立成行。
            run=None,
            call_source=CallSource.AUX_REPO_ROUTER.value,
            provider=provider,
            model=model,
            prompt_tokens=int(metadata.get("input_tokens") or 0),
            completion_tokens=int(metadata.get("output_tokens") or 0),
            total_tokens=int(metadata.get("total_tokens") or 0),
            duration_ms=duration_ms,
            ttft_ms=None,
            upstream_status_code=upstream_status_code,
            failure_type=failure_type,
            user_id=user_id,
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬路由主流程
        pass


def _rank_value(candidate: RepoRouteCandidateV2) -> float:
    """排序比较值的**唯一所有者**：有旁路排序分就用它，缺失则回退 `score`。

    `_apply_presentation` 内至少三处需要这个值——组内排序截断、并集后全局排序、
    取两组首位喂 `decide_block_order`。同一条件表达式内联三遍必然出现「改一处漏
    一处」（例如 107-05 写入旁路分后只更新了其中两处，排序与置顶判据当场不一致）。
    后续 plan 只负责把 `score_ranked` **写上**，不得再声明任何等价取值或排序。
    """
    return candidate.score_ranked if candidate.score_ranked is not None else candidate.score


def _rank_sort_key(candidate: RepoRouteCandidateV2) -> tuple[float, str]:
    """稳定排序键：先量化到 6 位再比较，第二键用不可变 `repo_id`。

    先量化再比较可避免浮点尾数噪声让顺序在两次等价计算间抖动；第二键取 id 而非
    name/path（后者可改名）——ROUTING-RANKING §6.2 第 4 条。组内排序与并集后的
    全局排序共用本函数，别处不得再写一遍等价排序。
    """
    return (-round(_rank_value(candidate), 6), candidate.repo_id)


def _apply_presentation(
    candidates: list[RepoRouteCandidateV2],
    *,
    grouping_repository_ids: list[str] | None,
    delta: float,
    top_k: int,
) -> tuple[list[RepoRouteCandidateV2], list[str]]:
    """分组标注 + 组内取 top_k + 全局排序 + 分区顺序（四条 return 出口共用）。

    `grouping_repository_ids is None` = 调用方无项目上下文 → 全部记 `global`、
    分区顺序退化为 `["global"]`，候选列表按同一个 `_rank_sort_key` 排序后 `[:top_k]`
    （与有上下文路径同口径，「首位 = 最佳」在两条路径上一致）。

    有上下文时按组各取 `top_k` 后并集（ROUTE-01 要求「组内各展示 Top-3」；若维持
    「全局总共 top_k」则 global 组常为 0 条，分组上线即无信息量），并集再按同一个
    比较键全局降序——扁平列表首位恒为全局最高分候选，分区顺序只是呈现层事实。

    本函数**绝不写** `score` / `breakdown`：给本项目仓做任何组别相关的分数偏移
    会让两组分数不可比、「跨组分更低」变成自我实现预言（ROUTING-RANKING §5.1 的
    in-domain 加分禁令）。
    """
    project_repo_ids = (
        frozenset(str(r) for r in grouping_repository_ids)
        if grouping_repository_ids is not None
        else None
    )
    annotations = annotate_groups(
        [c.repo_id for c in candidates], project_repo_ids=project_repo_ids
    )
    for c in candidates:
        c.group, c.trust = annotations.get(c.repo_id, (GROUP_GLOBAL, TRUST_NEEDS_CONFIRMATION))
        if project_repo_ids is not None and c.group == GROUP_GLOBAL:
            c.cross_group_note = CROSS_GROUP_NOTE

    if project_repo_ids is None:
        # 无项目上下文也按同一个比较键排序：`score_ranked` 在本函数之前就已写好，
        # 若这里只截断不排序，同一个 API 会出现两种排序口径——有上下文时「首位 = 凸组合
        # 最高分」，无上下文（MCP / REST / 无 work_item 的编排）时「首位 = LLM 排列首位」。
        # 「首位 = 最佳」是消费方普遍依赖的隐式契约，且前端还会按同一个 rankKey 重排一次，
        # 不排序会让后端扁平顺序与前端渲染顺序不一致。
        return sorted(candidates, key=_rank_sort_key)[:top_k], decide_block_order(
            None, None, delta=delta, has_project_context=False
        )

    in_project = sorted((c for c in candidates if c.group == GROUP_IN_PROJECT), key=_rank_sort_key)
    global_group = sorted((c for c in candidates if c.group == GROUP_GLOBAL), key=_rank_sort_key)
    block_order = decide_block_order(
        _rank_value(in_project[0]) if in_project else None,
        _rank_value(global_group[0]) if global_group else None,
        delta=delta,
        has_project_context=True,
    )
    merged = sorted(in_project[:top_k] + global_group[:top_k], key=_rank_sort_key)
    return merged, block_order


class RepoRouterV2:
    """两阶段推理式仓库路由器。"""

    @classmethod
    async def route(
        cls,
        query: str,
        *,
        top_k: int = 3,
        repository_ids: list[str] | None = None,
        grouping_repository_ids: list[str] | None = None,
        use_llm: bool = True,
        corpus_kind: str = "conversation",
    ) -> RepoRouteResultV2:
        """执行推理式路由。

        ``repository_ids`` 与 ``grouping_repository_ids`` **正交**，互不影响：

        Args:
            query: 用户提问 / 需求文本。
            top_k: 返回候选数上限（传了 ``grouping_repository_ids`` 时按组各取
                ``top_k`` 后并集，长度 <= 2*top_k）。
            repository_ids: 限定候选仓库范围（Qdrant 硬过滤，语义逐字不变）；
                None 为全库。
            grouping_repository_ids: 「本项目关联仓」——**只做 group / trust 标注
                依据，不参与任何过滤或打分**。None = 调用方无项目上下文（MCP /
                REST / skill_steps）→ 全部记 ``global`` 并跳过分组呈现，不报错。
            use_llm: False 时仅跑 Stage 0（纯检索 API 用）。
            corpus_kind: 长查询的语料性质，决定切块后是否过噪声闸。
                ``"conversation"``（默认）= 对话型上下文，只有小部分是检索意图，
                噪声块不该变成探针挤占候选池；``"requirement"`` = 需求型语料
                （feature list / PRD / 技术方案），整篇都是意图，全切全探。
                短查询（单块）下本参数无任何影响。
        """
        # ---- Stage 0: 节点级 hybrid 粗筛 ----
        started = time.monotonic()
        group_delta, _alpha, _budget_k = _ranking_conf()
        # 默认路径不传 kwarg：既有测试替身是严格两位置参数的 `_fake_search(query,
        # repository_ids)`，无条件传 kwarg 会把三个 Stage 0 注入 seam 全部打断。
        if corpus_kind == "requirement":
            searched = await cls._stage0_node_search(
                query, repository_ids, drop_noise_probes=False
            )
        else:
            searched = await cls._stage0_node_search(query, repository_ids)
        # 返回形状兼容三态：生产实现返回 (hits, primary, probe_vectors)；历史
        # 2 元组 (hits, query_dense) 与只返回 hits 列表的测试替身都必须继续可用
        # ——此时 query_dense=None，dense 余弦/T2 走既有降级分支（S_top 回退 RRF）。
        probe_vectors: list[list[float]] = []
        if isinstance(searched, tuple):
            if len(searched) == 3:
                node_hits, query_dense, probe_vectors = searched
            else:
                node_hits, query_dense = searched
                probe_vectors = [query_dense] if query_dense else []
        else:
            node_hits, query_dense = searched, None
        if not node_hits:
            return await cls._fallback_v1(
                query,
                top_k,
                grouping_repository_ids=grouping_repository_ids,
                delta=group_delta,
            )

        # ---- Stage 0.5: 权重配置 + repo_meta 组装（六信号供数，106-06）----
        # 权重经 loader 调用时读取（保存即生效）；repo_meta 组装整体失败
        # （意外异常）回退 repo_meta=None → 打分核心走 legacy 三信号路径——
        # 观测代码与新信号永不反噬路由主流程（T-106-14）。
        # 接了 cross-encoder 就先取宽池，精排后再收窄回 STAGE0_REPO_K；没接则维持原样。
        rerank_on = await cls._rerank_available()
        pool_k = STAGE0_REPO_K_WIDE if rerank_on else STAGE0_REPO_K

        config: dict[str, Any] | None = None
        repo_meta: dict[str, dict[str, Any]] | None = None
        meta_stats: dict[str, Any] = {}
        try:
            config = await aload_weight_config()
            repo_meta, meta_stats = await cls._load_repo_meta(
                node_hits, query, query_dense, config, probe_vectors=probe_vectors
            )
        except Exception as exc:  # noqa: BLE001 — 整体失败回退 legacy，绝不中断路由
            repo_meta = None
            try:
                logger.warning(
                    "repo_router_meta_load_failed",
                    error_type=type(exc).__name__,
                    # 上游异常文本先脱敏再截断：截断只是限长，不是脱敏——密钥出现在
                    # 前 200 字符时照样落进日志（T-107-02 的同类缺口，两处都要改）。
                    error=redact_secrets_in_text(str(exc))[:200],
                    category="sampling",
                    component="repo_router_v2",
                )
            except Exception:  # noqa: BLE001
                pass
        # 唯一取 now 的位置（值进快照 stage0.scored_at）——活跃度衰减的时间
        # 锚点参数注入打分核心，回放/golden 确定性依赖此纪律。
        scored_at = datetime.now(timezone.utc).isoformat()

        # 多探针（长需求切块）放大 breadth：专精仓节点少、挤不进仓级 top-K。
        # 仅在此路径打开去 breadth 入选；单探针短查询保持原总分序。
        diversify_breadth = bool(probe_vectors and len(probe_vectors) > 1)

        if config is not None and repo_meta is not None:
            effective_constants = {**config["constants"], "n_bar": meta_stats.get("n_bar")}
            # 锚点表也是外置配置（MJ-01）：注入打分核心 + 进快照，否则运维改了
            # 不生效、回放的 tie-break 顺序也不可复现。
            effective_anchors = dict(
                config.get("criticality_anchors")
                or DEFAULT_WEIGHT_CONFIG["criticality_anchors"]
            )
            stage0_candidates = cls._stage0_candidates(
                node_hits,
                top_k=pool_k,
                weights=config["weights"],
                repo_meta=repo_meta,
                constants=effective_constants,
                criticality_anchors=effective_anchors,
                now=scored_at,
                diversify_breadth=diversify_breadth,
            )
            # 快照携带本次生效全值（回放不依赖当时的 SystemSetting，106-07 消费）。
            snapshot_weight_config: dict[str, Any] | None = {
                "weights": dict(config["weights"]),
                "constants": effective_constants,
                "criticality_anchors": effective_anchors,
                "weight_set_version": config["weight_set_version"],
                "alias_dict_hash": meta_stats.get("alias_dict_hash"),
                "embedding_model_id": meta_stats.get("embedding_model_id"),
            }
            # 记**全部分桶仓**的 meta（BL-02 快照自包含）：回放用全量 node_hits
            # 重算，缺 meta 的仓会同时拿到「S_top 口径漂移 + breadth denom=1.0 +
            # facet 全缺重归一化」三重缺失红利，分数虚高并挤进比对窗口，让
            # verify_snapshot_replay 稳定误报。体积护栏作用在 node_hits（每条含
            # path 等长字段）上，repo_meta 每仓仅 5 个短字段，50 仓不过几 KB。
            snapshot_repo_meta: dict[str, Any] | None = dict(repo_meta)
        else:
            stage0_candidates = cls._stage0_candidates(
                node_hits, top_k=pool_k, diversify_breadth=diversify_breadth
            )
            snapshot_weight_config = None
            snapshot_repo_meta = None

        # Stage 0.7：cross-encoder 按真实相关度纠正入选集合与次序（fail-open）。
        if rerank_on:
            stage0_candidates = await cls._rerank_select(
                query, stage0_candidates, keep=STAGE0_REPO_K
            )

        snapshot_extras: dict[str, Any] = {
            "weight_config": snapshot_weight_config,
            "repo_meta": snapshot_repo_meta,
            "scored_at": scored_at,
            "s_top_source": meta_stats.get("s_top_source"),
        }
        # 呈现参数随三条 Stage 0 出口透传（分组依据只标注、不过滤、不打分）。
        presentation_extras: dict[str, Any] = {
            "grouping_repository_ids": grouping_repository_ids,
            "delta": group_delta,
        }

        if not stage0_candidates:
            # node_hits 非空但全部缺 repository_id（打分核心过滤后零候选）：
            # 进 Stage 1 只会发一次空 prompt 的 LLM 调用再被白名单过滤降级——
            # 提前短路省掉这次浪费（IN-04a）。
            return cls._stage0_only_result(
                query,
                node_hits,
                stage0_candidates,
                top_k,
                started,
                stage1_meta={"skipped_reason": "no_stage0_candidates"},
                **presentation_extras,
                **snapshot_extras,
            )
        # 桶仅供 Stage 1 组 prompt 取命中节点用；打分聚合已在纯函数核心内完成。
        repo_buckets = cls._aggregate_by_repo(node_hits)

        if not use_llm:
            return cls._stage0_only_result(
                query,
                node_hits,
                stage0_candidates,
                top_k,
                started,
                stage1_meta={"skipped_reason": "use_llm_false"},
                **presentation_extras,
                **snapshot_extras,
            )

        # ---- Stage 1: LLM 树推理 ----
        stage1_exc_type: str | None = None
        stage1_status_code: int | None = None
        try:
            llm_candidates, stage1_meta = await cls._stage1_llm_reasoning(
                query, stage0_candidates, repo_buckets, top_k
            )
        except Exception as exc:  # noqa: BLE001 — LLM 任意失败都降级 Stage 0
            from interactions.ledger import parse_upstream_status

            stage1_exc_type = type(exc).__name__
            # 状态码优先于类名参与降级原因分类：429/5xx 的 SDK 子类名不含 "APIStatus"，
            # 只按类名会让它们落进「未知原因」（用户看到的就是那行文案）。
            stage1_status_code = parse_upstream_status(exc)
            # 上游异常 body 可能回显请求内容（prompt 片段 / header 残留），必须先脱敏
            # 再截断——截断不是脱敏。原始 str(exc) 不进任何会回前端的结构。
            error_redacted = redact_secrets_in_text(str(exc))[:200]
            logger.warning(
                "repo_router_v2_stage1_failed",
                error_type=stage1_exc_type,
                error=error_redacted,
                timeout_seconds=_stage1_conf("REPO_ROUTER_STAGE1_TIMEOUT_SECONDS"),
                category="sampling",
                component="repo_router_v2",
            )
            llm_candidates = None
            stage1_meta = {
                "skipped_reason": f"stage1_failed:{stage1_exc_type}",
                # 脱敏后的排障文本（供下钻）；入库整体仍走 redact_for_ledger，双保险。
                "error_redacted": error_redacted,
            }

        if not llm_candidates:
            # 降级路径同样产出确定性分级，margin 达标即可 auto_selected（RELY-04 解锁点）。
            return cls._stage0_only_result(
                query,
                node_hits,
                stage0_candidates,
                top_k,
                started,
                stage1_meta=stage1_meta,
                exc_type_name=stage1_exc_type,
                status_code=stage1_status_code,
                **presentation_extras,
                **snapshot_extras,
            )

        # LLM 只降不升已在 _stage1_llm_reasoning 内应用；auto_selected 由最终
        # （确定性 + LLM 调节后）confidence 驱动——与降级路径语义一致。
        final, block_order = _apply_presentation(
            llm_candidates,
            grouping_repository_ids=grouping_repository_ids,
            delta=group_delta,
            top_k=top_k,
        )
        # auto_selected 读**扁平列表首位**。这里的首位是按 `score_ranked`（凸组合
        # `(1-α)·S_final + α·S_llm`）排序后的首位，**不是** Stage 0 最高分候选——所以
        # α 确实会参与「是否自动推进」的判定，这是凸组合的设计后果，不是不变量。
        #
        # 组别不进决策路径这一条仍然成立：`_apply_presentation` 的分区顺序（block
        # ranking）只影响呈现，`final` 是按同一比较键的全局降序扁平列表，与 block_order
        # 无关。
        #
        # α 的影响方向是**单调安全**的：confidence == high 只可能出现在 Stage 0 位次 0
        # 上（`_deterministic_confidence`），所以 α 只能把 auto_selected 由 True 变
        # False（更多人工确认），绝不可能凭空造出 high 让本不该自动推进的场景自动推进。
        # 该单调性由 `test_repo_router_v2_meta` 的护栏用例锁定；被抑制的场景经
        # `auto_selected_suppressed_by_alpha` 上报，让代价可观测而非静默。
        auto_selected = bool(final) and final[0].confidence == "high"
        auto_selected_suppressed = not auto_selected and any(
            c.confidence == "high" for c in final
        )
        result = RepoRouteResultV2(
            candidates=final,
            router_version="v2",
            auto_selected=auto_selected,
            auto_selected_suppressed_by_alpha=auto_selected_suppressed,
            degraded=False,
            snapshot=cls._build_snapshot(
                query,
                node_hits,
                final,
                stage1_meta=stage1_meta,
                block_order=block_order,
                **snapshot_extras,
            ),
            block_order=block_order,
        )
        cls._log_scored(result, started)
        return result

    # ------------------------------------------------------------------
    # Stage 0.7：cross-encoder 精排纠偏
    # ------------------------------------------------------------------

    @staticmethod
    async def _rerank_available() -> bool:
        """reranker 是否可用（配置读失败一律当不可用，绝不阻断路由）。"""
        try:
            from services.reranker import RerankerService

            return await RerankerService.is_enabled()
        except Exception:  # noqa: BLE001 — fail-open
            return False

    @staticmethod
    def _rerank_document(candidate: dict[str, Any]) -> str:
        """把一个候选仓压成 rerank 文档：仓名 + 命中的能力节点路径/摘要。"""
        parts = [str(candidate.get("repo_name") or candidate.get("repo_id") or "")]
        for hit in (candidate.get("hits") or [])[:_RERANK_REPO_DOC_HITS]:
            payload = hit.get("payload") or {}
            node_path = str(payload.get("node_path") or "").strip()
            summary = str(payload.get("summary") or "").strip()
            line = f"{node_path}: {summary}" if node_path else summary
            if line:
                parts.append(line)
        return "\n".join(parts)

    @classmethod
    async def _rerank_select(
        cls, query: str, candidates: list[dict[str, Any]], *, keep: int
    ) -> list[dict[str, Any]]:
        """用 cross-encoder 真实相关度纠正候选仓次序，收窄回 ``keep`` 个。

        **只改次序与入选集合，不改任何 score/breakdown** —— 打分核心
        （``aggregate_and_score``）与 golden/replay 的分数契约逐字不变，本步只决定
        「哪 ``keep`` 个仓、以什么顺序」进 Stage 1。

        次序策略：聚合序与精排序用 RRF 融合（理由见 ``_RERANK_RRF_K`` 注释——两个
        极端各自会漏掉不同的目标仓，融合下四仓全进 top-12）。

        fail-open：reranker 未配置/超时/返回空 → 原序截断，与未接入前逐字一致。
        """
        if len(candidates) <= 1:
            return candidates[:keep]
        started = time.monotonic()
        try:
            from services.reranker import RerankerService

            documents = [cls._rerank_document(c) for c in candidates]
            with use_call_source(CallSource.RERANKER):
                results = await RerankerService.rerank(
                    query[:_RERANK_QUERY_MAX_CHARS], documents, top_n=len(documents)
                )
            if not results:
                return candidates[:keep]

            rerank_rank: dict[int, int] = {}
            for order, item in enumerate(results):
                idx = item.get("index")
                if isinstance(idx, int) and 0 <= idx < len(candidates):
                    rerank_rank.setdefault(idx, order)
            if not rerank_rank:
                return candidates[:keep]

            # 未被 reranker 返回的候选按「排在所有返回项之后」处理，不直接淘汰。
            missing_rank = len(results)

            def _fused(i: int) -> float:
                agg = 1.0 / (_RERANK_RRF_K + i)
                rr = 1.0 / (_RERANK_RRF_K + rerank_rank.get(i, missing_rank))
                return agg + rr

            order_idx = sorted(
                range(len(candidates)),
                # 次键取原序下标，保证同分稳定（ROUTE-09 确定性纪律）。
                key=lambda i: (-_fused(i), i),
            )
            selected = [candidates[i] for i in order_idx[:keep]]

            try:
                rescued = [
                    candidates[i]["repo_name"]
                    for i in order_idx[:keep]
                    if i >= keep
                ]
                logger.info(
                    "repo_router_rerank_applied",
                    pool_size=len(candidates),
                    kept=len(selected),
                    rescued_count=len(rescued),
                    rescued=rescued[:5],
                    duration_ms=int((time.monotonic() - started) * 1000),
                    category="sampling",
                    component="repo_router_v2",
                )
            except Exception:  # noqa: BLE001 — 观测 best-effort
                pass
            return selected
        except Exception as exc:  # noqa: BLE001 — 精排失败绝不反噬路由
            try:
                logger.warning(
                    "repo_router_rerank_failed",
                    error_type=type(exc).__name__,
                    error=redact_secrets_in_text(str(exc))[:200],
                    category="sampling",
                    component="repo_router_v2",
                )
            except Exception:  # noqa: BLE001
                pass
            return candidates[:keep]

    # ------------------------------------------------------------------
    # Stage 0
    # ------------------------------------------------------------------

    @classmethod
    async def _stage0_node_search(
        cls,
        query: str,
        repository_ids: list[str] | None,
        *,
        drop_noise_probes: bool = True,
    ) -> tuple[list[dict[str, Any]], list[float] | None]:
        """节点级 hybrid 检索（长查询自动多探针）。

        Args:
            drop_noise_probes: 长查询切块后是否过噪声闸。对话型上下文置 True
                （"好的我看看"这类块不该变成探针去挤占候选池名额）；需求型语料
                置 False（整篇都是检索意图，每段指向不同落点，全切全探）。

        Returns:
            ``(node_hits, query_dense)``——dense 向量随命中一并返回，供
            ``_load_repo_meta`` 的 dense-only 余弦查询与 T2 匹配复用
            （零额外 embedding）。``route()`` 对旧形状（测试替身只返回
            hits 列表）保持兼容。
        """
        # 稀疏侧对全文编一次：SparseEncoderService 是本地 BM25，无长度上限，
        # 不随 dense 切块——关键词/标识符这一面由它完整兜底。
        query_sparse = await sync_to_async(
            SparseEncoderService.encode, thread_sensitive=False
        )(query)
        if not query_sparse.get("indices"):
            return [], None

        # dense 侧走查询收口：短查询单向量（与改造前逐字同路径），超长查询切块
        # 出多向量。绝不因「文本太长」返回空——那正是历史上静默零召回的成因。
        embedded = await embed_query(query, drop_noise=drop_noise_probes)
        if not embedded.ok:
            return [], None

        filters: dict[str, Any] | None = None
        if repository_ids:
            filters = {"repository_id": [str(r) for r in repository_ids]}

        node_k = _stage0_node_k()
        # 多探针塞进**同一次** query_points 的 prefetch 列表，服务端 RRF 融合：
        # 调用次数与单探针相同（N+1 路 prefetch 仍是一次往返）。
        hits = await sync_to_async(
            QdrantService.hybrid_search_multi_by_name, thread_sensitive=False
        )(
            COLLECTION_NAME,
            embedded.vectors,
            query_sparse,
            top_k=node_k,
            prefetch_limit=node_k,
            filters=filters,
        )
        # 回传向量供 _load_repo_meta 复用（零额外 embedding）：
        # - primary 供 T2 facet 匹配（单向量接口）；
        # - 全部探针供 dense_cos_max —— **必须全给**。只用首块算余弦会让 S_top
        #   只看 1/N 的需求语料，相关内容落在后面块的仓（实测 study-course）
        #   text 信号被系统性压低，进而挤不进候选池。
        return hits or [], embedded.primary, embedded.vectors

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

    @staticmethod
    def _load_latest_commits(repository_ids: list[str]) -> dict[str, str | None]:
        """候选仓 last_commit 一次聚合（免 N+1，RESEARCH §3 口径）。

        仓库级 last_commit = ``Max(FileIndex.last_commit_authored_at)``；
        无 FileIndex 行的仓不出现在返回 dict（→ 活跃度走枚举回退，CONTEXT 已锁）。
        sync 实现，调用方经 ``sync_to_async(thread_sensitive=False)`` 包装。

        热路径成本（MJ-05）：聚合覆盖索引 ``idx_repo_last_commit_at``
        （repositories 迁移 0040）+ 进程内短 TTL 缓存（key 含仓集合）——同一批
        候选在 TTL 内只算一次聚合。缓存值是「活跃度信号」这类容忍秒级陈旧的
        数据，过期即重算，无需失效通知。

        rid 来自 Qdrant payload（trust boundary，T-106-14 逐字段容错）：
        repository_id 是 UUIDField，payload 混入非 UUID 值会让 ``__in`` 查询抛
        ValidationError。**逐 rid 先过滤合法 UUID**（MN-01）——脏值只让自身的
        活跃度走枚举回退，不像整体 ``return {}`` 那样让全部候选一起退化；真正的
        DB 故障（OperationalError 等）继续上抛由 route() 整体回退兜底。
        """
        import uuid as _uuid

        from django.core.exceptions import ValidationError
        from django.db.models import Max

        from repositories.models import FileIndex

        if not repository_ids:
            return {}
        valid_ids: list[str] = []
        for rid in repository_ids:
            try:
                _uuid.UUID(str(rid))
            except (ValueError, AttributeError, TypeError):
                continue  # 脏 payload：该仓活跃度走枚举回退，不牵连其他候选
            valid_ids.append(str(rid))
        if not valid_ids:
            return {}

        cache_key = "repo_router_v2:last_commit:" + hashlib.sha256(
            "|".join(sorted(valid_ids)).encode("utf-8")
        ).hexdigest()
        try:
            cached = cache.get(cache_key)
            if isinstance(cached, dict):
                return cached
        except Exception:  # noqa: BLE001 — 缓存 best-effort，异常吞掉走直算
            pass

        try:
            rows = list(
                FileIndex.objects.filter(repository_id__in=valid_ids)
                .values("repository_id")
                .annotate(latest=Max("last_commit_authored_at"))
            )
        except (ValidationError, ValueError):
            return {}
        latest_by_repo = {
            str(row["repository_id"]): (row["latest"].isoformat() if row["latest"] else None)
            for row in rows
        }
        try:
            cache.set(cache_key, latest_by_repo, timeout=_LAST_COMMIT_CACHE_TTL_SECONDS)
        except Exception:  # noqa: BLE001 — 写失败不反噬，下次重算
            pass
        return latest_by_repo

    @classmethod
    async def _load_repo_meta(
        cls,
        node_hits: list[dict[str, Any]],
        query: str,
        query_dense: list[float] | None,
        config: dict[str, Any],
        *,
        probe_vectors: list[list[float]] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        """Stage 0 repo_meta 组装（resolver 编排——六信号的全部 I/O 收口点）。

        对 node_hits 分桶后的**全部**候选仓组装元数据（打分发生在 top_k 截断
        之前）；输出键契约 == ``repo_router_scoring`` 模块 docstring 的
        ``repo_meta`` 权威定义。I/O 预算：+1 次 Qdrant dense-only 查询 +
        1 次 FileIndex 聚合 DB 查询 + 快照/词典缓存读取，无 N+1。

        逐信号降级分支（任一失败路由不失败）：
        - dense 查询异常/空/query_dense 缺失 → 全仓 ``dense_cos_max=None``
          （S_top 回退 RRF s_hat，Pitfall 6）+ warning；
        - N_r 快照缺失 → ``n_bar=None``（breadth denom=1.0 降级）+ warning；
        - embedding 未配置/配置读取失败 → T2 matcher 不构造，facet 全走 T1。

        Returns:
            ``(repo_meta, meta_stats)``——meta_stats 供观测与快照组装：
            ``{"n_bar", "alias_dict_hash", "embedding_model_id", "repo_count",
            "dense_hit_ratio", "t2_used"}``。
        """
        meta_started = time.monotonic()
        buckets = cls._aggregate_by_repo(node_hits)
        rids = sorted(buckets)

        # ---- dense 余弦（O-3 口径）：复用已算好的探针向量，归仓取 max ----
        # 长查询切成 N 块时**必须用全部探针**：dense_cos_max 的语义是「该仓与需求
        # 任一部分的最佳匹配度」。只用首块会让相关内容在后段的仓 S_top 被系统性
        # 压低（实测 study-course 因此 text 信号落后 0.23，挤不进候选池）。
        # 单探针时 dense_search_multi_by_name 逐字委托单向量实现，调用计数不变。
        dense_probes = [v for v in (probe_vectors or []) if v] or (
            [query_dense] if query_dense else []
        )
        cos_by_repo: dict[str, float] = {}
        if dense_probes and rids:
            try:
                dense_hits = await sync_to_async(
                    QdrantService.dense_search_multi_by_name, thread_sensitive=False
                )(
                    COLLECTION_NAME,
                    dense_probes,
                    top_k=STAGE0_DENSE_K,
                    # 与 hybrid 同款 repository_id 过滤构造，限定到分桶候选仓——
                    # 余弦是 query·point 逐点值，不受候选集缩小影响，且提升
                    # 候选仓在 top-50 内的覆盖（减少 Pitfall 6 回退面）。
                    filters={"repository_id": rids},
                )
            except Exception:  # noqa: BLE001 — 查询失败按 dense 不可用降级
                dense_hits = []
            for hit in dense_hits or []:
                payload = hit.get("payload") or {}
                rid = str(payload.get("repository_id", ""))
                if not rid:
                    continue
                score = float(hit.get("score", 0.0))
                if rid not in cos_by_repo or score > cos_by_repo[rid]:
                    cos_by_repo[rid] = score
        if not cos_by_repo:
            # 异常/空结果/query_dense 缺失同路径：全仓 S_top 回退 RRF s_hat。
            try:
                logger.warning(
                    "repo_router_dense_search_failed",
                    repo_count=len(rids),
                    has_query_dense=bool(dense_probes),
                    probe_count=len(dense_probes),
                    category="sampling",
                    component="repo_router_v2",
                )
            except Exception:  # noqa: BLE001
                pass

        # ---- last_commit：一次聚合（免 N+1）----
        latest_by_repo = await sync_to_async(cls._load_latest_commits, thread_sensitive=False)(rids)

        # ---- N_r / N̄ 快照（106-04 --write-snapshot 供数）----
        nr_snapshot = await aload_nr_snapshot()
        n_bar = nr_snapshot.get("n_bar")
        n_r_by_repo = nr_snapshot.get("n_r_by_repo") or {}
        if n_bar is None:
            # 每次路由至多一条（本方法每路由恰调一次）；breadth 走 denom=1.0 降级。
            try:
                logger.warning(
                    "repo_router_nr_snapshot_missing",
                    repo_count=len(rids),
                    category="sampling",
                    component="repo_router_v2",
                )
            except Exception:  # noqa: BLE001
                pass

        # ---- facet_scores（T1 别名词典 + T2 校准余弦，106-03 resolver）----
        alias_dict, alias_hash = await aload_alias_dict()
        constants = config.get("constants") or {}
        t2_matcher: FacetT2Matcher | None = None
        embedding_model_id: str | None = None
        try:
            emb_config = await EmbeddingService.get_config()
            embedding_model_id = emb_config.get("model")
            if emb_config.get("api_url") and query_dense:
                t2_matcher = FacetT2Matcher(
                    model_id=str(embedding_model_id or "unknown"),
                    t2_c_lo=constants.get("t2_c_lo"),
                    t2_c_hi=constants.get("t2_c_hi"),
                    # 单次路由的 embedding 次数硬上限（MJ-06）：超限静默降级 T1-only
                    embed_budget=STAGE0_T2_EMBED_BUDGET,
                )
        except Exception:  # noqa: BLE001 — embedding 未配置/读取失败 → 全走 T1
            t2_matcher = None

        # ---- T2 冷启动批量预热（MJ-06）----
        # 逐仓逐值走 match() 会在缓存冷启动时串行发「候选仓数 × facet 分量数」次
        # embedding（进程重启 / cache 驱逐 / 换模型都会触发），几十次串行 HTTP 全
        # 落在 Stage 0。先把本次全部待匹配的 facet 值收齐批量预热一次，随后逐值
        # 只读缓存。best-effort：预热失败不阻塞（T2 自然降级 T1-only）。
        if t2_matcher is not None:
            await warm_facet_vectors(cls._collect_t2_facet_values(buckets, rids), t2_matcher)

        repo_meta: dict[str, dict[str, Any]] = {}
        t2_used = False
        for rid in rids:
            top_payload = buckets[rid][0].get("payload") or {}
            facets = cls._parse_json_field(top_payload.get("facets"), {})
            facet_scores = await resolve_facet_scores(
                query,
                facets,
                alias_dict=alias_dict,
                constants=config,
                query_embedding=query_dense,
                t2_matcher=t2_matcher,
            )
            if any(
                isinstance(entry, dict) and entry.get("layer") == LAYER_T2
                for entry in facet_scores.values()
            ):
                t2_used = True
            crit_raw = facets.get(FACET_CRITICALITY)
            repo_meta[rid] = {
                "n_r": n_r_by_repo.get(rid),
                "last_commit_at": latest_by_repo.get(rid),
                "dense_cos_max": cos_by_repo.get(rid),
                "facet_scores": facet_scores,
                "criticality_value": crit_raw if isinstance(crit_raw, str) else None,
            }

        # BL-01：本次查询的 S_top 口径（per-query 单一标尺）——与 scorer 调同一
        # 纯函数、同一输入，两处恒等；进 meta_stats → 快照 stage0 + 观测事件，
        # 回放/审计据此区分「本次用的是校准余弦还是 RRF」。
        s_top_source = resolve_s_top_source(rids, repo_meta)

        meta_stats: dict[str, Any] = {
            "n_bar": n_bar,
            "alias_dict_hash": alias_hash,
            "embedding_model_id": embedding_model_id,
            "repo_count": len(rids),
            "dense_hit_ratio": (len(cos_by_repo) / len(rids)) if rids else 0.0,
            "t2_used": t2_used,
            "s_top_source": s_top_source,
        }
        try:
            logger.debug(
                "repo_router_meta_resolved",
                repo_count=len(rids),
                dense_hit_ratio=round(meta_stats["dense_hit_ratio"], 4),
                s_top_source=s_top_source,
                t2_used=t2_used,
                duration_ms=int((time.monotonic() - meta_started) * 1000),
                category="sampling",
                component="repo_router_v2",
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
            pass
        return repo_meta, meta_stats

    @classmethod
    def _collect_t2_facet_values(
        cls,
        buckets: dict[str, list[dict[str, Any]]],
        rids: list[str],
    ) -> list[str]:
        """收集本次路由**可能走 T2** 的全部 facet 值（批量预热输入，MJ-06）。

        只含 domain / stack 两维（team 恒 T1-only）；技术栈按 "/" 拆分逐值，
        与 resolver 的匹配粒度一致。去重与无效值过滤由 warm_facet_vectors 负责。
        """
        values: list[str] = []
        for rid in rids:
            hits = buckets.get(rid) or []
            if not hits:
                continue
            facets = cls._parse_json_field((hits[0].get("payload") or {}).get("facets"), {})
            if not isinstance(facets, dict):
                continue
            domain = facets.get(FACET_DOMAIN)
            if isinstance(domain, str):
                values.append(domain)
            stack = facets.get(FACET_STACK)
            if isinstance(stack, str):
                values.extend(part.strip() for part in stack.split("/"))
        return values

    @classmethod
    def _stage0_candidates(
        cls,
        node_hits: list[dict[str, Any]],
        *,
        top_k: int,
        weights: dict[str, float] | None = None,
        repo_meta: dict[str, dict[str, Any]] | None = None,
        constants: dict[str, Any] | None = None,
        criticality_anchors: dict[str, float] | None = None,
        now: str | None = None,
        diversify_breadth: bool = False,
    ) -> list[dict[str, Any]]:
        """Stage 0 聚合打分薄封装——调纯函数打分核心（105-01 / 106-01）。

        分桶/归一/信号加性合成/稳定排序全部在 ``aggregate_and_score`` 内完成；
        本方法只把 ``ScoredCandidate`` 转回既有 dict 形状（repo_id/repo_name/
        score/facets/hits + breakdown + criticality），再经
        :func:`select_stage0_pool` 截取 top_k。

        ``repo_meta=None``（默认，兼容既有直调方：replay 测试等）→ 打分核心
        走 legacy 三信号路径；106-06 起 ``route()`` 注入六信号新路径参数。

        ``diversify_breadth``：多探针时由 ``route()`` 打开，纠偏 breadth 膨胀
        （见 ``select_stage0_pool``）；单探针 / 直调方保持默认 False，不改
        golden/replay 契约。
        """
        scored = aggregate_and_score(
            node_hits,
            weights=weights,
            repo_meta=repo_meta,
            constants=constants,
            criticality_anchors=criticality_anchors,
            now=now,
        )
        selected = select_stage0_pool(
            scored, top_k, diversify_breadth=diversify_breadth
        )
        return [
            {
                "repo_id": c.repo_id,
                "repo_name": c.repo_name,
                "score": c.score,
                "breakdown": c.breakdown,
                "facets": c.facets,
                "hits": c.hits,
                "criticality": c.criticality,
            }
            for c in selected
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
                    criticality=c.get("criticality"),
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
        *,
        stage1_meta: dict[str, Any] | None = None,
        exc_type_name: str | None = None,
        status_code: int | None = None,
        grouping_repository_ids: list[str] | None = None,
        delta: float = 0.0,
        weight_config: dict[str, Any] | None = None,
        repo_meta: dict[str, Any] | None = None,
        scored_at: str | None = None,
        s_top_source: str | None = None,
    ) -> RepoRouteResultV2:
        """Stage 1 未参与（use_llm=False / 失联降级）的统一出口。

        与 v2 路径语义一致：首位确定性 confidence == high → auto_selected=True，
        margin 达标时编排照常自动推进；``degraded=True`` 标记 Stage 1 未参与。
        ``stage1_meta`` 记录未参与原因（``{"skipped_reason": ...}``）进 snapshot。
        ``weight_config/repo_meta/scored_at`` 按需透传 ``_build_snapshot``
        （v2_stage0_only 降级路径与 v2 路径共用 Stage 0 打分材料）。
        ``grouping_repository_ids/delta`` 带默认值：既有直调方与测试替身照旧可用
        （无分组上下文 → 全部 global）。``exc_type_name`` / ``status_code`` 只吃**异常
        类型名与数值状态码**（不吃实例/消息，脱敏边界），用于区分 ``timeout`` 与
        ``upstream_error``；状态码优先，因为 SDK 抛的是 ``APIStatusError`` 的具体子类。
        """
        # 内部 skipped_reason 保持原字符串不变（快照/排障口径不破），另映射为面向
        # 用户的 6 值闭集枚举；两者同时进快照 stage1 节便于交叉核对。
        degrade_reason = classify_degrade_reason(
            str((stage1_meta or {}).get("skipped_reason", "")),
            exc_type_name=exc_type_name,
            status_code=status_code,
        )
        if stage1_meta is not None:
            stage1_meta = {**stage1_meta, "degrade_reason": degrade_reason}
        # 先按全部 Stage 0 候选定稿再交呈现层截断：分组启用时要按组各取 top_k，
        # 提前截到 top_k 会让 global 组几乎恒空。confidence 推导只依赖候选在
        # Stage 0 分数序列里的位次，与此处截断上限无关（口径不变）。
        finalized = cls._finalize_stage0(stage0_candidates, len(stage0_candidates))
        finalized, block_order = _apply_presentation(
            finalized,
            grouping_repository_ids=grouping_repository_ids,
            delta=delta,
            top_k=top_k,
        )
        result = RepoRouteResultV2(
            candidates=finalized,
            router_version="v2_stage0_only",
            auto_selected=bool(finalized) and finalized[0].confidence == "high",
            degraded=True,
            snapshot=cls._build_snapshot(
                query,
                node_hits,
                finalized,
                stage1_meta=stage1_meta,
                block_order=block_order,
                weight_config=weight_config,
                repo_meta=repo_meta,
                scored_at=scored_at,
                s_top_source=s_top_source,
            ),
            block_order=block_order,
            degrade_reason=degrade_reason,
        )
        cls._log_scored(result, started)
        return result

    @staticmethod
    def _index_version(built_at_by_repo: dict[str, str]) -> str:
        """索引版本口径：参与候选各仓 ``built_at`` 按 repo_id 排序拼接的 sha256。

        重索引（``RepoIndexTreeBuilder.build``）刷新 built_at → 版本变化；
        同时用于 snapshot.versions 与 Stage 1 缓存 key（key 变化 = 旧缓存自然失效）。
        """
        material = "|".join(
            f"{rid}:{built_at_by_repo[rid]}" for rid in sorted(built_at_by_repo)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @classmethod
    def _build_snapshot(
        cls,
        query: str,
        node_hits: list[dict[str, Any]],
        candidates: list[RepoRouteCandidateV2],
        *,
        stage1_meta: dict[str, Any] | None = None,
        block_order: list[str] | None = None,
        weight_config: dict[str, Any] | None = None,
        repo_meta: dict[str, Any] | None = None,
        scored_at: str | None = None,
        s_top_source: str | None = None,
    ) -> dict[str, Any]:
        """组装快照材料（ROUTE-09 数据底座；落 ConvergenceSessionEvent 由 105-07 处理）。

        node_hits 只存重算所需最小字段集（禁存全量 payload——防 payload 无界
        膨胀）。``stage1_meta``：成功路径为脱敏 prompt/response + model_id +
        prompt_hash + cache_hit（与 weight_set_version/index_version 合成版本
        绑定四元组）；失联/降级路径为 ``{"skipped_reason": ...}``。

        Phase 106 扩展（106-07 replay 的输入契约）：
        - ``weight_config``：本次生效的权重/常数**全值**（含生效 n_bar）+
          weight_set_version + alias_dict_hash + embedding_model_id——回放
          不依赖当时的 SystemSetting；缺省（legacy 打分路径）不写该节。
        - ``repo_meta``：**全部分桶仓**的元数据（BL-02 自包含性——回放按全量
          node_hits 重算，缺 meta 的仓分数会虚高并污染比对窗口）；T2 余弦与
          DB 聚合离线不可重算，以数据形式记录。体积护栏落在 node_hits 上。
        - ``stage0.scored_at``：打分时间锚点（活跃度衰减重算用）。
        - ``stage0.s_top_source``：本次 S_top 采用的口径（校准余弦 / RRF
          s_hat，per-query 单一标尺，BL-01）——回放与 golden 据此区分口径。
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
        stage1 = stage1_meta or {"skipped_reason": "not_run"}
        # index_version 单一口径（MN-02）：Stage 1 参与时复用其缓存 key 用的
        # index_version（按喂给 LLM 的候选仓集合计算）——versions 记录的值与
        # 参与缓存 key 的值恒等，回放门禁/缓存审计可直接交叉比对；Stage 1 未
        # 参与（无该值）时按最终候选仓集合计算。
        #
        # weight_set_version 一律来自 config loader 传入的生效配置（106-06 起
        # 105 版本四元组占位换真）；weight_config 缺省（legacy 打分回退 / 兼容
        # 直调方）时回退 DEFAULT_WEIGHT_CONFIG 的版本号。
        versions: dict[str, Any] = {
            "weight_set_version": (weight_config or {}).get("weight_set_version")
            or DEFAULT_WEIGHT_CONFIG["weight_set_version"],
            "index_version": stage1.get("index_version")
            or cls._index_version(built_at_by_repo),
        }
        # 版本绑定四元组补齐（Stage 1 参与时）：weight_set_version + index_version
        # + prompt_hash + model_id。
        if stage1.get("prompt_hash"):
            versions["prompt_hash"] = stage1["prompt_hash"]
        if stage1.get("model_id"):
            versions["model_id"] = stage1["model_id"]
        stage0: dict[str, Any] = {"query": query, "node_hits": minimal_hits}
        if scored_at is not None:
            stage0["scored_at"] = scored_at
        if s_top_source is not None:
            stage0["s_top_source"] = s_top_source
        snapshot: dict[str, Any] = {
            "stage0": stage0,
            "stage1": stage1,
            # candidates 节自动带上呈现字段（group/trust/cross_group_note/
            # score_ranked 已在 to_dict 内）；block_order 另记一键便于回放比对。
            "candidates": [c.to_dict() for c in candidates],
            "versions": versions,
        }
        if block_order is not None:
            snapshot["block_order"] = block_order
        if weight_config is not None:
            snapshot["weight_config"] = weight_config
        if repo_meta is not None:
            snapshot["repo_meta"] = repo_meta
        return snapshot

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
                auto_selected=result.auto_selected,
                # 「本该自动推进却被 α 静默拦下」必须与「本来就不该自动推进」可区分。
                auto_selected_suppressed_by_alpha=result.auto_selected_suppressed_by_alpha,
                weight_set_version=(result.snapshot.get("versions") or {}).get(
                    "weight_set_version"
                ),
                duration_ms=int((time.monotonic() - started) * 1000),
                category="sampling",
                component="repo_router_v2",
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬业务
            pass

    # ------------------------------------------------------------------
    # Stage 1
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_json(obj: Any) -> str:
        """规范化 JSON 序列化（缓存 key 材料用）：键排序 + 紧凑分隔符 + 保留非 ASCII。"""
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def _stage1_cache_key(
        cls,
        model_id: str,
        stage0_input: dict[str, Any],
        decode_params: dict[str, Any],
        index_version: str,
    ) -> str:
        """Stage 1 输入哈希缓存 key（ROUTE-09 幂等三件套之一）。

        key = sha256(model_id ‖ PROMPT_TEMPLATE_VERSION ‖ canonical_json(stage0_input)
        ‖ canonical_json(decode_params) ‖ index_version)——任一维度变化（换模型 /
        改 prompt 模板 / 输入不同 / decode 参数变 / 重索引）key 即不同，旧缓存自然
        失效，无需主动清理（TTL 仅兜底防无界增长）。
        """
        key_material = "\x1f".join(
            [
                model_id,
                PROMPT_TEMPLATE_VERSION,
                cls._canonical_json(stage0_input),
                cls._canonical_json(decode_params),
                index_version,
            ]
        )
        digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
        return f"repo_router_v2:stage1:{digest}"

    @classmethod
    async def _stage1_llm_reasoning(
        cls,
        query: str,
        stage0_candidates: list[dict[str, Any]],
        repo_buckets: dict[str, list[dict[str, Any]]],
        top_k: int,
    ) -> tuple[list[RepoRouteCandidateV2] | None, dict[str, Any]]:
        """Stage 1 LLM 树推理（返回 ``(candidates, stage1_meta)``）。

        stage1_meta 为 snapshot 的 stage1 材料：成功路径含脱敏 prompt/response +
        model_id + prompt_hash + cache_hit；跳过路径为 ``{"skipped_reason": ...}``。
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.llm_factory import build_chat_model
        from interactions.ledger import parse_upstream_status
        from interactions.redaction import redact_for_ledger
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
            return None, {"skipped_reason": "provider_missing"}

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
            return None, {"skipped_reason": "no_model_configured"}

        # ModelUsageRecord 的 provider 维度（口径与两个 Runner 的埋点一致）。
        provider_name = str(resolved.provider_type)

        # 六个配置项统一走 fail-safe 读取（T-107-05）：任一项写成非数值都不得让路由抛，
        # 否则异常被 route() 的兜底 except 吃掉 → 每次路由静默降级且原因报 unknown。
        timeout_seconds = _stage1_seconds("REPO_ROUTER_STAGE1_TIMEOUT_SECONDS")
        # 首调与重试**共享**的总延迟上界 + 退避基数（107-01 落的两个 settings 键）。
        total_budget_seconds = _stage1_seconds("REPO_ROUTER_STAGE1_TOTAL_BUDGET_SECONDS")
        backoff_base_seconds = _stage1_seconds("REPO_ROUTER_STAGE1_RETRY_BACKOFF_SECONDS")
        max_candidates = _stage1_int("REPO_ROUTER_STAGE1_MAX_CANDIDATES")
        hits_per_repo = _stage1_int("REPO_ROUTER_STAGE1_HITS_PER_REPO")
        cache_ttl = _stage1_int("REPO_ROUTER_STAGE1_CACHE_TTL_SECONDS")

        # 快速失败即降级：max_retries=0 —— 路由是启发式，超时无需 3× 重试空等
        # （旧行为：langchain 默认 max_retries=2 → 30s×3≈90s 才放弃再回落 Stage 0）。
        # decode 参数全固定（temperature=0/top_p=1/固定 seed）——幂等第三道防线。
        def _build_stage1_model(*, with_decode_params: bool) -> Any:
            """构造 Stage 1 模型；``with_decode_params=False`` 用于上游拒收 decode 参数后重建。"""
            decode = (
                {
                    "temperature": float(_STAGE1_DECODE_PARAMS["temperature"]),
                    "top_p": float(_STAGE1_DECODE_PARAMS["top_p"]),
                    "seed": int(_STAGE1_DECODE_PARAMS["seed"]),
                }
                if with_decode_params
                else {}
            )
            return build_chat_model(
                resolved,
                model_name,
                streaming=False,
                timeout_seconds=timeout_seconds,
                max_retries=0,
                **decode,
            )

        model = _build_stage1_model(with_decode_params=True)

        # 只把高分候选喂给 LLM：prompt 越短越快，尾部低分候选本就选不中；
        # Stage 0 仍保留完整候选集供降级时使用。
        stage0_candidates = stage0_candidates[:max_candidates]

        # stage0_input：喂给 LLM 的候选材料的结构化源（context_blocks 由此渲染）。
        # 含 query——同候选不同需求文本是不同输入，缓存 key 必须区分。
        # 含 output_cap——system prompt 的动态插值「最多输出 max(top_k,3) 项」
        # 也是 LLM 输入的一部分：不同 top_k 渲染出不同 prompt，是不同输入，
        # 必须并入 key 材料，否则跨 top_k 请求缓存碰撞（105 评审 MJ-02）。
        output_cap = max(top_k, 3)
        # prompt 侧独立截断：检索已用全量语料（多探针）跑完，这里只约束喂给 LLM 的
        # 正文长度。截断后的值同时进 stage0_input——缓存 key 必须与实际发出的
        # prompt 一致，否则「同一 prompt 命中不同 key」。
        prompt_query = query[:STAGE1_PROMPT_QUERY_MAX_CHARS]
        stage0_input: dict[str, Any] = {
            "query": prompt_query,
            "candidates": [],
            "output_cap": output_cap,
        }
        context_blocks: list[str] = []
        built_at_by_repo: dict[str, str] = {}
        for idx, c in enumerate(stage0_candidates, 1):
            lines = [f"### 候选 {idx}: {c['repo_name']} (repo_id={c['repo_id']})"]
            facets = {
                k: v for k, v in (c.get("facets") or {}).items()
                if not k.startswith("_")
            }
            if facets:
                lines.append(f"分面: {json.dumps(facets, ensure_ascii=False)}")
            input_hits: list[dict[str, Any]] = []
            for hit in c["hits"][:hits_per_repo]:
                p = hit.get("payload", {})
                node_path = p.get("node_path", "")
                summary = p.get("summary", "")
                sub = p.get("sub_project", "")
                sub_part = f" [子应用: {sub}]" if sub else ""
                lines.append(f"- {node_path}{sub_part}: {summary}")
                input_hits.append(
                    {
                        "node_path": str(node_path),
                        "summary": str(summary),
                        "sub_project": str(sub),
                    }
                )
            context_blocks.append("\n".join(lines))
            stage0_input["candidates"].append(
                {"repo_id": c["repo_id"], "facets": facets, "hits": input_hits}
            )
            first_payload = (c["hits"][0].get("payload") or {}) if c["hits"] else {}
            built_at_by_repo[str(c["repo_id"])] = str(first_payload.get("built_at", ""))

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
                "- 按相关度降序排列输出，数组顺序即你的排序结论；"
                "不要输出任何数值分数字段（如 score / 浮点分值）——排序只用数组顺序表达\n"
                "- 最多输出 " + str(output_cap) + " 项，无关候选不要输出\n"
                "- 只有当需求明确指向唯一仓库时首位才给 high\n"
                "- 活跃度=疑似废弃的仓库除非别无选择，否则降级或剔除\n"
                "- repo_id 必须从候选中选取，禁止编造"
            )
        )
        human = HumanMessage(
            content=f"用户需求：{prompt_query}\n\n候选仓库及命中节点：\n\n"
            + "\n\n".join(context_blocks)
        )
        prompt_text = str(system.content) + "\n\n" + str(human.content)
        prompt_hash = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

        # ---- 输入哈希缓存（幂等主防线）：命中则零 LLM 调用直接复用排列 ----
        index_version = cls._index_version(built_at_by_repo)
        cache_key = cls._stage1_cache_key(
            model_name, stage0_input, dict(_STAGE1_DECODE_PARAMS), index_version
        )
        parsed: list[Any] | None = None
        cache_hit = False
        try:
            cached = cache.get(cache_key)
            if isinstance(cached, list) and cached:
                parsed = cached
                cache_hit = True
                logger.debug(
                    "repo_router_v2_stage1_cache_hit",
                    cache_key_prefix=cache_key[:24],
                    category="sampling",
                    component="repo_router_v2",
                )
        except Exception:  # noqa: BLE001 — 缓存 best-effort，异常吞掉走直调
            parsed = None
            cache_hit = False

        response_text = ""
        attempts = 0
        if not cache_hit:
            # 硬性上限：不管客户端/代理如何处理超时，Stage 1 绝不超过配置的超时值。
            # 超时抛 TimeoutError → 上层 route() 捕获后降级 Stage 0（0.2s 出结果），
            # 避免慢模型把整个"仓库分级路由"拖成分钟级。
            # call_source 统一在 router 内部声明作用域——消灭调用方遗漏。
            #
            # 重试写在**我们自己的循环**里（`range(2)` = 首调 + 1 次重试，硬上界）：
            # 只有这样重试才受 budget_deadline 约束。langchain 内部重试**不受**该
            # 约束（旧病：30s×3≈90s 才放弃），故上面构造模型时保持其关闭。
            started = time.monotonic()
            # 首调与重试共享同一截止时刻——循环外取一次，预算耗尽即刻降级。
            budget_deadline = started + total_budget_seconds
            response: Any = None
            # 上游拒收 decode 参数后已重建过模型：只允许降级一次，避免与普通重试
            # 共用预算时出现「丢参数 → 再丢一次」的空转。
            decode_params_dropped = False
            for attempt in range(2):
                remaining = budget_deadline - time.monotonic()
                if remaining <= 0:
                    try:
                        logger.info(
                            "repo_router_v2_stage1_budget_exhausted",
                            attempt=attempt,
                            attempts=attempts,
                            total_budget_seconds=total_budget_seconds,
                            category="sampling",
                            component="repo_router_v2",
                        )
                    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬
                        pass
                    raise TimeoutError("stage1_budget_exhausted")
                attempts += 1
                attempt_started = time.monotonic()
                try:
                    with use_call_source(CallSource.AUX_REPO_ROUTER):
                        response = await asyncio.wait_for(
                            model.ainvoke([system, human]),
                            # per-attempt 超时取二者较小值：不存在「首调吃满
                            # per-call 后重试无余量」的结构。
                            timeout=min(timeout_seconds, remaining),
                        )
                except Exception as exc:  # noqa: BLE001 — 分类后决定重试还是上抛
                    # 只取数值上游码，绝不取响应体；分类与重试判定共用同一个码。
                    upstream_status = parse_upstream_status(exc)
                    await _record_stage1_usage(
                        provider=provider_name,
                        model=model_name,
                        duration_ms=int((time.monotonic() - attempt_started) * 1000),
                        # 短标签枚举而非异常消息（T-107-02：failure_type 不吃自由文本）。
                        failure_type=classify_degrade_reason(
                            "",
                            exc_type_name=type(exc).__name__,
                            status_code=upstream_status,
                        ),
                        upstream_status_code=upstream_status,
                    )
                    # decode 参数被拒：这是**可自愈**的 400——丢掉固定 decode 参数重建
                    # 模型重试一次。幂等主防线是输入哈希缓存 + 排列输出，decode 固定只是
                    # 第三道防线（105-RESEARCH），丢掉它远好过整个 Stage 1 静默降级。
                    # 限定首次尝试：末轮 `continue` 会让循环耗尽而 response 仍为 None，
                    # 后续 `response.content` 直接 AttributeError。
                    if (
                        attempt == 0
                        and not decode_params_dropped
                        and _is_decode_param_rejection(exc)
                    ):
                        decode_params_dropped = True
                        model = _build_stage1_model(with_decode_params=False)
                        try:
                            logger.warning(
                                "repo_router_v2_stage1_decode_params_dropped",
                                model=model_name,
                                error=redact_secrets_in_text(str(exc))[:200],
                                category="sampling",
                                component="repo_router_v2",
                            )
                        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬
                            pass
                        continue
                    if attempt == 1 or not _is_retryable_stage1_error(exc):
                        raise
                    try:
                        logger.info(
                            "repo_router_v2_stage1_retry",
                            attempt=attempt,
                            error_type=type(exc).__name__,
                            error=redact_secrets_in_text(str(exc))[:200],
                            remaining_seconds=round(budget_deadline - time.monotonic(), 3),
                            category="sampling",
                            component="repo_router_v2",
                        )
                    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬
                        pass
                    # 退避睡眠同样受总预算封顶：绝不睡到预算之外去。
                    await asyncio.sleep(
                        min(
                            backoff_base_seconds,
                            max(0.0, budget_deadline - time.monotonic()),
                        )
                    )
                    continue
                await _record_stage1_usage(
                    provider=provider_name,
                    model=model_name,
                    duration_ms=int((time.monotonic() - attempt_started) * 1000),
                    usage=_stage1_usage_metadata(response),
                )
                break
            from agents.llm_factory import content_to_text

            response_text = content_to_text(response.content)
            parsed = cls._parse_llm_json_array(response_text)
            # 防模型不遵指令引入浮点分数：排列输出模式下过滤各项的 "score" 键
            # （候选分数一律来自 Stage 0 归一化分，LLM 数值不采信）。
            if parsed:
                parsed = [
                    {k: v for k, v in item.items() if k != "score"}
                    if isinstance(item, dict)
                    else item
                    for item in parsed
                ]
            logger.info(
                "repo_router_v2_stage1_completed",
                model=model_name,
                candidate_count=len(stage0_candidates),
                parsed_count=len(parsed or []),
                attempts=attempts,
                duration_ms=int((time.monotonic() - started) * 1000),
                category="sampling",
                component="repo_router_v2",
            )
            if parsed:
                try:
                    cache.set(cache_key, parsed, timeout=cache_ttl)
                except Exception:  # noqa: BLE001 — 缓存写失败不反噬路由
                    pass
        if not parsed:
            logger.warning(
                "repo_router_v2_stage1_skipped",
                reason="unparsable_llm_output",
                model=model_name,
                category="sampling",
                component="repo_router_v2",
            )
            return None, {"skipped_reason": "unparsable_llm_output"}

        by_id = {c["repo_id"]: c for c in stage0_candidates}
        rank_by_id = {c["repo_id"]: i for i, c in enumerate(stage0_candidates)}
        # confidence 的输入恒为 **Stage 0 分数列表**，绝不换成凸组合后的旁路分：
        # 一旦改吃旁路分，LLM 就经 α 重新变成置信度的决策者，直接回退 RELY-04
        # （Phase 105 刚修完的编排死锁根因）。LLM 只保留「只降不升」这一条影响力。
        sorted_scores = [float(c["score"]) for c in stage0_candidates]
        candidates: list[RepoRouteCandidateV2] = []
        # 消费时对 repo_id 去重（首见保留）：prompt 未禁重复，模型偶发不遵指令
        # 输出同仓两次会透传到 trace/快照/前端 v-for key，且被输入哈希缓存固化
        # 24h 放大——缓存存 parsed 原文，消费统一去重即对两条路径同时生效（MN-01）。
        seen: set[str] = set()
        for item in parsed:
            if not isinstance(item, dict):
                continue
            rid = str(item.get("repo_id", ""))
            base = by_id.get(rid)
            if base is None or rid in seen:
                continue  # LLM 编造的 repo_id 或重复项直接丢弃
            seen.add(rid)
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
                    criticality=base.get("criticality"),
                )
            )
        if not candidates:
            return None, {"skipped_reason": "no_valid_candidates_in_llm_output"}

        # ---- 有界重排（RELY-05）：K 裁剪 → 凸组合 → 只写旁路字段 ----
        # 落点刻意在 parsed 消费循环之后：白名单过滤、去重与 apply_llm_adjustment
        # 都已完成，此时 candidates 恰为「LLM 返回的合法子集」。
        _delta, alpha, budget_k = _ranking_conf()
        stage0_order = [str(c["repo_id"]) for c in stage0_candidates]
        llm_order = [c.repo_id for c in candidates]
        # 原样传**全量** stage0_order：base rank 的「被返回子集内相对位次」语义由
        # clamp_llm_permutation 内部负责。调用侧既不得自己拿子集下标去减全量下标
        # （LLM 只返回窗口末几位是常态，两个下标域相减会让位移恒大于预算，重排被
        # 整体丢弃），也不得按全量 stage0_order 把裁剪产物补齐（会引入没有对应
        # 候选的 repo_id）。
        clamped_order, rank_budget_violations = clamp_llm_permutation(
            llm_order, stage0_order, k=budget_k
        )
        # 裁剪产物就是返回顺序——不写回去的话 K 预算只是快照里的一行装饰，
        # 无分组上下文的调用方（_apply_presentation 此时只截断不重排）拿到的
        # 仍是 LLM 的无界排列。
        by_rid = {c.repo_id: c for c in candidates}
        candidates = [by_rid[rid] for rid in clamped_order if rid in by_rid]
        ranked = blend_ranked_scores(
            {c.repo_id: c.score for c in candidates}, clamped_order, alpha=alpha
        )
        for cand in candidates:
            # D-3 硬约束：凸组合结果**只**进旁路字段。α·S_llm 不是任何信号的贡献，
            # 写进主分或分解表会让「分数分解」变成假的，并同时打断三处硬证据——
            # test_repo_router_v2_meta.py:248/:462 的两条 fsum 恒等断言、
            # RoutingDecisionPanel.vue 的 1e-6 容差校验、ROUTE-07 的 INV-R3 承诺。
            cand.score_ranked = ranked.get(cand.repo_id)
        if rank_budget_violations > 0:
            try:
                logger.info(
                    "repo_router_v2_stage1_rank_budget_clamped",
                    violations=rank_budget_violations,
                    k=budget_k,
                    llm_returned_count=len(clamped_order),
                    stage0_window_count=len(stage0_order),
                    category="sampling",
                    component="repo_router_v2",
                )
            except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬
                pass
        # snapshot stage1 材料：prompt/response 必经 redact_for_ledger 脱敏
        # （T-105-10 Information Disclosure mitigation）；prompt_hash + model_id
        # 与 versions 的 weight_set_version/index_version 合成版本绑定四元组。
        stage1_meta = {
            "prompt": redact_for_ledger(prompt_text),
            "response": redact_for_ledger(response_text),
            "model_id": model_name,
            "prompt_hash": prompt_hash,
            "cache_hit": cache_hit,
            # 参与缓存 key 的 index_version 随 meta 回传——snapshot.versions 复用
            # 同一值，保证同一次 route 内「index_version」单一口径（MN-02）。
            "index_version": index_version,
            # 实际上游调用次数（缓存命中为 0，正常 1，重试后 2）与本次生效的总预算
            # ——回放/排障自包含：「这次是不是重试过、当时预算是多少」不必查配置。
            "attempts": attempts,
            "total_budget_seconds": total_budget_seconds,
            # 有界重排留痕：K 预算后置条件的**唯一可断言对象**是 clamped_order
            # ——最终扁平列表可能被 _apply_presentation 按旁路分再排一次，那时相对
            # Stage 0 的位移上界是 2K 而非 K。
            "clamped_order": list(clamped_order),
            "rank_budget_violations": rank_budget_violations,
            "rank_budget_k": budget_k,
            "alpha": alpha,
            # 让「丢弃式提升」可观测：base rank 取子集内相对位次后，LLM 靠**少返回
            # 候选**拿到的提升不受 K 约束（极端情形：只返回窗口末位那一个仓，它以
            # 零违规被提到首位），rank_budget_violations 结构上看不到这条路径。
            # 两个计数落进快照后，「返回数远小于窗口数且违规为 0」可事后识别与告警。
            "llm_returned_count": len(clamped_order),
            "stage0_window_count": len(stage0_order),
        }
        return candidates, stage1_meta

    # ------------------------------------------------------------------
    # 降级与工具
    # ------------------------------------------------------------------

    @classmethod
    async def _fallback_v1(
        cls,
        query: str,
        top_k: int,
        *,
        grouping_repository_ids: list[str] | None = None,
        delta: float = 0.0,
    ) -> RepoRouteResultV2:
        """repo_index_nodes 无命中 → 回落 v1 单点摘要路由。

        ``grouping_repository_ids/delta`` 带默认值：既有直调方与测试替身照旧可用。
        """
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
        candidates, block_order = _apply_presentation(
            candidates,
            grouping_repository_ids=grouping_repository_ids,
            delta=delta,
            top_k=top_k,
        )
        degrade_reason = classify_degrade_reason("v1_fallback")
        return RepoRouteResultV2(
            candidates=candidates,
            router_version="v1_fallback",
            auto_selected=False,
            degraded=True,  # Stage 1 未参与（v1 无节点级分数，confidence 保持 low）
            snapshot={
                "stage1": {"skipped_reason": "v1_fallback", "degrade_reason": degrade_reason},
                "block_order": block_order,
            },
            block_order=block_order,
            degrade_reason=degrade_reason,
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


__all__ = [
    "PROMPT_TEMPLATE_VERSION",
    "RepoRouterV2",
    "RepoRouteCandidateV2",
    "RepoRouteResultV2",
]
