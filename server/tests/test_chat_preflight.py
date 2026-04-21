"""Phase Plan Task 01 — 对话凭证前置探测端点（ConversationPreflightView）。
覆盖 // 契约：
 GET /api/chat/conversations/{id}/preflight/
 - 凭证全链路缺失 → 400 + code=provider_credential_missing + data.missing_provider
 - project.default_provider_credential_id 有效 → 200 + status=ok
 - conversation.provider_credential_id 有效 → 200 + status=ok + resolved.source="conversation"
 - 凭证 is_active=false → 400 + code=provider_credential_missing
 - conversation 不存在 → 404
 - 未认证（Chat auth permission 放行 anonymous ⇒ 仍 200/400，按 existing ChatAuthPermission 语义）
Fixture 依赖（conftest.py）：
 - project / project_a（ProviderCredential scope_id 目标）
 - system_default_anthropic_credential（系统级凭证）
 - project_a_anthropic_credential（项目 A 的 Anthropic 凭证）
"""
from __future__ import annotations
import json
from uuid import uuid4
import pytest
from rest_framework.test import APIClient
from chat.models import Conversation
def _client -> APIClient:
 """创建未认证的 APIClient（Chat API 默认鉴权关闭）。"""
 return APIClient
def _url(conv_id: str) -> str:
 return f"/api/chat/conversations/{conv_id}/preflight/"
# ============================================================================
# Test A — 全链路缺失：conversation / project / system 均无凭证 → 400 + missing
# ============================================================================
@pytest.mark.django_db
def test_preflight_returns_missing_when_no_credentials_anywhere(
 project_a,
) -> None:
 """Behavior A：conversation + project + system 均无凭证 → 400 + code=provider_credential_missing。"""
 conv = Conversation.objects.create(project=project_a, title="无凭证")
 resp = _client.get(_url(str(conv.id)))
 assert resp.status_code == 400, resp.content
 body = resp.json
 assert body["code"] == "provider_credential_missing"
 assert body["data"]["missing_provider"] == "anthropic"
 assert "recommended_action" in body["data"]
 assert "scope_attempted" in body["data"]
# ============================================================================
# Test B — project.default_provider_credential_id 指向有效凭证 → 200 + ok
# ============================================================================
@pytest.mark.django_db
def test_preflight_ok_when_project_default_credential_resolves(
 project_a,
 project_a_anthropic_credential,
) -> None:
 """Behavior B：project 挂 default_provider_credential_id → preflight 成功。"""
 project_a.default_provider_credential_id_id = project_a_anthropic_credential.id
 project_a.save(update_fields=["default_provider_credential_id"])
 conv = Conversation.objects.create(project=project_a, title="走 project 默认")
 resp = _client.get(_url(str(conv.id)))
 assert resp.status_code == 200, resp.content
 body = resp.json
 assert body["status"] == "ok"
 assert body["resolved"]["source"] == "project"
 assert body["resolved"]["provider_type"] == "anthropic"
# ============================================================================
# Test C — conversation.provider_credential_id 指向有效凭证 → 200 + source=conversation
# ============================================================================
@pytest.mark.django_db
def test_preflight_ok_with_conversation_pinned_credential(
 project_a,
 project_a_anthropic_credential,
) -> None:
 """Behavior C：conversation 自身 pin 了 provider_credential → preflight 返 source=conversation。"""
 conv = Conversation.objects.create(project=project_a, title="对话级 pin")
 conv.provider_credential_id_id = project_a_anthropic_credential.id
 conv.save(update_fields=["provider_credential_id"])
 resp = _client.get(_url(str(conv.id)))
 assert resp.status_code == 200, resp.content
 body = resp.json
 assert body["status"] == "ok"
 assert body["resolved"]["source"] == "conversation"
 assert body["resolved"]["credential_id"] == str(project_a_anthropic_credential.id)
# ============================================================================
# Test D — 指向 is_active=false 的凭证 → 400 missing（aresolve_or_error 跳过不活跃）
# ============================================================================
@pytest.mark.django_db
def test_preflight_missing_when_credential_inactive(
 project_a,
 project_a_anthropic_credential,
) -> None:
 """Behavior D：conversation 指向 is_active=false 凭证 → 走四层 fallback；全链路无凭证 → 400。"""
 project_a_anthropic_credential.is_active = False
 project_a_anthropic_credential.save(update_fields=["is_active"])
 conv = Conversation.objects.create(project=project_a, title="指向不活跃凭证")
 conv.provider_credential_id_id = project_a_anthropic_credential.id
 conv.save(update_fields=["provider_credential_id"])
 resp = _client.get(_url(str(conv.id)))
 assert resp.status_code == 400, resp.content
 body = resp.json
 assert body["code"] == "provider_credential_missing"
# ============================================================================
# Test E — conversation 不存在 → 404
# ============================================================================
@pytest.mark.django_db
def test_preflight_nonexistent_conversation_returns_404 -> None:
 """Behavior E：preflight 不存在的 conversation_id 返回 404。"""
 resp = _client.get(_url("00000000-0000-0000-0000-000000000000"))
 assert resp.status_code == 404, resp.content
# ============================================================================
# Test F — payload 包含 {code, data.missing_provider, data.recommended_action,
# data.scope_attempted}（前端契约完整字段）
# ============================================================================
@pytest.mark.django_db
def test_preflight_missing_payload_has_all_contract_fields(
 project_a,
) -> None:
 """Behavior F：missing payload 字段完整 — code / data.missing_provider /
 data.recommended_action / data.scope_attempted 四字段全部存在。
 """
 conv = Conversation.objects.create(project=project_a, title="契约字段断言")
 resp = _client.get(_url(str(conv.id)))
 assert resp.status_code == 400, resp.content
 body = resp.json
 # 顶层契约
 assert body["code"] == "provider_credential_missing"
 assert isinstance(body["data"], dict)
 # data 四字段（work item §Copywriting `provider_credential_missing` 契约驱动前端 Card 渲染）
 assert "missing_provider" in body["data"]
 assert "recommended_action" in body["data"]
 assert "scope_attempted" in body["data"]
 assert body["data"]["missing_provider"] # 非空
