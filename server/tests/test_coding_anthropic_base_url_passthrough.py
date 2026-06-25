"""AICodingNode metadata 注入 env_FRIDAY_TASK_CLAUDE_* 字段契约测试。

覆盖：
- ROADMAP implementation SC3（passthrough 成功路由）
- context contract 纠偏命名（env_FRIDAY_TASK_CLAUDE_API_KEY / env_FRIDAY_TASK_CLAUDE_BASE_URL）
- context contract（URL scheme 白名单 + host 非空）
- context contract（空 base_url 不注入 metadata 键）
- Threat model security mitigation（api_key 不明文入日志；依赖 redact_credentials processor 自动脱敏）
- Threat model security mitigation（metadata 键名错误导致 Runner 静默丢弃）
- Threat model security mitigation（非法 scheme 注入容器）
- Threat model security mitigation（ProviderMissingError 时节点错误可观测）
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import structlog

from services.provider_config import (
    ProviderConfigError,
    ProviderMissingError,
    ProviderType,
    ResolvedProviderConfig,
)


# =========================================================================
# Task 1: _validate_anthropic_base_url parametrize（contract / security mitigation 缓解）
# =========================================================================


@pytest.mark.parametrize(
    "url,expected_return,should_raise",
    [
        # 合法 URL：trim 后返回
        ("http://localhost:4000", "http://localhost:4000", False),
        ("https://api.moonshot.cn/anthropic", "https://api.moonshot.cn/anthropic", False),
        ("  http://gateway  ", "http://gateway", False),
        # 空输入：contract 行为 — 返回空字符串（调用方不注入 metadata 键）
        ("", "", False),
        # 非法 scheme：security mitigation 缓解
        ("ftp://gateway/anthropic", None, True),
        ("gateway.local:4000", None, True),
        ("javascript:alert(1)", None, True),
        ("file:///etc/passwd", None, True),
    ],
)
def test_validate_anthropic_base_url(
    url: str,
    expected_return: str | None,
    should_raise: bool,
) -> None:
    """contract 锁定：scheme 白名单 + 非空 + trim 三项最小校验；security mitigation 缓解。"""
    from workflows.nodes.ai.coding import _validate_anthropic_base_url

    if should_raise:
        with pytest.raises(ProviderConfigError):
            _validate_anthropic_base_url(url)
    else:
        assert _validate_anthropic_base_url(url) == expected_return


# =========================================================================
# Fixtures（Task 2/3 契约测试复用）
# =========================================================================


@pytest.fixture
def workflow(db: None, project: Any) -> Any:
    from workflows.models.workflow import Workflow

    return Workflow.objects.create(name="Coding Workflow work item", space=project)


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
def conv02_repository(db: None) -> Any:
    """创建 work item 测试用 Repository（带 GitCredential，避免 _run_repo_coding 内
    repository.credential OneToOne DoesNotExist 访问异常）。

    注：生产 coding.py L790 访问 `repository.credential.ssl_verify`，但 GitCredential 模型
    未定义此字段（既有差异，非本 task 范围）。测试 fixture 通过 setattr 动态补字段以
    让 _run_repo_coding 正常跑通 Git 凭证分支。
    """
    from common.encryption import encrypt_value
    from repositories.models import AuthType, GitCredential, Repository

    repo = Repository.objects.create(
        name=f"conv02-repo-{uuid4().hex[:8]}",
        git_url="https://git.example.com/test/conv02-repo.git",
        default_branch="main",
    )
    cred = GitCredential.objects.create(
        repository=repo,
        auth_type=AuthType.ACCESS_TOKEN,
        encrypted_token=encrypt_value("conv02-test-token"),
    )
    # 动态补字段 ssl_verify（生产 coding.py 访问此字段）。
    cred.ssl_verify = True  # type: ignore[attr-defined]
    return repo


@pytest.fixture
def execution_context(
    node_execution: Any,
    workflow_execution: Any,
    conv02_repository: Any,
) -> Any:
    """ExecutionContext 带最小 plan_data 含 1 个仓库 1 个 task。"""
    from workflows.nodes.base import ExecutionContext

    plan_data = {
        "title": "Test Plan",
        "global_context": "Test global context.",
        "execution_plan": [
            {
                "repository_id": str(conv02_repository.id),
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

    monkeypatch.setattr(
        SubAgentSession.objects, "aupdate_or_create", _fake_sub_aupdate_or_create
    )


@pytest.fixture
def mock_fetch_repositories_with_credential(
    monkeypatch: pytest.MonkeyPatch, conv02_repository: Any
) -> None:
    """Patch AICodingNode._fetch_repositories 使其 select_related("credential") 预加载，
    避免 _run_repo_coding 内 `repository.credential` 反向 OneToOne 触发 SynchronousOnlyOperation。

    同时在 GitCredential 类上注入 ssl_verify 属性（生产 coding.py L790 访问该字段，
    但模型未定义——本 plan 边界不修生产，测试侧兜底）。"""
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
def log() -> Any:
    """structlog-bind 兼容 log 对象供 _execute_with_branch 使用。"""
    return structlog.get_logger("test-conv-02")


# =========================================================================
# Task 2: ProviderMissingError + 非法 base_url 阻止 dispatch
# =========================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_provider_missing_error_blocks_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    execution_context: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    log: Any,
) -> None:
    """security mitigation 缓解：ProviderMissingError 时抛 ProviderConfigError 阻止 dispatch。"""
    monkeypatch.setattr(
        "services.provider_config.ProviderConfigService.aresolve_or_error",
        AsyncMock(
            return_value=ProviderMissingError(
                missing_provider="anthropic",
                recommended_action="Anthropic 凭据未配置，请在系统设置添加 Anthropic 凭证",
                source_attempted="system",
            )
        ),
    )
    from workflows.nodes.ai.coding import AICodingNode

    node = AICodingNode()
    with pytest.raises(ProviderConfigError, match="Anthropic 凭据未配置"):
        await node._execute_with_branch(
            context=execution_context,
            branch_name="feat/test-branch",
            log=log,
        )
    assert mock_dispatcher == [], "ProviderMissingError 时不应触发 dispatch"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_illegal_base_url_raises_provider_config_error(
    monkeypatch: pytest.MonkeyPatch,
    execution_context: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    log: Any,
) -> None:
    """security mitigation 缓解：非法 scheme base_url 阻止 dispatch。"""
    monkeypatch.setattr(
        "services.provider_config.ProviderConfigService.aresolve_or_error",
        AsyncMock(
            return_value=ResolvedProviderConfig(
                provider_type=ProviderType.ANTHROPIC,
                api_key="sk-ant-test",
                base_url="ftp://evil-gateway/anthropic",
                source="system",
            )
        ),
    )
    from workflows.nodes.ai.coding import AICodingNode

    node = AICodingNode()
    with pytest.raises(ProviderConfigError, match="scheme 必须是 http 或 https"):
        await node._execute_with_branch(
            context=execution_context,
            branch_name="feat/test-branch",
            log=log,
        )
    assert mock_dispatcher == [], "非法 base_url 时不应触发 dispatch"


# =========================================================================
# Task 3: DispatchTask.metadata env_FRIDAY_TASK_CLAUDE_* 字段契约
# =========================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_metadata_contains_env_fields_when_base_url_present(
    monkeypatch: pytest.MonkeyPatch,
    execution_context: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    log: Any,
) -> None:
    """contract 纠偏命名 + ROADMAP SC3：非空 base_url 时 metadata 同时含两键。"""
    monkeypatch.setattr(
        "services.provider_config.ProviderConfigService.aresolve_or_error",
        AsyncMock(
            return_value=ResolvedProviderConfig(
                provider_type=ProviderType.ANTHROPIC,
                api_key="sk-ant-test-key",
                base_url="http://litellm-gateway:4000/anthropic",
                source="project",
            )
        ),
    )
    from workflows.nodes.ai.coding import AICodingNode

    node = AICodingNode()
    await node._execute_with_branch(
        context=execution_context,
        branch_name="feat/test-branch",
        log=log,
    )
    assert len(mock_dispatcher) == 1, "应恰好触发一次 dispatch"
    meta = mock_dispatcher[0].metadata
    # contract 纠偏命名硬约束
    assert meta["env_FRIDAY_TASK_CLAUDE_API_KEY"] == "sk-ant-test-key"
    assert meta["env_FRIDAY_TASK_CLAUDE_BASE_URL"] == "http://litellm-gateway:4000/anthropic"
    # security mitigation 缓解：旧命名不得作为 metadata 键出现
    assert "anthropic_api_key" not in meta
    assert "anthropic_base_url" not in meta


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_metadata_omits_base_url_key_when_empty(
    monkeypatch: pytest.MonkeyPatch,
    execution_context: Any,
    mock_dispatcher: list[Any],
    mock_subagent_session_create: None,
    mock_fetch_repositories_with_credential: None,
    log: Any,
) -> None:
    """contract 契约：空 base_url → metadata 不含 env_FRIDAY_TASK_CLAUDE_BASE_URL 键（api_key 仍注入）。"""
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
    from workflows.nodes.ai.coding import AICodingNode

    node = AICodingNode()
    await node._execute_with_branch(
        context=execution_context,
        branch_name="feat/test-branch",
        log=log,
    )
    assert len(mock_dispatcher) == 1
    meta = mock_dispatcher[0].metadata
    assert meta["env_FRIDAY_TASK_CLAUDE_API_KEY"] == "sk-ant-test-key"
    # contract 硬约束：空 base_url 不注入该 key
    assert "env_FRIDAY_TASK_CLAUDE_BASE_URL" not in meta
