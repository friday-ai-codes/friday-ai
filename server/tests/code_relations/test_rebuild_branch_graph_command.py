"""initial implementation plan（work item / v26.2 Critical 2）：rebuild_branch_graph 命令测试。

覆盖：dry-run 不写库 + 污染量区间报告结构 + INDEXED 非 base 分支筛选 + 参数校验。
"""

from __future__ import annotations

import uuid
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from code_relations.models import ChunkEdge, ChunkRegistry
from codegraph.models import Symbol
from repositories.models import (
    BranchFileIndex,
    BranchIndexStatus,
    IndexStatus,
    Repository,
    RepositoryBranchIndex,
)


def _make_repo(name: str = "branch-graph-repo") -> Repository:
    return Repository.objects.create(
        name=name,
        git_url=f"https://example.com/{name}.git",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )


def _seed_pollution(repo: Repository) -> None:
    """构造一个 INDEXED feature 分支 + added/modified overlay 文件 + 命中 base 图谱行。"""
    # base 分支（不应计入 at-risk）。
    RepositoryBranchIndex.objects.create(
        repository=repo, branch_name="main", is_base_branch=True,
        status=BranchIndexStatus.INDEXED,
    )
    feature = RepositoryBranchIndex.objects.create(
        repository=repo, branch_name="feature/x", is_base_branch=False,
        status=BranchIndexStatus.INDEXED,
    )
    BranchFileIndex.objects.create(
        branch_index=feature, file_path="src/added.py", change_type="added"
    )
    BranchFileIndex.objects.create(
        branch_index=feature, file_path="src/modified.py", change_type="modified"
    )
    # base 图谱行（branch_name=""）命中 added → definite；命中 modified → ambiguous。
    Symbol.objects.create(
        repository=repo, branch_name="", name="f_added", symbol_type="FUNCTION",
        file_path="src/added.py", start_line=1, end_line=2,
    )
    Symbol.objects.create(
        repository=repo, branch_name="", name="f_modified", symbol_type="FUNCTION",
        file_path="src/modified.py", start_line=1, end_line=2,
    )
    ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(), content_hash="a" * 64, repository=repo,
        branch_name="", file_path="src/added.py", chunk_index=0,
    )


@pytest.mark.django_db
def test_dry_run_does_not_write_db() -> None:
    """work item：--dry-run 运行前后图谱行计数零变化（证明不写库）。"""
    repo = _make_repo()
    _seed_pollution(repo)
    before = (
        Symbol.objects.count(),
        ChunkRegistry.objects.count(),
        ChunkEdge.objects.count(),
    )
    out = StringIO()
    call_command("rebuild_branch_graph", "--repo", str(repo.id), "--dry-run", stdout=out)
    after = (
        Symbol.objects.count(),
        ChunkRegistry.objects.count(),
        ChunkEdge.objects.count(),
    )
    assert before == after
    text = out.getvalue()
    assert "[DRY-RUN]" in text
    assert "definite_feature_rows=" in text
    assert "ambiguous_rows=" in text
    assert "feature/x" in text


@pytest.mark.django_db
def test_dry_run_filters_indexed_non_base_only() -> None:
    """work item：base 分支不计入 at-risk；无 feature 分支的仓为 skipped_no_work。"""
    repo = _make_repo()
    _seed_pollution(repo)
    clean = _make_repo("clean-repo")
    RepositoryBranchIndex.objects.create(
        repository=clean, branch_name="main", is_base_branch=True,
        status=BranchIndexStatus.INDEXED,
    )

    out = StringIO()
    call_command("rebuild_branch_graph", "--all", "--dry-run", stdout=out)
    text = out.getvalue()
    # 有污染仓走 work item，干净仓走 SKIP。
    assert "[DRY-RUN]" in text
    assert "[SKIP]" in text
    assert "processed_repos=1" in text
    assert "skipped_no_work_repos=1" in text


@pytest.mark.django_db
def test_dry_run_interval_definite_and_ambiguous() -> None:
    """work item：added 命中计 definite、modified 命中计 ambiguous，区间口径自洽。"""
    repo = _make_repo()
    _seed_pollution(repo)
    out = StringIO()
    call_command("rebuild_branch_graph", "--repo", str(repo.id), "--dry-run", stdout=out)
    text = out.getvalue()
    # added.py 命中 1 Symbol + 1 ChunkRegistry = 2 definite；modified.py 命中 1 Symbol = 1 ambiguous。
    assert "definite_feature_rows=2" in text
    assert "ambiguous_rows=1" in text


@pytest.mark.django_db
def test_repo_and_all_mutually_exclusive() -> None:
    """work item：--repo 与 --all 同传抛 CommandError。"""
    with pytest.raises(CommandError):
        call_command("rebuild_branch_graph", "--repo", str(uuid.uuid4()), "--all", "--dry-run")


@pytest.mark.django_db
def test_missing_repo_and_all_raises() -> None:
    """work item：--repo / --all 都不传抛 CommandError。"""
    with pytest.raises(CommandError):
        call_command("rebuild_branch_graph", "--dry-run")


@pytest.mark.django_db
def test_non_dry_run_cleans_base_added_rows_and_rebuilds_branches() -> None:
    """work item：实跑清理 definite base 污染，并触发 base + feature 重建。"""
    repo = _make_repo()
    _seed_pollution(repo)
    calls: list[dict[str, object]] = []

    async def fake_build_graph_for_repository(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return SimpleNamespace(status="completed", files_processed=1, files_total=1)

    out = StringIO()
    with patch(
        "code_relations.management.commands.rebuild_branch_graph.build_graph_for_repository",
        new=fake_build_graph_for_repository,
    ):
        call_command("rebuild_branch_graph", "--repo", str(repo.id), stdout=out)
    text = out.getvalue()
    assert "[APPLIED]" in text
    assert "cleaned_base_rows=2" in text
    assert Symbol.objects.filter(file_path="src/added.py", branch_name="").count() == 0
    assert ChunkRegistry.objects.filter(file_path="src/added.py", branch_name="").count() == 0
    assert [call["kwargs"]["branch"] for call in calls] == [None, "feature/x"]
