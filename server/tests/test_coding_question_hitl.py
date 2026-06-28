"""编码遇阻 HITL 服务端测试（Phase 47，HITL-01b/c）。

覆盖（mock IO 边界 = 飞书发卡 + 研究/replan 编排 spy；ORM 走真实 DB transaction=True）：

- routing：wave 编码任务（带 node_execution_id、无 main_session）的 question 卡片经
  ``_resolve_notification_chat_id`` 取 node 级 chat_id；缺 chat_id fail-soft；main_session
  路径零回归。
- e2e：编码遇阻（SubAgentSession RUNNING + pending_question）→ ``aadvance_coding_waves``
  返回 waiting（不阻断下游、不 dead-end）→ 回答后容器 completed → 再 aadvance 推进下游
  （续跑只走 Phase 43/44，无新 resume 通路）。
- no-replan guard：HITL question/answer/resume 链路不触发任何 research/replan 编排（HITL-01c）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from delivery.models import (
    Artifact,
    ArtifactVersion,
    RepoCodingTask,
    RepoCodingTaskStatus,
)
from delivery.services import RepoCodingTaskService
from repositories.models import Repository
from services.process_runtime.wave_progression import aadvance_coding_waves
from subagent.models import SubAgentSession, TaskResult

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_repo(name: str) -> Repository:
    return await Repository.objects.acreate(
        name=f"{name}-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


async def _make_plan_version() -> ArtifactVersion:
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    av = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content={}, content_hash="h"
    )
    artifact.current_version = av
    await artifact.asave(update_fields=["current_version", "updated_at"])
    return av


async def _make_node_execution(chat_id: str = "") -> object:
    """建真实 NodeExecution 链；node.config.chat_id 用于 question 卡片路由。"""
    from projects.models import Space
    from workflows.models import (
        NodeExecution,
        Workflow,
        WorkflowExecution,
        WorkflowNode,
    )

    project = await Space.objects.acreate(name=f"proj-{uuid.uuid4().hex[:6]}")
    workflow = await Workflow.objects.acreate(name="wf-hitl", space=project)
    wf_node = await WorkflowNode.objects.acreate(
        workflow=workflow,
        node_type="ai_coding",
        name="AI 编码",
        config={"chat_id": chat_id} if chat_id else {},
    )
    wf_exec = await WorkflowExecution.objects.acreate(
        workflow=workflow, space=project, trigger_type="manual"
    )
    return await NodeExecution.objects.acreate(
        workflow_execution=wf_exec, node=wf_node, status="running"
    )


async def _make_main_session(chat_id: str = "") -> object:
    """建 main AgentSession（SubAgentSession.main_session 为 NOT NULL，必须有）。

    chat_id 为空时 metadata 不含 chat_id —— 模拟 wave 编码主会话（无 chat 触面），
    使 _resolve_notification_chat_id 的 main_session 分支返回空、fallback 到 node_execution。
    """
    from agents.models import AgentSession

    metadata = {"chat_id": chat_id} if chat_id else {"workflow_execution_id": uuid.uuid4().hex}
    return await AgentSession.objects.acreate(
        session_id=f"main-{uuid.uuid4().hex[:8]}",
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Routing tests — send_question_card_enhanced
# ---------------------------------------------------------------------------


class _FakeIMClient:
    sent: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def send_card(self, receive_id, receive_id_type, card):
        _FakeIMClient.sent.append({"receive_id": receive_id, "type": receive_id_type})
        return "msg-fake-id"


async def test_send_card_routes_via_node_execution(monkeypatch):
    """wave 编码任务（node_execution、无 main_session）经 _resolve_notification_chat_id 取 node chat_id。"""
    from django.conf import settings

    from subagent.question_handler import send_question_card_enhanced

    _FakeIMClient.sent = []
    monkeypatch.setattr("services.feishu_im.FeishuIMClient", _FakeIMClient)
    monkeypatch.setattr(settings, "FEISHU_APP_ID", "app", raising=False)
    monkeypatch.setattr(settings, "FEISHU_APP_SECRET", "secret", raising=False)

    ne = await _make_node_execution(chat_id="oc_node_chat")
    main = await _make_main_session(chat_id="")  # 主会话无 chat_id → fallback 到 node
    session = await SubAgentSession.objects.acreate(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=main,
        node_execution=ne,
        repo_url="https://github.com/test/repo",
        task_type="coding",
        status=SubAgentSession.Status.RUNNING,
    )

    message_id = await send_question_card_enhanced(
        session=session,
        question="编码遇阻：用哪个迁移策略？",
        options=["在线", "停机"],
        question_id="q-hitl-1",
    )

    assert message_id == "msg-fake-id"
    assert _FakeIMClient.sent and _FakeIMClient.sent[-1]["receive_id"] == "oc_node_chat"


async def test_send_card_failsoft_no_chat_id(monkeypatch):
    """无 main_session 且 node 无 chat_id → fail-soft 返回 None，不抛。"""
    from subagent.question_handler import send_question_card_enhanced

    monkeypatch.setattr("services.feishu_im.FeishuIMClient", _FakeIMClient)

    ne = await _make_node_execution(chat_id="")  # node config 无 chat_id
    main = await _make_main_session(chat_id="")  # 主会话亦无 chat_id
    session = await SubAgentSession.objects.acreate(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=main,
        node_execution=ne,
        repo_url="https://github.com/test/repo",
        task_type="coding",
        status=SubAgentSession.Status.RUNNING,
    )

    message_id = await send_question_card_enhanced(
        session=session,
        question="遇阻提问",
        question_id="q-hitl-2",
    )
    assert message_id is None


async def test_send_card_main_session_chat_id_unchanged(monkeypatch):
    """main_session.metadata.chat_id 路径零回归——仍走 main_session，不依赖 fallback。"""
    from django.conf import settings

    from subagent.question_handler import send_question_card_enhanced

    _FakeIMClient.sent = []
    monkeypatch.setattr("services.feishu_im.FeishuIMClient", _FakeIMClient)
    monkeypatch.setattr(settings, "FEISHU_APP_ID", "app", raising=False)
    monkeypatch.setattr(settings, "FEISHU_APP_SECRET", "secret", raising=False)

    main = await _make_main_session(chat_id="oc_main_chat")
    session = await SubAgentSession.objects.acreate(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=main,
        repo_url="https://github.com/test/repo",
        task_type="coding",
        status=SubAgentSession.Status.RUNNING,
    )

    message_id = await send_question_card_enhanced(
        session=session, question="提问", question_id="q-hitl-3"
    )
    assert message_id == "msg-fake-id"
    assert _FakeIMClient.sent[-1]["receive_id"] == "oc_main_chat"


# ---------------------------------------------------------------------------
# e2e — 遇阻 RUNNING → waiting → 回答 completed → 推进
# ---------------------------------------------------------------------------


async def _build_two_wave_tasks() -> tuple[ArtifactVersion, str, str, SubAgentSession]:
    """建 A(wave0) ← B(wave1 depends A)；A 置 running + pending_question（模拟遇阻发问）。"""
    pv = await _make_plan_version()
    repo_a = await _make_repo("hitl-a")
    repo_b = await _make_repo("hitl-b")
    id_a, id_b = str(repo_a.id), str(repo_b.id)

    service = RepoCodingTaskService()
    tasks = await service.create_tasks_for_plan(
        pv,
        repo_waves={id_a: 0, id_b: 1},
        repo_dep_edges={id_b: [id_a]},
    )

    # A 遇阻发问：SubAgentSession RUNNING + pending_question，task A → running。
    main = await _make_main_session(chat_id="")
    sess_a = await SubAgentSession.objects.acreate(
        session_id=f"sub-a-{uuid.uuid4().hex[:8]}",
        main_session=main,
        repo_url="https://github.com/test/repo",
        task_type="coding",
        status=SubAgentSession.Status.RUNNING,
        last_output={
            "pending_question": {"question_id": "q1", "question": "遇阻：怎么办？"}
        },
    )
    await service.mark_running(tasks[id_a], sess_a)
    return pv, id_a, id_b, sess_a


async def test_blocked_wave_task_stays_waiting():
    """遇阻 A RUNNING → aadvance 返回 waiting：A 未被标 failed、下游 B 未被阻断/派发（不 dead-end）。"""
    pv, id_a, id_b, _sess_a = await _build_two_wave_tasks()

    result = await aadvance_coding_waves(pv.id)

    assert result == {"waiting": True}
    task_a = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_a)
    task_b = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_b)
    assert task_a.status == RepoCodingTaskStatus.RUNNING  # 仍在途（遇阻等待），未失败
    assert task_b.status == RepoCodingTaskStatus.PENDING  # 下游未被阻断、未派发


async def test_answer_then_complete_resumes_wave():
    """回答后 A 容器 completed → aadvance 回填 A done 并 dispatch 下游 B（经既有 Phase 44 推进）。"""
    pv, id_a, id_b, sess_a = await _build_two_wave_tasks()

    # 模拟用户回答后容器续跑完成（HITL 解除阻塞 → 正常完成回调）。
    sess_a.status = SubAgentSession.Status.COMPLETED
    sess_a.last_output = {**(sess_a.last_output or {})}
    sess_a.last_output.pop("pending_question", None)
    await sess_a.asave(update_fields=["status", "last_output"])
    await TaskResult.objects.acreate(session=sess_a, pr_url="https://mr/a", raw_output={})

    result = await aadvance_coding_waves(pv.id)

    task_a = await RepoCodingTask.objects.aget(artifact_version=pv, repository_id=id_a)
    assert task_a.status == RepoCodingTaskStatus.DONE
    assert "dispatch" in result
    dispatched_repo_ids = {str(t.repository_id) for t in result["dispatch"]}
    assert dispatched_repo_ids == {id_b}
    assert result["wave"] == 1


async def test_hitl_path_does_not_trigger_replan(monkeypatch):
    """no-replan 守护（HITL-01c）：遇阻→等待→回答→推进全程不触发 research/replan 编排。"""
    import services.process_runtime.research_aggregation as ra

    replan_spy = AsyncMock()
    # 守护代表性 research/replan 编排入口——HITL wave 推进绝不应调用它。
    monkeypatch.setattr(ra, "amaybe_complete_research", replan_spy)

    pv, id_a, id_b, sess_a = await _build_two_wave_tasks()

    # 遇阻等待：aadvance → waiting。
    assert await aadvance_coding_waves(pv.id) == {"waiting": True}

    # 回答续跑 → completed → aadvance 推进。
    sess_a.status = SubAgentSession.Status.COMPLETED
    await sess_a.asave(update_fields=["status"])
    await TaskResult.objects.acreate(session=sess_a, pr_url="https://mr/a", raw_output={})
    result = await aadvance_coding_waves(pv.id)

    assert "dispatch" in result
    # 关键守护：HITL 链路全程零触发 research/replan 编排（只抛人、不重规划）。
    replan_spy.assert_not_awaited()
