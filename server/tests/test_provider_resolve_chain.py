"""implementation Task 1 — contract ProviderConfigService.aresolve_with_chain 单元测试。

覆盖 contract 四层 Provider 解析链契约：
    - Behavior A：node 层凭证存在 + 其他层也有 → chain[0].active=True，其余 False
    - Behavior B：node 空 + conversation 凭证 + project/system 也有 → chain[1].active=True
    - Behavior C：node 空 + conversation 空 + project 凭证 → chain[2].active=True
    - Behavior D：全链路 miss → 返回 ProviderMissingError（非 ResolvedProviderChain）
    - Behavior E：chain 数组恒为 4 层（node/conversation/project/system），顺序固定

Fixture 依赖（conftest.py）：
    - project_a / project_b / system_default_anthropic_credential / project_a_anthropic_credential
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from chat.models import Conversation
from services.provider_config import (
    ProviderConfigService,
    ProviderMissingError,
    ResolutionChainEntry,
    ResolvedProviderChain,
    ResolvedProviderConfig,
)


def _chain_by_layer(chain: list[ResolutionChainEntry]) -> dict[str, ResolutionChainEntry]:
    """辅助：按 layer 取 chain entry（4 层都存在，顺序固定）。"""
    return {e.layer: e for e in chain}


# ============================================================================
# Behavior A：node 层凭证存在 + project / system 也有 → chain[0].active=True
# ============================================================================


@pytest.mark.django_db(transaction=True)
async def test_node_level_wins_over_lower_layers(
    project_a,
    project_a_anthropic_credential,
    system_default_anthropic_credential,
) -> None:
    """A：node_config 带 provider_credential_id → winning=node，其他层 active=False。"""
    # project 也挂默认凭证，验证 node 仍赢
    project_a.default_provider_credential_id_id = project_a_anthropic_credential.id
    await project_a.asave(update_fields=["default_provider_credential_id"])

    node_config = {"provider_credential_id": str(project_a_anthropic_credential.id)}

    result = await ProviderConfigService.aresolve_with_chain(
        node_config=node_config,
        conversation=None,
        project=project_a,
    )

    assert isinstance(result, ResolvedProviderChain)
    assert result.winning.source == "node"
    assert len(result.chain) == 4
    by = _chain_by_layer(result.chain)
    assert by["node"].active is True
    assert by["conversation"].active is False
    assert by["project"].active is False
    assert by["system"].active is False


# ============================================================================
# Behavior B：node 空 + conversation 凭证 + project/system 也有 → winning=conversation
# ============================================================================


@pytest.mark.django_db(transaction=True)
async def test_conversation_level_wins_when_node_empty(
    project_a,
    project_a_anthropic_credential,
    system_default_anthropic_credential,
) -> None:
    """B：conversation.provider_credential_id 有值 → winning=conversation。"""
    conv = await Conversation.objects.acreate(
        space=project_a,
        title="conversation pinned",
    )
    conv.provider_credential_id_id = project_a_anthropic_credential.id
    await conv.asave(update_fields=["provider_credential_id"])

    # 同时 project 也挂默认凭证，验证 conversation 层仍赢
    project_a.default_provider_credential_id_id = project_a_anthropic_credential.id
    await project_a.asave(update_fields=["default_provider_credential_id"])

    # 重新拉取以预取 FK _id 列（async 上下文）
    conv_refetched = await Conversation.objects.select_related("space").aget(id=conv.id)

    result = await ProviderConfigService.aresolve_with_chain(
        node_config=None,
        conversation=conv_refetched,
        project=conv_refetched.space,
    )

    assert isinstance(result, ResolvedProviderChain)
    assert result.winning.source == "conversation"
    by = _chain_by_layer(result.chain)
    assert by["node"].active is False
    assert by["conversation"].active is True
    assert by["project"].active is False
    assert by["system"].active is False
    # chain entry 含 provider_type（从凭证 FK 读出）
    assert by["conversation"].provider_type == "anthropic"


# ============================================================================
# Behavior C：node 空 + conversation 空 + project 凭证 → winning=project
# ============================================================================


@pytest.mark.django_db(transaction=True)
async def test_project_level_wins_when_conversation_empty(
    project_a,
    project_a_anthropic_credential,
) -> None:
    """C：仅 project 挂默认凭证 → winning=project。"""
    project_a.default_provider_credential_id_id = project_a_anthropic_credential.id
    await project_a.asave(update_fields=["default_provider_credential_id"])

    conv = await Conversation.objects.acreate(space=project_a, title="project 层赢")
    conv_refetched = await Conversation.objects.select_related("space").aget(id=conv.id)

    result = await ProviderConfigService.aresolve_with_chain(
        node_config=None,
        conversation=conv_refetched,
        project=conv_refetched.space,
    )

    assert isinstance(result, ResolvedProviderChain)
    assert result.winning.source == "project"
    by = _chain_by_layer(result.chain)
    assert by["node"].active is False
    assert by["conversation"].active is False
    assert by["project"].active is True
    assert by["system"].active is False
    assert by["project"].provider_type == "anthropic"


# ============================================================================
# Behavior D：全链路 miss → 返回 ProviderMissingError
# ============================================================================


@pytest.mark.django_db(transaction=True)
async def test_all_layers_miss_returns_missing_error(
    project_a,
) -> None:
    """D：conversation + project + system 均无凭证 → ProviderMissingError。"""
    conv = await Conversation.objects.acreate(space=project_a, title="全链路无凭证")
    conv_refetched = await Conversation.objects.select_related("space").aget(id=conv.id)

    result = await ProviderConfigService.aresolve_with_chain(
        node_config=None,
        conversation=conv_refetched,
        project=conv_refetched.space,
    )

    assert isinstance(result, ProviderMissingError)
    assert result.code == "provider_credential_missing"


# ============================================================================
# Behavior E：chain 恒为 4 层（顺序固定）
# ============================================================================


@pytest.mark.django_db(transaction=True)
async def test_chain_always_contains_four_layers_in_fixed_order(
    project_a,
    project_a_anthropic_credential,
) -> None:
    """E：ResolvedProviderChain.chain 恒 4 层，顺序 node → conversation → project → system。

    任意 winning path 下 chain 都是 4 层且顺序固定（此处验 node 层 winning 场景）。
    """
    node_config = {"provider_credential_id": str(project_a_anthropic_credential.id)}
    result = await ProviderConfigService.aresolve_with_chain(
        node_config=node_config,
        conversation=None,
        project=None,
    )
    assert isinstance(result, ResolvedProviderChain)
    # 4 层顺序固定
    assert [e.layer for e in result.chain] == ["node", "conversation", "project", "system"]
    # winning 层 active 唯一
    active_layers = [e.layer for e in result.chain if e.active]
    assert active_layers == ["node"]


# ============================================================================
# Behavior F：节点层凭证存在但其他层都没有 → chain 仍 4 层 / 其他层字段为 None
# ============================================================================


@pytest.mark.django_db(transaction=True)
async def test_inactive_credential_at_node_clears_credential_id_in_chain(
    project_a,
    project_a_anthropic_credential,
) -> None:
    """F：node_config 指向已失效凭证 → chain[0].credential_id 被清零（不 active）。

    项目层同时挂相同的 active 凭证作为 fallback → winning=project。
    验证 node 层 chain entry 虽有指向但 provider_type=None / credential_id=None。
    """
    # 先把项目挂成默认（fallback 路径）
    project_a.default_provider_credential_id_id = project_a_anthropic_credential.id
    await project_a.asave(update_fields=["default_provider_credential_id"])

    # 新建一个独立失效凭证供 node_config 指向
    import json as _json
    from uuid import uuid4 as _uuid4

    from common.encryption import encrypt_value
    from system.models import ProviderCredential

    inactive_cred = await ProviderCredential.objects.acreate(
        provider_type="anthropic",
        name=f"inactive-{_uuid4().hex[:6]}",
        scope="project",
        scope_id=project_a.id,
        encrypted_config=encrypt_value(
            _json.dumps({"api_key": "sk-ant-dead", "base_url": "https://api.anthropic.com"})
        ),
        is_active=False,
    )

    node_config = {"provider_credential_id": str(inactive_cred.id)}
    project_refetched = await type(project_a).objects.aget(id=project_a.id)
    result = await ProviderConfigService.aresolve_with_chain(
        node_config=node_config,
        conversation=None,
        project=project_refetched,
    )
    assert isinstance(result, ResolvedProviderChain), result
    # winning 应 fallback 到 project（node 指向失效）
    assert result.winning.source == "project"
    by = _chain_by_layer(result.chain)
    # node 层 credential_id 被清除（因为指向 is_active=False 凭证）
    assert by["node"].credential_id is None
    assert by["node"].active is False
    assert by["project"].active is True
