"""蓝图全链路集成冒烟（Phase 111-04 Task 3）——三个 wave-1 plan 接缝验收。

golden fixture（gaokao_boost.json）驱动，单一事实源不再手造第二份大样例：

① schema→落库：合法 blueprint 经 ArtifactService 落 Artifact + v1，缺段被拒（111-01）。
② 落库→状态机：BlueprintLifecycleService 走主干 ""→…→pending_review，open+blocking
   线程阻塞 confirm，resolved 后放行且 acting_user 入 BlueprintReviewer（111-02）。
③ 状态机→派生：confirmed 后 derive_technical_plan_document 产出 execution_plan，
   仓集合 == fixture 三 direct 仓，双跑逐字节一致（111-01）。
④ diff 与版本演进：add_version 改一个 finding text → diff 恰命中该 block_id。
⑤ 观测面：transition 带真实 ConvergenceSession → 事件行 blueprint.status.transitioned
   （既有事件类型零改动的共存证明）。

async + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import pytest

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintReviewer,
    BlueprintStatus,
    BlueprintThread,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
    ThreadKind,
    ThreadStatus,
)
from delivery.services import ArtifactContentInvalid, ArtifactService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from services.process_runtime.blueprint_execution import derive_technical_plan_document
from services.process_runtime.blueprint_schema import diff_blueprint_blocks

pytestmark = pytest.mark.django_db(transaction=True)

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "blueprint_golden" / "gaokao_boost.json"
)

# 主干路径 ""→researching→drafting→ai_reviewing→pending_review
_TRUNK_TO_PENDING_REVIEW = (
    BlueprintStatus.RESEARCHING,
    BlueprintStatus.DRAFTING,
    BlueprintStatus.AI_REVIEWING,
    BlueprintStatus.PENDING_REVIEW,
)


def _load_golden_case() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


async def _make_user():
    from django.contrib.auth import get_user_model

    return await get_user_model().objects.acreate(username=f"u-{uuid.uuid4().hex[:6]}")


async def _create_blueprint_artifact(blueprint: dict) -> Artifact:
    return await ArtifactService().create(
        artifact_type="technical_plan",
        content=blueprint,
        created_by_user_id="tester",
    )


# ---- ① schema→落库 ----


async def test_golden_blueprint_persists_and_missing_section_rejected() -> None:
    case = _load_golden_case()
    artifact = await _create_blueprint_artifact(case["blueprint"])
    v1 = await ArtifactVersion.objects.aget(id=artifact.current_version_id)
    assert v1.version_no == 1
    assert v1.content["schema_version"] == "blueprint/v1"
    assert v1.content["meta"]["title"] == "高三提分专项"

    broken = copy.deepcopy(case["blueprint"])
    broken.pop("must_haves")
    with pytest.raises(ArtifactContentInvalid):
        await ArtifactService().create(artifact_type="technical_plan", content=broken)


# ---- ② 落库→状态机 ----


async def test_lifecycle_trunk_confirm_gate_and_reviewer_roster() -> None:
    case = _load_golden_case()
    artifact = await _create_blueprint_artifact(case["blueprint"])
    assert artifact.blueprint_status == ""  # 落库默认未进入状态机

    service = BlueprintLifecycleService()
    user = await _make_user()
    for to_status in _TRUNK_TO_PENDING_REVIEW:
        await service.transition(artifact, to_status, initiated_by_user_id=str(user.id))

    thread = await BlueprintThread.objects.acreate(
        artifact=artifact,
        kind=ThreadKind.REPO_CONFIRMATION,
        blocking=True,
    )
    with pytest.raises(ValueError):
        await service.transition(
            artifact,
            BlueprintStatus.CONFIRMED,
            initiated_by_user_id=str(user.id),
            acting_user=user,
        )

    thread.status = ThreadStatus.RESOLVED
    await thread.asave(update_fields=["status"])
    await service.transition(
        artifact,
        BlueprintStatus.CONFIRMED,
        initiated_by_user_id=str(user.id),
        acting_user=user,
    )

    fresh = await Artifact.objects.aget(id=artifact.id)
    assert fresh.blueprint_status == BlueprintStatus.CONFIRMED
    reviewer = await BlueprintReviewer.objects.aget(artifact=artifact, user=user)
    assert reviewer.first_action == "final_approve"


# ---- ③ 状态机→派生 ----


async def test_confirmed_blueprint_derives_execution_plan_for_direct_repos() -> None:
    case = _load_golden_case()
    blueprint = case["blueprint"]
    artifact = await _create_blueprint_artifact(blueprint)
    service = BlueprintLifecycleService()
    user = await _make_user()
    for to_status in (*_TRUNK_TO_PENDING_REVIEW, BlueprintStatus.CONFIRMED):
        await service.transition(
            artifact, to_status, initiated_by_user_id=str(user.id), acting_user=user
        )
    assert artifact.blueprint_status == BlueprintStatus.CONFIRMED

    doc, err = derive_technical_plan_document(blueprint)
    assert err is None
    repo_names = {task["repository_name"] for task in doc["execution_plan"]}
    assert repo_names == set(case["expected"]["direct_repos"])

    doc_again, _ = derive_technical_plan_document(blueprint)
    assert json.dumps(doc, sort_keys=True, ensure_ascii=False) == json.dumps(
        doc_again, sort_keys=True, ensure_ascii=False
    )


# ---- ④ diff 与版本演进 ----


async def test_add_version_block_diff_hits_exactly_changed_block() -> None:
    case = _load_golden_case()
    artifact = await _create_blueprint_artifact(case["blueprint"])
    v1 = await ArtifactVersion.objects.aget(id=artifact.current_version_id)

    v2_content = copy.deepcopy(case["blueprint"])
    changed_block = v2_content["current_state_analysis"][0]["findings"][0]["text"][0]
    changed_block["text"] = "培优课占位入口已确认改造为高三提分专项入口（修订轮补充实证）。"
    v2 = await ArtifactService().add_version(artifact, v2_content)
    assert v2.version_no == 2
    assert v2.supersedes_id == v1.id

    diff = diff_blueprint_blocks(v1.content, v2.content)
    assert diff["modified"] == [changed_block["block_id"]]
    assert diff["added"] == []
    assert diff["removed"] == []


# ---- ⑤ 观测面：既有事件模型零改动共存 ----


async def test_transition_with_session_emits_blueprint_event_row() -> None:
    case = _load_golden_case()
    artifact = await _create_blueprint_artifact(case["blueprint"])
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
    )
    await BlueprintLifecycleService().transition(
        artifact,
        BlueprintStatus.RESEARCHING,
        initiated_by_user_id="tester",
        session=session,
    )
    event = await ConvergenceSessionEvent.objects.aget(session=session)
    assert event.event == "blueprint.status.transitioned"
    assert event.payload["artifact_id"] == str(artifact.id)
    assert event.payload["from_status"] == ""
    assert event.payload["to_status"] == BlueprintStatus.RESEARCHING
