"""git_platform 双客户端 merged_at 归一化真实路径守护（CR-01）。

``fake_git_platform`` fixture 绕过真实客户端，故 naive→aware 归一化逻辑
（``get_merge_request_metadata`` 内）此前无任何用例覆盖；CR-01 暴露该处
误用了 Django 5.0 起已删除的 ``django.utils.timezone.utc``，naive merged_at
路径必抛 ``AttributeError`` 被外层 except 兜成 success=False。本模块直接实例化
真实 ``GitHubClient`` / ``GitLabClient``（``_get_repo`` / ``_get_project`` 经
monkeypatch 注入 fake 平台对象，不触网），断言 naive merged_at 被归一为
aware UTC 且 ``success=True``——关上 fake-client 的覆盖缺口。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from services.git_platform.github_client import GitHubClient
from services.git_platform.gitlab_client import GitLabClient


async def test_github_naive_merged_at_normalized_to_aware_utc(monkeypatch) -> None:
    """GitHub：naive merged_at（无 tzinfo）→ aware UTC，success=True（CR-01 真实路径）。"""
    client = GitHubClient(token="tok", owner="o", repo="r")
    naive = datetime(2024, 1, 2, 3, 4, 5)  # naive：命中 is_naive 归一分支
    assert naive.tzinfo is None

    fake_pr = MagicMock()
    fake_pr.merged_at = naive
    fake_pr.merge_commit_sha = "deadbeef" * 5
    fake_pr.base = MagicMock(ref="main")
    fake_pr.head = MagicMock(ref="feat/x")
    fake_repo = MagicMock()
    fake_repo.get_pull.return_value = fake_pr
    monkeypatch.setattr(client, "_get_repo", lambda: fake_repo)

    result = await client.get_merge_request_metadata("9")

    assert result.success is True
    assert result.merged_at is not None
    # 归一为 aware UTC（naive 被解释为 UTC，时刻不偏移）
    assert result.merged_at.tzinfo is not None
    assert result.merged_at.utcoffset() == timedelta(0)
    assert result.merged_at == naive.replace(tzinfo=timezone.utc)
    assert result.merge_commit_sha == "deadbeef" * 5
    assert result.target_branch == "main"
    assert result.source_branch == "feat/x"


async def test_github_aware_merged_at_passthrough(monkeypatch) -> None:
    """GitHub：已 aware merged_at（PyGithub ≥2.0 现状）短路不改写。"""
    client = GitHubClient(token="tok", owner="o", repo="r")
    aware = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    fake_pr = MagicMock()
    fake_pr.merged_at = aware
    fake_pr.merge_commit_sha = "abc"
    fake_pr.base = MagicMock(ref="main")
    fake_pr.head = MagicMock(ref="feat/x")
    fake_repo = MagicMock()
    fake_repo.get_pull.return_value = fake_pr
    monkeypatch.setattr(client, "_get_repo", lambda: fake_repo)

    result = await client.get_merge_request_metadata("9")

    assert result.success is True
    assert result.merged_at == aware


async def test_gitlab_naive_merged_at_normalized_to_aware_utc(monkeypatch) -> None:
    """GitLab：parse_datetime 解析出 naive merged_at → 归一为 aware UTC（CR-01 真实路径）。"""
    client = GitLabClient(base_url="https://gitlab.com", token="tok", project_path="g/p")

    fake_mr = MagicMock()
    fake_mr.merged_at = "2024-01-02T03:04:05"  # 无时区偏移 → parse_datetime 返回 naive
    fake_mr.merge_commit_sha = "deadbeef" * 5
    fake_mr.target_branch = "main"
    fake_mr.source_branch = "feat/x"
    fake_project = MagicMock()
    fake_project.mergerequests.get.return_value = fake_mr
    monkeypatch.setattr(client, "_get_project", lambda: fake_project)

    result = await client.get_merge_request_metadata("9")

    assert result.success is True
    assert result.merged_at is not None
    assert result.merged_at.tzinfo is not None
    assert result.merged_at.utcoffset() == timedelta(0)
    assert result.merged_at == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert result.merge_commit_sha == "deadbeef" * 5
