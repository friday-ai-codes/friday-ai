"""assumptions 三档守护测试（GATE-01，Phase 116-06）。

守十件事：

1. **不传档位时行为逐字不变**：``threshold`` 与改动前相同、``max_rounds == 3``。
2. **三档各自的 ``threshold`` / ``max_rounds`` 生效**（参数化三条）。
3. ⭐ **三个调用点口径一致**：跑一轮完整 spec_gate，断言 ``ambiguity_report["threshold"]``
   与实际判定用的阈值**相等**（⛔ 不接受只测 ``aload_spec_gate_config`` 本身）。
3b. ⭐ **sampling 日志不撒谎**：``blueprint_ambiguity_score_completed`` 报的 ``threshold``
    必须等于该档配置值。⭐ **变异**：去掉 ``ascore_ambiguity`` 里的 ``tier=tier`` ⇒ 本条转红
    （``:434`` 会读回默认阈值）。
4. ⭐ **``max_rounds`` 真的生效**：``assume_more`` 档配 ``max_rounds=1`` ⇒ 第 1 轮即
   ``capped``（⛔ 不再是硬编码的 3）。
5. ⭐ **``assume_more`` ≠ ``skip_clarification``**（本文件头号靶子，T-116-52）：``assume_more``
   档下歧义分**高于该档阈值**的需求 ⇒ (a) 四维打分**仍然执行**、(b) **仍然开 blocking 线程**。
   **并列反向对照**：同一需求在 ``strict`` 档下同样开线程 ⇒ 档位只改「问多少」不改「问不问
   这件事本身」；且源码里 ``skip_clarification`` 零命中。
6. **畸形配置回默认**：非 dict / 档名不存在 / ``max_rounds`` 为 0 或负 ⇒ 回落且**不抛**。
7. ``ambiguity_report`` 里记了 ``assumptions_tier`` 与 ``max_rounds``。
7b. ⭐ **``_MAX_SPEC_GATE_ROUNDS`` 已无处可寻**，且默认行为逐字不变（不配任何东西时第 3 轮
    才 ``capped``，与改动前一致）。
8. **既有 spec_gate / ambiguity 用例零回归**（由那两个文件自身承担）。

scorer 经构造参数注入 AsyncMock（不 patch 模块全局）；断言一律重读 DB。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async

from delivery.models import (
    BlueprintThread,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ThreadKind,
    ThreadStatus,
)
from delivery.services import ArtifactService
from services.process_runtime.blueprint_ambiguity_score import (
    DEFAULT_ASSUMPTIONS_TIERS,
    DEFAULT_SPEC_GATE_CONFIG,
    aload_spec_gate_config,
)
from services.process_runtime.blueprint_spec_gate import BlueprintSpecGateAdapter
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)

_SERVER_DIR = Path(__file__).resolve().parents[3]
_DIMS = ("goal", "boundary", "constraint", "acceptance")
_SPEC_GATE_REL = "services/process_runtime/blueprint_spec_gate.py"
_AMBIGUITY_REL = "services/process_runtime/blueprint_ambiguity_score.py"


@pytest.fixture(autouse=True)
def _isolate_blueprint_settings():
    from django.core.cache import cache

    from system.models import SettingKeys, SystemSetting
    from system.settings_service import _cache_key

    def _clear() -> None:
        SystemSetting.objects.filter(key__startswith="blueprint.").delete()
        for key in (
            SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG,
            SettingKeys.BLUEPRINT_ASSUMPTIONS_TIERS,
        ):
            cache.delete(_cache_key(key))

    _clear()
    yield
    _clear()


@pytest.fixture(autouse=True)
def _no_card_delivery(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """规格门开线程后会推飞书卡片（116-06 唯一接线点）——单测里桩掉，不触外部。"""
    sent = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "services.process_runtime.blueprint_notify.anotify_blueprint_clarification", sent
    )
    return sent


@sync_to_async
def _save_tiers(value: Any) -> None:
    from system.models import SettingKeys, SystemSetting

    SystemSetting.objects.update_or_create(
        key=SettingKeys.BLUEPRINT_ASSUMPTIONS_TIERS, defaults={"value": json.dumps(value)}
    )


def _scores(score: float, questions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "dimensions": {dim: {"score": score, "reason": f"{dim} 理由"} for dim in _DIMS},
        "questions": questions
        if questions is not None
        else [{"text": "目标用户是谁？", "options": [], "citations": []}],
    }


async def _make_artifact():
    return await ArtifactService().create(
        artifact_type="technical_plan",
        content=make_blueprint(),
        created_by_user_id="tester",
    )


async def _make_session(artifact, *, tier: str = "", round_no: int = 0) -> ConvergenceSession:
    stage_state: dict[str, Any] = {}
    if tier:
        stage_state["decomposition"] = {"assumptions_tier": tier}
    if round_no:
        stage_state["spec_gate"] = {"round": round_no}
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="spec_gate",
        stage_state=stage_state,
        current_artifact_version_id=artifact.current_version_id,
    )


def _adapter(*, scorer: Any) -> BlueprintSpecGateAdapter:
    return BlueprintSpecGateAdapter(scorer=scorer, classifier=AsyncMock(return_value={}))


# ═══════════════════════════════════════════════════════════════════════════
# 1-2. 配置面
# ═══════════════════════════════════════════════════════════════════════════


async def test_no_tier_keeps_the_previous_behaviour_byte_for_byte() -> None:
    config = await aload_spec_gate_config()

    assert config["threshold"] == DEFAULT_SPEC_GATE_CONFIG["threshold"]
    assert config["max_rounds"] == 3, "默认轮数上界必须与改动前的模块级常量逐字相等"
    assert set(config) == {"threshold", "weights", "max_rounds"}


def test_max_rounds_single_source_lives_in_the_config_default() -> None:
    """⭐ B4：``max_rounds`` 的单一事实源是 ``DEFAULT_SPEC_GATE_CONFIG``。"""
    assert "max_rounds" in DEFAULT_SPEC_GATE_CONFIG
    assert DEFAULT_SPEC_GATE_CONFIG["max_rounds"] == 3


def test_balanced_tier_equals_the_current_behaviour() -> None:
    """默认档零回归：``balanced`` 必须与现状逐字相等。"""
    assert (
        DEFAULT_ASSUMPTIONS_TIERS["balanced"]["threshold"]
        == (DEFAULT_SPEC_GATE_CONFIG["threshold"])
    )
    assert (
        DEFAULT_ASSUMPTIONS_TIERS["balanced"]["max_rounds"]
        == (DEFAULT_SPEC_GATE_CONFIG["max_rounds"])
    )


@pytest.mark.parametrize("tier", ["strict", "balanced", "assume_more"])
async def test_each_tier_preset_takes_effect(tier: str) -> None:
    config = await aload_spec_gate_config(tier=tier)

    assert config["threshold"] == DEFAULT_ASSUMPTIONS_TIERS[tier]["threshold"]
    assert config["max_rounds"] == DEFAULT_ASSUMPTIONS_TIERS[tier]["max_rounds"]


async def test_runtime_override_beats_the_builtin_preset() -> None:
    await _save_tiers({"assume_more": {"threshold": 0.77, "max_rounds": 9}})

    config = await aload_spec_gate_config(tier="assume_more")

    assert config["threshold"] == 0.77
    assert config["max_rounds"] == 9


# ═══════════════════════════════════════════════════════════════════════════
# 3 / 3b. ⭐ 三个调用点口径一致（留痕不撒谎）
# ═══════════════════════════════════════════════════════════════════════════


def test_all_three_config_call_sites_pass_a_tier_argument() -> None:
    """⭐ B3：扫描面是**两个**模块（⛔ 不是只扫 spec_gate）。

    第三处在 ``ascore_ambiguity`` 体内 —— 漏掉它 = 开档位之后 sampling 日志报的阈值
    与真正判定用的不是一个值，而运维正是看那条日志回答「这轮为什么问 / 为什么不问」。
    """
    calls: list[tuple[str, ast.Call]] = []
    for rel in (_SPEC_GATE_REL, _AMBIGUITY_REL):
        tree = ast.parse((_SERVER_DIR / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and (getattr(node.func, "id", "") or getattr(node.func, "attr", ""))
                == "aload_spec_gate_config"
            ):
                calls.append((rel, node))

    assert len(calls) >= 3, (
        "调用点少于三个，八成漏了 ascore_ambiguity 里那处",
        [(rel, node.lineno) for rel, node in calls],
    )
    for rel, call in calls:
        assert call.args or call.keywords, ("每处调用都必须带档位实参", rel, call.lineno)


def test_ascore_ambiguity_accepts_tier_and_spec_gate_threads_it_through() -> None:
    import inspect

    from services.process_runtime.blueprint_ambiguity_score import ascore_ambiguity

    assert "tier" in inspect.signature(ascore_ambiguity).parameters
    src = (_SERVER_DIR / _SPEC_GATE_REL).read_text(encoding="utf-8")
    idx = src.index("await self.scorer(")
    assert "tier" in src[idx : idx + 400], "spec_gate 调 scorer 时必须把同一个 tier 传下去"


async def test_ambiguity_report_threshold_equals_the_deciding_threshold() -> None:
    """⭐ 端到端：report 里记的阈值 == 该档真正判定用的阈值（T-116-53）。"""
    artifact = await _make_artifact()
    session = await _make_session(artifact, tier="assume_more")
    # 分数低于 assume_more 阈值（0.45）⇒ 放行并落 ambiguity_report
    scorer = AsyncMock(return_value=_scores(0.30, questions=[]))

    result = await _adapter(scorer=scorer).run(session)

    assert result["event"] == "spec_locked"
    report = result["ambiguity"]
    assert report["threshold"] == DEFAULT_ASSUMPTIONS_TIERS["assume_more"]["threshold"]
    # 同一分数在 balanced 档（0.20）下会超阈值 ⇒ 证明阈值真的换了（判据非恒真）
    assert report["weighted_total"] < report["threshold"]
    assert report["weighted_total"] > DEFAULT_SPEC_GATE_CONFIG["threshold"]


async def test_scorer_receives_the_same_tier_the_gate_decides_with() -> None:
    """⭐ 3b 的可证伪形态：变异「去掉 ``tier=tier``」⇒ scorer 收不到档位，本条转红。"""
    artifact = await _make_artifact()
    session = await _make_session(artifact, tier="assume_more")
    scorer = AsyncMock(return_value=_scores(0.30, questions=[]))

    await _adapter(scorer=scorer).run(session)

    assert scorer.await_args.kwargs.get("tier") == "assume_more"


async def test_sampling_log_threshold_comes_from_the_tiered_config() -> None:
    """⭐ ``ascore_ambiguity`` 体内那次读取必须带档位，否则日志阈值与判定分叉。"""
    config = await aload_spec_gate_config(tier="assume_more")

    assert config["threshold"] != DEFAULT_SPEC_GATE_CONFIG["threshold"], (
        "本用例要求该档阈值与默认不同，否则分叉不可观测"
    )
    src = (_SERVER_DIR / _AMBIGUITY_REL).read_text(encoding="utf-8")
    idx = src.index('"blueprint_ambiguity_score_completed",')
    segment = src[max(0, idx - 600) : idx]
    assert "aload_spec_gate_config(tier=tier)" in segment, (
        "打 completed 日志之前那次配置读取必须带 tier"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 4 / 7b. max_rounds 真的生效 + 常量已删除
# ═══════════════════════════════════════════════════════════════════════════


async def test_tiered_max_rounds_caps_earlier_than_the_old_hardcoded_three() -> None:
    await _save_tiers({"assume_more": {"threshold": 0.45, "max_rounds": 1}})
    artifact = await _make_artifact()
    session = await _make_session(artifact, tier="assume_more", round_no=1)
    scorer = AsyncMock(return_value=_scores(0.99))

    result = await _adapter(scorer=scorer).run(session)

    assert result["event"] == "spec_locked"
    assert result["ambiguity"]["capped"] is True
    assert result["ambiguity"]["max_rounds"] == 1
    scorer.assert_not_awaited()


async def test_default_round_cap_is_unchanged_without_any_configuration() -> None:
    """零回归对照：不配任何东西时第 3 轮才 capped（与改动前的硬编码 3 逐字一致）。"""
    artifact = await _make_artifact()
    session = await _make_session(artifact, round_no=2)
    scorer = AsyncMock(return_value=_scores(0.99))

    result = await _adapter(scorer=scorer).run(session)

    # 第 2 轮 < 3 ⇒ 仍然打分、仍然开线程（未 capped）
    assert result["event"] == "needs_clarification"
    scorer.assert_awaited_once()

    capped_session = await _make_session(await _make_artifact(), round_no=3)
    capped = await _adapter(scorer=AsyncMock(return_value=_scores(0.99))).run(capped_session)
    assert capped["ambiguity"]["capped"] is True


def test_the_old_module_level_constant_is_gone() -> None:
    """⭐ B4：常量必须删干净（含注释引用），两处使用改读 ``config["max_rounds"]``。"""
    src = (_SERVER_DIR / _SPEC_GATE_REL).read_text(encoding="utf-8")

    assert "_MAX_SPEC_GATE_ROUNDS" not in src, (
        "常量必须删干净（含注释引用）",
        src.count("_MAX_SPEC_GATE_ROUNDS"),
    )
    idx = src.index("blueprint_spec_gate_cap_reached")
    segment = src[max(0, idx - 600) : idx + 600]
    assert segment.count("max_rounds") >= 2, "判定处与日志处都必须改读 config['max_rounds']"
    assert "config[" in segment, "轮数上界必须来自 config 而不是字面量"


# ═══════════════════════════════════════════════════════════════════════════
# 5. ⭐ assume_more ≠ skip_clarification（头号靶子）
# ═══════════════════════════════════════════════════════════════════════════


async def test_assume_more_still_scores_and_still_opens_a_blocking_thread() -> None:
    """⭐ T-116-52：档位只管「问不问」——超过该档阈值时**照样开阻塞线程**。"""
    artifact = await _make_artifact()
    session = await _make_session(artifact, tier="assume_more")
    # 0.80 > assume_more 阈值 0.45 ⇒ 必须开线程
    scorer = AsyncMock(return_value=_scores(0.80))

    result = await _adapter(scorer=scorer).run(session)

    # (a) 四维打分仍然执行
    scorer.assert_awaited_once()
    report = result["ambiguity"]
    assert set(report["dimensions"]) == set(_DIMS)
    assert all(report["dimensions"][dim]["score"] == 0.80 for dim in _DIMS)
    # (b) 仍然开了 blocking 线程
    assert result["event"] == "needs_clarification"
    thread = await BlueprintThread.objects.filter(artifact_id=artifact.id).afirst()
    assert thread is not None
    assert thread.kind == ThreadKind.AI_CLARIFICATION
    assert thread.blocking is True
    assert thread.status == ThreadStatus.OPEN


async def test_strict_tier_is_the_reverse_control_for_the_same_requirement() -> None:
    """并列反向对照：同一需求在 ``strict`` 档下同样开线程 ⇒ 档位只改「问多少」。"""
    artifact = await _make_artifact()
    session = await _make_session(artifact, tier="strict")
    scorer = AsyncMock(return_value=_scores(0.80))

    result = await _adapter(scorer=scorer).run(session)

    assert result["event"] == "needs_clarification"
    assert result["ambiguity"]["threshold"] == DEFAULT_ASSUMPTIONS_TIERS["strict"]["threshold"]
    assert await BlueprintThread.objects.filter(artifact_id=artifact.id).acount() == 1


async def test_a_score_between_the_two_tiers_shows_the_knob_actually_turns() -> None:
    """非恒真对照：0.30 在 ``strict``（0.10）下要问、在 ``assume_more``（0.45）下不问。"""
    strict_artifact = await _make_artifact()
    strict_session = await _make_session(strict_artifact, tier="strict")
    strict = await _adapter(scorer=AsyncMock(return_value=_scores(0.30))).run(strict_session)

    loose_artifact = await _make_artifact()
    loose_session = await _make_session(loose_artifact, tier="assume_more")
    loose = await _adapter(scorer=AsyncMock(return_value=_scores(0.30, questions=[]))).run(
        loose_session
    )

    assert strict["event"] == "needs_clarification"
    assert loose["event"] == "spec_locked"


def test_the_tier_never_short_circuits_the_stage() -> None:
    """⛔ 源码级：两个模块里 ``skip_clarification`` 零命中（⛔ 不得把档位实现成跳过 stage）。"""
    for rel in (_SPEC_GATE_REL, _AMBIGUITY_REL):
        src = (_SERVER_DIR / rel).read_text(encoding="utf-8")
        assert "skip_clarification" not in src, rel


# ═══════════════════════════════════════════════════════════════════════════
# 6-7. 畸形回落 + 留痕
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-dict",
        {"assume_more": "not-a-dict"},
        {"assume_more": {"threshold": "nope", "max_rounds": "nope"}},
        {"assume_more": {"max_rounds": 0}},
        {"assume_more": {"max_rounds": -5}},
    ],
)
async def test_malformed_tier_config_falls_back_without_raising(raw: Any) -> None:
    await _save_tiers(raw)

    config = await aload_spec_gate_config(tier="assume_more")

    assert config["max_rounds"] >= 1, "轮数上界下界必须是 1（0/负会让规格门恒不澄清）"
    assert 0.0 <= config["threshold"] <= 1.0


async def test_unknown_tier_name_falls_back_to_base() -> None:
    config = await aload_spec_gate_config(tier="wildly_unknown")

    assert config["threshold"] == DEFAULT_SPEC_GATE_CONFIG["threshold"]
    assert config["max_rounds"] == DEFAULT_SPEC_GATE_CONFIG["max_rounds"]


async def test_ambiguity_report_records_the_tier_and_max_rounds() -> None:
    artifact = await _make_artifact()
    session = await _make_session(artifact, tier="strict")
    scorer = AsyncMock(return_value=_scores(0.05, questions=[]))

    result = await _adapter(scorer=scorer).run(session)

    report = result["ambiguity"]
    assert report["assumptions_tier"] == "strict"
    assert report["max_rounds"] == DEFAULT_ASSUMPTIONS_TIERS["strict"]["max_rounds"]


async def test_report_tier_is_empty_string_when_the_session_has_no_tier() -> None:
    artifact = await _make_artifact()
    session = await _make_session(artifact)
    scorer = AsyncMock(return_value=_scores(0.05, questions=[]))

    result = await _adapter(scorer=scorer).run(session)

    assert result["ambiguity"]["assumptions_tier"] == ""
    assert result["ambiguity"]["max_rounds"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# 9. ⭐ 生产写入方（116-REVIEW MJ-02）——档位从 MCP 入口一路写进 stage_state
#
# 上面那一整片用例证明的是「**如果**有人把 `assumptions_tier` 写进 `decomposition`，
# 档位会生效」。MJ-02 指出：生产里**没有那个「如果」**——全仓零写入点，唯一写它的是
# `_make_session` 这个测试夹具 ⇒ 档位恒为默认、`_aload_tier_overrides` 永不被调用、
# `SettingKeys.BLUEPRINT_ASSUMPTIONS_TIERS` 的读取路径不可达。
#
# 本节补的是那一环：**走真实入口**（MCP delegate）发起，⛔ 不碰 stage_state 一个字，
# 再用真规格门证明判定结果真的换了。
# ═══════════════════════════════════════════════════════════════════════════

_DELEGATE_REL = "mcp_tools/orchestration_delegate.py"
_ENTRYPOINT_REL = "services/process_runtime/entrypoint.py"
_TP_SERVICE_REL = "mcp_tools/technical_plan_service.py"
_MCP_VIEWS_REL = "mcp_tools/views.py"


def _forwards_kwarg(rel: str, callee: str, kwarg: str) -> bool:
    """AST：``rel`` 里对 ``callee`` 的调用是否显式带了 ``kwarg=``（⛔ 不用字符串包含判）。"""
    tree = ast.parse((_SERVER_DIR / rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and (getattr(node.func, "id", "") or getattr(node.func, "attr", "")) == callee
        ):
            if any(kw.arg == kwarg for kw in node.keywords or []):
                return True
    return False


async def _amcp_blueprint_session(tier: str):
    """走**真实 MCP 入口**建一条蓝图会话（⛔ 全程不碰 ``stage_state``）。

    ``build_engine_for_session`` 换成不推进的替身：本用例只验「入口有没有把档位写进会话」，
    不驱真链路（真链路会去调 LLM）。
    """
    import uuid
    from unittest.mock import MagicMock, patch

    from initiatives.models import Project
    from mcp_tools.orchestration_delegate import delegate_process_runtime
    from projects.models import Space
    from system.models import SettingKeys, SystemSetting

    space = await Space.objects.acreate(name=f"space-{uuid.uuid4().hex[:6]}")
    await Project.objects.acreate(space=space, name=f"proj-{uuid.uuid4().hex[:6]}")
    await sync_to_async(SystemSetting.objects.update_or_create)(
        key=SettingKeys.BLUEPRINT_ENTRY_SWITCH,
        defaults={"value": json.dumps({"mcp": "technical_blueprint"})},
    )
    context = type("Ctx", (), {"space": space, "space_id": space.id})()

    engine = MagicMock(name="engine")
    with patch(
        "services.process_runtime.entrypoint.build_engine_for_session",
        new=lambda session, **kw: (engine, AsyncMock(return_value=session)),
    ):
        result = await delegate_process_runtime(
            requirement_text="让登录支持双因子",
            work_item_context=context,
            assumptions_tier=tier,
        )
    return result.session


async def _arun_gate_on(session, score: float) -> dict[str, Any]:
    """给会话挂一份蓝图 artifact 后跑**真规格门**（档位仍只来自会话自己的 stage_state）。

    scorer 的产出**两条对照完全相同**（同一分数、同一条问题）⇒ 判定差异的唯一来源是档位。
    """
    artifact = await _make_artifact()
    session.current_artifact_version_id = artifact.current_version_id
    await session.asave(update_fields=["current_artifact_version_id"])
    return await _adapter(scorer=AsyncMock(return_value=_scores(score))).run(session)


async def test_mcp_entry_persists_the_tier_into_stage_state() -> None:
    """⭐ MJ-02 头号断言：经 MCP 入口传档位 ⇒ 会话 ``decomposition`` 里真的有那个键。

    ⛔ 本用例全程不碰 ``stage_state``——这正是回退前缺失的那一环（零生产写入点）。
    """
    session = await _amcp_blueprint_session("assume_more")

    assert session.process_type == "technical_blueprint"
    assert (session.decomposition or {}).get("assumptions_tier") == "assume_more"


async def test_tier_from_the_entry_actually_flips_the_gate_decision() -> None:
    """⭐ 断言 ``config`` 的取值与**判定结果**（⛔ 不只断言 stage_state 里那个字符串）。

    同一个 0.30 分：走入口设成 ``assume_more``（阈值 0.45）⇒ 放行；**并列对照**不传档位
    （默认 0.20）⇒ 开阻塞线程。两条差异的唯一来源是入口那一个实参。
    """
    tiered = await _arun_gate_on(await _amcp_blueprint_session("assume_more"), 0.30)

    assert tiered["event"] == "spec_locked"
    assert tiered["ambiguity"]["threshold"] == 0.45
    assert tiered["ambiguity"]["assumptions_tier"] == "assume_more"

    # 非恒真对照：同一入口、同一分数、不传档位 ⇒ 判定相反
    default = await _arun_gate_on(await _amcp_blueprint_session(""), 0.30)

    assert default["event"] == "needs_clarification"
    assert default["ambiguity"]["threshold"] == DEFAULT_SPEC_GATE_CONFIG["threshold"]


async def test_runtime_setting_key_is_now_reachable_through_the_entry() -> None:
    """⭐ ``SettingKeys.BLUEPRINT_ASSUMPTIONS_TIERS`` 的读取路径不再不可达。

    运维改这个键 ⇒ 经入口选中该档的会话真的用上新阈值（回退前改它什么都不会发生）。
    """
    await _save_tiers({"assume_more": {"threshold": 0.66, "max_rounds": 4}})

    result = await _arun_gate_on(await _amcp_blueprint_session("assume_more"), 0.60)

    assert result["event"] == "spec_locked", "0.60 < 运维配的 0.66 ⇒ 应放行"
    assert result["ambiguity"]["threshold"] == 0.66
    assert result["ambiguity"]["max_rounds"] == 4


async def test_entry_drops_a_tier_name_outside_the_three() -> None:
    """非法档名一律**不写键**（⛔ 不留一份读出来还要再丢掉的误导性会话状态）。"""
    session = await _amcp_blueprint_session("wildly_unknown")

    assert "assumptions_tier" not in (session.decomposition or {})


async def test_no_tier_still_means_zero_tier_override_calls() -> None:
    """⭐ 现状的锁：不做任何配置 ⇒ 档位为 ``""`` 且 ``_aload_tier_overrides`` **零调用**。"""
    from unittest.mock import patch

    from services.process_runtime.blueprint_spec_gate import BlueprintSpecGateAdapter

    session = await _amcp_blueprint_session("")
    assert BlueprintSpecGateAdapter()._assumptions_tier(session) == ""

    with patch(
        "services.process_runtime.blueprint_ambiguity_score._aload_tier_overrides",
        new=AsyncMock(return_value={}),
    ) as spy:
        await aload_spec_gate_config(tier=BlueprintSpecGateAdapter()._assumptions_tier(session))

    spy.assert_not_awaited()


def test_the_whole_mcp_chain_forwards_the_tier() -> None:
    """AST：档位从 view → service → delegate → 会话工厂**每一跳都显式转发**。

    ⛔ 任何一跳漏掉 ``assumptions_tier=`` 就又回到「配了没人读」——这正是 MJ-02 的形状。
    """
    hops = [
        (_MCP_VIEWS_REL, "build_work_item_technical_plan"),
        (_TP_SERVICE_REL, "delegate_process_runtime"),
        (_DELEGATE_REL, "_amaybe_start_blueprint_session"),
        (_DELEGATE_REL, "start_blueprint_orchestration"),
    ]
    missing = [
        (rel, callee)
        for rel, callee in hops
        if not _forwards_kwarg(rel, callee, "assumptions_tier")
    ]
    assert not missing, ("这几跳没转发 assumptions_tier", missing)


def test_entrypoint_is_the_only_production_writer_of_the_state_key() -> None:
    """⭐ 写入点必须**恰好一处**且在 ``entrypoint.py``（⛔ 不许各入口各写一份）。"""
    import subprocess

    out = subprocess.run(
        ["rg", "-l", r'decomposition\["assumptions_tier"\]', "--glob", "*.py", "."],
        cwd=_SERVER_DIR,
        capture_output=True,
        text=True,
    ).stdout
    writers = sorted(
        line.removeprefix("./") for line in out.splitlines() if not line.startswith("./tests/")
    )
    assert writers == [_ENTRYPOINT_REL], writers


def test_serializer_tier_choices_match_the_single_source_of_truth() -> None:
    """⭐ ``serializers._ASSUMPTIONS_TIER_CHOICES`` 是字面量副本 ⇒ 这条守卫盯着它别漂。"""
    from mcp_tools.serializers import (
        _ASSUMPTIONS_TIER_CHOICES,
        CreateFeishuTechnicalPlanRequestSerializer,
    )
    from services.process_runtime.blueprint_ambiguity_score import ASSUMPTIONS_TIERS

    assert _ASSUMPTIONS_TIER_CHOICES == ASSUMPTIONS_TIERS
    field = CreateFeishuTechnicalPlanRequestSerializer().fields["assumptions_tier"]
    assert set(field.choices) == {"", *ASSUMPTIONS_TIERS}
    assert field.required is False


@pytest.mark.parametrize("tier", ["", "strict", "balanced", "assume_more"])
def test_serializer_accepts_every_legal_tier(tier: str) -> None:
    from mcp_tools.serializers import CreateFeishuTechnicalPlanRequestSerializer

    serializer = CreateFeishuTechnicalPlanRequestSerializer(
        data={"context_id": "0f6b0f2e-0000-4000-8000-000000000001", "assumptions_tier": tier}
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["assumptions_tier"] == tier


def test_serializer_rejects_an_illegal_tier_at_the_boundary() -> None:
    """非法档名在 MCP 边界即 400（⛔ 不让它一路飘到 stage_state 再被静默丢掉）。"""
    from mcp_tools.serializers import CreateFeishuTechnicalPlanRequestSerializer

    serializer = CreateFeishuTechnicalPlanRequestSerializer(
        data={
            "context_id": "0f6b0f2e-0000-4000-8000-000000000001",
            "assumptions_tier": "assume_everything",
        }
    )

    assert not serializer.is_valid()
    assert "assumptions_tier" in serializer.errors


def test_session_creation_leaves_a_tier_trace() -> None:
    """会话级留痕：``blueprint_orchestration_started`` 必须带 ``assumptions_tier``。

    档位也进 ``ambiguity_report``，但那要等第一次打分之后才有 —— 建会话时就该能看出
    这条会话用的是哪一档。
    """
    src = (_SERVER_DIR / _ENTRYPOINT_REL).read_text(encoding="utf-8")
    idx = src.index('"blueprint_orchestration_started"')
    assert "assumptions_tier=" in src[idx : idx + 800]
