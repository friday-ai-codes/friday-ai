"""容器 token 链路闭合守护测试（Phase 72-03 / RATE-02 容器侧）。

覆盖 server 侧 ``_handle_token_usage`` 桥接：在既有 ``TokenUsage`` 之外补一行
``ModelUsageRecord`` 纳入统一 TPS 源。断言：

- (a) coding 容器 → TokenUsage 1 行 **且** ModelUsageRecord 1 行
  （call_source=workflow_coding_container、user_id 来自服务端权威来源、run=None、tokens 正确）。
- (b) repo_summary / EXPLORE+chat_deep_analysis / 兜底 agent 三类 call_source 映射。
- (c) payload 含显式 ttft_ms/provider → 透传采用；显式（伪造）call_source → 服务端派生覆盖
  （T-72-03-TAMPER：绝不采信 runner 可篡改字段）。
- (d) 缺可选字段 → 服务端派生 + ttft_ms=None（向后兼容降级）。
- (e) arecord_llm_usage 抛错 → 回调仍 200、TokenUsage 仍落（best-effort 不反噬）。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from django.contrib.auth import get_user_model

from agents.call_source import CallSource
from agents.models import AgentSession
from interactions.models import ModelUsageRecord
from subagent.api.callbacks import _handle_token_usage
from subagent.models import SubAgentSession, TokenUsage

pytestmark = pytest.mark.django_db(transaction=True)


def _log() -> Any:
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None
    log.warning = lambda *a, **kw: None
    return log


async def _make_session(
    *,
    task_type: str,
    last_output: dict | None = None,
    with_user: bool = True,
) -> tuple[SubAgentSession, Any]:
    """构造 AgentSession(+user) + SubAgentSession。"""
    user = None
    if with_user:
        user = await get_user_model().objects.acreate(
            username=f"u-{uuid.uuid4().hex[:8]}",
        )
    agent = await AgentSession.objects.acreate(
        session_id=f"agent-{uuid.uuid4().hex[:8]}",
        user=user,
    )
    sub = await SubAgentSession.objects.acreate(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=agent,
        repo_url="https://example.com/r.git",
        task_type=task_type,
        status=SubAgentSession.Status.RUNNING,
        last_output=last_output,
    )
    return sub, user


def _payload(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "input_tokens": 120,
        "output_tokens": 30,
        "cache_read_tokens": 5,
        "cache_write_tokens": 2,
        "model": "claude-sonnet-4-5",
        "total_cost_usd": "0.001234",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    base.update(extra)
    return base


@pytest.mark.asyncio
async def test_coding_token_usage_bridges_to_model_usage_record() -> None:
    """(a) coding 容器：TokenUsage + ModelUsageRecord 各一行，权威派生 + run=None。"""
    sub, user = await _make_session(
        task_type=SubAgentSession.TaskType.CODING,
        last_output={"task_type": "coding"},
    )

    resp = await _handle_token_usage(sub, _payload(), _log())

    assert resp.status_code == 200
    assert await TokenUsage.objects.filter(session=sub).acount() == 1

    records = [r async for r in ModelUsageRecord.objects.all()]
    assert len(records) == 1
    rec = records[0]
    assert rec.call_source == CallSource.WORKFLOW_CODING_CONTAINER.value
    assert rec.run_id is None
    assert rec.source == "container_callback"
    assert rec.user_id == str(user.id)
    assert rec.prompt_tokens == 120
    assert rec.completion_tokens == 30
    assert rec.total_tokens == 150


@pytest.mark.asyncio
async def test_coding_commit_via_last_output_task_type() -> None:
    """coding_commit（task_type=CODING 不变，last_output.task_type=coding_commit）也映射编码容器。"""
    sub, _ = await _make_session(
        task_type=SubAgentSession.TaskType.CODING,
        last_output={"task_type": "coding_commit"},
    )
    resp = await _handle_token_usage(sub, _payload(), _log())
    assert resp.status_code == 200
    rec = await ModelUsageRecord.objects.aget()
    assert rec.call_source == CallSource.WORKFLOW_CODING_CONTAINER.value


@pytest.mark.asyncio
async def test_repo_summary_call_source_mapping() -> None:
    """(b) repo_summary → repo_summary_container。"""
    sub, _ = await _make_session(task_type=SubAgentSession.TaskType.REPO_SUMMARY)
    resp = await _handle_token_usage(sub, _payload(), _log())
    assert resp.status_code == 200
    rec = await ModelUsageRecord.objects.aget()
    assert rec.call_source == CallSource.REPO_SUMMARY_CONTAINER.value


@pytest.mark.asyncio
async def test_deep_analysis_call_source_mapping() -> None:
    """(b) EXPLORE + last_output.source=chat_deep_analysis → deep_analysis_container。"""
    sub, _ = await _make_session(
        task_type=SubAgentSession.TaskType.EXPLORE,
        last_output={"source": "chat_deep_analysis"},
    )
    resp = await _handle_token_usage(sub, _payload(), _log())
    assert resp.status_code == 200
    rec = await ModelUsageRecord.objects.aget()
    assert rec.call_source == CallSource.DEEP_ANALYSIS_CONTAINER.value


@pytest.mark.asyncio
async def test_fallback_call_source_sdk_agent() -> None:
    """(b) 其余（如 ASK，非 deep_analysis）→ 兜底 sdk_agent_task。"""
    sub, _ = await _make_session(task_type=SubAgentSession.TaskType.ASK)
    resp = await _handle_token_usage(sub, _payload(), _log())
    assert resp.status_code == 200
    rec = await ModelUsageRecord.objects.aget()
    assert rec.call_source == CallSource.SDK_AGENT_TASK.value


@pytest.mark.asyncio
async def test_explicit_ttft_provider_adopted_but_call_source_server_authoritative() -> None:
    """(c) ttft_ms/provider 透传；伪造 call_source 被服务端派生覆盖（T-72-03-TAMPER）。"""
    sub, _ = await _make_session(
        task_type=SubAgentSession.TaskType.REPO_SUMMARY,
    )
    resp = await _handle_token_usage(
        sub,
        _payload(
            ttft_ms=850,
            provider="anthropic",
            # 伪造为编码容器：服务端必须忽略并按 session 派生为 repo_summary_container。
            call_source="workflow_coding_container",
        ),
        _log(),
    )
    assert resp.status_code == 200
    rec = await ModelUsageRecord.objects.aget()
    assert rec.ttft_ms == 850
    assert rec.provider == "anthropic"
    # 服务端权威派生覆盖 runner 上报的 call_source
    assert rec.call_source == CallSource.REPO_SUMMARY_CONTAINER.value


@pytest.mark.asyncio
async def test_missing_optional_fields_degrade() -> None:
    """(d) 缺可选字段 → 派生 + ttft_ms/upstream_status_code=None、provider=空。"""
    sub, _ = await _make_session(
        task_type=SubAgentSession.TaskType.CODING,
        last_output={"task_type": "coding"},
    )
    resp = await _handle_token_usage(sub, _payload(), _log())
    assert resp.status_code == 200
    rec = await ModelUsageRecord.objects.aget()
    assert rec.ttft_ms is None
    assert rec.upstream_status_code is None
    assert rec.provider == ""
    assert rec.failure_type == ""


@pytest.mark.asyncio
async def test_no_user_falls_back_to_system() -> None:
    """无触发用户（main_session.user 为空、无 node_execution）→ user_id=system。"""
    sub, _ = await _make_session(
        task_type=SubAgentSession.TaskType.CODING,
        last_output={"task_type": "coding"},
        with_user=False,
    )
    resp = await _handle_token_usage(sub, _payload(), _log())
    assert resp.status_code == 200
    rec = await ModelUsageRecord.objects.aget()
    assert rec.user_id == "system"


@pytest.mark.asyncio
async def test_bridge_failure_does_not_break_callback() -> None:
    """(e) arecord_llm_usage 抛错 → 回调仍 200、TokenUsage 仍落（best-effort 不反噬）。"""
    sub, _ = await _make_session(
        task_type=SubAgentSession.TaskType.CODING,
        last_output={"task_type": "coding"},
    )

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("bridge boom")

    with patch("subagent.api.callbacks.arecord_llm_usage", new=_boom):
        resp = await _handle_token_usage(sub, _payload(), _log())

    assert resp.status_code == 200
    # TokenUsage（成本归因既有消费方）仍落，桥接失败不连带回滚
    assert await TokenUsage.objects.filter(session=sub).acount() == 1
    # 桥接抛错 → 无 ModelUsageRecord 落库
    assert await ModelUsageRecord.objects.acount() == 0
