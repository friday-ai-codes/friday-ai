"""Phase 141 Wave 0：CaptureService 持久化、挂钩与隔离契约（RED）。"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

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

    assert second.capture.id == first.capture.id
    assert second.created is False
    assert second.idempotent_hit is True
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
