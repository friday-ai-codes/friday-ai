"""研究聚合 + 结果解析测试（Phase 39-04，DOMAIN §7/§14）。

覆盖 barrier 终态判定 / amaybe_complete_research 推进 / parse_partial_plan_content
结构化+降级+None 三路。
"""

from __future__ import annotations

import json
import uuid

import pytest

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from repositories.models import Repository
from services.process_runtime.research_aggregation import (
    aall_research_tasks_terminal,
    amaybe_complete_research,
    parse_partial_plan_content,
)

pytestmark = pytest.mark.django_db(transaction=True)


async def _repo() -> Repository:
    return await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


async def _session(current_stage: str = "research") -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage=current_stage,
    )


# --- aall_research_tasks_terminal ---


@pytest.mark.asyncio
async def test_terminal_no_tasks_true() -> None:
    """无任何 task → True（无需调研）。"""
    session = await _session()
    assert await aall_research_tasks_terminal(session.id) is True


@pytest.mark.asyncio
async def test_terminal_all_done_or_failed_true() -> None:
    """全部 done/failed → True。"""
    session = await _session()
    await RepoResearchTask.objects.acreate(
        session=session, repository=await _repo(), status=RepoResearchTaskStatus.DONE
    )
    await RepoResearchTask.objects.acreate(
        session=session, repository=await _repo(), status=RepoResearchTaskStatus.FAILED
    )
    assert await aall_research_tasks_terminal(session.id) is True


@pytest.mark.asyncio
async def test_terminal_pending_running_stale_false() -> None:
    """有 pending/running/stale 在途 → False（stale 非终态）。"""
    session = await _session()
    await RepoResearchTask.objects.acreate(
        session=session, repository=await _repo(), status=RepoResearchTaskStatus.DONE
    )
    await RepoResearchTask.objects.acreate(
        session=session, repository=await _repo(), status=RepoResearchTaskStatus.STALE
    )
    assert await aall_research_tasks_terminal(session.id) is False


# --- amaybe_complete_research ---


@pytest.mark.asyncio
async def test_maybe_complete_advances_to_merging() -> None:
    """所有终态 → transition research_complete → merge stage，返回 True。"""
    session = await _session()
    await RepoResearchTask.objects.acreate(
        session=session, repository=await _repo(), status=RepoResearchTaskStatus.DONE
    )
    advanced = await amaybe_complete_research(session)
    assert advanced is True
    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "merge"


@pytest.mark.asyncio
async def test_maybe_complete_in_flight_no_advance() -> None:
    """仍有 running 在途 → 不推进，停留 research stage。"""
    session = await _session()
    await RepoResearchTask.objects.acreate(
        session=session, repository=await _repo(), status=RepoResearchTaskStatus.RUNNING
    )
    advanced = await amaybe_complete_research(session)
    assert advanced is False
    reloaded = await ConvergenceSession.objects.aget(id=session.id)
    assert reloaded.current_stage == "research"


@pytest.mark.asyncio
async def test_maybe_complete_non_researching_noop() -> None:
    """非 research stage（已推进）→ no-op return False。"""
    session = await _session(current_stage="merge")
    advanced = await amaybe_complete_research(session)
    assert advanced is False


# --- parse_partial_plan_content ---


def test_parse_structured_dict() -> None:
    """raw 含 §7 字段 → 直采结构化（缺列表补 []，回填 repository_id）。"""
    raw = {
        "research_summary": "改鉴权",
        "proposed_changes": [{"file": "a.py"}],
        "candidate_files": ["a.py"],
    }
    content = parse_partial_plan_content(raw, repository_id="repo1")
    assert content is not None
    assert content["repository_id"] == "repo1"
    assert content["research_summary"] == "改鉴权"
    assert content["proposed_changes"] == [{"file": "a.py"}]
    assert content["api_contracts_exposed"] == []
    assert content["dependencies_on_other_repos"] == []


def test_parse_text_json_struct() -> None:
    """raw.text 为含 §7 键的 JSON 文本 → 解析为结构化。"""
    inner = json.dumps({"research_summary": "S", "candidate_files": ["x.py"]})
    content = parse_partial_plan_content({"text": f"前言\n{inner}"}, repository_id="r2")
    assert content is not None
    assert content["research_summary"] == "S"
    assert content["candidate_files"] == ["x.py"]


def test_parse_free_text_degrades() -> None:
    """自由文本（非 JSON）→ 优雅降级 file 级摘要。"""
    content = parse_partial_plan_content("这是一段非结构化分析", repository_id="r3")
    assert content is not None
    assert content["repository_id"] == "r3"
    assert content["research_summary"] == "这是一段非结构化分析"
    assert content["proposed_changes"] == []


def test_parse_empty_returns_none() -> None:
    """空 dict / 空串 / None → None。"""
    assert parse_partial_plan_content({}, repository_id="r") is None
    assert parse_partial_plan_content("", repository_id="r") is None
    assert parse_partial_plan_content(None, repository_id="r") is None
    assert parse_partial_plan_content({"text": "   "}, repository_id="r") is None
