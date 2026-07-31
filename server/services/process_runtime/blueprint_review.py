"""blueprint_review —— AI 审查判定内核（Phase 114-02，FLOW-07）。

四段契约（改动前先读）：

1. **本模块分两节**：**机械规则纯函数节**（无 IO / 无 ORM / 无 LLM，stdlib + 既有纯
   函数）与 **goal-backward LLM 节**（唯一 LLM 一类，best-effort 返 ``None``）。顶层
   零 ORM import；ORM 只由调用方（114-03 adapter）经 ``BlueprintLifecycleService``
   触达（INV-6）。本模块**不建线程、不转状态、不写 stage_state**——只定义
   :data:`STAGE_STATE_KEY` 常量供 114-03 落桶，留痕通道只有
   ``BlueprintLifecycleService.append_note``（114-01）。
2. **输入是半可信的装配产物**：``merge`` 的 ``exhausted`` 出口也走 ``merged`` 边
   （``builtin_processes.py:694-696``），故本模块拿到的蓝图可能是「已成形但未达标」的
   半成品——整段缺失、``repo_associations`` 为空、``citations`` 池不存在都属常态。逐
   字段 ``.get`` 防御、逐层 ``isinstance`` 检查、**绝不外抛**：审查结论是编排层「打回
   还是升人审」的判据，抛异常会把「有缺陷」升级成「整轮失败」。
3. **不用 LLM 做机械判定**（114-CONTEXT 锁定）：六类必须可复现、可单测、可解释——
   交给 LLM 则同一蓝图每轮结论不同、无法回归、打回决策不可解释。LLM 只承担
   goal-backward 一类，且其不可得（``None``）**一律 fail-closed 记一条 warning meta
   finding**（:func:`normalize_review_findings`），**绝不当作「无问题」放行**。
4. **三条已知假通过陷阱，写死在实现里**：

   - (a) ``validate_blueprint`` 对缺 ``schema_version`` 的 content **直接
     ``return True, None``**（``blueprint_schema.py:809-810`` 的 v0 pass-through）⇒
     规则① :func:`check_schema` **先自断言** ``schema_version ==
     BLUEPRINT_SCHEMA_VERSION``，绝不把它的返回直接当结论；
   - (b) ``citation_coverage`` 分母为 0 返回 **1.0**（``blueprint_quality.py:76``，
     空文档拿满分）⇒ 规则② :func:`check_citations` 走**条目级**走查，**不看比率**；
   - (c) ``api_contracts[].direction`` 的枚举是 ``provided`` / ``consumed``
     （``blueprint_schema.py:522-524``），写成 ``produced`` 会永远匹配不到 ⇒ 规则④
     退化成恒通过的装饰品。

   另一条同源纪律：**被减集合为空时判 skip 或 BLOCKER，绝不判 pass**——
   ``repo_associations`` 为空时「每个 direct 仓 ≥1 实现项」恒真，跑出来是一片假阳性
   通过（P1）。故 :func:`check_preconditions` 命中即**短路**，后五条一律不跑。
"""

from __future__ import annotations

import re
from typing import Any, Iterator

from delivery.services.blueprint_anchor import _block_text
from services.process_runtime.blueprint_schema import BLUEPRINT_SCHEMA_VERSION, validate_blueprint

__all__ = [
    "STAGE_STATE_KEY",
    "SEVERITY_BLOCKER",
    "SEVERITY_WARNING",
    "SEVERITY_INFO",
    "check_preconditions",
    "check_schema",
    "check_citations",
    "check_roles",
    "normalize_review_findings",
    "finding_dedupe_key",
]

# stage_state 顶层键（实测未被 spec_gate / confirmation / repo_plan / merge 占用）。
# ⚠️ 绝不复用 "merge" 桶：那会把审查结论写进融合状态、让阶段 3 的续跑判据失真。
STAGE_STATE_KEY = "ai_review"

# 分级字面量。本模块顶层零 Django import（INV-6），拿不到 ThreadSeverity 枚举，故用
# 字面量并由测试锁死等值（沿用 blueprint_resume._STAGE_BLUEPRINT_STATUS 的同款纪律）。
SEVERITY_BLOCKER = "blocker"  # == ThreadSeverity.BLOCKER
SEVERITY_WARNING = "warning"  # == ThreadSeverity.WARNING
SEVERITY_INFO = "info"  # == ThreadSeverity.INFO

_SEVERITIES = (SEVERITY_BLOCKER, SEVERITY_WARNING, SEVERITY_INFO)

# 单次审查的 finding 上界：结论会进线程 body 与人审面板，无界列表会把 HITL 刷爆。
# 截断只影响详尽度，不影响处置——只要有一条 BLOCKER，打回/升人审的结论就已成立。
_MAX_FINDINGS = 50

# 单条 detail 字符上界（与 blueprint_schema._MAX_ERROR_CHARS 同量级）：detail 会进线程
# body，而蓝图正文是半可信文本（可能夹带代码片段/凭证样本），出口统一截断。
_MAX_DETAIL_CHARS = 500

# 命中片段上界：排期禁令等文本类判定只带命中片段，**绝不贴整块正文**。
_MAX_SNIPPET_CHARS = 80

# 规则⑤排期禁令：以周为单位的排期（`3 周` / `2 个周` / `week` 大小写不敏感）。
_WEEK_SCHEDULE_PATTERN = re.compile(r"\d+\s*个?\s*周|\bweeks?\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 机械规则纯函数节（无 IO / 无 ORM / 无 LLM）
# ---------------------------------------------------------------------------


def check_preconditions(content: Any) -> list[dict]:
    """前置完整性（**短路判定**）：三段必备内容任一为空即单条 BLOCKER。

    三段 = ``repo_associations`` / ``implementation_overview.items`` /
    ``requirement_spec.feature_points``（非空 dict 元素 list 才算「有」）。

    命中即**短路**：:func:`run_mechanical_rules` 不再跑后五条。理由是被减集合为空会让
    规则③④⑤⑥的集合运算**恒真**——``repo_associations`` 为空时「每个 direct 仓 ≥1 实现
    项」必然成立，跑出来是一片假通过噪声（P1）。半成品蓝图必须拿到「缺段」这个可行动
    的结论，而不是一个看起来干净的 ``[]``。

    Returns:
        恰好一条 ``precondition_missing`` BLOCKER（``detail`` 只列**缺哪几段的段名**，
        不带任何正文），或 ``[]``。**绝不抛**。
    """
    findings: list[dict] = []
    try:
        data = content if isinstance(content, dict) else {}
        missing: list[str] = []
        if not _dict_list(data.get("repo_associations")):
            missing.append("repo_associations")
        if not _impl_items(data):
            missing.append("implementation_overview.items")
        spec = data.get("requirement_spec")
        if not _dict_list(spec.get("feature_points") if isinstance(spec, dict) else None):
            missing.append("requirement_spec.feature_points")
        if missing:
            _append(
                findings,
                _finding(
                    "precondition_missing",
                    SEVERITY_BLOCKER,
                    detail="蓝图缺少前置必备段，无法进行六类机械规则走查（缺段："
                    + "、".join(missing)
                    + "）",
                ),
            )
    except Exception:  # noqa: BLE001 — 半可信输入恒不抛：抛了会把「有缺陷」升级成「整轮失败」
        return findings
    return findings


def check_schema(content: Any) -> list[dict]:
    """规则① schema 完整性：判别字段自断言 + ``validate_blueprint`` 结构校验。

    **先自断言 ``schema_version``**：``validate_blueprint`` 对缺该字段的 content 走 v0
    pass-through **直接 ``return True, None``**（``blueprint_schema.py:809-810``）——把它
    的返回当规则①结论，等于让任何「忘了写 schema_version 的半成品」原地满分通过。

    结构校验本身**不重写**（Don't Hand-Roll）：jsonschema + 5 项后置检查（引用完整性 /
    feature_point_id 可解析 / repository_id 在 repo_associations / 引用池键一致 / id
    唯一）全部由 ``validate_blueprint`` 承担，本函数只翻译成 finding。

    Returns:
        ``schema_version_missing`` 或 ``schema_invalid`` BLOCKER（``detail`` 直接引用
        校验器报错，该报错已由 ``_format_error`` 脱敏并截断 500 字符），或 ``[]``。
    """
    findings: list[dict] = []
    try:
        if (
            not isinstance(content, dict)
            or content.get("schema_version") != BLUEPRINT_SCHEMA_VERSION
        ):
            _append(
                findings,
                _finding(
                    "schema_version_missing",
                    SEVERITY_BLOCKER,
                    section_path="schema_version",
                    detail=f"schema_version 缺失或不等于 {BLUEPRINT_SCHEMA_VERSION}；"
                    "该形状会被 validate_blueprint 按隐式 v0 直接放行，不能据其判定合法",
                ),
            )
            return findings
        ok, error = validate_blueprint(content)
        if ok is False:
            _append(
                findings,
                _finding(
                    "schema_invalid",
                    SEVERITY_BLOCKER,
                    detail=str(error or "结构校验未通过（校验器未给出原因）"),
                ),
            )
    except Exception:  # noqa: BLE001 — 半可信输入恒不抛（同 check_preconditions）
        return findings
    return findings


def check_citations(content: Any) -> list[dict]:
    """规则② 引用覆盖：**条目级**走查，关键结论无引用即 BLOCKER。

    **不看 ``citation_coverage`` 比率**（理由见模块 docstring 第 4 段 (b)：分母为 0 返
    1.0，空文档拿满分）。三类关键结论的遍历口径**同源于**
    ``blueprint_quality._iter_key_conclusion_citations``（顺序也一致）：

    - ``current_state_analysis[].findings[]``——取 ``finding.citations``；
    - ``repo_associations[]``（rationale 级）——取 ``rationale.citations``；
    - ``impact_analysis.affected_features[]``——取 ``feature.citations``。

    遍历在本模块**自写**（不 import 受限模块的私有 generator，也不改 111 已交付的
    ``blueprint_quality``），但判定逐字同源并额外产出 ``section_path``（点分 +
    ``[标识]``，对齐 ``iter_blocks`` 约定）。两处漂移会导致「覆盖率说达标、审查说缺
    引用」的自相矛盾——那种矛盾无法被任何一侧的测试逮住。

    Returns:
        关键结论缺引用 → ``citation_missing`` **BLOCKER**；其余事实性断言条目
        （``implementation_overview.items[]`` / ``api_contracts[]``）缺引用 →
        ``citation_missing_weak`` **WARNING**（弱判据，仅供人审参考不打回）。
    """
    findings: list[dict] = []
    try:
        for section_path, repository_id, citations, is_key in _iter_conclusion_entries(content):
            if _cited(citations):
                continue
            if is_key:
                _append(
                    findings,
                    _finding(
                        "citation_missing",
                        SEVERITY_BLOCKER,
                        section_path=section_path,
                        repository_id=repository_id,
                        detail="关键结论条目没有任何 citations 支撑（关键结论必须有据）",
                    ),
                )
            else:
                _append(
                    findings,
                    _finding(
                        "citation_missing_weak",
                        SEVERITY_WARNING,
                        section_path=section_path,
                        repository_id=repository_id,
                        detail="事实性断言条目没有 citations 支撑（弱判据，仅供人审参考）",
                    ),
                )
    except Exception:  # noqa: BLE001 — 半可信输入恒不抛（同 check_preconditions）
        return findings
    return findings


def check_roles(content: Any) -> list[dict]:
    """规则③ 角色一致性：三条，按**可证伪度**分档（纯集合运算 BLOCKER / 模糊匹配 WARNING）。

    - ``role == "direct"`` 的仓在 ``implementation_overview.items[].repository_id`` 里
      **零命中** → ``role_mismatch`` **BLOCKER**（纯集合运算）；
    - 实现项指向 ``role == "indirect"`` 的仓 → ``role_mismatch`` **BLOCKER**
      （indirect 的语义就是「被依赖但本方案不改动」，改它即越界，纯集合运算）；
    - indirect 仓的 ``capabilities_used`` 未在任何实现项文本（``title`` / ``how``）或
      ``api_contracts[].data_source.from_api|from_service`` 中被包含匹配 →
      ``capability_unreferenced`` **WARNING**。这是本模块**唯一的模糊匹配项**：文本包含
      是弱判据，强判 BLOCKER 会产生不可复现的假阳性（A4）。

    ``role`` 非法/缺失一律**保守回落 direct**（与
    ``blueprint_repo_plan._normalize_locked_repos`` 同源：把「要改的仓」误判成「不用改」
    的代价远高于反过来）；``role`` 的合法性本身由规则①的 jsonschema 承担。
    """
    findings: list[dict] = []
    try:
        data = content if isinstance(content, dict) else {}
        direct_ids: set[str] = set()
        indirect: dict[str, dict] = {}
        for assoc in _dict_list(data.get("repo_associations")):
            repository_id = str(assoc.get("repository_id") or "")
            if not repository_id:
                continue
            if str(assoc.get("role") or "").strip().lower() == "indirect":
                indirect[repository_id] = assoc
            else:
                direct_ids.add(repository_id)

        items = _impl_items(data)
        item_repos = {str(item.get("repository_id") or "") for item in items}
        for repository_id in sorted(direct_ids - item_repos):
            _append(
                findings,
                _finding(
                    "role_mismatch",
                    SEVERITY_BLOCKER,
                    section_path=f"repo_associations[{repository_id}]",
                    repository_id=repository_id,
                    detail="direct 仓无任何实现项：要么它不该是 direct，要么实现概述漏了它",
                ),
            )
        for item in items:
            repository_id = str(item.get("repository_id") or "")
            if not repository_id or repository_id not in indirect:
                continue
            item_id = str(item.get("id") or "") or "?"
            _append(
                findings,
                _finding(
                    "role_mismatch",
                    SEVERITY_BLOCKER,
                    section_path=f"implementation_overview.items[{item_id}]",
                    repository_id=repository_id,
                    detail="实现项落在 role=indirect 的仓：indirect 的语义是被依赖但本方案不改动",
                ),
            )

        corpus = _reference_corpus(data)
        for repository_id in sorted(indirect):
            for index, capability in enumerate(_capabilities(indirect[repository_id])):
                if capability.lower() in corpus:
                    continue
                _append(
                    findings,
                    _finding(
                        "capability_unreferenced",
                        SEVERITY_WARNING,
                        section_path=(
                            f"repo_associations[{repository_id}].capabilities_used[{index}]"
                        ),
                        repository_id=repository_id,
                        detail="indirect 仓声明会用到的能力未被任何实现项或契约引用"
                        f"（文本包含匹配，弱判据）：{capability[:_MAX_SNIPPET_CHARS]}",
                    ),
                )
    except Exception:  # noqa: BLE001 — 半可信输入恒不抛（同 check_preconditions）
        return findings
    return findings


# ---------------------------------------------------------------------------
# finding 归一 / 去重（114-03 落线程、114-05 呈现共用同一形状）
# ---------------------------------------------------------------------------


def normalize_review_findings(raw: Any) -> list[dict]:
    """把任意来源（含 LLM 原始输出、``None``）归一到 finding 六键形状。

    ⭐ **``raw is None`` 的语义是「goal-backward 一类不可得」，不是「无问题」**：本函数
    据此产出**一条 ``goal_backward_unavailable`` WARNING meta finding**——上游
    fail-closed 的落点就在这里。返回 ``[]`` 会让编排层把「审查没跑成」误读成「审查通
    过」，那是 T-114-11（LLM 静默失效 ⇒ 带缺陷蓝图直升人审）。

    归一规则：非 list（且非 ``None``）→ ``[]``；元素非 dict / ``rule_id`` 为空 → 整项
    丢弃；``severity`` ∉ ``{blocker, warning, info}`` → 回落 ``warning``（宁可少挡不误
    钉：把模型胡写的级别当 BLOCKER 会无端打回）；条数受 :data:`_MAX_FINDINGS` 约束、
    ``detail`` 受 :data:`_MAX_DETAIL_CHARS` 截断。
    """
    if raw is None:
        return [
            _finding(
                "goal_backward_unavailable",
                SEVERITY_WARNING,
                detail="goal-backward 审查未能执行（LLM 不可得），本轮不据此打回，请人审关注",
            )
        ]
    findings: list[dict] = []
    if not isinstance(raw, list):
        return findings
    for item in raw:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("rule_id") or "").strip()
        if not rule_id:
            continue
        severity = str(item.get("severity") or "").strip().lower()
        if severity not in _SEVERITIES:
            severity = SEVERITY_WARNING
        _append(
            findings,
            _finding(
                rule_id,
                severity,
                section_path=str(item.get("section_path") or ""),
                block_id=str(item.get("block_id") or ""),
                repository_id=str(item.get("repository_id") or ""),
                detail=str(item.get("detail") or ""),
            ),
        )
    return findings


def finding_dedupe_key(finding: Any) -> str:
    """finding 的幂等键：``f"{rule_id}|{block_id or section_path}"``。

    114-03 落库前用它查既有线程——命中 ``kind=ai_review_finding`` 且 ``status ∈
    {open, answered}`` 的线程时走 ``append_note("第 N 轮仍存在")`` **而非新开线程**：
    同一 block 反复开线程会让人审侧噪声爆炸（一轮打回 = 一份重复清单）。

    ``block_id`` 优先于 ``section_path``：块被编辑后 section_path 可能漂移，而
    ``block_id`` 是版本间稳定标识（``blueprint_schema`` 的 Block 基元约定）。
    """
    data = finding if isinstance(finding, dict) else {}
    rule_id = str(data.get("rule_id") or "")
    anchor = str(data.get("block_id") or "") or str(data.get("section_path") or "")
    return f"{rule_id}|{anchor}"


# ── 内部纯函数 ────────────────────────────────────────────────────────────


def _finding(
    rule_id: str,
    severity: str,
    *,
    section_path: str = "",
    block_id: str = "",
    repository_id: str = "",
    detail: str = "",
) -> dict:
    """构造 finding：**恒定六键**，114-03 落线程与 114-05 呈现按此形状对齐。

    - ``rule_id``：判据标识（如 ``citation_missing``），也是幂等键的第一段；
    - ``severity``：``blocker`` ⇒ 114-03 以 ``blocking=True`` 开线程并计入打回判据；
      ``warning`` / ``info`` ⇒ 只作人审参考，**不打回**（114-01 的不变式要求
      ``blocking == (severity == "blocker")``，成对给值，否则 ``ValueError``）；
    - ``section_path``：点分 + ``[标识]`` 定位（对齐 ``iter_blocks`` 约定），无则空串；
    - ``block_id``：可锚定到具体 block 时给出（划线线程重锚定用），无则空串；
    - ``repository_id``：可归因到单仓时给出（决定「回哪个仓」），无则空串；
    - ``detail``：给人看的一句话结论，**截断至** :data:`_MAX_DETAIL_CHARS`。绝不整段
      贴蓝图正文（半可信文本可能夹带凭证样本，T-114-10）。
    """
    return {
        "rule_id": str(rule_id or ""),
        "severity": str(severity or ""),
        "section_path": str(section_path or ""),
        "block_id": str(block_id or ""),
        "repository_id": str(repository_id or ""),
        "detail": str(detail or "")[:_MAX_DETAIL_CHARS],
    }


def _append(bucket: list[dict], entry: dict, *, limit: int = _MAX_FINDINGS) -> None:
    """有界追加：超界**静默丢弃**（结论已足够打回/开线程，多一条只是刷屏）。"""
    if len(bucket) < limit:
        bucket.append(entry)


def _cited(value: Any) -> bool:
    """条目引用判定（与 ``blueprint_quality._cited`` 逐字同源）：非空 list 即已引用。"""
    return isinstance(value, list) and len(value) > 0


def _dict_list(value: Any) -> list[dict]:
    """取 list 中的 dict 元素（非 list / 非 dict 元素一律剔除）。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _impl_items(content: Any) -> list[dict]:
    """``implementation_overview.items`` 的 dict 元素。"""
    if not isinstance(content, dict):
        return []
    overview = content.get("implementation_overview")
    if not isinstance(overview, dict):
        return []
    return _dict_list(overview.get("items"))


def _blocks_text(value: Any) -> str:
    """block_list → 可比对文本（逐块走 ``blueprint_anchor._block_text``，口径同源）。

    ``blueprint_anchor`` 是 stdlib-only、零 Django import 的纯函数模块，顶层 import
    不破坏本模块的零 ORM 纪律；**绝不自写第二套取文本规则**（四型块的取值口径漂移会让
    重锚定与审查看到不同的文本）。
    """
    if isinstance(value, str):
        return value
    return "\n".join(_block_text(block) for block in _dict_list(value))


def _iter_conclusion_entries(content: Any) -> Iterator[tuple[str, str, Any, bool]]:
    """走查带引用的条目，产出 ``(section_path, repository_id, citations, is_key)``。

    前三类 ``is_key=True``，遍历顺序与 ``blueprint_quality._iter_key_conclusion_citations``
    逐字同源；后两类（实现项 / API 契约）``is_key=False``，是「事实性断言」弱判据。
    """
    if not isinstance(content, dict):
        return
    for analysis in _dict_list(content.get("current_state_analysis")):
        repository_id = str(analysis.get("repository_id") or "")
        base = f"current_state_analysis[{repository_id or '?'}]"
        for index, finding in enumerate(_dict_list(analysis.get("findings"))):
            key = str(finding.get("id") or "") or str(index)
            yield (f"{base}.findings[{key}]", repository_id, finding.get("citations"), True)
    for index, assoc in enumerate(_dict_list(content.get("repo_associations"))):
        repository_id = str(assoc.get("repository_id") or "") or str(index)
        rationale = assoc.get("rationale")
        citations = rationale.get("citations") if isinstance(rationale, dict) else None
        yield (
            f"repo_associations[{repository_id}].rationale",
            str(assoc.get("repository_id") or ""),
            citations,
            True,
        )
    impact = content.get("impact_analysis")
    features = impact.get("affected_features") if isinstance(impact, dict) else None
    for index, feature in enumerate(_dict_list(features)):
        key = str(feature.get("feature") or "") or str(index)
        yield (
            f"impact_analysis.affected_features[{key}]",
            _first_text(feature.get("repository_ids")),
            feature.get("citations"),
            True,
        )
    for index, item in enumerate(_impl_items(content)):
        key = str(item.get("id") or "") or str(index)
        yield (
            f"implementation_overview.items[{key}]",
            str(item.get("repository_id") or ""),
            item.get("citations"),
            False,
        )
    for index, contract in enumerate(_dict_list(content.get("api_contracts"))):
        key = str(contract.get("id") or "") or str(index)
        yield (
            f"api_contracts[{key}]",
            str(contract.get("repository_id") or ""),
            contract.get("citations"),
            False,
        )


def _first_text(values: Any) -> str:
    """取 list 首个非空字符串（受影响功能可能横跨多仓、也可能没标仓 → 空串）。"""
    for value in values if isinstance(values, list) else []:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _capabilities(assoc: Any) -> list[str]:
    """``capabilities_used`` 归一为文本列表（元素可能是 str 也可能是 dict）。"""
    if not isinstance(assoc, dict):
        return []
    raw = assoc.get("capabilities_used")
    if not isinstance(raw, list):
        return []
    texts: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            text = ""
            for key in ("name", "capability", "text", "title"):
                text = str(item.get(key) or "").strip()
                if text:
                    break
        else:
            text = str(item or "").strip()
        if text:
            texts.append(text)
    return texts


def _reference_corpus(content: Any) -> str:
    """indirect 能力被引用与否的比对文本池（**小写**，供包含匹配）。

    池 = 实现项 ``title`` / ``how`` 文本 + ``api_contracts[].data_source`` 的
    ``from_api`` / ``from_service``（规则③第三条的判据来源，114-CONTEXT 锁定）。
    """
    parts: list[str] = []
    for item in _impl_items(content):
        parts.append(str(item.get("title") or ""))
        parts.append(_blocks_text(item.get("how")))
    if isinstance(content, dict):
        for contract in _dict_list(content.get("api_contracts")):
            data_source = contract.get("data_source")
            if not isinstance(data_source, dict):
                continue
            parts.append(str(data_source.get("from_api") or ""))
            parts.append(str(data_source.get("from_service") or ""))
    return "\n".join(parts).lower()
