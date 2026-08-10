"""MCP / mr_service 建 MR 安全扫描挂点（TAINT-02；D-04 / D-06）。

与 ``test_coding_security_scan`` 共用 ``attach_security_scan_pending``。
⛔ 不得改 ``mcp/`` submodule；⛔ 不得改 ``repo_router_v2.py``。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.code_graph.security_scan_report import SECURITY_SECTION_MARKER
from services.git_platform.models import MRCreateRequest, MRCreateResult

pytestmark = [pytest.mark.asyncio]


_SOURCE_SHA = "a" * 40
_TARGET_SHA = "b" * 40


class _FakeGitClient:
    def __init__(self, branch_shas: dict[str, str] | None = None) -> None:
        self.last_request: MRCreateRequest | None = None
        self._branch_shas = (
            branch_shas if branch_shas is not None else {"feat/x": _SOURCE_SHA, "main": _TARGET_SHA}
        )

    async def create_merge_request(self, request: MRCreateRequest) -> MRCreateResult:
        self.last_request = request
        return MRCreateResult(
            success=True,
            mr_id="42",
            mr_url="https://example.com/mr/42",
        )

    async def resolve_branch_sha(self, branch_name: str) -> str:
        return self._branch_shas.get(branch_name, "")


def _repo(*, name: str = "demo") -> MagicMock:
    repo = MagicMock()
    repo.id = uuid4()
    repo.name = name
    repo.default_branch = "main"
    return repo


async def test_mcp_create_mr_appends_security_scan_and_enqueues() -> None:
    """MCP create_mr 缝调 append + enqueue；不阻断建 MR。

    （Req: TAINT-02, 决策: D-06）
    """
    from mcp_tools import merge_request_service as mrs

    client = _FakeGitClient()
    user = MagicMock(id=3)
    enqueue = AsyncMock(return_value="job-mcp")

    with (
        patch.object(mrs, "_get_client", new=AsyncMock(return_value=client)),
        patch(
            "services.code_graph.impact_report.build_impact_report_section",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "services.code_graph.semgrep_enqueue.enqueue_semgrep_scan",
            new=enqueue,
        ),
    ):
        payload = await mrs.create_merge_request(
            repository=_repo(),
            source_branch="feat/x",
            target_branch="main",
            title="feat: x",
            description="## Custom\n\nhello",
            reviewer_usernames=[],
            remove_source_branch=True,
            trace=None,
            user=user,
        )

    assert payload["success"]
    assert client.last_request is not None
    desc = client.last_request.description
    assert SECURITY_SECTION_MARKER in desc
    assert "`pending`" in desc
    enqueue.assert_awaited()
    assert "sgp_" not in desc
    # CR-01：入队 payload 必须携带解析出的两端真实 sha，⛔ 不得为空
    kwargs = enqueue.await_args.kwargs
    assert kwargs["source_sha"] == _SOURCE_SHA
    assert kwargs["target_sha"] == _TARGET_SHA


async def test_mcp_create_mr_skips_enqueue_when_sha_unresolvable() -> None:
    """MCP 挂点两端 sha 解析不到时跳过入队，MR 仍照常创建。

    （Req: TAINT-01, 决策: D-04）
    """
    from mcp_tools import merge_request_service as mrs

    client = _FakeGitClient(branch_shas={})
    enqueue = AsyncMock(return_value="job-never")

    with (
        patch.object(mrs, "_get_client", new=AsyncMock(return_value=client)),
        patch(
            "services.code_graph.impact_report.build_impact_report_section",
            new=AsyncMock(return_value=""),
        ),
        patch("services.code_graph.semgrep_enqueue.enqueue_semgrep_scan", new=enqueue),
        patch(
            "services.repo_mirror.ensure_mirror_commit",
            new=AsyncMock(side_effect=RuntimeError("mirror down")),
        ),
    ):
        payload = await mrs.create_merge_request(
            repository=_repo(),
            source_branch="feat/x",
            target_branch="main",
            title="feat: x",
            description="## Custom\n\nhello",
            reviewer_usernames=[],
            remove_source_branch=True,
            trace=None,
            user=MagicMock(id=3),
        )

    assert payload["success"]
    enqueue.assert_not_awaited()


async def test_mr_service_enqueues_commit_sha_and_resolved_target() -> None:
    """mr_service 挂点：source 复用 commit_sha，target 经 client 解析，两端均非空。

    （Req: TAINT-01, 决策: D-04）
    """
    from workflows.services import mr_service

    repo = _repo(name="svc")
    repo.default_branch = "develop"
    user = MagicMock(id=9)
    task = MagicMock()
    task.id = uuid4()
    task.name = "feat: demo"
    task.repository = repo
    task.metadata = {}
    execution = MagicMock()
    execution.triggered_by = user
    execution.triggered_by_id = user.id
    task.workflow_execution = execution

    client = AsyncMock()
    client.create_merge_request.return_value = MRCreateResult(
        success=True,
        mr_url="https://example.com/mr/9",
        mr_id="9",
        has_conflicts=False,
    )
    client.resolve_branch_sha = AsyncMock(
        side_effect=lambda branch: _TARGET_SHA if branch == "develop" else ""
    )
    enqueue = AsyncMock(return_value="job-svc")

    async def _fake_token(*args: Any, **kwargs: Any) -> str:
        return "tok"

    with (
        patch("workflows.services.mr_service.aresolve_git_token", _fake_token),
        patch(
            "workflows.services.mr_service.get_git_platform_client",
            MagicMock(return_value=client),
        ),
        patch(
            "services.code_graph.impact_report.build_impact_report_section",
            new=AsyncMock(return_value=""),
        ),
        patch("services.code_graph.semgrep_enqueue.enqueue_semgrep_scan", new=enqueue),
    ):
        result = await mr_service.create_mr_for_task(
            task=task,
            branch_name="friday/task-2",
            commit_sha=_SOURCE_SHA,
            modified_files=["x.py"],
            target_branch="develop",
        )

    assert result.success
    enqueue.assert_awaited_once()
    kwargs = enqueue.await_args.kwargs
    assert kwargs["source_sha"] == _SOURCE_SHA
    assert kwargs["target_sha"] == _TARGET_SHA
    # source 侧已有完整 sha → 不必再问平台
    assert all(
        call.args[0] != "friday/task-2" for call in client.resolve_branch_sha.await_args_list
    )


async def test_mr_service_security_scan_shell_failure_is_fail_open() -> None:
    """mr_service 路径 shell/scan 失败 fail-open，不阻断建 MR。

    （Req: TAINT-02, 决策: D-04/D-06；威胁: T-127-02）
    """
    from workflows.services import mr_service

    repo = _repo(name="svc")
    repo.default_branch = "develop"
    user = MagicMock(id=9)
    task = MagicMock()
    task.id = uuid4()
    task.name = "feat: demo"
    task.repository = repo
    task.metadata = {}
    execution = MagicMock()
    execution.triggered_by = user
    execution.triggered_by_id = user.id
    task.workflow_execution = execution

    client = AsyncMock()
    client.create_merge_request.return_value = MRCreateResult(
        success=True,
        mr_url="https://example.com/mr/9",
        mr_id="9",
        has_conflicts=False,
    )

    async def _fake_token(*args: Any, **kwargs: Any) -> str:
        return "tok"

    with (
        patch("workflows.services.mr_service.aresolve_git_token", _fake_token),
        patch(
            "workflows.services.mr_service.get_git_platform_client",
            MagicMock(return_value=client),
        ),
        patch(
            "services.code_graph.impact_report.build_impact_report_section",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "services.code_graph.security_scan_report.attach_security_scan_pending",
            new=AsyncMock(side_effect=RuntimeError("security down")),
        ),
    ):
        soft = await mr_service.create_mr_for_task(
            task=task,
            branch_name="friday/task-2",
            commit_sha="a" * 40,
            modified_files=["x.py"],
            target_branch="develop",
        )

    assert soft.success
    client.create_merge_request.assert_awaited_once()
