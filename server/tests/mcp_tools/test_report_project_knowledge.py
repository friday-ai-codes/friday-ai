"""MCP report_project_knowledge 守护测试（CURSOR-03）。

覆盖：
- 成员上报 → 入 pending 草稿（绝不直接 active）；
- 质量门槛：过短/低信息量/重复 → accepted=False 不入库；
- 脱敏不可绕过（凭证不落明文）；
- 非项目成员 → 403 fail-closed；
- 归因（initiated_by = 令牌用户）。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import (
    DraftStatus,
    ProjectMemory,
    ProjectMemoryDraft,
)
from initiatives.services import MemoryService, ProjectService
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()
_URL = "/api/mcp/tools/report_project_knowledge/"


async def _make_project(created_by, key="rpk-board"):
    space = await sync_to_async(Space.objects.create)(name="S", feishu_project_key=f"{key}-sp")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=created_by
    )
    return project


@sync_to_async
def _draft_count(project_id) -> int:
    return ProjectMemoryDraft.objects.filter(project_id=project_id).count()


@sync_to_async
def _active_count(project_id) -> int:
    return ProjectMemory.objects.filter(project_id=project_id).count()


@sync_to_async
def _first_draft(project_id):
    return ProjectMemoryDraft.objects.filter(project_id=project_id).first()


async def test_member_report_creates_pending_draft(mcp_client, access_user) -> None:
    client, _ = mcp_client
    project = await _make_project(access_user, key="rpk-a")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "content": "方案决策：登录态统一走 cookie-JWT，避免本地存储 token。",
        },
        format="json",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["accepted"] is True
    assert body["draft_id"]
    # 默认入 pending 草稿，绝不直接 active。
    assert await _draft_count(project.id) == 1
    assert await _active_count(project.id) == 0
    draft = await _first_draft(project.id)
    assert draft.status == DraftStatus.PENDING


async def test_quality_gate_rejects_too_short(mcp_client, access_user) -> None:
    client, _ = mcp_client
    project = await _make_project(access_user, key="rpk-short")
    resp = await sync_to_async(client.post)(
        _URL, {"project_id": str(project.id), "content": "ok"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is False
    assert body["reason"] == "too_short"
    assert await _draft_count(project.id) == 0


async def test_quality_gate_rejects_duplicate(mcp_client, access_user) -> None:
    client, _ = mcp_client
    project = await _make_project(access_user, key="rpk-dup")
    text = "方案决策：登录态统一走 cookie-JWT 刷新，避免本地存储明文 token 泄漏。"
    await MemoryService().append(
        project_id=project.id, content=text, contributor=access_user
    )
    resp = await sync_to_async(client.post)(
        _URL, {"project_id": str(project.id), "content": text}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is False
    assert body["reason"] == "duplicate"


async def test_redaction_not_bypassable(mcp_client, access_user) -> None:
    client, _ = mcp_client
    project = await _make_project(access_user, key="rpk-secret")
    secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "content": f"接入说明：使用 token {secret} 调用上游 API 完成同步流程。",
        },
        format="json",
    )
    assert resp.status_code == 201
    draft = await _first_draft(project.id)
    assert secret not in draft.content


async def test_non_member_forbidden(mcp_client) -> None:
    client, _ = mcp_client
    other = await sync_to_async(User.objects.create_user)(
        username="rpk-other", password="x"
    )
    project = await _make_project(other, key="rpk-nm")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "content": "外部人员尝试上报的有意义但越权内容，应被 fail-closed 拒绝。",
        },
        format="json",
    )
    assert resp.status_code == 403
    assert await _draft_count(project.id) == 0


async def test_attribution_records_token_user(mcp_client, access_user) -> None:
    client, _ = mcp_client
    project = await _make_project(access_user, key="rpk-attr")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "content": "归因校验：本条草稿的提议人应为令牌所属用户而非匿名系统。",
        },
        format="json",
    )
    assert resp.status_code == 201
    draft = await _first_draft(project.id)
    assert str(draft.proposed_by_id) == str(access_user.id)
