"""Phase 141 Wave 0：Capture 持久化 caller 生命周期与无正文契约（RED）。"""

from __future__ import annotations

import json
import uuid

import pytest
import structlog
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import SessionCapture
from initiatives.services import CaptureService

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@sync_to_async
def _make_user():
    suffix = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"capture-observe-{suffix}", password="x")


def _events(captured: list[dict], *names: str) -> list[dict]:
    allowed = set(names)
    return [event for event in captured if event.get("event") in allowed]


async def _persist(actor, **overrides):
    params = {
        "question": "capture-question-sentinel",
        "answer": "capture-answer-sentinel",
        "session_id": f"observe-{uuid.uuid4().hex}",
        "actor": actor,
    }
    params.update(overrides)
    return await CaptureService().persist(**params)


async def test_success_caller_lifecycle():
    actor = await _make_user()

    with structlog.testing.capture_logs() as captured:
        result = await _persist(actor)

    lifecycle = _events(
        captured,
        "session_capture_persist_started",
        "session_capture_persist_completed",
        "session_capture_persist_failed",
    )
    assert [event["event"] for event in lifecycle] == [
        "session_capture_persist_started",
        "session_capture_persist_completed",
    ]
    for event in lifecycle:
        assert event["category"] == "caller"
        assert event["component"] == "knowledge"
        assert event["initiated_by_user_id"] == str(actor.id)
    assert "duration_ms" not in lifecycle[0]
    assert lifecycle[1]["duration_ms"] >= 0
    assert lifecycle[1]["capture_id"] == str(result.capture.id)
    assert lifecycle[1]["link_reason"] == result.capture.link_reason


async def test_failure_caller_lifecycle(monkeypatch):
    actor = await _make_user()
    token = "sk-ant-" + ("a" * 32)
    original = RuntimeError(f"database rejected {token}")

    def fail_create(*_args, **_kwargs):
        raise original

    monkeypatch.setattr(SessionCapture.objects, "create", fail_create)
    with structlog.testing.capture_logs() as captured:
        with pytest.raises(RuntimeError) as raised:
            await _persist(actor, question="failure-question-sentinel")

    assert raised.value is original
    lifecycle = _events(
        captured,
        "session_capture_persist_started",
        "session_capture_persist_completed",
        "session_capture_persist_failed",
    )
    assert [event["event"] for event in lifecycle] == [
        "session_capture_persist_started",
        "session_capture_persist_failed",
    ]
    assert lifecycle[1]["category"] == "caller"
    assert lifecycle[1]["component"] == "knowledge"
    assert lifecycle[1]["initiated_by_user_id"] == str(actor.id)
    assert lifecycle[1]["duration_ms"] >= 0
    serialized = json.dumps(captured, ensure_ascii=False)
    assert token not in serialized
    assert "REDACTED" in serialized
    assert "failure-question-sentinel" not in serialized


async def test_no_eval_sampling_events():
    actor = await _make_user()

    with structlog.testing.capture_logs() as captured:
        await _persist(actor)

    forbidden = [
        event
        for event in captured
        if str(event.get("event", "")).startswith(
            ("session_capture_eval_", "session_capture_ingest_")
        )
    ]
    assert forbidden == []
    assert not [
        event
        for event in captured
        if event.get("category") == "sampling"
        and str(event.get("event", "")).startswith("session_capture_")
    ]


async def test_no_body_or_secrets_in_logs():
    actor = await _make_user()
    token = "sk-ant-" + ("b" * 32)
    question = f"private-question-sentinel {token}"
    answer = f"private-answer-sentinel {token}"

    with structlog.testing.capture_logs() as captured:
        await _persist(actor, question=question, answer=answer)

    serialized = json.dumps(captured, ensure_ascii=False)
    assert "private-question-sentinel" not in serialized
    assert "private-answer-sentinel" not in serialized
    assert token not in serialized
    for event in captured:
        assert "question" not in event
        assert "answer" not in event
        assert "git_url" not in event


async def test_logger_failure_does_not_drop_capture(monkeypatch):
    actor = await _make_user()

    def broken_log(*_args, **_kwargs):
        raise RuntimeError("logger unavailable")

    monkeypatch.setattr("initiatives.services.capture_service.logger.info", broken_log)
    monkeypatch.setattr("initiatives.services.capture_service.logger.warning", broken_log)

    result = await _persist(actor)

    assert await SessionCapture.objects.filter(pk=result.capture.id).aexists()
