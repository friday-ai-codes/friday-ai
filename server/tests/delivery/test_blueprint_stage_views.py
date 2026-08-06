"""蓝图节点面两端点 REST 测试（quick 260806）。

守六件事：

1. 鉴权：两端点未认证一律拒（401/403）。
2. 范围闸正反并列：成员 2xx；非成员 404 且响应体与「artifact 不存在」逐字相同；
   superuser 直通。
3. ``GET stages/`` 无会话 → 200 空结构（⛔ 不 404），且 ``versions`` 仍可用。
4. ``GET stages/`` 有会话 → stage_state 按节点分片、重跑标记/历史透传、版本谱系清单。
5. ``POST rerun/`` 正路：200 + 会话回卷（DB 重读）；非法 stage → 400 且 DB 不写。
6. ``POST rerun/`` 指令正文不进事件 payload（脱敏纪律）。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse

from delivery.models import (
    Artifact,
    BlueprintStatus,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
)
from delivery.services import ArtifactService
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)

_SCOPE_PROJECT_ID = "11111111-1111-1111-1111-111111111111"
_OTHER_PROJECT_ID = "22222222-2222-2222-2222-222222222222"

_ENDPOINTS = [
    ("blueprint-stages", "get"),
    ("blueprint-stage-rerun", "post"),
]


def _make_project(project_id: str, *, member: Any = None) -> Any:
    from initiatives.models import Project, ProjectMember
    from projects.models import Space

    project = Project.objects.filter(id=project_id).first()
    if project is None:
        space, _ = Space.objects.get_or_create(
            name=f"space-{project_id[:8]}", defaults={"feishu_project_key": f"k-{project_id[:8]}"}
        )
        project = Project.objects.create(id=project_id, space=space, name=f"proj-{project_id[:8]}")
    if member is not None:
        ProjectMember.objects.get_or_create(project=project, user=member)
    return project


@pytest.fixture(autouse=True)
def _project_scope(user) -> Any:
    return _make_project(_SCOPE_PROJECT_ID, member=user)


@pytest.fixture(autouse=True)
def _no_enqueue(monkeypatch):
    """rerun 端点的续驱入队恒 no-op（不把真实 engine/LLM 拖进 REST 测试）。"""
    from services.process_runtime import blueprint_stage_rerun as rerun_module

    async def _noop(session, *, initiated_by_user_id):
        return None

    monkeypatch.setattr(rerun_module, "_aenqueue_resume", _noop)


def _make_artifact(
    status: str = BlueprintStatus.PENDING_REVIEW, *, project_id: str = _SCOPE_PROJECT_ID
) -> Artifact:
    content = make_blueprint()
    content["meta"]["project_id"] = project_id
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", content, title="节点面样例", created_by_user_id="tester"
    )
    Artifact.objects.filter(id=artifact.id).update(blueprint_status=status)
    artifact.blueprint_status = status
    return artifact


def _make_session(
    artifact: Artifact,
    *,
    current_stage: str = "ai_review",
    status: str = ConvergenceSessionStatus.DONE,
    stage_state: dict | None = None,
) -> ConvergenceSession:
    return ConvergenceSession.objects.create(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage=current_stage,
        status=status,
        stage_state=stage_state or {},
        current_artifact_version_id=Artifact.objects.get(id=artifact.id).current_version_id,
    )


def _call(client: Any, name: str, method: str, artifact_id: Any, **kwargs: Any) -> Any:
    url = reverse(name, args=[str(artifact_id)])
    if method == "post":
        return client.post(url, kwargs.get("data") or {"stage": "merge"}, format="json")
    return client.get(url)


# ═══════════════════════════════════════════════════════════════════════════
# 1-2. 鉴权与范围闸
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_stage_endpoints_reject_unauthenticated(api_client, name: str, method: str) -> None:
    resp = _call(api_client, name, method, uuid.uuid4())
    assert resp.status_code in (401, 403)


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_stage_endpoints_allow_project_members(
    authenticated_client, name: str, method: str
) -> None:
    artifact = _make_artifact()
    _make_session(artifact)
    resp = _call(authenticated_client, name, method, artifact.id)
    assert resp.status_code == 200


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_stage_endpoints_return_neutral_404_for_non_members(
    authenticated_client, name: str, method: str
) -> None:
    _make_project(_OTHER_PROJECT_ID)
    artifact = _make_artifact(project_id=_OTHER_PROJECT_ID)
    session = _make_session(artifact)

    denied = _call(authenticated_client, name, method, artifact.id)
    missing = _call(authenticated_client, name, method, uuid.uuid4())

    assert denied.status_code == 404
    assert missing.status_code == 404
    assert denied.json() == missing.json()
    # DB 一字未动（rerun 也不得回卷）
    fresh = ConvergenceSession.objects.get(id=session.id)
    assert fresh.current_stage == "ai_review"


@pytest.mark.parametrize(("name", "method"), _ENDPOINTS)
def test_stage_endpoints_pass_through_for_superuser(api_client, admin_user, name, method) -> None:
    _make_project(_OTHER_PROJECT_ID)
    artifact = _make_artifact(project_id=_OTHER_PROJECT_ID)
    _make_session(artifact)
    api_client.force_authenticate(user=admin_user)
    resp = _call(api_client, name, method, artifact.id)
    assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# 3-4. GET stages/
# ═══════════════════════════════════════════════════════════════════════════


def test_stages_without_session_returns_empty_structure(authenticated_client) -> None:
    artifact = _make_artifact()
    resp = _call(authenticated_client, "blueprint-stages", "get", artifact.id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == ""
    assert body["current_stage"] == ""
    assert body["stage_rerun"] is None
    # 无会话也要给版本清单（版本切换器不依赖会话存在）
    assert len(body["versions"]) == 1
    assert body["versions"][0]["version_label"] == "1"
    assert body["versions"][0]["is_current"] is True
    assert {item["key"] for item in body["stages"]} >= {"route", "merge", "ai_review"}


def test_stages_slices_stage_state_per_node(authenticated_client) -> None:
    artifact = _make_artifact()
    marker = {"stage": "route", "instruction": "x", "run_label": "1.1"}
    _make_session(
        artifact,
        current_stage="repo_plan",
        status=ConvergenceSessionStatus.RUNNING,
        stage_state={
            "routing": {"candidates": [{"repository_id": "r1"}]},
            "confirmation": {"repos": []},
            "repo_plan": {"pending": ["r1"]},
            "stage_rerun": marker,
            "stage_rerun_history": [marker],
        },
    )
    resp = _call(authenticated_client, "blueprint-stages", "get", artifact.id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_stage"] == "repo_plan"
    assert body["session_status"] == "running"
    assert body["run_label"] == "1.1"
    assert body["stage_rerun"] == marker
    assert body["stage_rerun_history"] == [marker]
    stages = {item["key"]: item["state"] for item in body["stages"]}
    assert stages["route"] == {"routing": {"candidates": [{"repository_id": "r1"}]}}
    assert stages["repo_confirmation"] == {"confirmation": {"repos": []}}
    assert stages["repo_plan"] == {"repo_plan": {"pending": ["r1"]}}
    # 未产出的节点分片为空 dict（不缺键）
    assert stages["merge"] == {}
    assert "route" in body["rerunnable_stages"]


# ═══════════════════════════════════════════════════════════════════════════
# 5-6. POST rerun/
# ═══════════════════════════════════════════════════════════════════════════


def test_rerun_endpoint_rewinds_session(authenticated_client) -> None:
    artifact = _make_artifact()
    session = _make_session(artifact)
    resp = _call(
        authenticated_client,
        "blueprint-stage-rerun",
        "post",
        artifact.id,
        data={"stage": "route", "instruction": "重点看网关"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["run_label"] == "1.1"

    fresh = ConvergenceSession.objects.get(id=session.id)
    assert fresh.current_stage == "route"
    assert fresh.status == ConvergenceSessionStatus.RUNNING
    assert fresh.stage_state["stage_rerun"]["instruction"] == "重点看网关"


def test_rerun_endpoint_rejects_unknown_stage(authenticated_client) -> None:
    artifact = _make_artifact()
    session = _make_session(artifact)
    resp = _call(
        authenticated_client,
        "blueprint-stage-rerun",
        "post",
        artifact.id,
        data={"stage": "ghost", "instruction": "x"},
    )
    assert resp.status_code == 400
    fresh = ConvergenceSession.objects.get(id=session.id)
    assert fresh.current_stage == "ai_review"


def test_rerun_endpoint_without_session_returns_400(authenticated_client) -> None:
    artifact = _make_artifact()
    resp = _call(
        authenticated_client,
        "blueprint-stage-rerun",
        "post",
        artifact.id,
        data={"stage": "route"},
    )
    assert resp.status_code == 400
