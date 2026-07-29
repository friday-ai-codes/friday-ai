"""歧义四维打分 + 意图分类 helper 单测（Phase 112-02 Task 2）。

镜像 ``test_decompose_segments`` 范式：纯函数（归一/加权/阈值/配置）不触网；异步接线
patch 模块级符号 + AsyncMock 注入，覆盖 happy / JSON 健壮 / fail-soft / 缺 model。

守的核心不变量是**方向**：任何降级都朝「需澄清」（保守值 1.0 / 返回 None），绝不朝
「放行」——规格门是全链路唯一 fail-closed 点。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.process_runtime.blueprint_ambiguity_score import (
    DEFAULT_SPEC_GATE_CONFIG,
    aload_spec_gate_config,
    ascore_ambiguity,
    is_ambiguous,
    normalize_ambiguity_scores,
    weighted_total,
)
from services.process_runtime.blueprint_intent_classify import normalize_intents

_ARESOLVE = "services.provider_config.ProviderConfigService.aresolve"
_BUILD = "agents.llm_factory.build_chat_model"

_DIMS = ("goal", "boundary", "constraint", "acceptance")


def _resolved(default_model: str = "test-model") -> SimpleNamespace:
    return SimpleNamespace(extra={"default_model": default_model})


def _model_returning(content: object) -> MagicMock:
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(content=content))
    return model


def _full_payload(score: float = 0.1) -> dict:
    return {
        "dimensions": {dim: {"score": score, "reason": f"{dim} 说明"} for dim in _DIMS},
        "questions": [{"text": "目标用户是谁？", "options": ["高三", "初三"], "citations": ["c1"]}],
    }


def _dims(score: float) -> dict:
    return {dim: {"score": score, "reason": "r"} for dim in _DIMS}


# ── 纯函数：normalize_ambiguity_scores ────────────────────────────────────


def test_normalize_keeps_valid_payload() -> None:
    result = normalize_ambiguity_scores(_full_payload(0.25))
    assert set(result["dimensions"]) == set(_DIMS)
    assert all(entry["score"] == 0.25 for entry in result["dimensions"].values())
    assert result["questions"] == [
        {"text": "目标用户是谁？", "options": ["高三", "初三"], "citations": ["c1"]}
    ]


def test_normalize_missing_dimension_falls_back_to_conservative() -> None:
    """缺维 → 1.0（最歧义），绝不当作 0 放行。"""
    payload = _full_payload(0.1)
    del payload["dimensions"]["acceptance"]
    result = normalize_ambiguity_scores(payload)
    assert result["dimensions"]["acceptance"]["score"] == 1.0
    assert result["dimensions"]["goal"]["score"] == 0.1


@pytest.mark.parametrize(
    ("raw_score", "expected"),
    [("abc", 1.0), (None, 1.0), (-1, 0.0), (5, 1.0), ("0.4", 0.4), (True, 1.0)],
    ids=["non_numeric", "none", "negative_clamped", "overflow_clamped", "numeric_string", "bool"],
)
def test_normalize_score_coercion(raw_score: object, expected: float) -> None:
    payload = _full_payload(0.1)
    payload["dimensions"]["goal"]["score"] = raw_score
    assert normalize_ambiguity_scores(payload)["dimensions"]["goal"]["score"] == expected


def test_normalize_non_dict_input_is_all_conservative() -> None:
    for bad in (None, [], "text", 42):
        result = normalize_ambiguity_scores(bad)
        assert all(entry["score"] == 1.0 for entry in result["dimensions"].values())
        assert result["questions"] == []


def test_normalize_empty_reason_keeps_conservative_score() -> None:
    """理由为空 = 判定失去依据 → 该维降级到保守值 + 占位理由（fail-closed 方向）。"""
    payload = _full_payload(0.05)
    payload["dimensions"]["boundary"]["reason"] = "   "
    result = normalize_ambiguity_scores(payload)
    assert result["dimensions"]["boundary"]["score"] == 1.0
    assert result["dimensions"]["boundary"]["reason"]


def test_normalize_truncates_reason() -> None:
    payload = _full_payload(0.3)
    payload["dimensions"]["goal"]["reason"] = "长" * 500
    assert len(normalize_ambiguity_scores(payload)["dimensions"]["goal"]["reason"]) == 300


def test_normalize_questions_capped_and_filtered() -> None:
    payload = _full_payload(0.3)
    payload["questions"] = [{"text": ""}, {"text": "   "}, "noise"] + [
        {"text": f"q{i}"} for i in range(8)
    ]
    questions = normalize_ambiguity_scores(payload)["questions"]
    assert len(questions) == 5
    assert all(q["text"] for q in questions)
    assert questions[0] == {"text": "q0", "options": [], "citations": []}


def test_normalize_questions_whitelist_drops_unknown_keys() -> None:
    payload = _full_payload(0.3)
    payload["questions"] = [{"text": "q", "options": "not-a-list", "evil": "x", "citations": None}]
    assert normalize_ambiguity_scores(payload)["questions"] == [
        {"text": "q", "options": [], "citations": []}
    ]


# ── 纯函数：weighted_total / is_ambiguous ─────────────────────────────────


def test_weighted_total_uses_default_for_missing_weight() -> None:
    """权重缺项用同维默认（配置写坏了不得让某一维静默失重）。"""
    assert weighted_total(_dims(1.0), {"goal": 0.30}) == pytest.approx(1.0)


def test_weighted_total_all_zero_weights_falls_back_to_equal() -> None:
    zero = {dim: 0 for dim in _DIMS}
    assert weighted_total(_dims(0.4), zero) == pytest.approx(0.4)


def test_weighted_total_clamped() -> None:
    assert weighted_total(_dims(1.0), {dim: 10 for dim in _DIMS}) == 1.0
    assert weighted_total({}, DEFAULT_SPEC_GATE_CONFIG["weights"]) == pytest.approx(1.0)


def test_weighted_total_negative_weight_uses_default() -> None:
    assert weighted_total(_dims(1.0), {dim: -1 for dim in _DIMS}) == pytest.approx(1.0)


def test_is_ambiguous_boundary_is_inclusive() -> None:
    assert is_ambiguous(0.20, 0.20) is True
    assert is_ambiguous(0.19, 0.20) is False
    assert is_ambiguous("bad", 0.20) is True  # type: ignore[arg-type]


# ── aload_spec_gate_config ────────────────────────────────────────────────


def _save_setting(key: str, value: str) -> None:
    from system.models import SystemSetting

    SystemSetting.objects.update_or_create(key=key, defaults={"value": value})


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_load_config_missing_returns_default() -> None:
    assert await aload_spec_gate_config() == DEFAULT_SPEC_GATE_CONFIG


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_load_config_coerces_string_threshold() -> None:
    from asgiref.sync import sync_to_async

    from system.models import SettingKeys

    await sync_to_async(_save_setting)(
        SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, json.dumps({"threshold": "0.5"})
    )
    config = await aload_spec_gate_config()
    assert config["threshold"] == 0.5
    assert config["weights"] == DEFAULT_SPEC_GATE_CONFIG["weights"]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_load_config_clamps_extreme_threshold() -> None:
    """阈值被写成极端值不得让门形同虚设（T-112-07）。"""
    from asgiref.sync import sync_to_async

    from system.models import SettingKeys

    await sync_to_async(_save_setting)(
        SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, json.dumps({"threshold": 99})
    )
    assert (await aload_spec_gate_config())["threshold"] == 1.0


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_load_config_weights_list_falls_back() -> None:
    from asgiref.sync import sync_to_async

    from system.models import SettingKeys

    await sync_to_async(_save_setting)(
        SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG,
        json.dumps({"threshold": 0.3, "weights": [1, 2, 3]}),
    )
    config = await aload_spec_gate_config()
    assert config["weights"] == DEFAULT_SPEC_GATE_CONFIG["weights"]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_load_config_negative_weight_becomes_zero() -> None:
    from asgiref.sync import sync_to_async

    from system.models import SettingKeys

    await sync_to_async(_save_setting)(
        SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG,
        json.dumps({"weights": {"goal": -3, "boundary": 0.25}}),
    )
    config = await aload_spec_gate_config()
    assert config["weights"]["goal"] == 0.0
    assert config["weights"]["boundary"] == 0.25


# ── ascore_ambiguity 接线 ─────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_score_parses_bare_json() -> None:
    model = _model_returning(json.dumps(_full_payload(0.8)))
    with (
        patch(_ARESOLVE, AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=model),
    ):
        result = await ascore_ambiguity(goal="做个东西", feature_points=[{"id": "fp_01"}])
    assert result is not None
    assert result["dimensions"]["goal"]["score"] == 0.8
    assert len(result["questions"]) == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_score_parses_fenced_json() -> None:
    content = f"分析如下：\n```json\n{json.dumps(_full_payload(0.05))}\n```\n完毕"
    model = _model_returning(content)
    with (
        patch(_ARESOLVE, AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=model),
    ):
        result = await ascore_ambiguity(goal="g", feature_points=[{"id": "fp_01", "title": "t"}])
    assert result is not None
    assert result["dimensions"]["acceptance"]["score"] == 0.05


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_score_non_json_response_returns_none() -> None:
    """不可解析 → None（上游 fail-closed 判需澄清），绝不返回「全 0」放行。"""
    model = _model_returning("我觉得这个需求挺清楚的。")
    with (
        patch(_ARESOLVE, AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=model),
    ):
        assert await ascore_ambiguity(goal="g", feature_points=[]) is None


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_score_without_default_model_returns_none() -> None:
    with patch(_ARESOLVE, AsyncMock(return_value=_resolved(""))):
        assert await ascore_ambiguity(goal="g", feature_points=[]) is None


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_score_build_model_exception_swallowed() -> None:
    with (
        patch(_ARESOLVE, AsyncMock(return_value=_resolved())),
        patch(_BUILD, side_effect=RuntimeError("boom")),
    ):
        assert await ascore_ambiguity(goal="g", feature_points=[]) is None


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_score_prior_context_enters_prompt() -> None:
    """已澄清结论必须进重判输入，否则同一问题会被反复问。"""
    model = _model_returning(json.dumps(_full_payload(0.1)))
    with (
        patch(_ARESOLVE, AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=model),
    ):
        await ascore_ambiguity(goal="g", feature_points=[], prior_context="- 目标用户：高三学生")
    human_message = model.ainvoke.await_args.args[0][1]
    assert "高三学生" in human_message.content


# ── normalize_intents ─────────────────────────────────────────────────────


def test_normalize_intents_keeps_valid_values() -> None:
    raw = [
        {"id": "fp_01", "intent": "greenfield"},
        {"id": "fp_02", "intent": "brownfield"},
        {"id": "fp_03", "intent": "fix"},
    ]
    assert normalize_intents(raw, {"fp_01", "fp_02", "fp_03"}) == {
        "fp_01": "greenfield",
        "fp_02": "brownfield",
        "fp_03": "fix",
    }


def test_normalize_intents_drops_hallucinated_ids() -> None:
    raw = [{"id": "fp_01", "intent": "fix"}, {"id": "fp_99", "intent": "fix"}]
    assert normalize_intents(raw, {"fp_01"}) == {"fp_01": "fix"}


def test_normalize_intents_illegal_enum_falls_back_to_brownfield() -> None:
    raw = [{"id": "fp_01", "intent": "refactor"}, {"id": "fp_02"}]
    assert normalize_intents(raw, {"fp_01", "fp_02"}) == {
        "fp_01": "brownfield",
        "fp_02": "brownfield",
    }


def test_normalize_intents_non_list_input() -> None:
    assert normalize_intents(None, {"fp_01"}) == {}
    assert normalize_intents({"items": []}, {"fp_01"}) == {}
