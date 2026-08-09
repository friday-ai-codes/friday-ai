"""MCP ``create_merge_request`` 影响面附加 + workflow↔MCP 对等哨兵（DIFF-04 / D-14）。

与 ``test_coding_impact_report`` 共用 ``build_impact_report_section``。
⛔ 不得改 ``mcp/`` submodule；⛔ 不得改 ``repo_router_v2.py``（D-16）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.code_graph.impact_report import IMPACT_SECTION_MARKER
from services.git_platform.models import MRCreateRequest, MRCreateResult

pytestmark = [pytest.mark.asyncio]

_FOUR_SECTION = (
    f"{IMPACT_SECTION_MARKER}\n\n"
    "### Changes\n\n- `a.py` (modified)\n\n"
    "### Affected\n\n- （无 impact 种子 / 未展开）\n\n"
    "### Risk\n\n- **LOW**\n\n"
    "### Recommendations\n\n- 按常规 code review 复核变更影响即可\n"
)

_STUB = (
    f"{IMPACT_SECTION_MARKER}\n\n"
    "_影响面报告未能生成（`unavailable`）。MR 已照常创建，请人工复核变更影响。_\n"
)


class _FakeGitClient:
    def __init__(self) -> None:
        self.last_request: MRCreateRequest | None = None

    async def create_merge_request(self, request: MRCreateRequest) -> MRCreateResult:
        self.last_request = request
        return MRCreateResult(
            success=True,
            mr_id="42",
            mr_url="https://example.com/mr/42",
        )


def _repo(*, name: str = "demo") -> MagicMock:
    repo = MagicMock()
    repo.id = uuid4()
    repo.name = name
    repo.default_branch = "main"
    return repo


async def _create_mr(**overrides: Any) -> tuple[dict[str, Any], _FakeGitClient]:
    from mcp_tools import merge_request_service as mrs

    client = _FakeGitClient()
    user = overrides.pop("user", MagicMock(id=3))
    kwargs = {
        "repository": _repo(),
        "source_branch": "feat/x",
        "target_branch": "main",
        "title": "feat: x",
        "description": "",
        "reviewer_usernames": [],
        "remove_source_branch": True,
        "trace": None,
        "user": user,
    }
    kwargs.update(overrides)

    with (
        patch.object(mrs, "_get_client", new=AsyncMock(return_value=client)),
        patch(
            "services.code_graph.impact_report.build_impact_report_section",
            new=AsyncMock(return_value=_FOUR_SECTION),
        ) as build_mock,
    ):
        payload = await mrs.create_merge_request(**kwargs)
    return payload, client, build_mock  # type: ignore[return-value]


async def test_mcp_create_mr_appends_impact_section() -> None:
    """MCP 建 MR 缺省 description 路径追加 ``## 影响面``。"""
    payload, client, build_mock = await _create_mr(description="")
    assert payload["success"]
    assert client.last_request is not None
    desc = client.last_request.description
    assert IMPACT_SECTION_MARKER in desc
    assert "### Changes" in desc
    build_mock.assert_awaited_once()
    assert build_mock.await_args.kwargs["compare"] == "feat/x"
    assert build_mock.await_args.kwargs["base_ref"] == "main"


async def test_mcp_explicit_description_append_idempotent() -> None:
    """显式 description：无标记则 append；已含标记不重复。"""
    payload, client, _ = await _create_mr(description="## Custom\n\nhello")
    assert IMPACT_SECTION_MARKER in (client.last_request.description if client.last_request else "")
    assert (client.last_request.description or "").count(IMPACT_SECTION_MARKER) == 1
    assert payload["description"].count(IMPACT_SECTION_MARKER) == 1

    already = f"## Custom\n\n{_FOUR_SECTION}"
    payload2, client2, _ = await _create_mr(description=already)
    assert (client2.last_request.description or "").count(IMPACT_SECTION_MARKER) == 1
    assert payload2["description"].count(IMPACT_SECTION_MARKER) == 1


async def test_mcp_create_mr_failsoft_on_impact_error() -> None:
    """影响面失败仍创建 MR（D-09 fail-soft）。"""
    from mcp_tools import merge_request_service as mrs

    client = _FakeGitClient()
    with (
        patch.object(mrs, "_get_client", new=AsyncMock(return_value=client)),
        patch(
            "services.code_graph.impact_report.build_impact_report_section",
            new=AsyncMock(side_effect=RuntimeError("down")),
        ),
    ):
        payload = await mrs.create_merge_request(
            repository=_repo(),
            source_branch="feat/x",
            target_branch="main",
            title="t",
            description="base body",
            reviewer_usernames=[],
            remove_source_branch=True,
            user=MagicMock(id=1),
        )

    assert payload["success"]
    assert client.last_request is not None
    assert client.last_request.description == "base body" or IMPACT_SECTION_MARKER in (
        client.last_request.description or ""
    )


async def test_workflow_mcp_impact_section_parity() -> None:
    """同一 (repo, compare, base_ref, user) 下两侧以等价 kwargs 调共享 helper（D-14）。

    不再用固定 stub mock 自证；spy 记录 await kwargs，并对照未 patch 的
    ``build_impact_report_section`` stub 输出字节级稳定。
    """
    from mcp_tools import merge_request_service as mrs
    from services.code_graph.impact_report import build_impact_report_section
    from workflows.nodes.ai.coding import AICodingNode

    repo = _repo(name="parity-repo")
    user = MagicMock(id=11)
    compare = "friday/parity"
    base_ref = "develop"
    repo.default_branch = base_ref

    shared_section = _FOUR_SECTION
    spy_calls: list[dict[str, Any]] = []

    async def _spy_section(**kwargs: Any) -> str:
        spy_calls.append(
            {
                "repository": kwargs.get("repository"),
                "compare": kwargs.get("compare"),
                "base_ref": kwargs.get("base_ref"),
                "user": kwargs.get("user"),
            }
        )
        return shared_section

    mcp_client = _FakeGitClient()
    with (
        patch(
            "services.code_graph.impact_report.build_impact_report_section",
            new=AsyncMock(side_effect=_spy_section),
        ),
        patch.object(mrs, "_get_client", new=AsyncMock(return_value=mcp_client)),
    ):
        mcp_payload = await mrs.create_merge_request(
            repository=repo,
            source_branch=compare,
            target_branch=base_ref,
            title="parity",
            description="## MCP body",
            reviewer_usernames=[],
            remove_source_branch=True,
            user=user,
        )

    wf_client = AsyncMock()
    wf_client.create_merge_request.return_value = MRCreateResult(
        success=True, mr_url="https://example.com/pr/1", mr_id="1", has_conflicts=False
    )
    wf_client.find_open_merge_request = AsyncMock(return_value=None)
    node = AICodingNode()

    async def _tok(*_a: Any, **_k: Any) -> str:
        return "tok"

    with (
        patch(
            "services.code_graph.impact_report.build_impact_report_section",
            new=AsyncMock(side_effect=_spy_section),
        ),
        patch("workflows.nodes.ai.coding.aresolve_git_token", _tok),
        patch(
            "workflows.nodes.ai.coding.get_git_platform_client",
            MagicMock(return_value=wf_client),
        ),
    ):
        wf_result = await node._create_mr_for_repo(
            repository=repo,
            branch_name=compare,
            base_branch="main",
            plan_title="parity",
            tasks_completed=["a"],
            changes_summary={},
            user=user,
        )

    assert len(spy_calls) == 2
    mcp_kwargs, wf_kwargs = spy_calls
    assert mcp_kwargs["repository"] is repo
    assert wf_kwargs["repository"] is repo
    assert mcp_kwargs["compare"] == wf_kwargs["compare"] == compare
    assert mcp_kwargs["base_ref"] == wf_kwargs["base_ref"] == base_ref
    assert mcp_kwargs["user"] is user
    assert wf_kwargs["user"] is user

    mcp_desc = mcp_payload["description"]
    wf_desc = wf_client.create_merge_request.call_args.args[0].description
    assert shared_section.strip() in mcp_desc
    assert shared_section.strip() in wf_desc
    assert IMPACT_SECTION_MARKER in (wf_result.get("description") or "")

    # stub 字节级对等：未 patch helper，mock 编排失败 → 两侧同模板
    with patch(
        "services.code_graph.impact_report.run_detect_changes",
        new=AsyncMock(return_value={"ok": False, "error_code": "unavailable", "error": "parity"}),
    ):
        s1 = await build_impact_report_section(
            repository=repo, user=user, compare=compare, base_ref=base_ref
        )
        s2 = await build_impact_report_section(
            repository=repo, user=user, compare=compare, base_ref=base_ref
        )
    assert s1.strip() == s2.strip() == _STUB.strip()

    # user=None 短路径：同一 helper 两次输出仍字节稳定（ACL 身份缺口）
    s_none_a = await build_impact_report_section(
        repository=repo, user=None, compare=compare, base_ref=base_ref
    )
    s_none_b = await build_impact_report_section(
        repository=repo, user=None, compare=compare, base_ref=base_ref
    )
    assert s_none_a.strip() == s_none_b.strip()
    assert IMPACT_SECTION_MARKER in s_none_a
