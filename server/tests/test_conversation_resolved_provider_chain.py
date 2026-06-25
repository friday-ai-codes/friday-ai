"""implementation Task 1 — contract API 契约测试。

覆盖 contract GET /api/chat/conversations/{id}/ 响应扩展契约：
    - Behavior E：响应包含 resolved_provider 对象 {provider_type, model, source, chain: [...]}
    - Behavior E1：chain 数组恒 4 层，顺序 node → conversation → project → system
    - Behavior E2：winning source 与 chain[i].active=True 层一致
    - Behavior E3：全链路 miss → resolved_provider=null（前端优雅降级）
    - Behavior F：workflow node resolved-provider 端点返回同 shape
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from chat.models import Conversation


def _client() -> APIClient:
    return APIClient()


def _conv_url(conv_id: str) -> str:
    return f"/api/chat/conversations/{conv_id}/"


def _node_url(wf_id: str, node_id: str) -> str:
    return f"/api/workflows/{wf_id}/nodes/{node_id}/resolved-provider/"


# ============================================================================
# Behavior E — Conversation 详情响应含 resolved_provider
# ============================================================================


@pytest.mark.django_db
def test_conversation_detail_includes_resolved_provider_field(
    project_a,
    project_a_anthropic_credential,
) -> None:
    """E：project 挂默认凭证 → 详情响应 resolved_provider.source=project + chain 4 层。"""
    project_a.default_provider_credential_id_id = project_a_anthropic_credential.id
    project_a.save(update_fields=["default_provider_credential_id"])

    conv = Conversation.objects.create(space=project_a, title="resolved_provider 契约")

    resp = _client().get(_conv_url(str(conv.id)))

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert "resolved_provider" in body, body
    rp = body["resolved_provider"]
    assert rp["provider_type"] == "anthropic"
    assert rp["source"] == "project"
    assert isinstance(rp["chain"], list)
    assert len(rp["chain"]) == 4
    assert [e["layer"] for e in rp["chain"]] == [
        "node",
        "conversation",
        "project",
        "system",
    ]


# ============================================================================
# Behavior E2 — winning source 与 chain[i].active 一致
# ============================================================================


@pytest.mark.django_db
def test_resolved_provider_winning_source_matches_chain_active(
    project_a,
    project_a_anthropic_credential,
) -> None:
    """E2：winning source="conversation" 时，chain 数组中仅该层 active=True。"""
    conv = Conversation.objects.create(space=project_a, title="winning=conversation")
    conv.provider_credential_id_id = project_a_anthropic_credential.id
    conv.save(update_fields=["provider_credential_id"])

    resp = _client().get(_conv_url(str(conv.id)))
    assert resp.status_code == 200, resp.content
    rp = resp.json()["resolved_provider"]
    assert rp["source"] == "conversation"

    active_layers = [e["layer"] for e in rp["chain"] if e["active"] is True]
    assert active_layers == ["conversation"]

    non_active_layers = [e["layer"] for e in rp["chain"] if e["active"] is False]
    assert sorted(non_active_layers) == sorted(["node", "project", "system"])


# ============================================================================
# Behavior E3 — 全链路 miss → resolved_provider = null
# ============================================================================


@pytest.mark.django_db
def test_resolved_provider_null_when_no_credentials_anywhere(
    project_a,
) -> None:
    """E3：conversation + project + system 均无凭证 → resolved_provider=null。"""
    conv = Conversation.objects.create(space=project_a, title="无凭证")

    resp = _client().get(_conv_url(str(conv.id)))
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body.get("resolved_provider") is None


# ============================================================================
# Behavior E4 — chain entry 字段契约
# ============================================================================


@pytest.mark.django_db
def test_chain_entry_has_all_contract_fields(
    project_a,
    project_a_anthropic_credential,
) -> None:
    """E4：chain 每层含 {layer, provider_type, model, credential_id, active} 五字段。"""
    project_a.default_provider_credential_id_id = project_a_anthropic_credential.id
    project_a.save(update_fields=["default_provider_credential_id"])

    conv = Conversation.objects.create(space=project_a, title="字段契约")

    resp = _client().get(_conv_url(str(conv.id)))
    assert resp.status_code == 200
    rp = resp.json()["resolved_provider"]

    for entry in rp["chain"]:
        assert "layer" in entry
        assert "provider_type" in entry
        assert "model" in entry
        assert "credential_id" in entry
        assert "active" in entry
        assert isinstance(entry["active"], bool)


# ============================================================================
# Behavior F — workflow node resolved-provider 端点
# ============================================================================


@pytest.mark.django_db
def test_workflow_node_resolved_provider_endpoint(
    project_a,
    project_a_anthropic_credential,
    project_a_admin_user,
) -> None:
    """F：GET /api/workflows/{wf_id}/nodes/{node_id}/resolved-provider/ 返回同 shape。"""
    from workflows.models import Workflow, WorkflowNode

    # 挂 project 默认凭证
    project_a.default_provider_credential_id_id = project_a_anthropic_credential.id
    project_a.save(update_fields=["default_provider_credential_id"])

    workflow = Workflow.objects.create(
        name="contract test workflow",
        space=project_a,
        created_by=project_a_admin_user,
    )
    node = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="ai_prompt",
        name="AI 节点",
        config={},
    )

    client = APIClient()
    client.force_authenticate(user=project_a_admin_user)
    resp = client.get(_node_url(str(workflow.id), str(node.id)))

    assert resp.status_code == 200, resp.content
    body = resp.json()
    # 按 plan：返回 resolved_provider 对象（或直接 resolved_provider shape）
    rp = body.get("resolved_provider") or body
    assert "source" in rp
    assert "chain" in rp
    assert len(rp["chain"]) == 4
    assert rp["source"] == "project"


# ============================================================================
# Behavior F2 — workflow 不存在的 node → 404
# ============================================================================


@pytest.mark.django_db
def test_workflow_node_resolved_provider_404(
    project_a,
    project_a_admin_user,
) -> None:
    """F2：workflow_id + node_id 不存在 → 404。"""
    from workflows.models import Workflow

    workflow = Workflow.objects.create(
        name="Test WF",
        space=project_a,
        created_by=project_a_admin_user,
    )

    client = APIClient()
    client.force_authenticate(user=project_a_admin_user)
    resp = client.get(_node_url(str(workflow.id), str(uuid4())))
    assert resp.status_code == 404
