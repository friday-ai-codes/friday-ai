"""MCP ``get_session_capture`` 只读回放与防枚举 RED 契约（Phase 144 Wave 0）。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from rest_framework.test import APIClient

from initiatives.models import Project, ProjectMember, SessionCapture
from initiatives.services import CaptureService
from interactions.models import RetrievalTrace, ToolCallRecord
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

_URL = "/api/mcp/tools/get_session_capture/"
_RESPONSE_KEYS = {
    "capture_id",
    "question",
    "answer",
    "response_model",
    "provider",
    "input_tokens",
    "output_tokens",
    "session_id",
    "branch_name",
    "repository_id",
    "project_id",
    "link_reason",
    "value_tier",
    "status",
    "created_at",
    "updated_at",
    "evaluated_at",
    "ingested_at",
    "run_id",
}
_FORBIDDEN_KEYS = {
    "last_error",
    "distilled_essence",
    "question_hash",
    "client",
    "initiated_by_user_id",
    "eval_attempts",
    "ingest_attempts",
    "next_retry_at",
}


async def _post(client: APIClient, capture_id: str) -> tuple[int, dict]:
    response = await sync_to_async(client.post)(
        _URL,
        {"capture_id": capture_id},
        format="json",
    )
    return response.status_code, response.json()


async def _persist(access_user, *, repository=None, project=None) -> SessionCapture:
    result = await CaptureService().persist(
        question="为什么回放必须只读？",
        answer="因为 Capture 是不可由读取动作推进的独立账本。",
        actor=access_user,
        repository_id=str(repository.id) if repository else None,
        project_id=str(project.id) if project else None,
        branch_name="feat/capture-replay",
        session_id=f"replay-{uuid.uuid4()}",
        response_model="test-model",
        provider="test-provider",
        input_tokens=13,
        output_tokens=21,
    )
    return result.capture


async def _linked_project(access_user, repository) -> Project:
    space = await sync_to_async(Space.objects.create)(
        name=f"Capture Replay {uuid.uuid4()}",
        feishu_project_key=f"capture-replay-{uuid.uuid4()}",
    )
    await sync_to_async(space.repositories.add)(repository)
    project = await Project.objects.acreate(
        space=space,
        name="Capture Replay Project",
        feishu_project_key=f"capture-replay-project-{uuid.uuid4()}",
        created_by=access_user,
    )
    await ProjectMember.objects.acreate(project=project, user=access_user)
    return project


async def _other_client(other_user) -> APIClient:
    from access_tokens.models import AccessToken, generate_pat
    from runners.models import hash_token

    plaintext = generate_pat()
    await AccessToken.objects.acreate(
        name=f"capture-other-{uuid.uuid4()}",
        token_hash=hash_token(plaintext),
        token_prefix=plaintext[:12],
        token_suffix=plaintext[-4:],
        created_by=other_user,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    return client


async def test_creator_replays_exact_allowlist_from_capture(
    mcp_client,
    access_user,
) -> None:
    client, _ = mcp_client
    capture = await _persist(access_user)

    status_code, body = await _post(client, str(capture.id))

    assert status_code == 200
    assert set(body) == _RESPONSE_KEYS
    assert not (_FORBIDDEN_KEYS & set(body))
    assert body["capture_id"] == str(capture.id)
    assert body["question"] == capture.question
    assert body["answer"] == capture.answer
    assert body["repository_id"] is None
    assert body["project_id"] is None
    assert body["run_id"]


async def test_other_user_and_missing_capture_have_identical_404(
    mcp_client,
    access_user,
    other_user,
) -> None:
    creator_client, _ = mcp_client
    capture = await _persist(access_user)
    other_client = await _other_client(other_user)

    denied = await _post(other_client, str(capture.id))
    missing = await _post(creator_client, str(uuid.uuid4()))

    assert denied == missing
    assert denied[0] == 404
    assert denied[1]["error_code"] == "capture_not_found"


async def test_creator_without_repository_scope_gets_same_neutral_404(
    mcp_client,
    access_user,
    repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_tools.views as views

    client, _ = mcp_client
    project = await _linked_project(access_user, repository)
    capture = await _persist(access_user, repository=repository, project=project)
    monkeypatch.setattr(
        views,
        "resolve_allowed_repository_ids",
        AsyncMock(return_value=[]),
        raising=False,
    )

    denied = await _post(client, str(capture.id))
    missing = await _post(client, str(uuid.uuid4()))

    assert denied == missing
    assert denied[0] == 404


async def test_creator_without_project_scope_gets_same_neutral_404(
    mcp_client,
    access_user,
    repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_tools.views as views

    client, _ = mcp_client
    project = await _linked_project(access_user, repository)
    capture = await _persist(access_user, repository=repository, project=project)
    monkeypatch.setattr(
        views,
        "resolve_allowed_project_ids",
        AsyncMock(return_value=[]),
        raising=False,
    )

    denied = await _post(client, str(capture.id))
    missing = await _post(client, str(uuid.uuid4()))

    assert denied == missing
    assert denied[0] == 404


async def test_replay_does_not_read_interaction_ledger(
    mcp_client,
    access_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = mcp_client
    capture = await _persist(access_user)

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("回放正文不得查询 Interaction Ledger")

    monkeypatch.setattr(ToolCallRecord.objects, "filter", _boom)
    monkeypatch.setattr(RetrievalTrace.objects, "filter", _boom)
    monkeypatch.setattr(RetrievalTrace.objects, "get", _boom)

    status_code, body = await _post(client, str(capture.id))

    assert status_code == 200
    assert body["question"] == capture.question
    assert body["answer"] == capture.answer


async def test_replay_is_read_only_and_never_enqueues(
    mcp_client,
    access_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_tools.views as views

    client, _ = mcp_client
    capture = await _persist(access_user)
    before = (
        capture.status,
        capture.eval_attempts,
        capture.ingest_attempts,
        capture.updated_at,
    )
    enqueue = AsyncMock(side_effect=AssertionError("只读回放不得投递任务"))
    monkeypatch.setattr(
        views,
        "enqueue_session_capture_eval",
        enqueue,
        raising=False,
    )

    status_code, _body = await _post(client, str(capture.id))
    await capture.arefresh_from_db()

    assert status_code == 200
    assert (
        capture.status,
        capture.eval_attempts,
        capture.ingest_attempts,
        capture.updated_at,
    ) == before
    enqueue.assert_not_awaited()
