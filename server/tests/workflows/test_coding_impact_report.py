"""AICodingNode / mr_service 建 MR 路径影响面附加（DIFF-04 / D-06 / D-09）。

直调 ``_create_mr_for_repo`` / ``create_mr_for_task``；mock git client +
``build_impact_report_section``，验证 append 与 fail-soft 不阻断建 MR。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.code_graph.impact_report import IMPACT_SECTION_MARKER
from services.git_platform import MRCreateResult
from workflows.nodes.ai.coding import AICodingNode

pytestmark = [pytest.mark.asyncio]

_FOUR_SECTION = (
    f"{IMPACT_SECTION_MARKER}\n\n"
    "### Changes\n\n- `a.py` (modified)\n\n"
    "### Affected\n\n- （无 impact 种子 / 未展开）\n\n"
    "### Risk\n\n- **LOW**\n\n"
    "### Recommendations\n\n- 按常规 code review 复核变更影响即可\n"
)

_TIMEOUT_STUB = (
    f"{IMPACT_SECTION_MARKER}\n\n"
    "_影响面报告未能生成（`timeout`）。MR 已照常创建，请人工复核变更影响。_\n"
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


async def test_create_mr_appends_impact_section() -> None:
    """``_create_mr_for_repo`` 成功路径 description 含 ``## 影响面`` 段。"""
    repo = _make_repo()
    client = _make_client()
    user = MagicMock(id=7)

    with patch(
        "services.code_graph.impact_report.build_impact_report_section",
        new=AsyncMock(return_value=_FOUR_SECTION),
    ) as build_mock:
        result = await _call_create_mr(repo, client=client, user=user)

    client.create_merge_request.assert_awaited_once()
    request = client.create_merge_request.call_args.args[0]
    assert IMPACT_SECTION_MARKER in request.description
    assert "### Changes" in request.description
    assert "### Affected" in request.description
    assert "### Risk" in request.description
    assert "### Recommendations" in request.description
    assert IMPACT_SECTION_MARKER in (result.get("description") or "")
    build_mock.assert_awaited_once()
    kwargs = build_mock.await_args.kwargs
    assert kwargs["compare"] == "friday/task-1"
    assert kwargs["base_ref"] == "main"
    assert kwargs["user"] is user


async def test_create_mr_failsoft_on_impact_error() -> None:
    """影响面 helper 异常仍调用 ``create_merge_request``（D-09）。"""
    repo = _make_repo()
    client = _make_client()

    with patch(
        "services.code_graph.impact_report.build_impact_report_section",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await _call_create_mr(repo, client=client, user=MagicMock(id=1))

    client.create_merge_request.assert_awaited_once()
    assert result.get("mr_url")
    assert not result.get("error")


async def test_create_mr_description_contains_stub_on_timeout() -> None:
    """超时 → description 含 stub ``timeout``（D-10/D-11）。"""
    repo = _make_repo()
    client = _make_client()

    with patch(
        "services.code_graph.impact_report.build_impact_report_section",
        new=AsyncMock(return_value=_TIMEOUT_STUB),
    ):
        result = await _call_create_mr(repo, client=client, user=MagicMock(id=1))

    request = client.create_merge_request.call_args.args[0]
    assert IMPACT_SECTION_MARKER in request.description
    assert "`timeout`" in request.description
    assert IMPACT_SECTION_MARKER in (result.get("description") or "")


def _make_task(repository: MagicMock, *, user: Any = None) -> MagicMock:
    task = MagicMock()
    task.id = uuid4()
    task.name = "feat: demo"
    task.repository = repository
    task.metadata = {}
    execution = MagicMock()
    execution.triggered_by = user
    execution.triggered_by_id = getattr(user, "id", None)
    task.workflow_execution = execution
    return task


async def test_create_mr_for_task_failsoft_appends_impact() -> None:
    """``mr_service.create_mr_for_task``：成功 append；helper 异常仍建 MR。"""
    from workflows.services import mr_service

    repo = _make_repo(default_branch="develop")
    user = MagicMock(id=9)
    task = _make_task(repo, user=user)
    client = _make_client()

    async def _fake_token(*args: Any, **kwargs: Any) -> str:
        return "tok"

    with (
        patch("workflows.services.mr_service.aresolve_git_token", _fake_token),
        patch("workflows.services.mr_service.get_git_platform_client", MagicMock(return_value=client)),
        patch(
            "services.code_graph.impact_report.build_impact_report_section",
            new=AsyncMock(return_value=_FOUR_SECTION),
        ) as build_ok,
    ):
        ok = await mr_service.create_mr_for_task(
            task=task,
            branch_name="friday/task-2",
            commit_sha="a" * 40,
            modified_files=["x.py"],
            target_branch="develop",
        )

    assert ok.success
    client.create_merge_request.assert_awaited_once()
    desc_ok = client.create_merge_request.call_args.args[0].description
    assert IMPACT_SECTION_MARKER in desc_ok
    assert "### Changes" in desc_ok
    build_ok.assert_awaited_once()
    assert build_ok.await_args.kwargs["compare"] == "friday/task-2"
    assert build_ok.await_args.kwargs["base_ref"] == "develop"

    client2 = _make_client()
    with (
        patch("workflows.services.mr_service.aresolve_git_token", _fake_token),
        patch(
            "workflows.services.mr_service.get_git_platform_client",
            MagicMock(return_value=client2),
        ),
        patch(
            "services.code_graph.impact_report.build_impact_report_section",
            new=AsyncMock(side_effect=RuntimeError("impact down")),
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
    client2.create_merge_request.assert_awaited_once()
