"""Provider API 端点测试 — Phase。
验证 Provider 列表、模型列表（缓存）、健康检查、
ConversationSerializer 扩展、TokenUsage 扩展、定价计算。
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from django.contrib.auth import get_user_model
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken
User = get_user_model
# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
async def user_and_token(db):
 """创建测试用户并生成 JWT token。"""
 user = await User.objects.acreate_user(
 username="provider_test_user",
 password="testpass123",
 )
 token = RefreshToken.for_user(user)
 return user, str(token.access_token)
@pytest.fixture
def auth_headers(user_and_token):
 """返回带 Authorization header 的 dict。"""
 _, access_token = user_and_token
 return {"authorization": f"Bearer {access_token}"}
# ---------------------------------------------------------------------------
# Provider 列表 API
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_provider_list(user_and_token):
 """GET /api/chat/providers/ 返回 Provider 列表。"""
 _, token = user_and_token
 client = AsyncClient
 resp = await client.get(
 "/api/chat/providers/",
 headers={"authorization": f"Bearer {token}"},
 )
 assert resp.status_code == 200
 data = resp.json
 assert isinstance(data, list)
 assert len(data) == 1 # 仅 Anthropic
 # 验证每个 Provider 有必需字段
 for provider in data:
 assert "id" in provider
 assert "name" in provider
 assert "icon" in provider
 assert "credential_type" in provider
 assert "has_credential" in provider
 # 验证唯一的 Provider 是 Anthropic
 assert data[0]["id"] == "anthropic"
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_provider_list_has_credential_true(user_and_token):
 """已配置 API Key 的 Provider has_credential=True。"""
 _, token = user_and_token
 # 配置 Anthropic API Key
 from system.models import SystemSetting
 await SystemSetting.objects.aupdate_or_create(
 key="anthropic_api_key",
 defaults={"value": "sk-test-key", "is_encrypted": False},
 )
 client = AsyncClient
 resp = await client.get(
 "/api/chat/providers/",
 headers={"authorization": f"Bearer {token}"},
 )
 assert resp.status_code == 200
 data = resp.json
 anthropic = next(p for p in data if p["id"] == "anthropic")
 assert anthropic["has_credential"] is True
# ---------------------------------------------------------------------------
# 模型列表 API
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_provider_models_valid(user_and_token):
 """GET /api/chat/providers/anthropic/models/ 返回模型列表。"""
 _, token = user_and_token
 mock_models = [
 SimpleNamespace(id="claude-sonnet-4-20250514", name="Claude Sonnet 4", created=None),
 ]
 with patch("chat.views.aget_setting_value", new_callable=AsyncMock, return_value="sk-test"):
 with patch("chat.views._get_provider_models", new_callable=AsyncMock, return_value=mock_models):
 client = AsyncClient
 resp = await client.get(
 "/api/chat/providers/anthropic/models/",
 headers={"authorization": f"Bearer {token}"},
 )
 assert resp.status_code == 200
 data = resp.json
 assert "models" in data
 assert len(data["models"]) >= 1
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_provider_models_invalid_type(user_and_token):
 """GET /api/chat/providers/invalid/models/ 返回 400。"""
 _, token = user_and_token
 client = AsyncClient
 resp = await client.get(
 "/api/chat/providers/invalid-provider/models/",
 headers={"authorization": f"Bearer {token}"},
 )
 assert resp.status_code == 400
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_provider_models_cache(user_and_token):
 """模型列表缓存：两次请求只调用一次上游。"""
 from django.core.cache import cache
 cache.clear
 _, token = user_and_token
 mock_models = [
 SimpleNamespace(id="claude-sonnet-4-20250514", name="Claude Sonnet 4", created=None),
 ]
 get_models_mock = AsyncMock(return_value=mock_models)
 with patch("chat.views.aget_setting_value", new_callable=AsyncMock, return_value="sk-test"):
 with patch("chat.views._get_provider_models", get_models_mock):
 client = AsyncClient
 # 第一次请求
 resp1 = await client.get(
 "/api/chat/providers/anthropic/models/",
 headers={"authorization": f"Bearer {token}"},
 )
 # 第二次请求（应命中缓存）
 resp2 = await client.get(
 "/api/chat/providers/anthropic/models/",
 headers={"authorization": f"Bearer {token}"},
 )
 assert resp1.status_code == 200
 assert resp2.status_code == 200
 # 只调用了一次上游 API
 assert get_models_mock.call_count == 1
# ---------------------------------------------------------------------------
# 健康检查 API
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_health_check_available(user_and_token):
 """POST /api/chat/providers/anthropic/health/ 返回 available。"""
 _, token = user_and_token
 mock_provider = MagicMock
 mock_provider.chat = AsyncMock(return_value=MagicMock)
 with patch("chat.views.aget_setting_value", new_callable=AsyncMock, return_value="sk-test"):
 with patch("chat.views.create_provider", return_value=mock_provider):
 client = AsyncClient
 resp = await client.post(
 "/api/chat/providers/anthropic/health/",
 content_type="application/json",
 headers={"authorization": f"Bearer {token}"},
 )
 assert resp.status_code == 200
 data = resp.json
 assert data["provider_type"] == "anthropic"
 assert data["status"] == "available"
 assert "latency_ms" in data
 assert isinstance(data["latency_ms"], int)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_health_check_unavailable(user_and_token):
 """API 失败时返回 unavailable。"""
 _, token = user_and_token
 mock_provider = MagicMock
 mock_provider.chat = AsyncMock(side_effect=Exception("API Key 无效"))
 with patch("chat.views.aget_setting_value", new_callable=AsyncMock, return_value="sk-test"):
 with patch("chat.views.create_provider", return_value=mock_provider):
 client = AsyncClient
 resp = await client.post(
 "/api/chat/providers/anthropic/health/",
 content_type="application/json",
 headers={"authorization": f"Bearer {token}"},
 )
 assert resp.status_code == 200
 data = resp.json
 assert data["status"] == "unavailable"
 assert data["error"] is not None
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_health_check_invalid_type(user_and_token):
 """POST /api/chat/providers/invalid/health/ 返回 400。"""
 _, token = user_and_token
 client = AsyncClient
 resp = await client.post(
 "/api/chat/providers/invalid-provider/health/",
 content_type="application/json",
 headers={"authorization": f"Bearer {token}"},
 )
 assert resp.status_code == 400
# ---------------------------------------------------------------------------
# ConversationSerializer
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_conversation_serializer_provider_type(user_and_token):
 """ConversationListSerializer 包含 provider_type 字段。"""
 from chat.serializers import ConversationListSerializer
 data = {
 "id": "00000000-0000-0000-0000-000000000001",
 "project_id": "00000000-0000-0000-0000-000000000002",
 "title": "测试对话",
 "model": "claude-sonnet-4",
 "provider_type": "anthropic",
 "created_at": "2026-03-09T00:00:00Z",
 "updated_at": "2026-03-09T00:00:00Z",
 }
 serializer = ConversationListSerializer(data=data)
 assert serializer.is_valid, serializer.errors
 assert serializer.validated_data["provider_type"] == "anthropic"
# ---------------------------------------------------------------------------
# TokenUsage 模型扩展
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_token_usage_provider_type:
 """TokenUsage 实例可设置 provider_type 字段。"""
 from subagent.models import TokenUsage
 # 验证 provider_type 字段存在
 field = TokenUsage._meta.get_field("provider_type")
 assert field is not None
 assert field.null is True
 assert field.blank is True
# ---------------------------------------------------------------------------
# 定价计算
# ---------------------------------------------------------------------------
def test_pricing_calculation:
 """calculate_cost 返回正确成本。"""
 from services.pricing import calculate_cost
 # claude-sonnet-4: input=$0.003/1K, output=$0.015/1K
 cost = calculate_cost("claude-sonnet-4-20250514", input_tokens=1000, output_tokens=500)
 expected = Decimal("0.003") * 1000 / 1000 + Decimal("0.015") * 500 / 1000
 assert cost == expected.quantize(Decimal("0.000001"))
def test_pricing_unknown_model:
 """未知模型使用默认价格。"""
 from services.pricing import DEFAULT_PRICING, calculate_cost
 cost = calculate_cost("unknown-model-xyz", input_tokens=1000, output_tokens=1000)
 expected = (
 Decimal(DEFAULT_PRICING["input_per_1k"]) * 1000 / 1000
 + Decimal(DEFAULT_PRICING["output_per_1k"]) * 1000 / 1000
 )
 assert cost == expected.quantize(Decimal("0.000001"))
def test_pricing_prefix_match:
 """定价表使用前缀匹配（gpt-4o-mini 优先于 gpt-4o）。"""
 from services.pricing import calculate_cost
 # gpt-4o-mini 有独立定价，不应匹配 gpt-4o
 cost_mini = calculate_cost("gpt-4o-mini-2024", input_tokens=1000, output_tokens=1000)
 cost_4o = calculate_cost("gpt-4o-2024", input_tokens=1000, output_tokens=1000)
 assert cost_mini != cost_4o # 两者价格不同
 assert cost_mini < cost_4o # mini 更便宜
