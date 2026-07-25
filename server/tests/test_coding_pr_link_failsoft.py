"""AICodingNode._finalize_and_notify spec↔PR 回填 fail-soft 守护（Phase 52-01，D-52-3，LINK-01）。

覆盖 D-52-3：算出 successful_mrs 后逐 MR best-effort 调 link_implementation_pr——

- 回填：正常路径每个 successful_mr 各调一次 link（含正确 repository_id/pr_url/
  artifact_version_id —— 后者取自 plan_data["plan_version_id"]）。
- fail-soft 不阻断：link 抛异常 → 整段吞为 warning sdd_spec_pr_link_failed，
  _finalize_and_notify 仍返回 completed 且通知被调用。
- 零回归：plan_version_id 缺失 → link 不被调用，既有 MR 创建+通知+输出不受影响。

mock IO 边界（_create_mr_for_repo / 通知 / 子步骤）；ORM 走真实 DB transaction=True。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from repositories.models import Repository
from workflows.nodes.ai.coding import AICodingNode
from workflows.nodes.base import ExecutionContext, NodeResult

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _make_repo(name: str) -> Repository:
    return await Repository.objects.acreate(
        name=f"{name}-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


def _make_node() -> AICodingNode:
    """构造 node 并 stub IO 边界（子步骤 / 通知 / MR 创建）。"""
    node = AICodingNode()
    node.emit_sub_step = AsyncMock()  # type: ignore[method-assign]
    node._send_result_notification = AsyncMock()  # type: ignore[method-assign]

    async def _fake_mr(*, repository: Repository, **kwargs: Any) -> dict[str, Any]:
        return {"mr_url": f"https://mr/{repository.name}", "mr_id": "1"}

    node._create_mr_for_repo = AsyncMock(side_effect=_fake_mr)  # type: ignore[method-assign]
    return node


def _make_context() -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-pr-link-001",
        node_id="node-coding",
        node_config={"timeout_seconds": 10, "chat_id": ""},
        input_data={},
        workflow_context={},
        previous_outputs={},
        trigger_data={},
        workflow_execution=None,
        node_execution=None,
    )


async def _run_finalize(
    node: AICodingNode,
    succeeded: list[dict[str, Any]],
    plan_data: dict[str, Any] | None,
) -> NodeResult:
    import structlog

    return await node._finalize_and_notify(
        context=_make_context(),
        succeeded=succeeded,
        failed_repos=[],
        completed_session_ids=[],  # 跳过 ingestion / output_data 持久化块
        branch_name="feat/x",
        base_branch="main",
        plan_title="测试方案",
        plan_data=plan_data,
        log=structlog.get_logger("test"),
    )


async def test_link_called_per_successful_mr_on_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常路径：每个 successful_mr 各调一次 link，含正确 repository_id/pr_url/版本 id。"""
    # 避免 ≥2 仓触发的 cross-ref 真实网络回写。
    monkeypatch.setattr(
        "workflows.services.pr_cross_reference.add_cross_references",
        AsyncMock(return_value={}),
    )
    link_mock = AsyncMock()
    monkeypatch.setattr(
        "delivery.services.sdd_spec_service.SddSpecService.link_implementation_pr",
        link_mock,
    )

    repo_a = await _make_repo("la")
    repo_b = await _make_repo("lb")
    id_a, id_b = str(repo_a.id), str(repo_b.id)
    succeeded = [
        {"repository_id": id_a, "tasks_completed": [], "output": {}},
        {"repository_id": id_b, "tasks_completed": [], "output": {}},
    ]

    result = await _run_finalize(node=_make_node(), succeeded=succeeded, plan_data={"plan_version_id": "pv-1"})

    assert result.status == "completed"
    assert link_mock.await_count == 2
    # plan_data 里仍叫 plan_version_id，service 侧形参已随 Chassis v2 更名为
    # artifact_version_id（PlanVersion → ArtifactVersion）。
    linked = {
        (c.kwargs["repository_id"], c.kwargs["pr_url"], c.kwargs["artifact_version_id"])
        for c in link_mock.await_args_list
    }
    assert (id_a, f"https://mr/{repo_a.name}", "pv-1") in linked
    assert (id_b, f"https://mr/{repo_b.name}", "pv-1") in linked


async def test_link_failure_does_not_block_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail-soft：link 抛异常 → 仍 completed 且通知被调用（绝不阻断 PR 创建/通知）。"""
    link_mock = AsyncMock(side_effect=RuntimeError("link boom"))
    monkeypatch.setattr(
        "delivery.services.sdd_spec_service.SddSpecService.link_implementation_pr",
        link_mock,
    )

    repo = await _make_repo("fs")
    succeeded = [{"repository_id": str(repo.id), "tasks_completed": [], "output": {}}]

    node = _make_node()
    result = await _run_finalize(node=node, succeeded=succeeded, plan_data={"plan_version_id": "pv-2"})

    assert result.status == "completed"
    assert link_mock.await_count == 1  # 尝试过回填（异常被吞）
    node._send_result_notification.assert_awaited_once()  # type: ignore[attr-defined]


async def test_link_skipped_when_plan_version_id_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """零回归：plan_version_id 缺失 → link 不被调用，MR 创建+通知不受影响。"""
    link_mock = AsyncMock()
    monkeypatch.setattr(
        "delivery.services.sdd_spec_service.SddSpecService.link_implementation_pr",
        link_mock,
    )

    repo = await _make_repo("zr")
    succeeded = [{"repository_id": str(repo.id), "tasks_completed": [], "output": {}}]

    node = _make_node()
    result = await _run_finalize(node=node, succeeded=succeeded, plan_data=None)

    assert result.status == "completed"
    assert link_mock.await_count == 0
    node._send_result_notification.assert_awaited_once()  # type: ignore[attr-defined]
