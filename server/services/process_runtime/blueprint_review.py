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

import json
import re
import time
from typing import Any, Iterator

import structlog

from common.logging import redact_secrets_in_text
from delivery.services.blueprint_anchor import _block_text
from services.process_runtime.blueprint_repo_alias import is_resolvable_repository_alias
from services.process_runtime.blueprint_schema import (
    BLUEPRINT_SCHEMA_VERSION,
    iter_blocks,
    validate_blueprint,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "STAGE_STATE_KEY",
    "SEVERITY_BLOCKER",
    "SEVERITY_WARNING",
    "SEVERITY_INFO",
    "RULE_GATE_LOCK_MISSING",
    "RULE_GATE_LOCK_ROLE",
    "RULE_GATE_LOCK_RESPONSIBILITY",
    "check_preconditions",
    "check_schema",
    "check_citations",
    "check_roles",
    "check_api_closure",
    "check_prohibitions",
    "check_charters",
    "check_gate_lock",
    "run_mechanical_rules",
    "agoal_backward_review",
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

# ⭐ 确认门锁定偏离的三个 rule_id（114-MN-03）：同一个仓可**同时**角色与职责都偏离，而三种
# 偏离的 `section_path` / `block_id` 逐字相同 ⇒ 必须由 `rule_id` 承担形态区分，否则
# `finding_dedupe_key` 会把它们折叠成同一个键（后果见 `check_gate_lock` 的 Returns 段）。
# `rule_id` 是唯一能从线程首条消息的 `[rule_id]` 前缀反查回来的段（`_RULE_ID_TAG`），
# 因此也是唯一能让**第二轮**的键仍然分得开的载体。
RULE_GATE_LOCK_MISSING = "gate_lock_violation"  # 锁定仓整条消失（保留原值，兼容既有线程）
RULE_GATE_LOCK_ROLE = "gate_lock_violation_role"  # role 偏离
RULE_GATE_LOCK_RESPONSIBILITY = "gate_lock_violation_responsibility"  # responsibility 文本偏离

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

# 规则④的 direction / availability 枚举字面值（``blueprint_schema.py:522-524`` /
# ``:555-559`` 实测）。⚠️ direction 只有 provided / consumed 两值——凭印象写成第三个词
# 会永远匹配不到，规则④就退化成恒通过的装饰品（模块 docstring 第 4 段 (c)）。
_DIRECTION_PROVIDED = "provided"
_DIRECTION_CONSUMED = "consumed"
_NEEDS_SUPPORT = "needs_support"

# 规则⑤ out_of_scope 扫描的**排除段**：``deferred_ideas`` 是「scope 外想法」的正当落位
# （``blueprint_schema.py:737-740``），扫它必然把每条想法都误报成「引入了 scope 外内容」。
_DEFERRED_IDEAS_PREFIX = "deferred_ideas"

# 规则⑥ 章程「不该再长新东西」的演进态（``repositories/models.py:1113`` 三选一之二）。
_FROZEN_EVOLUTIONS = ("maintenance_only", "deprecated")

# ── goal-backward LLM 节上界（prompt 体积与投影裁剪） ─────────────────────
# constraints 进 digest 的条数与单条文本上界（B5：语义冲突判定的输入）。
_MAX_CONSTRAINTS = 20
_MAX_CONSTRAINT_TEXT_CHARS = 300
# digest 各清单的条数上界（与 blueprint_merge._MAX_LIST_ITEMS 同量级）。
_MAX_DIGEST_ITEMS = 200
# 单条标题 / 叙事片段上界。
_MAX_TITLE_CHARS = 200
_MAX_NARRATIVE_CHARS = 1000
# prompt 各分节字符上界（照 blueprint_ambiguity_score._MAX_PROMPT_CHARS）。
_MAX_PROMPT_CHARS = 6000
# constraints 缺失时 digest 里的显式标注——**不静默落空**，人能从 digest 与
# ``constraint_count=0`` 事件同时看出「本轮约束冲突判定未生效」。
_NO_CONSTRAINTS_NOTICE = "（无约束清单，本项不可判）"


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
    """规则③ 角色一致性：四条，按**可证伪度**分档（纯集合运算 BLOCKER / 弱信号 WARNING）。

    - ``role == "direct"`` 的仓在 ``implementation_overview.items[].repository_id`` 里
      **零命中** → ``role_mismatch`` **BLOCKER**（纯集合运算）；
    - 实现项指向 ``role == "indirect"`` 的仓 → ``role_mismatch`` **BLOCKER**
      （indirect 的语义就是「被依赖但本方案不改动」，改它即越界，纯集合运算）；
    - indirect 仓零实现项 → ``indirect_repo_plan_empty`` **WARNING**。indirect 本可合理地
      不改代码，故不能升 BLOCKER；但仓级方案降级/空产出时必须给人审一个可见信号；
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
        for repository_id in sorted(set(indirect) - item_repos):
            _append(
                findings,
                _finding(
                    "indirect_repo_plan_empty",
                    SEVERITY_WARNING,
                    section_path=f"repo_associations[{repository_id}]",
                    repository_id=repository_id,
                    detail=(
                        "indirect 仓没有任何实现项；该仓可能合理地无需改动，也可能是仓级方案"
                        "降级或空产出，请在人审中确认"
                    ),
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


def check_api_closure(content: Any) -> list[dict]:
    """规则④ API 闭环：两条**纯集合运算**，均 BLOCKER。

    - ``interaction_flows[].steps[].api_ref`` 指向 ``api_contracts[].id`` 之外 →
      ``api_ref_dangling``（流程引用了不存在的契约，下游派生器会拿它建出无主的调用）；
    - ``direction == consumed`` 且 ``data_source.availability == needs_support`` 时，
      ``data_source.support_repository_id`` 缺失或不在 ``repo_associations`` 里 →
      ``support_repo_missing``（缺协作仓，等于把「要别人配合」写成了「自己能搞定」）。

    ⚠️ ``direction`` 的合法值只有 ``provided`` / ``consumed``
    （``blueprint_schema.py:522-524``）——凭印象写成别的词会**永远匹配不到**，规则④就变成
    恒通过的装饰品（Task 3 有一条并列防回归断言）。可用性判定**只读 ``data_source.*``
    子路径**，顶层同名键即便存在也一概不读（与 ``blueprint_reconcile`` 的 B4 纪律同源：
    111 schema 里没有那个顶层键，按它判定等于把结论建在幻觉字段上）。
    """
    findings: list[dict] = []
    try:
        data = content if isinstance(content, dict) else {}
        contracts = _dict_list(data.get("api_contracts"))
        contract_ids = {str(item.get("id") or "") for item in contracts}
        contract_ids.discard("")
        for flow in _dict_list(data.get("interaction_flows")):
            flow_key = str(flow.get("id") or "") or "?"
            for index, step in enumerate(_dict_list(flow.get("steps"))):
                api_ref = str(step.get("api_ref") or "").strip()
                if not api_ref or api_ref in contract_ids:
                    continue
                seq = step.get("seq")
                step_key = str(seq) if seq is not None and str(seq) else str(index)
                _append(
                    findings,
                    _finding(
                        "api_ref_dangling",
                        SEVERITY_BLOCKER,
                        section_path=f"interaction_flows[{flow_key}].steps[{step_key}]",
                        detail="步骤引用的契约 id 不存在于 api_contracts："
                        f"{api_ref[:_MAX_SNIPPET_CHARS]}",
                    ),
                )

        associations = _associations(data)
        for index, contract in enumerate(contracts):
            if _direction(contract) != _DIRECTION_CONSUMED:
                continue
            data_source = contract.get("data_source")
            if not isinstance(data_source, dict):
                continue
            if str(data_source.get("availability") or "") != _NEEDS_SUPPORT:
                continue
            support_id = str(data_source.get("support_repository_id") or "").strip()
            if support_id and _support_repository_resolved(associations, support_id):
                continue
            contract_key = str(contract.get("id") or "") or str(index)
            _append(
                findings,
                _finding(
                    "support_repo_missing",
                    SEVERITY_BLOCKER,
                    section_path=f"api_contracts[{contract_key}].data_source",
                    repository_id=str(contract.get("repository_id") or ""),
                    detail="consumed 契约已标 needs_support，但 support_repository_id "
                    "缺失或不在 repo_associations 中（缺协作仓）",
                ),
            )
    except Exception:  # noqa: BLE001 — 半可信输入恒不抛（同 check_preconditions）
        return findings
    return findings


def check_prohibitions(content: Any) -> list[dict]:
    """规则⑤ 禁令：排期表述 / out_of_scope 引入 / constraint 引用悬空。

    - **排期禁令**：走查全部 block 文本（``iter_blocks`` + ``_block_text``，口径同源不自
      写第二套），命中 :data:`_WEEK_SCHEDULE_PATTERN` → ``forbidden_schedule``
      **BLOCKER**。``detail`` 只带命中片段（≤ :data:`_MAX_SNIPPET_CHARS`）与定位，
      **绝不贴整块正文**（T-114-10）；
    - **out_of_scope 引入**：``requirement_spec.boundaries.out_of_scope`` 的词条在 block
      文本中被包含匹配 → ``out_of_scope_introduced`` **WARNING**（文本包含是弱判据）。
      扫描**排除 ``deferred_ideas`` 段**——那是 scope 外想法的正当落位，扫它必误报；
    - **constraint 引用悬空**：``repo_associations[].rationale.constraint_refs``（**唯一
      已存在的 constraint 引用通道**）减去 ``requirement_spec.constraints[].id`` 非空 →
      ``constraint_ref_dangling`` **BLOCKER**（纯集合运算）。

    ⭐ **B5 降级范围登记（分工与边界，改动前先读）**：114-CONTEXT 规则⑤的第三条「不得与
    constraints 冲突」在本模块**只覆盖引用层**——即「引用了不存在的 constraint id」
    （``constraint_ref_dangling``，纯集合运算、可复现、可单测）。**语义层冲突**（某实现项
    或 API 契约实质违背某条 ``constraints[].text``）**不做机械判定**：自由文本的语义判定
    强判 BLOCKER 会产生不可复现的假阳性（A4）。该判定**已下沉到**
    :func:`agoal_backward_review`——它把 ``requirement_spec.constraints`` 纳入形参与 prompt
    digest，并要求模型以 ``rule_id="constraint_conflict"`` 回报。LLM 不可得时该层退化为
    :func:`normalize_review_findings` 产出的 ``goal_backward_unavailable`` warning meta
    finding。⇒ **规则⑤第三条不落空，且两级降级路径显式可见。**
    """
    findings: list[dict] = []
    try:
        data = content if isinstance(content, dict) else {}
        blocks = iter_blocks(data)

        for section_path, block in blocks:
            text = _block_text(block)
            if not text:
                continue
            match = _WEEK_SCHEDULE_PATTERN.search(text)
            if match is None:
                continue
            _append(
                findings,
                _finding(
                    "forbidden_schedule",
                    SEVERITY_BLOCKER,
                    section_path=section_path,
                    block_id=str(block.get("block_id") or ""),
                    detail="出现以周为单位的排期表述（禁令）：" + _snippet(text, match.start()),
                ),
            )

        terms = _out_of_scope_terms(data)
        for section_path, block in blocks:
            if not terms or section_path.startswith(_DEFERRED_IDEAS_PREFIX):
                continue
            lowered = _block_text(block).lower()
            if not lowered:
                continue
            for term in terms:
                if term.lower() not in lowered:
                    continue
                _append(
                    findings,
                    _finding(
                        "out_of_scope_introduced",
                        SEVERITY_WARNING,
                        section_path=section_path,
                        block_id=str(block.get("block_id") or ""),
                        detail="正文出现被 boundaries.out_of_scope 排除的内容"
                        f"（文本包含匹配，弱判据）：{term[:_MAX_SNIPPET_CHARS]}",
                    ),
                )

        constraint_ids = _constraint_ids(data)
        for assoc in _dict_list(data.get("repo_associations")):
            repository_id = str(assoc.get("repository_id") or "")
            rationale = assoc.get("rationale")
            raw_refs = rationale.get("constraint_refs") if isinstance(rationale, dict) else None
            refs = {
                str(ref).strip()
                for ref in (raw_refs if isinstance(raw_refs, list) else [])
                if str(ref or "").strip()
            }
            for ref in sorted(refs - constraint_ids):
                _append(
                    findings,
                    _finding(
                        "constraint_ref_dangling",
                        SEVERITY_BLOCKER,
                        section_path=(
                            f"repo_associations[{repository_id or '?'}].rationale.constraint_refs"
                        ),
                        repository_id=repository_id,
                        detail="引用的约束 id 不存在于 requirement_spec.constraints："
                        f"{ref[:_MAX_SNIPPET_CHARS]}",
                    ),
                )
    except Exception:  # noqa: BLE001 — 半可信输入恒不抛（同 check_preconditions）
        return findings
    return findings


def check_charters(content: Any, *, charters: dict[str, dict] | None = None) -> list[dict]:
    """规则⑥ 章程边界：direct 仓落在冻结演进态且无决策记录支撑即 BLOCKER。

    Args:
        content: 半可信蓝图 content dict。
        charters: ``blueprint_charter_match.aload_charters`` 的返回
            （``{repository_id: 章程正式字段}``）。**``None`` / ``{}`` → 整条规则返回
            ``[]``（跳过，不判 BLOCKER）**：``aload_charters`` 对缺章程的仓**不返回条目**、
            异常时整体返 ``{}``——章程读失败不该把整份蓝图判成违章。同理，章程 dict 里
            没有某个仓 = 该仓没有章程 = **跳过该仓**。

    Returns:
        - ``charter_violation`` **BLOCKER**：direct 仓的 ``evolution ∈
          {maintenance_only, deprecated}``（该仓不该再长新东西）且 ``decision_log`` 中
          **无该仓的支撑条目**——要在冻结仓动土，必须有决策记录背书；
        - ``charter_boundary_risk`` **WARNING**：该仓章程写了明文 ``boundaries[].rule``
          且本轮无决策记录支撑，提示人审逐条核对是否越界。``rule`` 是自由文本，强判
          BLOCKER 会产生不可复现的假阳性（A4），语义判定交 LLM 一类。

    ⚠️ **只读正式字段，绝不读 ``draft_content``**（``repositories/models.py`` 的草案字段
    不生效——AI 生成的章程草案不该反过来约束人）。
    """
    findings: list[dict] = []
    try:
        if not isinstance(charters, dict) or not charters:
            return findings
        data = content if isinstance(content, dict) else {}
        for assoc in _dict_list(data.get("repo_associations")):
            repository_id = str(assoc.get("repository_id") or "")
            if not repository_id:
                continue
            if str(assoc.get("role") or "").strip().lower() == "indirect":
                continue
            charter = charters.get(repository_id)
            if not isinstance(charter, dict):
                continue
            supported = _has_decision_support(data, repository_id)
            evolution = str(charter.get("evolution") or "").strip()
            if evolution in _FROZEN_EVOLUTIONS and not supported:
                _append(
                    findings,
                    _finding(
                        "charter_violation",
                        SEVERITY_BLOCKER,
                        section_path=f"repo_associations[{repository_id}]",
                        repository_id=repository_id,
                        detail=f"direct 仓的章程演进态为 {evolution}（不应再承接新增改动），"
                        "且 decision_log 中没有该仓的决策记录支撑",
                    ),
                )
            if supported:
                continue
            for index, rule in enumerate(_charter_boundary_rules(charter)):
                _append(
                    findings,
                    _finding(
                        "charter_boundary_risk",
                        SEVERITY_WARNING,
                        section_path=f"repo_associations[{repository_id}]",
                        repository_id=repository_id,
                        detail=f"该仓章程第 {index + 1} 条明文边界需人审逐条核对是否越界"
                        f"（自由文本，弱判据）：{rule[:_MAX_SNIPPET_CHARS]}",
                    ),
                )
    except Exception:  # noqa: BLE001 — 半可信输入恒不抛（同 check_preconditions）
        return findings
    return findings


def check_gate_lock(content: Any, *, locked_snapshot: Any = None) -> list[dict]:
    """确认门锁定校验：偏离 112 阶段 1 锁定的仓库集 / 角色 / 职责即 BLOCKER。

    Args:
        content: 半可信蓝图 content dict。
        locked_snapshot: 114-03 传 ``session.stage_state["confirmation"]``（兼容
            ``{"repos": [...]}`` 与裸 list 两种形状）。为空时**回落**到 content 内
            ``confirmed_at_gate is True`` 的条目自比对——此时只能检出「锁定条目被整条
            移除」（自比对的角色/职责必然相等），docstring 明写此降级边界。

    基线投影复用 ``blueprint_repo_plan._normalize_locked_repos``（函数内 lazy import：
    复用既有投影做对比基线可避免两处口径漂移，lazy 则守住本模块顶层零 ORM 的纪律）。

    Returns:
        逐条 **BLOCKER**，``section_path`` 用稳定锚
        ``repo_associations[{rid}].responsibility``、``block_id`` 用 112 写入侧的稳定命名
        ``blk_gate_resp_{rid}``（``blueprint_confirm_gate.py:291-303``）。

        ⭐ **三种偏离各有独立 ``rule_id``**（:data:`RULE_GATE_LOCK_MISSING` /
        :data:`RULE_GATE_LOCK_ROLE` / :data:`RULE_GATE_LOCK_RESPONSIBILITY`，114-MN-03）：
        同一个仓可以**同时**角色与职责都偏离，而三者的 ``section_path`` / ``block_id``
        逐字相同 ⇒ 共用一个 ``rule_id`` 就会让 :func:`finding_dedupe_key` 对它们返回同一个
        键，后果分两轮：第一轮 ``existing`` 是循环**之前**一次性查好的索引 ⇒ 第二条又开一条
        内容不同的重复线程，且 ``landed[key]`` 被它覆盖 ⇒ 第一条的 thread_id 从
        ``unresolved`` 快照里消失（面板上有线程、清单里找不到）；第二轮起
        ``_aload_finding_threads`` 的 ``index.setdefault`` 只保留其中一条，另一条既拿不到
        「第 N 轮仍存在」留痕，也**不进「本轮已消失 → resolve」的收尾循环**（它压根不在
        ``existing`` 里）—— 一条 ``open + blocking`` 的 BLOCKER 线程从此**永久挡住
        confirm**，只能靠人工 dismiss 清掉。
        把形态写进 ``rule_id``（而不是 ``section_path``）的理由：``finding_dedupe_key``
        **优先取 ``block_id``**，改 ``section_path`` 根本不影响键；而 ``rule_id`` 是
        ``_aload_finding_threads`` 唯一能从线程首条消息 ``[rule_id]`` 前缀反查回来的段，
        改它才能让两轮的键都真的分开。``block_id`` 不动 ⇒ 锚定仍指向同一个真实块。

    偏离 112 锁定即 BLOCKER——**要变必须重开确认门**，不允许在阶段 3 之后悄悄改仓库集或
    职责（114-CONTEXT 锁定）。
    """
    findings: list[dict] = []
    try:
        from services.process_runtime.blueprint_repo_plan import _normalize_locked_repos

        data = content if isinstance(content, dict) else {}
        baseline = _normalize_locked_repos(_snapshot_repos(locked_snapshot))
        if not baseline:
            baseline = _normalize_locked_repos(
                [
                    assoc
                    for assoc in _dict_list(data.get("repo_associations"))
                    if assoc.get("confirmed_at_gate") is True
                ]
            )
        if not baseline:
            return findings
        current = {
            entry["repository_id"]: entry
            for entry in _normalize_locked_repos(data.get("repo_associations"))
        }
        for entry in sorted(baseline, key=lambda item: item["repository_id"]):
            repository_id = entry["repository_id"]
            section_path = f"repo_associations[{repository_id}].responsibility"
            block_id = f"blk_gate_resp_{repository_id}"
            actual = current.get(repository_id)
            if actual is None:
                _append(
                    findings,
                    _finding(
                        RULE_GATE_LOCK_MISSING,
                        SEVERITY_BLOCKER,
                        section_path=section_path,
                        block_id=block_id,
                        repository_id=repository_id,
                        detail="确认门锁定的仓在当前 repo_associations 中已消失"
                        "（要移除必须重开确认门）",
                    ),
                )
                continue
            if str(actual.get("role") or "") != str(entry.get("role") or ""):
                _append(
                    findings,
                    _finding(
                        RULE_GATE_LOCK_ROLE,
                        SEVERITY_BLOCKER,
                        section_path=section_path,
                        block_id=block_id,
                        repository_id=repository_id,
                        detail=f"角色偏离确认门锁定：锁定 {entry.get('role')}，"
                        f"当前 {actual.get('role')}",
                    ),
                )
            if (
                _blocks_text(actual.get("responsibility")).strip()
                != _blocks_text(entry.get("responsibility")).strip()
            ):
                _append(
                    findings,
                    _finding(
                        RULE_GATE_LOCK_RESPONSIBILITY,
                        SEVERITY_BLOCKER,
                        section_path=section_path,
                        block_id=block_id,
                        repository_id=repository_id,
                        detail="职责文本偏离确认门锁定（要改职责必须重开确认门）",
                    ),
                )
    except Exception:  # noqa: BLE001 — 半可信输入恒不抛（同 check_preconditions）
        return findings
    return findings


def run_mechanical_rules(
    content: Any, *, charters: dict[str, dict] | None = None, locked_snapshot: Any = None
) -> list[dict]:
    """六类机械规则总入口（**无 LLM / 无 DB / 无网络**），返回分级 findings。

    执行顺序（**确定性**：同一输入输出逐字相等，含顺序）：

    0. :func:`check_preconditions`——**非空即 return（短路）**，后七条一律不跑；
    1. :func:`check_schema` → 2. :func:`check_citations` → 3. :func:`check_roles` →
       4. :func:`check_api_closure` → 5. :func:`check_prohibitions` →
       6. :func:`check_charters` → 7. :func:`check_gate_lock`。

    确定性靠两条纪律保证：固定的调用顺序 + 集合运算前一律 ``sorted()``——**禁止依赖
    dict / set 的迭代顺序**，否则同一蓝图两次审查会给出顺序不同的清单，去重与「第 N 轮
    仍存在」的比对全部失真。

    Args:
        content: 半可信蓝图 content dict。
        charters: 规则⑥的章程字典（``None`` ⇒ 规则⑥跳过，见 :func:`check_charters`）。
        locked_snapshot: 确认门锁定快照（见 :func:`check_gate_lock`）。

    Returns:
        finding 六键 dict 列表，条数受 :data:`_MAX_FINDINGS` 约束。**绝不抛**；异常时返回
        **已积累的结果**（不是空结果——已判出的缺陷不该因后续步骤出错而丢失）。
    """
    findings: list[dict] = []
    try:
        preconditions = check_preconditions(content)
        if preconditions:
            return preconditions
        for entry in check_schema(content):
            _append(findings, entry)
        for entry in check_citations(content):
            _append(findings, entry)
        for entry in check_roles(content):
            _append(findings, entry)
        for entry in check_api_closure(content):
            _append(findings, entry)
        for entry in check_prohibitions(content):
            _append(findings, entry)
        for entry in check_charters(content, charters=charters):
            _append(findings, entry)
        for entry in check_gate_lock(content, locked_snapshot=locked_snapshot):
            _append(findings, entry)
    except Exception:  # noqa: BLE001 — 恒不抛且返回已积累结果（同 blueprint_reconcile:127）
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


# ---------------------------------------------------------------------------
# goal-backward LLM 节（**唯一** LLM 一类，best-effort 返 None）
# ---------------------------------------------------------------------------


async def agoal_backward_review(
    *,
    feature_points: list[dict[str, Any]],
    impl_items: list[dict[str, Any]],
    constraints: Any = None,
    test_strategy: Any = None,
    must_haves: Any = None,
    key_links: Any = None,
    session_id: str = "",
    operator_instruction: str = "",
) -> list[dict] | None:
    """goal-backward 逆向核对（**本模块唯一的 LLM 调用点**）；不可得时返回 ``None``。

    逆向核对四件事（114-CONTEXT 锁定）：每个功能点的 ``acceptance_criteria`` 是否被实现项
    与 ``test_strategy`` 覆盖、``must_haves.truths`` 是否有实现项支撑、``key_links`` 两端是
    否都存在，以及 ⭐ **逐条核对实现项/契约是否与某条 ``constraints`` 实质冲突**。

    ⭐ **``constraints`` 形参是 B5 的落点**（``requirement_spec.constraints``，弱 schema
    array，元素 ``{id, text, kind, citations}``）：它使 114-CONTEXT 规则⑤第三条「不得与
    constraints 冲突」**真正可判**——机械规则只覆盖引用悬空
    （``constraint_ref_dangling``，见 :func:`check_prohibitions`），**语义冲突在此**，模型
    以 ``rule_id="constraint_conflict"`` 回报。两条降级路径**均为已登记的降级、都不当作
    「无冲突」放行**：``constraints`` 缺失 ⇒ digest 里显式写
    :data:`_NO_CONSTRAINTS_NOTICE` 且 ``*_started`` 事件带 ``constraint_count=0``；LLM
    不可得 ⇒ :func:`normalize_review_findings` 产 ``goal_backward_unavailable`` warning
    meta finding。

    **独立 fresh context**：prompt 只喂 :func:`_goal_backward_digest` 的裁剪投影，
    **不带任何起草 / 融合会话历史**（114-CONTEXT 锁定，降相关性偏差——带着自己的起草上下文
    去自查，模型倾向于确认而非证伪）。

    Returns:
        成功 → 经 :func:`normalize_review_findings` 归一的 finding 列表（LLM 原始输出**从不
        直接进业务**）。``None`` 的语义是 **「goal-backward 一类不可得」**（无默认模型 /
        响应不可解析 / 调用异常），上游必须 fail-closed，**绝不当作「无问题」放行**；机械
        六类照常跑，审查不因 LLM 挂掉而空转。本函数 best-effort，**不外抛**。
    """
    started = time.monotonic()
    constraints_digest = _constraints_digest(constraints)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        logger.info(
            "blueprint_review_goal_backward_started",
            category="sampling",
            component="process_runtime",
            session_id=session_id,
            feature_point_count=len(feature_points or []),
            impl_item_count=len(impl_items or []),
            # constraint_count=0 是 B5 降级的**可见信号**：本轮约束冲突判定不可判。
            constraint_count=len(constraints_digest),
            has_must_haves=bool(must_haves),
            has_key_links=bool(key_links),
        )

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.warning(
                "blueprint_review_goal_backward_no_default_model",
                category="sampling",
                component="process_runtime",
                session_id=session_id,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return None

        model = build_chat_model(resolved, model_name, streaming=False)
        digest = _goal_backward_digest(
            feature_points=feature_points,
            impl_items=impl_items,
            constraints_digest=constraints_digest,
            test_strategy=test_strategy,
            must_haves=must_haves,
            key_links=key_links,
        )
        # 节点重跑的操作员补充指令（quick 260806）：重审时作为审查重点提示。
        # 无指令时为空串、digest 与改动前逐字一致（fresh context 纪律不受影响——
        # 指令是人给的审查要求，不是起草会话历史）。
        note = str(operator_instruction or "").strip()
        if note:
            digest = (
                f"{digest}\n\n### 操作员补充指令（本轮审查须重点核对）\n{note[:_MAX_PROMPT_CHARS]}"
            )
        messages = [
            SystemMessage(content=_goal_backward_system_prompt()),
            HumanMessage(content=digest),
        ]
        with use_call_source(CallSource.BLUEPRINT_AI_REVIEW):
            response = await model.ainvoke(messages)

        parsed = _parse_object_json(_content_to_text(response.content))
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        if parsed is None:
            logger.warning(
                "blueprint_review_goal_backward_failed",
                category="sampling",
                component="process_runtime",
                session_id=session_id,
                reason="unparsable_response",
                duration_ms=duration_ms,
            )
            return None

        findings = normalize_review_findings(parsed.get("findings"))
        logger.info(
            "blueprint_review_goal_backward_completed",
            category="sampling",
            component="process_runtime",
            session_id=session_id,
            finding_count=len(findings),
            # 只记计数与分级分布——**finding 正文绝不进日志**（T-114-10）。
            blocker_count=sum(1 for item in findings if item["severity"] == SEVERITY_BLOCKER),
            warning_count=sum(1 for item in findings if item["severity"] == SEVERITY_WARNING),
            info_count=sum(1 for item in findings if item["severity"] == SEVERITY_INFO),
            duration_ms=duration_ms,
        )
        return findings
    except Exception as exc:  # noqa: BLE001 — best-effort：上游按 fail-closed 处理 None
        logger.warning(
            "blueprint_review_goal_backward_failed",
            category="sampling",
            component="process_runtime",
            session_id=session_id,
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return None


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


def _associations(content: Any) -> list[dict]:
    """``repo_associations`` 的 dict 元素列表。"""
    if not isinstance(content, dict):
        return []
    return _dict_list(content.get("repo_associations"))


def _support_repository_resolved(associations: list[dict], support_id: str) -> bool:
    return is_resolvable_repository_alias(associations, support_id)


def _direction(contract: Any) -> str:
    """契约方向归一（大小写与首尾空白不敏感）。合法值只有
    :data:`_DIRECTION_PROVIDED` / :data:`_DIRECTION_CONSUMED`。"""
    if not isinstance(contract, dict):
        return ""
    return str(contract.get("direction") or "").strip().lower()


def _snippet(text: str, start: int) -> str:
    """命中片段：以命中位置为起点取 ≤ :data:`_MAX_SNIPPET_CHARS` 字符。

    **只带片段不带整块正文**——finding 会进线程 body，而 block 文本是半可信内容（可能夹带
    代码片段/凭证样本），整段搬运等于把正文外泄面放大（T-114-10）。
    """
    head = max(start, 0)
    return str(text or "")[head : head + _MAX_SNIPPET_CHARS].strip()


def _out_of_scope_terms(content: Any) -> list[str]:
    """``requirement_spec.boundaries.out_of_scope`` 归一为词条列表。

    容忍 ``list[str]`` 与 ``list[dict]`` 两种形状（``boundaries`` 是弱 schema object，
    ``blueprint_schema.py:216-219``）：dict 取 ``text`` / ``name``。
    """
    if not isinstance(content, dict):
        return []
    spec = content.get("requirement_spec")
    boundaries = spec.get("boundaries") if isinstance(spec, dict) else None
    raw = boundaries.get("out_of_scope") if isinstance(boundaries, dict) else None
    if not isinstance(raw, list):
        return []
    terms: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            text = ""
            for key in ("text", "name", "title"):
                text = str(item.get(key) or "").strip()
                if text:
                    break
        else:
            text = str(item or "").strip()
        if text:
            terms.append(text)
    return terms


def _constraint_ids(content: Any) -> set[str]:
    """``requirement_spec.constraints[].id`` 集合（弱 schema array，逐字段 ``.get``）。"""
    if not isinstance(content, dict):
        return set()
    spec = content.get("requirement_spec")
    raw = spec.get("constraints") if isinstance(spec, dict) else None
    ids = {str(item.get("id") or "").strip() for item in _dict_list(raw)}
    ids.discard("")
    return ids


def _has_decision_support(content: Any, repository_id: str) -> bool:
    """``decision_log`` 中是否有该仓的决策记录支撑（弱 schema，三条判据取或）。

    判据：条目 ``repository_id`` 全等 / ``repository_ids`` 命中 / 文本字段
    （``question`` / ``answer`` / ``decision`` / ``text``）包含该仓 id 或仓名。
    ``decision_log`` 是弱 schema array（``blueprint_schema.py:733-736``），逐字段 ``.get``。
    """
    if not isinstance(content, dict) or not repository_id:
        return False
    names = {repository_id}
    for assoc in _dict_list(content.get("repo_associations")):
        if str(assoc.get("repository_id") or "") == repository_id:
            name = str(assoc.get("repository_name") or "").strip()
            if name:
                names.add(name)
    for entry in _dict_list(content.get("decision_log")):
        if str(entry.get("repository_id") or "") == repository_id:
            return True
        raw_ids = entry.get("repository_ids")
        if isinstance(raw_ids, list) and repository_id in {str(rid or "") for rid in raw_ids}:
            return True
        haystack = " ".join(
            _blocks_text(entry.get(key)) for key in ("question", "answer", "decision", "text")
        )
        if any(name and name in haystack for name in names):
            return True
    return False


def _charter_boundary_rules(charter: Any) -> list[str]:
    """章程 ``boundaries[].rule`` 的非空文本列表（``repositories/models.py:1144`` 形状）。

    **只读正式字段**——``draft_content`` 一律不读（草案不生效）。
    """
    if not isinstance(charter, dict):
        return []
    rules: list[str] = []
    for item in _dict_list(charter.get("boundaries")):
        rule = str(item.get("rule") or "").strip()
        if rule:
            rules.append(rule)
    return rules


def _snapshot_repos(snapshot: Any) -> Any:
    """确认门快照的仓清单（兼容 ``{"repos": [...]}`` 与裸 list 两种形状）。"""
    if isinstance(snapshot, dict):
        return snapshot.get("repos")
    if isinstance(snapshot, list):
        return snapshot
    return None


def _constraints_digest(raw: Any) -> list[dict]:
    """``requirement_spec.constraints`` → prompt digest 投影（B5 的输入裁剪）。

    每条只取 ``{id, kind, text}``（``text`` 截断至 :data:`_MAX_CONSTRAINT_TEXT_CHARS`），
    条数上界 :data:`_MAX_CONSTRAINTS`；非 list / 元素非 dict 一律跳过 ⇒ ``None`` 与类型
    错乱输入返回 ``[]``（**恒不抛**）。空结果即「本轮约束冲突判定不可判」，由
    :func:`_goal_backward_digest` 显式标注、由 ``constraint_count=0`` 事件可见。
    """
    digest: list[dict] = []
    if not isinstance(raw, list):
        return digest
    for item in raw:
        if len(digest) >= _MAX_CONSTRAINTS:
            break
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:_MAX_CONSTRAINT_TEXT_CHARS]
        constraint_id = str(item.get("id") or "").strip()
        if not text and not constraint_id:
            continue
        digest.append({"id": constraint_id, "kind": str(item.get("kind") or ""), "text": text})
    return digest


def _goal_backward_system_prompt() -> str:
    return (
        "你是资深技术评审。给定一份技术蓝图的**功能点验收标准、实现项、约束清单、验收锚点**，"
        "做 goal-backward 逆向核对：从「要达成什么」倒推「现在写下的东西够不够」。\n"
        "逐项核对：\n"
        "- 覆盖性：每个功能点的验收标准是否都有实现项与测试策略覆盖；缺口回报 "
        'rule_id="acceptance_uncovered"。\n'
        "- 锚点支撑：must_haves.truths 每条是否有实现项支撑；缺口回报 "
        'rule_id="truth_unsupported"。\n'
        "- 链接完整：key_links 的 from / to 两端是否都在实现项或契约中存在；缺口回报 "
        'rule_id="key_link_broken"。\n'
        "- **约束核对**：逐条核对是否有实现项或 API 契约与某条 constraint **实质冲突**；"
        '冲突回报 rule_id="constraint_conflict"，并在 detail 里引用该 constraint 的 id。\n'
        "要求：\n"
        '- 只输出 JSON，形如 {"findings": [{"rule_id": "..", "severity": "blocker|warning|info",'
        '"section_path": "..", "block_id": "", "repository_id": "", "detail": ".."}]}。\n'
        "- severity 只用 blocker / warning / info 三值；**判不准就给 warning 并说明缺什么，"
        "不要猜**——猜错的代价比多提一句大。\n"
        "- detail 一句话说清「缺什么 / 与什么冲突」，不要复述原文。\n"
        "- 没有发现问题就返回空数组，**不要编造 finding**。\n"
        "- 不要输出 JSON 以外的解释性文字。"
    )


def _section(title: str, body: str) -> str:
    """prompt 分节（各节独立截断，防单节撑爆 prompt）。"""
    return f"### {title}\n{str(body or '').strip()[:_MAX_PROMPT_CHARS] or '（未提供）'}"


def _goal_backward_digest(
    *,
    feature_points: Any,
    impl_items: Any,
    constraints_digest: list[dict],
    test_strategy: Any,
    must_haves: Any,
    key_links: Any,
) -> str:
    """goal-backward 的**裁剪投影** prompt（fresh context：不带任何起草/融合会话历史）。

    投影口径照 ``blueprint_merge._feature_point_digest`` / ``_impl_items_digest``：只搬结构
    字段与短文本，不把整份蓝图倒进 prompt。``constraints`` 一节为空时写死
    :data:`_NO_CONSTRAINTS_NOTICE`——**不静默落空**（B5 降级可见）。
    """
    fp_lines: list[str] = []
    for point in _dict_list(feature_points)[:_MAX_DIGEST_ITEMS]:
        title = str(point.get("title") or "").strip()[:_MAX_TITLE_CHARS]
        criteria = point.get("acceptance_criteria")
        criteria_text = (
            "；".join(str(item).strip() for item in criteria if str(item or "").strip())
            if isinstance(criteria, list)
            else ""
        )
        line = f"- [{str(point.get('id') or '-')}] {title or '（无标题）'}"
        if criteria_text:
            line += f"（验收：{criteria_text}）"
        fp_lines.append(line)

    item_lines: list[str] = []
    for item in _dict_list(impl_items)[:_MAX_DIGEST_ITEMS]:
        item_id = str(item.get("id") or item.get("item_id") or "-")
        title = str(item.get("title") or "").strip()[:_MAX_TITLE_CHARS]
        how = _blocks_text(item.get("how"))[:_MAX_NARRATIVE_CHARS]
        line = (
            f"- [{item_id}] ({str(item.get('repository_id') or '-')}"
            f"/{str(item.get('change_type') or '-')}) {title or '（无标题）'}"
        )
        if str(item.get("feature_point_id") or ""):
            line += f" ← {item['feature_point_id']}"
        if how:
            line += f"\n  怎么做：{how}"
        item_lines.append(line)

    constraint_lines = [
        f"- [{entry['id'] or '-'}] ({entry['kind'] or '-'}) {entry['text']}"
        for entry in constraints_digest
    ]

    truths = must_haves.get("truths") if isinstance(must_haves, dict) else must_haves
    truth_lines = [
        f"- {str(truth).strip()[:_MAX_TITLE_CHARS]}"
        for truth in (truths if isinstance(truths, list) else [])
        if str(truth or "").strip()
    ][:_MAX_DIGEST_ITEMS]

    raw_links = key_links
    if raw_links is None and isinstance(must_haves, dict):
        raw_links = must_haves.get("key_links")
    link_lines: list[str] = []
    for link in _dict_list(raw_links)[:_MAX_DIGEST_ITEMS]:
        link_lines.append(
            f"- {str(link.get('from') or '-')} → {str(link.get('to') or '-')}"
            f"（via {str(link.get('via') or '-')}）"
        )

    sections = [
        _section("功能点与验收标准", "\n".join(fp_lines)),
        _section("实现项", "\n".join(item_lines)),
        _section(
            "约束清单（逐条核对是否有实现项/契约与之实质冲突）",
            "\n".join(constraint_lines) or _NO_CONSTRAINTS_NOTICE,
        ),
        _section("测试策略", _blocks_text(test_strategy)),
        _section("验收锚点 truths", "\n".join(truth_lines)),
        _section("关键链接 key_links", "\n".join(link_lines)),
    ]
    return "\n\n".join(sections) + "\n\n请输出 goal-backward 逆向核对结果 JSON。"


def _content_to_text(content: Any) -> str:
    """LangChain ``message.content`` 归一为文本（兼容 str / 分块 list）。

    reasoning 模型（经兼容代理的 deepseek/glm 等）content 为 content_blocks 列表，直接
    ``str()`` 会得到 Python repr（单引号）致下游 ``json.loads`` 失败——只拼接含 text 的
    block。口径与 ``blueprint_ambiguity_score._content_to_text`` 同源。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content or "")


def _parse_object_json(text: str) -> dict[str, Any] | None:
    """从 LLM 文本中健壮提取顶层 JSON 对象（``` 围栏 + 裸 JSON 双路）。

    非 JSON / 非对象 → ``None``（调用方按 fail-closed 处理），本函数不外抛。
    """
    candidates: list[str] = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidates.append(text)
    for block in candidates:
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


# ══════════════════════════════════════════════════════════════════════════
# stage adapter 节（Phase 114-03 追加；上面 114-02 交付的判定内核一字未动）
# ══════════════════════════════════════════════════════════════════════════
#
# 本节把判定内核接进流程：入口三件接线（人工块保护 → 答案消费 → 批量重锚）→ 跑六类 +
# goal-backward → findings 批量落分级线程 → 有界回退归因 → 超界携未决清单进人审。
#
# 三条贯穿全节的纪律：
#
# 1. **INV-6**：线程/状态的写入一律经 ``BlueprintLifecycleService``，adapter 只做**只读**
#    查询（去重索引）。事件写入一律经 ``ConvergenceSessionService.aemit_event``。
# 2. **绝不落流程失败**：审查未清是「待人审」不是「流程失败」。本节没有任何一条路径产出
#    终态失败——超界走 ``exhausted`` 进 ``pending_review``，异常走 ``needs_clarification``
#    停在本 stage 等人处置。CAS 冲突与非法边同样吞成 ``needs_clarification``。
# 3. **正文零外泄**：finding 正文只进线程 body（人审面板），**绝不**进 ``stage_state``、
#    事件 payload 或日志；日志与 payload 只放计数、分级分布与关联键（T-114-20）。

# CONTEXT 锁定的合计 ≤2 轮；可被 ``SettingKeys.BLUEPRINT_REVIEW_CONFIG`` 的
# ``max_review_rounds`` 覆盖，此处是兜底（配置坏了绝不能卡死流水线）。
MAX_REVIEW_ROUNDS = 2

# 未决清单上界（对齐 ``blueprint_merge`` 的同名常量）：它进 stage_state（< 2KB 约定）
# 与人审面板，无界会把两者一起刷爆。
_MAX_UNRESOLVED = 30

# ``review()`` 的四个出口状态。handler 只据它走**白名单出边**，绝不透传本返回值。
REVIEW_PASSED = "passed"
REVIEW_RETRY = "retry"
REVIEW_EXHAUSTED = "exhausted"
REVIEW_NEEDS_CLARIFICATION = "needs_clarification"

# 归因回退的**仓级**目标。融合级目标用空串表示（handler 的映射是
# ``"repo_plan" → repo_rework``、其余 → ``remerge``，与 ``_h_bp_merge`` 逐字同款）——
# 本模块因此**不出现任何融合桶键的字面量**，「绝不写错桶」这条纪律可被 rg 硬验收。
BACK_TARGET_REPO_PLAN = "repo_plan"
BACK_TARGET_REMERGE = ""

# 线程恢复目标（``BlueprintThread.return_stage`` max_length=16，本值 12 字符；
# ``_CLARIFICATION_RETURN_TARGETS`` 已含它）。
RETURN_STAGE_AI_REVIEWING = "ai_reviewing"

# 开线程时 question 的 rule_id 前缀 ``[rule_id] 正文``——去重索引靠它从既有线程反查
# rule_id（``BlueprintThread`` 无 rule_id 字段，anchor 也不该被塞进业务标记）。
_RULE_ID_TAG = re.compile(r"^\[([A-Za-z0-9_]+)\]")


def _round_of(state: Any) -> int:
    """读 ``stage_state["ai_review"]["round"]``（照 ``blueprint_merge._attempt_of``）。"""
    bucket = (state or {}).get(STAGE_STATE_KEY) if isinstance(state, dict) else None
    try:
        return max(0, int((bucket or {}).get("round", 0)))
    except (TypeError, ValueError):
        return 0


def _bucket_of(state: Any) -> dict:
    """读本 stage 的 stage_state 桶（缺省空 dict）。"""
    bucket = (state or {}).get(STAGE_STATE_KEY) if isinstance(state, dict) else None
    return bucket if isinstance(bucket, dict) else {}


def _initiated_by(session: Any) -> str:
    """触发用户（照 ``blueprint_merge._initiated_by``）：解析不到记 ``system``。"""
    return (
        str(getattr(session, "initiated_by_user_id", "") or "")
        or str(getattr(session, "created_by_id", "") or "")
        or "system"
    )


def _decide_back_target(blockers: list[dict]) -> dict:
    """BLOCKER 清单 → **回退目标归因**（纯函数，零 ORM，可直接单测）。

    两档判定（形状照 ``blueprint_merge.decide_back_target`` 的恒定三键）：

    - 全部 BLOCKER 落在**同一个** ``repository_id`` → 回该仓的分仓方案阶段
      （证据是那一个仓的方案没写对，重跑融合一万次也补不出来）。
    - 跨仓、或一条也解析不出仓归属 → 回融合阶段重装配（缺陷在融合层）。

    Returns:
        恒定三键 ``{"back_target": str, "back_repository_id": str, "blocker_count": int}``。
        ``back_target`` 取 :data:`BACK_TARGET_REPO_PLAN` 或 :data:`BACK_TARGET_REMERGE`
        （空串 = 融合级）。空输入 → 三键取空/零。
    """
    entries = [item for item in (blockers or []) if isinstance(item, dict)]
    if not entries:
        return {"back_target": "", "back_repository_id": "", "blocker_count": 0}
    repositories = sorted({str(item.get("repository_id") or "").strip() for item in entries})
    if len(repositories) == 1 and repositories[0]:
        return {
            "back_target": BACK_TARGET_REPO_PLAN,
            "back_repository_id": repositories[0],
            "blocker_count": len(entries),
        }
    return {
        "back_target": BACK_TARGET_REMERGE,
        "back_repository_id": "",
        "blocker_count": len(entries),
    }


class BlueprintReviewAdapter:
    """``ai_review`` stage 的 adapter：判定内核 → 线程 / 状态 / 出边（FLOW-07 执行面）。

    ``review(session)`` 返回**恒定八键**（下游 handler 无需判空分支）::

        {"review_status": "passed"|"retry"|"exhausted"|"needs_clarification",
         "artifact_version_id": str, "round": int, "back_target": str,
         "back_repository_id": str, "report": dict, "stage_state": dict,
         "thread_ids": list[str]}

    出口语义：

    - ``passed``：零 BLOCKER（仅 WARNING/INFO 也算）→ 蓝图转 ``pending_review``，
      findings 作人审参考，**不打回**。
    - ``retry``：有 BLOCKER 且轮次未用尽 → 归因打回，蓝图转回 ``drafting``，
      **回退不落版本**（审查未过的中间产物不进版本历史）。
    - ``exhausted``：有 BLOCKER 且轮次用尽 → 蓝图转 ``pending_review`` **携未决清单**。
      ⚠️ **绝不落流程失败**：蓝图已成形，只是审查未清 —— 那是「待人审」。死锁出口由
      114-05 的 finding 处置端点提供（``resolve`` / ``dismiss`` 让线程离开
      ``{open, answered}``，confirm 守卫随之放行）。
    - ``needs_clarification``：入口接线报冲突、基线不可得、或整轮异常 → 停在本 stage
      等人处置（handler 会先确保有阻塞线程再自环）。
    """

    def __init__(
        self,
        *,
        artifact_service: Any = None,
        lifecycle_service: Any = None,
        session_service: Any = None,
        node_execution_id: str = "",
    ) -> None:
        self._artifact_service = artifact_service
        self._lifecycle_service = lifecycle_service
        self._session_service = session_service
        self.node_execution_id = node_execution_id

    # ── 主入口 ────────────────────────────────────────────────────────────

    async def review(self, session: Any) -> dict:
        """跑一轮 AI 对抗审查，返回恒定键结果（**绝不上抛**）。

        九步（顺序不可换）：

        0-b. **人工块保护**（B3）→ 0-a. **答案消费**（B1）→ 0-c. **批量重锚**
        → 1. 读审查基线 → 2. 取轮次与轮上界 → 3. 跑六类 + goal-backward
        → 4. findings 落线程 → 5. 出口判定与状态转移 → 6. stage_state 回写
        → 7. 完成事件与 ``duration_ms``。

        ⭐ **前三步必须在读审查基线之前跑完**：否则审的是「答案未回灌、人工块已被抹掉」
        的旧内容 —— 审查结论会指向一份马上就要被改写的文档。
        """
        started = time.monotonic()
        state = getattr(session, "stage_state", None)
        state = state if isinstance(state, dict) else {}
        round_no = _round_of(state)
        initiated_by = _initiated_by(session)
        # ⚠️ 事件里的 `round` 是**给人看的 1-based「第几轮」**，与 `stage_state` 里 0-based 的
        # 重试计数器 `round_no` 不是一回事。曾经两者混用 ⇒ 同一轮的 started 显示「轮次 0」、
        # completed 显示「轮次 1」，界面上像是漏了一轮。⛔ 不要把这里改成裸 `round_no`：
        # 计数器语义归计数器（`_bucket` / `_result` 用它判有界重试，T-114-14），展示归展示。
        await self._aemit(session, _event("STARTED"), {"round": round_no + 1})
        try:
            return await self._areview(
                session,
                state=state,
                round_no=round_no,
                initiated_by=initiated_by,
                started=started,
            )
        except Exception as exc:  # noqa: BLE001 — 审查异常绝不上抛（上抛 = engine 落终态失败）
            await self._aemit(session, _event("FAILED"), {"round": round_no + 1})
            self._log(
                "blueprint_review_failed",
                session,
                level="warning",
                round=round_no,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                error=redact_secrets_in_text(str(exc))[:_MAX_DETAIL_CHARS],
            )
            return self._result(
                REVIEW_NEEDS_CLARIFICATION, round_no=round_no, report={"reason": "review_failed"}
            )

    async def _areview(
        self, session: Any, *, state: dict, round_no: int, initiated_by: str, started: float
    ) -> dict:
        artifact = await self._aload_artifact(session)
        if artifact is None:
            return self._result(
                REVIEW_NEEDS_CLARIFICATION,
                round_no=round_no,
                report={"reason": "artifact_unavailable"},
            )

        # ── 0-b：人工块保护（B3）─────────────────────────────────────────
        # 打回后 `repo_rework` / `remerge` 会重跑融合并 `add_version`，那是本相位**主要
        # 的产版本路径**。融合模块是只读受限面（本 plan 一行不改），所以保护挂在这里 ——
        # 每次进入 ai_review 都先把版本链里 `produced_by_ref` 带 `human_edit:` 的 block
        # 逐一比对：等价保留、实质冲突则写回人工版本并开阻塞线程。
        #
        # ⚠️ 停等判据看 `status == "conflict"`（等价于 `conflicted` 非空），**不看
        # `preserved`** —— 后者是前者的**子集**（差集 = 当前态整块缺失、无落位可写回的
        # 块），拿它当判据会漏掉「块被重装删掉」这一档冲突（114-04 契约明写）。
        guard_status = "skipped"
        try:
            guard = await self._acall_reflow(
                "arestore_human_blocks", artifact, session=session, initiated_by=initiated_by
            )
            guard_status = str(guard.get("status") or "")
            if guard_status == "conflict":
                self._log(
                    "blueprint_review_human_block_conflict",
                    session,
                    level="warning",
                    round=round_no,
                    conflicted_count=len(guard.get("conflicted") or []),
                    thread_id=str(guard.get("thread_id") or ""),
                )
                return self._result(
                    REVIEW_NEEDS_CLARIFICATION,
                    round_no=round_no,
                    report={"reason": "human_block_conflict"},
                )
        except Exception as exc:  # noqa: BLE001 — 保护失败只 warning，不阻断审查
            guard_status = "error"
            self._log(
                "blueprint_review_human_block_guard_skipped",
                session,
                level="warning",
                round=round_no,
                error=redact_secrets_in_text(str(exc))[:_MAX_DETAIL_CHARS],
            )

        # ── 0-a：答案消费（B1）──────────────────────────────────────────
        # 本调用是 `aapply_thread_answers` 的**两个生产调用方之一**（另一个是 114-05 的
        # answer 端点）。少了它，人在打回轮之间作答的线程永不被消费 ⇒ 答案不落地、
        # 同一问题会被反复问（T-114-16b）。`section_writer` 不传 ⇒ 走 114-04 的生产实现
        # `ablock_section_writer`（它**不是** no-op）。
        reflow_status = "skipped"
        try:
            reflow = await self._acall_reflow(
                "aapply_thread_answers", artifact, session=session, initiated_by=initiated_by
            )
            reflow_status = str(reflow.get("status") or "")
            if reflow_status == "conflict":
                # 已开阻塞线程等人裁决 ⇒ 不带着待裁决冲突继续审（审一份马上要被改的内容
                # 只会产出一份马上作废的结论）。
                self._log(
                    "blueprint_review_answer_reflow_conflict",
                    session,
                    level="warning",
                    round=round_no,
                    conflict_block_count=len(reflow.get("conflict_block_ids") or []),
                    thread_id=str(reflow.get("thread_id") or ""),
                )
                return self._result(
                    REVIEW_NEEDS_CLARIFICATION,
                    round_no=round_no,
                    report={"reason": "answer_reflow_conflict"},
                )
        except Exception as exc:  # noqa: BLE001 — 回灌失败只 warning，不阻断审查
            reflow_status = "error"
            self._log(
                "blueprint_review_answer_reflow_skipped",
                session,
                level="warning",
                round=round_no,
                error=redact_secrets_in_text(str(exc))[:_MAX_DETAIL_CHARS],
            )

        # ── 1：读**最新**版本作审查基线 ─────────────────────────────────
        # ⛔ 绝不读 `session.current_artifact_version`：融合的 `add_version` 已推进最新版本
        # 而会话指针只在显式 StageOutcome 里更新，读它会审到旧内容。0-a/0-b 可能刚落了
        # 新版本，故必须在此**重读**，不得复用入口处的快照。
        from delivery.models import ArtifactVersion

        version = await (
            ArtifactVersion.objects.select_related("supersedes")
            .filter(artifact=artifact)
            .order_by("-version_no")
            .afirst()
        )
        if version is None or not isinstance(version.content, dict):
            # fail-closed：读不到基线绝不判通过（判通过 = 带缺陷蓝图静默升人审）。
            return self._result(
                REVIEW_NEEDS_CLARIFICATION,
                round_no=round_no,
                report={"reason": "baseline_unavailable"},
            )
        content = version.content

        # ── 0-c：批量重锚（B3 第二件，判据 = **版本推进**而非「本轮是否产版本」）──
        anchored_version_id = await self._areanchor_if_advanced(
            session,
            artifact,
            version,
            state=state,
            initiated_by=initiated_by,
        )

        self._log(
            "blueprint_review_started",
            session,
            round=round_no,
            artifact_version_id=str(version.id),
            reflow_status=reflow_status,
            guard_status=guard_status,
        )

        # ── 2：轮次与轮上界 ─────────────────────────────────────────────
        max_rounds = await self._aload_review_config()

        # ── 3：跑判定（六类机械规则 + goal-backward 一类）────────────────
        charters = await self._aload_charters(content)
        locked_snapshot = state.get("confirmation")
        mechanical = run_mechanical_rules(
            content, charters=charters, locked_snapshot=locked_snapshot
        )
        # ⚠️ `agoal_backward_review` 返 None 的语义是「该类不可得」而非「无问题」——
        # `normalize_review_findings(None)` 会产一条 WARNING meta finding（fail-closed）。
        llm = await self._agoal_backward(content, session)
        findings = (mechanical + normalize_review_findings(llm))[:_MAX_FINDINGS]
        blockers = [item for item in findings if item["severity"] == SEVERITY_BLOCKER]
        warnings = [item for item in findings if item["severity"] == SEVERITY_WARNING]
        infos = [item for item in findings if item["severity"] == SEVERITY_INFO]

        # ── 4：findings → 分级线程（去重留痕 / 新开 / 消失即收尾）────────
        landed = await self._aland_findings(
            session,
            artifact,
            version,
            findings,
            content=content,
            round_no=round_no,
            initiated_by=initiated_by,
        )

        counts = {
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "info_count": len(infos),
            "thread_count": len(landed),
        }
        thread_ids = sorted(landed.values())

        # ── 5：出口判定 + 状态转移（全经 lifecycle）──────────────────────
        from delivery.models import BlueprintStatus

        if not blockers:
            # 仅 WARNING/INFO（或全清）→ 直接升人审，**不打回**（CONTEXT 锁定）。
            ok = await self._atransition(
                session, artifact, BlueprintStatus.PENDING_REVIEW, initiated_by=initiated_by
            )
            status = REVIEW_PASSED if ok else REVIEW_NEEDS_CLARIFICATION
            bucket = self._bucket(
                round_no=round_no,
                status=status,
                counts=counts,
                thread_ids=thread_ids,
                unresolved=[],
                anchored_version_id=anchored_version_id,
            )
            self._log(
                "blueprint_review_passed",
                session,
                round=round_no,
                artifact_version_id=str(version.id),
                **counts,
            )
            return await self._afinish(
                session,
                status,
                round_no=round_no,
                emitted_round=round_no + 1,
                artifact_version_id=str(version.id),
                bucket=bucket,
                counts=counts,
                thread_ids=thread_ids,
                started=started,
            )

        decision = _decide_back_target(blockers)
        if round_no + 1 <= max_rounds:
            # 有界回退：**不落版本**（审查未过的中间产物不进版本历史），轮次单点递增后
            # 整桶回写本 stage 的桶（**绝不**碰融合桶：那个桶会被融合侧整桶覆盖，
            # 计数归零 ⇒ 无限打回循环，T-114-14）。
            ok = await self._atransition(
                session, artifact, BlueprintStatus.DRAFTING, initiated_by=initiated_by
            )
            status = REVIEW_RETRY if ok else REVIEW_NEEDS_CLARIFICATION
            bucket = self._bucket(
                round_no=round_no + 1 if ok else round_no,
                status=status,
                counts=counts,
                thread_ids=thread_ids,
                unresolved=[],
                anchored_version_id=anchored_version_id,
                attribution=decision,
            )
            self._log(
                "blueprint_review_retry",
                session,
                level="warning",
                round=round_no + 1,
                back_target=decision["back_target"],
                **counts,
            )
            return await self._afinish(
                session,
                status,
                round_no=round_no + 1 if ok else round_no,
                emitted_round=round_no + 1,
                artifact_version_id=str(version.id),
                bucket=bucket,
                counts=counts,
                thread_ids=thread_ids,
                started=started,
                back_target=decision["back_target"],
                back_repository_id=decision["back_repository_id"],
            )

        # 轮次用尽 → 携未决清单进人审。⚠️ **绝不落流程失败**（同融合侧超界纪律）：
        # 蓝图已成形，只是审查未清。未决清单只含定位标量、**零正文**。
        unresolved = self._unresolved(blockers, landed)
        ok = await self._atransition(
            session, artifact, BlueprintStatus.PENDING_REVIEW, initiated_by=initiated_by
        )
        status = REVIEW_EXHAUSTED if ok else REVIEW_NEEDS_CLARIFICATION
        bucket = self._bucket(
            round_no=round_no,
            status=status,
            counts=counts,
            thread_ids=thread_ids,
            unresolved=unresolved,
            anchored_version_id=anchored_version_id,
            attribution=decision,
        )
        self._log(
            "blueprint_review_exhausted",
            session,
            level="warning",
            round=round_no,
            max_rounds=max_rounds,
            unresolved_count=len(unresolved),
            **counts,
        )
        return await self._afinish(
            session,
            status,
            round_no=round_no,
            emitted_round=round_no + 1,
            artifact_version_id=str(version.id),
            bucket=bucket,
            counts=counts,
            thread_ids=thread_ids,
            started=started,
            back_target=decision["back_target"],
            back_repository_id=decision["back_repository_id"],
            report={"unresolved_count": len(unresolved), "max_rounds": max_rounds},
        )

    # ── 入口接线（三件全部只调 114-04 的交付，本模块不复制实现）───────────

    async def _acall_reflow(
        self, name: str, artifact: Any, *, session: Any, initiated_by: str
    ) -> dict:
        """调 114-04 的回灌/保护入口（函数内 lazy import，返回值归一成 dict）。"""
        from services.process_runtime import blueprint_reflow

        handler = getattr(blueprint_reflow, name)
        result = await handler(
            artifact,
            session=session,
            initiated_by_user_id=initiated_by,
            artifact_service=self._artifact_service,
            lifecycle_service=self._lifecycle_service,
        )
        return result if isinstance(result, dict) else {}

    async def _areanchor_if_advanced(
        self, session: Any, artifact: Any, version: Any, *, state: dict, initiated_by: str
    ) -> str:
        """版本推进过就批量重锚一次线程，返回本轮之后的 ``anchored_version_id``。

        ⭐ **判据是「版本推进」而不是「本轮是否产版本」**：B3 点名的主路径是
        ``repo_rework`` / ``remerge`` **重跑融合产的版本** —— 它由融合侧落库，此时若既无
        已作答线程也无人工块，0-a/0-b 都不产版本；以「本轮是否产版本」为判据会让重锚
        **永不触发**，线程 anchor 仍指向已消失的 block（115 的批注全部错位/凭空消失，
        CLAR-02 明令禁止）。故这里**无条件**比对「artifact 当前最新版本」与「上次已重锚
        版本」，不一致即重锚。

        best-effort：失败只 warning 且**不回写** ``anchored_version_id``（下一轮自然重试），
        绝不阻断审查。
        """
        latest_id = str(version.id)
        anchored = str(_bucket_of(state).get("anchored_version_id") or "")
        if anchored == latest_id:
            return anchored
        try:
            previous = getattr(version, "supersedes", None)
            old_content = getattr(previous, "content", None)
            if anchored and (previous is None or str(previous.id) != anchored):
                from delivery.models import ArtifactVersion

                row = await ArtifactVersion.objects.filter(id=anchored).afirst()
                old_content = getattr(row, "content", None) if row is not None else old_content
            report = await self._lifecycle().areanchor_threads(
                artifact,
                version.content,
                old_content=old_content if isinstance(old_content, dict) else None,
                initiated_by_user_id=initiated_by,
            )
            report = report if isinstance(report, dict) else {}
            self._log(
                "blueprint_review_threads_reanchored",
                session,
                artifact_version_id=latest_id,
                checked=int(report.get("checked") or 0),
                reanchored=int(report.get("reanchored") or 0),
                orphaned=int(report.get("orphaned") or 0),
                skipped=int(report.get("skipped") or 0),
            )
            return latest_id
        except Exception as exc:  # noqa: BLE001 — 重锚失败不阻断审查，下一轮重试
            self._log(
                "blueprint_review_reanchor_skipped",
                session,
                level="warning",
                artifact_version_id=latest_id,
                error=redact_secrets_in_text(str(exc))[:_MAX_DETAIL_CHARS],
            )
            return anchored

    # ── 判定输入装配 ──────────────────────────────────────────────────────

    async def _aload_charters(self, content: dict) -> dict[str, dict]:
        """规则⑥的章程字典（best-effort：读不到返回 ``{}``，规则⑥自动跳过）。"""
        try:
            from services.process_runtime.blueprint_charter_match import aload_charters

            ids = [
                str(assoc.get("repository_id") or "")
                for assoc in (content.get("repo_associations") or [])
                if isinstance(assoc, dict)
            ]
            return await aload_charters([rid for rid in ids if rid])
        except Exception:  # noqa: BLE001 — 章程读失败不该把「有缺陷」升级成「整轮失败」
            return {}

    async def _agoal_backward(self, content: dict, session: Any) -> list[dict] | None:
        """goal-backward 一类（唯一 LLM 调用点，``call_source`` 已由 114-02 注册）。

        任何异常 → ``None``：调用方会把它归一成 ``goal_backward_unavailable`` WARNING
        meta finding（fail-closed，**绝不当作「无问题」**）。
        """
        try:
            from services.process_runtime.blueprint_stage_rerun import operator_instruction

            spec = content.get("requirement_spec")
            spec = spec if isinstance(spec, dict) else {}
            overview = content.get("implementation_overview")
            overview = overview if isinstance(overview, dict) else {}
            impl_items = _dict_list(overview.get("items"))
            must_haves = content.get("must_haves")
            must_haves = must_haves if isinstance(must_haves, dict) else {}
            return await agoal_backward_review(
                feature_points=_dict_list(spec.get("feature_points")),
                impl_items=impl_items,
                constraints=spec.get("constraints"),
                test_strategy=[
                    item.get("test_strategy") for item in impl_items if item.get("test_strategy")
                ],
                must_haves=must_haves,
                key_links=must_haves.get("key_links"),
                session_id=str(getattr(session, "id", "")),
                operator_instruction=operator_instruction(session),
            )
        except Exception:  # noqa: BLE001 — 不可得即 None（下游 fail-closed 成 WARNING）
            return None

    # ── findings → 线程 ───────────────────────────────────────────────────

    async def _aland_findings(
        self,
        session: Any,
        artifact: Any,
        version: Any,
        findings: list[dict],
        *,
        content: dict,
        round_no: int,
        initiated_by: str,
    ) -> dict[str, str]:
        """findings 批量落分级线程，返回 ``{dedupe_key: thread_id}``。

        三条通道（对应 finding 的三种生命周期）：

        - **本轮仍在且已有线程** → :meth:`append_note` 追加「第 N 轮仍存在」留痕。
          ⛔ 绝不用会把 ``open`` 推到 ``answered`` 的作答通道：那会让
          ``ahas_open_blocking_threads`` 判为无门 ⇒ 人审能通过带未决 BLOCKER 的蓝图
          ⇒ 续驱的 pause 判据一并失守（T-114-16，112 教训）。
        - **本轮新出现** → :meth:`open_thread`（``severity`` 与 ``blocking`` **同源派生**，
          错配会被 114-01 的不变式 raise）。
        - **本轮已消失** → :meth:`resolve_thread`（幂等，终态重复调用 no-op）。

        单条失败 best-effort 吞掉（warning + 继续下一条）：绝不让一条 finding 落库失败
        把整轮审查打成异常。
        """
        from delivery.models import ThreadKind

        lifecycle = self._lifecycle()
        existing = await self._aload_finding_threads(artifact)
        landed: dict[str, str] = {}
        for finding in findings:
            key = finding_dedupe_key(finding)
            thread = existing.get(key)
            try:
                if thread is not None:
                    await lifecycle.append_note(
                        thread,
                        body=f"第 {round_no + 1} 轮仍存在：{finding['detail']}",
                        initiated_by_user_id=initiated_by,
                    )
                    landed[key] = str(thread.id)
                    continue
                severity = finding["severity"]
                opened = await lifecycle.open_thread(
                    artifact,
                    kind=ThreadKind.AI_REVIEW_FINDING,
                    severity=severity,
                    blocking=(severity == SEVERITY_BLOCKER),
                    question=f"[{finding['rule_id']}] {finding['detail']}",
                    anchor={
                        "section_path": finding["section_path"],
                        "block_id": finding["block_id"],
                        "quoted_text": _quoted_text(content, finding["block_id"]),
                    },
                    created_on_version=version,
                    initiated_by_user_id=initiated_by,
                    return_stage=RETURN_STAGE_AI_REVIEWING,
                )
                landed[key] = str(opened.id)
            except Exception as exc:  # noqa: BLE001 — 单条落库失败不牵连整轮
                self._log(
                    "blueprint_review_finding_thread_failed",
                    session,
                    level="warning",
                    rule_id=str(finding.get("rule_id") or ""),
                    severity=str(finding.get("severity") or ""),
                    error=redact_secrets_in_text(str(exc))[:_MAX_DETAIL_CHARS],
                )
        for key, thread in existing.items():
            if key in landed:
                continue
            try:
                await lifecycle.resolve_thread(
                    thread,
                    resolution="本轮复检已不再命中该规则。",
                    initiated_by_user_id=initiated_by,
                )
            except Exception as exc:  # noqa: BLE001 — 收尾失败不牵连整轮
                self._log(
                    "blueprint_review_finding_resolve_failed",
                    session,
                    level="warning",
                    thread_id=str(getattr(thread, "id", "")),
                    error=redact_secrets_in_text(str(exc))[:_MAX_DETAIL_CHARS],
                )
        return landed

    @staticmethod
    async def _aload_finding_threads(artifact: Any) -> dict[str, Any]:
        """既有未决 finding 线程的去重索引 ``{dedupe_key: thread}``（**只读**查询）。

        索引键与 :func:`finding_dedupe_key` 同构：``rule_id`` 从首条消息的
        ``[rule_id]`` 前缀反查（线程模型无 rule_id 字段），定位取
        ``anchor.block_id or anchor.section_path``。只读查询允许 adapter 直查，
        **写一律经 service**（INV-6）。
        """
        from delivery.models import (
            BlueprintThread,
            BlueprintThreadMessage,
            ThreadKind,
            ThreadStatus,
        )

        rows = [
            row
            async for row in BlueprintThread.objects.filter(
                artifact=artifact,
                kind=ThreadKind.AI_REVIEW_FINDING,
                status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED],
            ).order_by("created_at")
        ]
        if not rows:
            return {}
        first_body: dict[str, str] = {}
        async for message in (
            BlueprintThreadMessage.objects.filter(thread_id__in=[row.id for row in rows])
            .order_by("created_at")
            .values("thread_id", "body")
        ):
            first_body.setdefault(str(message["thread_id"]), str(message["body"] or ""))
        index: dict[str, Any] = {}
        for row in rows:
            tag = _RULE_ID_TAG.match(first_body.get(str(row.id), ""))
            if tag is None:
                continue
            anchor = row.anchor if isinstance(row.anchor, dict) else {}
            locator = str(anchor.get("block_id") or "") or str(anchor.get("section_path") or "")
            index.setdefault(f"{tag.group(1)}|{locator}", row)
        return index

    # ── 状态转移（全经 lifecycle；CAS 冲突绝不外泄）────────────────────────

    async def _atransition(
        self, session: Any, artifact: Any, to_status: str, *, initiated_by: str
    ) -> bool:
        """经 lifecycle 转状态；成功 ``True``，任何拒绝/冲突 ``False``（调用方降级）。

        ``ConcurrentBlueprintTransitionError`` 重试一次（先 ``arefresh_from_db`` 取最新
        DB 态），仍失败或非法边则记 warning 返回 ``False`` —— 调用方把出口降级成
        ``needs_clarification``，**绝不让 engine 落终态失败**（T-114-21 / P4）。
        """
        from delivery.services.blueprint_lifecycle_service import (
            ConcurrentBlueprintTransitionError,
        )

        lifecycle = self._lifecycle()
        for attempt in (0, 1):
            try:
                if str(getattr(artifact, "blueprint_status", "") or "") == to_status:
                    return True  # 幂等：已是目标态（合法边表无自环）
                await lifecycle.transition(
                    artifact,
                    to_status,
                    initiated_by_user_id=initiated_by,
                    session=session,
                )
                return True
            except ConcurrentBlueprintTransitionError as exc:
                if attempt == 0:
                    try:
                        await artifact.arefresh_from_db()
                    except Exception:  # noqa: BLE001 — 重读失败即放弃重试
                        pass
                    continue
                self._log(
                    "blueprint_review_transition_conflict",
                    session,
                    level="warning",
                    to_status=to_status,
                    error=redact_secrets_in_text(str(exc))[:_MAX_DETAIL_CHARS],
                )
                return False
            except Exception as exc:  # noqa: BLE001 — 非法边等同样吞成降级出口
                self._log(
                    "blueprint_review_transition_rejected",
                    session,
                    level="warning",
                    to_status=to_status,
                    error=redact_secrets_in_text(str(exc))[:_MAX_DETAIL_CHARS],
                )
                return False
        return False

    # ── 结果 / stage_state / 观测 ─────────────────────────────────────────

    @staticmethod
    def _unresolved(blockers: list[dict], landed: dict[str, str]) -> list[dict]:
        """超界出口携带的未决清单：**只含定位六键、零正文**，条数有界。"""
        rows: list[dict] = []
        for finding in blockers[:_MAX_UNRESOLVED]:
            rows.append(
                {
                    "rule_id": finding["rule_id"],
                    "severity": finding["severity"],
                    "section_path": finding["section_path"],
                    "block_id": finding["block_id"],
                    "repository_id": finding["repository_id"],
                    "thread_id": landed.get(finding_dedupe_key(finding), ""),
                }
            )
        return rows

    @staticmethod
    def _bucket(
        *,
        round_no: int,
        status: str,
        counts: dict,
        thread_ids: list[str],
        unresolved: list[dict],
        anchored_version_id: str,
        attribution: dict | None = None,
    ) -> dict:
        """本 stage 的 ``stage_state`` 桶（只存计数 / id / 小摘要，单字段 < 2KB）。

        ⚠️ 返回的是**增量**：engine 的 ``stage_state_update`` 是顶层浅合并，故这里只写
        自己的桶。**绝不整桶读改写融合侧的桶** —— 融合侧每轮都整桶覆盖它自己那个键，
        审查轮次塞进去会被抹掉 ⇒ 计数归零 ⇒ 无限打回循环（T-114-14）。
        """
        bucket: dict[str, Any] = {
            "round": round_no,
            "status": status,
            "thread_ids": thread_ids[:_MAX_UNRESOLVED],
            "unresolved": unresolved,
            "anchored_version_id": anchored_version_id,
        }
        bucket.update({key: int(value) for key, value in counts.items()})
        if attribution:
            bucket["last_attribution"] = dict(attribution)
        return {STAGE_STATE_KEY: bucket}

    @staticmethod
    def _result(
        status: str,
        *,
        round_no: int,
        artifact_version_id: str = "",
        back_target: str = "",
        back_repository_id: str = "",
        report: dict | None = None,
        stage_state: dict | None = None,
        thread_ids: list[str] | None = None,
    ) -> dict:
        """**恒定八键**返回（下游 handler 无需判空分支）。"""
        return {
            "review_status": status,
            "artifact_version_id": artifact_version_id,
            "round": round_no,
            "back_target": back_target,
            "back_repository_id": back_repository_id,
            "report": report or {},
            "stage_state": stage_state or {},
            "thread_ids": list(thread_ids or []),
        }

    async def _afinish(
        self,
        session: Any,
        status: str,
        *,
        round_no: int,
        emitted_round: int,
        artifact_version_id: str,
        bucket: dict,
        counts: dict,
        thread_ids: list[str],
        started: float,
        back_target: str = "",
        back_repository_id: str = "",
        report: dict | None = None,
    ) -> dict:
        """收尾：完成事件（payload 只放计数与分级分布）+ ``duration_ms`` 日志 + 恒定结果。

        ``round_no`` 与 ``emitted_round`` **是两个东西，不能互相代入**：

        - ``round_no``：0-based 重试计数器，进 ``_result`` 与 ``stage_state`` 桶。retry 出口
          传的是**已递增**的下一轮号（有界重试判据靠它，T-114-14）。
        - ``emitted_round``：1-based「刚跑完的是第几轮」，**只**进事件 payload 给人看。

        混用的后果是三条出口各报各的：retry 报下一轮号、passed/exhausted 报当前轮号，
        于是同一轮的 started 和 completed 在界面上显示成两个数。
        """
        payload = {"round": emitted_round, "review_status": status, "back_target": back_target}
        payload.update(counts)
        await self._aemit(session, _event("COMPLETED"), payload)
        self._log(
            "blueprint_review_completed",
            session,
            round=round_no,
            review_status=status,
            back_target=back_target,
            artifact_version_id=artifact_version_id,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            **counts,
        )
        return self._result(
            status,
            round_no=round_no,
            artifact_version_id=artifact_version_id,
            back_target=back_target,
            back_repository_id=back_repository_id,
            report=report or dict(counts),
            stage_state=bucket,
            thread_ids=thread_ids,
        )

    # ── 依赖解析 / 配置 / 观测 ────────────────────────────────────────────

    def _lifecycle(self) -> Any:
        if self._lifecycle_service is None:
            from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

            self._lifecycle_service = BlueprintLifecycleService()
        return self._lifecycle_service

    def _sessions(self) -> Any:
        if self._session_service is None:
            from delivery.services import ConvergenceSessionService

            self._session_service = ConvergenceSessionService()
        return self._session_service

    async def _aload_artifact(self, session: Any) -> Any:
        """会话钉住的版本 → 其 artifact（无版本指针即 ``None``）。"""
        from delivery.models import ArtifactVersion

        version_id = getattr(session, "current_artifact_version_id", None)
        if not version_id:
            return None
        row = await (
            ArtifactVersion.objects.select_related("artifact").filter(id=version_id).afirst()
        )
        return getattr(row, "artifact", None)

    async def _aload_review_config(self) -> int:
        """读 ``SettingKeys.BLUEPRINT_REVIEW_CONFIG`` → 轮次上界。

        缺配置 / 非 JSON / 缺键 / 值类型错 → **整段回落** :data:`MAX_REVIEW_ROUNDS`
        （配置坏了绝不能卡死流水线：审查是质量门不是可用性门）。读取一律经既有
        ``settings_service.aget_json_setting``，本 plan 不改 settings_service 一行。
        """
        try:
            from system.models import SettingKeys
            from system.settings_service import aget_json_setting

            cfg = await aget_json_setting(SettingKeys.BLUEPRINT_REVIEW_CONFIG, {}) or {}
            return int(cfg.get("max_review_rounds", MAX_REVIEW_ROUNDS))
        except Exception:  # noqa: BLE001 — 配置坏了回默认，绝不阻断审查
            return MAX_REVIEW_ROUNDS

    async def _aemit(self, session: Any, event_name: str, payload: dict) -> None:
        """会话事件 best-effort（观测绝不反噬审查主链；**正文绝不进 payload**）。"""
        try:
            await self._sessions().aemit_event(event_name, session, payload)
        except Exception:  # noqa: BLE001 — 事件失败绝不阻断审查
            self._log("blueprint_review_event_emit_failed", session, level="warning")

    @staticmethod
    def _log(event: str, session: Any, *, level: str = "info", **payload: Any) -> None:
        """结构化事件 best-effort（payload 只含计数与关联键，绝不含蓝图/finding 正文）。"""
        try:
            emit = logger.warning if level == "warning" else logger.info
            emit(
                event,
                category="caller",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
                initiated_by_user_id=_initiated_by(session),
                **payload,
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬审查主链
            pass


def _event(suffix: str) -> str:
    """取 ``blueprint.review.*`` 事件常量（函数内 lazy import，保持顶层零 Django 依赖）。"""
    from delivery.services import event_taxonomy

    return str(getattr(event_taxonomy, f"EVENT_BLUEPRINT_REVIEW_{suffix}"))


def _quoted_text(content: Any, block_id: str) -> str:
    """finding 锚点的 ``quoted_text``（有界截断）。

    非空是必需的：块被后续版本删掉时，``blueprint_anchor.reanchor`` 只能靠
    ``quoted_text`` 的相似度模糊重挂；留空会让该线程直接失锚（批注错位，CLAR-02）。
    """
    if not block_id:
        return ""
    try:
        for _path, block in iter_blocks(content):
            if str(block.get("block_id") or "") == block_id:
                return _block_text(block)[:_MAX_DETAIL_CHARS]
    except Exception:  # noqa: BLE001 — 取不到就留空（只影响模糊重挂，不影响判定）
        return ""
    return ""


__all__ += [
    "BlueprintReviewAdapter",
    "MAX_REVIEW_ROUNDS",
    "BACK_TARGET_REPO_PLAN",
    "BACK_TARGET_REMERGE",
    "RETURN_STAGE_AI_REVIEWING",
    "REVIEW_PASSED",
    "REVIEW_RETRY",
    "REVIEW_EXHAUSTED",
    "REVIEW_NEEDS_CLARIFICATION",
]
