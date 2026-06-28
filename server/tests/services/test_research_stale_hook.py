"""重索引 stale 失效钩子测试（Phase 39-04，RESEARCH-03）。

覆盖 _run_research_stale_invalidation 调 ResearchService.invalidate_for_repo 置 stale /
service 抛异常仅 warning 不冒泡（best-effort）/ 钩子接入 base-only 段（源码守护）。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from delivery.services import ResearchService
from repositories.models import Repository
from services.indexer import _run_research_stale_invalidation

pytestmark = pytest.mark.django_db(transaction=True)

INDEXER_PATH = Path(__file__).resolve().parents[2] / "services" / "indexer.py"


@pytest.mark.asyncio
async def test_hook_invalidates_partial_to_stale() -> None:
    """_run_research_stale_invalidation 经 service 把 valid partial 失效 + task stale。"""
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
    )
    task = await RepoResearchTask.objects.acreate(session=session, repository=repo)
    await ResearchService().record_partial(task, {"repository_id": str(repo.id)})

    await _run_research_stale_invalidation(str(repo.id))

    partial = await PartialPlan.objects.aget(research_task=task)
    assert partial.valid is False
    assert partial.invalidated_reason == "repo_reindexed"
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.STALE


@pytest.mark.asyncio
async def test_hook_swallows_service_exception() -> None:
    """service 抛异常 → 仅 warning，钩子不冒泡（best-effort，绝不阻断索引）。"""
    boom = AsyncMock(side_effect=RuntimeError("db down"))
    with patch.object(ResearchService, "invalidate_for_repo", new=boom):
        # 不应抛出
        await _run_research_stale_invalidation(str(uuid.uuid4()))


def test_hook_wired_in_base_only_block() -> None:
    """源码守护：钩子接入 base-only 段（紧跟 _run_modifies_chunk_reconcile 之后）。"""
    text = INDEXER_PATH.read_text(encoding="utf-8")
    assert "_run_research_stale_invalidation" in text
    # 钩子调用紧随 modifies_chunk 对账之后（同 base-only 时序）
    assert re.search(
        r"_run_modifies_chunk_reconcile\(repository_id\)\s*\n"
        r"(?:\s*#.*\n)*\s*await _run_research_stale_invalidation\(repository_id\)",
        text,
    )
