"""PR-01 守护测试：多仓 wave 收尾时各仓 MR 的 `target_branch` 取值（Phase 46-01）。

直测私有方法 `AICodingNode._create_mr_for_repo`（无需走完整 execute）：
mock `aresolve_git_token` / `get_git_platform_client`，捕获传入
`client.create_merge_request` 的 `MRCreateRequest`，断言 `target_branch`。

覆盖：
- per-repo：各仓 `target_branch` = 各仓自己的 `Repository.default_branch`
  （**非** "main"、**非** 第一个仓的值）。
- 零回归：`default_branch == base_branch == "main"` → `target_branch == "main"`（D-14）。
- fallback 链：`default_branch` 空 → 退 `base_branch`，再退 `"main"`。
- 缺凭证 fail-soft：token 为 None → 返回 error、不调 client、不抛（D-15）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.git_platform import MRCreateResult
from workflows.nodes.ai.coding import AICodingNode

pytestmark = [pytest.mark.asyncio]


def _make_repo(default_branch: str, name: str = "repo") -> MagicMock:
    """构造仓库替身（仅设 _create_mr_for_repo 实际访问的字段）。"""
    repo = MagicMock()
    repo.id = uuid4()
    repo.name = name
    repo.default_branch = default_branch
    repo.git_url = "https://github.com/org/%s.git" % name
    repo.git_platform = "github"
    return repo


def _make_client() -> AsyncMock:
    """构造 git 平台 client 替身，create_merge_request 返回成功结果。"""
    client = AsyncMock()
    client.create_merge_request.return_value = MRCreateResult(
        success=True,
        mr_url="https://github.com/org/repo/pull/1",
        mr_id="1",
        has_conflicts=False,
    )
    # IDEMP-02：默认无既有 open MR，确保走创建路径（否则 AsyncMock 自动桩会被
    # 误判为命中既有 MR 而跳过 create_merge_request，干扰 target_branch 断言）。
    client.find_open_merge_request = AsyncMock(return_value=None)
    return client


async def _call_create_mr(
    repository: MagicMock,
    base_branch: str,
    *,
    token: str | None = "tok",
    client: AsyncMock | None = None,
) -> tuple[dict[str, Any], AsyncMock | None]:
    """调 _create_mr_for_repo，打桩 token / client，返回 (结果, client)。"""
    node = AICodingNode()

    async def _fake_token(*args: Any, **kwargs: Any) -> str | None:
        return token

    get_client_mock = MagicMock(return_value=client)
    with (
        patch("workflows.nodes.ai.coding.aresolve_git_token", _fake_token),
        patch("workflows.nodes.ai.coding.get_git_platform_client", get_client_mock),
    ):
        result = await node._create_mr_for_repo(
            repository=repository,
            branch_name="friday/task-1",
            base_branch=base_branch,
            plan_title="测试方案",
            tasks_completed=["任务 A"],
            changes_summary={"files_changed": 1, "insertions": 2, "deletions": 0},
        )
    return result, (client if get_client_mock.called else None)


async def test_per_repo_target_branch_uses_own_default_branch() -> None:
    """各仓 target_branch 用各仓自己的 default_branch（非 "main"、非第一个仓的值）。"""
    repo_a = _make_repo(default_branch="develop", name="repo-a")
    repo_b = _make_repo(default_branch="release/x", name="repo-b")

    client_a = _make_client()
    client_b = _make_client()

    await _call_create_mr(repo_a, base_branch="main", client=client_a)
    await _call_create_mr(repo_b, base_branch="main", client=client_b)

    request_a = client_a.create_merge_request.call_args.args[0]
    request_b = client_b.create_merge_request.call_args.args[0]

    assert request_a.target_branch == "develop"
    assert request_b.target_branch == "release/x"


async def test_zero_regression_same_default_branch() -> None:
    """default_branch == base_branch == "main" → target_branch == "main"（D-14 逐字等价）。"""
    repo = _make_repo(default_branch="main")
    client = _make_client()

    await _call_create_mr(repo, base_branch="main", client=client)

    request = client.create_merge_request.call_args.args[0]
    assert request.target_branch == "main"


async def test_zero_regression_fallback_when_no_default_branch() -> None:
    """default_branch 空时退 base_branch；base_branch 也空时退 "main"。"""
    # fallback 链第二级：default_branch 空 → 用 base_branch
    repo1 = _make_repo(default_branch="")
    client1 = _make_client()
    await _call_create_mr(repo1, base_branch="release/y", client=client1)
    request1 = client1.create_merge_request.call_args.args[0]
    assert request1.target_branch == "release/y"

    # fallback 链最终兜底：default_branch 与 base_branch 均空 → "main"
    repo2 = _make_repo(default_branch="")
    client2 = _make_client()
    await _call_create_mr(repo2, base_branch="", client=client2)
    request2 = client2.create_merge_request.call_args.args[0]
    assert request2.target_branch == "main"


async def test_no_credential_fail_soft() -> None:
    """token 为 None → 返回 error、mr_url 空、不调 get_git_platform_client、不抛（D-15）。"""
    repo = _make_repo(default_branch="develop")

    result, client = await _call_create_mr(repo, base_branch="main", token=None)

    assert result["error"]
    assert result["mr_url"] == ""
    assert client is None
