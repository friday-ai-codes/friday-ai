"""HumanTask 统一待办 REST API 守护测试（Chassis v2 · P8）。

覆盖：
- inbox list：鉴权；物化 + 投影聚合；?mine= / ?include_projections= 过滤。
- open：POST 开原生待办（dedup 幂等）+ 入参 400。
- action：resolve / skip（回流）+ 非法 action 400 + 不存在 404。
- clarification answer：投影澄清按题作答回流（答毕从收件箱消失）。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import async_to_sync

from delivery.models import (
    ConvergenceSession,
    HumanTask,
    HumanTaskStatus,
    HumanTaskType,
)
from delivery.services import ClarificationService
from projects.models import Space
from workflows.models import (
    NodeExecution,
    NodeExecutionStatus,
    Workflow,
    WorkflowExecution,
    WorkflowNode,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _make_waiting_approval() -> WorkflowExecution:
    space = Space.objects.create(name=f"s-{uuid.uuid4().hex[:6]}")
    workflow = Workflow.objects.create(
        name="WF", trigger_type="manual", space=space
    )
    node = WorkflowNode.objects.create(
        workflow=workflow, node_type="condition", name="审批节点", position_x=0, position_y=0
    )
    execution = WorkflowExecution.objects.create(
        workflow=workflow, space=space, trigger_type="manual"
    )
    NodeExecution.objects.create(
        workflow_execution=execution,
        node=node,
        status=NodeExecutionStatus.WAITING_APPROVAL,
    )
    return execution


def _make_pending_clarification() -> ConvergenceSession:
    session = ConvergenceSession.objects.create(
        process_type="technical_plan", entrypoint="workflow"
    )
    async_to_sync(ClarificationService().create_round)(
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
    return session


# ── inbox list ──────────────────────────────────────────────────────────


def test_inbox_requires_auth(api_client) -> None:
    resp = api_client.get("/api/delivery/human-tasks/")
    assert resp.status_code in (401, 403)


def test_inbox_aggregates_materialized_and_projections(authenticated_client) -> None:
    HumanTask.objects.create(
        task_type=HumanTaskType.RISK_ACK, scope="artifact", subject_id="art-1"
    )
    _make_waiting_approval()
    _make_pending_clarification()

    resp = authenticated_client.get("/api/delivery/human-tasks/")
    assert resp.status_code == 200
    body = resp.json()
    types = {row["task_type"] for row in body}
    assert HumanTaskType.RISK_ACK in types
    assert HumanTaskType.APPROVAL in types
    assert HumanTaskType.CLARIFICATION in types


def test_inbox_include_projections_off(authenticated_client) -> None:
    HumanTask.objects.create(
        task_type=HumanTaskType.RISK_ACK, scope="artifact", subject_id="art-1"
    )
    _make_waiting_approval()
    resp = authenticated_client.get(
        "/api/delivery/human-tasks/?include_projections=0"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["source"] == "materialized"


def test_inbox_mine_filters_materialized(authenticated_client, user) -> None:
    HumanTask.objects.create(
        task_type=HumanTaskType.TAKEOVER,
        scope="workflow_execution",
        subject_id="e1",
        assignee_user_id=str(user.id),
    )
    HumanTask.objects.create(
        task_type=HumanTaskType.TAKEOVER,
        scope="workflow_execution",
        subject_id="e2",
        assignee_user_id="999999",
    )
    resp = authenticated_client.get(
        "/api/delivery/human-tasks/?mine=1&include_projections=0"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["subject_id"] == "e1"


# ── open ────────────────────────────────────────────────────────────────


def test_open_task_creates(authenticated_client) -> None:
    resp = authenticated_client.post(
        "/api/delivery/human-tasks/",
        {
            "task_type": "risk_ack",
            "scope": "artifact",
            "subject_id": "art-9",
            "source_signal": "artifact.produced",
        },
        format="json",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["task_type"] == "risk_ack"
    assert HumanTask.objects.filter(id=body["id"]).exists()


def test_open_task_invalid_400(authenticated_client) -> None:
    resp = authenticated_client.post(
        "/api/delivery/human-tasks/",
        {"task_type": "bogus", "scope": "artifact", "subject_id": "x"},
        format="json",
    )
    assert resp.status_code == 400


# ── action ──────────────────────────────────────────────────────────────


def test_action_resolve(authenticated_client) -> None:
    task = HumanTask.objects.create(
        task_type=HumanTaskType.RISK_ACK, scope="artifact", subject_id="art-1"
    )
    resp = authenticated_client.post(
        f"/api/delivery/human-tasks/{task.id}/resolve/",
        {"resolution": {"ack": True}},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == HumanTaskStatus.DONE
    task.refresh_from_db()
    assert task.status == HumanTaskStatus.DONE
    assert task.resolution == {"ack": True}


def test_action_skip(authenticated_client) -> None:
    task = HumanTask.objects.create(
        task_type=HumanTaskType.RISK_ACK, scope="artifact", subject_id="art-1"
    )
    resp = authenticated_client.post(
        f"/api/delivery/human-tasks/{task.id}/skip/",
        {"reason": "无需"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == HumanTaskStatus.SKIPPED


def test_action_invalid_400(authenticated_client) -> None:
    task = HumanTask.objects.create(
        task_type=HumanTaskType.RISK_ACK, scope="artifact", subject_id="art-1"
    )
    resp = authenticated_client.post(
        f"/api/delivery/human-tasks/{task.id}/bogus/", {}, format="json"
    )
    assert resp.status_code == 400


def test_action_not_found_404(authenticated_client) -> None:
    resp = authenticated_client.post(
        f"/api/delivery/human-tasks/{uuid.uuid4()}/resolve/", {}, format="json"
    )
    assert resp.status_code == 404


# ── clarification answer 回流 ──────────────────────────────────────────────


def test_clarification_answer_resolves_projection(authenticated_client) -> None:
    session = _make_pending_clarification()
    clar = session.clarifications.first()
    qid = str(clar.questions.first().id)

    # 答前：收件箱含该澄清投影
    before = authenticated_client.get("/api/delivery/human-tasks/").json()
    assert any(r["task_type"] == HumanTaskType.CLARIFICATION for r in before)

    resp = authenticated_client.post(
        f"/api/delivery/human-tasks/clarification/{clar.id}/answer/",
        {"answers": [{"question_id": qid, "selected": "JWT"}]},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == HumanTaskStatus.DONE

    # 答后：投影从收件箱自然消失（回流）
    after = authenticated_client.get("/api/delivery/human-tasks/").json()
    assert not any(r["task_type"] == HumanTaskType.CLARIFICATION for r in after)


def test_clarification_answer_empty_400(authenticated_client) -> None:
    session = _make_pending_clarification()
    clar = session.clarifications.first()
    resp = authenticated_client.post(
        f"/api/delivery/human-tasks/clarification/{clar.id}/answer/",
        {"answers": []},
        format="json",
    )
    assert resp.status_code == 400


def test_clarification_answer_not_found_404(authenticated_client) -> None:
    resp = authenticated_client.post(
        f"/api/delivery/human-tasks/clarification/{uuid.uuid4()}/answer/",
        {"answers": [{"question_id": str(uuid.uuid4()), "selected": "x"}]},
        format="json",
    )
    assert resp.status_code == 404
