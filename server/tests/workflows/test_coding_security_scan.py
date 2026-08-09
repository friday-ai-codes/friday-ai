"""AICodingNode / mr_service 建 MR 路径安全扫描附加（TAINT-02 / D-04 / D-06）。

直调 ``_create_mr_for_repo`` / ``create_mr_for_task``；mock git client +
``attach_security_scan_pending`` / enqueue，验证 append 与 fail-soft 不阻断建 MR。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.code_graph.security_scan_report import SECURITY_SECTION_MARKER
from services.git_platform import MRCreateResult
from workflows.nodes.ai.coding import AICodingNode

pytestmark = [pytest.mark.asyncio]

_PENDING_STUB = (
    f"{SECURITY_SECTION_MARKER}\n\n"
    "_安全扫描未能生成（`pending`）。MR 已照常创建，请人工复核（advisory，不阻断合并）。_\n"
)


def _make_repo(default_branch: str = "main", name: str = "repo") -> MagicMock:
    repo = MagicMock()
    repo.id = uuid4()
    repo.name = name
    repo.default_branch = default_branch
    repo.git_url = f"https://github.com/org/{name}.git"
    repo.git_platform = "github"
    return repo


def _make_client() -> AsyncMock:
    client = AsyncMock()
    client.create_merge_request.return_value = MRCreateResult(
        success=True,
        mr_url="https://github.com/org/repo/pull/1",
        mr_id="1",
        has_conflicts=False,
    )
    client.find_open_merge_request = AsyncMock(return_value=None)
    return client


async def _call_create_mr(
    repository: MagicMock,
    *,
    client: AsyncMock,
    user: Any = None,
    token: str | None = "tok",
) -> dict[str, Any]:
    node = AICodingNode()

    async def _fake_token(*args: Any, **kwargs: Any) -> str | None:
        return token

    with (
        patch("workflows.nodes.ai.coding.aresolve_git_token", _fake_token),
        patch("workflows.nodes.ai.coding.get_git_platform_client", MagicMock(return_value=client)),
        patch(
            "services.code_graph.impact_report.build_impact_report_section",
            new=AsyncMock(return_value=""),
        ),
    ):
        return await node._create_mr_for_repo(
            repository=repository,
            branch_name="friday/task-1",
            base_branch="main",
            plan_title="测试方案",
            tasks_completed=["任务 A"],
            changes_summary={"files_changed": 1, "insertions": 2, "deletions": 0},
            user=user,
        )


async def test_coding_create_mr_appends_security_scan_and_enqueues() -> None:
    """coding 缝调 append + enqueue；不阻断建 MR。

    （Req: TAINT-02, 决策: D-06）
    """
    repo = _make_repo()
    client = _make_client()
    user = MagicMock(id=7)
    enqueue = AsyncMock(return_value="job-1")

    with (
        patch(
            "services.code_graph.semgrep_enqueue.enqueue_semgrep_scan",
            new=enqueue,
        ),
    ):
        result = await _call_create_mr(repo, client=client, user=user)

    client.create_merge_request.assert_awaited_once()
    request = client.create_merge_request.call_args.args[0]
    assert SECURITY_SECTION_MARKER in request.description
    assert "`pending`" in request.description
    assert result.get("mr_url")
    enqueue.assert_awaited()
    assert enqueue.await_args is not None
    called_repo = (
        enqueue.await_args.args[0]
        if enqueue.await_args.args
        else enqueue.await_args.kwargs.get("repository_id")
    )
    assert str(called_repo) == str(repo.id)
    assert "sgp_" not in request.description


async def test_coding_security_scan_shell_failure_is_fail_open() -> None:
    """coding 路径 shell/scan 失败 fail-open，不阻断建 MR。

    （Req: TAINT-02, 决策: D-04/D-06；威胁: T-127-02）
    """
    repo = _make_repo()
    client = _make_client()

    with patch(
        "services.code_graph.security_scan_report.attach_security_scan_pending",
        new=AsyncMock(side_effect=RuntimeError("scan shell boom")),
    ):
        result = await _call_create_mr(repo, client=client, user=MagicMock(id=1))

    client.create_merge_request.assert_awaited_once()
    assert result.get("mr_url")
    assert not result.get("error")
