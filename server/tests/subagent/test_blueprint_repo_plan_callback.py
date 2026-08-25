"""blueprint_repo_plan 容器回调 → repo_plan 段落 PartialPlan.content（Phase 113-03，FLOW-05）。

守七件事：

1. ⭐ **P-4 四链两两互斥**：plan 容器 session 跑 `_is_blueprint_research` **必须为 False**
   （否则被调研解析器抢走并因缺 `fitness.verdict` 判失败）；反向亦然，另含
   `_is_plan_research` / `_is_repo_verify` 的互斥矩阵。
2. **成功路径**：结构化 output 的 `repo_plan` 落 `PartialPlan.content["repo_plan"]`，task → done。
3. ⭐ **P-1 读-合并-写**：预置含 `fitness.verdict="suitable"` + `findings` + §7 五键的
   PartialPlan → 写入 repo_plan 后 `acollect_fitness(session)[repo_id]["verdict"]` 仍为
   `suitable`，且 findings 与 §7 五键仍在（**未吃掉 112 产物**）。
4. **文本路径**：output 只有 ```json 围栏时同样解析成功。
5. **有界重试**：非法 repo_plan 第 1 次 → task 变 `stale` 并立即重派；
   超 `MAX_REPO_PLAN_ATTEMPTS`（第 3 个 plan 容器）→ 合法 degraded RepoPlan
   + 阻塞 `BlueprintThread(ai_clarification, return_stage="repo_plan")`，且不计 ready。
6. **失败回调**：容器失败同样有界重派，耗尽后显式 degraded，回调仍返 200。
7. **call_source 显式**：本链容器 LLM 来源为 `blueprint_repo_plan`，不回退 sdk_agent_task。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.models import AgentSession
from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintThread,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
    ThreadKind,
)
from repositories.models import Repository
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)

_PATCHES = (
    patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
    patch("subagent.api.callbacks._schedule_workflow_resume"),
    patch("subagent.api.callbacks._schedule_agent_session_resume"),
)
# barrier 会去调 blueprint_resume 推进 engine——本文件只测回调落库语义，续驱另有测试覆盖。
_NO_BARRIER = patch(
    "subagent.api.callbacks._trigger_blueprint_repo_plan_barrier", new_callable=AsyncMock
)

_SUITABLE_CONTENT = {
    "research_summary": "阶段 1 结论",
    "proposed_changes": [],
    "candidate_files": [],
    "api_contracts_exposed": [],
    "dependencies_on_other_repos": [],
    "fitness": {"verdict": "suitable", "reasons": ["已有骨架"], "citations": ["src/a.ts"]},
    "role_suggestion": "direct",
    "responsibility": "承载专项学习页",
    "findings": [{"title": "已有路由", "detail": "已注册 /study", "citations": ["src/r.ts"]}],
}


def _repo_plan(**overrides) -> dict:
    section: dict[str, Any] = {
        "repository_id": "will-be-overwritten",
        "role": "direct",
        "impl_items": [
            {
                "item_id": "it_1",
                "title": "新增入口",
                "change_type": "create",
                "how": "加卡片",
                "files_touched": ["src/pages/study/index.vue"],
                "depends_on": [],
            }
        ],
        "risks": [{"block_id": "blk_r", "text": "首屏影响"}],
    }
    section.update(overrides)
    return section


def _plan_output(section: dict | None = None, **overrides) -> dict:
    """260818-pt8 D-01：唯一权威渠道 output.mcp_result（顶层键 repo_plan）。"""
    return {
        "mcp_result": {"repo_plan": section if section is not None else _repo_plan(**overrides)}
    }


async def _setup(
    *,
    source: str = "blueprint_repo_plan",
    status: str | None = None,
    task_type: Any = None,
    session_prefix: str = "bp-plan",
    with_artifact: bool = False,
    extra_containers: int = 0,
):
    session_kwargs: dict[str, Any] = {}
    artifact = None
    if with_artifact:
        artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
        version = await ArtifactVersion.objects.acreate(
            artifact=artifact, version_no=1, content={"repo_associations": []}
        )
        artifact.current_version = version
        await artifact.asave(update_fields=["current_version"])
        session_kwargs["current_artifact_version_id"] = version.id

    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_plan",
        **session_kwargs,
    )
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://example.com/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
    )
    task = await RepoResearchTask.objects.acreate(
        session=session,
        repository=repo,
        status=status or RepoResearchTaskStatus.RUNNING,
        routed_confidence="high",
    )
    agent = await AgentSession.objects.acreate(session_id=f"agent-{uuid.uuid4().hex[:8]}")
    sub = await SubAgentSession.objects.acreate(
        session_id=f"{session_prefix}-{task.id.hex[:12]}-{uuid.uuid4().hex[:6]}",
        main_session=agent,
        repo_url=repo.git_url,
        task_type=task_type or SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.RUNNING,
        last_output={
            "source": source,
            "blueprint_session_id": str(session.id),
            "research_task_id": str(task.id),
            "repository_id": str(repo.id),
        },
    )
    # 模拟「本 task 之前已起过 N 个 plan 容器」（有界重试的计数源是 session_id 前缀）
    for _ in range(extra_containers):
        prior_agent = await AgentSession.objects.acreate(session_id=f"agent-{uuid.uuid4().hex[:8]}")
        await SubAgentSession.objects.acreate(
            session_id=f"bp-plan-{task.id.hex[:12]}-{uuid.uuid4().hex[:6]}",
            main_session=prior_agent,
            repo_url=repo.git_url,
            task_type=SubAgentSession.TaskType.PLAN,
            status=SubAgentSession.Status.ERROR,
            last_output={"source": "blueprint_repo_plan"},
        )
    return session, repo, task, sub, artifact


def _log() -> Any:
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None
    log.warning = lambda *a, **kw: None
    return log


# ===========================================================================
# 1. 四链两两互斥（P-4）
# ===========================================================================


async def test_four_route_predicates_are_mutually_exclusive() -> None:
    """⭐ P-4：plan 容器 session 绝不被调研/方案调研/深验三链认领，反向亦然。"""
    from subagent.api.callbacks import (
        _is_blueprint_repo_plan,
        _is_blueprint_research,
        _is_plan_research,
        _is_repo_verify,
    )

    _s, _r, _t, plan_sub, _a = await _setup()
    assert _is_blueprint_repo_plan(plan_sub) is True
    assert _is_blueprint_research(plan_sub) is False
    assert _is_plan_research(plan_sub) is False
    assert _is_repo_verify(plan_sub) is False

    _s2, _r2, _t2, research_sub, _a2 = await _setup(
        source="blueprint_research", session_prefix="bp-research"
    )
    assert _is_blueprint_repo_plan(research_sub) is False
    assert _is_blueprint_research(research_sub) is True

    _s3, _r3, _t3, legacy_sub, _a3 = await _setup(source="plan_research")
    assert _is_blueprint_repo_plan(legacy_sub) is False
    assert _is_plan_research(legacy_sub) is True

    _s4, _r4, _t4, verify_sub, _a4 = await _setup(
        source="repo_verify", task_type=SubAgentSession.TaskType.REPO_VERIFY
    )
    assert _is_blueprint_repo_plan(verify_sub) is False
    assert _is_repo_verify(verify_sub) is True


async def test_research_session_not_hijacked_by_plan_chain() -> None:
    """source == blueprint_research 的 session 不会被第四链改写（既有链零扰动）。"""
    from subagent.api.callbacks import _handle_blueprint_repo_plan_completion

    _s, _r, task, sub, _a = await _setup(source="blueprint_research", session_prefix="bp-research")
    await _handle_blueprint_repo_plan_completion(sub, {"output": _plan_output()}, _log())

    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.RUNNING
    assert await PartialPlan.objects.filter(research_task=task).acount() == 0


# ===========================================================================
# 2/4. 成功路径（结构化 + 文本围栏）
# ===========================================================================


async def test_structured_repo_plan_recorded() -> None:
    """结构化 output → content["repo_plan"]["impl_items"] 就位，task → done。"""
    _s, repo, task, sub, _a = await _setup()
    payload = {"result_type": "text", "output": _plan_output()}
    from subagent.api.callbacks import _handle_completed

    with (
        _PATCHES[0],
        _PATCHES[1],
        _PATCHES[2],
        _NO_BARRIER,
        patch(
            "services.process_runtime.blueprint_research_adapter.BlueprintResearchAdapter.dispatch",
            new_callable=AsyncMock,
            return_value={"dispatched": 1},
        ),
    ):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.DONE

    partial = await PartialPlan.objects.filter(research_task=task, valid=True).afirst()
    assert partial is not None
    section = partial.content["repo_plan"]
    assert len(section["impl_items"]) == 1
    assert section["impl_items"][0]["change_type"] == "create"
    # repository_id 由服务端权威写入（不采信容器上报值）
    assert section["repository_id"] == str(repo.id)


def test_parse_normalizes_missing_block_id_without_losing_impl_items() -> None:
    """缺风险块锚点可确定性修复，完整实现项不得被降级清空。"""
    from subagent.api.callbacks import _parse_blueprint_repo_plan

    raw = _repo_plan(risks=[{"type": "paragraph", "text": "首屏影响"}])
    section, error = _parse_blueprint_repo_plan(_plan_output(raw))
    section_again, error_again = _parse_blueprint_repo_plan(_plan_output(section))

    assert error == error_again == ""
    assert section is not None and section_again is not None
    assert section["impl_items"] == raw["impl_items"]
    assert section["risks"][0]["block_id"] == "blk_repo_plan_risks_will-be-_0"
    assert section_again == section


async def test_text_fenced_repo_plan_rejected() -> None:
    """260818-pt8 D-02：output 只有 ```json 围栏（无 mcp_result）→ 判不合格走重试，绝不落库。"""
    import json

    _s, _r, task, sub, _a = await _setup()
    fenced = "```json\n" + json.dumps({"repo_plan": _repo_plan()}) + "\n```"
    payload = {"result_type": "text", "output": {"text": fenced}}
    from subagent.api.callbacks import _handle_completed

    with (
        _PATCHES[0],
        _PATCHES[1],
        _PATCHES[2],
        _NO_BARRIER,
        patch(
            "services.process_runtime.blueprint_research_adapter.BlueprintResearchAdapter.dispatch",
            new_callable=AsyncMock,
            return_value={"dispatched": 1},
        ),
    ):
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.STALE
    assert await PartialPlan.objects.filter(research_task=task).acount() == 0


# ===========================================================================
# 3. P-1：read-merge-write 未吃掉 112 的 fitness / findings / §7 五键
# ===========================================================================


async def test_repo_plan_write_preserves_stage1_fitness() -> None:
    """⭐ P-1：写入 repo_plan 后 acollect_fitness 的 verdict 与 findings 仍在。"""
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter
    from subagent.api.callbacks import _handle_blueprint_repo_plan_completion

    session, repo, task, sub, _a = await _setup()
    await PartialPlan.objects.acreate(
        research_task=task,
        content={**_SUITABLE_CONTENT, "repository_id": str(repo.id)},
        content_hash="x" * 8,
        valid=True,
    )

    adapter = BlueprintResearchAdapter()
    before = await adapter.acollect_fitness(session)
    assert before[str(repo.id)]["verdict"] == "suitable"

    with _NO_BARRIER:
        await _handle_blueprint_repo_plan_completion(sub, {"output": _plan_output()}, _log())

    after = await adapter.acollect_fitness(session)
    assert after[str(repo.id)]["verdict"] == "suitable"
    assert after[str(repo.id)]["findings"] == _SUITABLE_CONTENT["findings"]

    latest = await (
        PartialPlan.objects.filter(research_task=task, valid=True).order_by("-created_at").afirst()
    )
    assert latest is not None
    content = latest.content
    assert content["repo_plan"]["impl_items"]
    # §7 五键 + findings 一并保留（浅合并，不是整体覆写）
    for key in (
        "research_summary",
        "proposed_changes",
        "candidate_files",
        "api_contracts_exposed",
        "dependencies_on_other_repos",
        "findings",
        "role_suggestion",
        "responsibility",
    ):
        assert key in content, key
    # 历史行不被覆盖（一仓多条，只是取最新作 canonical）
    assert await PartialPlan.objects.filter(research_task=task).acount() == 2


# ===========================================================================
# 5. 有界重试
# ===========================================================================


async def test_invalid_repo_plan_first_round_goes_stale() -> None:
    """非法 repo_plan 第 1 轮 → task 变 stale 触发重跑，且不落非法 content。"""
    from subagent.api.callbacks import _handle_blueprint_repo_plan_completion

    _s, _r, task, sub, _a = await _setup()
    bad = _repo_plan()
    bad.pop("impl_items")

    with (
        _NO_BARRIER,
        patch(
            "services.process_runtime.blueprint_research_adapter.BlueprintResearchAdapter.dispatch",
            new_callable=AsyncMock,
            return_value={"dispatched": 1},
        ) as dispatch,
    ):
        await _handle_blueprint_repo_plan_completion(sub, {"output": _plan_output(bad)}, _log())

    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.STALE
    assert task.error.get("reason") == "repo_plan_invalid_retrying"
    assert await PartialPlan.objects.filter(research_task=task).acount() == 0
    dispatch.assert_awaited_once()


async def test_invalid_repo_plan_beyond_bound_records_degraded_and_opens_clarification() -> None:
    """超 MAX_REPO_PLAN_ATTEMPTS → done + degraded + 非阻塞澄清线程。"""
    from subagent.api.callbacks import _handle_blueprint_repo_plan_completion

    _s, _r, task, sub, artifact = await _setup(with_artifact=True, extra_containers=2)
    bad = _repo_plan(impl_items=[{"item_id": "it_1", "title": "t"}])  # 缺 change_type / how

    with _NO_BARRIER:
        await _handle_blueprint_repo_plan_completion(sub, {"output": _plan_output(bad)}, _log())

    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.STALE
    partial = await PartialPlan.objects.filter(research_task=task, valid=True).afirst()
    assert partial is not None
    assert partial.content["repo_plan"]["impl_items"] == []
    assert partial.content["repo_plan"]["risks"]
    assert partial.content["repo_plan"]["delivery_status"] == "degraded"

    thread = await BlueprintThread.objects.filter(
        artifact=artifact, kind=ThreadKind.AI_CLARIFICATION
    ).afirst()
    assert thread is not None
    assert thread.blocking is True
    # B3：漏传 return_stage 会让阶段 2 的澄清恢复退回阶段 1
    assert thread.return_stage == "repo_plan"


async def test_free_text_output_is_invalid() -> None:
    """纯自由文本（无 JSON）→ 判不合格走重试分支，绝不落 content。"""
    from subagent.api.callbacks import _handle_blueprint_repo_plan_completion

    _s, _r, task, sub, _a = await _setup()
    with (
        _NO_BARRIER,
        patch(
            "services.process_runtime.blueprint_research_adapter.BlueprintResearchAdapter.dispatch",
            new_callable=AsyncMock,
            return_value={"dispatched": 1},
        ),
    ):
        await _handle_blueprint_repo_plan_completion(
            sub, {"output": {"text": "我看了一圈，方案大概是加个入口。"}}, _log()
        )

    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.STALE
    assert await PartialPlan.objects.filter(research_task=task).acount() == 0


def test_parse_rejects_bad_shapes() -> None:
    """解析器对各类残缺形状一律返回 (None, err)，err 非空可进 mark_failed。"""
    from subagent.api.callbacks import _parse_blueprint_repo_plan

    for payload in (
        None,
        {},
        {"mcp_result": {"repo_plan": "not-a-dict"}},
        {"text": "no json"},
        {"repo_plan": _repo_plan()},  # 无 mcp_result 的旧文本渠道一律拒绝
    ):
        section, err = _parse_blueprint_repo_plan(payload)
        assert section is None
        assert isinstance(err, str) and err

    section, err = _parse_blueprint_repo_plan({"mcp_result": {"repo_plan": _repo_plan()}})
    assert section is not None and err == ""


# ===========================================================================
# 6/7. 失败回调 + call_source
# ===========================================================================


async def test_failure_callback_marks_container_failed() -> None:
    """首轮容器瞬时失败 → stale + 自动重派，回调仍返 200。"""
    from subagent.api.callbacks import _handle_failed

    _s, _r, task, sub, _a = await _setup()
    with (
        patch("subagent.api.callbacks._update_coding_session_on_fail", new_callable=AsyncMock),
        patch("subagent.api.callbacks._send_failure_notification", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
        _NO_BARRIER,
        patch(
            "services.process_runtime.blueprint_research_adapter.BlueprintResearchAdapter.dispatch",
            new_callable=AsyncMock,
            return_value={"dispatched": 1},
        ) as dispatch,
    ):
        resp = await _handle_failed(sub, {"error": "容器超时"}, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.STALE
    assert task.error.get("reason") == "container_failed_retrying"
    dispatch.assert_awaited_once()


async def test_container_failure_exhaustion_records_degraded_plan_and_advances() -> None:
    """第 3 个容器仍失败 → stale + degraded + 阻塞未决线程，不把整个流程打成 failed。"""
    from subagent.api.callbacks import _handle_failed

    session, repo, task, sub, artifact = await _setup(
        with_artifact=True,
        extra_containers=2,
    )
    with (
        patch("subagent.api.callbacks._update_coding_session_on_fail", new_callable=AsyncMock),
        patch("subagent.api.callbacks._send_failure_notification", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
        _NO_BARRIER,
    ):
        resp = await _handle_failed(sub, {"error": "socket closed"}, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.STALE
    partial = await PartialPlan.objects.filter(research_task=task, valid=True).afirst()
    assert partial is not None
    section = partial.content["repo_plan"]
    assert section["repository_id"] == str(repo.id)
    assert section["impl_items"] == []
    assert section["risks"]
    assert section["delivery_status"] == "degraded"
    thread = await BlueprintThread.objects.filter(
        artifact=artifact,
        kind=ThreadKind.AI_CLARIFICATION,
    ).afirst()
    assert thread is not None
    assert thread.blocking is True


async def test_completion_exception_swallowed_returns_200() -> None:
    """第四链完成钩子异常 → swallow，回调仍返 200（永不阻塞主流程）。"""
    from subagent.api.callbacks import _handle_completed

    _s, _r, _t, sub, _a = await _setup()

    async def _boom(*a, **kw):
        raise RuntimeError("downstream failure")

    with (
        _PATCHES[0],
        _PATCHES[1],
        _PATCHES[2],
        patch("subagent.api.callbacks._handle_blueprint_repo_plan_completion", new=_boom),
    ):
        resp = await _handle_completed(sub, {"result_type": "text", "output": {}}, _log())

    assert resp.status_code == 200


async def test_derive_call_source_blueprint_repo_plan() -> None:
    """last_output.source == blueprint_repo_plan → blueprint_repo_plan（不回退 sdk_agent_task）。"""
    from subagent.api.callbacks import _derive_container_call_source

    _s, _r, _t, sub, _a = await _setup()
    assert _derive_container_call_source(sub) == "blueprint_repo_plan"

    _s2, _r2, _t2, research_sub, _a2 = await _setup(
        source="blueprint_research", session_prefix="bp-research"
    )
    assert _derive_container_call_source(research_sub) == "blueprint_repo_research"


async def test_terminal_task_is_noop() -> None:
    """已 done 的 task 再回调 → 反查返 None，PartialPlan 行数不变（重投递幂等）。"""
    from subagent.api.callbacks import (
        _aload_blueprint_plan_task,
        _handle_blueprint_repo_plan_completion,
    )

    _s, _r, task, sub, _a = await _setup(status=RepoResearchTaskStatus.DONE)
    loaded, _bp = await _aload_blueprint_plan_task(sub)
    assert loaded is None

    with _NO_BARRIER:
        await _handle_blueprint_repo_plan_completion(sub, {"output": _plan_output()}, _log())
    assert await PartialPlan.objects.filter(research_task=task).acount() == 0
