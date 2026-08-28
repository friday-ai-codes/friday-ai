"""SessionCapture 只读回放授权契约（Phase 144-05）。"""

from __future__ import annotations

import inspect
import uuid

import pytest

from initiatives.services import CaptureService, ProjectService, aget_readable_capture

pytestmark = pytest.mark.django_db(transaction=True)


async def _persist(
    actor,
    *,
    repository_id: str | None = None,
    project_id: str | None = None,
):
    result = await CaptureService().persist(
        question="如何安全回放 Capture？",
        answer="只读 Capture 表并按创建者与挂钩 scope 授权。",
        actor=actor,
        repository_id=repository_id,
        project_id=project_id,
        session_id=f"capture-access-{uuid.uuid4()}",
    )
    return result.capture


async def test_missing_capture_returns_none(access_user) -> None:
    assert await aget_readable_capture(uuid.uuid4(), access_user) is None


async def test_creator_reads_unanchored_capture(access_user) -> None:
    capture = await _persist(access_user)

    result = await aget_readable_capture(capture.id, access_user)

    assert result is not None
    assert result.id == capture.id


async def test_other_user_cannot_read_capture(access_user, other_user) -> None:
    capture = await _persist(access_user)

    assert await aget_readable_capture(capture.id, other_user) is None


async def test_superuser_reads_capture(access_user, other_user) -> None:
    capture = await _persist(access_user)
    other_user.is_superuser = True

    result = await aget_readable_capture(capture.id, other_user)

    assert result is not None
    assert result.id == capture.id


async def test_creator_losing_repository_scope_cannot_read(
    access_user,
    repository_in_user_space,
    project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    linked_project, _ = await ProjectService().create(
        space=project,
        name="Capture Access Project",
        feishu_project_key=f"capture-access-{uuid.uuid4()}",
        created_by=access_user,
    )
    capture = await _persist(
        access_user,
        repository_id=str(repository_in_user_space.id),
        project_id=str(linked_project.id),
    )
    assert capture.repository_id == repository_in_user_space.id

    async def _deny(*_args: object, **_kwargs: object) -> list[str]:
        return []

    monkeypatch.setattr("initiatives.services.capture_access.resolve_allowed_repository_ids", _deny)

    assert await aget_readable_capture(capture.id, access_user) is None


def test_capture_access_has_no_ledger_or_write_path() -> None:
    from initiatives.services import capture_access

    source = inspect.getsource(capture_access)

    for forbidden in (
        "ToolCallRecord",
        "RetrievalTrace",
        "arecord_tool_call",
        "SessionCapture.objects.create",
        "SessionCapture.objects.update",
        "SessionCapture.objects.delete",
    ):
        assert forbidden not in source
