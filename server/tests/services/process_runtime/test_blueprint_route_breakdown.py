"""breakdown 纯函数机制级单测（CHARTER-02 / ROADMAP SC2 后半，112-03 Task 3）。

**断言机制而非结果名次**（对齐 112-CONTEXT）：

1. **恒等式**：`total` 逐位等于三项加权值之和（分数可拆解，CHARTER-02 硬要求）。
2. **章程分量对排序的可拆解影响**：排序差异能被**完全且仅**归因到 `charter_match`
   ——把该分量置 0 后两个候选总分相等。
3. **intent 加权方向**：greenfield 下章程+历史合计贡献 > router_base；
   brownfield/fix 下 router_base 主导。
4. **`resolve_boundary_override` 不变量**：命中禁区时「有理由」与「被打标记」恰有其一。
5. **权重加载全兜底**：缺键 / 非数值 / 负值 / 非 dict 一律回默认，绝不抛。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.process_runtime.blueprint_route import (
    DEFAULT_ROUTE_WEIGHTS,
    aload_route_weights,
    build_score_breakdown,
    resolve_boundary_override,
)

_GREENFIELD = DEFAULT_ROUTE_WEIGHTS["greenfield"]
_BROWNFIELD = DEFAULT_ROUTE_WEIGHTS["brownfield"]
_FIX = DEFAULT_ROUTE_WEIGHTS["fix"]

_AGET_JSON = "system.settings_service.aget_json_setting"


def _bd(router_base: float, charter_match: float, history_match: float, weights=None) -> dict:
    return build_score_breakdown(
        router_base=router_base,
        charter_match=charter_match,
        history_match=history_match,
        weights=weights or _GREENFIELD,
        evidence={"router_version": "v2"},
    )


# ── 恒等式：三项之和 == 总分 ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("router_base", "charter_match", "history_match"),
    [
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        (0.83, -0.4, 0.17),
        (0.5, -1.0, 0.0),
        (0.123456789, 0.987654321, 0.55555),
        (1.0, 0.0, 0.0),
        (0.0, 0.7, 0.0),
    ],
)
@pytest.mark.parametrize("weights", [_GREENFIELD, _BROWNFIELD, _FIX])
def test_total_equals_sum_of_components(
    router_base: float, charter_match: float, history_match: float, weights: dict
) -> None:
    """恒等式：`total` 与三项加权值之和逐位一致（同一批浮点值求和）。"""
    bd = _bd(router_base, charter_match, history_match, weights)

    assert abs(bd["total"] - (bd["router_base"] + bd["charter_match"] + bd["history_match"])) < 1e-9


def test_components_are_weighted_values() -> None:
    """三项是**加权后**的值（权重原样进 breakdown["weights"] 便于 115 回溯）。"""
    bd = _bd(1.0, 1.0, 1.0, _BROWNFIELD)

    assert bd["router_base"] == pytest.approx(_BROWNFIELD["router_base"])
    assert bd["charter_match"] == pytest.approx(_BROWNFIELD["charter_match"])
    assert bd["history_match"] == pytest.approx(_BROWNFIELD["history_match"])
    assert bd["weights"] == _BROWNFIELD


# ── 章程分量对排序的可拆解影响 ────────────────────────────────────────────


def test_charter_match_difference_fully_explains_ranking() -> None:
    """同 router_base 下章程分量高者总分更高，且置 0 后两者总分相等（差异可完全归因）。"""
    a = _bd(0.5, 0.7, 0.2)
    b = _bd(0.5, 0.0, 0.2)

    assert a["total"] > b["total"]

    a_zeroed = _bd(0.5, 0.0, 0.2)
    assert a_zeroed["total"] == pytest.approx(b["total"])
    # 差值恰等于章程分量的加权贡献差——排序差异**仅**由章程分量贡献
    assert a["total"] - b["total"] == pytest.approx(a["charter_match"] - b["charter_match"])


def test_negative_charter_match_lowers_total() -> None:
    """禁区命中（charter_match < 0）严格降低总分——降权而非被无视。"""
    penalized = _bd(0.8, -1.0, 0.3)
    neutral = _bd(0.8, 0.0, 0.3)

    assert penalized["total"] < neutral["total"]
    assert penalized["charter_match"] < 0


# ── intent 加权方向 ──────────────────────────────────────────────────────


def test_greenfield_favours_charter_and_history() -> None:
    """greenfield 权重下 charter+history 合计贡献严格大于 router_base 贡献。"""
    bd = _bd(1.0, 1.0, 1.0, _GREENFIELD)

    assert bd["charter_match"] + bd["history_match"] > bd["router_base"]


@pytest.mark.parametrize("weights", [_BROWNFIELD, _FIX])
def test_brownfield_and_fix_favour_router_base(weights: dict) -> None:
    """brownfield/fix 权重下 router_base 贡献占主导（改造重能力树命中）。"""
    bd = _bd(1.0, 1.0, 1.0, weights)

    assert bd["router_base"] > bd["charter_match"] + bd["history_match"]


# ── evidence 契约 ────────────────────────────────────────────────────────


def test_evidence_always_carries_router_version() -> None:
    """evidence 必带 router_version（v1_fallback 无能力节点证据时的可解释性要求）。"""
    bd = build_score_breakdown(
        router_base=0.4,
        charter_match=0.0,
        history_match=0.0,
        weights=_FIX,
        evidence={"router_version": "v1_fallback", "matched_node_paths": []},
    )

    assert bd["evidence"]["router_version"] == "v1_fallback"
    assert bd["evidence"]["matched_node_paths"] == []


def test_history_unavailable_visible_while_contributing_zero() -> None:
    """history 不可得时该项贡献为 0，但原因在 evidence 里可见（不伪装成「历史无命中」）。"""
    bd = build_score_breakdown(
        router_base=0.6,
        charter_match=0.0,
        history_match=0.0,
        weights=_GREENFIELD,
        evidence={"router_version": "v2", "history_match_unavailable": "no_acting_user"},
    )

    assert bd["history_match"] == 0.0
    assert bd["evidence"]["history_match_unavailable"] == "no_acting_user"


def test_evidence_missing_keys_get_neutral_defaults() -> None:
    """evidence 缺键补中性默认（下游 112-04/05 无需 .get 兜底）。"""
    bd = build_score_breakdown(
        router_base=0.0, charter_match=0.0, history_match=0.0, weights=_FIX, evidence={}
    )

    assert bd["evidence"]["boundary_override_reason"] == ""
    assert bd["evidence"]["unjustified_boundary_hit"] is False
    assert bd["evidence"]["violated_boundaries"] == []


# ── resolve_boundary_override 不变量（SC2 后半） ──────────────────────────


def test_no_boundary_hit_is_neutral() -> None:
    """未命中禁区 → ("", False)，不涉及本机制。"""
    assert resolve_boundary_override(
        violated_boundaries=[], router_reasoning="命中能力节点: a"
    ) == (
        "",
        False,
    )


def test_router_reasoning_alone_is_not_a_boundary_reason() -> None:
    """MJ-05：路由器 reasoning 是能力树命中说明，不能冒充禁区保留理由。

    它对召回的候选恒非空——认它就等于 `unjustified_boundary_hit` 永远为 False，
    「命中禁区仍保留时 LLM 必须给显式理由」只在形式上成立。
    """
    reason, unjustified = resolve_boundary_override(
        violated_boundaries=["不承接权益鉴权"],
        router_reasoning="命中能力节点: apps/study/entitlement",
        llm_reason="",
    )

    assert reason == ""
    assert unjustified is True


def test_llm_reason_is_the_only_accepted_reason() -> None:
    """命中禁区 → 只认 sanity-check LLM 的针对性理由，不打标记。"""
    reason, unjustified = resolve_boundary_override(
        violated_boundaries=["不承接权益鉴权"],
        router_reasoning="命中能力节点: apps/study/entitlement",
        llm_reason="本次写入面落在其 owned 领域",
    )

    assert reason == "本次写入面落在其 owned 领域"
    assert unjustified is False


def test_no_reason_flags_unjustified() -> None:
    """命中禁区 + 两来源皆空 → 打 unjustified_boundary_hit 标记（不静默保留）。"""
    assert resolve_boundary_override(
        violated_boundaries=["不承接权益鉴权"], router_reasoning="", llm_reason=""
    ) == ("", True)


def test_reason_is_truncated() -> None:
    """理由截断 300（防超长文本进 stage_state 与事件 payload）。"""
    reason, unjustified = resolve_boundary_override(
        violated_boundaries=["x"], llm_reason="理" * 500
    )

    assert len(reason) == 300
    assert unjustified is False


@pytest.mark.parametrize(
    ("router_reasoning", "llm_reason"),
    [
        ("命中能力节点: a", ""),
        ("", "LLM 给的理由"),
        ("", ""),
        ("   ", "   "),
        ("命中能力节点: a", "LLM 给的理由"),
        ("命中能力节点: a", "   "),
    ],
)
def test_boundary_hit_reason_xor_flag_invariant(router_reasoning: str, llm_reason: str) -> None:
    """不变量：命中禁区时「有理由」与「被打标记」**恰有其一**为真。"""
    reason, unjustified = resolve_boundary_override(
        violated_boundaries=["不承接权益鉴权"],
        router_reasoning=router_reasoning,
        llm_reason=llm_reason,
    )

    assert bool(reason) != unjustified


# ── aload_route_weights 全兜底（T-112-12） ───────────────────────────────


@pytest.mark.asyncio
async def test_weights_missing_setting_returns_defaults() -> None:
    """未配置 → 全默认。"""
    with patch(_AGET_JSON, new=AsyncMock(return_value=DEFAULT_ROUTE_WEIGHTS)):
        assert await aload_route_weights() == DEFAULT_ROUTE_WEIGHTS


@pytest.mark.asyncio
async def test_weights_non_dict_returns_defaults() -> None:
    """顶层非 dict（如 list）→ 整段回默认。"""
    with patch(_AGET_JSON, new=AsyncMock(return_value=[0.4, 0.35, 0.25])):
        assert await aload_route_weights() == DEFAULT_ROUTE_WEIGHTS


@pytest.mark.asyncio
async def test_weights_missing_intent_falls_back_per_intent() -> None:
    """某 intent 缺失 → 该 intent 回默认，其余生效值保留。"""
    with patch(
        _AGET_JSON,
        new=AsyncMock(
            return_value={
                "greenfield": {"router_base": 0.1, "charter_match": 0.8, "history_match": 0.1}
            }
        ),
    ):
        weights = await aload_route_weights()

    assert weights["greenfield"]["charter_match"] == pytest.approx(0.8)
    assert weights["brownfield"] == DEFAULT_ROUTE_WEIGHTS["brownfield"]
    assert weights["fix"] == DEFAULT_ROUTE_WEIGHTS["fix"]


@pytest.mark.asyncio
async def test_weights_missing_component_falls_back_per_component() -> None:
    """某 intent 缺某分量 → 该分量回默认（不整段丢弃已配置项）。"""
    with patch(
        _AGET_JSON,
        new=AsyncMock(return_value={"greenfield": {"router_base": 0.9, "history_match": 0.05}}),
    ):
        weights = await aload_route_weights()

    assert weights["greenfield"]["router_base"] == pytest.approx(0.9)
    assert weights["greenfield"]["charter_match"] == pytest.approx(
        DEFAULT_ROUTE_WEIGHTS["greenfield"]["charter_match"]
    )


@pytest.mark.asyncio
async def test_weights_non_numeric_falls_back() -> None:
    """非数值权重（如 "abc"）→ 该分量回默认，绝不抛。"""
    with patch(
        _AGET_JSON,
        new=AsyncMock(return_value={"fix": {"router_base": "abc", "charter_match": 0.2}}),
    ):
        weights = await aload_route_weights()

    assert weights["fix"]["router_base"] == pytest.approx(
        DEFAULT_ROUTE_WEIGHTS["fix"]["router_base"]
    )
    assert weights["fix"]["charter_match"] == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_negative_weights_clamped_to_zero() -> None:
    """负权重取 0（防「把某分量配成负数反向操纵排序」，T-112-12）。"""
    with patch(_AGET_JSON, new=AsyncMock(return_value={"fix": {"charter_match": -5.0}})):
        weights = await aload_route_weights()

    assert weights["fix"]["charter_match"] == 0.0


@pytest.mark.asyncio
async def test_weights_intent_value_not_dict_falls_back() -> None:
    """intent 的值非 dict → 该 intent 回默认。"""
    with patch(_AGET_JSON, new=AsyncMock(return_value={"greenfield": "heavy-charter"})):
        weights = await aload_route_weights()

    assert weights["greenfield"] == DEFAULT_ROUTE_WEIGHTS["greenfield"]


@pytest.mark.asyncio
async def test_weights_loader_exception_returns_defaults() -> None:
    """setting 读取抛异常 → 回默认，绝不上抛。"""
    with patch(_AGET_JSON, new=AsyncMock(side_effect=RuntimeError("db down"))):
        assert await aload_route_weights() == DEFAULT_ROUTE_WEIGHTS
