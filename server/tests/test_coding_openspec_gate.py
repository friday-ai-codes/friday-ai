"""AICodingNode 编码前置 openspec gate + env 注入测试（Phase 51-02，GATE-01/GATE-02）。

直接测 ``_apply_openspec_gate`` helper（独立可测）+ ``_run_repo_coding`` env 注入 +
下游阻断经真实 ``aadvance_coding_waves`` 传递闭包验证。覆盖：

- follow_openspec=False → 放行且**不查 SddSpec**（非 SDD/legacy 零回归命门）。
- follow_openspec=True + approved → 放行；未批准（无 spec / draft / in_review）→ 拦截
  reason=spec_not_approved 不放行。
- gate 校验异常 → fail-closed reason=gate_error，单仓隔离不波及其余仓。
- legacy/非 wave 短路（service/tasks_by_repo=None）→ 原样放行不查 spec。
- gate 拦截仓 failed → aadvance 传递闭包阻断下游 mark_blocked upstream_failed。
- approved SDD 仓 dispatch metadata 含 env_FRIDAY_TASK_FOLLOW_OPENSPEC=true；非 SDD 不含。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from delivery.models import (
    Artifact,
    ArtifactVersion,
    RepoCodingTask,
    RepoCodingTaskStatus,
    SddSpec,
    SddSpecStatus,
)
from delivery.services import RepoCodingTaskService
from repositories.models import Repository
from services.process_runtime.wave_progression import aadvance_coding_waves
from workflows.nodes.ai.coding import AICodingNode

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Fixtures / harness
# ---------------------------------------------------------------------------


async def _make_repo(*, sdd: bool = False) -> Repository:
    return await Repository.objects.acreate(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
        facets={"methodology": "SDD"} if sdd else {},
    )


async def _make_plan_version() -> ArtifactVersion:
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    av = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content={}, content_hash="h"
    )
    artifact.current_version = av
    await artifact.asave(update_fields=["current_version", "updated_at"])
    return av


async def _make_spec(pv: ArtifactVersion, repo: Repository, status: str) -> SddSpec:
    return await SddSpec.objects.acreate(artifact_version=pv, repository=repo, status=status)


def _log() -> Any:
    return MagicMock()


# ---------------------------------------------------------------------------
# gate helper 全态守护
# ---------------------------------------------------------------------------


async def test_gate_follow_openspec_false_passes_without_spec_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """follow_openspec=False 仓放行且不触发任何 SddSpec 查询（非 SDD 零回归命门）。"""
    pv = await _make_plan_version()
    repo = await _make_repo(sdd=False)
    rid = str(repo.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(pv, {rid: 0}, {})

    called = {"filter": False}
    orig_filter = SddSpec.objects.filter

    def _spy(*args: Any, **kwargs: Any):
        called["filter"] = True
        return orig_filter(*args, **kwargs)

    monkeypatch.setattr(SddSpec.objects, "filter", _spy)

    node = AICodingNode()
    passed, blocked = await node._apply_openspec_gate(
        repo_ids=[rid],
        repositories={rid: repo},
        tasks_by_repo=tasks,
        service=svc,
        log=_log(),
    )
    assert passed == [rid]
    assert blocked == []
    assert called["filter"] is False, "follow_openspec=False 不应触发 SddSpec 查询"


async def test_gate_approved_passes() -> None:
    """follow_openspec=True + approved spec → 放行（task 仍 pending 待 dispatch）。"""
    pv = await _make_plan_version()
    repo = await _make_repo(sdd=True)
    rid = str(repo.id)
    await _make_spec(pv, repo, SddSpecStatus.APPROVED)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(pv, {rid: 0}, {})

    node = AICodingNode()
    passed, blocked = await node._apply_openspec_gate(
        repo_ids=[rid], repositories={rid: repo}, tasks_by_repo=tasks, service=svc, log=_log()
    )
    assert passed == [rid]
    assert blocked == []
    reread = await RepoCodingTask.objects.aget(id=tasks[rid].id)
    assert reread.status == RepoCodingTaskStatus.PENDING


@pytest.mark.parametrize(
    "spec_status,expected",
    [
        (None, "missing"),
        (SddSpecStatus.DRAFT, "draft"),
        (SddSpecStatus.IN_REVIEW, "in_review"),
        (SddSpecStatus.IMPLEMENTED, "implemented"),
    ],
)
async def test_gate_unapproved_blocked(spec_status: Any, expected: str) -> None:
    """follow_openspec=True 未批准（无 spec / draft / in_review / implemented）→ 拦截不放行。"""
    pv = await _make_plan_version()
    repo = await _make_repo(sdd=True)
    rid = str(repo.id)
    if spec_status is not None:
        await _make_spec(pv, repo, spec_status)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(pv, {rid: 0}, {})

    node = AICodingNode()
    passed, blocked = await node._apply_openspec_gate(
        repo_ids=[rid], repositories={rid: repo}, tasks_by_repo=tasks, service=svc, log=_log()
    )
    assert passed == []
    assert len(blocked) == 1
    assert blocked[0]["repository_id"] == rid
    assert blocked[0]["error"] == "spec_not_approved"
    reread = await RepoCodingTask.objects.aget(id=tasks[rid].id)
    assert reread.status == RepoCodingTaskStatus.FAILED
    assert reread.error == {"reason": "spec_not_approved", "spec_status": expected}


async def test_gate_error_fail_closed_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """单仓 gate 校验异常 → fail-closed reason=gate_error，隔离不波及其余仓 dispatch。"""
    pv = await _make_plan_version()
    repo_sdd = await _make_repo(sdd=True)  # 查询将抛异常 → gate_error
    repo_plain = await _make_repo(sdd=False)  # follow_openspec=False → 放行不查
    rid_sdd, rid_plain = str(repo_sdd.id), str(repo_plain.id)
    svc = RepoCodingTaskService()
    tasks = await svc.create_tasks_for_plan(pv, {rid_sdd: 0, rid_plain: 0}, {})

    def _boom(*args: Any, **kwargs: Any):
        raise RuntimeError("spec query boom")

    monkeypatch.setattr(SddSpec.objects, "filter", _boom)

    node = AICodingNode()
    passed, blocked = await node._apply_openspec_gate(
        repo_ids=[rid_sdd, rid_plain],
        repositories={rid_sdd: repo_sdd, rid_plain: repo_plain},
        tasks_by_repo=tasks,
        service=svc,
        log=_log(),
    )
    # 非 SDD 仓不受异常波及，仍放行（隔离 + liveness）。
    assert passed == [rid_plain]
    assert len(blocked) == 1
    assert blocked[0]["repository_id"] == rid_sdd
    assert blocked[0]["error"] == "gate_error"
    reread = await RepoCodingTask.objects.aget(id=tasks[rid_sdd].id)
    assert reread.status == RepoCodingTaskStatus.FAILED
    assert reread.error == {"reason": "gate_error", "spec_status": "unknown"}


async def test_gate_legacy_short_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    """legacy/非 wave 模式（service/tasks_by_repo=None）→ 原样放行不查 SddSpec（零回归）。"""

    def _boom(*args: Any, **kwargs: Any):
        raise AssertionError("legacy 路径不应触发 SddSpec 查询")

    monkeypatch.setattr(SddSpec.objects, "filter", _boom)

    node = AICodingNode()
    # service=None
    passed, blocked = await node._apply_openspec_gate(
        repo_ids=["a", "b"],
        repositories={},
        tasks_by_repo={"a": object()},
        service=None,
        log=_log(),
    )
    assert passed == ["a", "b"]
    assert blocked == []
    # tasks_by_repo=None
    passed2, blocked2 = await node._apply_openspec_gate(
        repo_ids=["a"], repositories={}, tasks_by_repo=None, service=MagicMock(), log=_log()
    )
    assert passed2 == ["a"]
    assert blocked2 == []


async def test_gate_blocked_blocks_downstream() -> None:
    """gate 拦截仓 failed → aadvance 传递闭包阻断其 pending 下游（mark_blocked upstream_failed）。"""
    pv = await _make_plan_version()
    repo_up = await _make_repo(sdd=True)  # 无 spec → gate 拦截 failed
    repo_down = await _make_repo(sdd=False)  # 依赖 up，被阻断
    rid_up, rid_down = str(repo_up.id), str(repo_down.id)
    svc = RepoCodingTaskService()
    # down(wave1) depends_on up(wave0)
    tasks = await svc.create_tasks_for_plan(pv, {rid_up: 0, rid_down: 1}, {rid_down: [rid_up]})

    node = AICodingNode()
    passed, blocked = await node._apply_openspec_gate(
        repo_ids=[rid_up],
        repositories={rid_up: repo_up},
        tasks_by_repo=tasks,
        service=svc,
        log=_log(),
    )
    assert passed == []
    assert len(blocked) == 1
    # up 已 failed → aadvance 传递闭包阻断下游 down。
    result = await aadvance_coding_waves(pv.id, service=svc)
    assert result == {"all_terminal": True}
    down = await RepoCodingTask.objects.aget(id=tasks[rid_down].id)
    assert down.status == RepoCodingTaskStatus.FAILED
    assert down.error == {"reason": "upstream_failed", "upstream": [rid_up]}


# ---------------------------------------------------------------------------
# GATE-02：env 注入守护
# ---------------------------------------------------------------------------


@pytest.fixture
def _captured_dispatch(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """捕获 _run_repo_coding 构造的 DispatchTask（mock dispatcher + git token + session）。"""
    captured: list[Any] = []

    class _FakeDispatcher:
        async def dispatch(self, task: Any) -> None:
            captured.append(task)

    monkeypatch.setattr("runners.dispatcher.get_dispatcher", lambda: _FakeDispatcher())

    async def _token(*args: Any, **kwargs: Any) -> str:
        return ""

    monkeypatch.setattr("workflows.nodes.ai.coding.aresolve_git_token", _token)
    return captured


async def _run_dispatch(
    node: AICodingNode, repo: Repository, *, follow_openspec: bool
) -> dict[str, str]:
    """调用 _run_repo_coding 并返回捕获 DispatchTask 的 metadata。"""
    return await node._run_repo_coding(
        repository=repo,
        tasks=[{"id": "t1", "name": "T", "coding_instruction": "do"}],
        branch_name="feat/x",
        base_branch="main",
        global_context="",
        config={"timeout_seconds": 10},
        follow_openspec=follow_openspec,
    )


async def test_env_injection_sdd_repo(_captured_dispatch: list[Any]) -> None:
    """follow_openspec=True → dispatch metadata 含 env_FRIDAY_TASK_FOLLOW_OPENSPEC=true。"""
    repo = await _make_repo(sdd=True)
    node = AICodingNode()
    await _run_dispatch(node, repo, follow_openspec=True)
    assert len(_captured_dispatch) == 1
    metadata = _captured_dispatch[0].metadata
    assert metadata.get("env_FRIDAY_TASK_FOLLOW_OPENSPEC") == "true"


async def test_env_no_injection_non_sdd(_captured_dispatch: list[Any]) -> None:
    """follow_openspec=False（默认）→ metadata 不含 env_FRIDAY_TASK_FOLLOW_OPENSPEC 键（零回归）。"""
    repo = await _make_repo(sdd=False)
    node = AICodingNode()
    await _run_dispatch(node, repo, follow_openspec=False)
    assert len(_captured_dispatch) == 1
    metadata = _captured_dispatch[0].metadata
    assert "env_FRIDAY_TASK_FOLLOW_OPENSPEC" not in metadata
