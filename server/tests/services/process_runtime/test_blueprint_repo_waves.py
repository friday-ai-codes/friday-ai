"""波次预排纯函数测试（BUS-02，Phase 113-04）—— **零 DB、零 mock**。

守七类形态：

1. **provider 先行**：A 消费 B 提供的 `GET /x` → `{1: [B], 2: [A]}`（第一道防线成立）。
2. **三层链**：C ← B ← A → 三波各一仓，顺序正确。
3. **无依赖**：三仓互不引用 → 全在 wave 1（可完全并行，与预排前行为逐字一致）。
4. **显式 `from_repository_id` 优先**：path 对不上任何 provided 也仍建边（容器自述比形状猜测可信）。
5. **成环**：A ⇄ B → `cycles` 非空且含 {A, B}，两仓**仍在 waves 里**（放最后一波，不丢仓）。
6. **无 provider**：谁都不提供的 API → `unresolved_consumed` 有记录且该仓仍进 wave 1
   （113-05 的 `needs_support` 前置信号）。
7. `match_api` 三例：`(method, path)` 全等 / `name` 全等 / 都不等。
"""

from __future__ import annotations

from services.process_runtime.blueprint_repo_waves import build_api_waves, match_api


def _api(name: str = "", method: str = "", path: str = "", **extra) -> dict:
    api = {"name": name, "method": method, "path": path}
    api.update(extra)
    return api


def _all_ids(waves: dict) -> set[str]:
    return {rid for ids in waves.values() for rid in ids}


# ===========================================================================
# 1/2/3. 分层顺序
# ===========================================================================


def test_provider_repo_goes_to_earlier_wave() -> None:
    result = build_api_waves(
        {
            "A": {"apis_consumed": [_api(name="x", method="GET", path="/x")]},
            "B": {"apis_provided": [_api(name="x", method="GET", path="/x")]},
        }
    )
    assert result["waves"] == {1: ["B"], 2: ["A"]}
    assert result["edges"] == [{"from": "B", "to": "A", "api": "x"}]
    assert result["cycles"] == []
    assert result["unresolved_consumed"] == []


def test_three_layer_chain_orders_each_repo_in_own_wave() -> None:
    """A 消费 B、B 消费 C → C 最先、A 最后。"""
    result = build_api_waves(
        {
            "A": {"apis_consumed": [_api(name="b_api")]},
            "B": {
                "apis_provided": [_api(name="b_api")],
                "apis_consumed": [_api(name="c_api")],
            },
            "C": {"apis_provided": [_api(name="c_api")]},
        }
    )
    assert result["waves"] == {1: ["C"], 2: ["B"], 3: ["A"]}
    assert result["cycles"] == []


def test_no_dependencies_means_single_wave_full_parallel() -> None:
    result = build_api_waves({"A": {}, "B": {"apis_provided": []}, "C": {"apis_consumed": []}})
    assert result["waves"] == {1: ["A", "B", "C"]}
    assert result["edges"] == []
    assert result["unresolved_consumed"] == []


def test_empty_input_returns_constant_empty_shape() -> None:
    assert build_api_waves({}) == {
        "waves": {},
        "edges": [],
        "cycles": [],
        "unresolved_consumed": [],
    }


# ===========================================================================
# 4. 显式 from_repository_id 优先
# ===========================================================================


def test_explicit_from_repository_id_wins_over_shape_matching() -> None:
    """path 与任何 provided 都不匹配，但显式指了 B → 仍建边 B→A。"""
    result = build_api_waves(
        {
            "A": {
                "apis_consumed": [
                    _api(name="unknown", method="POST", path="/nope", from_repository_id="B")
                ]
            },
            "B": {"apis_provided": [_api(name="other", method="GET", path="/other")]},
        }
    )
    assert result["waves"] == {1: ["B"], 2: ["A"]}
    assert result["edges"] == [{"from": "B", "to": "A", "api": "unknown"}]
    assert result["unresolved_consumed"] == []


def test_explicit_from_repository_id_pointing_to_unknown_repo_is_unresolved() -> None:
    """指向不在本次仓集里的仓 → 不建假边，如实记 unresolved（绝不静默）。"""
    result = build_api_waves({"A": {"apis_consumed": [_api(name="z", from_repository_id="ZZZ")]}})
    assert result["edges"] == []
    assert result["unresolved_consumed"] == [{"repository_id": "A", "api": "z"}]
    assert result["waves"] == {1: ["A"]}


# ===========================================================================
# 5. 成环：如实上报 + 不丢仓
# ===========================================================================


def test_mutual_dependency_reports_cycle_and_keeps_repos_in_waves() -> None:
    result = build_api_waves(
        {
            "A": {
                "apis_provided": [_api(name="a_api")],
                "apis_consumed": [_api(name="b_api")],
            },
            "B": {
                "apis_provided": [_api(name="b_api")],
                "apis_consumed": [_api(name="a_api")],
            },
        }
    )
    assert result["cycles"], "互等必须如实上报，绝不静默打平"
    assert {frozenset(cycle) for cycle in result["cycles"]} == {frozenset({"A", "B"})}
    # 成环的仓仍在 waves 里（放最后一波）——绝不丢仓。
    assert _all_ids(result["waves"]) == {"A", "B"}


def test_cycle_repos_are_placed_in_last_wave_after_acyclic_ones() -> None:
    """无环仓正常分层，成环仓统一挂最后一波。"""
    result = build_api_waves(
        {
            "A": {"apis_provided": [_api(name="a_api")], "apis_consumed": [_api(name="b_api")]},
            "B": {"apis_provided": [_api(name="b_api")], "apis_consumed": [_api(name="a_api")]},
            "C": {"apis_provided": [_api(name="c_api")]},
            "D": {"apis_consumed": [_api(name="c_api")]},
        }
    )
    assert result["waves"][1] == ["C"]
    assert result["waves"][2] == ["D"]
    assert result["waves"][3] == ["A", "B"]


def test_self_consumed_api_does_not_create_self_edge() -> None:
    """自己提供也自己消费 → 不建自环、不判成环（同仓内部依赖不是跨仓关系）。"""
    result = build_api_waves(
        {"A": {"apis_provided": [_api(name="x")], "apis_consumed": [_api(name="x")]}}
    )
    assert result["cycles"] == []
    assert result["edges"] == []
    assert result["unresolved_consumed"] == [{"repository_id": "A", "api": "x"}]


# ===========================================================================
# 6. 无 provider
# ===========================================================================


def test_consumed_without_any_provider_is_reported_unresolved() -> None:
    result = build_api_waves(
        {
            "A": {"apis_consumed": [_api(name="ghost", method="GET", path="/ghost")]},
            "B": {"apis_provided": [_api(name="real", method="GET", path="/real")]},
        }
    )
    assert result["unresolved_consumed"] == [{"repository_id": "A", "api": "ghost"}]
    # 找不到 provider 不影响 A 开工（它得自己去标 needs_support）。
    assert result["waves"] == {1: ["A", "B"]}


def test_half_trusted_input_is_defended_without_raising() -> None:
    """半可信输入：非 dict section / 非 list / 非 dict 元素一律跳过，绝不抛。"""
    result = build_api_waves(
        {
            "A": "not-a-dict",  # type: ignore[dict-item]
            "B": {"apis_consumed": "nope", "apis_provided": [None, 1, _api(name="ok")]},
            "C": {"apis_consumed": [None, _api(name="ok")]},
            "": {"apis_provided": [_api(name="ok")]},
        }
    )
    assert result["waves"] == {1: ["A", "B"], 2: ["C"]}
    assert result["edges"] == [{"from": "B", "to": "C", "api": "ok"}]


# ===========================================================================
# 7. match_api 纯函数
# ===========================================================================


def test_match_api_by_method_and_path() -> None:
    assert match_api(_api(method="get", path="/x"), _api(method="GET", path="/x")) is True
    # path 同但 method 不同 → 不算同一接口
    assert match_api(_api(method="POST", path="/x"), _api(method="GET", path="/x")) is False


def test_match_api_by_name() -> None:
    assert match_api(_api(name="listUsers"), _api(name="listUsers")) is True
    assert match_api(_api(name="listUsers", path="/a"), _api(name="listUsers", path="/b")) is True


def test_match_api_no_match() -> None:
    assert match_api(_api(name="a", method="GET", path="/a"), _api(name="b", path="/b")) is False
    assert match_api({}, {}) is False
    assert match_api(None, _api(name="a")) is False  # type: ignore[arg-type]
