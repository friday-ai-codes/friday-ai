"""MCP report_project_state 守护测试（HOOK-03，Phase 86-04）。

覆盖：
- 成员经工具把结构化 API 清单（method/path/params/status）直写 ProjectStateApi（source=HOOK）；
- 跨会话/跨角色即时可读（写后经独立查询读到全部结构化条目）；
- (project, method, path) 幂等 upsert（重复回写不产生重复行，params/status 被更新）；
- 审计可回滚（写入 state_api_added → remove_state_api → state_api_removed 且行删除）；
- 逐条 fail-soft（批量含非法项：合法项写入、非法项标失败、HTTP 200 不抛）；
- 非成员 / 未认证 → 静默跳过（applied=false，200，不写、不抛）；
- 归因（审计 actor = 令牌所属用户）；
- 观测留痕（ToolCallRecord/RequestMetric，call_source=report_project_state）。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from audit.models import AuditEvent
from audit.services import taxonomy
from initiatives.models import ApiSource, ApiStatus, ProjectStateApi
from initiatives.services import ProjectDocService, ProjectService
from interactions.models import ToolCallRecord
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()
_URL = "/api/mcp/tools/report_project_state/"


async def _make_project(created_by, key="rps-board"):
    space = await sync_to_async(Space.objects.create)(
        name="S", feishu_project_key=f"{key}-sp"
    )
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=created_by
    )
    return project


@sync_to_async
def _state_apis(project_id) -> list[ProjectStateApi]:
    return list(
        ProjectStateApi.objects.filter(project_id=project_id).order_by("path")
    )


@sync_to_async
def _state_api_count(project_id) -> int:
    return ProjectStateApi.objects.filter(project_id=project_id).count()


@sync_to_async
def _audit_count(action) -> int:
    return AuditEvent.objects.filter(action=action).count()


@sync_to_async
def _first_audit(action):
    return AuditEvent.objects.filter(action=action).first()


async def test_member_structured_upsert_writes_state_apis(mcp_client, access_user) -> None:
    """成员经工具写结构化清单 → 每项一行 ProjectStateApi（source=HOOK）+ 审计 added。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="rps-write")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "apis": [
                {
                    "method": "post",
                    "path": "/api/login",
                    "params": {"username": "str", "password": "str"},
                    "status": "implemented",
                },
                {"method": "GET", "path": "/api/profile"},
            ],
        },
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is True
    assert body["total_applied"] == 2
    assert {r["action"] for r in body["results"]} == {"created"}

    # 跨会话/跨角色即时可读：独立查询读到全部结构化条目。
    rows = await _state_apis(project.id)
    assert len(rows) == 2
    login = next(r for r in rows if r.path == "/api/login")
    assert login.method == "POST"  # 规范化大写
    assert login.params == {"username": "str", "password": "str"}
    assert login.status == ApiStatus.IMPLEMENTED
    assert login.source == ApiSource.HOOK
    profile = next(r for r in rows if r.path == "/api/profile")
    assert profile.method == "GET"
    assert profile.status == ApiStatus.IMPLEMENTED

    # 每条写入产 state_api_added 审计。
    assert await _audit_count(taxonomy.ACTION_PROJECT_STATE_API_ADDED) == 2


async def test_idempotent_upsert_no_duplicate_rows(mcp_client, access_user) -> None:
    """重复回写同 (method, path) → 不产生重复行，params/status 被更新。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="rps-idem")
    payload = {
        "project_id": str(project.id),
        "apis": [
            {"method": "GET", "path": "/api/orders", "status": "planned"},
        ],
    }
    resp1 = await sync_to_async(client.post)(_URL, payload, format="json")
    assert resp1.status_code == 200
    assert resp1.json()["results"][0]["action"] == "created"

    # 二次回写：同 (method, path)，新 status/params。
    resp2 = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "apis": [
                {
                    "method": "GET",
                    "path": "/api/orders",
                    "params": {"page": "int"},
                    "status": "implemented",
                },
            ],
        },
        format="json",
    )
    assert resp2.status_code == 200
    assert resp2.json()["results"][0]["action"] == "updated"

    assert await _state_api_count(project.id) == 1
    rows = await _state_apis(project.id)
    assert rows[0].status == ApiStatus.IMPLEMENTED
    assert rows[0].params == {"page": "int"}


async def test_audit_rollback_chain(mcp_client, access_user) -> None:
    """写入产 state_api_added；经 remove_state_api 撤销产 state_api_removed 且行删除。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="rps-roll")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "apis": [{"method": "DELETE", "path": "/api/session"}],
        },
        format="json",
    )
    assert resp.status_code == 200
    assert await _audit_count(taxonomy.ACTION_PROJECT_STATE_API_ADDED) == 1

    rows = await _state_apis(project.id)
    assert len(rows) == 1

    # 撤销：经 INV-6 service 移除 → 审计 state_api_removed + 行删除（可回滚链完整）。
    removed = await ProjectDocService().remove_state_api(
        project_id=project.id, api_id=rows[0].id, actor=access_user
    )
    assert removed is True
    assert await _audit_count(taxonomy.ACTION_PROJECT_STATE_API_REMOVED) == 1
    assert await _state_api_count(project.id) == 0


async def test_per_item_fail_soft(mcp_client, access_user) -> None:
    """批量含非法项（缺 path）→ 合法项写入、非法项标失败、HTTP 200 不抛。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="rps-soft")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "apis": [
                {"method": "GET", "path": "/api/ok"},
                {"method": "GET", "path": "   "},  # 非法：path 空白
                {"method": "", "path": "/api/no-method"},  # 非法：缺 method
            ],
        },
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_applied"] == 1
    actions = [r["action"] for r in body["results"]]
    assert actions == ["created", "skipped", "skipped"]
    # 仅合法项落库。
    assert await _state_api_count(project.id) == 1


async def test_non_member_silent_skip(mcp_client) -> None:
    """非成员 → applied=false reason=not_member，HTTP 200，不写、不抛。"""
    client, _ = mcp_client
    other = await sync_to_async(User.objects.create_user)(
        username="rps-other", password="x"
    )
    project = await _make_project(other, key="rps-nm")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "apis": [{"method": "GET", "path": "/api/x"}],
        },
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied"] is False
    assert body["reason"] == "not_member"
    assert await _state_api_count(project.id) == 0


async def test_attribution_records_token_user(mcp_client, access_user) -> None:
    """审计归因：state_api_added 的 actor 为令牌所属用户（非匿名 system）。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="rps-attr")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "apis": [{"method": "PUT", "path": "/api/settings"}],
        },
        format="json",
    )
    assert resp.status_code == 200
    event = await _first_audit(taxonomy.ACTION_PROJECT_STATE_API_ADDED)
    assert event is not None
    assert str(event.actor_id) == str(access_user.id)


async def test_batch_report_schedules_materialization_once(mcp_client, access_user) -> None:
    """批量上报 N 条 API → STATE 物化只合并调度一次（102-REVIEW MED-01 去抖）。"""
    from unittest.mock import AsyncMock, patch

    from initiatives.models import DocType, ProjectDoc

    client, _ = mcp_client
    project = await _make_project(access_user, key="rps-coalesce")
    doc = await sync_to_async(ProjectDoc.objects.create)(
        project=project, doc_type=DocType.STATE
    )
    apis = [{"method": "GET", "path": f"/api/batch/{i}"} for i in range(5)]
    mock_schedule = AsyncMock()
    with patch("knowledge.ingestion.aschedule_ingestion", mock_schedule):
        resp = await sync_to_async(client.post)(
            _URL,
            {"project_id": str(project.id), "apis": apis},
            format="json",
        )
    assert resp.status_code == 200
    assert resp.json()["total_applied"] == 5
    # 逐条 upsert 传 defer_materialize=True，循环后合并调度恰一次。
    assert mock_schedule.await_count == 1
    assert mock_schedule.await_args_list[0].args[0].source_id == str(doc.id)


async def test_observability_records_tool_call(mcp_client, access_user) -> None:
    """观测留痕：写一条 ToolCallRecord（call_source/tool_name=report_project_state）。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="rps-obs")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "apis": [{"method": "GET", "path": "/api/health"}],
        },
        format="json",
    )
    assert resp.status_code == 200
    exists = await sync_to_async(
        ToolCallRecord.objects.filter(tool_name="report_project_state").exists
    )()
    assert exists is True
