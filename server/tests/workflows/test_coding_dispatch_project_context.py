"""workflow 派发项目上下文注入守护测试（Phase 103 AGENT-04）。

覆盖：
- ProjectBranch 显式绑定命中 → dispatch metadata 含 env_FRIDAY_TASK_PROJECT_CONTEXT
  且 DispatchTask.prompt 以上下文块开头（``---`` 分隔符在）；
- work_item fallback：无 ProjectBranch 绑定但 ProjectWorkItemLink 命中 → 同样注入；
- 复用：同 project 两仓 → apack_dispatch_context 只被调用一次（按 (project, branch)
  解析一次逐仓复用，不重复召回）；
- fail-soft：无 project / 无 dispatch_user / packer 抛异常 → dispatch 成功且
  metadata 无该键、prompt 无 prepend（与现状逐字一致，T-103-15）。

复刻 test_remote_tool_dispatch.py 的 dispatch 捕获 fixture 套（就地复制保独立可单跑）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import structlog
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from services.provider_config import (
    ProviderType,
    ResolvedProviderConfig,
)

User = get_user_model()

_BRANCH = "feat/ctx-branch"
_CTX_BLOCK = "# 项目上下文（自动召回）\n\n- 项目关键决策记忆"


# =========================================================================
# Fixtures（复刻 test_remote_tool_dispatch.py 的 dispatch 捕获套）
# =========================================================================


@pytest.fixture
def workflow(db: None, project: Any) -> Any:
    from workflows.models.workflow import Workflow

    return Workflow.objects.create(name="Ctx Dispatch Workflow", space=project)


@pytest.fixture
def workflow_node(db: None, workflow: Any) -> Any:
    from workflows.models.node import WorkflowNode

    return WorkflowNode.objects.create(
        workflow=workflow,
        node_type="ai_coding",
        name="Test AI Coding",
        config={},
    )


@pytest.fixture
def workflow_execution(db: None, workflow: Any) -> Any:
    from workflows.models.execution import WorkflowExecution

    return WorkflowExecution.objects.create(
        workflow=workflow,
        space=workflow.space,
        status="running",
    )


@pytest.fixture
def node_execution(
    db: None,
    workflow_execution: Any,
    workflow_node: Any,
) -> Any:
    from workflows.models.execution import NodeExecution

    return NodeExecution.objects.create(
        workflow_execution=workflow_execution,
        node=workflow_node,
        status="running",
    )


def _make_repo(name_prefix: str) -> Any:
    """带 GitCredential 的 Repository（避免 credential 反向 OneToOne 异常）。"""
    from common.encryption import encrypt_value
    from repositories.models import AuthType, GitCredential, Repository

    repo = Repository.objects.create(
        name=f"{name_prefix}-{uuid4().hex[:8]}",
        git_url=f"https://git.example.com/test/{name_prefix}.git",
        default_branch="main",
    )
    GitCredential.objects.create(
        repository=repo,
        auth_type=AuthType.ACCESS_TOKEN,
        encrypted_token=encrypt_value("ctx-test-token"),
    )
    return repo


@pytest.fixture
def ctx_repository(db: None) -> Any:
    return _make_repo("ctx-repo")


def _make_execution_context(
    *,
    node_execution: Any,
    workflow_execution: Any,
    repos: list[Any],
    node_config: dict[str, Any] | None = None,
) -> Any:
    """ExecutionContext 带最小 plan_data，每仓 1 个 task。"""
    from workflows.nodes.base import ExecutionContext

    plan_data = {
        "title": "Ctx Plan",
        "global_context": "Test global context.",
        "execution_plan": [
            {
                "repository_id": str(repo.id),
                "task_description": "Do something",
                "branch_name": _BRANCH,
            }
            for repo in repos
        ],
        "branch_name": _BRANCH,
    }
    return ExecutionContext(
        execution_id=str(workflow_execution.id),
        node_id=str(node_execution.node_id),
        node_config=node_config or {},
        input_data={"plan": plan_data},
        workflow_context={},
        previous_outputs={},
        workflow_execution=workflow_execution,
        node_execution=node_execution,
    )


@pytest.fixture
def mock_dispatcher(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Mock `get_dispatcher().dispatch()` —— 捕获 DispatchTask 到 list 供断言。"""
    dispatched: list[Any] = []

    class _FakeDispatcher:
        async def dispatch(self, task: Any) -> None:
            dispatched.append(task)

    _instance = _FakeDispatcher()

    def _get_disp() -> Any:
        return _instance

    monkeypatch.setattr("runners.dispatcher.get_dispatcher", _get_disp)
    return dispatched


@pytest.fixture
def mock_subagent_session_create(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock SubAgentSession / AgentSession 入库，避免真实 FK 关联副作用。"""
    from agents.models import AgentSession
    from subagent.models import SubAgentSession

    class _FakeAFilter:
        async def afirst(self) -> Any:
            return None

    def _fake_filter(*args: Any, **kwargs: Any) -> Any:
        return _FakeAFilter()

    async def _fake_acreate(**kwargs: Any) -> Any:
        return AgentSession(id=uuid4(), metadata=kwargs.get("metadata", {}))

    monkeypatch.setattr(AgentSession.objects, "filter", _fake_filter)
    monkeypatch.setattr(AgentSession.objects, "acreate", _fake_acreate)

    async def _fake_sub_aupdate_or_create(**kwargs: Any) -> tuple[Any, bool]:
        return (SubAgentSession(session_id=kwargs.get("session_id", "")), True)

    monkeypatch.setattr(SubAgentSession.objects, "aupdate_or_create", _fake_sub_aupdate_or_create)


@pytest.fixture
def mock_fetch_repositories_with_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch AICodingNode._fetch_repositories 使其 select_related("credential") 预加载。"""
    from repositories.models import GitCredential
    from workflows.nodes.ai.coding import AICodingNode

    monkeypatch.setattr(GitCredential, "ssl_verify", True, raising=False)

    async def _fake_fetch(self: Any, repo_ids: set[str]) -> dict[str, Any]:
        from repositories.models import Repository

        return {
            str(r.id): r
            async for r in Repository.objects.select_related("credential").filter(
                id__in=repo_ids, is_deleted=False
            )
        }

    monkeypatch.setattr(AICodingNode, "_fetch_repositories", _fake_fetch)


@pytest.fixture
def mock_anthropic_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    """monkeypatch ProviderConfigService.aresolve_or_error → 合法 ResolvedProviderConfig。"""
    monkeypatch.setattr(
        "services.provider_config.ProviderConfigService.aresolve_or_error",
        AsyncMock(
            return_value=ResolvedProviderConfig(
                provider_type=ProviderType.ANTHROPIC,
                api_key="sk-ant-test-key",
                base_url="",
                source="system",
            )
        ),
    )


@pytest.fixture
def log() -> Any:
    return structlog.get_logger("test-coding-dispatch-project-context")


# =========================================================================
# 领域数据 helpers
# =========================================================================


@sync_to_async
def _make_user(username_prefix: str) -> Any:
    return User.objects.create_user(
        username=f"{username_prefix}-{uuid4().hex[:8]}", password="x"
    )


async def _make_project(owner: Any, key: str) -> Any:
    from initiatives.services import ProjectService
    from projects.models import Space

    space = await sync_to_async(Space.objects.create)(name=f"S-{key}")
    proj, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=owner
    )
    return proj


@sync_to_async
def _bind_branch(project: Any, repo: Any, branch: str, owner: Any) -> Any:
    from initiatives.models import ProjectBranch

    return ProjectBranch.objects.create(
        project=project, repository=repo, branch_name=branch, created_by=owner
    )


async def _set_triggered_by(workflow_execution: Any, user: Any) -> None:
    workflow_execution.triggered_by = user
    await workflow_execution.asave(update_fields=["triggered_by"])


async def _run_node(context: Any, log: Any) -> None:
    from workflows.nodes.ai.coding import AICodingNode

    node = AICodingNode()
    await node._execute_with_branch(context=context, branch_name=_BRANCH, log=log)


# =========================================================================
# ProjectBranch 绑定命中 → metadata + prompt 双注入（与 chat 路径一致）
# =========================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_branch_binding_injects_context_env_and_prompt(
    ctx_repository: Any,
    node_execution: Any,
    workflow_execution: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """ProjectBranch 反查命中 → env_FRIDAY_TASK_PROJECT_CONTEXT + prompt 头部上下文块。"""
    user = await _make_user("wf-ctx")
    project = await _make_project(user, key="wf-ctx-bind")
    await _bind_branch(project, ctx_repository, _BRANCH, user)
    await _set_triggered_by(workflow_execution, user)

    context = _make_execution_context(
        node_execution=node_execution,
        workflow_execution=workflow_execution,
        repos=[ctx_repository],
    )

    with patch(
        "services.project_context_packer.apack_dispatch_context",
        new_callable=AsyncMock,
        return_value=_CTX_BLOCK,
    ) as mock_pack:
        await _run_node(context, log)

    assert len(mock_dispatcher) == 1, "应恰好触发一次 dispatch"
    task = mock_dispatcher[0]
    # env 注入与 chat 路径一致（HOOK-04 两件套之一）
    assert task.metadata["env_FRIDAY_TASK_PROJECT_CONTEXT"] == _CTX_BLOCK
    # prompt 以上下文块开头，`---` 分隔符在（prepend_project_context 语义）
    assert task.prompt.startswith(f"{_CTX_BLOCK}\n\n---\n\n")
    # 召回 user = dispatch_user（triggered_by 解析）
    assert mock_pack.await_count == 1
    called_project, called_user = mock_pack.await_args.args
    assert str(called_project.id) == str(project.id)
    assert called_user.id == user.id
    assert mock_pack.await_args.kwargs.get("query") == _BRANCH


# =========================================================================
# work_item 关联 fallback（无 ProjectBranch 绑定）
# =========================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_work_item_link_fallback_injects_context(
    ctx_repository: Any,
    node_execution: Any,
    workflow_execution: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """无 ProjectBranch 绑定但 ProjectWorkItemLink 命中 → 同样注入。"""
    from delivery.services import WorkItemIdentity, WorkItemService
    from initiatives.models import ProjectWorkItemLink

    user = await _make_user("wf-wi")
    project = await _make_project(user, key="wf-ctx-wi")
    work_item = await WorkItemService().upsert(
        WorkItemIdentity(
            feishu_project_key="wf-ctx-wi-fpk",
            work_item_type="story",
            work_item_id=90031,
        ),
        source="feishu_webhook",
        fetch=False,
    )
    await sync_to_async(ProjectWorkItemLink.objects.create)(
        project=project, work_item=work_item
    )
    await _set_triggered_by(workflow_execution, user)

    context = _make_execution_context(
        node_execution=node_execution,
        workflow_execution=workflow_execution,
        repos=[ctx_repository],
        node_config={"work_item_id": "90031"},
    )

    with patch(
        "services.project_context_packer.apack_dispatch_context",
        new_callable=AsyncMock,
        return_value=_CTX_BLOCK,
    ) as mock_pack:
        await _run_node(context, log)

    assert len(mock_dispatcher) == 1
    task = mock_dispatcher[0]
    assert task.metadata["env_FRIDAY_TASK_PROJECT_CONTEXT"] == _CTX_BLOCK
    assert task.prompt.startswith(f"{_CTX_BLOCK}\n\n---\n\n")
    called_project, _called_user = mock_pack.await_args.args
    assert str(called_project.id) == str(project.id)


# =========================================================================
# 复用：同 project 两仓 → apack_dispatch_context 只召回一次
# =========================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_same_project_two_repos_packs_once(
    db: None,
    node_execution: Any,
    workflow_execution: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """同 project 两仓：按 (project, branch) 解析一次逐仓复用（不重复召回）。"""
    repo_a = await sync_to_async(_make_repo)("ctx-reuse-a")
    repo_b = await sync_to_async(_make_repo)("ctx-reuse-b")

    user = await _make_user("wf-reuse")
    project = await _make_project(user, key="wf-ctx-reuse")
    await _bind_branch(project, repo_a, _BRANCH, user)
    await _bind_branch(project, repo_b, _BRANCH, user)
    await _set_triggered_by(workflow_execution, user)

    context = _make_execution_context(
        node_execution=node_execution,
        workflow_execution=workflow_execution,
        repos=[repo_a, repo_b],
    )

    with patch(
        "services.project_context_packer.apack_dispatch_context",
        new_callable=AsyncMock,
        return_value=_CTX_BLOCK,
    ) as mock_pack:
        await _run_node(context, log)

    assert len(mock_dispatcher) == 2, "两仓各 dispatch 一次"
    # 同 project → 只召回一次，逐仓复用同一份上下文
    assert mock_pack.await_count == 1
    for task in mock_dispatcher:
        assert task.metadata["env_FRIDAY_TASK_PROJECT_CONTEXT"] == _CTX_BLOCK
        assert task.prompt.startswith(f"{_CTX_BLOCK}\n\n---\n\n")


# =========================================================================
# fail-soft：无 project / 无 dispatch_user / packer 抛异常 → 与现状逐字一致
# =========================================================================


def _assert_no_injection(task: Any) -> None:
    assert "env_FRIDAY_TASK_PROJECT_CONTEXT" not in task.metadata
    assert not task.prompt.startswith(_CTX_BLOCK)
    assert task.prompt.startswith("# 项目背景"), "prompt 无 prepend，与现状逐字一致"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_no_project_binding_dispatches_without_injection(
    ctx_repository: Any,
    node_execution: Any,
    workflow_execution: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """无 ProjectBranch 绑定、无 work_item 关联 → dispatch 成功且零注入（fail-soft）。"""
    user = await _make_user("wf-noproj")
    await _set_triggered_by(workflow_execution, user)

    context = _make_execution_context(
        node_execution=node_execution,
        workflow_execution=workflow_execution,
        repos=[ctx_repository],
    )

    with patch(
        "services.project_context_packer.apack_dispatch_context",
        new_callable=AsyncMock,
        return_value=_CTX_BLOCK,
    ) as mock_pack:
        await _run_node(context, log)

    assert len(mock_dispatcher) == 1
    assert mock_pack.await_count == 0, "无 project 定位 → 不召回"
    _assert_no_injection(mock_dispatcher[0])


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_no_dispatch_user_dispatches_without_injection(
    ctx_repository: Any,
    node_execution: Any,
    workflow_execution: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """有绑定但无 triggered_by（背景触发）→ 不召回不注入（user=triggered_by 契约）。"""
    owner = await _make_user("wf-nouser")
    project = await _make_project(owner, key="wf-ctx-nouser")
    await _bind_branch(project, ctx_repository, _BRANCH, owner)
    # 不设 workflow_execution.triggered_by → dispatch_user=None

    context = _make_execution_context(
        node_execution=node_execution,
        workflow_execution=workflow_execution,
        repos=[ctx_repository],
    )

    with patch(
        "services.project_context_packer.apack_dispatch_context",
        new_callable=AsyncMock,
        return_value=_CTX_BLOCK,
    ) as mock_pack:
        await _run_node(context, log)

    assert len(mock_dispatcher) == 1
    assert mock_pack.await_count == 0, "无 dispatch_user → 不召回"
    _assert_no_injection(mock_dispatcher[0])


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_packer_exception_fail_soft_dispatch_succeeds(
    ctx_repository: Any,
    node_execution: Any,
    workflow_execution: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """召回抛异常 → dispatch 照常成功且零注入（T-103-15：召回失败绝不阻断编码派发）。"""
    user = await _make_user("wf-boom")
    project = await _make_project(user, key="wf-ctx-boom")
    await _bind_branch(project, ctx_repository, _BRANCH, user)
    await _set_triggered_by(workflow_execution, user)

    context = _make_execution_context(
        node_execution=node_execution,
        workflow_execution=workflow_execution,
        repos=[ctx_repository],
    )

    with patch(
        "services.project_context_packer.apack_dispatch_context",
        new_callable=AsyncMock,
        side_effect=RuntimeError("packer boom"),
    ):
        await _run_node(context, log)

    assert len(mock_dispatcher) == 1, "召回失败绝不阻断 dispatch"
    _assert_no_injection(mock_dispatcher[0])
