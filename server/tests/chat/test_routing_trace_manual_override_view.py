"""``POST /api/chat/routing-traces/<uuid>/override/`` 测试。

测试范围（≥ 5 条）：

1. 写新行 manual_override trace（不改原行）
2. 只更新 selected_by_user_final（score / evidence / level 不被前端污染）
3. 跨用户访问 → 404
4. trace_id 不存在 → 404
5. body 缺字段 → 400
6. 降级/分组事实继承与回传（107-08 Task 3，Pitfall 3 后端半边）：
   ``router_version`` / ``degrade_reason`` / ``block_order`` 三列必须**显式**继承 ——
   ``router_version`` 的列默认值是 ``legacy_hybrid``，不显式继承就会让「同一次路由的
   降级事实」在用户改一次勾选后凭空消失（降级横幅随之消失）。
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


def test_cross_project_access_forbidden(db, user, repo):
    """跨项目（会话归属自己但对该空间无成员权限）→ 仍 404。

    owner gate 通过后的第二道 project 级防御（V4）；本 plan 新增字段只在通过这两道
    校验后的分支里读写，不得成为绕过路径。
    """
    outsider_space = Space.objects.create(
        name=f"outsider-{uuid.uuid4().hex[:6]}",
        feishu_project_key=f"k-{uuid.uuid4().hex[:6]}",
    )
    conv = Conversation.objects.create(
        space=outsider_space, title="cross project", created_by=user
    )
    trace = RepositoryRoutingTrace.objects.create(
        conversation=conv,
        query="cross project query",
        candidates=[],
        threshold=0.5,
        triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
    )

    c = APIClient()
    c.force_authenticate(user=user)
    resp = c.post(
        _url(trace.id),
        data={"candidates": [{"repository_id": str(repo.id), "selected": False}]},
        format="json",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 降级 / 分组事实的继承与回传（107-08 Task 3）
# ---------------------------------------------------------------------------


@pytest.fixture
def degraded_trace(db, conversation, repo):
    """原 trace：降级 + 有分组上下文 + 候选携带呈现字段。"""
    return RepositoryRoutingTrace.objects.create(
        conversation=conversation,
        query="degraded orig",
        candidates=[
            {
                "repository_id": str(repo.id),
                "repository_name": "r0",
                "score": 0.88,
                "level": "high",
                "evidence": "Stage 0 命中",
                "selected_by_ai": True,
                "selected_by_user_final": True,
                "group": "in_project",
                "trust": "trusted",
                "score_ranked": 0.71,
            },
        ],
        threshold=0.5,
        triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
        router_version="v2_stage0_only",
        degrade_reason="timeout",
        block_order=["global", "in_project"],
    )


def _override(client, trace, repo, selected=False):
    return client.post(
        _url(trace.id),
        data={"candidates": [{"repository_id": str(repo.id), "selected": selected}]},
        format="json",
    )


def test_override_new_trace_inherits_degrade_facts(authed_client, degraded_trace, repo):
    """新 trace 行三列与原 trace 一致（同一次路由的事实不因用户改勾选而改变）。"""
    resp = _override(authed_client, degraded_trace, repo)
    assert resp.status_code == 201, resp.content

    new_trace = RepositoryRoutingTrace.objects.get(id=resp.json()["trace_id"])
    assert new_trace.router_version == "v2_stage0_only"
    assert new_trace.degrade_reason == "timeout"
    assert new_trace.block_order == ["global", "in_project"]


def test_override_response_returns_degrade_facts(authed_client, degraded_trace, repo):
    """响应回传 4 键且与新 trace 行一致 —— 前端 applyManualOverride 的数据来源。"""
    resp = _override(authed_client, degraded_trace, repo)
    assert resp.status_code == 201, resp.content
    body = resp.json()

    assert body["router_version"] == "v2_stage0_only"
    assert body["degraded"] is True
    assert body["degrade_reason"] == "timeout"
    assert body["block_order"] == ["global", "in_project"]

    new_trace = RepositoryRoutingTrace.objects.get(id=body["trace_id"])
    assert body["router_version"] == new_trace.router_version
    assert body["degrade_reason"] == new_trace.degrade_reason
    assert body["block_order"] == new_trace.block_order


def test_override_keeps_candidate_presentation_fields(
    authed_client, degraded_trace, repo
):
    """候选的 group / trust / score_ranked 不被字段白名单化丢弃。

    现行实现是浅拷贝后只改 selected_by_user_final（天然保留）；本断言防将来被重写成
    显式字段列表时静默丢字段（前端分组分区会随之失效）。
    """
    resp = _override(authed_client, degraded_trace, repo)
    assert resp.status_code == 201, resp.content
    cand = {c["repository_id"]: c for c in resp.json()["candidates"]}[str(repo.id)]
    assert cand["group"] == "in_project"
    assert cand["trust"] == "trusted"
    assert cand["score_ranked"] == 0.71
    assert cand["selected_by_user_final"] is False


def test_override_undegraded_original_stays_undegraded(
    authed_client, conversation, repo
):
    """原 trace router_version="v2" → 新 trace degraded False、无降级原因。"""
    trace = RepositoryRoutingTrace.objects.create(
        conversation=conversation,
        query="undegraded orig",
        candidates=[
            {
                "repository_id": str(repo.id),
                "repository_name": "r0",
                "score": 0.9,
                "level": "high",
                "evidence": "e",
                "selected_by_ai": True,
                "selected_by_user_final": True,
            },
        ],
        threshold=0.5,
        triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
        router_version="v2",
        block_order=["in_project", "global"],
    )
    resp = _override(authed_client, trace, repo)
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["router_version"] == "v2"
    assert body["degraded"] is False
    assert body["degrade_reason"] == ""

    new_trace = RepositoryRoutingTrace.objects.get(id=body["trace_id"])
    assert new_trace.degrade_reason == ""
    assert new_trace.block_order == ["in_project", "global"]


def test_override_twice_keeps_facts_along_the_chain(authed_client, degraded_trace, repo):
    """连续两次 override：第二次的原 trace 是第一次的新 trace，事实沿链不丢。"""
    first = _override(authed_client, degraded_trace, repo, selected=False)
    assert first.status_code == 201, first.content
    first_trace = RepositoryRoutingTrace.objects.get(id=first.json()["trace_id"])

    second = _override(authed_client, first_trace, repo, selected=True)
    assert second.status_code == 201, second.content
    body = second.json()
    assert body["router_version"] == "v2_stage0_only"
    assert body["degraded"] is True
    assert body["degrade_reason"] == "timeout"
    assert body["block_order"] == ["global", "in_project"]

    second_trace = RepositoryRoutingTrace.objects.get(id=body["trace_id"])
    assert second_trace.router_version == "v2_stage0_only"
    assert second_trace.degrade_reason == "timeout"
    assert second_trace.block_order == ["global", "in_project"]
    cand = {c["repository_id"]: c for c in second_trace.candidates}[str(repo.id)]
    assert cand["selected_by_user_final"] is True
    assert cand["group"] == "in_project"
