"""RepoVerifyDispatchService 单测（Phase 88-03，REPO-02）。

**真实容器 E2E DEFERRED**（见 88-UAT.md A1）：全程 mock dispatcher / runner 在线查询 /
git 凭证（mirror ``test_research_adapter``），覆盖：
- 逐仓 explore 容器派发（explore 双层 + token 注入 + REPO_VERIFY + source=repo_verify + running 回填）；
- node_execution_id 透传（DispatchTask + SubAgentSession）；
- per-repo fail-soft 隔离（一仓 dispatch 抛 → 仅该 task failed，其余仍派发，不上抛）；
- runner 离线降级（_count_online_runners=0 → 不起容器、仓标 unknown 不阻断）；
- collect_verdicts 聚合 fit/mismatch/unknown（缺 task 仓记 unknown）；
- confirm_repos proposed→confirmed。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async

from initiatives.models import (
    Project,
    RepoAssociation,
    RepoAssociationStatus,
    RepoVerifyTask,
    RepoVerifyTaskStatus,
)
from initiatives.services.repo_association_service import RepoAssociationService
from initiatives.services.repo_verify_dispatch import RepoVerifyDispatchService
from projects.models import Space
from repositories.models import Repository
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)

_CC = {"api_key": "k", "base_url": "https://u", "default_model": "m", "haiku_model": "h"}


# ===========================================================================
# fixtures / helpers（async 测试经 sync_to_async 包同步 ORM）
# ===========================================================================


@sync_to_async
def _make_confirmed(n: int = 2, status=RepoAssociationStatus.VERIFYING):
    space = Space.objects.create(name=f"VfySpace-{uuid.uuid4().hex[:6]}")
    project = Project.objects.create(space=space, name="P", feishu_project_key="")
    assocs: list[RepoAssociation] = []
    for i in range(n):
        repo = Repository.objects.create(
            name=f"repo{i}",
            git_url=f"https://github.com/test/repo{i}-{uuid.uuid4().hex[:6]}.git",
            git_platform="github",
            default_branch="main",
            index_status="indexed",
        )
        assoc = RepoAssociation.objects.create(
            project=project,
            repository=repo,
            status=status,
            routed_reason=f"命中 {repo.name} 鉴权能力",
            matched_node_paths=[f"{repo.name}/auth"],
            source="router_v2",
        )
        assocs.append(assoc)
    return project, assocs


def _mock_dispatcher():
    captured: list = []
    dispatcher = MagicMock()

    async def _dispatch(task):
        captured.append(task)

    dispatcher.dispatch = AsyncMock(side_effect=_dispatch)
    return dispatcher, captured


def _runtime_patches():
    return (
        patch("services.git_credentials.aresolve_git_token", AsyncMock(return_value="ghp_secret")),
        patch(
            "services.provider_config.aget_claude_code_runtime_config",
            AsyncMock(return_value=_CC),
        ),
    )


@sync_to_async
def _reload_task(task_id) -> RepoVerifyTask:
    return RepoVerifyTask.objects.select_related("subagent_session").get(id=task_id)


@sync_to_async
def _verify_tasks(association) -> list[RepoVerifyTask]:
    return list(RepoVerifyTask.objects.filter(association=association))


# ===========================================================================
# dispatch — explore 容器派发
# ===========================================================================


async def test_dispatch_explore_container() -> None:
    """逐仓派 explore 容器：metadata explore 双层 + token 注入 + task_type=repo_verify +
    SubAgentSession(REPO_VERIFY, source=repo_verify) + task→running。"""
    project, assocs = await _make_confirmed(2)
    dispatcher, captured = _mock_dispatcher()
    svc = RepoVerifyDispatchService()
    git_p, cc_p = _runtime_patches()

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(
            RepoVerifyDispatchService, "_count_online_runners", new=AsyncMock(return_value=1)
        ),
        git_p,
        cc_p,
    ):
        result = await svc.dispatch(assocs, initiated_by_user_id="u-1")

    assert len(result["dispatched"]) == 2
    assert result["failed"] == []
    assert result["runner_offline"] is False
    assert dispatcher.dispatch.await_count == 2

    dt = captured[0]
    # explore 双层只读拦截
    assert dt.metadata["env_FRIDAY_TASK_MODE"] == "explore"
    assert dt.metadata["env_FRIDAY_TASK_TASK_MODE"] == "explore"
    # token 注入容器 env（不入日志）
    assert dt.metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] == "ghp_secret"
    assert dt.task_type == "repo_verify"
    assert "_repo_url" not in dt.metadata  # pop 出后不残留

    # 任务回填 running + SubAgentSession REPO_VERIFY + source repo_verify
    task = await _reload_task(result["dispatched"][0])
    assert task.status == RepoVerifyTaskStatus.RUNNING
    assert task.subagent_session_id is not None
    sub = await SubAgentSession.objects.aget(id=task.subagent_session_id)
    assert sub.task_type == SubAgentSession.TaskType.REPO_VERIFY
    assert sub.last_output.get("source") == "repo_verify"
    assert sub.last_output.get("repo_verify_task_id") == str(task.id)
    assert sub.last_output.get("initiated_by_user_id") == "u-1"


async def test_dispatch_node_execution_id_passthrough() -> None:
    """node_execution_id 非空时透传到 DispatchTask（续驱关联，Pitfall 2）。"""
    from workflows.models import (
        NodeExecution,
        Workflow,
        WorkflowExecution,
        WorkflowNode,
    )

    project, assocs = await _make_confirmed(1)

    @sync_to_async
    def _make_node_exec() -> str:
        space = Space.objects.create(name=f"wf-{uuid.uuid4().hex[:6]}")
        wf = Workflow.objects.create(name="wf", space=space)
        node = WorkflowNode.objects.create(workflow=wf, node_type="x", name="n")
        wf_exec = WorkflowExecution.objects.create(
            workflow=wf, space=space, trigger_type="manual"
        )
        ne = NodeExecution.objects.create(
            workflow_execution=wf_exec, node=node, status="running"
        )
        return str(ne.id)

    node_exec_id = await _make_node_exec()
    dispatcher, captured = _mock_dispatcher()
    svc = RepoVerifyDispatchService(node_execution_id=node_exec_id)
    git_p, cc_p = _runtime_patches()

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(
            RepoVerifyDispatchService, "_count_online_runners", new=AsyncMock(return_value=1)
        ),
        git_p,
        cc_p,
    ):
        result = await svc.dispatch(assocs)

    assert captured[0].node_execution_id == node_exec_id
    task = await _reload_task(result["dispatched"][0])
    sub = await SubAgentSession.objects.aget(id=task.subagent_session_id)
    assert str(sub.node_execution_id) == node_exec_id


# ===========================================================================
# fail-soft —— 单仓隔离 / runner 离线降级
# ===========================================================================


async def test_per_repo_isolation() -> None:
    """一仓 dispatch 抛异常仅标该 task failed，其余仓仍派发，dispatch 不上抛（D-03 Pitfall 3）。"""
    project, assocs = await _make_confirmed(2)
    dispatcher, captured = _mock_dispatcher()
    svc = RepoVerifyDispatchService()
    git_p, cc_p = _runtime_patches()

    original = svc._dispatch_verify_task
    state = {"n": 0}

    async def _flaky(association, task, repo, user):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("dispatch boom")
        return await original(association, task, repo, user)

    svc._dispatch_verify_task = _flaky

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(
            RepoVerifyDispatchService, "_count_online_runners", new=AsyncMock(return_value=2)
        ),
        git_p,
        cc_p,
    ):
        result = await svc.dispatch(assocs)

    # 整个 dispatch 不抛
    assert "dispatched" in result
    assert len(result["failed"]) == 1
    assert len(result["dispatched"]) == 1

    statuses = []
    for a in assocs:
        for t in await _verify_tasks(a):
            statuses.append(t.status)
    statuses.sort()
    assert RepoVerifyTaskStatus.FAILED in statuses
    assert RepoVerifyTaskStatus.RUNNING in statuses
    # failed 仓 error reason
    failed_task = await _reload_task(result["failed"][0])
    assert failed_task.error.get("reason") == "dispatch_failed"


async def test_runner_offline_degrades_to_unknown() -> None:
    """_count_online_runners=0 → 不起容器、确认仓 verdict 记 unknown 不阻断（runner_offline=True）。"""
    project, assocs = await _make_confirmed(2)
    dispatcher, captured = _mock_dispatcher()
    svc = RepoVerifyDispatchService()

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(
            RepoVerifyDispatchService, "_count_online_runners", new=AsyncMock(return_value=0)
        ),
    ):
        result = await svc.dispatch(assocs)

    assert result["runner_offline"] is True
    assert result["dispatched"] == []
    assert dispatcher.dispatch.await_count == 0
    # 两仓都标 unknown verdict + done（不阻断终态）
    for a in assocs:
        tasks = await _verify_tasks(a)
        assert len(tasks) == 1
        assert tasks[0].status == RepoVerifyTaskStatus.DONE
        assert tasks[0].verdict.get("fit") == "unknown"
        assert tasks[0].subagent_session_id is None


async def test_missing_git_url_fails_without_container() -> None:
    """缺 git_url 的确认仓 → mark_verify_failed(missing_git_url)，不派占位 URL 容器。"""

    @sync_to_async
    def _make_nogit():
        space = Space.objects.create(name=f"ng-{uuid.uuid4().hex[:6]}")
        project = Project.objects.create(space=space, name="P", feishu_project_key="")
        repo = Repository.objects.create(
            name="nogit", git_url="", git_platform="github", default_branch="main"
        )
        assoc = RepoAssociation.objects.create(
            project=project, repository=repo, status=RepoAssociationStatus.VERIFYING
        )
        return project, [assoc]

    project, assocs = await _make_nogit()
    dispatcher, captured = _mock_dispatcher()
    svc = RepoVerifyDispatchService()
    git_p, cc_p = _runtime_patches()

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(
            RepoVerifyDispatchService, "_count_online_runners", new=AsyncMock(return_value=1)
        ),
        git_p,
        cc_p,
    ):
        result = await svc.dispatch(assocs)

    assert dispatcher.dispatch.await_count == 0
    assert result["dispatched"] == []
    tasks = await _verify_tasks(assocs[0])
    assert tasks[0].status == RepoVerifyTaskStatus.FAILED
    assert tasks[0].error.get("reason") == "missing_git_url"


# ===========================================================================
# collect_verdicts —— 聚合 fit/mismatch/unknown
# ===========================================================================


async def test_collect_verdicts_aggregation() -> None:
    """聚合各仓 verdict → fit/mismatch/unknown；缺 task 的确认仓记 unknown，all_terminal 正确。"""
    project, assocs = await _make_confirmed(4, status=RepoAssociationStatus.VERIFYING)
    svc = RepoAssociationService()

    # assoc0=fit, assoc1=mismatch, assoc2=unknown, assoc3=无 task → unknown
    @sync_to_async
    def _seed():
        RepoVerifyTask.objects.create(
            association=assocs[0], repository=assocs[0].repository,
            status=RepoVerifyTaskStatus.DONE, verdict={"fit": "fit"},
        )
        RepoVerifyTask.objects.create(
            association=assocs[1], repository=assocs[1].repository,
            status=RepoVerifyTaskStatus.DONE, verdict={"fit": "mismatch"},
        )
        RepoVerifyTask.objects.create(
            association=assocs[2], repository=assocs[2].repository,
            status=RepoVerifyTaskStatus.DONE, verdict={"fit": "unknown"},
        )

    await _seed()
    agg = await svc.collect_verdicts(assocs)

    assert agg["fit"] == [str(assocs[0].repository_id)]
    assert agg["mismatch"] == [str(assocs[1].repository_id)]
    assert set(agg["unknown"]) == {
        str(assocs[2].repository_id),
        str(assocs[3].repository_id),
    }
    assert agg["all_terminal"] is True


async def test_collect_verdicts_running_not_terminal() -> None:
    """存在 running verify task → all_terminal=False（缺 verdict 记 unknown）。"""
    project, assocs = await _make_confirmed(1, status=RepoAssociationStatus.VERIFYING)
    svc = RepoAssociationService()

    @sync_to_async
    def _seed():
        RepoVerifyTask.objects.create(
            association=assocs[0], repository=assocs[0].repository,
            status=RepoVerifyTaskStatus.RUNNING,
        )

    await _seed()
    agg = await svc.collect_verdicts(assocs)
    assert agg["all_terminal"] is False
    assert agg["unknown"] == [str(assocs[0].repository_id)]


# ===========================================================================
# confirm_repos —— proposed → confirmed
# ===========================================================================


async def test_confirm_repos_proposed_to_confirmed() -> None:
    """命中 repo_ids 的 proposed 候选置 confirmed，未命中保持 proposed。"""
    project, assocs = await _make_confirmed(2, status=RepoAssociationStatus.PROPOSED)
    svc = RepoAssociationService()

    confirmed = await svc.confirm_repos(
        project=project,
        repo_ids=[str(assocs[0].repository_id)],
        initiated_by_user_id="u-2",
    )
    assert len(confirmed) == 1
    assert confirmed[0].status == RepoAssociationStatus.CONFIRMED

    @sync_to_async
    def _statuses():
        return {
            str(a.repository_id): RepoAssociation.objects.get(id=a.id).status
            for a in assocs
        }

    statuses = await _statuses()
    assert statuses[str(assocs[0].repository_id)] == RepoAssociationStatus.CONFIRMED
    assert statuses[str(assocs[1].repository_id)] == RepoAssociationStatus.PROPOSED
