"""`rebuild_repo_summaries` 管理命令测试 —— 仓库路由索引存量回填。"""

from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from repositories.models import IndexStatus, Repository

BUILD_PATH = "codegraph.services.repo_summary_builder.RepoSummaryBuilder.build"


def _make_repo(name: str, status: str = IndexStatus.INDEXED) -> Repository:
    return Repository.objects.create(
        name=name,
        git_url=f"https://github.com/test/{name}.git",
        git_platform="github",
        default_branch="main",
        index_status=status,
    )


@pytest.mark.django_db
def test_rebuilds_all_indexed_repositories() -> None:
    """缺省模式只处理 INDEXED 仓库，未索引仓库跳过。"""
    indexed_a = _make_repo("repo-a")
    indexed_b = _make_repo("repo-b")
    _make_repo("repo-c", status=IndexStatus.NOT_INDEXED)

    out = StringIO()
    with patch(BUILD_PATH, new_callable=AsyncMock, return_value=True) as mock_build:
        call_command("rebuild_repo_summaries", stdout=out)

    called_ids = {call.kwargs["repository_id"] for call in mock_build.call_args_list}
    assert called_ids == {str(indexed_a.id), str(indexed_b.id)}
    assert "2/2 成功" in out.getvalue()


@pytest.mark.django_db
def test_rebuilds_specified_repository_regardless_of_status() -> None:
    """--repo 显式指定时不过滤索引状态（用于修复 FAILED 后的残留）。"""
    repo = _make_repo("repo-x", status=IndexStatus.FAILED)
    _make_repo("repo-y")

    out = StringIO()
    with patch(BUILD_PATH, new_callable=AsyncMock, return_value=True) as mock_build:
        call_command("rebuild_repo_summaries", "--repo", str(repo.id), stdout=out)

    assert mock_build.call_count == 1
    assert mock_build.call_args.kwargs["repository_id"] == str(repo.id)


@pytest.mark.django_db
def test_invalid_repo_uuid_raises_command_error() -> None:
    """非法 UUID 必须 fail fast，不进入重建流程。"""
    with pytest.raises(CommandError, match="无效的仓库 UUID"):
        call_command("rebuild_repo_summaries", "--repo", "not-a-uuid")


@pytest.mark.django_db
def test_reports_failed_repositories() -> None:
    """构建失败（返回 False 或抛异常）的仓库要在输出中点名。"""
    failed_repo = _make_repo("repo-fail")
    ok_repo = _make_repo("repo-ok")

    async def fake_build(*, repository_id: str) -> bool:
        if repository_id == str(failed_repo.id):
            raise RuntimeError("qdrant down")
        return True

    out = StringIO()
    with patch(BUILD_PATH, side_effect=fake_build):
        call_command("rebuild_repo_summaries", stdout=out)

    output = out.getvalue()
    assert "1/2 成功" in output
    assert str(failed_repo.id) in output
    assert str(ok_repo.id) not in output.split("失败仓库")[-1]
