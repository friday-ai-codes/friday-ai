"""Phase 141 Wave 0：CaptureService 持久化、挂钩与隔离契约；Phase 143 CAS RED。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.utils import timezone

from initiatives.models import ProjectMemory, SessionCapture, SessionCaptureStatus
from initiatives.services import CaptureService, ProjectService
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@sync_to_async
def _make_user(prefix: str):
    suffix = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"{prefix}-{suffix}", password="x")


async def _make_project_with_member(*, owner=None, name: str = "Capture Project"):
    owner = owner or await _make_user("capture-owner")
    suffix = uuid.uuid4().hex[:8]
    space = await Space.objects.acreate(name=f"Capture Space {suffix}")
    project, _ = await ProjectService().create(
        space=space,
        name=f"{name} {suffix}",
        feishu_project_key=f"capture-{suffix}",
        created_by=owner,
    )
    return space, project, owner


async def _make_visible_repo(space: Space, *, name: str, git_url: str) -> Repository:
    repository = await Repository.objects.acreate(name=name, git_url=git_url)
    await space.repositories.aadd(repository)
    return repository


async def _persist(actor, **overrides):
    params = {
        "question": "如何修复 Capture？",
        "answer": "使用唯一写入服务。",
        "session_id": "session-141",
        "actor": actor,
    }
    params.update(overrides)
    return await CaptureService().persist(**params)


async def test_persist_without_project_or_repo():
    actor = await _make_user("unanchored")

    result = await _persist(actor)

    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.project_id is None
    assert capture.repository_id is None
    assert capture.status == SessionCaptureStatus.PENDING_EVAL
    assert capture.link_reason == "unanchored"


async def test_unknown_scalars():
    actor = await _make_user("unknown-scalars")

    result = await _persist(
        actor,
        response_model=None,
        provider="",
        input_tokens=None,
        output_tokens=" ",
    )

    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.response_model == "unknown"
    assert capture.provider == "unknown"
    assert capture.input_tokens == "unknown"
    assert capture.output_tokens == "unknown"


async def test_redaction_and_actor():
    actor = await _make_user("redaction")
    token = "sk-ant-abc123secretvalue1234567890"

    result = await _persist(
        actor,
        question=f"question-secret {token}",
        answer=f"answer-secret {token}",
    )

    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert token not in capture.question
    assert token not in capture.answer
    assert "REDACTED" in capture.question
    assert "REDACTED" in capture.answer
    assert capture.initiated_by_user_id == str(actor.id)


async def test_persist_does_not_write_memory_or_ledger(monkeypatch):
    actor = await _make_user("separation")
    ledger_calls: list[dict] = []

    async def record_ledger_call(*_args, **kwargs):
        ledger_calls.append(kwargs)

    monkeypatch.setattr("interactions.ledger.arecord_tool_call", record_ledger_call)
    before = await ProjectMemory.objects.acount()

    result = await _persist(actor)

    assert await SessionCapture.objects.filter(pk=result.capture.id).aexists()
    assert await ProjectMemory.objects.acount() == before
    assert ledger_calls == []


async def test_idempotent_returns_existing():
    actor = await _make_user("idempotent")

    first = await _persist(actor, answer="first answer")
    second = await _persist(actor, answer="replacement answer")

    assert first.created is True
    assert first.idempotent_hit is False
    assert second.capture.id == first.capture.id
    assert second.created is False
    assert second.idempotent_hit is True
    assert second.link_reason == first.link_reason
    assert await SessionCapture.objects.acount() == 1
    capture = await SessionCapture.objects.aget(pk=first.capture.id)
    assert capture.answer == "first answer"


async def test_missing_session_id_uses_unspecified():
    actor = await _make_user("missing-session")

    first = await _persist(actor, session_id=None)
    second = await _persist(actor, session_id="")

    capture = await SessionCapture.objects.aget(pk=first.capture.id)
    assert capture.session_id == "unspecified"
    assert second.capture.id == first.capture.id
    assert second.idempotent_hit is True


async def test_repo_ambiguous_does_not_bind_fk():
    space, _project, actor = await _make_project_with_member(name="Ambiguous")
    await _make_visible_repo(
        space,
        name="ambiguous-a",
        git_url="https://git.example.com/team/ambiguous.git",
    )
    await _make_visible_repo(
        space,
        name="ambiguous-b",
        git_url="https://git.example.com/team/ambiguous/",
    )

    result = await _persist(
        actor,
        git_url="git@git.example.com:team/ambiguous.git",
    )

    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.repository_id is None
    assert capture.link_reason == "repo_ambiguous"


async def test_project_only_without_repo():
    _space, project, actor = await _make_project_with_member(name="Project Only")

    result = await _persist(actor, project_id=project.id)

    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.repository_id is None
    assert capture.project_id == project.id
    assert capture.link_reason == "project_only"


async def test_project_repo_mismatch_binds_repo_only():
    _project_space, project, actor = await _make_project_with_member(name="Mismatch Target")
    repo_space, _other_project, _same_actor = await _make_project_with_member(
        owner=actor,
        name="Mismatch Repo Scope",
    )
    repository = await _make_visible_repo(
        repo_space,
        name="mismatch-repo",
        git_url="https://git.example.com/team/mismatch.git",
    )

    result = await _persist(
        actor,
        repository_id=repository.id,
        project_id=project.id,
    )

    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.repository_id == repository.id
    assert capture.project_id is None
    assert capture.link_reason == "project_repo_mismatch"


@pytest.mark.parametrize(
    "git_url",
    [
        "https://git.example.com/team/linked.git",
        "git@git.example.com:team/linked.git",
    ],
)
async def test_links_repository_by_https_or_ssh_url(git_url):
    space, _project, actor = await _make_project_with_member(name="URL Link")
    repository = await _make_visible_repo(
        space,
        name="linked-repo",
        git_url="https://git.example.com/team/linked.git",
    )

    result = await _persist(actor, git_url=git_url)

    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.repository_id == repository.id
    assert capture.link_reason == "linked"


async def test_unresolved_repo_still_persists():
    actor = await _make_user("unresolved")

    result = await _persist(actor, git_url="https://git.example.com/missing/repo.git")

    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.repository_id is None
    assert capture.link_reason == "repo_unresolved"


async def test_explicit_repository_id_takes_priority():
    space, _project, actor = await _make_project_with_member(name="Explicit Priority")
    explicit = await _make_visible_repo(
        space,
        name="explicit-repo",
        git_url="https://git.example.com/team/explicit.git",
    )
    url_match = await _make_visible_repo(
        space,
        name="url-repo",
        git_url="https://git.example.com/team/url-match.git",
    )

    result = await _persist(
        actor,
        repository_id=explicit.id,
        git_url=url_match.git_url,
    )

    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.repository_id == explicit.id


async def test_unauthorized_does_not_set_fk():
    private_space, private_project, _owner = await _make_project_with_member(name="Private")
    private_repo = await _make_visible_repo(
        private_space,
        name="private-repo",
        git_url="https://git.example.com/private/repo.git",
    )
    stranger = await _make_user("stranger")

    result = await _persist(
        stranger,
        repository_id=private_repo.id,
        project_id=private_project.id,
    )

    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.repository_id is None
    assert capture.project_id is None
    assert capture.link_reason in {"repo_unauthorized", "project_unauthorized"}
    assert capture.initiated_by_user_id == str(stranger.id)


_NEW_STATUSES = {
    "evaluating",
    "evaluated_low",
    "ingesting",
    "ingested",
    "ingest_failed",
}
_CLOSED_TIERS = {"high", "medium", "low"}
_ADDITIVE_DEFAULTS = {
    "value_tier": "",
    "distilled_essence": "",
    "eval_attempts": 0,
    "ingest_attempts": 0,
    "last_error": "",
    "next_retry_at": None,
    "evaluated_at": None,
    "ingested_at": None,
}


def _status_literals() -> set[str]:
    return {value for value, _label in SessionCaptureStatus.choices}


def test_value_tier_choices_closed_set():
    field = SessionCapture._meta.get_field("value_tier")
    choice_values = {value for value, _label in field.choices}
    assert choice_values <= {""} | _CLOSED_TIERS
    assert _CLOSED_TIERS <= choice_values
    assert field.blank is True
    assert field.default == ""


def test_status_literals_fit_max_length_20():
    field = SessionCapture._meta.get_field("status")
    assert field.max_length == 20
    literals = _status_literals()
    required = {
        SessionCaptureStatus.PENDING_EVAL,
        SessionCaptureStatus.EVAL_FAILED,
        SessionCaptureStatus.INGEST_PENDING,
        SessionCaptureStatus.EVALUATED,
        *_NEW_STATUSES,
    }
    assert required <= literals
    for value in literals:
        assert len(value) <= field.max_length


def test_additive_eval_fields_default_safe():
    for name, expected_default in _ADDITIVE_DEFAULTS.items():
        field = SessionCapture._meta.get_field(name)
        if expected_default is None:
            assert field.null is True
        else:
            assert field.default == expected_default


async def test_existing_pending_eval_row_keeps_question_answer():
    actor = await _make_user("pending-eval-row")
    question = "存量问答必须原样保留"
    answer = "迁移不得回填或改写原文"
    result = await _persist(actor, question=question, answer=answer)

    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.question == question
    assert capture.answer == answer
    assert capture.status == SessionCaptureStatus.PENDING_EVAL
    for name, expected_default in _ADDITIVE_DEFAULTS.items():
        assert getattr(capture, name) == expected_default


async def test_claim_evaluation_from_pending_eval_increments_eval_attempts():
    actor = await _make_user("claim-pending")
    result = await _persist(actor)
    service = CaptureService()

    claimed = await service.claim_evaluation(result.capture.id)

    assert claimed is not None
    assert claimed.status == "evaluating"
    assert claimed.eval_attempts == 1
    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.status == "evaluating"
    assert capture.eval_attempts == 1
    assert capture.ingest_attempts == 0


async def test_claim_evaluation_from_eval_failed_increments_eval_attempts():
    actor = await _make_user("claim-eval-failed")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)
    await service.record_eval_failure(
        result.capture.id,
        error="upstream timeout",
        next_retry_at=timezone.now() + timedelta(seconds=5),
    )

    claimed = await service.claim_evaluation(result.capture.id)

    assert claimed is not None
    assert claimed.status == "evaluating"
    assert claimed.eval_attempts == 2


async def test_claim_evaluation_resume_when_evaluating_does_not_increment():
    actor = await _make_user("resume-eval")
    result = await _persist(actor)
    service = CaptureService()
    first = await service.claim_evaluation(result.capture.id)

    resumed = await service.claim_evaluation(result.capture.id)

    assert first.eval_attempts == 1
    assert resumed is not None
    assert resumed.status == "evaluating"
    assert resumed.eval_attempts == 1


@pytest.mark.parametrize("tier", ["medium", "high"])
async def test_record_evaluation_medium_high_writes_ingest_pending(tier):
    actor = await _make_user(f"record-eval-{tier}")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)

    updated = await service.record_evaluation(
        result.capture.id,
        value_tier=tier,
        distilled_essence=f"{tier} 可独立召回的根因与验证证据",
    )

    assert updated is not None
    assert updated.status == "ingest_pending"
    assert updated.value_tier == tier
    assert updated.distilled_essence.strip()
    assert updated.last_error == ""
    assert updated.next_retry_at is None
    assert updated.evaluated_at is not None


async def test_record_evaluation_low_writes_evaluated_low():
    actor = await _make_user("record-eval-low")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)

    updated = await service.record_evaluation(
        result.capture.id,
        value_tier="low",
        distilled_essence="低价值但仍可回放的精华",
    )

    assert updated is not None
    assert updated.status == "evaluated_low"
    assert updated.value_tier == "low"
    assert updated.evaluated_at is not None


async def test_record_evaluation_invalid_tier_does_not_write_low():
    actor = await _make_user("invalid-tier-cas")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)

    updated = await service.record_evaluation(
        result.capture.id,
        value_tier="critical",
        distilled_essence="非法档位不得降成 low",
    )

    assert updated is None
    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.status == "evaluating"
    assert capture.value_tier == ""
    assert capture.value_tier != "low"


async def test_record_eval_failure_redacts_error_and_sets_retry():
    actor = await _make_user("eval-retry")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)
    secret = "sk-ant-abc123secretvalue1234567890"
    retry_at = timezone.now() + timedelta(seconds=8)

    failed = await service.record_eval_failure(
        result.capture.id,
        error=f"provider 500 token={secret}",
        next_retry_at=retry_at,
    )

    assert failed is not None
    assert failed.status == SessionCaptureStatus.EVAL_FAILED
    assert secret not in failed.last_error
    assert "REDACTED" in failed.last_error
    assert failed.next_retry_at is not None
    assert await SessionCapture.objects.filter(pk=result.capture.id).aexists()


async def test_eval_success_clears_retry_metadata():
    actor = await _make_user("clear-retry")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)
    await service.record_eval_failure(
        result.capture.id,
        error="temporary",
        next_retry_at=timezone.now() + timedelta(seconds=5),
    )
    await service.claim_evaluation(result.capture.id)

    updated = await service.record_evaluation(
        result.capture.id,
        value_tier="low",
        distilled_essence="失败后成功必须清掉 retry",
    )

    assert updated.last_error == ""
    assert updated.next_retry_at is None


async def test_claim_ingestion_from_ingest_pending_increments_ingest_attempts():
    actor = await _make_user("claim-ingest")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)
    await service.record_evaluation(
        result.capture.id,
        value_tier="medium",
        distilled_essence="中价值精华",
    )

    claimed = await service.claim_ingestion(result.capture.id)

    assert claimed is not None
    assert claimed.status == "ingesting"
    assert claimed.ingest_attempts == 1
    assert claimed.eval_attempts == 1


async def test_claim_ingestion_from_ingest_failed_increments_ingest_attempts():
    actor = await _make_user("claim-ingest-failed")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)
    await service.record_evaluation(
        result.capture.id,
        value_tier="high",
        distilled_essence="高价值精华",
    )
    await service.claim_ingestion(result.capture.id)
    await service.record_ingest_failure(
        result.capture.id,
        error="qdrant unavailable",
        next_retry_at=timezone.now() + timedelta(seconds=5),
    )

    claimed = await service.claim_ingestion(result.capture.id)

    assert claimed is not None
    assert claimed.status == "ingesting"
    assert claimed.ingest_attempts == 2
    assert claimed.eval_attempts == 1


async def test_claim_ingestion_resume_when_ingesting_does_not_increment():
    actor = await _make_user("resume-ingest")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)
    await service.record_evaluation(
        result.capture.id,
        value_tier="medium",
        distilled_essence="可恢复入图",
    )
    first = await service.claim_ingestion(result.capture.id)

    resumed = await service.claim_ingestion(result.capture.id)

    assert first.ingest_attempts == 1
    assert resumed is not None
    assert resumed.status == "ingesting"
    assert resumed.ingest_attempts == 1


async def test_record_ingested_from_ingesting():
    actor = await _make_user("record-ingested")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)
    await service.record_evaluation(
        result.capture.id,
        value_tier="high",
        distilled_essence="入图成功精华",
    )
    await service.claim_ingestion(result.capture.id)

    ingested = await service.record_ingested(result.capture.id)

    assert ingested is not None
    assert ingested.status == "ingested"
    assert ingested.ingested_at is not None
    assert ingested.last_error == ""
    assert ingested.next_retry_at is None


async def test_record_ingest_failure_does_not_change_eval_attempts():
    actor = await _make_user("ingest-retry-independent")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)
    await service.record_evaluation(
        result.capture.id,
        value_tier="medium",
        distilled_essence="入图失败不得回评估",
    )
    await service.claim_ingestion(result.capture.id)
    eval_attempts = (await SessionCapture.objects.aget(pk=result.capture.id)).eval_attempts

    failed = await service.record_ingest_failure(
        result.capture.id,
        error="embed timeout",
        next_retry_at=timezone.now() + timedelta(seconds=9),
    )

    assert failed.status == "ingest_failed"
    assert failed.eval_attempts == eval_attempts
    assert failed.ingest_attempts == 1
    assert failed.next_retry_at is not None


async def test_ingest_and_eval_retry_metadata_are_independent():
    actor = await _make_user("independent-retry")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)
    await service.record_eval_failure(
        result.capture.id,
        error="eval boom",
        next_retry_at=timezone.now() + timedelta(seconds=5),
    )
    await service.claim_evaluation(result.capture.id)
    await service.record_evaluation(
        result.capture.id,
        value_tier="high",
        distilled_essence="评估成功后入图失败",
    )
    await service.claim_ingestion(result.capture.id)
    ingest_retry = timezone.now() + timedelta(seconds=11)

    failed = await service.record_ingest_failure(
        result.capture.id,
        error="ingest boom",
        next_retry_at=ingest_retry,
    )

    assert failed.status == "ingest_failed"
    assert failed.eval_attempts == 2
    assert failed.ingest_attempts == 1
    assert failed.next_retry_at is not None
    assert await service.claim_evaluation(result.capture.id) is None


async def test_illegal_cas_from_wrong_status_is_noop():
    actor = await _make_user("illegal-cas")
    result = await _persist(actor)
    service = CaptureService()

    recorded = await service.record_evaluation(
        result.capture.id,
        value_tier="high",
        distilled_essence="未 claim 不得写档",
    )
    ingested = await service.record_ingested(result.capture.id)
    ingest_claimed = await service.claim_ingestion(result.capture.id)

    assert recorded is None
    assert ingested is None
    assert ingest_claimed is None
    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.status == SessionCaptureStatus.PENDING_EVAL
    assert capture.eval_attempts == 0
    assert capture.ingest_attempts == 0


async def test_terminal_states_cannot_cas_backward():
    actor = await _make_user("terminal-cas")
    result = await _persist(actor)
    service = CaptureService()
    await service.claim_evaluation(result.capture.id)
    await service.record_evaluation(
        result.capture.id,
        value_tier="low",
        distilled_essence="终态不可回退",
    )

    assert await service.claim_evaluation(result.capture.id) is None
    assert await service.claim_ingestion(result.capture.id) is None
    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.status == "evaluated_low"


async def test_concurrent_claim_evaluation_cas_only_one_increments():
    actor = await _make_user("concurrent-claim")
    result = await _persist(actor)
    capture_id = result.capture.id

    await asyncio.gather(
        CaptureService().claim_evaluation(capture_id),
        CaptureService().claim_evaluation(capture_id),
    )

    capture = await SessionCapture.objects.aget(pk=capture_id)
    assert capture.status == "evaluating"
    assert capture.eval_attempts == 1


async def test_legacy_evaluated_cannot_be_claimed_or_resumed():
    actor = await _make_user("legacy-evaluated")
    result = await _persist(actor)
    # 仅模拟存量 legacy 行：新 writer 不以 evaluated 为目标。
    await SessionCapture.objects.filter(pk=result.capture.id).aupdate(
        status=SessionCaptureStatus.EVALUATED
    )
    service = CaptureService()

    assert await service.claim_evaluation(result.capture.id) is None
    assert await service.claim_ingestion(result.capture.id) is None
    capture = await SessionCapture.objects.aget(pk=result.capture.id)
    assert capture.status == SessionCaptureStatus.EVALUATED
    assert capture.eval_attempts == 0
    assert capture.ingest_attempts == 0
