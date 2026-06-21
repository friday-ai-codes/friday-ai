"""implementation Task 1 — contract Execution Provider 快照集成测试。

覆盖 context contract/contract/contract 全链路：
    A: WorkflowEngine.start_execution 启动 DAG 含 AI 节点 → node_snapshots 写入
    B: 某 AI 节点凭证解析失败（ProviderMissingError）→ 该节点不写入 snapshot
    C: 非 AI 节点（ScriptNode / DataTransformNode）→ 不写入 snapshot（白名单过滤）
    D: AI 节点 runner 读 node_snapshots[node_id] 命中 → 不再调 aresolve_or_error
    E: AI 节点 runner miss → fallback aresolve + structlog warning
    F: snapshot 写入的 provider_type 是 str（JSON 序列化安全）

Analog: test_node_provider_credential_resolution.py（implementation）+ fixture
  execution_with_snapshot_factory（conftest work item）。
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from asgiref.sync import sync_to_async
from structlog.testing import capture_logs

from common.encryption import encrypt_value


# ============================================================================
# Fixture：预置单条 Anthropic 系统级凭证（系统层兜底解析命中）
# ============================================================================


@pytest.fixture
def sys_anthropic_cred(db) -> Any:
    """系统级 anthropic 凭证——`aresolve_or_error` 系统层兜底查命中。"""
    from system.models import ProviderCredential

    enc = encrypt_value(
        json.dumps({"api_key": "sk-ant-test", "base_url": "https://api.anthropic.com"})
    )
    return ProviderCredential.objects.create(
        provider_type="anthropic",
        name="default",
        scope="system",
        scope_id=None,
        encrypted_config=enc,
        is_active=True,
    )


# ============================================================================
# Test A：start_execution 为多 AI 节点写入 node_snapshots
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_start_execution_writes_node_snapshots_for_ai_nodes(
    sys_anthropic_cred: Any,
    project: Any,
) -> None:
    """A + F：3 AI 节点 + 1 Script 节点 → snapshot 只写 AI 节点 + 字段为 str。"""
    from workflows.engine.scheduler import WorkflowEngine
    from workflows.models import Workflow, WorkflowExecution
    from workflows.models.node import WorkflowNode as Node

    workflow = await sync_to_async(Workflow.objects.create)(
        name="snapshot-wf-a",
        project=project,
        trigger_type="manual",
    )

    # 3 AI 节点（白名单内）
    await sync_to_async(Node.objects.create)(
        workflow=workflow,
        node_type="ai_prompt",
        name="prompt-n1",
        config={"model": "claude-3-5-sonnet-20241022", "user_prompt": "hi"},
    )
    await sync_to_async(Node.objects.create)(
        workflow=workflow,
        node_type="ai_variable_extractor",
        name="extractor-n2",
        config={"model": "claude-3-5-sonnet-20241022"},
    )
    await sync_to_async(Node.objects.create)(
        workflow=workflow,
        node_type="ai_plan_generation",
        name="plangen-n3",
        config={"model": "claude-3-5-sonnet-20241022"},
    )
    # 非 AI 节点（应被白名单过滤）
    await sync_to_async(Node.objects.create)(
        workflow=workflow,
        node_type="script",
        name="script-n4",
        config={"script": "print(1)"},
    )

    engine = WorkflowEngine()

    # 直接调 helper（避免 _run_execution 异步调度复杂度；helper 是 pure）
    from workflows.engine.dag import DAG

    dag = await DAG.afrom_workflow(workflow)

    execution = await WorkflowExecution.objects.acreate(
        workflow=workflow,
        project=project,
        trigger_type="manual",
    )
    # 预填充 workflow/project 缓存（avoid async FK lazy-load）
    execution.workflow = workflow
    execution.project = project

    snapshots = await engine._snapshot_ai_node_providers(dag, execution)

    # 3 AI 节点命中；script 节点不在 snapshots
    assert len(snapshots) == 3, f"期望 3 AI 节点，实际 {len(snapshots)}：{list(snapshots)}"

    # 每条 snapshot 字段契约（F：str 类型）
    for node_id, snap in snapshots.items():
        assert isinstance(snap["provider_type"], str), (
            f"provider_type 必须是 str（JSON 序列化安全）实际 {type(snap['provider_type'])}"
        )
        assert snap["provider_type"] == "anthropic"
        assert snap["model"] == "claude-3-5-sonnet-20241022"
        assert snap["source"] == "system"  # 系统级兜底
        assert snap["credential_id"] == str(sys_anthropic_cred.id)


# ============================================================================
# Test B：凭证解析失败的 AI 节点不写入 snapshot
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_snapshot_skips_node_with_missing_credential(
    db,
    project: Any,
) -> None:
    """B：aresolve_or_error 返 ProviderMissingError 的节点不写入 snapshot。"""
    # 故意不创建任何 ProviderCredential：所有层都 miss
    from workflows.engine.dag import DAG
    from workflows.engine.scheduler import WorkflowEngine
    from workflows.models import Workflow, WorkflowExecution
    from workflows.models.node import WorkflowNode as Node

    workflow = await sync_to_async(Workflow.objects.create)(
        name="snapshot-wf-miss",
        project=project,
        trigger_type="manual",
    )
    await sync_to_async(Node.objects.create)(
        workflow=workflow,
        node_type="ai_prompt",
        name="no-cred",
        config={"model": "claude-3-5-sonnet-20241022"},
    )

    engine = WorkflowEngine()
    dag = await DAG.afrom_workflow(workflow)
    execution = await WorkflowExecution.objects.acreate(
        workflow=workflow,
        project=project,
        trigger_type="manual",
    )
    execution.workflow = workflow
    execution.project = project

    snapshots = await engine._snapshot_ai_node_providers(dag, execution)

    assert snapshots == {}, (
        f"凭证 miss 时不应写入 snapshot；实际 {snapshots}"
    )


# ============================================================================
# Test C：非 AI 节点被白名单过滤
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_snapshot_filters_non_ai_nodes(
    sys_anthropic_cred: Any,
    project: Any,
) -> None:
    """C：script / data_transform / http 等非 AI 节点不进入 snapshot。"""
    from workflows.engine.dag import DAG
    from workflows.engine.scheduler import WorkflowEngine
    from workflows.models import Workflow, WorkflowExecution
    from workflows.models.node import WorkflowNode as Node

    workflow = await sync_to_async(Workflow.objects.create)(
        name="snapshot-wf-c",
        project=project,
        trigger_type="manual",
    )
    for nt in ("script", "http_request", "data_transform"):
        await sync_to_async(Node.objects.create)(
            workflow=workflow,
            node_type=nt,
            name=f"non-ai-{nt}",
            config={},
        )

    engine = WorkflowEngine()
    dag = await DAG.afrom_workflow(workflow)
    execution = await WorkflowExecution.objects.acreate(
        workflow=workflow,
        project=project,
        trigger_type="manual",
    )
    execution.workflow = workflow
    execution.project = project

    snapshots = await engine._snapshot_ai_node_providers(dag, execution)

    assert snapshots == {}, (
        f"非 AI 节点不应进入 snapshot；实际 {snapshots}"
    )


# ============================================================================
# Test D：AI 节点 runner 读 snapshot 命中时不再调 aresolve_or_error
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_prefers_snapshot_over_runtime_resolve(
    execution_with_snapshot_factory: Any,
    make_minimal_context: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D：ExecutionContext.node_snapshots 命中时 base_agent 读快照，不调 aresolve。"""
    from workflows.nodes.ai.base_agent import AIAgentBaseNode

    # 构造一个带 snapshot 的 WorkflowExecution
    node_id = "node-cached-1"
    # credential_id=None：snapshot 命中路径不触发凭证 DB 读（Test D 专注
    # 断言 aresolve_or_error 不被调用）；Test F 另外覆盖 credential_id 往返
    snap = {
        "provider_type": "anthropic",
        "model": "claude-3-5-sonnet-20241022",
        "source": "project",
        "credential_id": None,
    }
    we = await sync_to_async(execution_with_snapshot_factory)(
        node_snapshots={node_id: snap},
    )

    # 构造 ExecutionContext
    ctx = make_minimal_context(
        node_config={"user_prompt": "q", "model": ""},
        node_id=node_id,
        workflow_execution=we,
    )
    # 手动把 snapshot dict 注入 dataclass 字段（contract 设计）
    ctx.node_snapshots = {node_id: snap}

    # spy aresolve_or_error：若被调则 fail
    call_count = {"n": 0}

    async def _spy_resolve(*args: Any, **kwargs: Any) -> Any:
        call_count["n"] += 1
        raise AssertionError("snapshot 命中时不应调 aresolve_or_error")

    monkeypatch.setattr(
        "services.provider_config.ProviderConfigService.aresolve_or_error",
        _spy_resolve,
    )

    # 直接调 _resolve_api_key_and_model（base_agent 的解析入口），
    # 快照命中路径应跳过 aresolve 直接构造 ResolvedProviderConfig
    class _FakeAgent(AIAgentBaseNode):
        node_type = "ai_prompt"
        display_name = "x"

        def get_system_prompt(self, context: Any) -> str:
            return ""

        def get_user_prompt(self, context: Any) -> str:
            return "q"

    agent = _FakeAgent()
    resolved, model = await agent._resolve_from_snapshot_or_runtime(
        context=ctx,
        project=None,
        config_model="",
        use_custom_api=False,
        api_base_url="",
        api_key="",
        provider_type="",
        provider_credential_id="",
    )

    assert call_count["n"] == 0, "snapshot 命中时禁止调 aresolve_or_error"
    assert resolved.source == "project"
    assert model == "claude-3-5-sonnet-20241022"


# ============================================================================
# Test E：snapshot miss 时 runner fallback + warning log
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_runner_logs_warning_and_falls_back_on_snapshot_miss(
    sys_anthropic_cred: Any,
    execution_with_snapshot_factory: Any,
    make_minimal_context: Any,
    project: Any,
) -> None:
    """E：context.node_snapshots 不含当前 node_id → structlog warning + runtime aresolve。"""
    from workflows.nodes.ai.base_agent import AIAgentBaseNode

    # 构造 snapshot 仅含其他节点（当前 node_id miss）
    we = await sync_to_async(execution_with_snapshot_factory)(
        node_snapshots={"some-other-node": {
            "provider_type": "anthropic",
            "model": "x",
            "source": "system",
            "credential_id": None,
        }},
        project=project,
    )
    ctx = make_minimal_context(
        node_config={"user_prompt": "q", "model": "claude-3-5-sonnet-20241022"},
        node_id="node-miss",
        workflow_execution=we,
    )
    ctx.node_snapshots = {"some-other-node": {
        "provider_type": "anthropic",
        "model": "x",
        "source": "system",
        "credential_id": None,
    }}

    class _FakeAgent(AIAgentBaseNode):
        node_type = "ai_prompt"
        display_name = "x"

        def get_system_prompt(self, context: Any) -> str:
            return ""

        def get_user_prompt(self, context: Any) -> str:
            return "q"

    agent = _FakeAgent()

    with capture_logs() as logs:
        resolved, model = await agent._resolve_from_snapshot_or_runtime(
            context=ctx,
            project=project,
            config_model="claude-3-5-sonnet-20241022",
            use_custom_api=False,
            api_base_url="",
            api_key="",
            provider_type="",
            provider_credential_id="",
        )

    # warning 事件已发射（结构化 key='value'，非 f-string）
    miss_events = [
        log for log in logs
        if log.get("event") == "snapshot.miss_fallback_to_runtime_resolve"
    ]
    assert len(miss_events) >= 1, (
        f"snapshot miss 应产生 structlog warning；实际 logs={logs}"
    )
    # fallback 成功：resolve 走系统级凭证命中
    assert resolved.source == "system"
    assert model == "claude-3-5-sonnet-20241022"


# ============================================================================
# Test F：snapshot JSON 序列化往返（context JSONField 持久化兼容性）
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_snapshot_json_round_trip_via_context_field(
    sys_anthropic_cred: Any,
    project: Any,
) -> None:
    """F（补强）：_snapshot_ai_node_providers 的返回值 JSON 序列化后往返不丢精度。"""
    from workflows.engine.dag import DAG
    from workflows.engine.scheduler import WorkflowEngine
    from workflows.models import Workflow, WorkflowExecution
    from workflows.models.node import WorkflowNode as Node

    workflow = await sync_to_async(Workflow.objects.create)(
        name="snapshot-wf-f",
        project=project,
        trigger_type="manual",
    )
    await sync_to_async(Node.objects.create)(
        workflow=workflow,
        node_type="ai_prompt",
        name="p1",
        config={"model": "claude-3-5-sonnet-20241022"},
    )

    engine = WorkflowEngine()
    dag = await DAG.afrom_workflow(workflow)
    execution = await WorkflowExecution.objects.acreate(
        workflow=workflow,
        project=project,
        trigger_type="manual",
    )
    execution.workflow = workflow
    execution.project = project

    snapshots = await engine._snapshot_ai_node_providers(dag, execution)

    # 写入 context JSONField 并持久化
    execution.context = {**(execution.context or {}), "node_snapshots": snapshots}
    await sync_to_async(execution.save)(update_fields=["context"])

    # reload 并断言完整性
    refreshed = await WorkflowExecution.objects.aget(pk=execution.pk)
    assert "node_snapshots" in refreshed.context
    assert refreshed.context["node_snapshots"] == snapshots
    # JSON 序列化安全：所有值都是 str / None
    for snap in refreshed.context["node_snapshots"].values():
        assert isinstance(snap["provider_type"], str)
        assert isinstance(snap["model"], str)
        assert isinstance(snap["source"], str)
        assert snap["credential_id"] is None or isinstance(snap["credential_id"], str)
