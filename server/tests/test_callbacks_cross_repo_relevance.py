"""_handle_completed 自动回算 cross_repo_relevance 测试。

测试范围：

1. **Serializer 字段可选**
   - CompletedPayloadSerializer 接受不传 cross_repo_relevance
   - 显式传 list 时透传

2. **分支判定 / helper 调用**
   - EXPLORE + source=chat_deep_analysis → helper 被调
   - EXPLORE + source != chat_deep_analysis → helper 不被调
   - REPO_SUMMARY → helper 不被调

3. **Helper 行为**
   - 写 AgentSession.metadata['cross_repo_relevance'] + trace_id
   - 写一行 RepositoryRoutingTrace(triggered_by=DEEP_ANALYSIS_COMPLETION,
     agent_session_id=main_session.id)
   - TaskResult.text_output 末尾追加 `[cross_repo_relevance:<trace_id>]\n<JSON>` 段

4. **容错**
   - helper 异常 → swallow 仅 warning，回调返 200
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.models import AgentSession
from agents.tools.schemas.repository_relevance import RepositoryRelevanceCandidate
from chat.models import Conversation, RepositoryRoutingTrace
from projects.models import Space
from repositories.models import Repository
from subagent.api.serializers import CompletedPayloadSerializer
from subagent.models import SubAgentSession, TaskResult


pytestmark = pytest.mark.django_db(transaction=True)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_repo_conv(db):
    project = Space.objects.create(
        name=f"da-{uuid.uuid4().hex[:6]}",
        feishu_project_key=f"k-{uuid.uuid4().hex[:6]}",
    )
    repo = Repository.objects.create(
        name="r0",
        git_url="https://github.com/test/r0.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    project.repositories.add(repo)
    conversation = Conversation.objects.create(space=project, title="da-conv")
    return project, repo, conversation


@pytest.fixture
def main_session(db, user):
    return AgentSession.objects.create(
        user=user,
        session_id=f"main-{uuid.uuid4().hex[:8]}",
        metadata={},
    )


@pytest.fixture
def deep_analysis_subagent(db, project_repo_conv, main_session):
    project, repo, conversation = project_repo_conv
    # contract-E1：conversation_id 须来自服务端权威来源 main_session.metadata
    # （dispatch 时写入），helper 不再信任 last_output 的 conversation_id。
    main_session.metadata = {
        "source": "chat_deep_analysis",
        "conversation_id": str(conversation.id),
    }
    main_session.save(update_fields=["metadata"])
    return SubAgentSession.objects.create(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=main_session,
        repo_url="https://github.com/test/r0.git",
        task_type=SubAgentSession.TaskType.EXPLORE,
        status=SubAgentSession.Status.RUNNING,
        last_output={
            "task_type": "explore",
            "source": "chat_deep_analysis",
            "space_id": str(project.id),
            "conversation_id": str(conversation.id),
            "repository_id": str(repo.id),
            "task_description": "梳理跨仓 API 调用链",
        },
    )


def _make_candidate(repository_id: str, score: float = 0.9) -> RepositoryRelevanceCandidate:
    return RepositoryRelevanceCandidate(
        repository_id=repository_id,
        repository_name="r0",
        score=score,
        level="high" if score >= 0.7 else "medium" if score >= 0.4 else "low",
        evidence="mocked",
        selected_by_ai=score >= 0.5,
        selected_by_user_final=score >= 0.5,
    )


# ---------------------------------------------------------------------------
# 1. Serializer 字段可选
# ---------------------------------------------------------------------------


def test_completed_serializer_accepts_missing_cross_repo_relevance():
    ser = CompletedPayloadSerializer(data={"result_type": "text", "output": {"text": "x"}})
    assert ser.is_valid(), ser.errors
    assert ser.validated_data["cross_repo_relevance"] == []


def test_completed_serializer_accepts_explicit_cross_repo_relevance():
    payload = {
        "result_type": "text",
        "output": {"text": "x"},
        "cross_repo_relevance": [{"repository_id": "r1", "score": 0.9}],
    }
    ser = CompletedPayloadSerializer(data=payload)
    assert ser.is_valid(), ser.errors
    assert len(ser.validated_data["cross_repo_relevance"]) == 1


# ---------------------------------------------------------------------------
# 2 & 3. 分支判定 + helper 行为
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_deep_analysis_triggers_helper(
    deep_analysis_subagent, project_repo_conv, main_session
):
    project, repo, conversation = project_repo_conv
    fake_trace_id = str(uuid.uuid4())
    fake_candidate = _make_candidate(str(repo.id))

    payload = {"result_type": "text", "output": {"text": "analysis result"}}
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None

    async def _fake_core(**kwargs: Any):
        # 在 helper 内部真的写 trace 行（模拟 work item core 行为）
        trace = await RepositoryRoutingTrace.objects.acreate(
            agent_session_id=kwargs["agent_session_id"],
            conversation_id=kwargs["conversation_id"],
            query=kwargs["query"],
            candidates=[fake_candidate.model_dump()],
            threshold=0.5,
            triggered_by=kwargs["triggered_by"],
        )
        return [fake_candidate], str(trace.id)

    from subagent.api.callbacks import _handle_completed

    with (
        patch(
            "agents.tools.repository_relevance._analyze_relevance_core",
            new=_fake_core,
        ),
        patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
    ):
        resp = await _handle_completed(deep_analysis_subagent, payload, log)

    assert resp.status_code == 200

    # AgentSession.metadata 写入
    await main_session.arefresh_from_db()
    assert main_session.metadata.get("cross_repo_relevance") is not None
    assert len(main_session.metadata["cross_repo_relevance"]) == 1
    assert main_session.metadata["cross_repo_relevance_trace_id"] is not None

    # RoutingTrace 写入
    traces = [
        t async for t in RepositoryRoutingTrace.objects.filter(
            conversation_id=conversation.id,
            triggered_by=RepositoryRoutingTrace.TriggeredBy.DEEP_ANALYSIS_COMPLETION,
        )
    ]
    assert len(traces) == 1
    assert traces[0].agent_session_id == main_session.id

    # TaskResult.text_output 含 [cross_repo_relevance:<trace_id>] 段
    task_result = await TaskResult.objects.filter(session=deep_analysis_subagent).afirst()
    assert task_result is not None
    assert "[cross_repo_relevance:" in task_result.text_output
    # 段尾 JSON 可被解析
    marker = "[cross_repo_relevance:"
    idx = task_result.text_output.index(marker)
    end_bracket = task_result.text_output.index("]", idx)
    embedded_trace_id = task_result.text_output[idx + len(marker) : end_bracket]
    json_part = task_result.text_output[end_bracket + 1 :].strip()
    parsed = json.loads(json_part)
    assert isinstance(parsed, list)
    assert parsed[0]["repository_id"] == str(repo.id)
    # 段内嵌入的 trace_id 与 metadata trace_id 一致
    assert embedded_trace_id == main_session.metadata["cross_repo_relevance_trace_id"]


@pytest.mark.asyncio
async def test_explore_non_chat_source_does_not_trigger(
    project_repo_conv, main_session
):
    project, repo, conversation = project_repo_conv
    sub = await SubAgentSession.objects.acreate(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=main_session,
        repo_url="https://github.com/test/r0.git",
        task_type=SubAgentSession.TaskType.EXPLORE,
        status=SubAgentSession.Status.RUNNING,
        last_output={"source": "subagent_self_dispatch"},
    )
    payload = {"result_type": "text", "output": {"text": "x"}}
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None

    helper_spy = AsyncMock()
    from subagent.api import callbacks as cbs
    from subagent.api.callbacks import _handle_completed

    with (
        patch.object(cbs, "_update_agent_session_cross_repo_relevance", new=helper_spy),
        patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
    ):
        resp = await _handle_completed(sub, payload, log)

    assert resp.status_code == 200
    helper_spy.assert_not_called()


@pytest.mark.asyncio
async def test_repo_summary_does_not_trigger(project_repo_conv, main_session):
    project, repo, conversation = project_repo_conv
    sub = await SubAgentSession.objects.acreate(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=main_session,
        repo_url="https://github.com/test/r0.git",
        task_type=SubAgentSession.TaskType.REPO_SUMMARY,
        status=SubAgentSession.Status.RUNNING,
        last_output={"repository_id": str(repo.id)},
    )
    payload = {"result_type": "text", "output": {"text": "x"}}
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None

    helper_spy = AsyncMock()
    from subagent.api import callbacks as cbs
    from subagent.api.callbacks import _handle_completed

    with (
        patch.object(cbs, "_update_agent_session_cross_repo_relevance", new=helper_spy),
        patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
        patch("subagent.api.callbacks._update_repository_on_summary_complete", new_callable=AsyncMock),
    ):
        resp = await _handle_completed(sub, payload, log)

    assert resp.status_code == 200
    helper_spy.assert_not_called()


# ---------------------------------------------------------------------------
# 3b. WS 完成路径（RunnerConsumer._handle_completed）—— 284 UAT review round 集成断点回归
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_completed_path_triggers_cross_repo_relevance(
    deep_analysis_subagent, project_repo_conv, main_session
):
    """deep_analysis 完成实际走 WS → RunnerConsumer._handle_completed（非 HTTP
    _handle_completed）。该路径必须同样回算 cross_repo_relevance，否则
    deep_analysis_completion trace 永远不写（review review round 实测断点）。

    本测试用 task_id 触发 consumer 内部按 session_id 重新 afirst() 拉取 session
    （不 select_related main_session）—— 同时回归 helper 的 async-safe main_session 取数。
    """
    from unittest.mock import MagicMock

    project, repo, conversation = project_repo_conv
    fake_candidate = _make_candidate(str(repo.id))

    async def _fake_core(**kwargs: Any):
        trace = await RepositoryRoutingTrace.objects.acreate(
            agent_session_id=kwargs["agent_session_id"],
            conversation_id=kwargs["conversation_id"],
            query=kwargs["query"],
            candidates=[fake_candidate.model_dump()],
            threshold=0.5,
            triggered_by=kwargs["triggered_by"],
        )
        return [fake_candidate], str(trace.id)

    payload = {
        "task_id": deep_analysis_subagent.session_id,
        "result_type": "text",
        "output": {"text": "deep analysis done"},
        "text_output": "deep analysis done",
    }
    log = MagicMock()

    from runners.consumers import RunnerConsumer

    with (
        patch(
            "agents.tools.repository_relevance._analyze_relevance_core",
            new=_fake_core,
        ),
        patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
    ):
        await RunnerConsumer._handle_completed(MagicMock(), payload, log)

    # deep_analysis_completion trace 落库
    traces = [
        t async for t in RepositoryRoutingTrace.objects.filter(
            conversation_id=conversation.id,
            triggered_by=RepositoryRoutingTrace.TriggeredBy.DEEP_ANALYSIS_COMPLETION,
        )
    ]
    assert len(traces) == 1
    assert traces[0].agent_session_id == main_session.id

    # AgentSession.metadata 双键
    await main_session.arefresh_from_db()
    assert main_session.metadata.get("cross_repo_relevance") is not None
    assert main_session.metadata.get("cross_repo_relevance_trace_id") is not None

    # TaskResult.text_output 末尾含 [cross_repo_relevance:<trace_id>] 段
    task_result = await TaskResult.objects.filter(session=deep_analysis_subagent).afirst()
    assert task_result is not None
    assert "[cross_repo_relevance:" in task_result.text_output


@pytest.mark.asyncio
async def test_ws_completed_path_non_chat_explore_does_not_trigger(
    project_repo_conv, main_session
):
    """WS 路径下 EXPLORE 但 source != chat_deep_analysis → 不回算。"""
    from unittest.mock import MagicMock

    project, repo, conversation = project_repo_conv
    sub = await SubAgentSession.objects.acreate(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=main_session,
        repo_url="https://github.com/test/r0.git",
        task_type=SubAgentSession.TaskType.EXPLORE,
        status=SubAgentSession.Status.RUNNING,
        last_output={"source": "subagent_self_dispatch"},
    )
    payload = {
        "task_id": sub.session_id,
        "result_type": "text",
        "output": {"text": "x"},
    }
    log = MagicMock()

    helper_spy = AsyncMock()
    from runners.consumers import RunnerConsumer
    from subagent.api import callbacks as cbs

    with (
        patch.object(cbs, "_update_agent_session_cross_repo_relevance", new=helper_spy),
        patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
    ):
        await RunnerConsumer._handle_completed(MagicMock(), payload, log)

    helper_spy.assert_not_called()


# ---------------------------------------------------------------------------
# 3c. 安全 contract-E1：conversation_id/space_id 取权威来源，不信任 runner 篡改的 last_output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_injected_conversation_id_in_last_output_is_ignored(
    db, project_repo_conv, main_session
):
    """contract-E1：runner 经 last_output 注入的攻击者 conversation_id 必须被忽略。

    helper 应只采信服务端权威来源 main_session.metadata 的 conversation_id，
    并据此派生 space_id（防越权把路由 trace 写入他人会话）。
    """
    project, repo, real_conversation = project_repo_conv

    # 攻击者目标会话（独立 project）—— runner 试图把 trace 写到这里
    attacker_project = await Space.objects.acreate(
        name=f"atk-{uuid.uuid4().hex[:6]}",
        feishu_project_key=f"atk-{uuid.uuid4().hex[:6]}",
    )
    attacker_conv = await Conversation.objects.acreate(space=attacker_project, title="victim-conv")

    # 权威来源：main_session.metadata 指向真实会话
    main_session.metadata = {
        "source": "chat_deep_analysis",
        "conversation_id": str(real_conversation.id),
    }
    await main_session.asave(update_fields=["metadata"])

    sub = await SubAgentSession.objects.acreate(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=main_session,
        repo_url="https://github.com/test/r0.git",
        task_type=SubAgentSession.TaskType.EXPLORE,
        status=SubAgentSession.Status.RUNNING,
        last_output={
            "source": "chat_deep_analysis",
            # 攻击者经 progress 回调注入的伪造值：
            "space_id": str(attacker_project.id),
            "conversation_id": str(attacker_conv.id),
            "task_description": "梳理跨仓 API 调用链",
        },
    )

    captured: dict[str, Any] = {}

    async def _fake_core(**kwargs: Any):
        captured.update(kwargs)
        trace = await RepositoryRoutingTrace.objects.acreate(
            agent_session_id=kwargs["agent_session_id"],
            conversation_id=kwargs["conversation_id"],
            query=kwargs["query"],
            candidates=[],
            threshold=0.5,
            triggered_by=kwargs["triggered_by"],
        )
        return [], str(trace.id)

    payload = {"result_type": "text", "output": {"text": "x"}}
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None

    from subagent.api.callbacks import _handle_completed

    with (
        patch("agents.tools.repository_relevance._analyze_relevance_core", new=_fake_core),
        patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
    ):
        await _handle_completed(sub, payload, log)

    # 采信权威 conversation（真实会话），忽略攻击者注入值
    assert captured.get("conversation_id") == str(real_conversation.id)
    assert captured.get("conversation_id") != str(attacker_conv.id)
    # space_id 由真实会话的 project 派生，非攻击者 project
    assert captured.get("space_id") == str(project.id)
    assert captured.get("space_id") != str(attacker_project.id)
    # 攻击者会话下不应被写入任何 trace
    assert (
        await RepositoryRoutingTrace.objects.filter(conversation_id=attacker_conv.id).acount()
        == 0
    )


# ---------------------------------------------------------------------------
# 4. 容错
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_helper_exception_is_swallowed_and_main_flow_returns_200(
    deep_analysis_subagent, project_repo_conv, main_session
):
    project, repo, conversation = project_repo_conv
    payload = {"result_type": "text", "output": {"text": "x"}}
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None

    async def _boom(**kwargs: Any):
        raise RuntimeError("downstream failure")

    from subagent.api.callbacks import _handle_completed

    with (
        patch(
            "agents.tools.repository_relevance._analyze_relevance_core",
            new=_boom,
        ),
        patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
    ):
        resp = await _handle_completed(deep_analysis_subagent, payload, log)

    assert resp.status_code == 200
    # metadata 未被污染 / trace 未写
    await main_session.arefresh_from_db()
    assert main_session.metadata.get("cross_repo_relevance") is None
    assert (
        await RepositoryRoutingTrace.objects.filter(
            conversation_id=conversation.id,
            triggered_by=RepositoryRoutingTrace.TriggeredBy.DEEP_ANALYSIS_COMPLETION,
        ).acount()
        == 0
    )
