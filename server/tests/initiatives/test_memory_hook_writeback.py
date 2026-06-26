"""IDE stop hook active 直写守护测试（HOOK-02，用户授权 accepted deviation 2026-06-26）。

覆盖 Task 1 服务层四道兜底：

- ``MemoryService.record_hook_writeback`` 成员调用 → 写 **active** ``ProjectMemory``
  （非 draft）+ 初始 revision + ``project.memory_created`` 审计；
- 非成员调用 → ``applied=False`` 不写任何表、**不抛**（静默跳过，绝不阻断编码）；
- 脱敏不可绕过（含密钥输入入库后无明文）；
- 撤销路径：active 记忆可经 ``supersede`` 置 superseded（审计可回滚）；
- ``ProjectDocService.append_research_note`` 成员调用 → RESEARCH 正文 append 新段
  （既有正文保留，非覆盖）+ ``project.research_note_appended`` 审计；非成员静默跳过。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from audit.models import AuditEvent
from initiatives.models import (
    DocType,
    ProjectDoc,
    ProjectMemory,
    ProjectMemoryRevision,
    ProjectMemoryStatus,
)
from initiatives.services import MemoryService, ProjectDocService, ProjectService
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@sync_to_async
def _make_user(username: str):
    return User.objects.create_user(username=username, password="x")


async def _make_project(created_by, key="hook-wb"):
    space = await sync_to_async(Space.objects.create)(name="S", feishu_project_key=f"{key}-sp")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=created_by
    )
    return project


@sync_to_async
def _active_memories(project_id):
    return list(
        ProjectMemory.objects.filter(
            project_id=project_id, status=ProjectMemoryStatus.ACTIVE
        )
    )


@sync_to_async
def _revision_count(memory_id) -> int:
    return ProjectMemoryRevision.objects.filter(memory_id=memory_id).count()


@sync_to_async
def _audit_count(action: str) -> int:
    return AuditEvent.objects.filter(action=action).count()


@sync_to_async
def _research_doc(project_id):
    return ProjectDoc.objects.filter(
        project_id=project_id, doc_type=DocType.RESEARCH
    ).first()


# ---- MemoryService.record_hook_writeback ----


async def test_member_active_write_creates_active_memory() -> None:
    owner = await _make_user("hook-owner")
    project = await _make_project(owner, key="hook-a")
    result = await MemoryService().record_hook_writeback(
        project_id=project.id,
        content="方案决策：登录态统一走 cookie-JWT 刷新，避免本地存储明文 token。",
        contributor=owner,
        initiated_by_user_id=owner.id,
    )
    assert result["applied"] is True
    assert result["memory_id"]
    memories = await _active_memories(project.id)
    assert len(memories) == 1
    # 初始 revision 快照（MEM-03 可追溯）。
    assert await _revision_count(memories[0].id) == 1
    # active 直写审计（可回滚依据）。
    assert await _audit_count("project.memory_created") >= 1


async def test_non_member_silent_skip_no_write_no_raise() -> None:
    owner = await _make_user("hook-owner2")
    stranger = await _make_user("hook-stranger")
    project = await _make_project(owner, key="hook-nm")
    result = await MemoryService().record_hook_writeback(
        project_id=project.id,
        content="外部人员尝试经 hook 写 active 的越权内容，应被静默跳过不写。",
        contributor=stranger,
    )
    assert result == {"applied": False, "reason": "not_member"}
    assert await _active_memories(project.id) == []


async def test_active_write_redaction_not_bypassable() -> None:
    owner = await _make_user("hook-secret")
    project = await _make_project(owner, key="hook-sec")
    secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    result = await MemoryService().record_hook_writeback(
        project_id=project.id,
        content=f"接入说明：使用 token {secret} 调用上游 API 完成同步流程。",
        contributor=owner,
    )
    assert result["applied"] is True
    memories = await _active_memories(project.id)
    assert secret not in memories[0].content


async def test_active_write_supersede_rollback() -> None:
    owner = await _make_user("hook-rb")
    project = await _make_project(owner, key="hook-rb")
    result = await MemoryService().record_hook_writeback(
        project_id=project.id,
        content="可回滚校验：本条 active 记忆应能经 supersede 撤销为 superseded。",
        contributor=owner,
    )
    memory_id = result["memory_id"]
    superseded = await MemoryService().supersede(memory_id=memory_id, actor=owner)
    assert superseded.status == ProjectMemoryStatus.SUPERSEDED


# ---- ProjectDocService.append_research_note ----


async def test_research_append_member_preserves_existing() -> None:
    owner = await _make_user("hook-res")
    project = await _make_project(owner, key="hook-res")
    svc = ProjectDocService()
    r1 = await svc.append_research_note(
        project_id=project.id,
        content="调研一：选型 redis 作为缓存层，权衡内存成本与延迟。",
        contributor=owner,
        initiated_by_user_id=owner.id,
    )
    assert r1["applied"] is True
    r2 = await svc.append_research_note(
        project_id=project.id,
        content="调研二：消息队列选 kafka，保证跨服务事件顺序与回放。",
        contributor=owner,
    )
    assert r2["applied"] is True
    doc = await _research_doc(project.id)
    assert doc is not None
    # append-only：两段都在，既有正文保留非覆盖。
    assert "redis 作为缓存层" in doc.last_synced_snapshot
    assert "kafka" in doc.last_synced_snapshot
    assert await _audit_count("project.research_note_appended") >= 2


async def test_research_append_non_member_silent_skip() -> None:
    owner = await _make_user("hook-res-owner")
    stranger = await _make_user("hook-res-stranger")
    project = await _make_project(owner, key="hook-res-nm")
    result = await ProjectDocService().append_research_note(
        project_id=project.id,
        content="非成员尝试写 RESEARCH 正文，应被静默跳过不写。",
        contributor=stranger,
    )
    assert result == {"applied": False, "reason": "not_member"}
    doc = await _research_doc(project.id)
    assert doc is None or "非成员" not in (doc.last_synced_snapshot or "")


async def test_research_append_redaction_not_bypassable() -> None:
    owner = await _make_user("hook-res-sec")
    project = await _make_project(owner, key="hook-res-sec")
    secret = "sk-ZYXWVUTSRQPONMLKJIHGFEDCBA9876543210"
    result = await ProjectDocService().append_research_note(
        project_id=project.id,
        content=f"调研接入：上游 token {secret} 用于鉴权，注意脱敏。",
        contributor=owner,
    )
    assert result["applied"] is True
    doc = await _research_doc(project.id)
    assert secret not in doc.last_synced_snapshot
