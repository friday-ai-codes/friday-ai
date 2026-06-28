"""HumanTaskService 行为 + 统一投影测试（Chassis v2 · P8）。

覆盖：
- open_task（dedup 幂等）/ resolve / skip / expire / reassign / aexpire_due。
- list_inbox 物化行。
- 投影：待答 Clarification → clarification、NodeExecution.waiting_approval → approval、
  ReactionExecution.failed → reaction_retry。
- dedup：物化行（dedup_key 命中）抑制对应来源的重复投影。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from delivery.models import (
    ConvergenceSession,
    HumanTask,
    HumanTaskStatus,
    HumanTaskType,
)
from delivery.services import ClarificationService, HumanTaskService
from projects.models import Space
from workflows.models import (
    NodeExecution,
    NodeExecutionStatus,
    ReactionExecution,
    ReactionExecutionStatus,
    Workflow,
    WorkflowExecution,
    WorkflowNode,
    WorkflowReaction,
)

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_session() -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan", entrypoint="workflow"
    )


async def _make_pending_clarification(session: ConvergenceSession):
    svc = ClarificationService()
    return await svc.create_round(
        session,
        [
            {
                "question": "用哪个鉴权方案？",
                "type": "single",
                "options": ["JWT", "Session"],
                "recommended": ["JWT"],
            }
        ],
        round_no=1,
    )


async def _make_workflow_execution():
    space = await Space.objects.acreate(name="HT Space", description="ht tests")
    workflow = await Workflow.objects.acreate(
        name="HT Workflow", trigger_type="manual", space=space
    )
    node = await WorkflowNode.objects.acreate(
        workflow=workflow, node_type="condition", name="审批节点", position_x=0, position_y=0
    )
    execution = await WorkflowExecution.objects.acreate(
        workflow=workflow, space=space, trigger_type="manual"
    )
    return space, workflow, node, execution


# ── open / 流转 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_task_creates_open_row():
    svc = HumanTaskService()
    task = await svc.open_task(
        task_type=HumanTaskType.RISK_ACK,
        scope="artifact",
        subject_id="art-1",
        source_signal="artifact.produced",
    )
    assert task.status == HumanTaskStatus.OPEN
    assert task.task_type == HumanTaskType.RISK_ACK


@pytest.mark.asyncio
async def test_open_task_dedup_idempotent():
    svc = HumanTaskService()
    a = await svc.open_task(
        task_type=HumanTaskType.TAKEOVER,
        scope="workflow_execution",
        subject_id="exec-1",
        dedup_key="takeover:exec-1",
    )
    b = await svc.open_task(
        task_type=HumanTaskType.TAKEOVER,
        scope="workflow_execution",
        subject_id="exec-1",
        dedup_key="takeover:exec-1",
    )
    assert a.id == b.id
    count = await sync_to_async(
        HumanTask.objects.filter(dedup_key="takeover:exec-1").count
    )()
    assert count == 1


@pytest.mark.asyncio
async def test_open_task_invalid_type_rejected():
    svc = HumanTaskService()
    with pytest.raises(ValueError):
        await svc.open_task(task_type="bogus", scope="artifact", subject_id="x")


@pytest.mark.asyncio
async def test_resolve_marks_done():
    svc = HumanTaskService()
    task = await svc.open_task(
        task_type=HumanTaskType.RISK_ACK, scope="artifact", subject_id="art-1"
    )
    resolved = await svc.resolve(task, {"ack": True})
    assert resolved.status == HumanTaskStatus.DONE
    assert resolved.resolved_at is not None
    assert resolved.resolution == {"ack": True}


@pytest.mark.asyncio
async def test_skip_records_reason():
    svc = HumanTaskService()
    task = await svc.open_task(
        task_type=HumanTaskType.RISK_ACK, scope="artifact", subject_id="art-1"
    )
    skipped = await svc.skip(task, reason="无需确认")
    assert skipped.status == HumanTaskStatus.SKIPPED
    assert skipped.resolution.get("skip_reason") == "无需确认"


@pytest.mark.asyncio
async def test_resolve_only_open_idempotent():
    svc = HumanTaskService()
    task = await svc.open_task(
        task_type=HumanTaskType.RISK_ACK, scope="artifact", subject_id="art-1"
    )
    await svc.resolve(task, {"first": True})
    # 二次处理 no-op：不覆盖首次 resolution
    again = await svc.skip(task, reason="late")
    assert again.status == HumanTaskStatus.DONE
    assert again.resolution == {"first": True}


@pytest.mark.asyncio
async def test_reassign_changes_assignee():
    svc = HumanTaskService()
    task = await svc.open_task(
        task_type=HumanTaskType.TAKEOVER, scope="workflow_execution", subject_id="e1"
    )
    out = await svc.reassign(task, assignee_user_id="42", assignee_role="lead")
    assert out.assignee_user_id == "42"
    assert out.assignee_role == "lead"


@pytest.mark.asyncio
async def test_aexpire_due_expires_past_due():
    svc = HumanTaskService()
    past = timezone.now() - timezone.timedelta(hours=1)
    await svc.open_task(
        task_type=HumanTaskType.APPROVAL,
        scope="workflow_execution",
        subject_id="e1",
        due_at=past,
    )
    n = await svc.aexpire_due()
    assert n == 1
    remaining = await sync_to_async(
        HumanTask.objects.filter(status=HumanTaskStatus.OPEN).count
    )()
    assert remaining == 0


# ── 投影 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_inbox_includes_materialized():
    svc = HumanTaskService()
    await svc.open_task(
        task_type=HumanTaskType.RISK_ACK, scope="artifact", subject_id="art-1"
    )
    views = await svc.list_inbox(include_projections=False)
    assert len(views) == 1
    assert views[0].source == "materialized"
    assert views[0].task_type == HumanTaskType.RISK_ACK


@pytest.mark.asyncio
async def test_projects_pending_clarification():
    session = await _make_session()
    await _make_pending_clarification(session)

    svc = HumanTaskService()
    views = await svc.list_inbox()
    clar_views = [v for v in views if v.task_type == HumanTaskType.CLARIFICATION]
    assert len(clar_views) == 1
    v = clar_views[0]
    assert v.source == "projection"
    assert v.subject_id == str(session.id)
    assert "鉴权" in v.title
    assert v.detail["pending_count"] == 1
    assert v.detail["questions"]


@pytest.mark.asyncio
async def test_projects_waiting_approval_node():
    _, workflow, node, execution = await _make_workflow_execution()
    await NodeExecution.objects.acreate(
        workflow_execution=execution,
        node=node,
        status=NodeExecutionStatus.WAITING_APPROVAL,
    )
    svc = HumanTaskService()
    views = await svc.list_inbox()
    approvals = [v for v in views if v.task_type == HumanTaskType.APPROVAL]
    assert len(approvals) == 1
    assert approvals[0].subject_id == str(execution.id)
    assert approvals[0].title == "审批节点"
    assert approvals[0].source_signal == "approval.requested"


@pytest.mark.asyncio
async def test_projects_failed_reaction():
    _, workflow, node, execution = await _make_workflow_execution()
    reaction = await WorkflowReaction.objects.acreate(
        workflow=workflow,
        host_node=node,
        signal_name="node.failed",
        target_type="notify_feishu_im",
        config={},
    )
    await ReactionExecution.objects.acreate(
        reaction=reaction,
        workflow_execution=execution,
        idempotency_key="k1",
        status=ReactionExecutionStatus.FAILED,
        last_error="boom",
        triggered_signal="node.failed",
        attempts=2,
    )
    svc = HumanTaskService()
    views = await svc.list_inbox()
    retries = [v for v in views if v.task_type == HumanTaskType.REACTION_RETRY]
    assert len(retries) == 1
    assert retries[0].subject_id == str(execution.id)
    assert retries[0].detail["last_error"] == "boom"
    assert retries[0].detail["target_type"] == "notify_feishu_im"


@pytest.mark.asyncio
async def test_materialized_dedup_suppresses_projection():
    """物化一条 approval（dedup_key=approval:<ne>）后，对应 waiting_approval 不再重复投影。"""
    _, workflow, node, execution = await _make_workflow_execution()
    ne = await NodeExecution.objects.acreate(
        workflow_execution=execution,
        node=node,
        status=NodeExecutionStatus.WAITING_APPROVAL,
    )
    svc = HumanTaskService()
    await svc.open_task(
        task_type=HumanTaskType.APPROVAL,
        scope="workflow_execution",
        subject_id=str(execution.id),
        dedup_key=f"approval:{ne.id}",
    )
    views = await svc.list_inbox()
    approvals = [v for v in views if v.task_type == HumanTaskType.APPROVAL]
    # 仅一条（物化），投影被 dedup 抑制
    assert len(approvals) == 1
    assert approvals[0].source == "materialized"


@pytest.mark.asyncio
async def test_inbox_excludes_resolved_and_answered():
    """已处理物化行 + 已答澄清都不出现在收件箱。"""
    svc = HumanTaskService()
    task = await svc.open_task(
        task_type=HumanTaskType.RISK_ACK, scope="artifact", subject_id="a"
    )
    await svc.resolve(task, {"ok": True})

    session = await _make_session()
    clar = await _make_pending_clarification(session)
    qid = await sync_to_async(
        lambda: str(clar.questions.first().id)
    )()
    await ClarificationService().answer_round(
        clar, [{"question_id": qid, "selected": "JWT"}]
    )

    views = await svc.list_inbox()
    assert views == []
