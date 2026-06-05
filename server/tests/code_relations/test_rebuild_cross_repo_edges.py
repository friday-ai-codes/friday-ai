"""implementation: rebuild_cross_repo_edges management command 测试（work item）。"""
from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_command_exits_when_enrichment_disabled(settings) -> None:
    """ENABLE_CROSS_REPO_ENRICHMENT=False → 打印警告并退出，不报错。"""
    settings.ENABLE_CROSS_REPO_ENRICHMENT = False
    out = StringIO()
    err = StringIO()
    call_command("rebuild_cross_repo_edges", "--all", stdout=out, stderr=err)
    # 应输出警告
    assert "ENABLE_CROSS_REPO_ENRICHMENT=False" in err.getvalue()


@pytest.mark.django_db
def test_command_all_dry_run_no_cross_calls(settings) -> None:
    """ENABLE_CROSS_REPO_ENRICHMENT=True，无 CrossRepoApiCall 时正常退出。"""
    settings.ENABLE_CROSS_REPO_ENRICHMENT = True
    out = StringIO()
    err = StringIO()
    call_command("rebuild_cross_repo_edges", "--all", "--dry-run", stdout=out, stderr=err)
    output = out.getvalue()
    # 无记录时应提示跳过
    assert "无 CrossRepoApiCall" in output or "rebuild_cross_repo_edges" in output


@pytest.mark.django_db
def test_command_all_no_cross_calls(settings) -> None:
    """无 CrossRepoApiCall 时 --all 正常返回，不报错。"""
    settings.ENABLE_CROSS_REPO_ENRICHMENT = True
    out = StringIO()
    call_command("rebuild_cross_repo_edges", "--all", stdout=out)
    output = out.getvalue()
    assert output  # 有输出


@pytest.mark.django_db
def test_command_invalid_repo_uuid_raises(settings) -> None:
    """--repo 传无效 UUID 应 CommandError。"""
    from django.core.management.base import CommandError

    settings.ENABLE_CROSS_REPO_ENRICHMENT = True
    with pytest.raises(CommandError, match="非法 UUID"):
        call_command("rebuild_cross_repo_edges", "--repo", "not-a-uuid")
