"""acapture_pr_review 守护测试（Phase 101 / LOOP-05，ROADMAP 成功标准 4/5）。

- 开关关（默认）→ summarize_branch 与 LLM 均未调用（零成本断言）
- 开关开 + 全链 mock → persist 被调、幂等键带 :pr_review 后缀、outcome="review"、
  source_links 含 pr_url
- summarize_branch 抛异常 → 不上抛、无 persist
- 同 session 重入 → 复用 101-02 幂等（已存在 {sid}:pr_review 行时 skip、不烧 token）
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from structlog.testing import capture_logs

from mcp_tools.models import McpLearningCase
from mcp_tools.pr_review_capture import acapture_pr_review
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

_BASE = "mcp_tools.pr_review_capture"
_SWITCH_PATH = f"{_BASE}.aget_bool_setting"
_SUMMARIZE_PATH = f"{_BASE}.summarize_branch"
_LLM_PATH = f"{_BASE}._acall_llm"
_INGEST_PATH = "knowledge.ingestion.aschedule_ingestion"

_REVIEW_TEXT = (
    '{"repository": "backend", "summary": "变更整体可控", "dimensions": {}}\n'
    "本次变更最值得沉淀的经验：异步 ORM 访问统一经 sync_to_async 桥接，"
    "避免在事件循环内直接触发同步查询导致 SynchronousOnlyOperation。"
)

_SUMMARY = {
    "files": [
        {"path": "server/app/views.py", "change_type": "modified", "additions": 10, "deletions": 2}
    ],
    "risks": ["未发现明显合并风险。"],
    "test_suggestions": ["复跑受影响模块的单元测试。"],
}


async def _make_repo() -> Repository:
    return await Repository.objects.acreate(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        default_branch="main",
    )


def _call(repo: Repository, session_id: str = "sess-review", **kwargs: Any):
    defaults = {
        "repository_id": str(repo.id),
        "source_branch": "feature/x",
        "target_branch": "main",
        "pr_url": "https://git.example.com/mr/9",
        "session_id": session_id,
        "requirement_text": "登录接口异步化改造",
        "work_item_type": "story",
        "work_item_id": 42,
        "initiated_by_user_id": "u-7",
    }
    defaults.update(kwargs)
    return acapture_pr_review(**defaults)


async def test_switch_off_default_zero_cost():
    """开关关（默认）：summarize_branch 与 LLM 均未调用，零 LLM 调用。"""
    repo = await _make_repo()
    summarize = AsyncMock(return_value=_SUMMARY)
    llm = AsyncMock(return_value=_REVIEW_TEXT)
    with (
        patch(_SUMMARIZE_PATH, new=summarize),
        patch(_LLM_PATH, new=llm),
        capture_logs() as logs,
    ):
        await _call(repo)
    summarize.assert_not_awaited()
    llm.assert_not_awaited()
    assert await McpLearningCase.objects.acount() == 0
    skipped = [log for log in logs if log.get("event") == "pr_review_capture_skipped"]
    assert skipped and skipped[0]["reason"] == "disabled"


async def test_switch_on_persists_review_case():
    """开关开 + 全链 mock：case 落库、幂等键带 :pr_review 后缀、outcome=review、
    source_links 含 pr_url。"""
    repo = await _make_repo()
    with (
        patch(_SWITCH_PATH, new=AsyncMock(return_value=True)),
        patch(_SUMMARIZE_PATH, new=AsyncMock(return_value=_SUMMARY)),
        patch(_LLM_PATH, new=AsyncMock(return_value=_REVIEW_TEXT)),
        patch(_INGEST_PATH, new=AsyncMock()) as ingest,
        capture_logs() as logs,
    ):
        await _call(repo, session_id="sess-on")

    case = await McpLearningCase.objects.aget(source_session_id="sess-on:pr_review")
    assert case.outcome == "review"
    assert case.source_links["pr_url"] == "https://git.example.com/mr/9"
    assert case.source_links["source"] == "pr_review"
    assert case.source_links["session_id"] == "sess-on"
    assert case.mr_urls == ["https://git.example.com/mr/9"]
    assert case.branches == ["feature/x"]
    assert case.repositories == [repo.name]
    assert case.work_item_type == "story"
    assert case.work_item_id == 42
    # 入图复用 LOOP-03 路径（INV-6）。
    ingest.assert_awaited_once()
    assert ingest.await_args.kwargs.get("initiated_by_user_id") == "u-7"
    completed = [log for log in logs if log.get("event") == "pr_review_capture_completed"]
    assert len(completed) == 1
    assert completed[0]["category"] == "caller"
    assert completed[0]["initiated_by_user_id"] == "u-7"


async def test_summarize_failure_soft_skip_no_persist():
    """summarize_branch 抛异常：不上抛、无 persist、LLM 未调用。"""
    repo = await _make_repo()
    llm = AsyncMock(return_value=_REVIEW_TEXT)
    with (
        patch(_SWITCH_PATH, new=AsyncMock(return_value=True)),
        patch(_SUMMARIZE_PATH, new=AsyncMock(side_effect=RuntimeError("platform down"))),
        patch(_LLM_PATH, new=llm),
        capture_logs() as logs,
    ):
        await _call(repo, session_id="sess-boom")
    llm.assert_not_awaited()
    assert await McpLearningCase.objects.acount() == 0
    skipped = [log for log in logs if log.get("event") == "pr_review_capture_skipped"]
    assert skipped and skipped[0]["reason"] == "diff_summary_failed"


async def test_idempotent_reentry_skips_without_llm():
    """同 session 重入：已存在 {sid}:pr_review 行 → skip 且不烧 token（复用 101-02 幂等）。"""
    repo = await _make_repo()
    await McpLearningCase.objects.acreate(
        run=None,
        source_session_id="sess-dup:pr_review",
        title="既有 review case",
        problem="p" * 40,
        root_cause="",
        solution="s" * 40,
        outcome="review",
    )
    summarize = AsyncMock(return_value=_SUMMARY)
    llm = AsyncMock(return_value=_REVIEW_TEXT)
    with (
        patch(_SWITCH_PATH, new=AsyncMock(return_value=True)),
        patch(_SUMMARIZE_PATH, new=summarize),
        patch(_LLM_PATH, new=llm),
        capture_logs() as logs,
    ):
        await _call(repo, session_id="sess-dup")
    summarize.assert_not_awaited()
    llm.assert_not_awaited()
    assert await McpLearningCase.objects.acount() == 1
    skipped = [log for log in logs if log.get("event") == "pr_review_capture_skipped"]
    assert skipped and skipped[0]["reason"] == "duplicate"


async def test_repository_missing_soft_skip():
    """仓库不存在：skip return，summarize/LLM 均未调用。"""
    repo = await _make_repo()
    summarize = AsyncMock(return_value=_SUMMARY)
    with (
        patch(_SWITCH_PATH, new=AsyncMock(return_value=True)),
        patch(_SUMMARIZE_PATH, new=summarize),
        capture_logs() as logs,
    ):
        await _call(repo, repository_id=str(uuid.uuid4()), session_id="sess-norepo")
    summarize.assert_not_awaited()
    assert await McpLearningCase.objects.acount() == 0
    skipped = [log for log in logs if log.get("event") == "pr_review_capture_skipped"]
    assert skipped and skipped[0]["reason"] == "repository_missing"
