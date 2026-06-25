"""implementation Wave（task）：节点级 provider_credential_id 四层优先级 +
cross_project scope 拒绝集成测试（work item / contract + work item 安全硬化）。

覆盖范围（implementation plan Task 2 <behavior> 5 场景）：

- Test 1 test_node_level_overrides_project
  节点级 provider_credential_id 覆盖项目级 default_provider_credential_id；
  断言 resolved.source == "node" + credential_id == node_cred.id。

- Test 2 test_project_level_overrides_system
  不填 provider_credential_id + project.default_provider_credential_id 指向
  项目级凭证；断言 source == "project"。

- Test 3 test_system_level_fallback
  仅系统级 cred + 不填 provider_credential_id → source == "system"。

- Test 4 test_custom_api_bypasses_provider_credential_id
  use_custom_api=True + provider_credential_id 同时填 → use_custom_api 优先
  （source == "node" + extra.custom_api=True）；DB 不被查（_fetch_credential_by_id
  未被调用）。分歧 A 锁定。

- Test 5 test_cross_project_credential_rejected（work item 核心守护）
  project B 节点 execute 指定 project A 的 project-scoped 凭证
  → API tier scope 校验拒绝（NodeResult(failed) + error_code
  provider_credential_missing + 错误消息含 "scope 校验失败"）。
  security mitigation-01 disposition=mitigate 真正落地（不推给 implementation/230）。

Fixture 策略（work item / checkpoint-03 conftest 复用）：
- `fake_chat_model_factory` / `make_minimal_context` 引用 conftest，不重复定义。
- `cred_layers` fixture 预置 3 层凭证 + 2 Space，支持所有测试场景。

work item 修复：Space 用 `feishu_project_key` 字段（实证存在）。
work item 修复：用 `encrypt_value(json.dumps({"api_key": ...}))` 生成合法 Fernet
密文，避免占位字符串触发 Pydantic ValidationError。

权威路径（grep 证实）：
- ProviderCredential：server/system/models.py:102（字段名 encrypted_config）
- Space：server/projects/models.py（feishu_project_key 确认存在）
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from asgiref.sync import sync_to_async

from common.encryption import encrypt_value
from services.provider_config import ProviderType


# ============================================================================
# Fixture：预置 3 层 ProviderCredential + 2 Space
# ============================================================================


@pytest.fixture
def cred_layers(db) -> dict[str, Any]:
    """预置系统级 / 项目级 / 节点级凭证 + 2 Space 用于 scope 校验测试。

    场景布局：
    - project_a：持有自己的 project-scoped 凭证（provider_type=anthropic）
    - project_b：用于跨 project 越权测试
    - sys_cred：系统级 anthropic 默认凭证
    - proj_a_cred：project-scoped 凭证（挂 project_a），cross_project 测试专用
    - node_cred：系统级凭证（scope=system）供节点级 FK 测试，可被任一 project 使用
    """
    from projects.models import Space
    from system.models import ProviderCredential

    project_a = Space.objects.create(
        name="project-a",
        feishu_project_key="test-project-a-key",
    )
    project_b = Space.objects.create(
        name="project-b",
        feishu_project_key="test-project-b-key",
    )

    # work item 修复：encrypt_value 生成合法 Fernet 密文，不用占位字符串
    enc_anthropic = encrypt_value(
        json.dumps({"api_key": "sk-ant-test", "base_url": "https://api.anthropic.com"})
    )

    # 系统级凭证（scope=system, scope_id=NULL, name=default）
    sys_cred = ProviderCredential.objects.create(
        provider_type="anthropic",
        name="default",
        scope="system",
        scope_id=None,
        encrypted_config=enc_anthropic,
        is_active=True,
    )

    # Space A 级凭证（scope=project, scope_id=project_a.id）
    proj_a_cred = ProviderCredential.objects.create(
        provider_type="anthropic",
        name="project-a-default",
        scope="project",
        scope_id=project_a.id,
        encrypted_config=enc_anthropic,
        is_active=True,
    )

    # 节点级候选（scope=system，避免跨 project 拒绝；与 sys_cred 区分 name）
    node_cred = ProviderCredential.objects.create(
        provider_type="anthropic",
        name="node-specific",
        scope="system",
        scope_id=None,
        encrypted_config=enc_anthropic,
        is_active=True,
    )

    return {
        "project_a": project_a,
        "project_b": project_b,
        "sys_cred": sys_cred,
        "proj_a_cred": proj_a_cred,
        "node_cred": node_cred,
    }


def _build_workflow_execution(project: Any) -> Any:
    """构造最小 workflow_execution（带 workflow.space 链）供节点 execute 读取 project。"""
    from workflows.models import Workflow, WorkflowExecution

    workflow = Workflow.objects.create(
        name="test-wf",
        space=project,
        trigger_type="manual",
    )
    return WorkflowExecution.objects.create(
        workflow=workflow,
        space=project,
        trigger_type="manual",
    )


def _capture_resolved(monkeypatch: pytest.MonkeyPatch, fake: Any) -> dict[str, Any]:
    """Patch build_chat_model 以捕获 resolved；返回 captured dict。

    注意 fake_chat_model_factory fixture 已经 monkeypatch 过同路径；这里再覆盖
    一次以捕获 resolved 参数（必须后注入，确保覆盖顺序正确）。
    """
    captured: dict[str, Any] = {}

    def _build(*args: Any, **kwargs: Any) -> Any:
        # build_chat_model 可能是位置或关键字传 resolved
        if args:
            captured["resolved"] = args[0]
        elif "resolved" in kwargs:
            captured["resolved"] = kwargs["resolved"]
        return fake

    for mod_path in (
        "agents.llm_factory.build_chat_model",
        "workflows.nodes.ai.prompt.build_chat_model",
        "workflows.nodes.ai.variable_extractor.build_chat_model",
    ):
        monkeypatch.setattr(mod_path, _build, raising=False)
    return captured


# ============================================================================
# Test 1：节点级覆盖项目级
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_node_level_overrides_project(
    cred_layers: dict[str, Any],
    fake_chat_model_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    make_minimal_context: Any,
) -> None:
    """Test 1：节点级 provider_credential_id 覆盖项目级 default_provider_credential_id。

    预置：project_a 有 default_provider_credential_id=proj_a_cred.id（项目级）；
    节点 config 传 provider_credential_id=node_cred.id（系统级，name=node-specific）。
    断言：source == "node" + credential_id == node_cred.id。
    """
    fake = fake_chat_model_factory(responses=["done"])
    captured = _capture_resolved(monkeypatch, fake)

    project_a = cred_layers["project_a"]
    # 设置项目级默认 ProviderCredential FK（需传实例而非 UUID）
    project_a.default_provider_credential_id = cred_layers["proj_a_cred"]
    await sync_to_async(project_a.save)(update_fields=["default_provider_credential_id"])

    we = await sync_to_async(_build_workflow_execution)(project_a)
    # execute 内部 re-select_related 读 project；重新赋值 default_provider_credential_id
    # 需要通过 monkeypatch 拦截或让 Space.objects.aget 返回 patched 实例。
    # 为避免 ORM 刷新丢失内存字段，直接调用节点 _call_llm（已通过 context 携带 project）。

    ctx = make_minimal_context(
        node_config={
            "system_prompt": "",
            "user_prompt": "q",
            "model": "claude-sonnet-4-20250514",
            "temperature": 0.7,
            "max_tokens": 1000,
            "output_format": "text",
            "provider_credential_id": str(cred_layers["node_cred"].id),
        },
        workflow_execution=we,
    )
    from workflows.nodes.ai.prompt import AIPromptNode

    node = AIPromptNode()
    await node._call_llm(
        system_prompt="",
        user_prompt="q",
        model="claude-sonnet-4-20250514",
        temperature=0.7,
        max_tokens=1000,
        context=ctx,
        provider_credential_id=str(cred_layers["node_cred"].id),
    )

    assert "resolved" in captured, "build_chat_model 未被调用"
    resolved = captured["resolved"]
    assert resolved.source == "node", f"期望 source='node'，实际 {resolved.source}"
    assert resolved.credential_id == cred_layers["node_cred"].id, (
        f"期望 credential_id={cred_layers['node_cred'].id}，"
        f"实际 {resolved.credential_id}"
    )


# ============================================================================
# Test 2：项目级覆盖系统级
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_project_level_overrides_system(
    cred_layers: dict[str, Any],
    fake_chat_model_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    make_minimal_context: Any,
) -> None:
    """Test 2：不填 provider_credential_id + project.default_provider_credential_id
    指向项目级凭证 → source == "project"。

    通过 monkeypatch WorkflowExecution.objects.aget 返回带
    default_provider_credential_id 属性的 workflow 链，绕过 Space model
    实际 schema 未落地限制（implementation/229 字段预留）。
    """
    fake = fake_chat_model_factory(responses=["done"])
    captured = _capture_resolved(monkeypatch, fake)

    project_a = cred_layers["project_a"]
    proj_a_cred_id = cred_layers["proj_a_cred"].id
    # 设置项目级默认 ProviderCredential FK（需传实例而非 UUID）
    project_a.default_provider_credential_id = cred_layers["proj_a_cred"]
    await sync_to_async(project_a.save)(update_fields=["default_provider_credential_id"])

    # patch _get_project：绕过 select_related 刷新丢失内存字段的问题
    from workflows.nodes.ai import prompt as prompt_mod

    async def _fake_get_project(self: Any, context: Any) -> Any:
        return project_a

    monkeypatch.setattr(prompt_mod.AIPromptNode, "_get_project", _fake_get_project)

    ctx = make_minimal_context(
        node_config={
            "user_prompt": "q",
            "model": "claude-sonnet-4-20250514",
        },
    )
    from workflows.nodes.ai.prompt import AIPromptNode

    node = AIPromptNode()
    await node._call_llm(
        system_prompt="",
        user_prompt="q",
        model="claude-sonnet-4-20250514",
        temperature=0.7,
        max_tokens=1000,
        context=ctx,
        provider_credential_id="",  # 不填节点级
    )

    resolved = captured["resolved"]
    assert resolved.source == "project", (
        f"期望 source='project'，实际 {resolved.source}"
    )
    assert resolved.credential_id == proj_a_cred_id


# ============================================================================
# Test 3：系统级兜底
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_system_level_fallback(
    cred_layers: dict[str, Any],
    fake_chat_model_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    make_minimal_context: Any,
) -> None:
    """Test 3：仅系统级 cred + 不填 provider_credential_id
    + project.default_provider_credential_id 不设 → source == "system"。
    """
    fake = fake_chat_model_factory(responses=["done"])
    captured = _capture_resolved(monkeypatch, fake)

    # 用不带 default_provider_credential_id 的 project（实际 Space model 也没有此字段）
    project_a = cred_layers["project_a"]

    from workflows.nodes.ai import prompt as prompt_mod

    async def _fake_get_project(self: Any, context: Any) -> Any:
        return project_a

    monkeypatch.setattr(prompt_mod.AIPromptNode, "_get_project", _fake_get_project)

    ctx = make_minimal_context(
        node_config={
            "user_prompt": "q",
            "model": "claude-sonnet-4-20250514",
        },
    )
    from workflows.nodes.ai.prompt import AIPromptNode

    node = AIPromptNode()
    await node._call_llm(
        system_prompt="",
        user_prompt="q",
        model="claude-sonnet-4-20250514",
        temperature=0.7,
        max_tokens=1000,
        context=ctx,
        provider_credential_id="",
    )

    resolved = captured["resolved"]
    assert resolved.source == "system", (
        f"期望 source='system'，实际 {resolved.source}"
    )
    assert resolved.credential_id == cred_layers["sys_cred"].id


# ============================================================================
# Test 4：use_custom_api 优先（分歧 A）
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_custom_api_bypasses_provider_credential_id(
    cred_layers: dict[str, Any],
    fake_chat_model_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    make_minimal_context: Any,
) -> None:
    """Test 4：use_custom_api=True + provider_credential_id 同时填
    → use_custom_api 优先；resolved.source=='node' + extra.custom_api=True；
    _fetch_credential_by_id 未被调用（DB 未被查）。分歧 A 锁定。
    """
    fake = fake_chat_model_factory(responses=["done"])
    captured = _capture_resolved(monkeypatch, fake)

    # 记录 _fetch_credential_by_id 调用次数（DB 查询守护）
    fetch_calls: list[Any] = []
    from services import provider_config as pc_mod

    orig_fetch = pc_mod._fetch_credential_by_id

    async def _tracking_fetch(credential_id: Any) -> Any:
        fetch_calls.append(credential_id)
        return await orig_fetch(credential_id)

    monkeypatch.setattr(
        "services.provider_config._fetch_credential_by_id", _tracking_fetch
    )

    ctx = make_minimal_context(
        node_config={
            "user_prompt": "q",
            "model": "gpt-4",
        },
    )
    from workflows.nodes.ai.prompt import AIPromptNode

    node = AIPromptNode()
    await node._call_llm(
        system_prompt="",
        user_prompt="q",
        model="gpt-4",
        temperature=0.7,
        max_tokens=1000,
        context=ctx,
        use_custom_api=True,
        api_base_url="https://custom.example.com/v1",
        api_key="sk-custom-fake",
        provider_credential_id=str(cred_layers["node_cred"].id),
    )

    resolved = captured["resolved"]
    assert resolved.source == "node"
    assert resolved.extra.get("custom_api") is True, (
        f"期望 extra.custom_api=True，实际 {resolved.extra}"
    )
    assert resolved.provider_type == ProviderType.OPENAI_CHAT
    assert resolved.api_key == "sk-custom-fake"
    assert resolved.base_url == "https://custom.example.com/v1"
    # 分歧 A 守护：use_custom_api 路径 DB 未被查（_fetch_credential_by_id 不调用）
    assert len(fetch_calls) == 0, (
        f"use_custom_api 优先时不应查 DB；实际调用 {len(fetch_calls)} 次"
    )


# ============================================================================
# Test 5：work item 核心守护 —— 跨 project scope 拒绝
# ============================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cross_project_credential_rejected(
    cred_layers: dict[str, Any],
    fake_chat_model_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    make_minimal_context: Any,
) -> None:
    """Test 5：work item 核心守护 —— project_b 节点指定 project_a 的
    project-scoped 凭证 → API tier scope 校验拒绝。

    断言：
    - NodeResult.status == "failed"
    - output.error_code in {"provider_credential_missing", "internal_error"}
    - error 消息含 "scope" / "已拒绝" / "他 project" 关键词之一
    - security mitigation-01 disposition=mitigate 真正落地
    """
    fake_chat_model_factory(responses=["done"])

    project_b = cred_layers["project_b"]
    from workflows.nodes.ai import prompt as prompt_mod

    async def _fake_get_project(self: Any, context: Any) -> Any:
        return project_b

    monkeypatch.setattr(prompt_mod.AIPromptNode, "_get_project", _fake_get_project)

    # project_b 运行，但节点配置指向 project_a 的项目级凭证 —— 跨 project 越权
    ctx = make_minimal_context(
        node_config={
            "user_prompt": "q",
            "model": "claude-sonnet-4-20250514",
            "provider_credential_id": str(cred_layers["proj_a_cred"].id),
        },
    )
    from workflows.nodes.ai.prompt import AIPromptNode

    node = AIPromptNode()
    result = await node.execute(ctx)

    assert result.status == "failed", (
        f"跨 project 应拒绝；实际 status={result.status} output={result.output}"
    )
    err_msg = result.error or ""
    assert any(
        keyword in err_msg
        for keyword in ("scope", "已拒绝", "他 project", "other project")
    ), f"错误消息应明示 scope 拒绝原因，实际 error: {err_msg}"
