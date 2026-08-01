"""规格门 adapter 行为测试（Phase 112-02 Task 3，FLOW-01）。

守的是**回路与方向**，不是措辞：

- 低分放行 → 新蓝图版本过 ``validate_blueprint``，ambiguity_report / intent 就位。
- 高分开门 → 一条 open+blocking 的 ``ai_clarification`` 线程，options 带候选与证据。
- pending 短路 → 不重复打分、不重复提问。
- 同一问题已在 decision_log / resolved 线程里 → 被指纹剔除，不新建线程。
- scorer 返 None / add_version 校验失败 → 一律 fail-closed 判需澄清，绝不上抛。
- 轮数上界 → 带 capped 留痕放行（不挂死）。
- intent 兜底 → classifier 不可得时落 brownfield 且仍过 schema。
- decision_log 幂等 → 连跑两轮不重复堆积。

scorer / classifier 经构造参数注入 AsyncMock（不 patch 模块全局）；断言一律重读 DB。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from delivery.models import (
    ArtifactVersion,
    BlueprintThread,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ThreadKind,
    ThreadStatus,
)
from delivery.services import ArtifactContentInvalid, ArtifactService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from services.process_runtime.blueprint_schema import validate_blueprint
from services.process_runtime.blueprint_spec_gate import (
    STAGE_STATE_KEY,
    BlueprintSpecGateAdapter,
)
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)

_DIMS = ("goal", "boundary", "constraint", "acceptance")


@pytest.fixture(autouse=True)
def _isolate_blueprint_settings():
    """清 blueprint.* 设置行与缓存：阈值/权重被别的测试文件写脏会让加权断言假红。"""
    from django.core.cache import cache

    from system.models import SettingKeys, SystemSetting
    from system.settings_service import _cache_key

    def _clear() -> None:
        SystemSetting.objects.filter(key__startswith="blueprint.").delete()
        for key in (SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, SettingKeys.BLUEPRINT_ROUTE_WEIGHTS):
            cache.delete(_cache_key(key))

    _clear()
    yield
    _clear()


def _scores(score: float, questions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "dimensions": {dim: {"score": score, "reason": f"{dim} 理由"} for dim in _DIMS},
        "questions": questions
        if questions is not None
        else [
            {
                "text": "目标用户是谁？",
                "options": ["高三学生", "初三学生"],
                "citations": ["cit_repo_file"],
            }
        ],
    }


async def _make_artifact(content: dict[str, Any] | None = None):
    return await ArtifactService().create(
        artifact_type="technical_plan",
        content=content if content is not None else make_blueprint(),
        created_by_user_id="tester",
    )


async def _make_session(artifact, stage_state: dict | None = None) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="spec_gate",
        stage_state=stage_state or {},
        current_artifact_version_id=artifact.current_version_id,
    )


def _adapter(*, scorer: Any, classifier: Any = None) -> BlueprintSpecGateAdapter:
    return BlueprintSpecGateAdapter(
        scorer=scorer,
        classifier=classifier or AsyncMock(return_value={}),
    )


async def _latest_content(artifact) -> dict[str, Any]:
    fresh = await ArtifactVersion.objects.filter(artifact=artifact).order_by("-version_no").afirst()
    return fresh.content


# ---- 低分放行 ----


async def test_low_score_locks_spec_and_passes_schema() -> None:
    artifact = await _make_artifact()
    session = await _make_session(artifact)
    scorer = AsyncMock(return_value=_scores(0.05, questions=[]))

    result = await _adapter(scorer=scorer).run(session)

    assert result["event"] == "spec_locked"
    assert result["thread_id"] is None
    content = await _latest_content(artifact)
    report = content["requirement_spec"]["ambiguity_report"]
    assert report["weighted_total"] == pytest.approx(0.05)
    assert report["threshold"] == 0.20
    assert report["capped"] is False
    assert report["scorer_unavailable"] is False
    assert all(
        p["intent"] in ("greenfield", "brownfield", "fix")
        for p in content["requirement_spec"]["feature_points"]
    )
    assert validate_blueprint(content) == (True, None)
    assert await BlueprintThread.objects.acount() == 0


# ---- 高分开门 ----


async def test_high_score_opens_blocking_thread_with_options() -> None:
    artifact = await _make_artifact()
    session = await _make_session(artifact)
    scorer = AsyncMock(return_value=_scores(0.9))

    result = await _adapter(scorer=scorer).run(session)

    assert result["event"] == "needs_clarification"
    assert result["thread_id"]
    assert result["stage_state"][STAGE_STATE_KEY]["round"] == 1
    thread = await BlueprintThread.objects.aget(id=result["thread_id"])
    assert thread.kind == ThreadKind.AI_CLARIFICATION
    assert thread.blocking is True
    assert thread.status == ThreadStatus.OPEN
    assert thread.options[0]["options"] == ["高三学生", "初三学生"]
    assert thread.options[0]["citations"] == ["cit_repo_file"]


# ---- pending 短路 ----


async def test_pending_thread_short_circuits_without_scoring() -> None:
    artifact = await _make_artifact()
    session = await _make_session(artifact)
    await BlueprintLifecycleService().open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="还在等回答"
    )
    scorer = AsyncMock(return_value=_scores(0.9))

    result = await _adapter(scorer=scorer).run(session)

    assert result["event"] == "needs_clarification"
    assert scorer.await_count == 0
    assert await BlueprintThread.objects.acount() == 1


# ---- 不重复提问 ----


async def test_already_answered_question_is_not_asked_again() -> None:
    """已解决线程 + decision_log 里有同一问题 → 指纹剔除后无新问题 → 直接锁定。"""
    artifact = await _make_artifact()
    lifecycle = BlueprintLifecycleService()
    thread = await lifecycle.open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="目标用户是谁？"
    )
    await lifecycle.record_answer(thread, body="高三学生")
    await lifecycle.resolve_thread(thread)
    session = await _make_session(artifact)
    scorer = AsyncMock(return_value=_scores(0.9))

    result = await _adapter(scorer=scorer).run(session)

    assert result["event"] == "spec_locked"
    assert await BlueprintThread.objects.acount() == 1
    content = await _latest_content(artifact)
    report = content["requirement_spec"]["ambiguity_report"]
    assert report["resolved_thread_ids"] == [str(thread.id)]
    # 「超阈值 + 问不出新问题」是第二条放行例外，必须与轮数上界同等留痕
    assert report["capped"] is True
    assert report["release_reason"] == "no_new_questions"
    assert [e["question"] for e in content["decision_log"]] == ["目标用户是谁？"]


async def test_prior_answers_feed_back_into_scoring_prompt() -> None:
    """已答结论必须进重判输入（否则同题死循环）。"""
    artifact = await _make_artifact()
    lifecycle = BlueprintLifecycleService()
    thread = await lifecycle.open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="目标用户是谁？"
    )
    await lifecycle.record_answer(thread, body="高三学生")
    session = await _make_session(artifact)
    scorer = AsyncMock(return_value=_scores(0.05, questions=[]))

    await _adapter(scorer=scorer).run(session)

    assert "高三学生" in scorer.await_args.kwargs["prior_context"]


# ---- fail-closed：scorer 不可得 ----


async def test_scorer_unavailable_is_fail_closed() -> None:
    artifact = await _make_artifact()
    session = await _make_session(artifact)
    scorer = AsyncMock(return_value=None)

    result = await _adapter(scorer=scorer).run(session)

    assert result["event"] == "needs_clarification"
    assert result["ambiguity"]["scorer_unavailable"] is True
    assert result["ambiguity"]["weighted_total"] == pytest.approx(1.0)
    thread = await BlueprintThread.objects.aget(id=result["thread_id"])
    assert thread.blocking is True


async def test_scorer_unavailable_never_releases_via_fingerprint_dedup() -> None:
    """CR-02 核心反向断言：兜底问题被答过后，打分仍不可得 → **不得**放行。

    兜底问题是**固定常量**，答过一次它的指纹必然命中 ``prior["fingerprints"]``；若让指纹
    过滤把它吃掉，规格门就会在 ``weighted_total=1.0`` 下走「无新问题 ⇒ 无歧义」放行，
    且 ``capped=False`` 不留痕——那是 fail-closed 的开门洞。
    """
    artifact = await _make_artifact()
    lifecycle = BlueprintLifecycleService()
    thread = await lifecycle.open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question=(
            "自动歧义评估暂不可用。请补充：本次需求的目标（做成什么样算成功）、范围边界"
            "（明确不做什么）、关键约束（性能/兼容/依赖方）、验收标准中仍不明确的部分。"
        ),
    )
    await lifecycle.record_answer(thread, body="已补齐目标与验收")
    await lifecycle.resolve_thread(thread)
    session = await _make_session(artifact)

    result = await _adapter(scorer=AsyncMock(return_value=None)).run(session)

    assert result["event"] == "needs_clarification", "打分持续不可得绝不放行"
    assert result["ambiguity"]["scorer_unavailable"] is True
    assert result["ambiguity"]["weighted_total"] == pytest.approx(1.0)
    assert await BlueprintThread.objects.acount() == 2, "应重新开一条阻塞线程而不是锁定"
    assert await ArtifactVersion.objects.filter(artifact=artifact).acount() == 1, "不得落新版本"


async def test_two_consecutive_unavailable_rounds_stay_blocked() -> None:
    """连续两轮 LLM 不可用（中间用户答过一次）→ 仍停在 needs_clarification，未放行。"""
    artifact = await _make_artifact()
    session = await _make_session(artifact)
    adapter = _adapter(scorer=AsyncMock(return_value=None))

    first = await adapter.run(session)
    assert first["event"] == "needs_clarification"

    lifecycle = BlueprintLifecycleService()
    thread = await BlueprintThread.objects.aget(id=first["thread_id"])
    await lifecycle.record_answer(thread, body="目标是提分，范围只做练习页")
    session.stage_state = first["stage_state"]

    second = await adapter.run(session)

    assert second["event"] == "needs_clarification", "第 2 轮仍不可得 → 绝不放行"
    assert second["ambiguity"]["capped"] is False
    assert second["ambiguity"]["release_reason"] == ""
    assert await ArtifactVersion.objects.filter(artifact=artifact).acount() == 1
    assert await BlueprintThread.objects.acount() == 2


async def test_max_ambiguity_never_releases_even_with_available_scorer() -> None:
    """满歧义（total=1.0）+ 问题全被答过 → 复述同题重新挂起，绝不当作「无歧义」放行。"""
    artifact = await _make_artifact()
    lifecycle = BlueprintLifecycleService()
    thread = await lifecycle.open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="目标用户是谁？"
    )
    await lifecycle.record_answer(thread, body="高三学生")
    await lifecycle.resolve_thread(thread)
    session = await _make_session(artifact)

    result = await _adapter(scorer=AsyncMock(return_value=_scores(1.0))).run(session)

    assert result["event"] == "needs_clarification"
    assert await ArtifactVersion.objects.filter(artifact=artifact).acount() == 1


# ---- 轮数上界 ----


async def test_round_cap_releases_with_capped_flag() -> None:
    artifact = await _make_artifact()
    session = await _make_session(artifact, {STAGE_STATE_KEY: {"round": 3}})
    scorer = AsyncMock(return_value=_scores(0.9))

    result = await _adapter(scorer=scorer).run(session)

    assert result["event"] == "spec_locked"
    assert scorer.await_count == 0
    content = await _latest_content(artifact)
    report = content["requirement_spec"]["ambiguity_report"]
    assert report["capped"] is True
    assert report["release_reason"] == "round_cap", "两条放行例外必须可区分"
    assert validate_blueprint(content) == (True, None)


# ---- intent 兜底 ----


async def _strip_intents(artifact, *, point_ids: set[str] | None = None) -> None:
    """把在库版本的 intent 抹掉（模拟历史/手改数据）。

    ``intent`` 自 112-01 起是 schema 必填枚举，正常入库路径不可能缺——只能旁路造出
    来，才能验规格门的兜底确实兜得住（缺值不得让 add_version 把新版本卡死）。
    """
    version = (
        await ArtifactVersion.objects.filter(artifact=artifact).order_by("-version_no").afirst()
    )
    content = version.content
    for point in content["requirement_spec"]["feature_points"]:
        if point_ids is None or point["id"] in point_ids:
            point.pop("intent", None)
    await ArtifactVersion.objects.filter(id=version.id).aupdate(content=content)


async def test_missing_intent_falls_back_to_brownfield() -> None:
    artifact = await _make_artifact()
    await _strip_intents(artifact)
    session = await _make_session(artifact)

    result = await _adapter(
        scorer=AsyncMock(return_value=_scores(0.05, questions=[])),
        classifier=AsyncMock(return_value=None),
    ).run(session)

    assert result["event"] == "spec_locked"
    locked = await _latest_content(artifact)
    assert [p["intent"] for p in locked["requirement_spec"]["feature_points"]] == [
        "brownfield",
        "brownfield",
    ]
    assert validate_blueprint(locked) == (True, None)


async def test_classifier_result_applied_for_missing_intent() -> None:
    artifact = await _make_artifact()
    await _strip_intents(artifact, point_ids={"fp_01"})
    session = await _make_session(artifact)

    await _adapter(
        scorer=AsyncMock(return_value=_scores(0.05, questions=[])),
        classifier=AsyncMock(return_value={"fp_01": "fix"}),
    ).run(session)

    locked = await _latest_content(artifact)
    intents = {p["id"]: p["intent"] for p in locked["requirement_spec"]["feature_points"]}
    assert intents == {"fp_01": "fix", "fp_02": "brownfield"}


# ---- decision_log 幂等 ----


async def test_decision_log_not_duplicated_across_runs() -> None:
    artifact = await _make_artifact()
    lifecycle = BlueprintLifecycleService()
    thread = await lifecycle.open_thread(
        artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="目标用户是谁？"
    )
    await lifecycle.record_answer(thread, body="高三学生")
    await lifecycle.resolve_thread(thread)
    session = await _make_session(artifact)
    adapter = _adapter(scorer=AsyncMock(return_value=_scores(0.05, questions=[])))

    await adapter.run(session)
    first = await _latest_content(artifact)
    session.current_artifact_version_id = (
        await ArtifactVersion.objects.filter(artifact=artifact).order_by("-version_no").afirst()
    ).id
    await adapter.run(session)
    second = await _latest_content(artifact)

    assert len(first["decision_log"]) == 1
    assert len(second["decision_log"]) == 1


# ---- 内容非法 ----


async def test_invalid_content_is_fail_closed_not_raised() -> None:
    artifact = await _make_artifact()
    session = await _make_session(artifact)
    artifacts = ArtifactService()
    artifacts.add_version = AsyncMock(  # type: ignore[method-assign]
        side_effect=ArtifactContentInvalid("content 校验失败：缺 interaction_flows")
    )
    adapter = BlueprintSpecGateAdapter(
        artifacts=artifacts,
        scorer=AsyncMock(return_value=_scores(0.05, questions=[])),
        classifier=AsyncMock(return_value={}),
    )

    result = await adapter.run(session)

    assert result["event"] == "needs_clarification"
    assert result["thread_id"] is None
    assert await ArtifactVersion.objects.filter(artifact=artifact).acount() == 1


# ---- 无蓝图版本 ----


async def test_session_without_artifact_version_is_fail_closed() -> None:
    session = SimpleNamespace(id="s-1", stage_state={}, current_artifact_version_id=None)
    result = await _adapter(scorer=AsyncMock(return_value=_scores(0.05))).run(session)
    assert result["event"] == "needs_clarification"
    assert result["ambiguity"]["scorer_unavailable"] is True
