"""implementation Wave：LangChainAgentRunner AgentSession + ToolCallLog 持久化守护测试。

contract / contract 审计结论：implementation 交付的 langchain_runner.py 未实现持久化；
checkpoint-01 补齐后本测试文件守护回归。

测试覆盖（implementation plan Task 2 Behaviors 1-6）：
- Test 1 test_add_usage_called_after_turn_no_tools：单 turn 无工具，usage 正确写入 metadata
- Test 2 test_multiple_turns_accumulate_usage：多 turn usage 累加
- Test 3 test_tool_call_log_created_per_tool_use：工具调用产生 ToolCallLog 记录
- Test 4 test_tool_call_log_iteration_increments：多工具调用 iteration 递增
- Test 5 test_agent_session_none_silent_skip：agent_session=None 静默跳过不 crash
- Test 6 test_db_exception_does_not_crash_runner：DB 异常走 logger.exception 兜底

Fixture 策略（Q6 决策弥补 work item）：
本文件内 `_patch_model` + `_make_fake` 为本文件私有 helper；checkpoint~08 所有新测试将
统一引用 checkpoint-03 抽到 conftest.py 的 `fake_chat_model_factory` / `mock_aresolve_ok`
/ `mock_aresolve_missing` / `make_minimal_context` 公共 fixture（本文件为 Wave
基建，先完成 Runner 侧持久化守护；conftest 抽取在 Task 3）。
"""

from __future__ import annotations

from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool as lc_tool

from agents.langchain_runner import LangChainAgentRunner, LangChainRunnerConfig
from agents.models import AgentSession, ToolCallLog
from projects.models import Space
from services.provider_config import ProviderType, ResolvedProviderConfig
from tests.helpers.fake_chat_model import FakeChatModel

User = get_user_model()


# ============================================================================
# Helpers（本文件私有；Q6/work item conftest 抽取见 Task 3）
# ============================================================================


def _patch_model(monkeypatch: pytest.MonkeyPatch, fake: BaseChatModel) -> None:
    """注入 FakeChatModel 到 runner._build_model 调用点（与 implementation core 测试一致）。"""
    monkeypatch.setattr(
        "agents.langchain_runner.build_chat_model",
        lambda *a, **kw: fake,
    )


def _make_fake(
    *,
    responses: list[str],
    tool_calls: list[list[dict[str, Any]]] | None = None,
    usage_metadata: dict[str, int] | None = None,
) -> FakeChatModel:
    """构造 FakeChatModel 语法糖（保持与 conftest factory 同签名）。"""
    return FakeChatModel(
        responses=responses,
        tool_calls=tool_calls or [],
        usage_metadata=usage_metadata or {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        },
    )


def _make_config(
    session: AgentSession | None,
    *,
    session_id: str,
    tools: list[Any] | None = None,
    max_turns: int = 3,
) -> LangChainRunnerConfig:
    """最小 LangChainRunnerConfig（agent_session 可 None 测试 contract 静默路径）。"""
    resolved = ResolvedProviderConfig(
        provider_type=ProviderType.ANTHROPIC,
        api_key="sk-fake",
        base_url="https://api.anthropic.com",
        source="system",
    )
    return LangChainRunnerConfig(
        resolved=resolved,
        model="claude-sonnet-4-20250514",
        session_id=session_id,
        tools=tools or [],
        max_turns=max_turns,
        agent_session=session,
    )


# ============================================================================
# Fixtures：AgentSession DB 预置（持久化测试专属，不抽到 conftest）
# ============================================================================


@pytest.fixture
def persistence_project(db):
    """本测试专属 Space（与 conftest.space 隔离，避免 feishu_project_key 冲突）。"""
    return Space.objects.create(
        name="persistence-test-project",
        feishu_project_key="persistence-test-key",
    )


@pytest.fixture
def persistence_user(db):
    """本测试专属 User（与 conftest.user 隔离）。"""
    return User.objects.create_user(
        username="persistence-test-user",
        email="persist@example.com",
        password="persistence-pw",
    )


@pytest.fixture
async def agent_session_fixture(persistence_project, persistence_user):
    """创建运行中的 AgentSession，供 Runner.stream 消费。"""
    session = await AgentSession.objects.acreate(
        session_id="wf-work-item",
        space=persistence_project,
        user=persistence_user,
        status=AgentSession.Status.RUNNING,
    )
    return session


# ============================================================================
# 工具定义（Test 3/4 使用）
# ============================================================================


@lc_tool
async def echo(text: str) -> str:
    """Echo tool（测试 ToolCallLog 写入）。"""
    return f"echoed: {text}"


# ============================================================================
# Test 1-2：usage 累加路径（contract）
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_add_usage_called_after_turn_no_tools(
    monkeypatch: pytest.MonkeyPatch,
    agent_session_fixture: AgentSession,
) -> None:
    """contract Behavior 1：单 turn 无工具，usage 正确写入 AgentSession.metadata。

    FakeChatModel 单 turn 无工具 + usage_metadata={input:50, output:30, total:80}；
    runner.stream 消费后重读 AgentSession.metadata['usage']['input_tokens'] == 50。
    """
    fake = _make_fake(
        responses=["done"],
        usage_metadata={"input_tokens": 50, "output_tokens": 30, "total_tokens": 80},
    )
    _patch_model(monkeypatch, fake)

    runner = LangChainAgentRunner(
        _make_config(agent_session_fixture, session_id=agent_session_fixture.session_id)
    )
    async for _ in runner.stream("hi"):
        pass

    refreshed = await AgentSession.objects.aget(session_id=agent_session_fixture.session_id)
    assert refreshed.metadata.get("usage", {}).get("input_tokens", 0) == 50
    assert refreshed.metadata.get("usage", {}).get("output_tokens", 0) == 30
    assert runner.result is not None
    assert runner.result.status == "completed"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_multiple_turns_accumulate_usage(
    monkeypatch: pytest.MonkeyPatch,
    agent_session_fixture: AgentSession,
) -> None:
    """contract Behavior 1（累加）：两 turn usage={input:50, output:30} 各一次 → 累计 100/60。

    Turn 1 触发 tool_call echo；Turn 2 无 tool_call 结束。每 turn usage 都累加到
    AgentSession.metadata.usage 上。
    """
    fake = _make_fake(
        responses=["call echo", "finished"],
        tool_calls=[[{"name": "echo", "args": {"text": "hi"}, "id": "call_1"}], []],
        usage_metadata={"input_tokens": 50, "output_tokens": 30, "total_tokens": 80},
    )
    _patch_model(monkeypatch, fake)

    runner = LangChainAgentRunner(
        _make_config(
            agent_session_fixture,
            session_id=agent_session_fixture.session_id,
            tools=[echo],
        )
    )
    async for _ in runner.stream("go"):
        pass

    refreshed = await AgentSession.objects.aget(session_id=agent_session_fixture.session_id)
    # 两 turn 各累加一次 → 100/60
    assert refreshed.metadata.get("usage", {}).get("input_tokens", 0) == 100
    assert refreshed.metadata.get("usage", {}).get("output_tokens", 0) == 60


# ============================================================================
# Test 3-4：ToolCallLog 路径（contract）
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_tool_call_log_created_per_tool_use(
    monkeypatch: pytest.MonkeyPatch,
    agent_session_fixture: AgentSession,
) -> None:
    """contract Behavior 2：工具 echo turn 1 触发 + turn 2 结束 → ToolCallLog 1 条。

    字段断言：tool_name=="echo"、result_success is True、result_output 含 "echoed: hi"、
    arguments 保留原始 tool_call args。
    """
    fake = _make_fake(
        responses=["call echo", "finished"],
        tool_calls=[[{"name": "echo", "args": {"text": "hi"}, "id": "call_1"}], []],
    )
    _patch_model(monkeypatch, fake)

    runner = LangChainAgentRunner(
        _make_config(
            agent_session_fixture,
            session_id=agent_session_fixture.session_id,
            tools=[echo],
        )
    )
    async for _ in runner.stream("go"):
        pass

    logs = [
        log
        async for log in ToolCallLog.objects.filter(
            session=agent_session_fixture
        ).aiterator()
    ]
    assert len(logs) == 1
    assert logs[0].tool_name == "echo"
    assert logs[0].tool_call_id == "call_1"
    assert logs[0].result_success is True
    # result_output 是 JSONField；FakeChatModel 的 echo tool 返回 "echoed: hi"，
    # langchain_runner._execute_tool 将其包成 ToolMessage(content="echoed: hi")，
    # _log_tool_call 写 result_output=str(tool_msg.content)
    assert "echoed: hi" in logs[0].result_output
    assert logs[0].arguments == {"text": "hi"}
    assert logs[0].iteration == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_tool_call_log_iteration_increments(
    monkeypatch: pytest.MonkeyPatch,
    agent_session_fixture: AgentSession,
) -> None:
    """contract Behavior 2（iteration 递增）：两工具调用 → iteration 1, 2。

    FakeChatModel 三 turn：turn1 触发 echo → turn2 触发 echo → turn3 结束。
    AgentSession.increment_tool_calls 按 metadata['tool_calls_count'] 自增。
    """
    fake = _make_fake(
        responses=["call 1", "call 2", "done"],
        tool_calls=[
            [{"name": "echo", "args": {"text": "a"}, "id": "call_a"}],
            [{"name": "echo", "args": {"text": "b"}, "id": "call_b"}],
            [],
        ],
    )
    _patch_model(monkeypatch, fake)

    runner = LangChainAgentRunner(
        _make_config(
            agent_session_fixture,
            session_id=agent_session_fixture.session_id,
            tools=[echo],
            max_turns=4,
        )
    )
    async for _ in runner.stream("go"):
        pass

    logs = [
        log
        async for log in ToolCallLog.objects.filter(
            session=agent_session_fixture
        ).order_by("iteration").aiterator()
    ]
    assert len(logs) == 2
    assert logs[0].iteration == 1
    assert logs[1].iteration == 2
    assert logs[0].tool_call_id == "call_a"
    assert logs[1].tool_call_id == "call_b"


# ============================================================================
# Test 5：agent_session=None 静默跳过（contract）
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_agent_session_none_silent_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """contract Behavior 3：agent_session=None 时 _persist_usage / _log_tool_call 静默跳过。

    不应 raise；runner.result.status == "completed"；DB 中无新增 AgentSession / ToolCallLog。
    """
    fake = _make_fake(
        responses=["call echo", "done"],
        tool_calls=[[{"name": "echo", "args": {"text": "hi"}, "id": "c1"}], []],
    )
    _patch_model(monkeypatch, fake)

    # 预先快照 DB 行数
    pre_session_count = await sync_to_async(AgentSession.objects.count)()
    pre_log_count = await sync_to_async(ToolCallLog.objects.count)()

    runner = LangChainAgentRunner(
        _make_config(None, session_id="no-session", tools=[echo])
    )
    async for _ in runner.stream("go"):
        pass

    assert runner.result is not None
    assert runner.result.status == "completed"
    # agent_session=None 路径不新增任何 DB 行
    post_session_count = await sync_to_async(AgentSession.objects.count)()
    post_log_count = await sync_to_async(ToolCallLog.objects.count)()
    assert post_session_count == pre_session_count
    assert post_log_count == pre_log_count


# ============================================================================
# Test 6：DB 异常走 logger.exception 兜底（security mitigation-04 Tampering mitigation）
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_db_exception_does_not_crash_runner(
    monkeypatch: pytest.MonkeyPatch,
    agent_session_fixture: AgentSession,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Behavior 4：_persist_usage 内 aupdate 抛异常时，Runner 仍正常完成且 logger 记录。

    通过 monkeypatch 让 AgentSession.add_usage 抛 RuntimeError（不直接 patch DB，避免
    污染其他测试；add_usage 是 _persist_usage try 块内第一步，同样会走 except 分支）。
    result.status 应保持 "completed"；stdout 应含 event="langchain_runner_usage_update_failed"。

    说明：项目用 structlog 直接写 stdout（JSON 格式），不经 stdlib logging 桥接，
    因此用 capsys 而非 caplog 捕获日志（project instructions 规定）。
    """
    fake = _make_fake(responses=["done"])
    _patch_model(monkeypatch, fake)

    def _boom(self: Any, input_tokens: int, output_tokens: int) -> None:
        raise RuntimeError("simulated DB error")

    monkeypatch.setattr(AgentSession, "add_usage", _boom)

    runner = LangChainAgentRunner(
        _make_config(agent_session_fixture, session_id=agent_session_fixture.session_id)
    )
    async for _ in runner.stream("hi"):
        pass

    # Runner 主循环没因 DB 异常崩溃
    assert runner.result is not None
    assert runner.result.status == "completed"
    # structlog 写 JSON 到 stdout；断言 event name 出现
    captured = capsys.readouterr()
    assert "langchain_runner_usage_update_failed" in captured.out
    assert "simulated DB error" in captured.out
