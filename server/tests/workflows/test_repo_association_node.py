"""RepoAssociationNode 守护测试（Phase 88，REPO-01/02，88-04）。

覆盖三分支（纯 mock，patch service/ProjectService/FeishuIMService + 模块级解析器）：
- 节点自动注册（registry 含 repo_association）+ is_blocking + outputs handles。
- 首发：mock propose → waiting_event，output_data 含 proposal/chat_id/round=1/stage="clarify"；
  建 WorkflowEventSubscription(event_type="RepoAssocCallback")。
- 无输入源 → failed + error（不发卡）。
- 无群（resolve_or_create_group="" ）→ failed + error（不调 propose）。
- 确认派发：output_data._confirmed_repo_ids → confirm_repos + dispatch_verify（透传 node_execution_id）
  → waiting_event(stage="verifying")。
- 续驱 mismatch：output_data._resume_from_callback + mismatch → waiting_event(stage="reconfirm") + 发回退卡。
- 续驱全 fit → completed + next_handle="verified"。
- 发卡失败 → fail-soft，不阻断挂起（仍 waiting_event）。
- associate_repos 工具与节点共用 RepoAssociationService（-k tool）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.nodes.base import ExecutionContext
from workflows.nodes.integrations.repo_association import RepoAssociationNode
from workflows.nodes.registry import NodeRegistry

_NODE_MOD = "workflows.nodes.integrations.repo_association"

_PROPOSAL = {
    "candidates": [
        {
            "repo_id": "repo-1",
            "repo_name": "backend-auth",
            "score": 0.9,
            "confidence": "high",
            "reason": "命中 auth",
            "matched_node_paths": ["backend-auth/auth"],
        }
    ],
    "router_version": "v2",
    "auto_selected": True,
}


def _ctx(
    *,
    config: dict | None = None,
    input_data: dict | None = None,
    node_execution: object | None = None,
    workflow_execution: object | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-1",
        node_id="node-1",
        node_config=config or {},
        input_data=input_data or {},
        workflow_context={},
        previous_outputs={},
        workflow_execution=workflow_execution,
        node_execution=node_execution,
    )


def _mock_im_service() -> MagicMock:
    im = MagicMock()
    im.create_card_entity = AsyncMock(return_value="card-1")
    im.send_card_entity = AsyncMock(return_value="msg-1")
    im.stream_card_content = AsyncMock(return_value=True)
    im.settle_card_stream = AsyncMock(return_value=True)
    im.send_card = AsyncMock(return_value="msg-fallback")
    return im


# ---------------------------------------------------------------------------
# 注册 + 端口
# ---------------------------------------------------------------------------


def test_node_auto_registered() -> None:
    node_cls = NodeRegistry.get("repo_association")
    assert node_cls is RepoAssociationNode
    assert node_cls.is_blocking is True
    assert node_cls.execution_mode == "server_local"
    out_handles = {p.name for p in node_cls.outputs}
    assert out_handles == {"verified", "reconfirm", "timeout", "error"}


# ---------------------------------------------------------------------------
# 首发
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_input_source_fails() -> None:
    node = RepoAssociationNode()
    result = await node.execute(_ctx())
    assert result.status == "failed"
    assert result.next_handle == "error"


@pytest.mark.asyncio
async def test_first_dispatch_waiting_event_persisted() -> None:
    node = RepoAssociationNode()
    proj_svc = MagicMock()
    proj_svc.resolve_or_create_group = AsyncMock(return_value="oc_group")
    assoc_svc = MagicMock()
    assoc_svc.propose = AsyncMock(return_value=_PROPOSAL)
    im = _mock_im_service()

    with (
        patch(f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))),
        patch(f"{_NODE_MOD}.ProjectService", return_value=proj_svc),
        patch(f"{_NODE_MOD}.RepoAssociationService", return_value=assoc_svc),
        patch(f"{_NODE_MOD}.FeishuIMService.create", AsyncMock(return_value=im)),
    ):
        result = await node.execute(
            _ctx(input_data={"features_flat": [{"name": "登录"}]})
        )

    assert result.status == "waiting_event"
    out = result.output
    assert out["proposal"] == _PROPOSAL
    assert out["chat_id"] == "oc_group"
    assert out["card_id"] == "card-1"
    assert out["round"] == 1
    assert out["stage"] == "clarify"
    proj_svc.resolve_or_create_group.assert_awaited_once()
    assoc_svc.propose.assert_awaited_once()
    im.create_card_entity.assert_awaited_once()
    im.stream_card_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_first_dispatch_creates_event_subscription() -> None:
    node = RepoAssociationNode()
    proj_svc = MagicMock()
    proj_svc.resolve_or_create_group = AsyncMock(return_value="oc_group")
    assoc_svc = MagicMock()
    assoc_svc.propose = AsyncMock(return_value=_PROPOSAL)
    im = _mock_im_service()
    we = MagicMock()
    ne = MagicMock()
    ne.output_data = {}
    acreate = AsyncMock()

    with (
        patch(f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))),
        patch(f"{_NODE_MOD}.ProjectService", return_value=proj_svc),
        patch(f"{_NODE_MOD}.RepoAssociationService", return_value=assoc_svc),
        patch(f"{_NODE_MOD}.FeishuIMService.create", AsyncMock(return_value=im)),
        patch(f"{_NODE_MOD}.WorkflowEventSubscription.objects.acreate", acreate),
    ):
        result = await node.execute(
            _ctx(
                input_data={"features_flat": [{"name": "登录"}]},
                node_execution=ne,
                workflow_execution=we,
            )
        )

    assert result.status == "waiting_event"
    acreate.assert_awaited_once()
    assert acreate.await_args.kwargs["event_type"] == "RepoAssocCallback"


@pytest.mark.asyncio
async def test_no_group_fails_without_proposing() -> None:
    node = RepoAssociationNode()
    proj_svc = MagicMock()
    proj_svc.resolve_or_create_group = AsyncMock(return_value="")
    assoc_svc = MagicMock()
    assoc_svc.propose = AsyncMock(return_value=_PROPOSAL)

    with (
        patch(f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))),
        patch(f"{_NODE_MOD}.ProjectService", return_value=proj_svc),
        patch(f"{_NODE_MOD}.RepoAssociationService", return_value=assoc_svc),
    ):
        result = await node.execute(
            _ctx(input_data={"features_flat": [{"name": "x"}]})
        )

    assert result.status == "failed"
    assert result.next_handle == "error"
    assoc_svc.propose.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_dispatch_card_failure_failsoft() -> None:
    node = RepoAssociationNode()
    proj_svc = MagicMock()
    proj_svc.resolve_or_create_group = AsyncMock(return_value="oc_group")
    assoc_svc = MagicMock()
    assoc_svc.propose = AsyncMock(return_value=_PROPOSAL)
    im = _mock_im_service()
    im.create_card_entity = AsyncMock(side_effect=RuntimeError("cardkit down"))

    with (
        patch(f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))),
        patch(f"{_NODE_MOD}.ProjectService", return_value=proj_svc),
        patch(f"{_NODE_MOD}.RepoAssociationService", return_value=assoc_svc),
        patch(f"{_NODE_MOD}.FeishuIMService.create", AsyncMock(return_value=im)),
    ):
        result = await node.execute(
            _ctx(input_data={"features_flat": [{"name": "x"}]})
        )

    # 流式发卡失败 → 降级普通发卡 → 仍挂起（card_id 空），不抛
    assert result.status == "waiting_event"
    assert result.output["card_id"] == ""
    im.send_card.assert_awaited_once()


# ---------------------------------------------------------------------------
# 确认派发
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_dispatch_runs_verify() -> None:
    node = RepoAssociationNode()
    confirmed = [SimpleNamespace(repository_id="repo-1")]
    assoc_svc = MagicMock()
    assoc_svc.confirm_repos = AsyncMock(return_value=confirmed)
    assoc_svc.dispatch_verify = AsyncMock(
        return_value={"dispatched": ["t1"], "failed": [], "runner_offline": False}
    )
    ne = MagicMock()
    ne.id = "ne-1"
    ne.output_data = {"_confirmed_repo_ids": ["repo-1"], "chat_id": "oc_group", "round": 1}
    im = _mock_im_service()

    with (
        patch(f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))),
        patch(f"{_NODE_MOD}.RepoAssociationService", return_value=assoc_svc),
        patch(f"{_NODE_MOD}.FeishuIMService.create", AsyncMock(return_value=im)),
    ):
        result = await node.execute(_ctx(node_execution=ne))

    assert result.status == "waiting_event"
    assert result.output["stage"] == "verifying"
    assert result.output["confirmed_repo_ids"] == ["repo-1"]
    assoc_svc.confirm_repos.assert_awaited_once()
    assoc_svc.dispatch_verify.assert_awaited_once()
    # 透传 node_execution_id 使容器回调续驱本节点
    assert assoc_svc.dispatch_verify.await_args.kwargs["node_execution_id"] == "ne-1"


# ---------------------------------------------------------------------------
# 续驱聚合
# ---------------------------------------------------------------------------


def _assoc(repo_id: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(repository_id=repo_id, repository=SimpleNamespace(name=name))


@pytest.mark.asyncio
async def test_resume_mismatch_keeps_waiting_reconfirm() -> None:
    node = RepoAssociationNode()
    assoc_svc = MagicMock()
    assoc_svc.collect_verdicts = AsyncMock(
        return_value={
            "fit": ["repo-1"],
            "mismatch": ["repo-2"],
            "unknown": [],
            "all_terminal": True,
        }
    )
    ne = MagicMock()
    ne.id = "ne-1"
    ne.output_data = {
        "_resume_from_callback": True,
        "confirmed_repo_ids": ["repo-1", "repo-2"],
        "chat_id": "oc_group",
        "round": 1,
    }
    im = _mock_im_service()

    with (
        patch(f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))),
        patch(
            f"{_NODE_MOD}._aload_associations",
            AsyncMock(return_value=[_assoc("repo-1", "backend"), _assoc("repo-2", "web")]),
        ),
        patch(f"{_NODE_MOD}.RepoAssociationService", return_value=assoc_svc),
        patch(f"{_NODE_MOD}.FeishuIMService.create", AsyncMock(return_value=im)),
    ):
        result = await node.execute(_ctx(node_execution=ne))

    assert result.status == "waiting_event"
    assert result.output["stage"] == "reconfirm"
    assoc_svc.collect_verdicts.assert_awaited_once()
    # 发回退卡（普通发卡）
    im.send_card.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_all_fit_completes_verified() -> None:
    node = RepoAssociationNode()
    assoc_svc = MagicMock()
    assoc_svc.collect_verdicts = AsyncMock(
        return_value={
            "fit": ["repo-1"],
            "mismatch": [],
            "unknown": [],
            "all_terminal": True,
        }
    )
    ne = MagicMock()
    ne.id = "ne-1"
    ne.output_data = {
        "_resume_from_callback": True,
        "confirmed_repo_ids": ["repo-1"],
        "chat_id": "oc_group",
        "round": 1,
    }
    im = _mock_im_service()

    with (
        patch(f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))),
        patch(
            f"{_NODE_MOD}._aload_associations",
            AsyncMock(return_value=[_assoc("repo-1", "backend")]),
        ),
        patch(f"{_NODE_MOD}.RepoAssociationService", return_value=assoc_svc),
        patch(f"{_NODE_MOD}.FeishuIMService.create", AsyncMock(return_value=im)),
    ):
        result = await node.execute(_ctx(node_execution=ne))

    assert result.status == "completed"
    assert result.next_handle == "verified"
    assert "backend" in result.output["verified_repos"]


@pytest.mark.asyncio
async def test_resume_failsoft_on_exception() -> None:
    """续驱整段 fail-soft：聚合异常不抛、不回 5xx，返回 completed 降级。"""
    node = RepoAssociationNode()
    assoc_svc = MagicMock()
    assoc_svc.collect_verdicts = AsyncMock(side_effect=RuntimeError("db down"))
    ne = MagicMock()
    ne.id = "ne-1"
    ne.output_data = {
        "_resume_from_callback": True,
        "confirmed_repo_ids": ["repo-1"],
        "chat_id": "oc_group",
    }

    with (
        patch(f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))),
        patch(f"{_NODE_MOD}._aload_associations", AsyncMock(return_value=[_assoc("repo-1", "b")])),
        patch(f"{_NODE_MOD}.RepoAssociationService", return_value=assoc_svc),
    ):
        result = await node.execute(_ctx(node_execution=ne))

    assert result.status == "completed"
    assert result.output.get("degraded") is True


# ---------------------------------------------------------------------------
# associate_repos 工具（与节点共用 service）
# ---------------------------------------------------------------------------


def test_associate_repos_registered_as_tool() -> None:
    from agents.tools.repo_association_tools import associate_repos

    definition = associate_repos._tool_definition
    assert definition.name == "associate_repos"
    assert definition.category.value == "PROJECT"


@pytest.mark.asyncio
async def test_associate_repos_tool_shares_service() -> None:
    from agents.tools import repo_association_tools as mod

    svc = MagicMock()
    svc.propose = AsyncMock(return_value=_PROPOSAL)
    space = SimpleNamespace(id="s1")

    with (
        patch.object(mod.Space.objects, "aget", AsyncMock(return_value=space)),
        patch.object(mod, "RepoAssociationService", return_value=svc),
    ):
        result = await mod.associate_repos(
            space_id="s1", features=[{"name": "登录"}]
        )

    assert result.success is True
    assert result.output["data"]["candidate_count"] == 1
    # 与节点共用同一 service（调 propose，无第二套选仓实现）
    svc.propose.assert_awaited_once()
