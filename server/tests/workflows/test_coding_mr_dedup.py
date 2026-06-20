"""IDEMP-02 守护测试：`_create_mr_for_repo` 创建前 existing-MR fence（Phase 63-03）。

直测私有方法 `AICodingNode._create_mr_for_repo`（镜像 test_coding_pr_target_branch.py）：
mock `aresolve_git_token` / `get_git_platform_client`，控制 client.find_open_merge_request
返回值，断言"命中复用不重复创建 / 无既有照常创建 / fence 失败照常创建"。

覆盖：
- reuse：find_open_merge_request 命中 open MR → 复用 mr_url/mr_id，**不调** create_merge_request。
- create：find_open_merge_request 返回 None → 照常调 create_merge_request 一次（现状路径）。
- fail-soft：find_open_merge_request 返回 None（内部已 swallow 异常）→ 仍走创建，不阻断。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.git_platform import MRCreateResult
from workflows.nodes.ai.coding import AICodingNode

pytestmark = [pytest.mark.asyncio]


def _make_repo(default_branch: str = "main", name: str = "repo") -> MagicMock:
    """构造仓库替身（仅设 _create_mr_for_repo 实际访问的字段）。"""
    repo = MagicMock()
    repo.id = uuid4()
    repo.name = name
    repo.default_branch = default_branch
    repo.git_url = "https://github.com/org/%s.git" % name
    repo.git_platform = "github"
    return repo


def _make_client(find_return: MRCreateResult | None) -> AsyncMock:
    """构造 git 平台 client 替身。

    create_merge_request 返回成功结果；find_open_merge_request 返回指定值
    （None 表示无既有 MR / fence 内部已 fail-soft）。
    """
    client = AsyncMock()
    client.create_merge_request.return_value = MRCreateResult(
        success=True,
        mr_url="https://github.com/org/repo/pull/99",
        mr_id="99",
        has_conflicts=False,
    )
    client.find_open_merge_request = AsyncMock(return_value=find_return)
    return client


async def _call_create_mr(
    repository: MagicMock,
    *,
    client: AsyncMock,
    base_branch: str = "main",
) -> dict[str, Any]:
    """调 _create_mr_for_repo，打桩 token / client，返回结果 dict。"""
    node = AICodingNode()

    async def _fake_token(*args: Any, **kwargs: Any) -> str | None:
        return "tok"

    with (
        patch("workflows.nodes.ai.coding.aresolve_git_token", _fake_token),
        patch(
            "workflows.nodes.ai.coding.get_git_platform_client",
            MagicMock(return_value=client),
        ),
    ):
        return await node._create_mr_for_repo(
            repository=repository,
            branch_name="friday/task-1",
            base_branch=base_branch,
            plan_title="测试方案",
            tasks_completed=["任务 A"],
            changes_summary={"files_changed": 1, "insertions": 2, "deletions": 0},
        )


async def test_mr_dedup_reuse() -> None:
    """命中既有 open MR → 复用 mr_url/mr_id，且 create_merge_request 未被调用。"""
    repo = _make_repo(default_branch="main")
    client = _make_client(
        find_return=MRCreateResult(success=True, mr_url="http://x/mr/1", mr_id="1"),
    )

    result = await _call_create_mr(repo, client=client)

    assert result["mr_url"] == "http://x/mr/1"
    assert result["mr_id"] == "1"
    assert result["deduplicated"] is True
    client.find_open_merge_request.assert_awaited_once_with("friday/task-1", "main")
    client.create_merge_request.assert_not_awaited()


async def test_mr_create_when_none() -> None:
    """无既有 open MR（find 返回 None）→ 照常调 create_merge_request 一次。"""
    repo = _make_repo(default_branch="main")
    client = _make_client(find_return=None)

    result = await _call_create_mr(repo, client=client)

    assert result["mr_url"] == "https://github.com/org/repo/pull/99"
    assert result["mr_id"] == "99"
    assert "deduplicated" not in result
    client.create_merge_request.assert_awaited_once()


async def test_mr_fence_failsoft() -> None:
    """find_open_merge_request fail-soft 返回 None（内部已 swallow）→ 仍走创建不阻断。"""
    repo = _make_repo(default_branch="main")
    client = _make_client(find_return=None)

    result = await _call_create_mr(repo, client=client)

    assert result["mr_url"] == "https://github.com/org/repo/pull/99"
    client.find_open_merge_request.assert_awaited_once()
    client.create_merge_request.assert_awaited_once()
