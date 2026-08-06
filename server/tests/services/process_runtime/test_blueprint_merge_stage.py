"""融合装配（阶段 3）测试（Phase 113-05，FLOW-06 / SCHEMA-02~05）。

守十四件事：

1. ⭐ **确定性投影不经推理**：起草替身四段全返空（不贡献任何内容）→ `repo_associations`
   与 `current_state_analysis` **仍完整产出**，且与上游产物（确认门锁定 associations /
   各仓 `repo_plan.current_state`）**逐字段相等**（不是「大致包含」，是相等）。
2. ⭐ **P-8 覆盖率非零**：3 个带 citations 的 association → 投影后
   `citation_coverage(blueprint) > 0`，且 `repo_associations[0].rationale.citations` 非空。
3. ⭐ **引用完整性（P-5）**：装配产物过 `validate_blueprint` 为 `(True, None)`；
   全文档每个 citations id 都能在顶层引用池里找到且都是 `cit_` 前缀（裸路径零残留）。
4. ⭐ **基线读最新版本（P-6）**：会话钉住空的 v1、artifact 最新是含 2 仓的 v2 →
   融合产物含这 2 仓。
5. **must_haves 确定性派生**：三键齐全、`artifacts[].path` 去重自 `files_touched`、
   `key_links` 含 provider→consumer 边、空 items 时 `artifacts == []` 而非缺键。
6. **分节而非单 prompt**：起草替身被调用 **4 次**，section 参数分别是四段名。
7. ⭐ **单段失败降级（W2 可证伪）**：逐段各一条 —— 其余三段仍产出、整体仍
   `(True, None)` 且 `validation_status == "passed"`；`impact_analysis` 那条额外断言降级值
   **恰好**是 `{"business_impact": [], "affected_features": []}`（两键都在，不是 `{}`）。
   四段全抛才 `failed`。
8. **顶层 required 十一键齐全 + meta 承接**：`schema_version` 是常量值；基线 meta 的
   非 required 键（`summary` / `revision_round`）未丢；`title` / `project_id` 非空。
9. **对账抛澄清**：`method` 两侧不一致 → `needs_clarification` + `back_target == "merge"`
   + DB 有 blocking `ai_clarification` 线程且 `return_stage == "merge"`（B3）+ **不落新版本**。
10. ⭐ **consumed 无 provider 必标 needs_support（B4 路径断言）**：
    `item["data_source"]["availability"] == "needs_support"` 且 **`"availability" not in item`**
    （顶层零残留）；协作仓缺失时走澄清路径。
11. **幂等落版本（W6 口径）**：同输入连续两次 → 版本数只 +1、两次
    `artifact_version_id` 相同、`produced_by_ref` 含 `attempt=`。
12. **schema 不过不落版本**：基线 `requirement_spec` 非法 → `failed` 且版本数不变。
13. **返回值带 artifact_version_id**（113-06 回填 `StageOutcome` 的依据）。
14. **SCHEMA-03/04/05 形状**：`items[]` 逐项有合法 `change_type` 与 `wave`；
    `flows[].steps[]` 有 `seq` 且六要素字段在位、`api_ref` 已换算成真实契约 id；
    `api_contracts[]` 含 `request_example` / `response_example` / `data_source`。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintThread,
    BlueprintThreadMessage,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ThreadKind,
)
from services.process_runtime.blueprint_merge import (
    SECTION_API_CONTRACTS,
    SECTION_IMPACT_ANALYSIS,
    SECTION_IMPLEMENTATION_OVERVIEW,
    SECTION_INTERACTION_FLOWS,
    BlueprintMergeAdapter,
    build_citation_pool,
    derive_must_haves,
    project_current_state,
    project_repo_associations,
)
from services.process_runtime.blueprint_quality import citation_coverage
from services.process_runtime.blueprint_schema import (
    BLUEPRINT_JSON_SCHEMA,
    BLUEPRINT_SCHEMA_VERSION,
    validate_blueprint,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

_CITATION_A = "server/services/a.py"
_CITATION_B = "server/services/b.py"


# ── 工厂与替身 ────────────────────────────────────────────────────────────


class _FakeSynthesizer:
    """分节起草替身：按 section 返回预置产物，可配置某几段抛异常。"""

    def __init__(self, sections: dict | None = None, failing: tuple[str, ...] = ()) -> None:
        self.sections = sections if sections is not None else {}
        self.failing = set(failing)
        self.calls: list[str] = []
        self.prompts: list[dict] = []

    async def draft(self, *, section: str, prompt_parts: dict) -> dict:
        self.calls.append(section)
        self.prompts.append(prompt_parts)
        if section in self.failing:
            raise RuntimeError(f"section_draft_failed:{section}")
        return self.sections.get(section, {})


class _FakeRepoPlanAdapter:
    """各仓方案聚合替身（真实实现走 PartialPlan，本测试直接给产物）。"""

    def __init__(self, plans: dict) -> None:
        self.plans = plans
        self.calls = 0

    async def acollect_repo_plans(self, session: Any) -> dict:
        self.calls += 1
        return self.plans


def _repo_id(suffix: str) -> str:
    return f"repo-{suffix}-{uuid.uuid4().hex[:6]}"


def _association(
    repository_id: str, *, role: str = "direct", citations: list | None = None
) -> dict:
    """确认门锁定产物形状（对齐 `build_locked_associations` 的落法：citations 在 fitness 下）。"""
    return {
        "repository_id": repository_id,
        "repository_name": f"name-{repository_id}",
        "role": role,
        "responsibility": [
            {"block_id": f"blk_gate_resp_{repository_id}", "type": "paragraph", "text": "承担职责"}
        ],
        "routing_evidence": {"total": 0.8, "confidence": "high"},
        "decided_by": "human",
        "confirmed_at_gate": True,
        "fitness": {
            "verdict": "suitable",
            "reasons": [
                {"block_id": f"blk_fit_{repository_id}", "type": "paragraph", "text": "适配"}
            ],
            "citations": list(citations if citations is not None else [_CITATION_A]),
        },
    }


def _repo_plan(
    repository_id: str,
    *,
    current_state: list | None = None,
    impl_items: list | None = None,
    apis_provided: list | None = None,
    apis_consumed: list | None = None,
    local_impact: dict | None = None,
) -> dict:
    section: dict[str, Any] = {
        "repository_id": repository_id,
        "role": "direct",
        "impl_items": impl_items
        if impl_items is not None
        else [
            {
                "item_id": "it_1",
                "title": "加一个接口",
                "change_type": "create",
                "how": "写 view + serializer",
                "files_touched": ["server/api/views.py", "server/api/views.py"],
                "depends_on": [],
                "citations": [_CITATION_A],
            }
        ],
        "current_state": current_state
        if current_state is not None
        else [
            {
                "summary": "该仓已有 REST 骨架",
                "findings": [
                    {
                        "title": "已有 DRF 路由",
                        "detail": "urls.py 已注册 router",
                        "citations": [_CITATION_A],
                    }
                ],
            }
        ],
    }
    section["apis_provided"] = (
        apis_provided
        if apis_provided is not None
        # 默认给一条**仅本仓可见**的契约（名字带仓 id，跨仓天然不匹配）：既让 api 段非空，
        # 又不会在多仓样本里意外配出 provider/consumer 对。
        else [
            {
                "name": f"api-{repository_id}",
                "method": "GET",
                "path": f"/{repository_id}",
                "description": "本仓已提供",
                "citations": [_CITATION_A],
            }
        ]
    )
    if apis_consumed is not None:
        section["apis_consumed"] = apis_consumed
    if local_impact is not None:
        section["local_impact"] = local_impact
    return section


def _requirement_spec() -> dict:
    return {
        "goal": [{"block_id": "blk_goal", "type": "paragraph", "text": "让用户能查看列表"}],
        "feature_points": [
            {
                "id": "fp_1",
                "title": "用户列表",
                "intent": "greenfield",
                "acceptance_criteria": ["打开页面能看到用户列表"],
            }
        ],
    }


def _baseline_meta() -> dict:
    return {
        "title": "既有蓝图标题",
        "project_id": "proj-001",
        # 非 required 键：融合必须整段承接，不得重造把它们丢掉
        "summary": [{"block_id": "blk_meta_sum", "type": "paragraph", "text": "执行摘要"}],
        "revision_round": 2,
        "language": "zh-CN",
    }


async def _make_locked_session(
    *associations: dict,
    requirement_spec: dict | None = None,
    meta: dict | None = None,
):
    """建 artifact 两版：v1 空（会话钉住它）、v2 带确认门锁定产物（最新版）。"""
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    stale = await ArtifactVersion.objects.acreate(
        artifact=artifact,
        version_no=1,
        content={"schema_version": BLUEPRINT_SCHEMA_VERSION, "repo_associations": []},
    )
    latest = await ArtifactVersion.objects.acreate(
        artifact=artifact,
        version_no=2,
        content={
            "schema_version": BLUEPRINT_SCHEMA_VERSION,
            "meta": meta if meta is not None else _baseline_meta(),
            "requirement_spec": requirement_spec
            if requirement_spec is not None
            else _requirement_spec(),
            "repo_associations": list(associations),
            "citations": {},
        },
    )
    artifact.current_version = latest
    await artifact.asave(update_fields=["current_version"])
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="merge",
        stage_state={},
        # 故意钉住落后的 v1：融合必须自己去取最新版（P-6 残留口 2）
        current_artifact_version_id=stale.id,
    )
    return session, artifact


def _drafted_sections(repository_id: str, *, api_name: str = "listUsers") -> dict:
    """一份「四段都产出内容」的起草产物（形状按各段 prompt 的输出契约）。"""
    return {
        SECTION_IMPLEMENTATION_OVERVIEW: {
            SECTION_IMPLEMENTATION_OVERVIEW: {
                "requirement_narrative": "整体上先在 A 仓加接口，再由前端消费",
                "modules": [
                    {
                        "id": "mod_1",
                        "name": "用户模块",
                        "feature_point_ids": ["fp_1"],
                        "repository_ids": [repository_id],
                        "narrative": "模块叙事",
                    }
                ],
                "items": [
                    {
                        "repository_id": repository_id,
                        "item_id": "it_1",
                        "feature_point_id": "fp_1",
                        "module_id": "mod_1",
                    }
                ],
            }
        },
        SECTION_API_CONTRACTS: {
            SECTION_API_CONTRACTS: [
                {
                    "name": api_name,
                    "method": "GET",
                    "path": "/users",
                    "description": "拉用户列表",
                    "request_example": {"page": 1},
                    "response_example": {"items": []},
                    "data_source": {"fields_needed": ["id", "name"], "notes": "数据已在本仓"},
                }
            ]
        },
        SECTION_INTERACTION_FLOWS: {
            SECTION_INTERACTION_FLOWS: [
                {
                    "id": "flow_1",
                    "name": "查看用户列表",
                    "trigger": "用户打开列表页",
                    "steps": [
                        {
                            "seq": 1,
                            "actor": "frontend",
                            "action": "打开用户列表页并请求数据",
                            "component": "UserListPage",
                            "api_ref": api_name,
                            "data_in": "page=1",
                            "data_out": "users[]",
                        },
                        {
                            "seq": 2,
                            "actor": "backend",
                            "action": "查库并返回列表",
                            "component": "UserViewSet",
                            "data_in": "page",
                            "data_out": "users[]",
                        },
                    ],
                    "alternative_paths": [
                        {
                            "condition": "无权限",
                            "steps": [{"seq": 1, "actor": "backend", "action": "返回 403"}],
                        }
                    ],
                }
            ]
        },
        SECTION_IMPACT_ANALYSIS: {
            SECTION_IMPACT_ANALYSIS: {
                "business_impact": "列表页新增一块内容",
                "affected_features": [
                    {
                        "feature": "用户中心",
                        "kind": "behavior_change",
                        "repository_ids": [repository_id],
                        "description": "多一个入口",
                        "citations": [_CITATION_A],
                    }
                ],
                "regression_scope": [{"area": "用户中心", "level": "smoke", "reason": "改动小"}],
            }
        },
    }


async def _run_merge(session, *, plans: dict, sections: dict | None = None, failing=()):
    synthesizer = _FakeSynthesizer(sections=sections, failing=failing)
    adapter = BlueprintMergeAdapter(
        synthesizer=synthesizer, repo_plan_adapter=_FakeRepoPlanAdapter(plans)
    )
    result = await adapter.merge(session)
    return result, synthesizer


async def _landed_content(result: dict) -> dict:
    version = await ArtifactVersion.objects.filter(id=result["artifact_version_id"]).afirst()
    assert version is not None, result
    return version.content


def _all_citation_ids(node: Any) -> list[str]:
    """递归收集全文档（引用池之外）所有 citations 值。"""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "citations" and isinstance(value, list):
                found.extend(str(item) for item in value)
            elif key != "citations":
                found.extend(_all_citation_ids(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_all_citation_ids(item))
    return found


# ── 1. ⭐ 确定性投影不经推理 ───────────────────────────────────────────────


async def test_projection_sections_are_complete_without_any_drafted_content():
    """起草替身四段全返空 dict（零贡献）→ 投影两段仍完整且与上游逐字段相等。"""
    rid = _repo_id("a")
    association = _association(rid)
    session, _artifact = await _make_locked_session(association)
    plan = _repo_plan(rid)
    result, synthesizer = await _run_merge(session, plans={rid: plan})

    assert result["validation_status"] == "passed", result
    content = await _landed_content(result)

    # 起草器被问过五次（四段正文 + best-effort 执行摘要），但一个字都没贡献
    assert sorted(synthesizer.calls) == sorted(
        [
            SECTION_API_CONTRACTS,
            SECTION_IMPACT_ANALYSIS,
            SECTION_IMPLEMENTATION_OVERVIEW,
            SECTION_INTERACTION_FLOWS,
            "meta_summary",
        ]
    )

    # repo_associations 逐字段等于锁定产物
    projected = content["repo_associations"]
    assert len(projected) == 1
    entry = projected[0]
    assert entry["repository_id"] == association["repository_id"]
    assert entry["repository_name"] == association["repository_name"]
    assert entry["role"] == association["role"]
    assert entry["decided_by"] == association["decided_by"]
    assert entry["confirmed_at_gate"] == association["confirmed_at_gate"]
    assert entry["responsibility"] == association["responsibility"]
    assert entry["routing_evidence"] == association["routing_evidence"]
    assert entry["fitness"]["verdict"] == association["fitness"]["verdict"]

    # current_state_analysis 逐字段等于该仓 repo_plan.current_state
    analysis = content["current_state_analysis"]
    assert len(analysis) == 1
    assert analysis[0]["repository_id"] == rid
    source_finding = plan["current_state"][0]["findings"][0]
    projected_finding = analysis[0]["findings"][0]
    assert projected_finding["title"] == source_finding["title"]
    assert projected_finding["detail"] == source_finding["detail"]
    assert len(projected_finding["citations"]) == 1


async def test_all_four_sections_failing_returns_failed_without_version():
    """四段全抛才判整轮 failed（且不落版本）——单段失败绝不走到这里。"""
    rid = _repo_id("a")
    session, artifact = await _make_locked_session(_association(rid))
    before = await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount()
    result, _synthesizer = await _run_merge(
        session,
        plans={rid: _repo_plan(rid)},
        failing=(
            SECTION_IMPLEMENTATION_OVERVIEW,
            SECTION_API_CONTRACTS,
            SECTION_INTERACTION_FLOWS,
            SECTION_IMPACT_ANALYSIS,
        ),
    )
    assert result["validation_status"] == "failed"
    assert result["report"]["reason"] == "all_sections_failed"
    assert result["back_target"] == "merge"
    assert await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount() == before


async def test_projection_pure_functions_need_no_session_or_synthesizer():
    """两段投影是模块级纯函数：不碰 DB、不碰起草器，可直接调（可断言「不经推理」）。"""
    rid = _repo_id("a")
    association = _association(rid)
    plan = _repo_plan(rid)
    _entries, cite_map = build_citation_pool({rid: plan}, [association])

    associations = project_repo_associations([association], cite_map)
    current_state = project_current_state({rid: plan}, cite_map)

    assert associations[0]["repository_id"] == rid
    assert associations[0]["rationale"]["citations"] == [cite_map[_CITATION_A]]
    assert (
        current_state[0]["findings"][0]["detail"]
        == plan["current_state"][0]["findings"][0]["detail"]
    )


# ── 2. ⭐ P-8 覆盖率非零 ──────────────────────────────────────────────────


async def test_citation_coverage_is_positive_after_projection():
    """3 个带 citations 的 association → 覆盖率 > 0 且 rationale.citations 非空（P-8）。"""
    rids = [_repo_id(str(index)) for index in range(3)]
    associations = [_association(rid, citations=[_CITATION_A, _CITATION_B]) for rid in rids]
    session, _artifact = await _make_locked_session(*associations)
    plans = {rid: _repo_plan(rid) for rid in rids}
    result, _synthesizer = await _run_merge(
        session, plans=plans, sections=_drafted_sections(rids[0])
    )
    assert result["validation_status"] == "passed", result
    content = await _landed_content(result)

    assert citation_coverage(content) > 0
    assert content["repo_associations"][0]["rationale"]["citations"], (
        "rationale.citations 为空会让 repo_associations 这类条目分子恒 0（P-8）"
    )


# ── 3. ⭐ 引用完整性（P-5：先建引用池、各段只填池内 id） ────────────────────


async def test_assembled_blueprint_passes_validate_and_has_no_raw_path_citations():
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid))
    result, _synthesizer = await _run_merge(
        session, plans={rid: _repo_plan(rid)}, sections=_drafted_sections(rid)
    )
    content = await _landed_content(result)

    assert validate_blueprint(content) == (True, None)
    pool = content["citations"]
    used = _all_citation_ids({key: value for key, value in content.items() if key != "citations"})
    assert used, "样本应至少有一条引用，否则这条断言恒真"
    assert all(citation_id.startswith("cit_") for citation_id in used), used
    assert all(citation_id in pool for citation_id in used)


# ── 4. ⭐ 基线读最新版本（P-6 残留口 2） ────────────────────────────────────


async def test_baseline_reads_latest_version_not_the_pinned_one():
    rid_a, rid_b = _repo_id("a"), _repo_id("b")
    session, _artifact = await _make_locked_session(_association(rid_a), _association(rid_b))
    result, _synthesizer = await _run_merge(
        session, plans={rid_a: _repo_plan(rid_a), rid_b: _repo_plan(rid_b)}
    )
    content = await _landed_content(result)
    assert {entry["repository_id"] for entry in content["repo_associations"]} == {rid_a, rid_b}


# ── 5. must_haves 确定性派生 ──────────────────────────────────────────────


async def test_derive_must_haves_three_keys_and_dedup():
    overview = {
        "requirement_narrative": [],
        "items": [
            {
                "id": "impl_1",
                "title": "加接口",
                "files_touched": [
                    {"path": "a.py", "action": "create"},
                    {"path": "a.py", "action": "modify"},
                    {"path": "b.py", "action": "modify"},
                ],
                "depends_on": [],
            },
            {"id": "impl_2", "title": "接前端", "files_touched": [], "depends_on": ["impl_1"]},
        ],
    }
    contracts = [
        {"id": "api_p", "name": "listUsers", "direction": "provided", "repository_id": "repo-b"},
        {"id": "api_c", "name": "listUsers", "direction": "consumed", "repository_id": "repo-a"},
    ]
    must_haves = derive_must_haves(
        requirement_spec=_requirement_spec(),
        implementation_overview=overview,
        api_contracts=contracts,
    )
    assert set(must_haves) == {"truths", "artifacts", "key_links"}
    assert must_haves["truths"] == ["[fp_1] 用户列表：打开页面能看到用户列表"]
    assert [item["path"] for item in must_haves["artifacts"]] == ["a.py", "b.py"]
    assert {"from": "impl_2", "to": "impl_1", "via": "depends_on"} in must_haves["key_links"]
    assert {"from": "repo-b", "to": "repo-a", "via": "listUsers"} in must_haves["key_links"]


async def test_derive_must_haves_empty_items_still_has_all_three_keys():
    """空 items 时 `artifacts == []` 而非缺键——缺键会让整份蓝图 schema 失败。"""
    must_haves = derive_must_haves(requirement_spec={}, implementation_overview={})
    assert must_haves == {"truths": [], "artifacts": [], "key_links": []}


async def test_derived_must_haves_pass_schema_inside_assembled_blueprint():
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid))
    result, _synthesizer = await _run_merge(
        session, plans={rid: _repo_plan(rid)}, sections=_drafted_sections(rid)
    )
    content = await _landed_content(result)
    assert set(content["must_haves"]) == {"truths", "artifacts", "key_links"}
    assert content["must_haves"]["truths"]
    assert [item["path"] for item in content["must_haves"]["artifacts"]] == ["server/api/views.py"]


# ── 6. 分节而非单 prompt ──────────────────────────────────────────────────


async def test_sections_are_drafted_one_call_each():
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid))
    _result, synthesizer = await _run_merge(
        session, plans={rid: _repo_plan(rid)}, sections=_drafted_sections(rid)
    )
    # 四个正文分节 + 执行摘要（meta_summary，best-effort 第五次调用）各一次
    assert len(synthesizer.calls) == 5
    assert set(synthesizer.calls) == {
        SECTION_IMPLEMENTATION_OVERVIEW,
        SECTION_API_CONTRACTS,
        SECTION_INTERACTION_FLOWS,
        SECTION_IMPACT_ANALYSIS,
        "meta_summary",
    }
    # system 与 human 分离，且 prompt 不是同一份巨文本
    assert all(set(parts) == {"system", "human"} for parts in synthesizer.prompts)
    assert len({parts["human"] for parts in synthesizer.prompts}) == 5


# ── 7. ⭐ 单段失败降级为过 schema 的最小合法结构（W2） ──────────────────────


@pytest.mark.parametrize(
    "section",
    [
        SECTION_IMPLEMENTATION_OVERVIEW,
        SECTION_API_CONTRACTS,
        SECTION_INTERACTION_FLOWS,
        SECTION_IMPACT_ANALYSIS,
    ],
)
async def test_single_section_failure_degrades_gracefully(section):
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid))
    result, _synthesizer = await _run_merge(
        session,
        plans={rid: _repo_plan(rid)},
        sections=_drafted_sections(rid),
        failing=(section,),
    )
    assert result["validation_status"] == "passed", result
    content = await _landed_content(result)
    assert validate_blueprint(content) == (True, None)
    assert result["stage_state"]["merge"]["degraded_sections"] == [section]

    # 其余三段仍有内容
    if section != SECTION_IMPACT_ANALYSIS:
        assert content["impact_analysis"]["affected_features"]
    if section != SECTION_INTERACTION_FLOWS:
        assert content["interaction_flows"]
    if section != SECTION_API_CONTRACTS:
        assert content["api_contracts"]
    if section != SECTION_IMPLEMENTATION_OVERVIEW:
        assert content["implementation_overview"]["items"]


async def test_impact_analysis_degradation_keeps_both_required_keys():
    """降级值必须是 `{"business_impact": [], "affected_features": []}`——两键都在。

    缺 required 键会让 `validate_blueprint` 判**整份**非法：明明只挂一段却整轮 failed，
    那才是真正的失血点。
    """
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid))
    result, _synthesizer = await _run_merge(
        session,
        plans={rid: _repo_plan(rid)},
        sections=_drafted_sections(rid),
        failing=(SECTION_IMPACT_ANALYSIS,),
    )
    content = await _landed_content(result)
    assert content["impact_analysis"] == {"business_impact": [], "affected_features": []}


# ── 8. 顶层 required 十一键 + meta 承接（W2） ───────────────────────────────


async def test_assembled_has_all_required_top_level_keys_and_inherits_meta():
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid))
    result, _synthesizer = await _run_merge(
        session, plans={rid: _repo_plan(rid)}, sections=_drafted_sections(rid)
    )
    content = await _landed_content(result)

    assert set(BLUEPRINT_JSON_SCHEMA["required"]) <= set(content)
    assert content["schema_version"] == BLUEPRINT_SCHEMA_VERSION
    # meta 整段承接：非 required 键未丢
    assert content["meta"]["summary"] == _baseline_meta()["summary"]
    assert content["meta"]["revision_round"] == 2
    assert content["meta"]["language"] == "zh-CN"
    assert content["meta"]["title"] and content["meta"]["project_id"]
    # requirement_spec 承接自基线（含 feature_points[].intent）
    assert content["requirement_spec"]["feature_points"][0]["intent"] == "greenfield"


async def test_missing_meta_keys_are_backfilled_not_rebuilt():
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(
        _association(rid), meta={"language": "zh-CN", "revision_round": 1}
    )
    result, _synthesizer = await _run_merge(session, plans={rid: _repo_plan(rid)})
    content = await _landed_content(result)
    assert content["meta"]["language"] == "zh-CN"
    assert content["meta"]["revision_round"] == 1
    assert content["meta"]["title"] == "让用户能查看列表"
    assert content["meta"]["project_id"]


# ── 9. 对账矛盾抛澄清（绝不静默拍板） ─────────────────────────────────────


async def test_method_conflict_opens_blocking_clarification_and_lands_no_version():
    rid_a, rid_b = _repo_id("a"), _repo_id("b")
    session, artifact = await _make_locked_session(_association(rid_a), _association(rid_b))
    before = await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount()
    plans = {
        rid_a: _repo_plan(
            rid_a,
            apis_consumed=[
                {
                    "name": "listUsers",
                    "method": "GET",
                    "path": "/users",
                    "from_repository_id": rid_b,
                }
            ],
        ),
        rid_b: _repo_plan(
            rid_b, apis_provided=[{"name": "listUsers", "method": "POST", "path": "/users"}]
        ),
    }
    result, _synthesizer = await _run_merge(session, plans=plans)

    assert result["validation_status"] == "needs_clarification"
    assert result["back_target"] == "merge"
    assert result["reconcile"]["conflicts"] == 1
    assert result["artifact_version_id"] == ""
    assert await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount() == before

    thread = await BlueprintThread.objects.filter(artifact_id=artifact.id).afirst()
    assert thread is not None
    assert thread.kind == ThreadKind.AI_CLARIFICATION
    assert thread.blocking is True
    assert thread.return_stage == "merge"
    question = await BlueprintThreadMessage.objects.filter(thread_id=thread.id).afirst()
    assert question is not None
    assert "listUsers" in question.body and "method" in question.body
    # 澄清文本只列契约名与双方取值，不夹带方案正文（T-113-33）
    assert "写 view + serializer" not in question.body


async def test_missing_support_repo_opens_clarification():
    """无 provider 且推不出协作仓 → 缺协作仓，抛澄清而非静默落版本。"""
    rid_a = _repo_id("a")
    session, artifact = await _make_locked_session(_association(rid_a))
    plans = {
        rid_a: _repo_plan(
            rid_a, apis_consumed=[{"name": "somebodyElse", "method": "GET", "path": "/other"}]
        )
    }
    result, _synthesizer = await _run_merge(session, plans=plans)
    assert result["validation_status"] == "needs_clarification"
    assert result["reconcile"]["missing_support_repos"] == 1
    assert await BlueprintThread.objects.filter(artifact_id=artifact.id).acount() == 1


# ── 10. ⭐ consumed 无 provider 必标 needs_support（B4 路径断言） ────────────


async def test_unprovided_consumed_gets_needs_support_under_data_source_only():
    """标记只写 `data_source` 两键；顶层 `availability` 零残留（114/115 按 schema 才读得到）。"""
    rid_a, rid_b = _repo_id("a"), _repo_id("b")
    session, _artifact = await _make_locked_session(_association(rid_a), _association(rid_b))
    plans = {
        rid_a: _repo_plan(
            rid_a,
            apis_consumed=[
                {
                    "name": "needSomething",
                    "method": "GET",
                    "path": "/need",
                    # 协作仓线索：B 仓在锁定仓集里，故 needs_support 可闭合、无需澄清
                    "from_repository_id": rid_b,
                }
            ],
        ),
        rid_b: _repo_plan(rid_b),
    }
    result, _synthesizer = await _run_merge(session, plans=plans)
    assert result["validation_status"] == "passed", result
    content = await _landed_content(result)

    consumed = [item for item in content["api_contracts"] if item["direction"] == "consumed"]
    assert len(consumed) == 1
    item = consumed[0]
    assert item["data_source"]["availability"] == "needs_support"
    assert item["data_source"]["support_repository_id"] == rid_b
    assert "availability" not in item, "顶层 availability 会让 114/115 按 schema 路径读不到"
    assert "from_repository_id" not in item, "RepoPlan 中间产物专属键不落蓝图顶层"
    assert result["reconcile"]["missing_support_repos"] == 0


# ── 11. 幂等落版本（W6 口径：同 content_hash 与 current 相同才复用） ─────────


async def test_identical_merge_twice_does_not_bump_version():
    rid = _repo_id("a")
    session, artifact = await _make_locked_session(_association(rid))
    plans = {rid: _repo_plan(rid)}
    sections = _drafted_sections(rid)
    before = await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount()

    first, _s1 = await _run_merge(session, plans=plans, sections=sections)
    second, _s2 = await _run_merge(session, plans=plans, sections=sections)

    assert first["validation_status"] == second["validation_status"] == "passed"
    assert first["artifact_version_id"] == second["artifact_version_id"]
    assert await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount() == before + 1

    version = await ArtifactVersion.objects.filter(id=first["artifact_version_id"]).afirst()
    assert "attempt=" in version.produced_by_ref
    assert version.produced_by_ref.startswith("blueprint_merge#attempt=")


# ── 12. schema 不过不落版本 ───────────────────────────────────────────────


async def test_invalid_baseline_requirement_spec_fails_without_landing_version():
    """基线 `requirement_spec` 非法（goal 不是数组）→ failed 且版本数不变。

    融合**承接**基线的规格段而不重造（那是规格门锁定的产物），故基线坏了就该 fail-closed，
    绝不悄悄改写用户已锁定的 WHAT。
    """
    rid = _repo_id("a")
    session, artifact = await _make_locked_session(
        _association(rid), requirement_spec={"goal": "不是数组", "feature_points": []}
    )
    before = await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount()
    result, _synthesizer = await _run_merge(
        session, plans={rid: _repo_plan(rid)}, sections=_drafted_sections(rid)
    )
    assert result["validation_status"] == "failed"
    assert result["report"]["schema_error"]
    assert await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount() == before


async def test_missing_baseline_version_returns_failed():
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="merge",
        stage_state={},
    )
    result, _synthesizer = await _run_merge(session, plans={})
    assert result["validation_status"] == "failed"
    assert result["report"]["reason"] == "no_baseline_version"


# ── 13. 返回值带 artifact_version_id（113-06 回填依据） ─────────────────────


async def test_passed_result_carries_artifact_version_id_and_constant_shape():
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid))
    result, _synthesizer = await _run_merge(
        session, plans={rid: _repo_plan(rid)}, sections=_drafted_sections(rid)
    )
    assert set(result) == {
        "validation_status",
        "artifact_version_id",
        "attempt",
        "back_target",
        "report",
        "reconcile",
        "stage_state",
    }
    assert result["artifact_version_id"]
    assert result["attempt"] == 0
    assert result["stage_state"]["merge"]["count"] == 1


# ── 14. SCHEMA-03 / 04 / 05 形状 ──────────────────────────────────────────


async def test_schema_03_04_05_field_shapes():
    rid_a, rid_b = _repo_id("a"), _repo_id("b")
    session, _artifact = await _make_locked_session(_association(rid_a), _association(rid_b))
    plans = {
        rid_a: _repo_plan(
            rid_a,
            apis_provided=[{"name": "listUsers", "method": "GET", "path": "/users"}],
            impl_items=[
                {
                    "item_id": "it_1",
                    "title": "加接口",
                    "change_type": "create",
                    "how": "写 view",
                    "files_touched": ["server/api/views.py"],
                    "depends_on": [],
                },
                {
                    "item_id": "it_2",
                    "title": "接前端",
                    "change_type": "modify",
                    "how": "调接口",
                    "files_touched": ["web/src/pages/users.vue"],
                    "depends_on": ["it_1"],
                },
            ],
        ),
        rid_b: _repo_plan(
            rid_b,
            apis_consumed=[
                {
                    "name": "listUsers",
                    "method": "GET",
                    "path": "/users",
                    "from_repository_id": rid_a,
                    "data_source": {"availability": "existing", "fields_needed": ["id"]},
                }
            ],
        ),
    }
    result, _synthesizer = await _run_merge(session, plans=plans, sections=_drafted_sections(rid_a))
    assert result["validation_status"] == "passed", result
    content = await _landed_content(result)

    # SCHEMA-03：逐项带 change_type（合法枚举）与 wave；跨仓依赖投影成 depends_on
    items = content["implementation_overview"]["items"]
    assert items
    assert all(
        item["change_type"] in ("create", "modify", "remove", "indirect_refine") for item in items
    )
    assert all(isinstance(item["wave"], int) and item["wave"] >= 1 for item in items)
    by_title = {item["title"]: item for item in items}
    assert by_title["接前端"]["depends_on"] == [by_title["加接口"]["id"]]
    assert by_title["加接口"]["files_touched"] == [
        {"path": "server/api/views.py", "action": "create"}
    ]

    # SCHEMA-05：请求响应示例 + 数据来源说明
    contracts = {item["name"]: item for item in content["api_contracts"]}
    provided = contracts["listUsers"]
    assert provided["request_example"] == {"page": 1}
    assert provided["response_example"] == {"items": []}
    consumed = [item for item in content["api_contracts"] if item["direction"] == "consumed"][0]
    assert consumed["data_source"]["availability"] == "existing"
    assert consumed["data_source"]["fields_needed"] == ["id"]

    # SCHEMA-04：六要素 + steps[].seq + api_ref 已换算成真实契约 id
    flow = content["interaction_flows"][0]
    assert flow["trigger"]
    assert [step["seq"] for step in flow["steps"]] == [1, 2]
    first_step = flow["steps"][0]
    assert first_step["component"] and first_step["data_in"] and first_step["data_out"]
    contract_ids = {item["id"] for item in content["api_contracts"]}
    assert first_step["api_ref"] in contract_ids
    assert flow["alternative_paths"][0]["condition"] == "无权限"
