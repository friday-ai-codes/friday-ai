"""blueprint_research 容器回调 → fitness 落 PartialPlan.content 测试（Phase 112-04，FLOW-02）。

守七件事：

1. **三链互斥**：PLAN 任务下 `blueprint_research` 与 `plan_research` 判定互不侵占。
2. **成功路径**：结构化 output 的 `fitness` / `role_suggestion` / `responsibility` /
   `findings` 落 `PartialPlan.content`，task → done。
3. **文本路径**：只有 ```json 围栏文本时同样解析成功。
4. **不可解析即失败**：缺 `fitness.verdict` → task failed + `empty_or_unparseable_result`，
   且**不产生** PartialPlan 行（绝不把编造结论落进蓝图投影数据）。
5. **枚举归一**：非法 `verdict` 判不可解析；非法 `role_suggestion` 回落保守的 `direct`。
6. **幂等**：已终态 task 再回调 no-op，PartialPlan 行数不变。
7. **call_source 显式**：本链容器 LLM 来源为 `blueprint_repo_research`，不回退 sdk_agent_task。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.models import AgentSession
from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from repositories.models import Repository
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)

_PATCHES = (
    patch("subagent.api.callbacks._update_coding_session_on_complete", new_callable=AsyncMock),
    patch("subagent.api.callbacks._schedule_workflow_resume"),
    patch("subagent.api.callbacks._schedule_agent_session_resume"),
)


async def _setup(*, source: str = "blueprint_research", status: str | None = None):
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_research",
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
        session_id=f"bp-research-{uuid.uuid4().hex[:8]}",
        main_session=agent,
        repo_url=repo.git_url,
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.RUNNING,
        last_output={
            "source": source,
            "blueprint_session_id": str(session.id),
            "research_task_id": str(task.id),
            "repository_id": str(repo.id),
        },
    )
    return session, repo, task, sub


def _log() -> Any:
    log = AsyncMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None
    log.warning = lambda *a, **kw: None
    return log


def _fitness_output(**overrides) -> dict:
    payload = {
        "fitness": {
            "verdict": "suitable",
            "reasons": ["本仓已有专项学习页骨架"],
            "citations": ["src/pages/study/index.vue"],
        },
        "role_suggestion": "direct",
        "responsibility": "承载专项学习页与练习入口",
        "findings": [
            {
                "title": "已有学习页路由",
                "detail": "src/router 下已注册 /study",
                "citations": ["src/router/index.ts"],
            }
        ],
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# 1. 三链互斥
# ===========================================================================


async def test_route_predicates_are_mutually_exclusive() -> None:
    """blueprint_research 与 plan_research 判定互斥（同为 PLAN 任务，只靠 source 区分）。"""
    from subagent.api.callbacks import _is_blueprint_research, _is_plan_research

    _s, _r, _t, bp_sub = await _setup()
    assert _is_blueprint_research(bp_sub) is True
    assert _is_plan_research(bp_sub) is False

    _s2, _r2, _t2, plan_sub = await _setup(source="plan_research")
    assert _is_blueprint_research(plan_sub) is False
    assert _is_plan_research(plan_sub) is True


async def test_plan_research_session_not_hijacked() -> None:
    """source == plan_research 的 session 不会被蓝图链改写（既有链零扰动）。"""
    from subagent.api.callbacks import _handle_blueprint_research_completion

    _s, _r, task, sub = await _setup(source="plan_research")
    await _handle_blueprint_research_completion(sub, {"output": _fitness_output()}, _log())

    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.RUNNING
    assert await PartialPlan.objects.filter(research_task=task).acount() == 0


# ===========================================================================
# 2/3. 成功路径（结构化 + 文本围栏）
# ===========================================================================


async def test_structured_fitness_recorded_to_partial_plan() -> None:
    """结构化 output → PartialPlan.content 含 fitness/role/responsibility/findings，task done。"""
    _s, repo, task, sub = await _setup()
    payload = {"result_type": "text", "output": _fitness_output()}
    from subagent.api.callbacks import _handle_completed

    with _PATCHES[0], _PATCHES[1], _PATCHES[2]:
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.DONE

    partial = await PartialPlan.objects.filter(research_task=task, valid=True).afirst()
    assert partial is not None
    content = partial.content
    assert content["fitness"]["verdict"] == "suitable"
    assert content["fitness"]["citations"] == ["src/pages/study/index.vue"]
    assert content["role_suggestion"] == "direct"
    assert content["responsibility"] == "承载专项学习页与练习入口"
    assert len(content["findings"]) == 1
    assert content["findings"][0]["citations"] == ["src/router/index.ts"]
    # repository_id 由服务端权威写入（不采信容器上报值）
    assert content["repository_id"] == str(repo.id)


async def test_text_fenced_json_parsed() -> None:
    """output 只有 ```json 围栏文本 → 同样解析成功并落库。"""
    _s, _r, task, sub = await _setup()
    fenced = (
        '```json\n{"fitness": {"verdict": "unsuitable", "reasons": ["与本仓职责无关"], '
        '"citations": []}, "role_suggestion": "indirect", "responsibility": "无", '
        '"findings": []}\n```'
    )
    payload = {"result_type": "text", "output": {"text": fenced}}
    from subagent.api.callbacks import _handle_completed

    with _PATCHES[0], _PATCHES[1], _PATCHES[2]:
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    partial = await PartialPlan.objects.filter(research_task=task, valid=True).afirst()
    assert partial is not None
    assert partial.content["fitness"]["verdict"] == "unsuitable"
    assert partial.content["role_suggestion"] == "indirect"


# ===========================================================================
# 4/5. 不可解析与枚举归一
# ===========================================================================


async def test_missing_verdict_marks_failed_without_partial() -> None:
    """缺 fitness.verdict → task failed + empty_or_unparseable_result，且无 PartialPlan 行。"""
    _s, _r, task, sub = await _setup()
    payload = {"result_type": "text", "output": {"fitness": {"reasons": ["没给结论"]}}}
    from subagent.api.callbacks import _handle_completed

    with _PATCHES[0], _PATCHES[1], _PATCHES[2]:
        resp = await _handle_completed(sub, payload, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.FAILED
    assert task.error.get("reason") == "empty_or_unparseable_result"
    assert await PartialPlan.objects.filter(research_task=task).acount() == 0


async def test_free_text_output_marks_failed() -> None:
    """纯自由文本（无 JSON）→ 不可解析 → failed。"""
    _s, _r, task, sub = await _setup()
    payload = {"result_type": "text", "output": {"text": "我看了一圈，感觉还行。"}}
    from subagent.api.callbacks import _handle_completed

    with _PATCHES[0], _PATCHES[1], _PATCHES[2]:
        await _handle_completed(sub, payload, _log())

    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.FAILED
    assert task.error.get("reason") == "empty_or_unparseable_result"


def test_illegal_verdict_is_unparseable() -> None:
    """非法 verdict（great）→ 判不可解析（宁可重跑也不落编造结论）。"""
    from subagent.api.callbacks import _parse_blueprint_fitness

    assert _parse_blueprint_fitness(_fitness_output(fitness={"verdict": "great"})) is None
    assert _parse_blueprint_fitness({"fitness": "not-a-dict"}) is None
    assert _parse_blueprint_fitness({}) is None
    assert _parse_blueprint_fitness(None) is None


def test_illegal_role_falls_back_to_direct() -> None:
    """非法 role_suggestion（maybe / 缺失）→ 回落保守的 direct。"""
    from subagent.api.callbacks import _parse_blueprint_fitness

    parsed = _parse_blueprint_fitness(_fitness_output(role_suggestion="maybe"))
    assert parsed is not None and parsed["role_suggestion"] == "direct"

    raw = _fitness_output()
    raw.pop("role_suggestion")
    parsed2 = _parse_blueprint_fitness(raw)
    assert parsed2 is not None and parsed2["role_suggestion"] == "direct"


def test_findings_normalized_and_capped() -> None:
    """findings 白名单归一：非 dict 项/裸字符串可容纳，条数有上界。"""
    from subagent.api.callbacks import _BLUEPRINT_MAX_FINDINGS, _parse_blueprint_fitness

    parsed = _parse_blueprint_fitness(
        _fitness_output(findings=["纯文本发现", {"title": "t", "citations": "非法"}, 42])
    )
    assert parsed is not None
    assert parsed["findings"][0]["detail"] == "纯文本发现"
    assert parsed["findings"][1]["citations"] == []

    many = _parse_blueprint_fitness(
        _fitness_output(findings=[{"title": f"t{i}"} for i in range(60)])
    )
    assert many is not None and len(many["findings"]) == _BLUEPRINT_MAX_FINDINGS


# ===========================================================================
# 6. 幂等
# ===========================================================================


async def test_terminal_task_is_noop() -> None:
    """已 done 的 task 再回调 → 反查返 None，PartialPlan 行数不变（回调重投递幂等）。"""
    from subagent.api.callbacks import (
        _aload_blueprint_research_task,
        _handle_blueprint_research_completion,
    )

    _s, _r, task, sub = await _setup(status=RepoResearchTaskStatus.DONE)
    loaded, _bp = await _aload_blueprint_research_task(sub)
    assert loaded is None

    await _handle_blueprint_research_completion(sub, {"output": _fitness_output()}, _log())
    assert await PartialPlan.objects.filter(research_task=task).acount() == 0


# ===========================================================================
# 7. 失败回调 + call_source
# ===========================================================================


async def test_failure_callback_marks_container_failed_and_emits() -> None:
    """失败回调 → mark_failed(container_failed) + blueprint.repo_research.failed 事件。"""
    from delivery.services.event_taxonomy import EVENT_BLUEPRINT_REPO_RESEARCH_FAILED
    from subagent.api.callbacks import _handle_failed

    _s, _r, task, sub = await _setup()
    emitted: list[tuple] = []

    async def _spy(self, event, session, payload):  # noqa: ANN001
        emitted.append((event, payload))

    with (
        patch("subagent.api.callbacks._update_coding_session_on_fail", new_callable=AsyncMock),
        patch("subagent.api.callbacks._send_failure_notification", new_callable=AsyncMock),
        patch("subagent.api.callbacks._schedule_workflow_resume"),
        patch("subagent.api.callbacks._schedule_agent_session_resume"),
        patch(
            "delivery.services.convergence_session_service.ConvergenceSessionService._emit_event",
            new=_spy,
        ),
    ):
        resp = await _handle_failed(sub, {"error": "容器超时"}, _log())

    assert resp.status_code == 200
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.FAILED
    assert task.error.get("reason") == "container_failed"
    # 112-05 把 barrier 的续驱接通后（`blueprint_resume.aresume_blueprint_session` 落地），
    # 全部 task 终态会顺带驱动 engine，后续 transition 也各自 emit 一条事件。断言收紧为
    # 「失败事件必须是本次回调 emit 的第一条」——原「恰好只有一条」的口径在 barrier 还是
    # no-op 桩时才成立。
    assert emitted, "失败回调必须 emit 事件"
    assert emitted[0][0] == EVENT_BLUEPRINT_REPO_RESEARCH_FAILED


async def test_completion_exception_swallowed_returns_200() -> None:
    """蓝图链完成钩子异常 → swallow，回调仍返 200（永不阻塞主流程）。"""
    _s, _r, _t, sub = await _setup()
    from subagent.api.callbacks import _handle_completed

    async def _boom(*a, **kw):
        raise RuntimeError("downstream failure")

    with (
        _PATCHES[0],
        _PATCHES[1],
        _PATCHES[2],
        patch("subagent.api.callbacks._handle_blueprint_research_completion", new=_boom),
    ):
        resp = await _handle_completed(sub, {"result_type": "text", "output": {}}, _log())

    assert resp.status_code == 200


async def test_derive_call_source_blueprint_repo_research() -> None:
    """last_output.source == blueprint_research → blueprint_repo_research（不回退 sdk_agent_task）。"""
    from subagent.api.callbacks import _derive_container_call_source

    _s, _r, _t, sub = await _setup()
    assert _derive_container_call_source(sub) == "blueprint_repo_research"

    _s2, _r2, _t2, plan_sub = await _setup(source="plan_research")
    assert _derive_container_call_source(plan_sub) == "sdk_agent_task"
