"""Capture 观测：persist caller（Phase 141）与 eval/normalize/ingest sampling（Phase 143 RED）。"""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path

import pytest
import structlog
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import SessionCapture
from initiatives.services import CaptureService

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()
SERVER_DIR = Path(__file__).resolve().parents[2]


@sync_to_async
def _make_user():
    suffix = uuid.uuid4().hex[:8]
    return User.objects.create_user(username=f"capture-observe-{suffix}", password="x")


def _events(captured: list[dict], *names: str) -> list[dict]:
    allowed = set(names)
    return [event for event in captured if event.get("event") in allowed]


_COMMON_EVENT_KEYS = {
    "category",
    "component",
    "event",
    "initiated_by_user_id",
    "log_level",
}
_COMPLETED_EVENT_KEYS = _COMMON_EVENT_KEYS | {
    "capture_id",
    "duration_ms",
    "idempotent_hit",
    "link_reason",
    "project_bound",
    "repository_bound",
    "session_present",
}
_FAILED_EVENT_KEYS = _COMMON_EVENT_KEYS | {"duration_ms", "error"}


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
    assert set(lifecycle[0]) == _COMMON_EVENT_KEYS
    assert set(lifecycle[1]) == _COMPLETED_EVENT_KEYS
    assert lifecycle[1]["duration_ms"] >= 0
    assert lifecycle[1]["capture_id"] == str(result.capture.id)
    assert lifecycle[1]["link_reason"] == result.capture.link_reason
    assert lifecycle[1]["repository_bound"] is False
    assert lifecycle[1]["project_bound"] is False
    assert lifecycle[1]["session_present"] is True
    assert lifecycle[1]["idempotent_hit"] is False


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
    assert set(lifecycle[1]) == _FAILED_EVENT_KEYS
    assert lifecycle[1]["duration_ms"] >= 0
    serialized = json.dumps(captured, ensure_ascii=False)
    assert token not in serialized
    assert "REDACTED" in serialized
    assert "failure-question-sentinel" not in serialized


def _source(relative: str) -> str:
    path = SERVER_DIR / relative
    assert path.exists(), f"Phase 143 观测目标文件尚未建立：{relative}"
    return path.read_text(encoding="utf-8")


def _logger_calls(relative: str) -> list[str]:
    source = _source(relative)
    tree = ast.parse(source)
    calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"debug", "info", "warning", "error", "exception", "_log"}:
            continue
        segment = ast.get_source_segment(source, node)
        if segment and "session_capture_" in segment:
            calls.append(segment)
    return calls


@pytest.mark.parametrize(
    ("relative", "prefix"),
    [
        ("initiatives/services/session_capture_eval.py", "session_capture_eval"),
        ("durable/tasks_impl.py", "session_capture_ingest"),
        ("knowledge/sources/session_capture.py", "session_capture_normalize"),
    ],
)
def test_eval_normalize_ingest_sampling_lifecycle(relative: str, prefix: str) -> None:
    calls = _logger_calls(relative)
    joined = "\n".join(calls)
    source = _source(relative)

    for suffix in ("started", "completed", "failed"):
        assert f'"{prefix}_{suffix}"' in joined
    for call in calls:
        if f"{prefix}_" not in call:
            continue
        if "self._log(" in call:
            assert 'category="sampling"' in source
            assert 'component=_COMPONENT' in source
            assert '_COMPONENT = "knowledge"' in source
        else:
            assert 'category="sampling"' in call
            assert 'component="knowledge"' in call
        assert "capture_id=" in call
    for suffix in ("completed", "failed"):
        matching = [call for call in calls if f'"{prefix}_{suffix}"' in call]
        assert matching and all("duration_ms=" in call for call in matching)


def test_sampling_events_exclude_capture_body_and_tokens() -> None:
    calls = []
    for relative in (
        "initiatives/services/session_capture_eval.py",
        "durable/tasks_impl.py",
        "knowledge/sources/session_capture.py",
    ):
        calls.extend(_logger_calls(relative))

    serialized = "\n".join(calls)
    forbidden_fields = (
        "question=",
        "answer=",
        "distilled_essence=",
        "transcript=",
        "input_tokens=",
        "output_tokens=",
        "token=",
    )
    assert [field for field in forbidden_fields if field in serialized] == []
    assert "initiated_by_user_id=" in serialized or "user_id=" in serialized
    assert "status=" in serialized
    assert "tier=" in serialized or "value_tier=" in serialized


def test_sampling_failures_redact_errors_and_logging_is_best_effort() -> None:
    for relative in (
        "initiatives/services/session_capture_eval.py",
        "durable/tasks_impl.py",
        "knowledge/sources/session_capture.py",
    ):
        source = _source(relative)
        assert "redact_secrets_in_text" in source
        assert "except Exception:" in source
        assert "pass" in source


async def test_persist_does_not_emit_eval_sampling_events():
    """Persist 路径仍不得提前发出 eval/ingest sampling；评估在 durable worker。"""
    actor = await _make_user()

    with structlog.testing.capture_logs() as captured:
        await _persist(actor)

    forbidden = [
        event
        for event in captured
        if str(event.get("event", "")).startswith(
            ("session_capture_eval_", "session_capture_ingest_", "session_capture_normalize_")
        )
    ]
    assert forbidden == []


def test_recovery_logs_rows_at_debug_and_one_sampling_summary() -> None:
    calls = _logger_calls("initiatives/services/session_capture_enqueue.py")
    row_calls = [call for call in calls if "capture_id=" in call]
    summary_calls = [call for call in calls if "recovery" in call and "capture_id=" not in call]

    assert row_calls and all(".debug(" in call for call in row_calls)
    assert len(summary_calls) == 1
    assert ".info(" in summary_calls[0]
    assert 'category="sampling"' in summary_calls[0]
    assert 'component="knowledge"' in summary_calls[0]


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
