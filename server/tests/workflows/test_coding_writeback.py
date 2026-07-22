"""AICodingNode 完工闭环测试（101-03 / LOOP-02/03）。

覆盖 write_back 三态守门（P3 锁定，T-101-03-01）与提炼调度锚点：

- legacy fallback（config 无 write_back 键）+ 无三元组 → 不回写、无 writeback_skipped
  噪音（**存量零行为变化用例**）；
- legacy fallback + 三元组可反查 → 回写且入参三元组正确；
- 显式 False → 即使有三元组也不回写；
- 显式 True + 无三元组 → 不回写但记 ``writeback_skipped``（caller 事件）；
- 提炼调度：completed_session_ids 逐 session 经 run_in_background 调度（不 await）；
- 闭环块内抛异常 → NodeResult status 不受影响（fail-soft）。

IO 边界全 mock（awrite_back / run_in_background / 反查器 / MR 创建 / 通知 / 子步骤 /
ingestion）；Repository 走真实 DB（transaction=True）。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from structlog.testing import capture_logs

from delivery.services.coding_completion import CompletionWritebackService, WorkItemTriple
from repositories.models import Repository
from workflows.nodes.ai.coding import AICodingNode
from workflows.nodes.base import ExecutionContext, NodeResult

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

_TRIPLE = WorkItemTriple(
    feishu_project_key="wb-key",
    work_item_type="story",
    work_item_id=88,
    title="登录改造",
    space_id=None,
)


# ---------------------------------------------------------------------------
# Fixtures / harness
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    """INGEST-02 投递 noop（与本 plan 无关的既有锚点）。"""

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("knowledge.ingestion.aschedule_ingestion", _noop)


@pytest.fixture()
def awrite_back_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """patch 公共回写入口，捕获 kwargs。"""
    calls: list[dict[str, Any]] = []

    async def _fake(self: Any, **kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        calls.append(kwargs)
        return {"status": "skipped"}, {"status": "written"}

    monkeypatch.setattr(CompletionWritebackService, "awrite_back", _fake)
    return calls


@pytest.fixture()
def bg_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """patch run_in_background，捕获调度（factory 产生的 coroutine 立即 close）。"""
    calls: list[dict[str, Any]] = []

    def _fake(factory: Any, *, name: str | None = None, initiated_by_user_id: str | None = None):
        calls.append({"name": name, "initiated_by_user_id": initiated_by_user_id})
        factory().close()  # 避免 un-awaited coroutine 警告
        return MagicMock()

    monkeypatch.setattr("services.background_runner.run_in_background", _fake)
    return calls


def _patch_resolver(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    """patch plan_version 反查器：返回 triple/None 或抛异常。"""
    if isinstance(result, Exception):

        async def _resolve(_pid: Any) -> None:
            raise result
    else:

        async def _resolve(_pid: Any) -> Any:
            return result

    monkeypatch.setattr(
        "delivery.services.coding_completion.aresolve_triple_from_plan_version",
        _resolve,
    )


def _make_node() -> AICodingNode:
    node = AICodingNode()
    node.emit_sub_step = AsyncMock()  # type: ignore[method-assign]
    node._send_result_notification = AsyncMock()  # type: ignore[method-assign]

    async def _fake_mr(*, repository: Repository, **kwargs: Any) -> dict[str, Any]:
        return {"mr_url": f"https://mr/{repository.name}", "mr_id": "1"}

    node._create_mr_for_repo = AsyncMock(side_effect=_fake_mr)  # type: ignore[method-assign]
    return node


def _make_context(node_config: dict[str, Any]) -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-writeback",
        node_id="node-coding",
        node_config=node_config,
        input_data={},
        workflow_context={},
        previous_outputs={},
        trigger_data={},
        workflow_execution=None,
        node_execution=None,
    )


async def _make_repo() -> Repository:
    return await Repository.objects.acreate(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        default_branch="main",
    )


async def _finalize(
    node: AICodingNode,
    context: ExecutionContext,
    repo: Repository,
    *,
    completed_session_ids: list[str] | None = None,
    session_repo_map: dict[str, str] | None = None,
) -> NodeResult:
    succeeded = [
        {
            "repository_id": str(repo.id),
            "repository_name": repo.name,
            "tasks_completed": [],
            "output": {},
            "mr_url": "",
            "mr_id": "",
            "files_changed": 0,
            "insertions": 0,
            "deletions": 0,
        }
    ]
    return await node._finalize_and_notify(
        context=context,
        succeeded=succeeded,
        failed_repos=[],
        completed_session_ids=completed_session_ids or [],
        branch_name="feat/x",
        base_branch="main",
        plan_title="登录改造",
        plan_data={"plan_version_id": str(uuid.uuid4())},
        log=structlog.get_logger(__name__),
        session_repo_map=session_repo_map or {},
    )


# ---------------------------------------------------------------------------
# write_back 三态守门
# ---------------------------------------------------------------------------


async def test_legacy_config_without_key_and_no_triple_is_zero_change(
    monkeypatch: pytest.MonkeyPatch,
    awrite_back_calls: list[dict[str, Any]],
    bg_calls: list[dict[str, Any]],
) -> None:
    """存量零行为变化：config 无 write_back 键 + 无三元组 → 不回写、无 writeback_skipped。"""
    _patch_resolver(monkeypatch, None)
    repo = await _make_repo()
    node = _make_node()

    with capture_logs() as logs:
        result = await _finalize(node, _make_context({"timeout_seconds": 600}), repo)

    assert result.status == "completed"
    assert awrite_back_calls == []
    assert not any(entry["event"] == "writeback_skipped" for entry in logs)


async def test_legacy_config_without_key_with_triple_writes_back(
    monkeypatch: pytest.MonkeyPatch,
    awrite_back_calls: list[dict[str, Any]],
    bg_calls: list[dict[str, Any]],
) -> None:
    """legacy fallback：config 无键但三元组可反查 → 回写且入参三元组正确。"""
    _patch_resolver(monkeypatch, _TRIPLE)
    repo = await _make_repo()
    node = _make_node()

    result = await _finalize(node, _make_context({"timeout_seconds": 600}), repo)

    assert result.status == "completed"
    assert len(awrite_back_calls) == 1
    call = awrite_back_calls[0]
    assert call["feishu_project_key"] == "wb-key"
    assert call["work_item_type"] == "story"
    assert call["work_item_id"] == 88
    assert call["title"] == "登录改造"
    assert [r.mr_url for r in call["results"]] == [f"https://mr/{repo.name}"]
    assert call["results"][0].status == "completed"


async def test_explicit_false_never_writes_back(
    monkeypatch: pytest.MonkeyPatch,
    awrite_back_calls: list[dict[str, Any]],
    bg_calls: list[dict[str, Any]],
) -> None:
    """显式 False：即使三元组可反查也不回写。"""
    _patch_resolver(monkeypatch, _TRIPLE)
    repo = await _make_repo()
    node = _make_node()

    result = await _finalize(node, _make_context({"write_back": False}), repo)

    assert result.status == "completed"
    assert awrite_back_calls == []


async def test_explicit_true_without_triple_logs_writeback_skipped(
    monkeypatch: pytest.MonkeyPatch,
    awrite_back_calls: list[dict[str, Any]],
    bg_calls: list[dict[str, Any]],
) -> None:
    """显式 True + 无三元组：不回写但记 writeback_skipped（caller 事件）。"""
    _patch_resolver(monkeypatch, None)
    repo = await _make_repo()
    node = _make_node()

    with capture_logs() as logs:
        result = await _finalize(node, _make_context({"write_back": True}), repo)

    assert result.status == "completed"
    assert awrite_back_calls == []
    skipped = [entry for entry in logs if entry["event"] == "writeback_skipped"]
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "no_work_item"


# ---------------------------------------------------------------------------
# 提炼调度 + fail-soft
# ---------------------------------------------------------------------------


async def test_extraction_scheduled_per_completed_session(
    monkeypatch: pytest.MonkeyPatch,
    awrite_back_calls: list[dict[str, Any]],
    bg_calls: list[dict[str, Any]],
) -> None:
    """completed_session_ids 非空 → run_in_background 逐 session 调度（回写与否无关）。"""
    _patch_resolver(monkeypatch, None)
    repo = await _make_repo()
    node = _make_node()

    result = await _finalize(
        node,
        _make_context({"write_back": False}),
        repo,
        completed_session_ids=["sub-aaa", "sub-bbb"],
        session_repo_map={"sub-aaa": str(repo.id)},
    )

    assert result.status == "completed"
    assert awrite_back_calls == []
    assert [c["name"] for c in bg_calls] == ["learning-case-sub-aaa", "learning-case-sub-bbb"]


async def test_completion_loop_exception_does_not_affect_node_result(
    monkeypatch: pytest.MonkeyPatch,
    awrite_back_calls: list[dict[str, Any]],
    bg_calls: list[dict[str, Any]],
) -> None:
    """闭环块内抛异常（反查器 raise）→ NodeResult status 不受影响（fail-soft）。"""
    _patch_resolver(monkeypatch, RuntimeError("resolver exploded"))
    repo = await _make_repo()
    node = _make_node()

    result = await _finalize(
        node,
        _make_context({"write_back": True}),
        repo,
        completed_session_ids=["sub-aaa"],
    )

    assert result.status == "completed"
    assert result.error is None
    assert awrite_back_calls == []
