"""chat 链完工闭环测试（101-03 / LOOP-02/03）：create_pr_or_skip_node 回写 + 提炼。

节点级测试（参照 test_coding_session_graph 的 mock 构造方式），IO 边界全 patch：

- PR 成功 + 三元组可反查 → awrite_back 一次（入参正确）+ 提炼调度一次，返回值不变；
- PR 成功 + 三元组 None → 不回写、提炼仍调度、返回值不变（零回归）;
- skip-PR → 不回写（CONTEXT 锁定）、提炼照常调度、branch_url 返回不变；
- 闭环块内抛异常（反查器 raise）→ 节点返回值不变（fail-soft）。
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from delivery.services.coding_completion import CompletionWritebackService, WorkItemTriple
from orchestration.coding_graph import create_pr_or_skip_node

_TRIPLE = WorkItemTriple(
    feishu_project_key="chat-key",
    work_item_type="story",
    work_item_id=66,
    title="Chat 编码需求",
    space_id=None,
)


# ---------------------------------------------------------------------------
# Fixtures / harness
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_coding_session() -> MagicMock:
    """mock CodingSession（含 subagent_session.session_id 真实字符串）。"""
    session = MagicMock()
    session.id = "cs-completion-1"
    session.coding_plan = None
    session.coding_plan_id = None
    session.tech_plan = "## 技术方案\n- 步骤 1"
    session.repository.name = "chat-repo"
    session.repository.git_url = "https://github.com/test/chat-repo.git"
    session.repository.git_platform = "github"
    session.repository.default_branch = "main"
    session.branch_name = "feat/chat-x"
    session.target_branch = "main"
    session.pr_url = ""
    session.subagent_session_id = 42
    session.subagent_session.session_id = "sub-chat-1"
    session.amark_completed = AsyncMock()
    session.amark_failed = AsyncMock()
    return session


@pytest.fixture()
def awrite_back_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _fake(self: Any, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        calls.append(kwargs)
        return {"status": "skipped"}, {"status": "written"}

    monkeypatch.setattr(CompletionWritebackService, "awrite_back", _fake)
    return calls


@pytest.fixture()
def bg_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _fake(factory: Any, *, name: str | None = None, initiated_by_user_id: str | None = None):
        calls.append({"name": name, "initiated_by_user_id": initiated_by_user_id})
        factory().close()  # 避免 un-awaited coroutine 警告
        return MagicMock()

    monkeypatch.setattr("services.background_runner.run_in_background", _fake)
    return calls


def _patch_resolver(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    if isinstance(result, Exception):

        async def _resolve(_session: Any) -> None:
            raise result
    else:

        async def _resolve(_session: Any) -> Any:
            return result

    monkeypatch.setattr(
        "delivery.services.coding_completion.aresolve_triple_for_coding_session",
        _resolve,
    )


@contextlib.contextmanager
def _patch_node_io(mock_session: MagicMock) -> Any:
    """patch 节点 IO：session 反查 / 结果消息 / ingestion / git 平台。"""
    from services.git_platform.models import MRCreateResult

    async def _noop_ingest(*args: Any, **kwargs: Any) -> None:
        return None

    mock_platform_client = AsyncMock()
    mock_platform_client.create_merge_request = AsyncMock(
        return_value=MRCreateResult(
            success=True, mr_url="https://github.com/test/chat-repo/pull/7", mr_id="7"
        )
    )

    with (
        patch(
            "orchestration.coding_graph._get_coding_session",
            new_callable=AsyncMock,
            return_value=mock_session,
        ),
        patch(
            "chat.coding_events.store_coding_complete_to_message",
            new_callable=AsyncMock,
        ) as mock_store,
        patch("knowledge.ingestion.aschedule_ingestion", _noop_ingest),
        patch(
            "services.git_credentials.aresolve_git_token",
            new_callable=AsyncMock,
            return_value="test-token",
        ),
        patch(
            "services.git_platform.get_git_platform_client",
            return_value=mock_platform_client,
        ),
    ):
        yield mock_store


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pr_created_with_triple_writes_back_and_schedules_extraction(
    monkeypatch: pytest.MonkeyPatch,
    mock_coding_session: MagicMock,
    awrite_back_calls: list[dict[str, Any]],
    bg_calls: list[dict[str, Any]],
) -> None:
    """PR 成功 + 三元组可反查 → 回写一次 + 提炼调度一次，返回值不变。"""
    _patch_resolver(monkeypatch, _TRIPLE)

    with _patch_node_io(mock_coding_session):
        result = await create_pr_or_skip_node(
            {
                "coding_session_id": "cs-completion-1",
                "skip_pr": False,
                "confirmed_pr_title": "feat: chat",
                "confirmed_pr_description": "desc",
                "target_branch": "main",
            }
        )

    assert result == {"phase": "completed", "pr_url": "https://github.com/test/chat-repo/pull/7"}
    assert len(awrite_back_calls) == 1
    call = awrite_back_calls[0]
    assert call["feishu_project_key"] == "chat-key"
    assert call["work_item_type"] == "story"
    assert call["work_item_id"] == 66
    assert call["title"] == "编码任务"  # coding_plan=None → 兜底文案
    assert len(call["results"]) == 1
    assert call["results"][0].repo_name == "chat-repo"
    assert call["results"][0].status == "completed"
    assert call["results"][0].mr_url == "https://github.com/test/chat-repo/pull/7"
    assert [c["name"] for c in bg_calls] == ["learning-case-sub-chat-1"]


@pytest.mark.asyncio
async def test_pr_created_without_triple_skips_writeback_but_extracts(
    monkeypatch: pytest.MonkeyPatch,
    mock_coding_session: MagicMock,
    awrite_back_calls: list[dict[str, Any]],
    bg_calls: list[dict[str, Any]],
) -> None:
    """PR 成功 + 三元组 None → 不回写（自然跳过）、提炼仍调度、返回值不变（零回归）。"""
    _patch_resolver(monkeypatch, None)

    with _patch_node_io(mock_coding_session):
        result = await create_pr_or_skip_node(
            {
                "coding_session_id": "cs-completion-1",
                "skip_pr": False,
                "confirmed_pr_title": "feat: chat",
                "confirmed_pr_description": "desc",
                "target_branch": "main",
            }
        )

    assert result == {"phase": "completed", "pr_url": "https://github.com/test/chat-repo/pull/7"}
    assert awrite_back_calls == []
    assert [c["name"] for c in bg_calls] == ["learning-case-sub-chat-1"]


@pytest.mark.asyncio
async def test_skip_pr_never_writes_back_but_extracts(
    monkeypatch: pytest.MonkeyPatch,
    mock_coding_session: MagicMock,
    awrite_back_calls: list[dict[str, Any]],
    bg_calls: list[dict[str, Any]],
) -> None:
    """skip-PR 分支：不回写（CONTEXT 锁定）、提炼照常调度、branch_url 返回不变。"""
    _patch_resolver(monkeypatch, _TRIPLE)

    with _patch_node_io(mock_coding_session):
        result = await create_pr_or_skip_node(
            {
                "coding_session_id": "cs-completion-1",
                "skip_pr": True,
            }
        )

    assert result["phase"] == "completed"
    assert "branch_url" in result
    assert "github.com" in result["branch_url"]
    assert awrite_back_calls == []
    assert [c["name"] for c in bg_calls] == ["learning-case-sub-chat-1"]
    mock_coding_session.amark_completed.assert_awaited_once()


@pytest.mark.asyncio
async def test_completion_loop_exception_does_not_change_node_result(
    monkeypatch: pytest.MonkeyPatch,
    mock_coding_session: MagicMock,
    awrite_back_calls: list[dict[str, Any]],
    bg_calls: list[dict[str, Any]],
) -> None:
    """闭环块内抛异常（反查器 raise）→ 节点返回值不变（fail-soft）。"""
    _patch_resolver(monkeypatch, RuntimeError("resolver exploded"))

    with _patch_node_io(mock_coding_session):
        result = await create_pr_or_skip_node(
            {
                "coding_session_id": "cs-completion-1",
                "skip_pr": False,
                "confirmed_pr_title": "feat: chat",
                "confirmed_pr_description": "desc",
                "target_branch": "main",
            }
        )

    assert result == {"phase": "completed", "pr_url": "https://github.com/test/chat-repo/pull/7"}
    assert awrite_back_calls == []
    assert bg_calls == []
