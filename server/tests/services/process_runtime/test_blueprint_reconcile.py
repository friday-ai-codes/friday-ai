"""跨仓 API 对账纯函数测试（Phase 113-05，FLOW-06）。

**零 DB、零 mock**：`reconcile_cross_repo_apis` 是纯函数，所有断言直接喂 dict。

守八件事：

1. **consumed 无 provider** → `gaps` 命中且 `reason == "no_provider"`。
2. **needs_support 缺 support_repository_id** → `missing_support_repos` 非空。
3. **support_repository_id 不在 repo_associations** → 同样进 `missing_support_repos`
   （缺协作仓的两种形态都被捕获）。
4. ⭐ **顶层 availability 不被识别（B4 防回归）**：只写顶层同名键的那条**不进**
   `missing_support_repos`，把同样语义写进 `data_source` 的那条**进**——两条并列，
   杜绝「路径写错还看起来通过」。
5. **字段不一致**：`method` / `request_schema` / `response_schema` 各一例，
   `conflicts` 带 `provider_value` / `consumer_value` 双值。
6. **完全闭环**：逐字段一致 → 三键全空。
7. **绝不抛**：`None` / `{}` / 类型错乱 → 恒定三键空 dict。
8. **口径一致性**：同一组 provided/consumed 喂 `build_api_waves` 与
   `reconcile_cross_repo_apis`，「有 provider」的结论一致（防两套匹配规则漂移）。
"""

from __future__ import annotations

import pytest

from services.process_runtime.blueprint_reconcile import reconcile_cross_repo_apis
from services.process_runtime.blueprint_repo_waves import build_api_waves

_EMPTY = {"gaps": [], "conflicts": [], "missing_support_repos": []}


# ── 工厂 ──────────────────────────────────────────────────────────────────


def _contract(
    contract_id: str,
    *,
    direction: str,
    repository_id: str,
    name: str = "listUsers",
    method: str = "GET",
    path: str = "/x",
    **extra,
) -> dict:
    item = {
        "id": contract_id,
        "name": name,
        "kind": "http",
        "direction": direction,
        "repository_id": repository_id,
        "method": method,
        "path": path,
    }
    item.update(extra)
    return item


def _blueprint(*contracts: dict, association_ids: tuple[str, ...] = ("repo-a", "repo-b")) -> dict:
    return {
        "repo_associations": [
            {"repository_id": rid, "repository_name": rid, "role": "direct"}
            for rid in association_ids
        ],
        "api_contracts": list(contracts),
    }


# ── 1. consumed 无 provider ───────────────────────────────────────────────


def test_consumed_without_provider_enters_gaps():
    blueprint = _blueprint(
        _contract("api_c", direction="consumed", repository_id="repo-a", path="/x")
    )
    result = reconcile_cross_repo_apis(blueprint)
    assert len(result["gaps"]) == 1
    assert result["gaps"][0]["repository_id"] == "repo-a"
    assert result["gaps"][0]["reason"] == "no_provider"
    assert result["gaps"][0]["api"] == "listUsers"
    assert result["conflicts"] == []


def test_gaps_are_not_truncated_so_every_contract_stays_actionable():
    """⭐ MJ-04：60 条无 provider 的 consumed → **60 条 gap 全在**，第 51 条也被标 needs_support。

    `gaps` 不开澄清，它是 `_apply_needs_support` 的逐条驱动源：截到 50 条会让第 51 条起的契约
    既不标 `data_source.availability = needs_support`、也进不了 `missing_support_repos`
    （那道检查只认已标 needs_support 的条目），最终原样落版本 —— 114/115 按 schema 读到
    「可用性未标注」= 默认可用，正是 FLOW-06 禁止的静默拍板。
    """
    from services.process_runtime.blueprint_merge import _apply_needs_support

    contracts = [
        _contract(
            f"api_c{i}",
            direction="consumed",
            repository_id="repo-a",
            name=f"listThing{i}",
            path=f"/x/{i}",
        )
        for i in range(60)
    ]
    blueprint = _blueprint(*contracts)

    result = reconcile_cross_repo_apis(blueprint)
    assert len(result["gaps"]) == 60, "第 51 条起被丢弃 = 那些契约永远不会被处置"

    applied = _apply_needs_support(blueprint["api_contracts"], result["gaps"], {})
    assert applied == 60
    # 逐条可处置：**第 51 条**（下标 50）与最后一条同样带上了可用性标注
    for index in (0, 50, 59):
        data_source = blueprint["api_contracts"][index]["data_source"]
        assert data_source["availability"] == "needs_support"


def test_same_repo_self_consumption_is_not_a_provider():
    """同仓自产自消不算跨仓 provider（与波次预排跳过自环同口径）。"""
    blueprint = _blueprint(
        _contract("api_p", direction="provided", repository_id="repo-a"),
        _contract("api_c", direction="consumed", repository_id="repo-a"),
    )
    result = reconcile_cross_repo_apis(blueprint)
    assert [gap["reason"] for gap in result["gaps"]] == ["no_provider"]


# ── 2 / 3. 缺协作仓的两种形态 ──────────────────────────────────────────────


def test_needs_support_without_support_repository_id():
    blueprint = _blueprint(
        _contract("api_p", direction="provided", repository_id="repo-b"),
        _contract(
            "api_c",
            direction="consumed",
            repository_id="repo-a",
            data_source={"availability": "needs_support"},
        ),
    )
    result = reconcile_cross_repo_apis(blueprint)
    assert len(result["missing_support_repos"]) == 1
    assert result["missing_support_repos"][0]["repository_id"] == "repo-a"
    assert result["missing_support_repos"][0]["support_repository_id"] == ""


def test_needs_support_with_support_repo_outside_associations():
    blueprint = _blueprint(
        _contract("api_p", direction="provided", repository_id="repo-b"),
        _contract(
            "api_c",
            direction="consumed",
            repository_id="repo-a",
            data_source={
                "availability": "needs_support",
                "support_repository_id": "repo-zzz",
            },
        ),
    )
    result = reconcile_cross_repo_apis(blueprint)
    assert len(result["missing_support_repos"]) == 1
    assert result["missing_support_repos"][0]["support_repository_id"] == "repo-zzz"


def test_needs_support_with_support_repo_in_associations_is_clean():
    blueprint = _blueprint(
        _contract("api_p", direction="provided", repository_id="repo-b"),
        _contract(
            "api_c",
            direction="consumed",
            repository_id="repo-a",
            data_source={
                "availability": "needs_support",
                "support_repository_id": "repo-b",
            },
        ),
    )
    assert reconcile_cross_repo_apis(blueprint)["missing_support_repos"] == []


# ── 4. ⭐ 顶层 availability 不被识别（B4 防回归） ──────────────────────────


def test_top_level_availability_key_is_never_read_but_data_source_is():
    """两条并列：顶层同名键那条不进 missing_support_repos，`data_source` 那条进。

    这条断言的存在意义就是「写错路径也能看起来通过」的反面 —— 111 schema 的
    `api_contracts[]` 没有顶层可用性字段，判定一旦读它，114/115 按 schema 路径
    就永远读不到 needs_support（SC-4 表面通过实际失效）。
    """
    blueprint = _blueprint(
        _contract("api_p", direction="provided", repository_id="repo-b"),
        # 只写顶层键（无 data_source）——必须被忽略
        _contract(
            "api_top",
            direction="consumed",
            repository_id="repo-a",
            name="topOnly",
            path="/top",
            availability="needs_support",
        ),
        # 同样语义写进 data_source——必须被识别
        _contract(
            "api_nested",
            direction="consumed",
            repository_id="repo-a",
            name="nested",
            path="/nested",
            data_source={"availability": "needs_support"},
        ),
    )
    result = reconcile_cross_repo_apis(blueprint)
    flagged = {entry["api"] for entry in result["missing_support_repos"]}
    assert "topOnly" not in flagged
    assert flagged == {"nested"}


# ── 5. 字段不一致 ─────────────────────────────────────────────────────────


def test_method_conflict_carries_both_values():
    blueprint = _blueprint(
        _contract("api_p", direction="provided", repository_id="repo-b", method="POST", path="/x"),
        _contract("api_c", direction="consumed", repository_id="repo-a", method="GET", path="/x"),
    )
    result = reconcile_cross_repo_apis(blueprint)
    assert result["gaps"] == []
    assert len(result["conflicts"]) == 1
    conflict = result["conflicts"][0]
    assert conflict["field"] == "method"
    assert conflict["provider_value"] == "POST"
    assert conflict["consumer_value"] == "GET"
    assert conflict["provider_repository_id"] == "repo-b"
    assert conflict["consumer_repository_id"] == "repo-a"


def test_request_schema_conflict():
    blueprint = _blueprint(
        _contract(
            "api_p",
            direction="provided",
            repository_id="repo-b",
            request_schema={"type": "object", "properties": {"a": {"type": "string"}}},
        ),
        _contract(
            "api_c",
            direction="consumed",
            repository_id="repo-a",
            request_schema={"type": "object", "properties": {"b": {"type": "string"}}},
        ),
    )
    fields = [c["field"] for c in reconcile_cross_repo_apis(blueprint)["conflicts"]]
    assert fields == ["request_schema"]


def test_response_schema_conflict():
    blueprint = _blueprint(
        _contract(
            "api_p", direction="provided", repository_id="repo-b", response_schema={"type": "array"}
        ),
        _contract(
            "api_c",
            direction="consumed",
            repository_id="repo-a",
            response_schema={"type": "object"},
        ),
    )
    fields = [c["field"] for c in reconcile_cross_repo_apis(blueprint)["conflicts"]]
    assert fields == ["response_schema"]


def test_one_sided_missing_field_is_not_a_conflict():
    """一侧未声明 schema 不算矛盾（阶段 2 半成品契约是常态）。"""
    blueprint = _blueprint(
        _contract(
            "api_p", direction="provided", repository_id="repo-b", response_schema={"type": "array"}
        ),
        _contract("api_c", direction="consumed", repository_id="repo-a"),
    )
    assert reconcile_cross_repo_apis(blueprint)["conflicts"] == []


# ── 6. 完全闭环 ───────────────────────────────────────────────────────────


def test_fully_matched_contracts_return_three_empty_keys():
    schema = {"type": "object"}
    blueprint = _blueprint(
        _contract(
            "api_p",
            direction="provided",
            repository_id="repo-b",
            request_schema=schema,
            response_schema=schema,
        ),
        _contract(
            "api_c",
            direction="consumed",
            repository_id="repo-a",
            request_schema=schema,
            response_schema=schema,
            data_source={"availability": "existing", "from_service": "repo-b"},
        ),
    )
    assert reconcile_cross_repo_apis(blueprint) == _EMPTY


# ── 7. 绝不抛 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        [],
        "not-a-dict",
        {"api_contracts": "not-a-list"},
        {"api_contracts": [None, 1, "x"]},
        {"api_contracts": [{"direction": "consumed", "data_source": "not-a-dict"}]},
        {"api_contracts": [{"direction": "consumed"}], "repo_associations": "not-a-list"},
        {"api_contracts": [{"direction": None, "name": None}]},
    ],
)
def test_never_raises_and_returns_constant_shape(payload):
    result = reconcile_cross_repo_apis(payload)
    assert set(result) == {"gaps", "conflicts", "missing_support_repos"}
    assert all(isinstance(value, list) for value in result.values())


def test_malformed_consumed_item_still_reports_gap_without_raising():
    blueprint = {"api_contracts": [{"direction": "consumed", "name": "x"}]}
    assert reconcile_cross_repo_apis(blueprint)["gaps"] == [
        {"repository_id": "", "api": "x", "reason": "no_provider"}
    ]


# ── 8. 与波次预排口径一致 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("consumed_path", "expect_provider"),
    [("/x", True), ("/nowhere", False)],
)
def test_provider_resolution_matches_build_api_waves(consumed_path, expect_provider):
    """同一组契约喂两个模块，「有 provider」的结论必须一致。

    口径漂移（一处按 name、一处按 path）会产出「预排说有 provider、对账说没有」的
    自相矛盾——那种矛盾任何单侧测试都逮不住。
    """
    provided = {"name": "listUsers", "method": "GET", "path": "/x"}
    consumed = {"name": "consumeSomethingElse", "method": "GET", "path": consumed_path}
    repo_plans = {
        "repo-a": {"apis_consumed": [consumed]},
        "repo-b": {"apis_provided": [provided]},
    }
    waves = build_api_waves(repo_plans)
    waves_has_provider = not waves["unresolved_consumed"]

    blueprint = _blueprint(
        _contract("api_p", direction="provided", repository_id="repo-b", **provided),
        _contract("api_c", direction="consumed", repository_id="repo-a", **consumed),
    )
    reconcile_has_provider = not reconcile_cross_repo_apis(blueprint)["gaps"]

    assert waves_has_provider is expect_provider
    assert reconcile_has_provider is waves_has_provider
