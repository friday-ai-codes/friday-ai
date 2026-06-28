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


# ===========================================================================
# Phase 86 HOOK-02：active 写回模式（用户授权 accepted deviation 2026-06-26）
# ===========================================================================


@sync_to_async
def _active_memory_count(project_id) -> int:
    return ProjectMemory.objects.filter(
        project_id=project_id, status="active"
    ).count()


@sync_to_async
def _first_active_memory(project_id):
    return ProjectMemory.objects.filter(
        project_id=project_id, status="active"
    ).first()


@sync_to_async
def _research_snapshot(project_id) -> str:
    from initiatives.models import DocType, ProjectDoc

    doc = ProjectDoc.objects.filter(
        project_id=project_id, doc_type=DocType.RESEARCH
    ).first()
    return doc.last_synced_snapshot if doc else ""


async def test_active_member_writes_active_memory(mcp_client, access_user) -> None:
    """active + 成员 → 写 active 记忆（非 draft），accepted=true + memory_id，HTTP 200。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="rpk-active")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "content": "active 直写：会话结束沉淀本次架构决策，直接生效无需人工确认。",
            "writeback_mode": "active",
        },
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["memory_id"]
    # active 直写，绝不落 draft。
    assert await _active_memory_count(project.id) == 1
    assert await _draft_count(project.id) == 0


async def test_active_redaction_not_bypassable(mcp_client, access_user) -> None:
    client, _ = mcp_client
    project = await _make_project(access_user, key="rpk-active-sec")
    secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "content": f"active 接入：使用 token {secret} 调上游完成同步流程沉淀。",
            "writeback_mode": "active",
        },
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    memory = await _first_active_memory(project.id)
    assert secret not in memory.content


async def test_active_non_member_silent_skip(mcp_client) -> None:
    """active + 非成员 → accepted=false reason=not_member，HTTP 200，不写不抛。"""
    client, _ = mcp_client
    other = await sync_to_async(User.objects.create_user)(
        username="rpk-active-other", password="x"
    )
    project = await _make_project(other, key="rpk-active-nm")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "content": "非成员经 hook active 写共享记忆，应被静默跳过不阻断编码。",
            "writeback_mode": "active",
        },
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is False
    assert body["reason"] == "not_member"
    assert await _active_memory_count(project.id) == 0


async def test_active_quality_gate_rejects_low_quality(mcp_client, access_user) -> None:
    client, _ = mcp_client
    project = await _make_project(access_user, key="rpk-active-short")
    resp = await sync_to_async(client.post)(
        _URL,
        {"project_id": str(project.id), "content": "ok", "writeback_mode": "active"},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is False
    assert body["reason"] == "too_short"
    assert await _active_memory_count(project.id) == 0


async def test_active_target_research_appends_doc(mcp_client, access_user) -> None:
    """active + target=research + 成员 → RESEARCH ProjectDoc 正文新增 append 段。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="rpk-active-res")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "content": "调研沉淀：选型对比与最终决策记录在 RESEARCH 文档正文。",
            "writeback_mode": "active",
            "target": "research",
        },
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    snapshot = await _research_snapshot(project.id)
    assert "调研沉淀" in snapshot
    # research 路径不写记忆。
    assert await _active_memory_count(project.id) == 0


async def test_draft_default_path_not_regressed(mcp_client, access_user) -> None:
    """不带 writeback_mode（或 draft）→ 行为与现状一致（落 pending draft，HTTP 201）。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="rpk-draft-compat")
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "project_id": str(project.id),
            "content": "默认路径校验：不带 active 标记仍应落 pending draft 不回退。",
            "writeback_mode": "draft",
        },
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["accepted"] is True
    assert await _draft_count(project.id) == 1
    assert await _active_memory_count(project.id) == 0


# ===========================================================================
# #1a：不传 project_id，按 branch_name 反查唯一项目（通用规则不写死项目）
# ===========================================================================


async def _attach_work_item(project, work_item_id: int) -> None:
    from delivery.services import WorkItemIdentity, WorkItemService

    wi = await WorkItemService().upsert(
        WorkItemIdentity(
            feishu_project_key="rpk-wpk",
            work_item_type="story",
            work_item_id=work_item_id,
        ),
        source="feishu_webhook",
        fetch=False,
    )
    await ProjectService().attach_work_item(project_id=project.id, work_item=wi)


async def test_branch_name_resolves_project_without_project_id(
    mcp_client, access_user
) -> None:
    """只给 branch_name（无 project_id）→ 按分支反查唯一项目并落草稿。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="rpk-branch")
    await _attach_work_item(project, 7001)
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "branch_name": "feat/xxxx-m7001-login-rework",
            "content": "按当前分支自动定位项目并沉淀本次登录改造的关键方案决策。",
        },
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["accepted"] is True
    assert await _draft_count(project.id) == 1


async def test_unresolvable_branch_fail_soft(mcp_client, access_user) -> None:
    """分支无法唯一定位 → fail-soft：accepted=false reason=branch_unresolved，不入库不报错。"""
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(
        _URL,
        {
            "branch_name": "feat/no-such-branch-zzz",
            "content": "无法定位项目时应 fail-soft 跳过，既不入库也不报 5xx。",
        },
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is False
    assert body["reason"] == "branch_unresolved"


async def test_missing_project_id_and_branch_is_validation_error(
    mcp_client, access_user
) -> None:
    """既无 project_id 又无 branch_name → 校验失败（400）。"""
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(
        _URL,
        {"content": "两个定位键都不给，应被 serializer 校验拦下。"},
        format="json",
    )
    assert resp.status_code == 400
