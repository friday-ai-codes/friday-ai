"""蓝图路由的模块聚合与 supporting 置信度（Fix A / Fix B，纯函数，零 DB）。

覆盖三条机制事实：

1. ``_requirement_spec_to_feature_list`` 产出**真实** ``modules[]``（不再伪造
   ``[{"name": "requirement"}]``），多模块功能点因此能被 ``build_placement_units``
   拆成多个 PlacementUnit —— 否则全部落 ``_unassigned`` 单桶，多模块需求只会发一次
   ``RepoRouterV2`` 查询，而且**不报任何错**。
2. ``_aapply_placement_funnel`` 用 ``merge_depends_on=False``：depends_on 只连 unit 边，
   不并查合并回单元。
3. ``_raw_candidates_from_placements`` 的 supporting 置信度来自 ``scores[sid]``（复用
   ``place_units._confidence_from_score`` 阈值），不再恒 ``low``。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from services.process_runtime.blueprint_route import (
    MEGA_UNIT_DEGRADE_REASON,
    BlueprintRouteAdapter,
    _requirement_spec_to_feature_list,
)
from services.process_runtime.placement_units import (
    PlacementUnitsResult,
    build_placement_units,
)


def _point(pid: str, title: str, *, module: str = "", description: str = "") -> dict[str, Any]:
    point: dict[str, Any] = {"id": pid, "title": title, "intent": "greenfield"}
    if module:
        point["module"] = module
    if description:
        point["description"] = [
            {"block_id": f"{pid}_desc_1", "type": "paragraph", "text": description}
        ]
    return point


def _spec(points: list[dict[str, Any]], *, goal: str = "让高三学生一键生成个性化练习") -> dict:
    return {
        "goal": [{"block_id": "goal_1", "type": "paragraph", "text": goal}],
        "feature_points": points,
    }


# ══════════════════════════════════════════════════════════════════════════
# Fix A：真实 modules[] → 多 PlacementUnit
# ══════════════════════════════════════════════════════════════════════════


def test_distinct_modules_produce_real_module_list_without_fake_requirement() -> None:
    """两个模块 → ``modules[]`` 两条真实模块名；⛔ 不再有 ``"requirement"`` 假模块。"""
    spec = _spec(
        [
            _point("fp_1", "习题生成接口", module="practice"),
            _point("fp_2", "生成埋点", module="observability"),
        ]
    )

    feature_list = _requirement_spec_to_feature_list(spec)

    assert [m["name"] for m in feature_list["modules"]] == ["practice", "observability"]
    assert "requirement" not in {m["name"] for m in feature_list["modules"]}
    assert [f["module"] for f in feature_list["features_flat"]] == [
        "practice",
        "observability",
    ]
    assert feature_list["_degrade_reasons"] == []


def test_distinct_modules_yield_multiple_placement_units() -> None:
    """⭐ 端到端事实：不同模块 → ``unit_count >= 2``（多次 RepoRouterV2 查询的前提）。"""
    spec = _spec(
        [
            _point("fp_1", "习题生成接口", module="practice"),
            _point("fp_2", "练习页入口", module="practice"),
            _point("fp_3", "生成埋点", module="observability"),
        ]
    )

    result = build_placement_units(feature_list=_requirement_spec_to_feature_list(spec))

    assert result.unit_count >= 2
    assert sorted(sorted(u.module_names) for u in result.units) == [
        ["observability"],
        ["practice"],
    ]


def test_same_module_features_still_merge_into_one_unit() -> None:
    """回归：同模块多功能点仍合并为 1 个 unit（拆分不是越碎越好）。"""
    spec = _spec(
        [
            _point("fp_1", "习题生成接口", module="practice"),
            _point("fp_2", "练习页入口", module="practice"),
            _point("fp_3", "错题本", module="practice"),
        ]
    )

    result = build_placement_units(feature_list=_requirement_spec_to_feature_list(spec))

    assert result.unit_count == 1
    assert result.units[0].feature_ids and len(result.units[0].feature_ids) == 3


def test_description_is_flattened_text_not_repr_of_block_list() -> None:
    """description 必须过 ``_blocks_to_text``：``str(list)`` 会把 block 字典喂进语料。"""
    spec = _spec([_point("fp_1", "习题生成接口", module="practice", description="按学科出题")])

    feature = _requirement_spec_to_feature_list(spec)["features_flat"][0]

    assert feature["description"] == "按学科出题"
    assert "block_id" not in feature["description"]
    assert feature["id"] == "fp_1"


def test_legacy_description_recovers_module_and_avoids_mega_unit() -> None:
    """legacy 兼容：旧 intake 只把 ``"模块A / layer"`` 写进 description → 回收模块名。

    存量蓝图的功能点没有结构化 ``module``；不回收就会 5 个功能点全塌成 1 个 unit。
    """
    spec = _spec(
        [
            _point("fp_1", "任务列表", description="模块A / backend"),
            _point("fp_2", "任务详情", description="模块A / frontend"),
            _point("fp_3", "练习入口", description="模块B / frontend"),
            _point("fp_4", "错题本", description="模块B / backend"),
            _point("fp_5", "生成埋点", description="模块C / backend"),
        ]
    )

    feature_list = _requirement_spec_to_feature_list(spec)

    assert [m["name"] for m in feature_list["modules"]] == ["模块A", "模块B", "模块C"]
    assert feature_list["_degrade_reasons"] == []
    assert build_placement_units(feature_list=feature_list).unit_count == 3


def test_repeated_short_description_head_is_treated_as_a_grouping_key() -> None:
    """module-only 旧数据（description 就是模块名）：同一 head 复现 ⇒ 它在充当分组键。"""
    spec = _spec(
        [
            _point("fp_1", "习题生成接口", description="practice"),
            _point("fp_2", "练习页入口", description="practice"),
            _point("fp_3", "生成埋点", description="observability"),
            _point("fp_4", "埋点看板", description="observability"),
        ]
    )

    feature_list = _requirement_spec_to_feature_list(spec)

    assert [m["name"] for m in feature_list["modules"]] == ["practice", "observability"]


def test_one_off_short_description_is_not_promoted_to_a_module() -> None:
    """只出现一次、又无「模块」字样/legacy 分隔符的短首段不采信（弱信号不猜）。"""
    spec = _spec(
        [
            _point("fp_1", "习题生成接口", description="一键出题"),
            _point("fp_2", "练习页入口", description="打开练习"),
        ]
    )

    feature_list = _requirement_spec_to_feature_list(spec)

    assert feature_list["modules"] == []


def test_sentence_description_is_not_mistaken_for_a_module_name() -> None:
    """⛔ 宁缺勿造：整句需求正文不得被当成模块名（会按噪声聚合，比塌成单桶更糟）。"""
    spec = _spec(
        [
            _point("fp_1", "任务列表", description="用户可以在看板上查看任务，并按学科筛选。"),
            _point("fp_2", "任务详情", description="点击任务后展示进度与截止时间。"),
        ]
    )

    feature_list = _requirement_spec_to_feature_list(spec)

    assert feature_list["modules"] == []
    assert [f["module"] for f in feature_list["features_flat"]] == ["", ""]


def test_mega_unit_guardrail_records_degrade_reason_instead_of_pretending() -> None:
    """5+ 功能点却凑不出 2 个模块 → 显式记 degrade，⛔ 不静默假装已拆分。"""
    spec = _spec([_point(f"fp_{i}", f"功能{i}") for i in range(1, 6)])

    feature_list = _requirement_spec_to_feature_list(spec)

    assert feature_list["_degrade_reasons"] == [MEGA_UNIT_DEGRADE_REASON]
    assert build_placement_units(feature_list=feature_list).unit_count == 1


def test_mega_unit_guardrail_event_is_sampling_and_carries_no_requirement_body(
    monkeypatch,
) -> None:
    """guardrail 事件是 sampling 类，kv 只有计数——⛔ 不 dump 需求正文。"""
    events: list[tuple[str, dict]] = []

    class _FakeLogger:
        def info(self, event, **kwargs):
            events.append((event, kwargs))

        def warning(self, event, **kwargs):
            events.append((event, kwargs))

    monkeypatch.setattr("services.process_runtime.blueprint_route.logger", _FakeLogger())
    secret = "这段需求正文不该出现在日志里，它只该留在蓝图内容里。"
    _requirement_spec_to_feature_list(
        _spec([_point(f"fp_{i}", f"功能{i}", description=secret) for i in range(1, 6)])
    )

    event, kwargs = next(
        (e, kw) for e, kw in events if e == "blueprint_route_placement_mega_unit_guardrail"
    )
    assert event
    assert kwargs["category"] == "sampling"
    assert kwargs["component"] == "process_runtime"
    assert kwargs["feature_count"] == 5
    assert kwargs["unit_module_count"] == 0
    assert secret not in " ".join(str(v) for v in kwargs.values())


async def test_funnel_builds_units_without_merging_depends_on() -> None:
    """⭐ funnel 必须传 ``merge_depends_on=False``（否则依赖模块又塌回一个 unit）。"""
    captured: dict[str, Any] = {}

    def _fake_build(**kwargs):
        captured.update(kwargs)
        return PlacementUnitsResult(
            status="ok", units=[], unit_count=0, duration_ms=0.0, degrade_reasons=[]
        )

    spec = _spec(
        [
            _point("fp_1", "任务列表", module="模块A"),
            _point("fp_2", "练习入口", module="模块B"),
        ]
    )

    with (
        patch(
            "services.process_runtime.placement_units.build_placement_units",
            side_effect=_fake_build,
        ),
        patch(
            "services.process_runtime.place_units.place_units",
            new=AsyncMock(side_effect=RuntimeError("place down")),
        ),
    ):
        result = await BlueprintRouteAdapter()._aapply_placement_funnel(
            requirement_spec=spec,
            shortlist_ids=["r-1"],
            team_core=["r-1"],
            router=object(),
        )

    assert captured["merge_depends_on"] is False
    assert captured["feature_list"]["modules"]
    # place_units 抛错只降级，不抛给调用方（fail-soft 回归）
    assert result["degrade_reasons"] == ["place_units_failed"]


async def test_funnel_propagates_mega_unit_degrade_reason() -> None:
    """guardrail 的 degrade 原因要能被 funnel 带出去（可观测、可判读）。"""
    spec = _spec([_point(f"fp_{i}", f"功能{i}") for i in range(1, 6)])

    with patch(
        "services.process_runtime.place_units.place_units",
        new=AsyncMock(side_effect=RuntimeError("place down")),
    ):
        result = await BlueprintRouteAdapter()._aapply_placement_funnel(
            requirement_spec=spec,
            shortlist_ids=["r-1"],
            team_core=["r-1"],
            router=object(),
        )

    assert MEGA_UNIT_DEGRADE_REASON in result["degrade_reasons"]


# ══════════════════════════════════════════════════════════════════════════
# Fix B：supporting 置信度随 V2 分数
# ══════════════════════════════════════════════════════════════════════════


def _candidates(placements: list[dict]) -> dict[str, dict]:
    raw = BlueprintRouteAdapter()._raw_candidates_from_placements(
        placements, hard_scope=set(), excluded=set()
    )
    return {c["repository_id"]: c for c in raw}


def test_high_scoring_supporting_repo_is_not_pinned_to_low() -> None:
    """⭐ supporting 高分 → high/medium；旧实现恒 low 会让角色建议恒偏 indirect。"""
    placements = [
        {
            "unit_id": "u-1",
            "primary_repo": "r-primary",
            "supporting_repos": ["r-strong", "r-mid"],
            "confidence": "high",
            "scores": {"r-primary": 0.9, "r-strong": 0.8, "r-mid": 0.5},
        }
    ]

    by_id = _candidates(placements)

    assert by_id["r-strong"]["confidence"] == "high"
    assert by_id["r-strong"]["router_base"] == 0.8
    assert by_id["r-mid"]["confidence"] == "medium"


def test_low_scoring_supporting_repo_stays_low() -> None:
    """低分 supporting 仍为 low（阈值来自 ``_confidence_from_score``，不是硬编码）。"""
    placements = [
        {
            "unit_id": "u-1",
            "primary_repo": "r-primary",
            "supporting_repos": ["r-weak"],
            "scores": {"r-weak": 0.2},
        }
    ]

    assert _candidates(placements)["r-weak"]["confidence"] == "low"


def test_supporting_without_score_uses_router_base_default() -> None:
    """缺分走既有默认 0.35 → low（仍经 helper，不新增硬编码分支）。"""
    placements = [
        {"unit_id": "u-1", "primary_repo": "r-primary", "supporting_repos": ["r-unknown"]}
    ]

    candidate = _candidates(placements)["r-unknown"]

    assert candidate["router_base"] == 0.35
    assert candidate["confidence"] == "low"


def test_primary_confidence_still_comes_from_placement() -> None:
    """primary 行为不变：置信度取 ``placement.confidence``，缺省 medium。"""
    placements = [
        {"unit_id": "u-1", "primary_repo": "r-a", "confidence": "high", "scores": {"r-a": 0.2}},
        {"unit_id": "u-2", "primary_repo": "r-b", "scores": {"r-b": 0.9}},
    ]

    by_id = _candidates(placements)

    assert by_id["r-a"]["confidence"] == "high"
    assert by_id["r-b"]["confidence"] == "medium"
