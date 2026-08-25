"""RepoPlan jsonschema 校验测试（Phase 113-03，SCHEMA-03 / DESIGN §5.3）。

守七件事（**零 DB 纯函数测试**，不加 django_db 标记）：

1. 合法 direct / indirect 两形状均放行（indirect 只有 role/responsibility/apis_provided）。
2. 三个必填字段（repository_id / role / impl_items）各缺一 → 报错且含字段名。
3. 枚举越界一律拒：role / change_type / data_source.availability；⭐ 含旧变体
   ``availab`` 系的历史值也必须拒（防枚举漂移复发）。
4. ``depends_on`` 引用不存在的 item_id → 拒且错误串含该 id。
5. ``needs_support`` 缺 ``support_repository_id`` → 拒且错误串含 ``data_source`` 路径。
6. ⭐ **判定只认 ``data_source.*`` 路径**：只写顶层同名键（无 data_source）不触发后置
   检查——证明可用性来源绝不取自幻觉字段。
7. **绝不外抛** + **报错脱敏截断**：None / [] / str / 怪异 dict 均返 (False, str)；
   含凭证样本的报错里凭证前缀零出现且长度有上界。
"""

from __future__ import annotations

from services.process_runtime.blueprint_repo_plan_schema import (
    REPO_PLAN_AVAILABILITY,
    REPO_PLAN_CHANGE_TYPES,
    coerce_repo_plan_shapes,
    validate_repo_plan,
)

# 满足 SENSITIVE_VALUE_PATTERN 的 friday_pat_ 门槛（前缀后 ≥20 字符），否则脱敏不会命中，
# 「凭证已脱敏」断言会在脱敏根本没发生时也通过（断言恒真、零覆盖）。
_SECRET = "friday_pat_abcdefghij1234567890"


def _direct_plan(**overrides) -> dict:
    plan: dict = {
        "repository_id": "repo-a",
        "role": "direct",
        "responsibility": [{"block_id": "blk_1", "type": "paragraph", "text": "承载学习页"}],
        "fitness": {
            "verdict": "suitable",
            "reasons": ["已有页面骨架"],
            "citations": ["src/pages/study/index.vue"],
        },
        "current_state": [
            {
                "summary": "已有 /study 路由",
                "findings": [
                    {
                        "title": "路由已注册",
                        "detail": "src/router 下有 /study",
                        "citations": ["src/router/index.ts"],
                    }
                ],
            }
        ],
        "impl_items": [
            {
                "item_id": "it_1",
                "title": "新增专项练习入口",
                "change_type": "create",
                "how": "在 study 页加入口卡片",
                "files_touched": ["src/pages/study/index.vue"],
                "depends_on": [],
                "test_strategy": "组件快照 + 点击跳转",
                "citations": ["src/pages/study/index.vue"],
            },
            {
                "item_id": "it_2",
                "title": "接入练习接口",
                "change_type": "modify",
                "how": "api 层加 fetchDrills",
                "files_touched": ["src/api/drill.ts"],
                "depends_on": ["it_1"],
            },
            {
                "item_id": "it_3",
                "title": "移除旧入口",
                "change_type": "remove",
                "how": "删除废弃 banner",
                "depends_on": ["it_1", "it_2"],
            },
        ],
        "apis_provided": [{"name": "getStudyEntry", "method": "GET", "path": "/api/study/entry/"}],
        "apis_consumed": [],
        "local_impact": {
            "affected_modules": ["study"],
            "affected_features": [{"name": "专项学习", "citations": []}],
            "migration_required": False,
            "notes": "无",
        },
        "risks": [{"block_id": "blk_r1", "text": "入口曝光可能影响首屏"}],
        "open_question_thread_ids": [],
    }
    plan.update(overrides)
    return plan


def _consumed(**data_source) -> list[dict]:
    return [
        {
            "name": "listDrills",
            "method": "GET",
            "path": "/api/drills/",
            "from_repository_id": "repo-b",
            "data_source": dict(data_source),
        }
    ]


# ===========================================================================
# 1. 合法形状
# ===========================================================================


def test_valid_direct_plan_passes() -> None:
    """完整 direct 方案（含 3 个 impl_items 与仓内 depends_on 引用）→ 放行。"""
    assert validate_repo_plan(_direct_plan()) == (True, None)


def test_valid_indirect_capability_list_passes() -> None:
    """indirect 仓的能力引用清单（只有 role/responsibility/apis_provided）→ 放行。"""
    plan = {
        "repository_id": "repo-b",
        "role": "indirect",
        "responsibility": [{"block_id": "blk_2", "text": "提供题库接口"}],
        "apis_provided": [{"name": "listDrills", "method": "GET", "path": "/api/drills/"}],
        "impl_items": [],
    }
    assert validate_repo_plan(plan) == (True, None)


def test_missing_block_ids_are_deterministically_normalized_before_validation() -> None:
    """缺 block_id 只补确定性锚点，完整实现项原样保留且重复归一化幂等。"""
    plan = _direct_plan(
        risks=[{"type": "paragraph", "text": "入口曝光可能影响首屏"}],
    )
    plan["impl_items"][0]["how"] = [{"type": "paragraph", "text": "在 study 页加入口卡片"}]
    expected_items = [dict(item) for item in plan["impl_items"]]
    expected_items[0] = {**expected_items[0], "how": [dict(plan["impl_items"][0]["how"][0])]}

    normalized = coerce_repo_plan_shapes(plan)
    first_risk_id = normalized["risks"][0]["block_id"]
    first_how_id = normalized["impl_items"][0]["how"][0]["block_id"]
    normalized_again = coerce_repo_plan_shapes(normalized)

    assert validate_repo_plan(normalized_again) == (True, None)
    assert first_risk_id == "blk_repo_plan_risks_repo-a_0"
    assert first_how_id == "blk_repo_plan_how_it_1_repo-a_0"
    assert normalized_again["risks"][0]["text"] == "入口曝光可能影响首屏"
    assert (
        normalized_again["impl_items"][0]["how"][0]["text"] == expected_items[0]["how"][0]["text"]
    )
    assert len(normalized_again["impl_items"]) == len(expected_items)


def test_block_id_normalization_does_not_hide_missing_text() -> None:
    """只缺锚点可修；缺实质正文仍拒绝，不能被归一化误放行。"""
    plan = _direct_plan(risks=[{"type": "paragraph"}])

    normalized = coerce_repo_plan_shapes(plan)
    ok, error = validate_repo_plan(normalized)

    assert normalized["risks"][0]["block_id"] == "blk_repo_plan_risks_repo-a_0"
    assert ok is False
    assert error is not None and "text" in error


def test_block_text_aliases_are_normalized_without_rewriting_content() -> None:
    """MCP 产物把正文写进 detail/summary 时机械搬运，避免有效方案因字段名漂移报废。"""
    plan = _direct_plan(
        risks=[
            {
                "summary": "上游字段依赖",
                "detail": "需要 course-business 补齐章级视频字段",
                "citations": ["services/course.go:42"],
            }
        ],
    )

    normalized = coerce_repo_plan_shapes(plan)

    assert validate_repo_plan(normalized) == (True, None)
    assert normalized["risks"][0]["text"] == "需要 course-business 补齐章级视频字段"
    assert normalized["risks"][0]["summary"] == "上游字段依赖"
    assert normalized["risks"][0]["citations"] == ["services/course.go:42"]


# ===========================================================================
# 2. 必填缺失
# ===========================================================================


def test_missing_required_fields_rejected() -> None:
    """三个必填字段各缺一 → (False, err) 且 err 含字段名。"""
    for field in ("repository_id", "role", "impl_items"):
        plan = _direct_plan()
        plan.pop(field)
        ok, err = validate_repo_plan(plan)
        assert ok is False, field
        assert err is not None and field in err, (field, err)


# ===========================================================================
# 3. 枚举越界
# ===========================================================================


def test_illegal_enums_rejected() -> None:
    """role / change_type / data_source.availability 三处枚举越界一律拒。"""
    ok, err = validate_repo_plan(_direct_plan(role="maybe"))
    assert ok is False and err is not None and "role" in err

    bogus_items = _direct_plan()["impl_items"]
    bogus_items[0] = {**bogus_items[0], "change_type": "bogus"}
    ok, err = validate_repo_plan(_direct_plan(impl_items=bogus_items))
    assert ok is False and err is not None and "change_type" in err

    ok, err = validate_repo_plan(_direct_plan(apis_consumed=_consumed(availability="whatever")))
    assert ok is False and err is not None and "availability" in err


def test_legacy_availability_variant_rejected() -> None:
    """⭐ 旧变体（111 schema 里不存在的值）也必须被拒——防枚举漂移复发。"""
    legacy = "avail" + "able"
    assert legacy not in REPO_PLAN_AVAILABILITY
    ok, err = validate_repo_plan(_direct_plan(apis_consumed=_consumed(availability=legacy)))
    assert ok is False and err is not None and "availability" in err


def test_change_type_enum_matches_blueprint_schema() -> None:
    """change_type 枚举与 111 已冻结的蓝图 schema 逐字同源（融合投影可直接搬）。"""
    from services.process_runtime.blueprint_schema import BLUEPRINT_JSON_SCHEMA

    frozen = BLUEPRINT_JSON_SCHEMA["properties"]["implementation_overview"]["properties"]["items"][
        "items"
    ]["properties"]["change_type"]["enum"]
    assert list(REPO_PLAN_CHANGE_TYPES) == list(frozen)


def test_availability_enum_matches_blueprint_schema() -> None:
    """data_source.availability 枚举与 111 的 api_contracts 同源，且只有两值。"""
    from services.process_runtime.blueprint_schema import BLUEPRINT_JSON_SCHEMA

    frozen = BLUEPRINT_JSON_SCHEMA["properties"]["api_contracts"]["items"]["properties"][
        "data_source"
    ]["properties"]["availability"]["enum"]
    assert list(REPO_PLAN_AVAILABILITY) == list(frozen)
    # 111 的 api_contracts 条目本身**没有**顶层可用性字段——RepoPlan 也不得引入。
    assert (
        "availability"
        not in BLUEPRINT_JSON_SCHEMA["properties"]["api_contracts"]["items"]["properties"]
    )


# ===========================================================================
# 4/5. 两条后置检查
# ===========================================================================


def test_depends_on_must_reference_local_item() -> None:
    """depends_on 引用不存在的 item_id → 拒且错误串含该 id（跨仓依赖走 apis_consumed）。"""
    items = _direct_plan()["impl_items"]
    items[1] = {**items[1], "depends_on": ["it_from_other_repo"]}
    ok, err = validate_repo_plan(_direct_plan(impl_items=items))
    assert ok is False
    assert err is not None and "it_from_other_repo" in err


def test_needs_support_requires_support_repository_id() -> None:
    """needs_support 缺 / 空 support_repository_id → 拒且错误串含 data_source 路径。"""
    for data_source in (
        {"availability": "needs_support"},
        {"availability": "needs_support", "support_repository_id": "  "},
    ):
        ok, err = validate_repo_plan(_direct_plan(apis_consumed=_consumed(**data_source)))
        assert ok is False
        assert err is not None and "data_source" in err

    ok, err = validate_repo_plan(
        _direct_plan(
            apis_consumed=_consumed(availability="needs_support", support_repository_id="repo-b")
        )
    )
    assert (ok, err) == (True, None)


def test_top_level_availability_key_is_not_a_source_of_truth() -> None:
    """⭐ 只写顶层同名键（无 data_source）→ 后置检查 (b) 不触发（判定只认 data_source.*）。"""
    plan = _direct_plan(apis_consumed=[{"name": "listDrills", "availability": "needs_support"}])
    assert validate_repo_plan(plan) == (True, None)


# ===========================================================================
# 6. 绝不外抛 + 报错脱敏
# ===========================================================================


def test_never_raises_on_hostile_input() -> None:
    """None / [] / str / 怪异 dict → 一律 (False, str)，绝不抛。"""
    weird: dict = {"repository_id": "r", "role": "direct", "impl_items": {}}
    weird["self"] = weird  # 自引用：jsonschema 走查也不得把异常抛给调用方
    for payload in (None, [], "str", 42, weird):
        ok, err = validate_repo_plan(payload)
        assert ok is False
        assert isinstance(err, str) and err


def test_error_message_redacted_and_truncated() -> None:
    """报错里凭证前缀零出现且长度有上界（半可信正文不得原样回显）。"""
    plan = _direct_plan(role=_SECRET)
    ok, err = validate_repo_plan(plan)
    assert ok is False
    assert err is not None
    assert "friday_pat_" not in err
    assert "***REDACTED***" in err
    assert len(err) <= 520
