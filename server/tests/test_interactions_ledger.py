"""contract..05 锁名测试桩（initial implementation Wave）。

Nyquist Wave：在实现代码落地前先用锁名测试把 Interaction Ledger 契约固定下来。
顶部 `pytest.importorskip("interactions.models")` 让模块未实现时整文件优雅 skip，
保证套件可收集、不报 collection error；checkpoint/03 实现落地后这些断言自动生效（RED→GREEN）。

覆盖需求：
- contract：create_interaction_run 同步创建并必成功（可追踪）
- contract：8 类 event_type 事件级入库
- contract：tool call 记录 + parent_event 父子 trace
- contract：model usage 记录
- best-effort：子事件写入失败降级不抛
- contract：redact_for_ledger 脱敏（friday_pat_ / sk-ant- / nested dict）
"""

from __future__ import annotations

import pytest

pytest.importorskip("interactions.models")

from runners.models import hash_token  # noqa: E402


@pytest.mark.django_db
def test_run_created_synchronously() -> None:
    """contract：create_interaction_run 同步创建 InteractionRun 并落库。"""
    ledger = pytest.importorskip("interactions.ledger")
    from interactions.models import InteractionRun

    run = ledger.create_interaction_run(
        token_fingerprint=hash_token("sample"),
        source="mcp",
    )
    assert isinstance(run, InteractionRun)
    assert InteractionRun.objects.filter(pk=run.pk).exists()
    assert run.run_id is not None


@pytest.mark.django_db
def test_event_types_persisted() -> None:
    """contract：8 类 event_type 全部可事件级入库。"""
    ledger = pytest.importorskip("interactions.ledger")
    from interactions.models import InteractionEvent

    run = ledger.create_interaction_run(
        token_fingerprint=hash_token("evt"),
        source="mcp",
    )

    event_types = [choice[0] for choice in InteractionEvent.EventType.choices]
    assert len(event_types) == 8

    for event_type in event_types:
        ledger.record_event(run, event_type, {"note": "ok"})

    assert run.events.count() == 8
    persisted = set(run.events.values_list("event_type", flat=True))
    assert persisted == set(event_types)


@pytest.mark.django_db
def test_tool_call_record() -> None:
    """contract：tool call 记录 + parent_event 父子 trace 关联。"""
    ledger = pytest.importorskip("interactions.ledger")
    from interactions.models import ToolCallRecord

    run = ledger.create_interaction_run(
        token_fingerprint=hash_token("tool"),
        source="mcp",
    )

    parent = ledger.record_event(run, "tool_call", {"tool": "search"})
    child = ledger.record_event(
        run, "tool_result", {"ok": True}, parent_event=parent
    )
    # 父子 trace：子事件挂到父事件
    assert child.parent_event_id == parent.id

    record = ledger.record_tool_call(
        run,
        tool_name="search",
        input={"q": "hello"},
        output={"hits": 1},
        status="ok",
    )
    assert isinstance(record, ToolCallRecord)
    assert record.run_id == run.pk


@pytest.mark.django_db
def test_model_usage_record() -> None:
    """contract：model usage 记录入库。"""
    ledger = pytest.importorskip("interactions.ledger")
    from interactions.models import ModelUsageRecord

    run = ledger.create_interaction_run(
        token_fingerprint=hash_token("model"),
        source="mcp",
    )

    record = ledger.record_model_usage(
        run,
        provider="anthropic",
        model="claude-3-5-sonnet",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )
    assert isinstance(record, ModelUsageRecord)
    assert record.run_id == run.pk


@pytest.mark.django_db
def test_event_write_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    """子事件写入失败时降级（warning）不抛，返回 None（best-effort）。"""
    ledger = pytest.importorskip("interactions.ledger")
    from interactions.models import InteractionEvent

    run = ledger.create_interaction_run(
        token_fingerprint=hash_token("best"),
        source="mcp",
    )

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("db down")

    monkeypatch.setattr(InteractionEvent.objects, "create", _boom)

    # best-effort：子事件写入失败不应阻塞主请求，吞掉异常返回 None
    result = ledger.record_event(run, "error", {"reason": "x"})
    assert result is None


@pytest.mark.django_db(transaction=True)
async def test_begin_interaction_run_uses_fingerprint() -> None:
    """contract / contract：单 token 入口创建 run，fingerprint 为 hash，raw_request 不含明文。

    模拟一个已通过认证（带 ``request.auth``）的请求 → ``begin_interaction_run``
    → 断言 run.token_fingerprint == token_hash（只存 hash），且明文绝不入 raw_request。
    """
    entry = pytest.importorskip("interactions.entry")
    from rest_framework.parsers import JSONParser
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    from interactions.models import InteractionRun

    # 入口只读 request.auth.token_hash，无需建真 AccessToken；明文仅用于脱敏断言。
    plaintext = "friday_pat_" + "Z" * 32
    fingerprint = hash_token(plaintext)

    class _FakeAuth:
        token_hash = fingerprint

    wsgi = APIRequestFactory().post(
        "/api/mcp/", {"echo": f"token={plaintext}"}, format="json"
    )
    request = Request(wsgi, parsers=[JSONParser()])
    request.auth = _FakeAuth()

    run = await entry.begin_interaction_run(request, source="mcp")

    assert isinstance(run, InteractionRun)
    # fingerprint 取 token_hash，绝不取明文（contract）
    assert run.token_fingerprint == fingerprint
    # body 里的明文经 redact_for_ledger 脱敏后绝不入库
    assert plaintext not in str(run.raw_request)


def test_redact_for_ledger_scrubs_secrets() -> None:
    """contract：redact_for_ledger 对 friday_pat_ / sk-ant- / nested dict 全脱敏。"""
    redaction = pytest.importorskip("interactions.redaction")

    payload = {
        "authorization": "Bearer friday_pat_AAAAAAAAAAAAAAAAAAAAAAAA",
        "nested": {
            "api_key": "sk-ant-leaktest1234567890",
            "text": "my token friday_pat_BBBBBBBBBBBBBBBBBBBBBBBB",
        },
        "items": ["plain", "sk-ant-anotherleak0987654321"],
    }

    cleaned = redaction.redact_for_ledger(payload)
    blob = str(cleaned)

    assert "friday_pat_AAAA" not in blob
    assert "friday_pat_BBBB" not in blob
    assert "sk-ant-leaktest" not in blob
    assert "sk-ant-anotherleak" not in blob
