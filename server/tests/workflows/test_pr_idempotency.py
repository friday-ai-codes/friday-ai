"""CreatePRNode 的 reuse-first 幂等围栏与查重失败处置。

背景：AICodingNode 早有 IDEMP-02 去重，CreatePRNode 却完全没有——节点重试、
手动 re-run、runner 超时重投都会在同一对分支上再开一个 PR，连带交叉引用、飞书
通知、review 沉淀一起重复。

另一个更隐蔽的问题：``find_open_merge_request`` 原先对「查了确实没有」和
「平台 API 出错」一律返回 None，调用方无从分辨。于是查重接口一抖动就被当成
「无既有 PR」继续创建——本该防重复的围栏反而成了制造重复件的入口。现在出错抛
``MergeRequestLookupFailed``，调用方显式失败交给重试兜底。
"""

from __future__ import annotations

import uuid

import pytest

from services.git_platform.models import MRCreateResult, MergeRequestLookupFailed
from workflows.nodes.git.pr import CreatePRNode


class _Repo:
    """最小 Repository 替身——只用到 id / name，避免起 DB。"""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.name = "demo-repo"


class _Client:
    def __init__(self, existing=None, lookup_error: Exception | None = None) -> None:
        self._existing = existing
        self._lookup_error = lookup_error
        self.create_called = 0

    async def find_open_merge_request(self, source_branch, target_branch):
        if self._lookup_error:
            raise self._lookup_error
        return self._existing

    async def create_merge_request(self, request):
        self.create_called += 1
        return MRCreateResult(success=True, mr_url="http://mr/new", mr_id="99")


@pytest.fixture
def patch_client(monkeypatch):
    """把 token 解析与平台 client 都替换掉，聚焦去重分支本身。"""

    def _apply(client: _Client):
        async def _fake_token(_repository):
            return "token"

        monkeypatch.setattr("workflows.nodes.git.pr.aresolve_git_token", _fake_token)
        monkeypatch.setattr(
            "workflows.nodes.git.pr.get_git_platform_client",
            lambda repository, token: client,
        )
        return client

    return _apply


@pytest.mark.asyncio
async def test_reuses_existing_open_pr_instead_of_creating_second(patch_client):
    """命中既有 open PR 时复用其 URL，且绝不再调 create。"""
    client = patch_client(
        _Client(existing=MRCreateResult(success=True, mr_url="http://mr/1", mr_id="1"))
    )

    result = await CreatePRNode()._create_pr_for_repository(
        _Repo(), "title", "body", "main", "feature/x", []
    )

    assert result["success"] is True
    assert result["pr_url"] == "http://mr/1"
    assert result["pr_id"] == "1"
    assert client.create_called == 0, "命中既有 PR 后仍然创建了新 PR —— 幂等围栏失效"


@pytest.mark.asyncio
async def test_creates_when_no_existing_pr(patch_client):
    """无既有 PR 时正常创建——围栏只拦重复，不改变正常路径。"""
    client = patch_client(_Client(existing=None))

    result = await CreatePRNode()._create_pr_for_repository(
        _Repo(), "title", "body", "main", "feature/x", []
    )

    assert result["success"] is True
    assert result["pr_url"] == "http://mr/new"
    assert client.create_called == 1


@pytest.mark.asyncio
async def test_lookup_failure_aborts_instead_of_creating_duplicate(patch_client):
    """查重失败必须显式中止，而不是当「无命中」继续创建。

    这是重复 PR 的根因场景：GitHub/GitLab 列表接口抖动 → 旧实现返回 None →
    调用方以为没有 → 再建一个。
    """
    client = patch_client(_Client(lookup_error=MergeRequestLookupFailed("API 503")))

    result = await CreatePRNode()._create_pr_for_repository(
        _Repo(), "title", "body", "main", "feature/x", []
    )

    assert result["success"] is False
    assert "去重查询失败" in result["error"]
    assert client.create_called == 0, "查重失败后仍创建 PR —— 会留下重复件"
