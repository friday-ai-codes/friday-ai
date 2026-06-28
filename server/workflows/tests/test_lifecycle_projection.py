"""Chassis v2 · P5 节点生命周期相位投影测试。

覆盖纯函数 ``project_node_lifecycle`` 在不同 NodeExecution + ConvergenceSession +
澄清轮次组合下的相位/轮次映射；以及 best-effort 异步收集器 ``aproject_node_lifecycle``
的库查 + 软关联 + 失败隔离。
"""

import pytest

from workflows.lifecycle_projection import (
    DEFAULT_MAX_ROUNDS,
    PHASE_DONE,
    PHASE_FAILED,
    PHASE_IDLE,
    PHASE_PRODUCED,
    PHASE_REVISING,
    PHASE_RUNNING,
    PHASE_WAITING_APPROVAL,
    PHASE_WAITING_CLARIFICATION,
    aproject_node_lifecycle,
    project_node_lifecycle,
)


class _FakeNodeExecution:
    def __init__(self, status, id="ne-1"):
        self.id = id
        self.status = status


class _FakeSession:
    def __init__(self, status="", current_artifact_version_id=None):
        self.status = status
        self.current_artifact_version_id = current_artifact_version_id


# ---- 纯函数：纯节点态（无 session）映射 ---------------------------------------


@pytest.mark.parametrize(
    "node_status,expected",
    [
        ("pending", PHASE_IDLE),
        ("queued", PHASE_IDLE),
        ("skipped", PHASE_IDLE),
        ("cancelled", PHASE_IDLE),
        ("running", PHASE_RUNNING),
        ("waiting_event", PHASE_RUNNING),
        ("waiting_approval", PHASE_WAITING_APPROVAL),
        ("waiting_input", PHASE_WAITING_CLARIFICATION),
        ("completed", PHASE_DONE),
        ("failed", PHASE_FAILED),
        ("timeout", PHASE_FAILED),
    ],
)
def test_pure_node_status_only(node_status, expected):
    """无关联 session 时退化为纯节点态映射。"""
    proj = project_node_lifecycle(_FakeNodeExecution(node_status))
    assert proj.lifecycle == expected
    assert proj.max_rounds == DEFAULT_MAX_ROUNDS


def test_completed_with_artifact_is_produced():
    """节点完成且 session 有产物版本 → produced（已产出）。"""
    proj = project_node_lifecycle(
        _FakeNodeExecution("completed"),
        session=_FakeSession(status="done", current_artifact_version_id="av-1"),
    )
    assert proj.lifecycle == PHASE_PRODUCED


def test_session_done_overrides_running_node_to_produced():
    """会话已 done 而节点尚 running → 投影为 produced。"""
    proj = project_node_lifecycle(
        _FakeNodeExecution("running"),
        session=_FakeSession(status="done", current_artifact_version_id="av-9"),
    )
    assert proj.lifecycle == PHASE_PRODUCED


def test_waiting_clarification_uses_pending_round():
    """会话等待澄清 → waiting_clarification，round = 待答轮次。"""
    proj = project_node_lifecycle(
        _FakeNodeExecution("waiting_event"),
        session=_FakeSession(status="waiting_clarification"),
        pending_round_no=2,
        answered_round_count=1,
    )
    assert proj.lifecycle == PHASE_WAITING_CLARIFICATION
    assert proj.round == 2


def test_waiting_clarification_round_fallback_to_answered_plus_one():
    """待答轮次缺失时 round 回退为 已答数+1。"""
    proj = project_node_lifecycle(
        _FakeNodeExecution("waiting_input"),
        session=_FakeSession(status="waiting_clarification"),
        pending_round_no=None,
        answered_round_count=1,
    )
    assert proj.lifecycle == PHASE_WAITING_CLARIFICATION
    assert proj.round == 2


def test_revising_after_answered_clarification():
    """已答过澄清 + 会话重新运行 → revising，round = 已答轮数。"""
    proj = project_node_lifecycle(
        _FakeNodeExecution("running"),
        session=_FakeSession(status="running"),
        answered_round_count=1,
    )
    assert proj.lifecycle == PHASE_REVISING
    assert proj.round == 1


def test_first_pass_running_is_not_revising():
    """首轮（无已答澄清）running → running，非 revising。"""
    proj = project_node_lifecycle(
        _FakeNodeExecution("running"),
        session=_FakeSession(status="running"),
        answered_round_count=0,
    )
    assert proj.lifecycle == PHASE_RUNNING
    assert proj.round is None


def test_session_failed_overrides_running_node():
    """会话失败即便节点仍 running → failed。"""
    proj = project_node_lifecycle(
        _FakeNodeExecution("running"),
        session=_FakeSession(status="failed"),
        answered_round_count=2,
    )
    assert proj.lifecycle == PHASE_FAILED
    assert proj.round == 2


def test_failed_dominates_over_clarification():
    """节点失败优先于澄清等待。"""
    proj = project_node_lifecycle(
        _FakeNodeExecution("failed"),
        session=_FakeSession(status="waiting_clarification"),
        pending_round_no=3,
    )
    assert proj.lifecycle == PHASE_FAILED


def test_waiting_approval_gate():
    """审批闸门 → waiting_approval（不论 session）。"""
    proj = project_node_lifecycle(
        _FakeNodeExecution("waiting_approval"),
        session=_FakeSession(status="running"),
    )
    assert proj.lifecycle == PHASE_WAITING_APPROVAL


# ---- 异步收集器：库查 + 软关联 + 失败隔离 -------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_aproject_with_linked_session_and_clarifications():
    """端到端：建 session（node_execution_id 软关联）+ 一答一待澄清 → revising/waiting。"""
    from django.utils import timezone

    from delivery.models import Clarification, ConvergenceSession

    ne = _FakeNodeExecution("running", id="11111111-1111-1111-1111-111111111111")
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint="workflow",
        status="waiting_clarification",
        node_execution_id=ne.id,
    )
    # 已答一轮 + 待答一轮
    await Clarification.objects.acreate(
        session=session, question="q1", answer="a1", answered_at=timezone.now(), round_no=1
    )
    await Clarification.objects.acreate(session=session, question="q2", round_no=2)

    proj = await aproject_node_lifecycle(ne)
    assert proj is not None
    # 存在待答澄清 → waiting_clarification，轮次取待答轮
    assert proj.lifecycle == PHASE_WAITING_CLARIFICATION
    assert proj.round == 2


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_aproject_no_session_returns_node_only_phase():
    """无关联 session → 退化为纯节点态（completed → done）。"""
    ne = _FakeNodeExecution("completed", id="22222222-2222-2222-2222-222222222222")
    proj = await aproject_node_lifecycle(ne)
    assert proj is not None
    assert proj.lifecycle == PHASE_DONE


@pytest.mark.asyncio
async def test_aproject_missing_id_returns_none():
    """node_execution 无 id → None（调用方跳过补字段）。"""

    class _NoId:
        status = "running"

    assert await aproject_node_lifecycle(_NoId()) is None
