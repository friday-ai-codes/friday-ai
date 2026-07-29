"""章程分量（`charter_match`）—— 双面路由的「意图面」打分（CHARTER-02，112-03 Task 1）。

**本模块只算章程分量，不碰 `RepoRouterV2`**（DESIGN §13.2 + §5.7 第 4 条：
`codegraph/services/repo_router_v2.py` 是冻结面，零改动）。能力树是事实面（这个仓
现在有什么），章程是意图面（这个仓**应该**承接什么）——两者在
`blueprint_route.py` 的 adapter 层加权融合，绝不把章程证据塞进路由器内部 prompt。

**读正式字段，证据带 source/version**：`source == "ai_draft"` 的章程内容同样落在正式
字段上（`charter_service.py` 就地更新语义），因此打分无需区分 source；但 breakdown
证据里必须带 `charter_source` / `charter_version`，让 115 前端能标注「本分量依据的是
未经人工确认的草案」（T-112-11）。

**纯函数与 ORM 读严格分离**：`score_charter_match` 入参是已取出的 dict（无 DB、可单
测、可被 golden set 评估）；`aload_charters` / `acollect_charter_candidates` 是
best-effort 的 ORM 读，失败返回空而非上抛——路由不因章程读失败而中断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

__all__ = [
    "score_charter_match",
    "aload_charters",
    "acollect_charter_candidates",
    "CharterMatchResult",
    "DEFAULT_CHARTER_RULES",
]

# 章程三规则的强度基准（分量在加权前的原始量纲，clamp 到 [-1, 1]）。
#
# `owned_planned` 显著为正但低于 `owned_implemented`——这是 greenfield 场景让
# **规划中**领域的仓进候选的机制：能力树里没有节点（router_base=0.0）也能靠
# 「章程写明这块归我、只是还没实现」被召回（高三提分专项的 onion-learning case）。
# `boundary_hit` 取 -1.0：单条禁区命中即可把满分 owned 命中压回 0，语义是
# 「章程明令不承接」应当压倒「能力沾边」，但**只降权不淘汰**（保留候选 +
# 要求显式理由的机制在 `blueprint_route.resolve_boundary_override`）。
DEFAULT_CHARTER_RULES: dict[str, float] = {
    "owned_implemented": 1.0,
    "owned_planned": 0.7,
    "boundary_hit": -1.0,
    "evolution_maintenance_only": -0.4,
    "evolution_deprecated": -0.8,
}

# 正/负分各自的量纲上界（防「章程写得越长分越高」，T-112-11）。
_SCORE_MAX = 1.0
_SCORE_MIN = -1.0

# 命中判定时忽略的分隔符（中英标点 + 空白），规范化为单个空格。
_SEPARATORS = re.compile(r"[\s/\\|、，,。.;；:：()（）\[\]【】<>《》\"'`~!?！？+*&_-]+")

# 参与「片段互为子串」判定的最短片段长度：单字符片段（如 "页"）会把任意长文本
# 命中成假阳性，因此只让 ≥2 字符的片段参与子串判定。
_MIN_SEGMENT_LEN = 2

_VALID_DOMAIN_STATUS = ("implemented", "planned")


@dataclass(frozen=True)
class CharterMatchResult:
    """章程分量结果（分数 + 可解释证据，逐字段进 breakdown 的 `evidence`）。"""

    score: float = 0.0
    matched_domains: list[dict] = field(default_factory=list)
    violated_boundaries: list[str] = field(default_factory=list)
    evolution: str = ""
    penalty_reasons: list[str] = field(default_factory=list)
    charter_source: str = ""
    charter_version: int = 0
    citation_ids: list[str] = field(default_factory=list)


def _normalize(text: Any) -> str:
    """任意输入规范化为「小写 + 分隔符折叠成单空格」的比较用文本。"""
    if text is None:
        return ""
    return _SEPARATORS.sub(" ", str(text)).strip().lower()


def _segments(text: Any) -> list[str]:
    """规范化后按空格切片段（中文按标点/斜杠切，英文按词切）。"""
    normalized = _normalize(text)
    return [seg for seg in normalized.split(" ") if seg]


def _matches(target: Any, query_terms: list[str]) -> bool:
    """章程文本 `target` 是否命中 `query_terms`（大小写无关的片段/子串判定）。

    不引入分词依赖（T-112-SC：零新增外部依赖）：先做整串互为子串判定，再做
    ≥2 字符片段的双向子串判定——中文「培优/学习提分」的 `培优` 片段能命中
    「改造培优课占位入口」这类连写长文本，英文按词切后同样有效。
    """
    norm_target = _normalize(target)
    if not norm_target:
        return False
    target_segments = [seg for seg in norm_target.split(" ") if len(seg) >= _MIN_SEGMENT_LEN]
    for term in query_terms or []:
        norm_term = _normalize(term)
        if not norm_term:
            continue
        if norm_target in norm_term or norm_term in norm_target:
            return True
        if any(seg in norm_term for seg in target_segments):
            return True
        if any(seg in norm_target for seg in norm_term.split(" ") if len(seg) >= _MIN_SEGMENT_LEN):
            return True
    return False


def _clean_citations(value: Any) -> list[str]:
    """citations 白名单：仅接受 list，项强转 str/strip，空项剔除（对齐 normalize_charter_draft）。"""
    if not isinstance(value, list):
        return []
    return [str(c).strip() for c in value if str(c).strip()]


def _resolve_rules(rules: dict | None) -> dict[str, float]:
    """规则表逐键 `float()` 强转 + 缺键回默认（畸形入参绝不抛）。"""
    resolved = dict(DEFAULT_CHARTER_RULES)
    if not isinstance(rules, dict):
        return resolved
    for key, default in DEFAULT_CHARTER_RULES.items():
        if key not in rules:
            continue
        try:
            resolved[key] = float(rules[key])
        except (TypeError, ValueError):
            resolved[key] = default
    return resolved


def score_charter_match(
    charter: dict | None,
    *,
    query_terms: list[str],
    rules: dict | None = None,
) -> CharterMatchResult:
    """章程三规则打分（**纯函数**：入参是已取出的 dict，无 DB、可单测）。

    规则：
      1. `charter` 为 None/空 → `score=0.0` + `penalty_reasons=["no_charter"]`
         （无章程不是负分，只是**无证据**——不能让「没写章程」等价于「章程说别放这」）。
      2. `owned_domains` 命中 → 按 `status` 取 `owned_implemented` / `owned_planned`
         （非法 status 按 `implemented` 处理，与 `normalize_charter_draft` 回退一致）。
      3. `boundaries.rule` 命中 → 加 `boundary_hit`（负值）并记 `violated_boundaries`。
      4. `evolution == maintenance_only|deprecated` → 加对应负值并记 `penalty_reasons`。
      5. 正分累加后 clamp 到 1.0、总分 clamp 到 [-1, 1]（防「章程写越长分越高」）。
    """
    resolved_rules = _resolve_rules(rules)
    terms = [t for t in (query_terms or []) if str(t).strip()]

    if not isinstance(charter, dict) or not charter:
        return CharterMatchResult(score=0.0, penalty_reasons=["no_charter"])

    positive = 0.0
    matched_domains: list[dict] = []
    citation_ids: list[str] = []
    raw_domains = charter.get("owned_domains")
    if isinstance(raw_domains, list):
        for item in raw_domains:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "").strip()
            if not domain or not _matches(domain, terms):
                continue
            status = str(item.get("status") or "").strip().lower()
            if status not in _VALID_DOMAIN_STATUS:
                status = "implemented"
            positive += resolved_rules[
                "owned_planned" if status == "planned" else "owned_implemented"
            ]
            matched_domains.append({"domain": domain, "status": status})
            citation_ids.extend(_clean_citations(item.get("citations")))
    # 正分先收敛到上界，再叠加负分——否则「多写几条 owned」就能抵消禁区命中。
    positive = min(positive, _SCORE_MAX)

    negative = 0.0
    violated_boundaries: list[str] = []
    raw_boundaries = charter.get("boundaries")
    if isinstance(raw_boundaries, list):
        for item in raw_boundaries:
            if not isinstance(item, dict):
                continue
            rule_text = str(item.get("rule") or "").strip()
            if not rule_text or not _matches(rule_text, terms):
                continue
            negative += resolved_rules["boundary_hit"]
            violated_boundaries.append(rule_text)
            citation_ids.extend(_clean_citations(item.get("citations")))

    penalty_reasons: list[str] = []
    evolution = str(charter.get("evolution") or "").strip().lower()
    if evolution == "maintenance_only":
        negative += resolved_rules["evolution_maintenance_only"]
        penalty_reasons.append("evolution_maintenance_only")
    elif evolution == "deprecated":
        negative += resolved_rules["evolution_deprecated"]
        penalty_reasons.append("evolution_deprecated")
    if violated_boundaries:
        penalty_reasons.append(f"boundary_hit x{len(violated_boundaries)}")

    score = max(_SCORE_MIN, min(_SCORE_MAX, positive + negative))
    try:
        charter_version = int(charter.get("version") or 0)
    except (TypeError, ValueError):
        charter_version = 0

    return CharterMatchResult(
        score=score,
        matched_domains=matched_domains,
        violated_boundaries=violated_boundaries,
        evolution=evolution,
        penalty_reasons=penalty_reasons,
        charter_source=str(charter.get("source") or ""),
        charter_version=charter_version,
        citation_ids=list(dict.fromkeys(citation_ids)),
    )


_CHARTER_VALUE_FIELDS = (
    "repository_id",
    "owned_domains",
    "boundaries",
    "evolution",
    "source",
    "version",
    "positioning",
)


@sync_to_async
def _load_charters_sync(repository_ids: list[str]) -> dict[str, dict]:
    """一次取全指定仓的章程正式字段（避免 N+1 与 async 裸 lazy-FK）。"""
    from repositories.models import RepoCharter

    rows = RepoCharter.objects.filter(repository_id__in=repository_ids).values(
        *_CHARTER_VALUE_FIELDS
    )
    return {
        str(row["repository_id"]): {**row, "repository_id": str(row["repository_id"])}
        for row in rows
    }


async def aload_charters(repository_ids: list[str]) -> dict[str, dict]:
    """批量读章程（best-effort）：返回 `{repository_id: 正式字段 dict}`，缺章程的仓不出现。

    任何异常 → warning + 返回 `{}`（路由不因章程读失败而中断，章程分量退化为全 0）。
    """
    ids = [str(rid) for rid in (repository_ids or []) if str(rid or "").strip()]
    if not ids:
        return {}
    try:
        return await _load_charters_sync(ids)
    except Exception as exc:  # noqa: BLE001 — best-effort：章程读失败不阻断路由
        from common.logging import redact_secrets_in_text

        logger.warning(
            "blueprint_charter_load_failed",
            repository_count=len(ids),
            error=redact_secrets_in_text(str(exc)),
            category="sampling",
            component="process_runtime",
        )
        return {}


@sync_to_async
def _scan_charter_owned_sync(repository_ids: list[str] | None) -> list[dict]:
    """扫章程的 owned_domains（含仓名，经 values 取 FK 字段，绝不在 async 里裸访问 FK）。"""
    from repositories.models import RepoCharter

    qs = RepoCharter.objects.select_related("repository")
    if repository_ids:
        qs = qs.filter(repository_id__in=repository_ids)
    return list(
        qs.values("repository_id", "repository__name", "owned_domains", "source", "version")
    )


async def acollect_charter_candidates(
    *,
    query_terms: list[str],
    exclude_repository_ids: set[str],
    repository_ids: list[str] | None = None,
    limit: int = 5,
) -> list[dict]:
    """章程候选补入清单 —— **高三提分专项 case 的机制解**（ROADMAP SC2 前半）。

    能力树里没有节点的仓不会被 `RepoRouterV2` 召回（onion-learning 的培优领域尚未
    实现），但章程已写明「这块归我」（`status=planned`）——本函数把这类仓作为**补入
    候选**返回，让它们以 `router_base=0.0` + `charter_match>0` 参与排序，从而不被淘汰。

    Returns:
        `[{repository_id, repository_name, charter_match_raw, matched_domains,
        source: "charter_supplement"}]`，按 `charter_match_raw` 降序取前 `limit`；
        任何异常 → warning + `[]`（best-effort）。
    """
    terms = [t for t in (query_terms or []) if str(t).strip()]
    if not terms or limit <= 0:
        return []
    excluded = {str(rid) for rid in (exclude_repository_ids or set())}
    scope = [str(rid) for rid in (repository_ids or []) if str(rid or "").strip()] or None

    try:
        rows = await _scan_charter_owned_sync(scope)
    except Exception as exc:  # noqa: BLE001 — best-effort：补入失败退化为「无补入」
        from common.logging import redact_secrets_in_text

        logger.warning(
            "blueprint_charter_supplement_failed",
            error=redact_secrets_in_text(str(exc)),
            category="sampling",
            component="process_runtime",
        )
        return []

    collected: list[dict] = []
    for row in rows:
        repository_id = str(row.get("repository_id") or "")
        if not repository_id or repository_id in excluded:
            continue
        raw_domains = row.get("owned_domains")
        if not isinstance(raw_domains, list):
            continue
        raw_score = 0.0
        matched_domains: list[dict] = []
        for item in raw_domains:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain") or "").strip()
            if not domain or not _matches(domain, terms):
                continue
            status = str(item.get("status") or "").strip().lower()
            if status not in _VALID_DOMAIN_STATUS:
                status = "implemented"
            raw_score += DEFAULT_CHARTER_RULES[
                "owned_planned" if status == "planned" else "owned_implemented"
            ]
            matched_domains.append({"domain": domain, "status": status})
        if not matched_domains:
            continue
        collected.append(
            {
                "repository_id": repository_id,
                "repository_name": str(row.get("repository__name") or ""),
                "charter_match_raw": min(raw_score, _SCORE_MAX),
                "matched_domains": matched_domains,
                "source": "charter_supplement",
            }
        )

    collected.sort(key=lambda c: (-c["charter_match_raw"], c["repository_id"]))
    return collected[:limit]
