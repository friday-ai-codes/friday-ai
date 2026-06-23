"""PROG-02：索引状态 payload 暴露 AI 描述生成状态 + 单调进度守护。"""

from __future__ import annotations

import pytest

from repositories.index_views import _FILE_PHASE_CEIL, _compute_index_progress
from repositories.models import AISummaryStatus, IndexStatus, Repository

pytestmark = pytest.mark.django_db


def _repo(**kwargs) -> Repository:
    base = dict(
        name="prog-repo",
        git_url="https://github.com/test/prog.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXING,
    )
    base.update(kwargs)
    return Repository.objects.create(**base)


def test_progress_includes_ai_summary_status() -> None:
    repo = _repo(ai_summary_status=AISummaryStatus.RUNNING, ai_summary_error="")
    progress = _compute_index_progress(repo)
    assert progress["ai_summary_status"] == "running"
    assert progress["ai_summary_error"] == ""


def test_progress_includes_ai_summary_error_on_failure() -> None:
    repo = _repo(ai_summary_status=AISummaryStatus.FAILED, ai_summary_error="provider 缺失")
    progress = _compute_index_progress(repo)
    assert progress["ai_summary_status"] == "failed"
    assert progress["ai_summary_error"] == "provider 缺失"


# ---------------------------------------------------------------------------
# PROG-01 单调性：文件级 → chunk 级边界绝不回退
# ---------------------------------------------------------------------------


def test_progress_monotonic_at_file_to_chunk_boundary() -> None:
    """解析阶段封顶 _FILE_PHASE_CEIL；chunk 阶段从该上限续接（≥），无归零跳变。"""
    # 解析阶段尾声：文件 100% → 封顶 _FILE_PHASE_CEIL
    parsing = _repo(indexed_files_total=10, indexed_files_processed=10)
    parse_pct = _compute_index_progress(parsing)["overall_progress"]
    assert parse_pct == _FILE_PHASE_CEIL

    # chunk 阶段刚开始：total_chunks>0 但尚未 embed → 应 ≥ 解析阶段上限（不回退）
    chunk_start = _repo(
        indexed_files_total=10,
        indexed_files_processed=10,
        index_total_chunks=100,
        index_processed_chunks=0,
        index_write_total=0,
        index_write_processed=0,
    )
    chunk_pct = _compute_index_progress(chunk_start)["overall_progress"]
    assert chunk_pct >= parse_pct, "chunk 阶段起点不得低于解析阶段上限（PROG-01 单调）"
    assert chunk_pct == _FILE_PHASE_CEIL


def test_progress_climbs_monotonically_within_chunk_phase() -> None:
    """chunk 阶段内随 embed/write 推进单调上升至 100。"""
    half = _compute_index_progress(
        _repo(index_total_chunks=100, index_processed_chunks=50, index_write_total=100, index_write_processed=50)
    )["overall_progress"]
    done = _compute_index_progress(
        _repo(index_total_chunks=100, index_processed_chunks=100, index_write_total=100, index_write_processed=100)
    )["overall_progress"]
    assert _FILE_PHASE_CEIL < half < done == 100
