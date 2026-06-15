"""一键摄取 URL 解析守护单测（Phase 32-01 Task 2，ING-01 / CONTEXT Grey Area 2）。

覆盖：
- parse_board_url：标准飞书工作项 URL → BoardRef；非飞书 / 缺段 / 非数字 id /
  容器型不可靠形态 → None（不抛）。
- parse_mr_url：GitLab merge_requests / GitHub pull → MRRef；非 MR/PR → None。
- aresolve_repo_and_mr：host+path 归一匹配已落库 Repository（GitLab + GitHub 各一例）
  → (repo, iid)；无匹配 → None。
- 解析结果可直接构造 WorkItemIdentity（类型对齐）。

纯解析 / 异步 ORM 匹配（无真实网络，pytest-socket 隔离）。异步 ORM → transaction=True。
"""

from __future__ import annotations

import pytest

from delivery.services import (
    BoardRef,
    MRRef,
    aresolve_repo_and_mr,
    parse_board_url,
    parse_mr_url,
)
from delivery.services.work_item_service import WorkItemIdentity
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


# ============================================================================
# parse_board_url
# ============================================================================


def test_parse_board_url_standard_issue():
    """标准飞书 issue URL → BoardRef(key, type, id)。"""
    ref = parse_board_url("https://project.feishu.cn/abc123/issue/detail/456")
    assert ref == BoardRef("abc123", "issue", 456)


def test_parse_board_url_tolerates_query_fragment():
    """容忍尾部 ?query / #fragment 与末尾斜杠。"""
    ref = parse_board_url("https://project.feishu.cn/key9/story/detail/789/?tab=x#a")
    assert ref == BoardRef("key9", "story", 789)


def test_parse_board_url_larksuite_host():
    """larksuite.com 域同样视为飞书域。"""
    ref = parse_board_url("https://example.larksuite.com/projkey/issue/detail/123")
    assert ref == BoardRef("projkey", "issue", 123)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-url",
        "https://github.com/owner/repo/issue/detail/456",  # 非飞书域
        "https://project.feishu.cn/abc123/issue/detail/notanumber",  # 非数字 id
        "https://project.feishu.cn/abc123/detail/456",  # 缺 type 段
        "https://project.feishu.cn/abc123/issue/456",  # 缺 /detail/
        "https://project.feishu.cn/abc123/container/board/9527",  # 容器型不可靠形态
        "ftp://project.feishu.cn/abc123/issue/detail/456",  # 非 http(s)
    ],
)
def test_parse_board_url_returns_none(url):
    """非飞书 / 缺段 / 非数字 id / 容器型不可靠 URL → None（不抛）。"""
    assert parse_board_url(url) is None


def test_board_ref_feeds_work_item_identity():
    """解析结果可直接构造 WorkItemIdentity（三元组类型对齐）。"""
    ref = parse_board_url("https://project.feishu.cn/abc123/issue/detail/456")
    identity = WorkItemIdentity(
        feishu_project_key=ref.feishu_project_key,
        work_item_type=ref.work_item_type,
        work_item_id=ref.work_item_id,
    )
    assert identity.feishu_project_key == "abc123"
    assert identity.work_item_type == "issue"
    assert identity.work_item_id == 456
    assert isinstance(identity.work_item_id, int)


# ============================================================================
# parse_mr_url
# ============================================================================


def test_parse_mr_url_gitlab():
    """GitLab merge_requests → MRRef(host, namespace/project, iid)。"""
    ref = parse_mr_url("https://gitlab.example.com/group/proj/-/merge_requests/123")
    assert ref == MRRef("gitlab.example.com", "group/proj", "123")


def test_parse_mr_url_gitlab_nested_group():
    """GitLab 嵌套组 namespace 完整保留。"""
    ref = parse_mr_url("https://gitlab.example.com/g1/g2/proj/-/merge_requests/7")
    assert ref == MRRef("gitlab.example.com", "g1/g2/proj", "7")


def test_parse_mr_url_github():
    """GitHub pull → MRRef(github.com, owner/repo, iid)。"""
    ref = parse_mr_url("https://github.com/owner/repo/pull/9")
    assert ref == MRRef("github.com", "owner/repo", "9")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-url",
        "https://gitlab.example.com/group/proj",  # 无 MR 段
        "https://github.com/owner/repo",  # 无 PR 段
        "https://github.com/owner/repo/issues/9",  # issues 非 pull
        "https://project.feishu.cn/abc/issue/detail/1",  # 看板 URL 非 MR
    ],
)
def test_parse_mr_url_returns_none(url):
    """非 MR/PR URL → None（不抛）。"""
    assert parse_mr_url(url) is None


# ============================================================================
# aresolve_repo_and_mr（异步 ORM 匹配）
# ============================================================================


async def test_aresolve_repo_gitlab_hit():
    """命中已落库 GitLab Repository（host+path 归一）→ (repo, iid)。"""
    repo = await Repository.objects.acreate(
        name="proj",
        git_url="https://gitlab.example.com/group/proj.git",
        git_platform="gitlab",
    )
    result = await aresolve_repo_and_mr(
        "https://gitlab.example.com/group/proj/-/merge_requests/123"
    )
    assert result is not None
    matched, iid = result
    assert matched.pk == repo.pk
    assert iid == "123"


async def test_aresolve_repo_github_hit():
    """命中已落库 GitHub Repository（host+path 归一）→ (repo, iid)。"""
    repo = await Repository.objects.acreate(
        name="repo",
        git_url="https://github.com/owner/repo.git",
        git_platform="github",
    )
    result = await aresolve_repo_and_mr("https://github.com/owner/repo/pull/9")
    assert result is not None
    matched, iid = result
    assert matched.pk == repo.pk
    assert iid == "9"


async def test_aresolve_repo_case_insensitive_ssh_url():
    """SSH git_url + 大小写差异仍归一匹配（复用 extract helper）。"""
    repo = await Repository.objects.acreate(
        name="proj",
        git_url="git@gitlab.example.com:Group/Proj.git",
        git_platform="gitlab",
    )
    result = await aresolve_repo_and_mr(
        "https://gitlab.example.com/group/proj/-/merge_requests/5"
    )
    assert result is not None
    matched, iid = result
    assert matched.pk == repo.pk
    assert iid == "5"


async def test_aresolve_repo_no_match():
    """无匹配 Repository → None（不抛、不旁路写）。"""
    await Repository.objects.acreate(
        name="other",
        git_url="https://gitlab.example.com/group/other.git",
        git_platform="gitlab",
    )
    result = await aresolve_repo_and_mr(
        "https://gitlab.example.com/group/proj/-/merge_requests/123"
    )
    assert result is None


async def test_aresolve_repo_non_mr_url_none():
    """非 MR/PR URL → None（parse 先行短路）。"""
    assert await aresolve_repo_and_mr("https://github.com/owner/repo") is None
