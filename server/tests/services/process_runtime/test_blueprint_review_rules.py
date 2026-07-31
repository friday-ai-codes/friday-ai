"""六类机械规则纯函数测试（Phase 114-02，FLOW-07）。

**零 DB、零 mock**：`run_mechanical_rules` 与六条规则都是纯函数，全部断言直接喂 dict。

守十二件事：

1. ⭐ **无缺陷基线零 BLOCKER**：`run_mechanical_rules(_blueprint())` 里
   `severity == "blocker"` 的条数 == 0 —— 这是「其余断言非恒真」的地基。
2. ⭐ **空蓝图短路且绝不 pass**：`run_mechanical_rules({"schema_version": "blueprint/v1"})`
   恰好一条 `rule_id == "precondition_missing"` 且 `severity == "blocker"`，且**不含**
   `role_mismatch` / `api_ref_dangling`（后五条真的没跑）。
3. ⭐ **规则① `schema_version` 假通过防回归（正反并列）**：缺 `schema_version` 的
   content → `check_schema` 产 `schema_version_missing` BLOCKER，而同一 content 喂
   `validate_blueprint` **返回 `(True, None)`**；另一条：`schema_version` 正确但结构非法
   → `schema_invalid` BLOCKER 且 `detail` 非空。
4. **规则② 缺引用**：关键结论 `citations: []` → `citation_missing` BLOCKER 且同样本
   `citation_coverage < 1.0`；**并列**：空文档 `citation_coverage == 1.0` 而
   `check_citations({}) == []` ⇒ 不据比率判 pass，靠第 2 条短路兜住。
5. **规则③ 角色不一致（三档并列）**：direct 仓零实现项 → `role_mismatch` BLOCKER；
   item 指向 indirect 仓 → `role_mismatch` BLOCKER；indirect 仓 `capabilities_used`
   未被引用 → `capability_unreferenced` 且 `severity == "warning"`（唯一模糊项不升 BLOCKER）。
6. **规则④ API 断链（两条 + 枚举防回归）**：`api_ref` 悬空 → `api_ref_dangling` BLOCKER；
   `consumed` + `needs_support` 缺 `support_repository_id` → `support_repo_missing`
   BLOCKER；⭐ **并列**：把 `direction` 写成 `"produced"` 时该契约**不被当作 consumed
   处理**（不产 `support_repo_missing`）——锁死「实现里误用该字面量就恒通过」的回归面。
7. **规则⑤ 排期禁令**：`3 周` / `2 Weeks` / `week 3` 三种表述均 → `forbidden_schedule`
   BLOCKER，且 `detail` 只带命中片段（长度受上界约束，不贴整块正文）。
8. ⭐ **规则⑤ `deferred_ideas` 不误报（正反并列）**：out_of_scope 词条只写在
   `deferred_ideas` → 不产 `out_of_scope_introduced`；同词条写进 `items[].how` 的 block
   文本 → 产 `out_of_scope_introduced` 且 `severity == "warning"`。
9. **规则⑤ constraint 悬空 + B5 语义分工**：`constraint_refs` 引用不存在的 id →
   `constraint_ref_dangling` BLOCKER；⭐ **并列**：实现项文本明显违背某条
   `constraints[].text` 但引用合法 → `run_mechanical_rules` **不产** BLOCKER（语义冲突
   不由机械规则判），同用例断言 `agoal_backward_review` 签名含 `constraints` 且
   `_constraints_digest` 真的把该 constraint 的 id 投进 digest（不是形参摆设）。
10. ⭐ **规则⑥ 章程三态**：`charters=None` → `[]`；`evolution="maintenance_only"` 且无
    `decision_log` 支撑 → `charter_violation` BLOCKER；**同仓补一条 `decision_log` 支撑后
    该 BLOCKER 消失**；章程 dict 里没有该仓（缺章程）→ 不判 BLOCKER。
11. **确认门锁定 + 枚举等值**：仓被移除 / `role` 改判 / `responsibility` 改写各产一条
    `gate_lock_violation` BLOCKER 且 `block_id == f"blk_gate_resp_{rid}"`，未改动时零命中；
    ⭐ `SEVERITY_* == ThreadSeverity.*` 且 `STAGE_STATE_KEY == "ai_review"` 并
    `!= blueprint_merge.STAGE_STATE_KEY`（绝不复用 merge 桶）。
12. ⭐ **恒不抛 + 确定性 + LLM 降级**：`None` / `{}` / `[]` / `"x"` / 类型错乱喂全部公开
    函数均返回 list 不抛；同一 content 连调 `run_mechanical_rules` 两次结果逐字相等；
    `normalize_review_findings(None)` 恰好一条 `goal_backward_unavailable` **WARNING**
    （不是 `[]`、不是 BLOCKER）；非法 severity 回落 `warning`；超 `_MAX_FINDINGS` 被截断。
"""

from __future__ import annotations

import inspect

import pytest

from delivery.models import ThreadSeverity
from services.process_runtime import blueprint_merge
from services.process_runtime.blueprint_quality import citation_coverage
from services.process_runtime.blueprint_review import (
    _MAX_FINDINGS,
    SEVERITY_BLOCKER,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    STAGE_STATE_KEY,
    _constraints_digest,
    agoal_backward_review,
    check_api_closure,
    check_charters,
    check_citations,
    check_gate_lock,
    check_preconditions,
    check_prohibitions,
    check_roles,
    check_schema,
    finding_dedupe_key,
    normalize_review_findings,
    run_mechanical_rules,
)
from services.process_runtime.blueprint_schema import validate_blueprint

_REPO_ID = "repo-a"
_INDIRECT_ID = "repo-b"
_FP_ID = "fp_1"
_ITEM_ID = "impl_1"
_API_ID = "api_1"
_FLOW_ID = "flow_1"
_CITATION_ID = "cit_1"
_CONSTRAINT_ID = "con_1"
_CONSTRAINT_TEXT = "不得引入新的外部依赖"
_OUT_OF_SCOPE_TERM = "移动端适配"

_PUBLIC_RULES = (
    check_preconditions,
    check_schema,
    check_citations,
    check_roles,
    check_api_closure,
    check_prohibitions,
    check_charters,
    check_gate_lock,
    run_mechanical_rules,
)

_BAD_INPUTS = (
    None,
    {},
    [],
    "x",
    123,
    {"repo_associations": "not-a-list"},
    {"implementation_overview": {"items": {}}},
    {"requirement_spec": [], "api_contracts": "x", "interaction_flows": {}},
)


# ── 工厂：一份六段齐全、无缺陷的最小合法蓝图 ────────────────────────────


def _block(block_id: str, text: str = "一段正常的方案叙述") -> dict:
    return {"block_id": block_id, "type": "paragraph", "text": text}


def _assoc(repository_id: str, *, role: str = "direct", **extra) -> dict:
    assoc: dict = {
        "repository_id": repository_id,
        "repository_name": repository_id,
        "role": role,
        "rationale": {
            "text": [_block(f"blk_rationale_{repository_id}")],
            "constraint_refs": [_CONSTRAINT_ID],
            "citations": [_CITATION_ID],
        },
        "responsibility": [_block(f"blk_gate_resp_{repository_id}", f"{repository_id} 的既定职责")],
    }
    assoc.update(extra)
    return assoc


def _blueprint(**overrides) -> dict:
    """六段齐全、零缺陷的最小合法蓝图。各用例在其上**注入单一缺陷**。"""
    content: dict = {
        "schema_version": "blueprint/v1",
        "meta": {"title": "最小合法蓝图", "project_id": "proj-1"},
        "requirement_spec": {
            "goal": [_block("blk_goal", "把需求自动跑成可评审的技术蓝图")],
            "feature_points": [
                {
                    "id": _FP_ID,
                    "title": "审查判定内核",
                    "intent": "greenfield",
                    "acceptance_criteria": ["六类规则在无 LLM 下产确定性结论"],
                }
            ],
            "constraints": [{"id": _CONSTRAINT_ID, "text": _CONSTRAINT_TEXT, "kind": "tech"}],
        },
        "repo_associations": [_assoc(_REPO_ID)],
        "current_state_analysis": [
            {
                "repository_id": _REPO_ID,
                "findings": [
                    {
                        "id": "cs_1",
                        "text": [_block("blk_cs_1")],
                        "kind": "capability",
                        "citations": [_CITATION_ID],
                    }
                ],
            }
        ],
        "implementation_overview": {
            "requirement_narrative": [_block("blk_narrative")],
            "items": [
                {
                    "id": _ITEM_ID,
                    "feature_point_id": _FP_ID,
                    "repository_id": _REPO_ID,
                    "change_type": "create",
                    "title": "新建判定内核纯函数模块",
                    "how": [_block("blk_how", "新建纯函数模块并逐条实现六类判据")],
                    "citations": [_CITATION_ID],
                }
            ],
        },
        "api_contracts": [
            {
                "id": _API_ID,
                "name": "runReview",
                "kind": "http",
                "direction": "provided",
                "repository_id": _REPO_ID,
                "method": "POST",
                "path": "/api/review",
                "citations": [_CITATION_ID],
            }
        ],
        "impact_analysis": {
            "business_impact": [_block("blk_impact")],
            "affected_features": [
                {
                    "feature": "蓝图确认",
                    "kind": "behavior_change",
                    "repository_ids": [_REPO_ID],
                    "citations": [_CITATION_ID],
                }
            ],
        },
        "interaction_flows": [
            {
                "id": _FLOW_ID,
                "name": "审查流程",
                "steps": [
                    {"seq": 1, "actor": "backend", "action": "跑六类机械规则", "api_ref": _API_ID}
                ],
            }
        ],
        "must_haves": {
            "truths": ["同一蓝图反复审查输出逐字相等"],
            "artifacts": [],
            "key_links": [],
        },
        "citations": {
            _CITATION_ID: {
                "citation_id": _CITATION_ID,
                "source_type": "repo_file",
                "source_id": "server/services/process_runtime/blueprint_review.py",
            }
        },
    }
    content.update(overrides)
    return content


def _locked_snapshot() -> dict:
    """确认门锁定快照（形状对齐 `stage_state["confirmation"]`）。"""
    return {"repos": [_assoc(_REPO_ID)]}


def _rule_ids(findings: list[dict]) -> list[str]:
    return [item["rule_id"] for item in findings]


def _blockers(findings: list[dict]) -> list[dict]:
    return [item for item in findings if item["severity"] == SEVERITY_BLOCKER]


def _by_rule(findings: list[dict], rule_id: str) -> list[dict]:
    return [item for item in findings if item["rule_id"] == rule_id]


# ── 1. 无缺陷基线零 BLOCKER（断言非恒真的地基） ─────────────────────────


def test_clean_baseline_produces_no_blocker():
    findings = run_mechanical_rules(_blueprint())
    assert _blockers(findings) == [], findings
    # 基线连 WARNING 也不该有：注入缺陷的用例才是差异来源。
    assert findings == [], findings


def test_clean_baseline_is_schema_valid():
    ok, error = validate_blueprint(_blueprint())
    assert ok is True and error is None, error


# ── 2. 空蓝图短路且绝不 pass ────────────────────────────────────────────


def test_empty_blueprint_short_circuits_into_single_precondition_blocker():
    findings = run_mechanical_rules({"schema_version": "blueprint/v1"})
    assert len(findings) == 1, findings
    assert findings[0]["rule_id"] == "precondition_missing"
    assert findings[0]["severity"] == SEVERITY_BLOCKER
    # 短路生效：后五条一条也没跑（否则会冒出一片恒真的假阳性/假失败噪声）。
    assert "role_mismatch" not in _rule_ids(findings)
    assert "api_ref_dangling" not in _rule_ids(findings)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda bp: bp.update({"repo_associations": []}), id="repo_associations"),
        pytest.param(
            lambda bp: bp["implementation_overview"].update({"items": []}), id="impl_items"
        ),
        pytest.param(
            lambda bp: bp["requirement_spec"].update({"feature_points": []}), id="feature_points"
        ),
    ],
)
def test_each_missing_precondition_section_is_blocker(mutate):
    blueprint = _blueprint()
    mutate(blueprint)
    findings = check_preconditions(blueprint)
    assert len(findings) == 1 and findings[0]["rule_id"] == "precondition_missing", findings
    assert findings[0]["severity"] == SEVERITY_BLOCKER


# ── 3. 规则① schema_version 假通过防回归（正反并列） ────────────────────


def test_missing_schema_version_is_blocker_although_validate_blueprint_passes():
    blueprint = _blueprint()
    del blueprint["schema_version"]
    # 反面：既有 v0 pass-through 语义——校验器对这份 content **说合法**。
    assert validate_blueprint(blueprint) == (True, None)
    # 正面：规则①先自断言 schema_version，不被那句 pass-through 骗过去。
    findings = check_schema(blueprint)
    assert _rule_ids(findings) == ["schema_version_missing"], findings
    assert findings[0]["severity"] == SEVERITY_BLOCKER


def test_structurally_invalid_blueprint_is_schema_invalid_with_detail():
    blueprint = _blueprint()
    # role 是 required 且带 enum：删掉即结构非法。
    del blueprint["repo_associations"][0]["role"]
    findings = check_schema(blueprint)
    assert _rule_ids(findings) == ["schema_invalid"], findings
    assert findings[0]["severity"] == SEVERITY_BLOCKER
    assert findings[0]["detail"]


# ── 4. 规则② 引用覆盖（条目级，不看比率） ───────────────────────────────


def test_key_conclusion_without_citations_is_blocker():
    blueprint = _blueprint()
    blueprint["current_state_analysis"][0]["findings"][0]["citations"] = []
    findings = check_citations(blueprint)
    missing = _by_rule(findings, "citation_missing")
    assert len(missing) == 1, findings
    assert missing[0]["severity"] == SEVERITY_BLOCKER
    assert missing[0]["repository_id"] == _REPO_ID
    # 口径一致性：同一样本的覆盖率也确实掉下 1.0。
    assert citation_coverage(blueprint) < 1.0


def test_weak_conclusion_without_citations_is_only_warning():
    blueprint = _blueprint()
    blueprint["implementation_overview"]["items"][0].pop("citations")
    findings = check_citations(blueprint)
    weak = _by_rule(findings, "citation_missing_weak")
    assert len(weak) == 1, findings
    assert weak[0]["severity"] == SEVERITY_WARNING
    assert _blockers(findings) == []


def test_empty_document_coverage_is_one_but_never_counts_as_pass():
    # 分母为 0 → 覆盖率满分（既有语义，blueprint_quality.py:76）。
    assert citation_coverage({}) == 1.0
    # 条目级走查对空文档无话可说……
    assert check_citations({}) == []
    # ……所以「空文档不假通过」靠前置短路兜住，而不是靠比率。
    assert _rule_ids(run_mechanical_rules({})) == ["precondition_missing"]


# ── 5. 规则③ 角色一致性（三档并列） ─────────────────────────────────────


def test_direct_repo_without_impl_item_is_blocker():
    blueprint = _blueprint()
    blueprint["repo_associations"].append(_assoc("repo-lonely"))
    findings = check_roles(blueprint)
    mismatch = _by_rule(findings, "role_mismatch")
    assert len(mismatch) == 1, findings
    assert mismatch[0]["severity"] == SEVERITY_BLOCKER
    assert mismatch[0]["repository_id"] == "repo-lonely"


def test_item_pointing_to_indirect_repo_is_blocker():
    blueprint = _blueprint()
    blueprint["repo_associations"].append(_assoc(_INDIRECT_ID, role="indirect"))
    blueprint["implementation_overview"]["items"][0]["repository_id"] = _INDIRECT_ID
    findings = check_roles(blueprint)
    mismatch = _by_rule(findings, "role_mismatch")
    assert {item["repository_id"] for item in mismatch} == {_REPO_ID, _INDIRECT_ID}, findings
    assert all(item["severity"] == SEVERITY_BLOCKER for item in mismatch)


def test_unreferenced_capability_is_warning_not_blocker():
    blueprint = _blueprint()
    blueprint["repo_associations"].append(
        _assoc(_INDIRECT_ID, role="indirect", capabilities_used=["一个谁也没引用的能力"])
    )
    findings = run_mechanical_rules(blueprint)
    unreferenced = _by_rule(findings, "capability_unreferenced")
    assert len(unreferenced) == 1, findings
    # 唯一的模糊匹配项：**绝不升 BLOCKER**（强判会产生不可复现的假阳性）。
    assert unreferenced[0]["severity"] == SEVERITY_WARNING
    assert _blockers(findings) == []


def test_referenced_capability_is_not_reported():
    blueprint = _blueprint()
    capability = "既有的鉴权中间件"
    blueprint["repo_associations"].append(
        _assoc(_INDIRECT_ID, role="indirect", capabilities_used=[capability])
    )
    blueprint["implementation_overview"]["items"][0]["how"] = [
        _block("blk_how", f"复用 {capability} 完成鉴权")
    ]
    assert _by_rule(check_roles(blueprint), "capability_unreferenced") == []


# ── 6. 规则④ API 闭环（两条 + direction 枚举防回归） ────────────────────


def test_dangling_api_ref_is_blocker():
    blueprint = _blueprint()
    blueprint["interaction_flows"][0]["steps"][0]["api_ref"] = "api_ghost"
    findings = check_api_closure(blueprint)
    assert _rule_ids(findings) == ["api_ref_dangling"], findings
    assert findings[0]["severity"] == SEVERITY_BLOCKER
    assert findings[0]["section_path"] == f"interaction_flows[{_FLOW_ID}].steps[1]"


def test_consumed_needs_support_without_support_repo_is_blocker():
    blueprint = _blueprint()
    blueprint["api_contracts"][0]["direction"] = "consumed"
    blueprint["api_contracts"][0]["data_source"] = {"availability": "needs_support"}
    findings = check_api_closure(blueprint)
    assert _rule_ids(findings) == ["support_repo_missing"], findings
    assert findings[0]["severity"] == SEVERITY_BLOCKER


def test_consumed_needs_support_with_valid_support_repo_is_clean():
    blueprint = _blueprint()
    blueprint["api_contracts"][0]["direction"] = "consumed"
    blueprint["api_contracts"][0]["data_source"] = {
        "availability": "needs_support",
        "support_repository_id": _REPO_ID,
    }
    assert check_api_closure(blueprint) == []


def test_wrong_direction_literal_is_not_treated_as_consumed():
    """⭐ 枚举防回归：写成 `"produced"` 的契约不进 consumed 分支。

    这条锁死的是「实现里若把 direction 判据写成那个字面量，规则④会恒通过」的回归面——
    合法枚举只有 `provided` / `consumed`（`blueprint_schema.py:522-524`）。
    """
    blueprint = _blueprint()
    blueprint["api_contracts"][0]["direction"] = "produced"
    blueprint["api_contracts"][0]["data_source"] = {"availability": "needs_support"}
    assert _by_rule(check_api_closure(blueprint), "support_repo_missing") == []
    # 并列：同一样例只把 direction 改回合法的 consumed，立刻命中。
    blueprint["api_contracts"][0]["direction"] = "consumed"
    assert _rule_ids(check_api_closure(blueprint)) == ["support_repo_missing"]


# ── 7. 规则⑤ 排期禁令 ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    ["预计 3 周完成后端改造", "estimated 2 Weeks for rollout", "week 3 交付前端"],
)
def test_week_based_schedule_is_blocker(text):
    blueprint = _blueprint()
    blueprint["implementation_overview"]["items"][0]["how"] = [_block("blk_how", text)]
    findings = check_prohibitions(blueprint)
    schedule = _by_rule(findings, "forbidden_schedule")
    assert len(schedule) == 1, findings
    assert schedule[0]["severity"] == SEVERITY_BLOCKER
    assert schedule[0]["block_id"] == "blk_how"
    # 只带命中片段，不贴整块正文（前缀 + ≤80 字符片段）。
    assert len(schedule[0]["detail"]) <= 80 + 32


def test_clean_narrative_has_no_schedule_finding():
    assert _by_rule(check_prohibitions(_blueprint()), "forbidden_schedule") == []


# ── 8. 规则⑤ deferred_ideas 不误报（正反并列） ─────────────────────────


def test_out_of_scope_term_in_deferred_ideas_is_not_reported():
    blueprint = _blueprint(
        deferred_ideas=[{"text": _OUT_OF_SCOPE_TERM, "reason": "本期不做，留给下一期"}]
    )
    blueprint["requirement_spec"]["boundaries"] = {"out_of_scope": [_OUT_OF_SCOPE_TERM]}
    findings = check_prohibitions(blueprint)
    assert _by_rule(findings, "out_of_scope_introduced") == [], findings


def test_out_of_scope_term_inside_impl_item_is_warning():
    blueprint = _blueprint()
    blueprint["requirement_spec"]["boundaries"] = {"out_of_scope": [_OUT_OF_SCOPE_TERM]}
    blueprint["implementation_overview"]["items"][0]["how"] = [
        _block("blk_how", f"顺手把 {_OUT_OF_SCOPE_TERM} 也做掉")
    ]
    findings = check_prohibitions(blueprint)
    introduced = _by_rule(findings, "out_of_scope_introduced")
    assert len(introduced) == 1, findings
    assert introduced[0]["severity"] == SEVERITY_WARNING
    assert introduced[0]["block_id"] == "blk_how"


# ── 9. 规则⑤ constraint 悬空 + B5 语义分工 ─────────────────────────────


def test_dangling_constraint_ref_is_blocker():
    blueprint = _blueprint()
    blueprint["repo_associations"][0]["rationale"]["constraint_refs"] = ["con_ghost"]
    findings = check_prohibitions(blueprint)
    dangling = _by_rule(findings, "constraint_ref_dangling")
    assert len(dangling) == 1, findings
    assert dangling[0]["severity"] == SEVERITY_BLOCKER
    assert dangling[0]["repository_id"] == _REPO_ID


def test_semantic_constraint_conflict_is_not_judged_mechanically():
    """⭐ B5 分工：语义冲突**不由机械规则判**，但确实进了 LLM 一类的 digest。

    样例是「实现项文本明显违背某条 constraint 但引用合法」——机械层必须保持沉默（防将来
    有人塞进模糊文本匹配，那会产生不可复现的假阳性），语义层由
    `agoal_backward_review` 的 `constraints` 形参承担。
    """
    blueprint = _blueprint()
    blueprint["implementation_overview"]["items"][0]["how"] = [
        _block("blk_how", f"这里要{_CONSTRAINT_TEXT.replace('不得', '')}：引入一个新的三方库")
    ]
    assert _blockers(run_mechanical_rules(blueprint)) == []

    # 形参存在且全 keyword-only。
    params = inspect.signature(agoal_backward_review).parameters
    assert "constraints" in params, list(params)
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values()), params
    # 且它真的会进 prompt digest（不是形参摆设）。
    digest = _constraints_digest(blueprint["requirement_spec"]["constraints"])
    assert [entry["id"] for entry in digest] == [_CONSTRAINT_ID], digest
    assert _CONSTRAINT_TEXT in digest[0]["text"]
    # digest 恒不抛：None / 类型错乱一律空列表（空 ⇒ 「本项不可判」被显式标注）。
    assert _constraints_digest(None) == []
    assert _constraints_digest("x") == []


# ── 10. 规则⑥ 章程三态 ────────────────────────────────────────────────


def _charters(evolution: str = "maintenance_only") -> dict[str, dict]:
    return {
        _REPO_ID: {
            "repository_id": _REPO_ID,
            "evolution": evolution,
            "boundaries": [{"rule": "只维护既有能力，不承接新增域", "decided_by": "human"}],
        }
    }


def test_charters_none_or_empty_is_skipped():
    assert check_charters(_blueprint(), charters=None) == []
    assert check_charters(_blueprint(), charters={}) == []


def test_frozen_evolution_without_decision_support_is_blocker():
    findings = check_charters(_blueprint(), charters=_charters())
    violation = _by_rule(findings, "charter_violation")
    assert len(violation) == 1, findings
    assert violation[0]["severity"] == SEVERITY_BLOCKER
    assert violation[0]["repository_id"] == _REPO_ID
    # 明文边界另出一条 WARNING（自由文本，不升 BLOCKER）。
    assert [item["severity"] for item in _by_rule(findings, "charter_boundary_risk")] == [
        SEVERITY_WARNING
    ]


def test_decision_log_support_clears_charter_violation():
    blueprint = _blueprint(
        decision_log=[
            {
                "repository_id": _REPO_ID,
                "question": "是否允许在该仓新增审查内核？",
                "answer": "允许，本期唯一落点",
            }
        ]
    )
    assert check_charters(blueprint, charters=_charters()) == []


def test_active_evolution_is_not_violation():
    findings = check_charters(_blueprint(), charters=_charters(evolution="active"))
    assert _by_rule(findings, "charter_violation") == [], findings


def test_repo_without_charter_entry_is_skipped():
    charters = {"repo-somewhere-else": {"evolution": "deprecated"}}
    assert check_charters(_blueprint(), charters=charters) == []


# ── 11. 确认门锁定校验 + 字面量与枚举等值 ──────────────────────────────


def test_unchanged_repo_associations_pass_gate_lock():
    assert check_gate_lock(_blueprint(), locked_snapshot=_locked_snapshot()) == []


@pytest.mark.parametrize(
    "mutate,reason",
    [
        pytest.param(lambda bp: bp.update({"repo_associations": []}), "removed", id="removed"),
        pytest.param(
            lambda bp: bp["repo_associations"][0].update({"role": "indirect"}),
            "role",
            id="role_changed",
        ),
        pytest.param(
            lambda bp: bp["repo_associations"][0].update(
                {"responsibility": [_block("blk_gate_resp_repo-a", "换了一套完全不同的职责")]}
            ),
            "responsibility",
            id="responsibility_rewritten",
        ),
    ],
)
def test_deviation_from_gate_lock_is_blocker(mutate, reason):
    blueprint = _blueprint()
    mutate(blueprint)
    findings = check_gate_lock(blueprint, locked_snapshot=_locked_snapshot())
    assert _rule_ids(findings) == ["gate_lock_violation"], (reason, findings)
    assert findings[0]["severity"] == SEVERITY_BLOCKER
    assert findings[0]["block_id"] == f"blk_gate_resp_{_REPO_ID}"
    assert findings[0]["section_path"] == f"repo_associations[{_REPO_ID}].responsibility"


def test_gate_lock_falls_back_to_confirmed_at_gate_entries():
    blueprint = _blueprint()
    blueprint["repo_associations"][0]["confirmed_at_gate"] = True
    # 自比对：无外部快照时只能检出「锁定条目被整条移除」。
    assert check_gate_lock(blueprint) == []
    blueprint["repo_associations"] = []
    assert check_gate_lock(blueprint) == []


def test_severity_literals_match_thread_severity_enum():
    """字面量与枚举防漂移：本模块顶层零 Django import，故等值只能由测试锁死。"""
    assert SEVERITY_BLOCKER == ThreadSeverity.BLOCKER
    assert SEVERITY_WARNING == ThreadSeverity.WARNING
    assert SEVERITY_INFO == ThreadSeverity.INFO


def test_stage_state_key_never_reuses_merge_bucket():
    assert STAGE_STATE_KEY == "ai_review"
    assert STAGE_STATE_KEY != blueprint_merge.STAGE_STATE_KEY


# ── 12. 恒不抛 + 确定性 + LLM 降级 ─────────────────────────────────────


@pytest.mark.parametrize("bad", _BAD_INPUTS)
def test_public_rules_never_raise(bad):
    for rule in _PUBLIC_RULES:
        assert isinstance(rule(bad), list), (rule.__name__, bad)


def test_run_mechanical_rules_is_deterministic():
    blueprint = _blueprint()
    blueprint["repo_associations"].append(_assoc("repo-lonely"))
    blueprint["repo_associations"].append(
        _assoc(_INDIRECT_ID, role="indirect", capabilities_used=["能力甲", "能力乙"])
    )
    blueprint["interaction_flows"][0]["steps"][0]["api_ref"] = "api_ghost"
    first = run_mechanical_rules(
        blueprint, charters=_charters(), locked_snapshot=_locked_snapshot()
    )
    second = run_mechanical_rules(
        blueprint, charters=_charters(), locked_snapshot=_locked_snapshot()
    )
    assert first == second, (first, second)
    assert _blockers(first), first


def test_normalize_none_is_a_single_warning_meta_finding():
    findings = normalize_review_findings(None)
    assert len(findings) == 1, findings
    assert findings[0]["rule_id"] == "goal_backward_unavailable"
    # **绝不是 `[]`（会被读成「审查通过」），也绝不是 BLOCKER（LLM 挂了不该打回蓝图）。**
    assert findings[0]["severity"] == SEVERITY_WARNING
    assert findings[0]["detail"]


def test_normalize_illegal_severity_falls_back_to_warning():
    findings = normalize_review_findings([{"rule_id": "x", "severity": "fatal"}])
    assert findings[0]["severity"] == SEVERITY_WARNING
    # 无 rule_id 的条目整项丢弃；非 dict 元素同理。
    assert normalize_review_findings([{"severity": "blocker"}, "junk", None]) == []


def test_normalize_truncates_to_max_findings():
    raw = [
        {"rule_id": f"r{index}", "severity": SEVERITY_INFO} for index in range(_MAX_FINDINGS * 3)
    ]
    assert len(normalize_review_findings(raw)) == _MAX_FINDINGS


def test_finding_dedupe_key_prefers_block_id():
    assert (
        finding_dedupe_key(
            {"rule_id": "citation_missing", "block_id": "blk_1", "section_path": "s"}
        )
        == "citation_missing|blk_1"
    )
    assert (
        finding_dedupe_key({"rule_id": "citation_missing", "section_path": "s"})
        == "citation_missing|s"
    )
    assert finding_dedupe_key(None) == "|"
