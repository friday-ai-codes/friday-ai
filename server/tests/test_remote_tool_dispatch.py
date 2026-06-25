"""RTOOL-03 server dispatch 契约 RED 脚手架：tools endpoint 推导 + 机会性 PAT 注入 + 不读 DB 明文。

钉死 AICodingNode dispatch 路径在 RemoteTool 闭环中的可验证契约：
- `env_FRIDAY_TASK_TOOLS_ENDPOINT` 由 `settings.FRIDAY_BASE_URL` 推导（**非** callback_url，Pitfall 1）。
- 机会性 PAT（CONTEXT <resolution> Option C + 机会性 B）：仅当「实时请求线程提供明文 PAT」时注入
  `env_FRIDAY_TASK_USER_TOKEN`；无明文来源（背景/飞书触发）→ 不注入该键。
- PAT-02 安全不变量：dispatch 路径**绝不**从 AccessToken/DB 取明文（AccessToken 仅存 sha256）。

WR-3 机制钉定（plan-checker fix）：机会性 PAT 经 `_run_repo_coding` 的**可选 `user_pat` 参数**下传
（mirror 既有 `anthropic_api_key` 范式）。`_execute_with_branch` 通过 `AICodingNode._resolve_user_pat`
解析实时 PAT 明文后以 `user_pat=` 传入；非空时注入 `env_FRIDAY_TASK_USER_TOKEN`。Wave 2（11-04）须实现
**正是这套**：`_resolve_user_pat` 解析器 + `user_pat` 形参 + metadata 注入。

复刻 test_coding_anthropic_base_url_passthrough.py 的 dispatch 捕获 fixture 套（就地复制保独立可单跑）。
impl 落地前：endpoint / opportunistic-PAT 用例 RED（fail）；omit / never-reads-DB 为安全不变量（GREEN 且须保持）。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import structlog

from services.provider_config import (
    ProviderType,
    ResolvedProviderConfig,
)

# =========================================================================
# Fixtures（复刻 test_coding_anthropic_base_url_passthrough.py 的 dispatch 捕获套）
# =========================================================================


@pytest.fixture
def workflow(db: None, project: Any) -> Any:
    from workflows.models.workflow import Workflow

    return Workflow.objects.create(name="RemoteTool Dispatch Workflow", space=project)


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


@pytest.fixture
def rtool_repository(db: None) -> Any:
    """带 GitCredential 的 Repository（避免 _run_repo_coding 内 credential 反向 OneToOne 异常）。"""
    from common.encryption import encrypt_value
    from repositories.models import AuthType, GitCredential, Repository

    repo = Repository.objects.create(
        name=f"rtool-repo-{uuid4().hex[:8]}",
        git_url="https://git.example.com/test/rtool-repo.git",
        default_branch="main",
    )
    cred = GitCredential.objects.create(
        repository=repo,
        auth_type=AuthType.ACCESS_TOKEN,
        encrypted_token=encrypt_value("rtool-test-token"),
    )
    cred.ssl_verify = True  # type: ignore[attr-defined]
    return repo


@pytest.fixture
def execution_context(
    node_execution: Any,
    workflow_execution: Any,
    rtool_repository: Any,
) -> Any:
    """ExecutionContext 带最小 plan_data 含 1 个仓库 1 个 task。"""
    from workflows.nodes.base import ExecutionContext

    plan_data = {
        "title": "Test Plan",
        "global_context": "Test global context.",
        "execution_plan": [
            {
                "repository_id": str(rtool_repository.id),
                "task_description": "Do something",
                "branch_name": "feat/test-branch",
            },
        ],
        "branch_name": "feat/test-branch",
    }
    return ExecutionContext(
        execution_id=str(workflow_execution.id),
        node_id=str(node_execution.node_id),
        node_config={},
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
def mock_fetch_repositories_with_credential(
    monkeypatch: pytest.MonkeyPatch, rtool_repository: Any
) -> None:
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
    """structlog-bind 兼容 log 对象供 _execute_with_branch 使用。"""
    return structlog.get_logger("test-remote-tool-dispatch")


# =========================================================================
# RTOOL-03：tools endpoint 由 FRIDAY_BASE_URL 推导（非 callback_url，Pitfall 1）
# =========================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_dispatch_metadata_includes_tools_endpoint(
    settings: Any,
    execution_context: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """RED：metadata 含 env_FRIDAY_TASK_TOOLS_ENDPOINT，由 FRIDAY_BASE_URL 推导（非 callback_url）。"""
    settings.FRIDAY_BASE_URL = "https://friday.example.com"

    from workflows.nodes.ai.coding import AICodingNode

    node = AICodingNode()
    await node._execute_with_branch(
        context=execution_context,
        branch_name="feat/test-branch",
        log=log,
    )

    assert len(mock_dispatcher) == 1, "应恰好触发一次 dispatch"
    meta = mock_dispatcher[0].metadata
    assert meta["env_FRIDAY_TASK_TOOLS_ENDPOINT"] == "https://friday.example.com/api/tools/execute/"


# =========================================================================
# RTOOL-03：机会性 PAT —— 实时来源存在时注入（WR-3：经 user_pat 形参）
# =========================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_dispatch_opportunistic_pat_injected_when_present(
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    execution_context: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """RED：实时请求线程提供明文 PAT → metadata 注入 env_FRIDAY_TASK_USER_TOKEN。

    WR-3 机制钉定：Wave 2 须经 `AICodingNode._resolve_user_pat` 解析实时 PAT，
    以可选 `user_pat=` 形参下传 `_run_repo_coding`（mirror anthropic_api_key），
    非空时写入 metadata。本用例 monkeypatch 该解析器模拟实时明文来源。
    """
    settings.FRIDAY_BASE_URL = "https://friday.example.com"

    from workflows.nodes.ai.coding import AICodingNode

    # 模拟「带 PAT 的实时请求线程」：解析器返回明文 PAT（绝不来自 DB）。
    monkeypatch.setattr(
        AICodingNode,
        "_resolve_user_pat",
        AsyncMock(return_value="friday_pat_REALTIME"),
        raising=False,
    )

    node = AICodingNode()
    await node._execute_with_branch(
        context=execution_context,
        branch_name="feat/test-branch",
        log=log,
    )

    assert len(mock_dispatcher) == 1
    meta = mock_dispatcher[0].metadata
    assert meta["env_FRIDAY_TASK_USER_TOKEN"] == "friday_pat_REALTIME"


# =========================================================================
# RTOOL-03 / PAT-02：无实时来源 → 不注入（绝不从 AccessToken/DB 取明文）
# =========================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_dispatch_omits_pat_when_no_realtime_source(
    settings: Any,
    execution_context: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """安全不变量：无明文来源（默认背景触发）→ metadata 不含 env_FRIDAY_TASK_USER_TOKEN（PAT-02）。"""
    settings.FRIDAY_BASE_URL = "https://friday.example.com"

    from workflows.nodes.ai.coding import AICodingNode

    node = AICodingNode()
    await node._execute_with_branch(
        context=execution_context,
        branch_name="feat/test-branch",
        log=log,
    )

    assert len(mock_dispatcher) == 1
    meta = mock_dispatcher[0].metadata
    assert "env_FRIDAY_TASK_USER_TOKEN" not in meta, (
        "无实时明文来源时绝不注入 PAT（PAT-02：明文绝不来自 AccessToken/DB）"
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_dispatch_never_reads_access_token_plaintext(
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    execution_context: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """安全不变量（T-11-02）：dispatch 路径绝不查询 AccessToken（明文绝不来自 DB）。"""
    settings.FRIDAY_BASE_URL = "https://friday.example.com"

    from access_tokens.models import AccessToken

    calls: list[str] = []

    def _make_spy(name: str, orig: Any) -> Any:
        def _spy(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return orig(*args, **kwargs)

        return _spy

    for mname in ("filter", "get", "aget", "all", "afirst"):
        if hasattr(AccessToken.objects, mname):
            monkeypatch.setattr(
                AccessToken.objects,
                mname,
                _make_spy(mname, getattr(AccessToken.objects, mname)),
            )

    from workflows.nodes.ai.coding import AICodingNode

    node = AICodingNode()
    await node._execute_with_branch(
        context=execution_context,
        branch_name="feat/test-branch",
        log=log,
    )

    assert calls == [], f"dispatch 路径不得查询 AccessToken 取明文（PAT-02），实际调用：{calls}"
    # 兜底：metadata 中不得出现任何 friday_pat_ 来自 DB 的注入。
    assert len(mock_dispatcher) == 1
    meta_text = str(mock_dispatcher[0].metadata)
    assert "friday_pat_" not in meta_text


# =========================================================================
# RTOOL follow-up：实时明文 PAT 通道接入（contextvar → ExecutionContext 瞬态字段）
# =========================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_resolve_user_pat_reads_execution_context_field(
    settings: Any,
    execution_context: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """GREEN：明文经 ExecutionContext.user_pat_plaintext 真实下传 → 注入 USER_TOKEN。

    不 monkeypatch _resolve_user_pat，验证 follow-up 接入后解析器真实读取上下文瞬态字段
    （通道：请求 ContextVar → start_execution → execution 瞬态属性 → ExecutionContext）。
    """
    settings.FRIDAY_BASE_URL = "https://friday.example.com"
    execution_context.user_pat_plaintext = "friday_pat_REALCHANNEL"

    from workflows.nodes.ai.coding import AICodingNode

    node = AICodingNode()
    await node._execute_with_branch(
        context=execution_context, branch_name="feat/test-branch", log=log
    )

    assert len(mock_dispatcher) == 1
    assert mock_dispatcher[0].metadata["env_FRIDAY_TASK_USER_TOKEN"] == "friday_pat_REALCHANNEL"


def test_pat_context_var_roundtrip() -> None:
    """ContextVar 通道 set/get/reset 语义；reset 后回到无明文（空串）。"""
    from access_tokens.context import get_request_pat, reset_request_pat, set_request_pat

    assert get_request_pat() == ""
    token = set_request_pat("friday_pat_CTX")
    assert get_request_pat() == "friday_pat_CTX"
    reset_request_pat(token)
    assert get_request_pat() == ""
    # 空写入等价无来源。
    set_request_pat("")
    assert get_request_pat() == ""


def test_user_pat_plaintext_is_transient_not_persisted_field() -> None:
    """PAT-02 守护：user_pat_plaintext 仅运行时瞬态，绝不是 WorkflowExecution 的 DB 字段。"""
    from workflows.models.execution import WorkflowExecution

    field_names = {f.name for f in WorkflowExecution._meta.get_fields()}
    assert "user_pat_plaintext" not in field_names
    assert "_user_pat_plaintext" not in field_names


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_dispatch_forwards_request_pat_to_start_execution(
    monkeypatch: pytest.MonkeyPatch,
    workflow: Any,
) -> None:
    """触发边界：dispatch 从请求 ContextVar 取明文并以 user_pat= 转发给 start_execution。"""
    from access_tokens.context import reset_request_pat, set_request_pat
    from workflows.triggers.context import TriggerContext
    from workflows.triggers.dispatcher import TriggerDispatcher

    captured: dict[str, Any] = {}

    async def _fake_start_execution(**kwargs: Any) -> Any:
        captured.update(kwargs)

        class _Exec:
            id = uuid4()

        return _Exec()

    dispatcher = TriggerDispatcher()
    monkeypatch.setattr(dispatcher.engine, "start_execution", _fake_start_execution)

    context = TriggerContext(trigger_type="manual", raw_payload={}, workflow=workflow)
    token = set_request_pat("friday_pat_FROM_REQUEST")
    try:
        await dispatcher.dispatch_single(context)
    finally:
        reset_request_pat(token)

    assert captured.get("user_pat") == "friday_pat_FROM_REQUEST"
