"""元数据 resolver（Phase 106-03）——ROUTE-04 三层匹配的信号生产层。

把 ``Repository.facets`` 的原始值解析为 scorer 可消费的 ``facet_scores``
（键契约与 :mod:`codegraph.services.repo_router_scoring` 模块 docstring 的
``repo_meta.facet_scores`` 权威定义严格一致）：

- **T1 确定性别名词典**（本模块纯函数部分）：facet 值 + 人工同义词表；
  canonical/alias 命中 1.0、仅 parent（上位类目）命中 0.6、未命中 None。
  零网络零 DB——golden harness（106-08）可离线 import 确定性复用。
- **T2 校准 embedding 余弦**（async 部分，Task 2 落地）：
  ``clip((cos - t2_c_lo)/(t2_c_hi - t2_c_lo), 0, 1)``；facet 值向量走
  Django cache 缓存（闭集几百条）；embedding 不可用/失败/facet 被
  ``t2_disabled_facets`` 禁用（O-2 放弃条款）时**静默降级 T1-only**，
  绝不阻塞路由。
- **T3 LLM 判定绝不进分数**（CONTEXT 锁定）——只作 Stage 1 解释材料，
  与本模块无关。

别名词典双轨（planner 裁决）：代码常量 ``DEFAULT_ALIAS_DICT`` 起步 +
SystemSetting ``repo_router.alias_dict`` 运维覆盖——106-06 router 层读取
覆盖后经 :func:`merge_alias_dict` 合并，生效词典经 :func:`alias_dict_hash`
进快照（回放可审计词典版本，T-106-08）。

数据实况约束（106-RESEARCH §2，全部有测试锁定）：
- ``业务线/产品线`` 是复合键名（含斜杠）；值 ``"未分类"`` 视为缺失。
- ``技术栈`` 是斜杠拼接单字符串（"Python/Vue/Go"）——split("/") 后逐值
  匹配，按 ``0.8·max + 0.2·second_max`` 聚合，**绝不 sum/mean**
  （尺寸偏置同构重演，CONTEXT 锁定）。
- ``团队归属`` 是开放集条件信号：**只走 T1**；需求未提团队 → 不可用
  （None，进重归一化），不给 0.5。
- ``关键程度``/``活跃度`` 原值不经本模块——router（106-06）直接放进
  ``repo_meta.criticality_value`` / hit payload ``facets``。

模块契约：顶层零 Django import（T1/合并/hash 纯函数可在无 Django 环境
import，不触发 django.setup）；T2 的 Django 依赖（cache / EmbeddingService /
CallSource）全部在函数/方法体内局部 import。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from codegraph.services.repo_router_scoring import (
    SIGNAL_DOMAIN,
    SIGNAL_STACK,
    SIGNAL_TEAM,
)

# ---------------------------------------------------------------------------
# facet 键名常量（全中文实际键名，来源见 106-RESEARCH §2 实况表）
# ---------------------------------------------------------------------------

FACET_DOMAIN = "业务线/产品线"  # 语义分面（summary_service.SEMANTIC_FACET_DIMENSIONS）
FACET_STACK = "技术栈"  # 事实分面（facet_service.DIM_TECH_STACK）
FACET_TEAM = "团队归属"  # 事实分面（facet_service.DIM_TEAM，开放集）
FACET_CRITICALITY = "关键程度"  # 事实分面（facet_service.DIM_CRITICALITY）
FACET_ACTIVITY = "活跃度"  # 事实分面（facet_service.DIM_ACTIVITY）

# 语义分面 LLM 选不出时的填充值——视为缺失，绝不送匹配/embedding（Pitfall 2）。
UNCLASSIFIED_VALUE = "未分类"

# facet 分数来源层标注（进 facet_scores.layer 与快照，可解释性最低要求）。
LAYER_T1 = "t1"
LAYER_T2 = "t2"

# facet 值长度上限：超长直接视为不可匹配（DoS 护栏，T-106-06）。
MAX_FACET_VALUE_LENGTH = 200

# T1 两档分值（ROUTE-04：1.0 精确/别名、0.6 上位类目）。
_T1_MATCH_SCORE = 1.0
_T1_PARENT_SCORE = 0.6

# 技术栈多值聚合系数（CONTEXT 锁定 0.8·max + 0.2·second_max）。
_STACK_MAX_WEIGHT = 0.8
_STACK_SECOND_WEIGHT = 0.2

# ---------------------------------------------------------------------------
# 默认别名词典（代码常量起步；结构 {facet_dim: {canonical: {aliases, parent}}}）
#
# - 技术栈维度：facet_service._EXT_LANGUAGE_MAP 全部语言名 + 常见别名。
# - 活跃度/关键程度维度：枚举骨架（无别名）；关键程度四档全保留（Pitfall 1：
#   facet 自动值只有 核心/重要/边缘 三档，人工 pin 可出现「一般」）。
# - 业务线/产品线、服务对象、技术形态、团队归属：空骨架——生产词表条目
#   deferred（同 O-2 纪律），运维经 SystemSetting repo_router.alias_dict
#   覆盖补充（106-06 读取后 merge_alias_dict 合并）。
# ---------------------------------------------------------------------------

DEFAULT_ALIAS_DICT: dict[str, dict[str, dict[str, Any]]] = {
    FACET_STACK: {
        "Python": {"aliases": ["py", "python3"], "parent": None},
        "Go": {"aliases": ["golang"], "parent": None},
        "TypeScript": {"aliases": ["ts"], "parent": None},
        "JavaScript": {"aliases": ["js"], "parent": None},
        "Vue": {"aliases": ["vue3", "vuejs", "vue.js"], "parent": None},
        "Java": {"aliases": [], "parent": None},
        "Kotlin": {"aliases": ["kt"], "parent": None},
        "Rust": {"aliases": [], "parent": None},
        "Ruby": {"aliases": [], "parent": None},
        "PHP": {"aliases": [], "parent": None},
        "C#": {"aliases": ["csharp"], "parent": None},
        "C++": {"aliases": ["cpp"], "parent": None},
        "C": {"aliases": [], "parent": None},
        "Swift": {"aliases": [], "parent": None},
        "Objective-C": {"aliases": ["objc", "objective c"], "parent": None},
        "Scala": {"aliases": [], "parent": None},
        "SQL": {"aliases": [], "parent": None},
        "Shell": {"aliases": ["bash"], "parent": None},
    },
    FACET_ACTIVITY: {
        "活跃开发": {"aliases": [], "parent": None},
        "维护中": {"aliases": [], "parent": None},
        "低频": {"aliases": [], "parent": None},
        "疑似废弃": {"aliases": [], "parent": None},
    },
    FACET_CRITICALITY: {
        "核心": {"aliases": [], "parent": None},
        "重要": {"aliases": [], "parent": None},
        "一般": {"aliases": [], "parent": None},
        "边缘": {"aliases": [], "parent": None},
    },
    FACET_DOMAIN: {},
    "服务对象": {},
    "技术形态": {},
    FACET_TEAM: {},
}


# ---------------------------------------------------------------------------
# T1 确定性匹配（纯函数）
# ---------------------------------------------------------------------------


def _contains_token(query_cf: str, token_cf: str) -> bool:
    """casefold 后的子串包含匹配。

    中文短语直接 ``in``（零依赖约束，不引分词库）；纯 ASCII token 加
    字母数字词边界——否则 "django" 会误命中 "Go"、"tests" 误命中别名
    "ts" 这类短 token 误报（T1 是确定性层，误报比漏报代价高）。
    """
    if not token_cf:
        return False
    if token_cf.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(token_cf)}(?![a-z0-9])"
        return re.search(pattern, query_cf) is not None
    return token_cf in query_cf


def _lookup_entry(alias_dict: Any, dim: str, value: str) -> dict[str, Any] | None:
    """按维度 + canonical 值查词典条目；键比较大小写不敏感；结构容错。"""
    if not isinstance(alias_dict, dict):
        return None
    entries = alias_dict.get(dim)
    if not isinstance(entries, dict):
        return None
    entry = entries.get(value)
    if isinstance(entry, dict):
        return entry
    value_cf = value.casefold()
    for canonical, candidate in entries.items():
        if (
            isinstance(canonical, str)
            and canonical.casefold() == value_cf
            and isinstance(candidate, dict)
        ):
            return candidate
    return None


def match_t1(
    query_text: str,
    dim: str,
    value: Any,
    alias_dict: dict[str, Any] | None,
) -> float | None:
    """T1 确定性匹配：canonical/alias 命中 1.0、仅 parent 命中 0.6、否则 None。

    纯函数（零 I/O）：canonical 值本身子串命中无需词典条目；别名与上位
    类目取自 ``alias_dict[dim][value]``。超长值（> ``MAX_FACET_VALUE_LENGTH``）
    直接不可匹配（DoS 护栏，T-106-06）。
    """
    if not isinstance(query_text, str) or not query_text:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > MAX_FACET_VALUE_LENGTH:
        return None

    query_cf = query_text.casefold()
    if _contains_token(query_cf, value.casefold()):
        return _T1_MATCH_SCORE

    entry = _lookup_entry(alias_dict, dim, value)
    if entry is None:
        return None
    aliases = entry.get("aliases")
    if isinstance(aliases, (list, tuple)):
        for alias in aliases:
            if isinstance(alias, str) and _contains_token(query_cf, alias.casefold()):
                return _T1_MATCH_SCORE
    parent = entry.get("parent")
    if isinstance(parent, str) and parent and _contains_token(query_cf, parent.casefold()):
        return _T1_PARENT_SCORE
    return None


# ---------------------------------------------------------------------------
# 别名词典覆盖合并 + 快照 hash（纯函数）
# ---------------------------------------------------------------------------


def merge_alias_dict(
    default: dict[str, Any] | None,
    override: dict[str, Any] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """别名词典覆盖合并：override 新增 canonical / 追加 aliases / 覆盖 parent。

    双方均不被原地修改（返回全新结构）。override 来自 SystemSetting
    （运维可注入，T-106-08 trust boundary）：维度/canonical/条目任一处
    不是预期结构一律跳过，绝不抛异常。
    """
    merged: dict[str, dict[str, dict[str, Any]]] = {}
    if isinstance(default, dict):
        for dim, entries in default.items():
            if not isinstance(dim, str) or not isinstance(entries, dict):
                continue
            bucket: dict[str, dict[str, Any]] = {}
            for canonical, entry in entries.items():
                normalized = _normalize_entry(entry)
                if isinstance(canonical, str) and canonical and normalized is not None:
                    bucket[canonical] = normalized
            merged[dim] = bucket
    if isinstance(override, dict):
        for dim, entries in override.items():
            if not isinstance(dim, str) or not isinstance(entries, dict):
                continue
            bucket = merged.setdefault(dim, {})
            for canonical, entry in entries.items():
                if not isinstance(canonical, str) or not canonical or not isinstance(entry, dict):
                    continue
                existing = bucket.get(canonical) or {"aliases": [], "parent": None}
                aliases = entry.get("aliases")
                if isinstance(aliases, (list, tuple)):
                    appended = list(existing["aliases"]) + [
                        a for a in aliases if isinstance(a, str) and a
                    ]
                    existing["aliases"] = list(dict.fromkeys(appended))
                if "parent" in entry:
                    parent = entry.get("parent")
                    existing["parent"] = parent if isinstance(parent, str) and parent else None
                bucket[canonical] = existing
    return merged


def _normalize_entry(entry: Any) -> dict[str, Any] | None:
    """词典条目规范化：{"aliases": [str...], "parent": str|None}；非 dict → None。"""
    if not isinstance(entry, dict):
        return None
    aliases = entry.get("aliases")
    clean_aliases = (
        [a for a in aliases if isinstance(a, str) and a]
        if isinstance(aliases, (list, tuple))
        else []
    )
    parent = entry.get("parent")
    return {
        "aliases": list(dict.fromkeys(clean_aliases)),
        "parent": parent if isinstance(parent, str) and parent else None,
    }


def alias_dict_hash(alias_dict: dict[str, Any] | None) -> str:
    """生效词典 canonical JSON 的 sha256（键排序，键序不同内容相同 → 同 hash）。

    进路由快照，保证回放可审计「当时生效的词典版本」（T-106-08）。
    """
    payload = json.dumps(
        alias_dict if isinstance(alias_dict, dict) else {},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# facet_scores 组装（resolver 主入口，async——T2 通道在 Task 2 落地）
# ---------------------------------------------------------------------------


def _normalize_facet_value(raw: Any) -> str | None:
    """facet 原始值规范化：非 str / 空串 / "未分类" / 超长 → None（缺失）。"""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value or value == UNCLASSIFIED_VALUE:
        return None
    if len(value) > MAX_FACET_VALUE_LENGTH:
        return None
    return value


def _unavailable() -> dict[str, Any]:
    return {"score": None, "layer": None}


async def resolve_facet_scores(
    query_text: str,
    facets: dict[str, Any] | None,
    *,
    alias_dict: dict[str, Any],
    constants: dict[str, Any],
    query_embedding: list[float] | None = None,
    t2_matcher: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """把仓库 facets 解析为 scorer 可消费的 facet_scores（repo_meta 契约）。

    输出（键契约 == repo_meta.facet_scores，scorer 只消费数值）::

        {"domain" | "stack" | "team": {"score": float | None, "layer": "t1" | "t2" | None}}

    - **domain**（``业务线/产品线``）：T1 命中 → 分数 + t1；未命中且 T2 可用
      （t2_matcher 与 query_embedding 均给定、facet 不在 ``t2_disabled_facets``）
      → T2 校准余弦；均不可用 → None。
    - **stack**（``技术栈``）：split("/") 逐值 T1（T2 同理逐值），聚合
      ``0.8·max + 0.2·second_max``（单值时 second_max=0 → 0.8·max）；
      layer 取贡献 max 的那个值的来源层。
    - **team**（``团队归属``）：**只走 T1**（开放集，RESEARCH A3——T2 对
      团队名区分度存疑，禁用）；需求未提团队 → None（条件信号，不给 0.5）。
    - ``关键程度``/``活跃度`` 原值**不在本函数处理**——router（106-06）直接
      放进 repo_meta.criticality_value / hit payload facets（分工见模块 docstring）。

    参数：
    - ``constants``：配置 dict（可传完整 weight_config 或子集）——本函数只读
      ``t2_disabled_facets``（O-2 校准判废弃 T2 的 facet 列表）。
    - ``query_embedding``：调用方已算好的 query dense 向量（零额外 embedding）；
      None → T2 整体不可用，全走 T1。
    - ``t2_matcher``：FacetT2Matcher 实例（Task 2）；None → T1-only。
    """
    facets_map = facets if isinstance(facets, dict) else {}
    disabled_raw = constants.get("t2_disabled_facets") if isinstance(constants, dict) else None
    disabled = (
        {str(item) for item in disabled_raw}
        if isinstance(disabled_raw, (list, tuple, set))
        else set()
    )

    async def _t2_score(signal: str, value: str) -> float | None:
        """T2 通道前置条件收口：matcher/向量可用且 facet 未被校准禁用。"""
        if t2_matcher is None or not query_embedding:
            return None
        if signal in disabled:
            return None
        return await t2_matcher.match(query_embedding, value)

    async def _resolve_single(signal: str, raw: Any, *, allow_t2: bool) -> dict[str, Any]:
        value = _normalize_facet_value(raw)
        if value is None:
            return _unavailable()
        dim = FACET_DOMAIN if signal == SIGNAL_DOMAIN else FACET_TEAM
        t1 = match_t1(query_text, dim, value, alias_dict)
        if t1 is not None:
            return {"score": t1, "layer": LAYER_T1}
        if allow_t2:
            t2 = await _t2_score(signal, value)
            if t2 is not None:
                return {"score": t2, "layer": LAYER_T2}
        return _unavailable()

    async def _resolve_stack(raw: Any) -> dict[str, Any]:
        joined = _normalize_facet_value(raw)
        if joined is None:
            return _unavailable()
        matched: list[tuple[float, str]] = []  # (score, layer)，保持原值顺序
        for part in joined.split("/"):
            part = part.strip()
            if not part:
                continue
            t1 = match_t1(query_text, FACET_STACK, part, alias_dict)
            if t1 is not None:
                matched.append((t1, LAYER_T1))
                continue
            t2 = await _t2_score(SIGNAL_STACK, part)
            if t2 is not None:
                matched.append((t2, LAYER_T2))
        if not matched:
            return _unavailable()
        # 多值聚合只用 max/second_max（绝不 sum/mean——标签多的仓不因堆值
        # 得分更高，尺寸偏置不在元数据侧重演）；单值时 second_max=0 → 0.8·max。
        ordered = sorted((score for score, _ in matched), reverse=True)
        top = ordered[0]
        second = ordered[1] if len(ordered) > 1 else 0.0
        layer = next(layer for score, layer in matched if score == top)
        return {"score": _STACK_MAX_WEIGHT * top + _STACK_SECOND_WEIGHT * second, "layer": layer}

    return {
        SIGNAL_DOMAIN: await _resolve_single(
            SIGNAL_DOMAIN, facets_map.get(FACET_DOMAIN), allow_t2=True
        ),
        SIGNAL_STACK: await _resolve_stack(facets_map.get(FACET_STACK)),
        SIGNAL_TEAM: await _resolve_single(SIGNAL_TEAM, facets_map.get(FACET_TEAM), allow_t2=False),
    }


__all__ = [
    "DEFAULT_ALIAS_DICT",
    "FACET_ACTIVITY",
    "FACET_CRITICALITY",
    "FACET_DOMAIN",
    "FACET_STACK",
    "FACET_TEAM",
    "LAYER_T1",
    "LAYER_T2",
    "MAX_FACET_VALUE_LENGTH",
    "UNCLASSIFIED_VALUE",
    "alias_dict_hash",
    "match_t1",
    "merge_alias_dict",
    "resolve_facet_scores",
]
