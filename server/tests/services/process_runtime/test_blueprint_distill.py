"""总线条目 distill 沉淀（BUS-03，Phase 113-06）。

守以下几件事（编号即守护点）：

1. ⭐ **只产草案，绝不直写 active**：调 `MemoryDistiller.distill_to_draft` 一次，且
   `MemoryService.append` / `confirm_draft` / `MemoryDistiller.distill_hook_writeback`
   **零调用**（反向 mock 断言 —— 「AI 不覆盖人工」这条纪律是可证伪的）。
2. `proposed_by` 是**真实项目成员 User**（`session.created_by`），不是伪造 actor。
3. **kind 过滤**：`finding` / `question` / `dependency_claim` 不进 `conversation_text`。
4. **status 过滤**：`superseded` 条目不进。
5. ⭐ **解析不到成员即跳过**：`session.created_by` 为 None → 零调用且不抛。
6. ⭐ **best-effort 不反噬主链**：`distill_to_draft` 抛异常 → `merge()` 仍 `passed`
   且版本已落。
7. **两条出口都沉淀**：`passed` 与 `exhausted` 各调一次。
8. **无条目不调 LLM**：零条目 → `distill_to_draft` 零调用。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from test_blueprint_merge_stage import (  # noqa: E402 — 同目录 basedir，pytest 已插 sys.path
    _association,
    _make_locked_session,
    _repo_id,
    _repo_plan,
    _run_merge,
)

from delivery.models import ArtifactVersion, ConvergenceSession
from delivery.services.blueprint_context_service import BlueprintContextService
from initiatives.models import Project, ProjectMember
from initiatives.services.memory_distill import MemoryDistiller
from initiatives.services.memory_service import MemoryService
from projects.models import Space
from services.process_runtime.blueprint_merge import MAX_MERGE_ROUNDS, STAGE_STATE_KEY

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


class _DistillSpy:
    """`distill_to_draft` 替身：记录调用参数，可配置抛异常。"""

    def __init__(self, *, exc: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.exc = exc

    async def __call__(self, _self: Any = None, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return object()

    @property
    def text(self) -> str:
        return str(self.calls[0].get("conversation_text") or "") if self.calls else ""


class _ForbiddenCall:
    """「绝不该被调用」的替身：被调即计数（反向断言用）。"""

    def __init__(self) -> None:
        self.count = 0

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.count += 1
        return None


async def _make_member_user(username: str = "distiller"):
    return await get_user_model().objects.acreate(
        username=username, email=f"{username}@example.com"
    )


async def _make_project_with_member(user: Any) -> Project:
    space = await Space.objects.acreate(name=f"space-{user.username}")
    project = await Project.objects.acreate(space=space, name="p")
    await ProjectMember.objects.acreate(project=project, user=user)
    return project


async def _seed_entries(session: Any, project: Project, *specs: tuple[str, str, str, str]) -> None:
    """按 `(key, kind, status, detail)` 逐条写总线（唯一 writer 是 service）。"""
    service = BlueprintContextService()
    for key, kind, status, detail in specs:
        entry = await service.append_entry(
            session=session,
            key=key,
            kind=kind,
            content={"conclusion": detail},
            project_id=project.id,
        )
        if status != "active":
            await type(entry).objects.filter(id=entry.id).aupdate(status=status)


_VALUABLE = (
    ("decision:th-1", "decision", "active", "决定用 REST 而非 GraphQL"),
    ("contract:listUsers", "contract", "active", "listUsers 契约由 A 仓提供"),
    ("repo:a.api_surface", "api_surface", "active", "A 仓暴露 GET /users"),
)
_NOISE = (
    ("repo:a.finding-1", "finding", "active", "这是过程态调研发现"),
    ("question:q-1", "question", "active", "这是待澄清问题"),
    ("dependency:a->b", "dependency_claim", "active", "这是依赖等待声明"),
)


async def _prepared_session(*, with_user: bool = True, exhausted: bool = False, noise: bool = True):
    """建好 artifact/会话/项目/成员/总线条目的完整样本。"""
    user = await _make_member_user(f"u{_repo_id('x')[-6:]}")
    project = await _make_project_with_member(user)
    if exhausted:
        rid = _repo_id("a")
        session, artifact = await _make_locked_session(_association(rid, citations=[]))
        await ConvergenceSession.objects.filter(id=session.id).aupdate(
            stage_state={STAGE_STATE_KEY: {"count": MAX_MERGE_ROUNDS}}
        )
    else:
        rid = _repo_id("a")
        session, artifact = await _make_locked_session(_association(rid))
    if with_user:
        await ConvergenceSession.objects.filter(id=session.id).aupdate(created_by=user)
    session = await ConvergenceSession.objects.aget(id=session.id)
    specs = _VALUABLE + (_NOISE if noise else ())
    await _seed_entries(session, project, *specs)
    return session, artifact, rid, user, project


def _patch_distill(monkeypatch: pytest.MonkeyPatch, spy: _DistillSpy) -> None:
    async def _call(_self: Any, **kwargs: Any) -> Any:
        return await spy(**kwargs)

    monkeypatch.setattr(MemoryDistiller, "distill_to_draft", _call)


# ═══════════════════════════════════════════════════════════════════════════
# 1-4. 产草案不直写 active / proposed_by 真实成员 / kind 与 status 过滤
# ═══════════════════════════════════════════════════════════════════════════


async def test_valuable_entries_produce_draft_and_never_touch_active(
    monkeypatch: pytest.MonkeyPatch,
):
    """⭐ 只调 `distill_to_draft`；`append` / `confirm_draft` / hook 精炼零调用。"""
    spy = _DistillSpy()
    _patch_distill(monkeypatch, spy)
    forbidden_append, forbidden_confirm, forbidden_hook = (
        _ForbiddenCall(),
        _ForbiddenCall(),
        _ForbiddenCall(),
    )
    monkeypatch.setattr(MemoryService, "append", forbidden_append)
    monkeypatch.setattr(MemoryService, "confirm_draft", forbidden_confirm)
    monkeypatch.setattr(MemoryDistiller, "distill_hook_writeback", forbidden_hook)

    session, _artifact, rid, user, project = await _prepared_session()
    result, _s = await _run_merge(session, plans={rid: _repo_plan(rid)})

    assert result["validation_status"] == "passed", result
    assert len(spy.calls) == 1, "沉淀必须恰好走一次草案链"
    call = spy.calls[0]
    assert call["proposed_by"].id == user.id, "proposed_by 必须是真实项目成员 User"
    assert str(call["project_id"]) == str(project.id)
    assert call["initiated_by_user_id"] == str(user.id)
    assert forbidden_append.count == 0, "append 直写 active 会覆盖人工内容"
    assert forbidden_confirm.count == 0, "confirm_draft 是人工动作入口，AI 绝不许调"
    assert forbidden_hook.count == 0, "distill_hook_writeback 不产草案，不适用于总线沉淀"


async def test_conversation_text_only_carries_valuable_kinds(monkeypatch: pytest.MonkeyPatch):
    """kind 过滤：三类有价值条目进文本，`finding`/`question`/`dependency_claim` 不进。"""
    spy = _DistillSpy()
    _patch_distill(monkeypatch, spy)

    session, _artifact, rid, _user, _project = await _prepared_session()
    await _run_merge(session, plans={rid: _repo_plan(rid)})

    assert spy.calls
    text = spy.text
    for _key, _kind, _status, detail in _VALUABLE:
        assert detail in text
    for _key, _kind, _status, detail in _NOISE:
        assert detail not in text, "过程态条目进项目级记忆只会污染它"


async def test_superseded_entries_are_excluded(monkeypatch: pytest.MonkeyPatch):
    """status 过滤：`superseded` 条目不进文本。"""
    spy = _DistillSpy()
    _patch_distill(monkeypatch, spy)

    user = await _make_member_user("u-superseded")
    project = await _make_project_with_member(user)
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid))
    await ConvergenceSession.objects.filter(id=session.id).aupdate(created_by=user)
    session = await ConvergenceSession.objects.aget(id=session.id)
    await _seed_entries(
        session,
        project,
        ("decision:th-1", "decision", "active", "生效中的决策"),
        ("decision:th-2", "decision", "superseded", "已被废弃的决策"),
    )

    await _run_merge(session, plans={rid: _repo_plan(rid)})

    assert spy.calls
    assert "生效中的决策" in spy.text
    assert "已被废弃的决策" not in spy.text


# ═══════════════════════════════════════════════════════════════════════════
# 5-6. 解析不到成员即跳过 / best-effort 不反噬主链
# ═══════════════════════════════════════════════════════════════════════════


async def test_missing_session_user_skips_distill_without_faking_actor(
    monkeypatch: pytest.MonkeyPatch,
):
    """⭐ `session.created_by` 为 None → 零调用且不抛（绝不伪造 proposed_by）。"""
    spy = _DistillSpy()
    _patch_distill(monkeypatch, spy)

    session, _artifact, rid, _user, _project = await _prepared_session(with_user=False)
    result, _s = await _run_merge(session, plans={rid: _repo_plan(rid)})

    assert result["validation_status"] == "passed", result
    assert spy.calls == [], "解析不到真实成员时必须跳过沉淀，不伪造 actor"


async def test_distill_failure_does_not_break_merge(monkeypatch: pytest.MonkeyPatch):
    """⭐ 沉淀抛异常 → merge 仍 `passed` 且版本已落（best-effort 绝不反噬主链）。"""
    spy = _DistillSpy(exc=RuntimeError("distill boom"))
    _patch_distill(monkeypatch, spy)

    session, artifact, rid, _user, _project = await _prepared_session()
    before = await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount()

    result, _s = await _run_merge(session, plans={rid: _repo_plan(rid)})

    assert result["validation_status"] == "passed", result
    assert result["artifact_version_id"]
    assert await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount() == before + 1
    assert len(spy.calls) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 7-8. 两条出口都沉淀 / 无条目不调 LLM
# ═══════════════════════════════════════════════════════════════════════════


async def test_exhausted_exit_also_distills(monkeypatch: pytest.MonkeyPatch):
    """超界出口同样沉淀一次（会话到此已产出完整蓝图）。"""
    spy = _DistillSpy()
    _patch_distill(monkeypatch, spy)

    session, _artifact, rid, _user, _project = await _prepared_session(exhausted=True)
    result, _s = await _run_merge(session, plans={rid: _repo_plan(rid)})

    assert result["validation_status"] == "exhausted", result
    assert len(spy.calls) == 1


async def test_retry_exit_does_not_distill(monkeypatch: pytest.MonkeyPatch):
    """有界回退中途不沉淀：会话还没定稿，此时产草案是噪声。"""
    spy = _DistillSpy()
    _patch_distill(monkeypatch, spy)

    user = await _make_member_user("u-retry")
    project = await _make_project_with_member(user)
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid, citations=[]))
    await ConvergenceSession.objects.filter(id=session.id).aupdate(created_by=user)
    session = await ConvergenceSession.objects.aget(id=session.id)
    await _seed_entries(session, project, *_VALUABLE)

    result, _s = await _run_merge(session, plans={rid: _repo_plan(rid)})

    assert result["validation_status"] == "retry", result
    assert spy.calls == []


async def test_no_entries_means_no_llm_call(monkeypatch: pytest.MonkeyPatch):
    """零条目 → `distill_to_draft` 零调用（不为空会话烧一次 LLM）。"""
    spy = _DistillSpy()
    _patch_distill(monkeypatch, spy)

    user = await _make_member_user("u-empty")
    await _make_project_with_member(user)
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid))
    await ConvergenceSession.objects.filter(id=session.id).aupdate(created_by=user)
    session = await ConvergenceSession.objects.aget(id=session.id)

    result, _s = await _run_merge(session, plans={rid: _repo_plan(rid)})

    assert result["validation_status"] == "passed", result
    assert spy.calls == []


async def test_entries_without_project_binding_skip_distill(monkeypatch: pytest.MonkeyPatch):
    """总线条目没有项目归属 → 跳过沉淀（不伪造归属去撞成员校验）。"""
    spy = _DistillSpy()
    _patch_distill(monkeypatch, spy)

    user = await _make_member_user("u-noproj")
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid))
    await ConvergenceSession.objects.filter(id=session.id).aupdate(created_by=user)
    session = await ConvergenceSession.objects.aget(id=session.id)
    service = BlueprintContextService()
    await service.append_entry(
        session=session, key="decision:th-1", kind="decision", content={"conclusion": "无归属"}
    )

    result, _s = await _run_merge(session, plans={rid: _repo_plan(rid)})

    assert result["validation_status"] == "passed", result
    assert spy.calls == []


async def test_distill_text_is_bounded(monkeypatch: pytest.MonkeyPatch):
    """会话文本有界截断（条目无界会把 prompt 撑爆）。"""
    from services.process_runtime.blueprint_merge import _MAX_DISTILL_CHARS, _distill_text

    entries = [
        {"key": f"decision:{i}", "kind": "decision", "content": {"conclusion": "x" * 500}}
        for i in range(100)
    ]
    text = _distill_text(entries)
    assert len(text) <= _MAX_DISTILL_CHARS
    assert json.dumps(text)  # 可序列化（无控制字符）
    assert await sync_to_async(lambda: True)()
