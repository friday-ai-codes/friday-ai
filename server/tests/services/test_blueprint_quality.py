"""blueprint_quality 指标纯函数测试（Phase 111-04 Task 1，GATE-02）。

覆盖：引用覆盖率精确比值与边界（全引用 1.0 / 剥一条 findings 引用的分子递减 /
三类条目全空回 1.0 / 非 dict 输入防御）、目标仓命中率四象限（全中 / 半中 /
expected 空 / role 全 indirect）。

DB 统计接口节自 **114-05 实装**后改为**三态并列**：无数据 → ``None``、有数据无命中 → ``0``、
有命中 → 精确值。三态并列不是凑数——它是逮住「``human_edit_volume`` 口径写错字段名」这类
偏差的唯一手段：照 111 docstring 用不存在的 ``created_by_user_id`` 会 ``FieldError``（有值
用例直接红），改按别的用户字段过滤则指标恒为 0（有值用例红而零值用例绿）。
"""

from __future__ import annotations

import pytest

from services.process_runtime.blueprint_quality import (
    ai_rejection_rate,
    citation_coverage,
    clarification_rounds,
    human_edit_volume,
    target_repo_hit_rate,
)
from tests.helpers.blueprint_samples import make_blueprint


def _fully_cited_blueprint() -> dict:
    """三类条目全引用样例：工厂样例的 indirect 仓 rationale 无 citations，此处补齐。"""
    blueprint = make_blueprint()
    blueprint["repo_associations"][2]["rationale"]["citations"] = ["cit_knowledge"]
    return blueprint


# ---- citation_coverage ----


def test_citation_coverage_fully_cited_is_one() -> None:
    assert citation_coverage(_fully_cited_blueprint()) == 1.0


def test_citation_coverage_factory_sample_counts_uncited_indirect_rationale() -> None:
    """工厂原样：indirect 仓 rationale 无 citations → 6 条目命中 5。"""
    assert citation_coverage(make_blueprint()) == pytest.approx(5 / 6)


def test_citation_coverage_drops_exactly_when_one_finding_uncited() -> None:
    blueprint = _fully_cited_blueprint()
    blueprint["current_state_analysis"][0]["findings"][0]["citations"] = []
    # 条目总数 6 = findings 2 + repo_associations 3 + affected_features 1
    assert citation_coverage(blueprint) == pytest.approx(5 / 6)


def test_citation_coverage_empty_categories_returns_one() -> None:
    blueprint = make_blueprint(
        current_state_analysis=[],
        repo_associations=[],
        impact_analysis={"business_impact": [], "affected_features": []},
    )
    assert citation_coverage(blueprint) == 1.0


def test_citation_coverage_non_dict_input_never_raises() -> None:
    assert citation_coverage(None) == 1.0  # type: ignore[arg-type]
    assert citation_coverage("坏输入") == 1.0  # type: ignore[arg-type]


# ---- target_repo_hit_rate ----


def test_target_repo_hit_rate_full_hit() -> None:
    # 工厂样例 direct 仓：onion-practice + study-app
    assert target_repo_hit_rate(make_blueprint(), ["onion-practice", "study-app"]) == 1.0


def test_target_repo_hit_rate_half_hit() -> None:
    assert target_repo_hit_rate(make_blueprint(), ["onion-practice", "不存在的仓"]) == 0.5


def test_target_repo_hit_rate_empty_expected_returns_one() -> None:
    assert target_repo_hit_rate(make_blueprint(), []) == 1.0


def test_target_repo_hit_rate_all_indirect_is_zero() -> None:
    blueprint = make_blueprint()
    for assoc in blueprint["repo_associations"]:
        assoc["role"] = "indirect"
    assert target_repo_hit_rate(blueprint, ["onion-practice"]) == 0.0


def test_target_repo_hit_rate_non_dict_blueprint_never_raises() -> None:
    assert target_repo_hit_rate(None, ["onion-practice"]) == 0.0  # type: ignore[arg-type]


# ---- DB 统计接口（114-05 实装；无数据 / 零值 / 有值三态并列） ----


def _make_artifact():
    from asgiref.sync import async_to_sync

    from delivery.services import ArtifactService

    return async_to_sync(ArtifactService().create)(
        "technical_plan", make_blueprint(), created_by_user_id="tester"
    )


@pytest.mark.django_db
def test_db_stats_return_none_when_no_data() -> None:
    """⭐ 无数据一律 ``None`` 而不是 0——0 会被 ``evaluate_blueprint_golden`` 当成
    「零打回 / 零人工修改」，指标看着漂亮而实际什么都没测。"""
    unknown = "11111111-1111-1111-1111-111111111111"
    assert ai_rejection_rate(unknown) is None
    assert human_edit_volume(unknown) is None
    assert clarification_rounds(unknown) is None


@pytest.mark.django_db
def test_db_stats_never_raise_on_malformed_artifact_id() -> None:
    """非 uuid 入参 → 三项返回 ``None`` 不抛（离线评估不该因统计异常崩）。"""
    assert ai_rejection_rate("不是 uuid") is None
    assert human_edit_volume("不是 uuid") is None
    assert clarification_rounds("不是 uuid") is None


@pytest.mark.django_db
def test_human_edit_volume_counts_human_edit_versions() -> None:
    """⭐ 锁死 A2 偏差：口径必须走 ``produced_by_ref__startswith="human_edit:"``。

    ``ArtifactVersion`` **没有** ``created_by_user_id``——照 111 docstring 写会
    ``FieldError``（这条直接红）；若改按别的用户字段过滤则恒为 0，与下一条「零人工 → 0」
    并列时就露馅（两条不可能同时通过）。
    """
    from delivery.models import ArtifactVersion

    artifact = _make_artifact()
    base = ArtifactVersion.objects.filter(artifact=artifact).order_by("-version_no").first()
    for idx in range(2):
        ArtifactVersion.objects.create(
            artifact=artifact,
            version_no=base.version_no + idx + 1,
            content=base.content,
            content_hash=f"h{idx}",
            produced_by_ref="human_edit:u1",
            supersedes=base,
        )

    assert human_edit_volume(str(artifact.id)) == 2


@pytest.mark.django_db
def test_human_edit_volume_is_zero_when_versions_exist_but_none_are_human() -> None:
    """有版本但零人工编辑 → ``0``（真实的「零人工修改」），与「无版本 → None」区分。"""
    artifact = _make_artifact()
    assert human_edit_volume(str(artifact.id)) == 0


@pytest.mark.django_db
def test_clarification_rounds_counts_only_human_messages() -> None:
    from asgiref.sync import async_to_sync

    from delivery.models import ThreadKind
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    artifact = _make_artifact()
    service = BlueprintLifecycleService()
    for _ in range(2):
        thread = async_to_sync(service.open_thread)(
            artifact,
            kind=ThreadKind.AI_CLARIFICATION,
            blocking=True,
            question="鉴权走哪套？",
            initiated_by_user_id="reviewer-agent",
        )
        # AI 首问（open_thread 已写）+ AI 复检留痕不计轮次，只数 human 作答
        async_to_sync(service.append_note)(thread, body="第 2 轮仍存在")
        async_to_sync(service.record_answer)(thread, body="走 JWT")

    assert clarification_rounds(str(artifact.id)) == 2


@pytest.mark.django_db
def test_clarification_rounds_is_zero_when_threads_exist_but_unanswered() -> None:
    from asgiref.sync import async_to_sync

    from delivery.models import ThreadKind
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    artifact = _make_artifact()
    async_to_sync(BlueprintLifecycleService().open_thread)(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="鉴权走哪套？",
        initiated_by_user_id="reviewer-agent",
    )

    assert clarification_rounds(str(artifact.id)) == 0


@pytest.mark.django_db
def test_ai_rejection_rate_is_retried_rounds_over_total_rounds() -> None:
    from delivery.models import (
        ConvergenceSession,
        ConvergenceSessionEntrypoint,
        ConvergenceSessionEvent,
    )
    from delivery.services.event_taxonomy import EVENT_BLUEPRINT_REVIEW_COMPLETED

    artifact = _make_artifact()
    session = ConvergenceSession.objects.create(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="ai_review",
        current_artifact_version_id=artifact.current_version_id,
    )
    for review_status in ("retry", "passed", "passed"):
        ConvergenceSessionEvent.objects.create(
            session=session,
            event=EVENT_BLUEPRINT_REVIEW_COMPLETED,
            payload={"review_status": review_status, "round": 1},
        )

    assert ai_rejection_rate(str(artifact.id)) == pytest.approx(1 / 3)


@pytest.mark.django_db
def test_ai_rejection_rate_is_none_without_review_events() -> None:
    """无审查事件 → ``None``（无数据 ≠ 零打回）。"""
    artifact = _make_artifact()
    assert ai_rejection_rate(str(artifact.id)) is None
