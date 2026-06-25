"""``POST /api/chat/routing-traces/<uuid>/override/`` 测试。

测试范围（≥ 5 条）：

1. 写新行 manual_override trace（不改原行）
2. 只更新 selected_by_user_final（score / evidence / level 不被前端污染）
3. 跨用户访问 → 404
4. trace_id 不存在 → 404
5. body 缺字段 → 400
"""

from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

from chat.models import Conversation, RepositoryRoutingTrace
from permissions.models import SpaceMembership, SpaceRole
from projects.models import Space
from repositories.models import Repository


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def project_with_owner(db, user):
    proj = Space.objects.create(
        name=f"override-{uuid.uuid4().hex[:6]}",
        feishu_project_key=f"k-{uuid.uuid4().hex[:6]}",
    )
    SpaceMembership.objects.create(space=proj, user=user, role=SpaceRole.MEMBER)
    return proj


@pytest.fixture
def repo(db, project_with_owner):
    r = Repository.objects.create(
        name="r0",
        git_url="https://github.com/x/r0.git",
        git_platform="github",
        default_branch="main",
    )
    project_with_owner.repositories.add(r)
    return r


@pytest.fixture
def conversation(db, project_with_owner, user):
    return Conversation.objects.create(
        space=project_with_owner, title="override", created_by=user
    )


@pytest.fixture
def chat_tool_trace(db, conversation, repo):
    return RepositoryRoutingTrace.objects.create(
        conversation=conversation,
        query="orig query",
        candidates=[
            {
                "repository_id": str(repo.id),
                "repository_name": "r0",
                "score": 0.92,
                "level": "high",
                "evidence": "原 evidence",
                "selected_by_ai": True,
                "selected_by_user_final": True,
            },
            {
                "repository_id": str(uuid.uuid4()),
                "repository_name": "other",
                "score": 0.3,
                "level": "low",
                "evidence": "另一个 evidence",
                "selected_by_ai": False,
                "selected_by_user_final": False,
            },
        ],
        threshold=0.5,
        triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
    )


@pytest.fixture
def authed_client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _url(trace_id):
    return f"/api/chat/routing-traces/{trace_id}/override/"


def test_post_override_creates_new_trace(authed_client, chat_tool_trace, repo):
    other_id = chat_tool_trace.candidates[1]["repository_id"]
    resp = authed_client.post(
        _url(chat_tool_trace.id),
        data={
            "candidates": [
                {"repository_id": str(repo.id), "selected": False},
                {"repository_id": other_id, "selected": True},
            ],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["original_trace_id"] == str(chat_tool_trace.id)
    assert body["triggered_by"] == "manual_override"

    # DB 多了 manual_override 一行
    traces = list(
        RepositoryRoutingTrace.objects.filter(
            conversation_id=chat_tool_trace.conversation_id
        ).order_by("created_at")
    )
    assert len(traces) == 2
    new_trace = traces[1]
    assert new_trace.triggered_by == RepositoryRoutingTrace.TriggeredBy.MANUAL_OVERRIDE
    assert new_trace.agent_session_id is None
    # 字段继承
    assert new_trace.query == chat_tool_trace.query
    assert new_trace.threshold == chat_tool_trace.threshold
    # selected_by_user_final 已更新
    new_cands = {c["repository_id"]: c for c in new_trace.candidates}
    assert new_cands[str(repo.id)]["selected_by_user_final"] is False
    assert new_cands[other_id]["selected_by_user_final"] is True
    # score / evidence / level 继承自原 trace
    assert new_cands[str(repo.id)]["score"] == 0.92
    assert new_cands[str(repo.id)]["evidence"] == "原 evidence"
    assert new_cands[str(repo.id)]["level"] == "high"
    assert new_cands[str(repo.id)]["selected_by_ai"] is True


def test_post_override_does_not_mutate_original_trace(
    authed_client, chat_tool_trace, repo
):
    original_candidates = list(chat_tool_trace.candidates)
    authed_client.post(
        _url(chat_tool_trace.id),
        data={"candidates": [{"repository_id": str(repo.id), "selected": False}]},
        format="json",
    )
    chat_tool_trace.refresh_from_db()
    assert chat_tool_trace.candidates == original_candidates
    assert (
        chat_tool_trace.triggered_by
        == RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL
    )


def test_override_ignores_extra_fields(authed_client, chat_tool_trace, repo):
    """前端发额外字段（如 score / evidence）被 serializer 忽略，原值保留。"""
    resp = authed_client.post(
        _url(chat_tool_trace.id),
        data={
            "candidates": [
                {
                    "repository_id": str(repo.id),
                    "selected": False,
                    "score": 0.0,  # 应被忽略
                    "evidence": "hacked",  # 应被忽略
                },
            ],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    new_cands = {c["repository_id"]: c for c in body["candidates"]}
    # 注入字段被 dropped；原值继承
    assert new_cands[str(repo.id)]["score"] == 0.92
    assert new_cands[str(repo.id)]["evidence"] == "原 evidence"


def test_cross_user_access_forbidden(chat_tool_trace, db, repo):
    other = SpaceMembership.objects.create  # type: ignore[var-annotated]  # noqa
    from django.contrib.auth import get_user_model

    other_user = get_user_model().objects.create_user(
        username="otheruser-284",
        email="other-284@test.local",
        password="x",
    )
    c = APIClient()
    c.force_authenticate(user=other_user)
    resp = c.post(
        _url(chat_tool_trace.id),
        data={"candidates": [{"repository_id": str(repo.id), "selected": False}]},
        format="json",
    )
    assert resp.status_code == 404


def test_trace_id_not_found_returns_404(authed_client):
    resp = authed_client.post(
        _url(uuid.uuid4()),
        data={"candidates": [{"repository_id": str(uuid.uuid4()), "selected": True}]},
        format="json",
    )
    assert resp.status_code == 404


def test_invalid_body_400(authed_client, chat_tool_trace):
    resp = authed_client.post(
        _url(chat_tool_trace.id),
        data={"candidates": [{"selected": True}]},  # 缺 repository_id
        format="json",
    )
    assert resp.status_code == 400
