"""workflow dispatch 契约测试：tools endpoint 推导 + 任务级短 TTL token 铸造注入。

Phase 103 AGENT-01 机制换代：机会性 PAT 透传通道（请求级 ContextVar 捕获 + 引擎
瞬态字段下传 + 节点解析器）已整体移除，改为按 `triggered_by` 经
`access_tokens.services.mint_task_token` **新签发**任务级短 TTL token 注入
`env_FRIDAY_TASK_USER_TOKEN`（解析器：`AICodingNode._resolve_dispatch_user`）。

PAT-02 底线不变（语义澄清）：
- 明文不落盘、不可从 DB 反取——DB 只存 sha256，dispatch 路径绝不调用 AccessToken
  的**读取类** manager 方法反取存量 token（T-11-02 spy 收窄为读取类断言）。
- mint 是"新造"不是"反取"：明文由 generate_pat() 内存生成、一次性直进容器 env
  （Key Decisions 已定版推翻 PATX-04 搁置）。
- 无 triggered_by（背景触发）→ 不注入该键（降级不挂，零回归）。

复刻 test_coding_anthropic_base_url_passthrough.py 的 dispatch 捕获 fixture 套（就地复制保独立可单跑）。
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
# Phase 103 AGENT-01：triggered_by 存在时铸造任务级 token 注入
# =========================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_dispatch_mints_task_token_when_triggered_by_present(
    settings: Any,
    execution_context: Any,
    workflow_execution: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """triggered_by 可解析 → metadata 注入**新签发**的 friday_pat_ token + 知识端点。

    机制换代（Phase 103）：`_resolve_dispatch_user` 解析 triggered_by，
    `_run_repo_coding(dispatch_user=...)` 内经 mint_task_token 新签发——断言
    DB 行 kind=="task" 且 token_hash==hash_token(env 明文)，证明"新造"而非复用存量。
    """
    settings.FRIDAY_BASE_URL = "https://friday.example.com"

    from asgiref.sync import sync_to_async
    from django.contrib.auth import get_user_model

    from access_tokens.models import AccessToken
    from runners.models import hash_token
    from workflows.nodes.ai.coding import AICodingNode

    user = await sync_to_async(get_user_model().objects.create_user)(
        username=f"wf-trigger-{uuid4().hex[:8]}", password="x"
    )
    workflow_execution.triggered_by = user
    await workflow_execution.asave(update_fields=["triggered_by"])

    node = AICodingNode()
    await node._execute_with_branch(
        context=execution_context,
        branch_name="feat/test-branch",
        log=log,
    )

    assert len(mock_dispatcher) == 1
    meta = mock_dispatcher[0].metadata
    plaintext = meta["env_FRIDAY_TASK_USER_TOKEN"]
    assert plaintext.startswith("friday_pat_")
    # 知识端点同点位注入（AGENT-02 服务端面）：base 不带路径
    assert meta["env_FRIDAY_TASK_KNOWLEDGE_ENDPOINT"] == "https://friday.example.com"

    token = await AccessToken.objects.aget(kind="task", created_by=user)
    assert token.token_hash == hash_token(plaintext)
    assert token.session_id == mock_dispatcher[0].session_id


# =========================================================================
# PAT-02：无 triggered_by → 不注入（绝不从 AccessToken/DB 取明文）
# =========================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_dispatch_omits_token_when_no_triggered_by(
    settings: Any,
    execution_context: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    mock_anthropic_resolved: None,
    log: Any,
) -> None:
    """安全不变量：无 triggered_by（背景触发）→ metadata 不含 env_FRIDAY_TASK_USER_TOKEN。"""
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
        "无 triggered_by 时绝不注入 token（降级不挂，PAT-02：明文绝不来自 AccessToken/DB）"
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
    """安全不变量（T-11-02，Phase 103 收窄）：dispatch 路径绝不调用 AccessToken 的
    **读取类** manager 方法反取存量 token（PAT-02：DB 只有 sha256，明文不可反取）。

    机制换代说明：mint_task_token 会 `acreate` 新行（新签发合法且必要），故 spy
    只钉读取类方法（filter/get/aget/all/afirst）——本用例无 triggered_by，读取与
    写入都不应发生。
    """
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
    # 兜底：无 triggered_by → metadata 中不得出现任何 friday_pat_ 注入。
    assert len(mock_dispatcher) == 1
    meta_text = str(mock_dispatcher[0].metadata)
    assert "friday_pat_" not in meta_text
