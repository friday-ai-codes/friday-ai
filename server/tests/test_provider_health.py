"""initial implementation plan: 5 Provider 健康检查 + 原子写入 + Ollama available_models 测试。

覆盖 Requirement: contract, contract
威胁参考: security mitigation (凭证泄漏到日志), security mitigation (上游 error body 泄漏), security mitigation (权限契约)
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest import mock

import httpx
import pytest
import respx
from asgiref.sync import sync_to_async

from common.encryption import encrypt_value


def _make_credential(provider_type: str, config: dict[str, Any], **overrides: Any):
    """同步版本的凭证构造 helper（由 sync_to_async 包装调用）。

    默认使用随机 uuid4 作为 name 以避免 (provider_type, name) 在系统 scope 下
    UniqueConstraint 在 async pytest 测试间事务未彻底回滚时碰撞。
    """
    from system.models import ProviderCredential

    defaults: dict[str, Any] = dict(
        provider_type=provider_type,
        name=f"test-{uuid.uuid4().hex[:8]}",
        scope="system",
        scope_id=None,
        encrypted_config=encrypt_value(json.dumps(config)),
        base_url="",
        default_model="",
        is_active=True,
    )
    defaults.update(overrides)
    return ProviderCredential.objects.create(**defaults)


# ============================================================================
# Anthropic
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestHealthCheckAnthropic:
    @respx.mock
    async def test_ok(self) -> None:
        from services.provider_health import health_check
        from system.models import ProviderCredential

        cred = await sync_to_async(_make_credential)(
            "anthropic",
            {"api_key": "sk-ant-test", "base_url": "https://api.anthropic.com"},
        )
        respx.post("https://api.anthropic.com/v1/messages/count_tokens").mock(
            return_value=httpx.Response(200, json={"input_tokens": 8})
        )
        result = await health_check(cred)
        assert result.ok is True
        assert result.status == "ok"
        assert result.latency_ms >= 0

        # 三字段原子写回
        refreshed = await ProviderCredential.objects.aget(id=cred.id)
        assert refreshed.last_health_check_status == "ok"
        assert refreshed.last_health_check_at is not None
        assert refreshed.last_health_check_error == ""

    @respx.mock
    async def test_error_body_redacted_T225_02(self) -> None:
        from services.provider_health import health_check
        from system.models import ProviderCredential

        cred = await sync_to_async(_make_credential)(
            "anthropic",
            {"api_key": "sk-ant-test", "base_url": "https://api.anthropic.com"},
        )
        # 故意构造上游 422 body 含 sk-ant-* 明文
        respx.post("https://api.anthropic.com/v1/messages/count_tokens").mock(
            return_value=httpx.Response(
                422,
                text='{"error":"invalid api_key sk-ant-leaktest1234567890"}',
            )
        )
        result = await health_check(cred)
        assert result.status == "error"

        # security mitigation 缓解契约：错误字段必须脱敏（DB + 返回值都必须脱敏）
        refreshed = await ProviderCredential.objects.aget(id=cred.id)
        assert "sk-ant-leaktest1234567890" not in refreshed.last_health_check_error
        assert "REDACTED" in refreshed.last_health_check_error
        assert "sk-ant-leaktest1234567890" not in result.error

    @respx.mock
    async def test_uses_default_model_fallback(self) -> None:
        """cred.default_model 为空时 _ping_anthropic 用 claude-3-5-haiku-20241022 fallback。"""
        from services.provider_health import health_check

        cred = await sync_to_async(_make_credential)(
            "anthropic",
            {"api_key": "sk-ant-test", "base_url": "https://api.anthropic.com"},
            default_model="",
        )
        route = respx.post("https://api.anthropic.com/v1/messages/count_tokens").mock(
            return_value=httpx.Response(200, json={"input_tokens": 5})
        )
        await health_check(cred)
        assert route.called
        sent_body = json.loads(route.calls.last.request.content)
        assert sent_body["model"] == "claude-3-5-haiku-20241022"


# ============================================================================
# OpenAI（Responses + Chat 两个 ProviderType 共享 _ping_openai）
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestHealthCheckOpenAI:
    @respx.mock
    async def test_openai_chat_ok(self) -> None:
        from services.provider_health import health_check

        cred = await sync_to_async(_make_credential)(
            "openai_chat",
            {"api_key": "sk-openai-test-1234567890"},
        )
        respx.get("https://api.openai.com/v1/models").mock(
            return_value=httpx.Response(
                200, json={"data": [{"id": "gpt-5"}, {"id": "gpt-4o"}]}
            )
        )
        result = await health_check(cred)
        assert result.ok is True
        assert result.status == "ok"

    @respx.mock
    async def test_openai_responses_ok(self) -> None:
        from services.provider_health import health_check

        cred = await sync_to_async(_make_credential)(
            "openai_responses",
            {"api_key": "sk-openai-test-1234567890"},
        )
        respx.get("https://api.openai.com/v1/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "gpt-5"}]})
        )
        result = await health_check(cred)
        assert result.ok is True


# ============================================================================
# Gemini
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestHealthCheckGemini:
    @respx.mock
    async def test_gemini_ok(self) -> None:
        from services.provider_health import health_check

        cred = await sync_to_async(_make_credential)(
            "gemini",
            {"api_key": "fixture-gemini-api-key"},
        )
        respx.get(
            "https://generativelanguage.googleapis.com/v1beta/models"
        ).mock(
            return_value=httpx.Response(
                200, json={"models": [{"name": "models/gemini-2.5-flash"}]}
            )
        )
        result = await health_check(cred)
        assert result.ok is True


# ============================================================================
# Ollama（contract 协同：available_models 写入）
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestHealthCheckOllama:
    @respx.mock
    async def test_ollama_writes_available_models_PROV_06(self) -> None:
        from services.provider_health import health_check
        from system.models import ProviderCredential

        cred = await sync_to_async(_make_credential)(
            "ollama",
            {"base_url": "http://localhost:11434"},
        )
        respx.get("http://localhost:11434/api/tags").mock(
            return_value=httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "llama3.2:latest"},
                        {"name": "qwen2.5:7b"},
                    ]
                },
            )
        )
        result = await health_check(cred)
        assert result.ok is True
        assert result.available_models == ["llama3.2:latest", "qwen2.5:7b"]

        # contract 协同：DB 字段同次往返写入
        refreshed = await ProviderCredential.objects.aget(id=cred.id)
        assert refreshed.available_models == ["llama3.2:latest", "qwen2.5:7b"]


# ============================================================================
# 错误路径：graceful 降级
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestHealthCheckErrorPaths:
    @respx.mock
    async def test_timeout_graceful(self) -> None:
        from services.provider_health import health_check

        cred = await sync_to_async(_make_credential)(
            "anthropic",
            {"api_key": "sk-ant-test", "base_url": "https://api.anthropic.com"},
        )
        respx.post("https://api.anthropic.com/v1/messages/count_tokens").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        result = await health_check(cred)
        assert result.status == "error"
        assert "timeout" in result.error.lower()

    @respx.mock
    async def test_connect_error_graceful(self) -> None:
        from services.provider_health import health_check

        cred = await sync_to_async(_make_credential)(
            "ollama",
            {"base_url": "http://unreachable.localtest.me:11434"},
        )
        respx.get("http://unreachable.localtest.me:11434/api/tags").mock(
            side_effect=httpx.ConnectError("Name or service not known")
        )
        result = await health_check(cred)
        assert result.status == "error"
        assert "connection" in result.error.lower()


# ============================================================================
# Dispatch matrix：5 ProviderType 分别分发到对应 _ping_* 函数
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestHealthCheckDispatchMatrix:
    """契约：_PING_DISPATCH 5 ProviderType -> 4 helper（openai_chat / openai_responses 共享 _ping_openai）。

    patch `_PING_DISPATCH` dict 中的项而非模块级 name —— 字典已在 import 时持有原始函数引用，
    patch 模块属性不生效。
    """

    async def test_dispatch_anthropic_goes_to_ping_anthropic(self) -> None:
        from services import provider_health
        from services.provider_health import HealthCheckResult, health_check

        cred = await sync_to_async(_make_credential)(
            "anthropic", {"api_key": "sk-ant-test"}
        )
        stub = mock.AsyncMock(
            return_value=HealthCheckResult(
                ok=True, status="ok", latency_ms=1, error=""
            )
        )
        with mock.patch.dict(
            provider_health._PING_DISPATCH,
            {provider_health.ProviderType.ANTHROPIC: stub},
        ):
            await health_check(cred)
            assert stub.call_count == 1

    async def test_dispatch_ollama_goes_to_ping_ollama(self) -> None:
        from services import provider_health
        from services.provider_health import HealthCheckResult, health_check

        cred = await sync_to_async(_make_credential)(
            "ollama", {"base_url": "http://localhost:11434"}
        )
        stub = mock.AsyncMock(
            return_value=HealthCheckResult(
                ok=True,
                status="ok",
                latency_ms=1,
                error="",
                available_models=[],
            )
        )
        with mock.patch.dict(
            provider_health._PING_DISPATCH,
            {provider_health.ProviderType.OLLAMA: stub},
        ):
            await health_check(cred)
            assert stub.call_count == 1

    async def test_dispatch_openai_chat_and_responses_share_ping_openai(self) -> None:
        from services import provider_health
        from services.provider_health import HealthCheckResult, health_check

        cred_chat = await sync_to_async(_make_credential)(
            "openai_chat",
            {"api_key": "sk-openai-test-1234567890"},
        )
        cred_resp = await sync_to_async(_make_credential)(
            "openai_responses",
            {"api_key": "sk-openai-test-1234567890"},
        )
        stub = mock.AsyncMock(
            return_value=HealthCheckResult(
                ok=True, status="ok", latency_ms=1, error=""
            )
        )
        # 同一 stub 绑定到两种 OpenAI ProviderType，验证 2 次调用
        with mock.patch.dict(
            provider_health._PING_DISPATCH,
            {
                provider_health.ProviderType.OPENAI_CHAT: stub,
                provider_health.ProviderType.OPENAI_RESPONSES: stub,
            },
        ):
            await health_check(cred_chat)
            await health_check(cred_resp)
            assert stub.call_count == 2


# ============================================================================
# DRF 端点：ProviderCredentialTestConnectionView
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestTestConnectionEndpoint:
    """POST /api/providers/credentials/{id}/test-connection/ 契约。

    本 phase 权限：IsAuthenticated（initial implementation 升级 IsSuperUserOrProjectAdmin）；
    Ollama 凭证走 respx mock；鉴权失败 / 不存在 credential / URL reverse 链路验证。
    """

    @respx.mock
    def test_test_connection_anthropic_ok(self) -> None:
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        UserModel = get_user_model()
        user = UserModel.objects.create_user(
            username="health-user",
            email="h@example.com",
            password="x",
        )

        cred = _make_credential(
            "anthropic",
            {"api_key": "sk-ant-test", "base_url": "https://api.anthropic.com"},
        )
        respx.post("https://api.anthropic.com/v1/messages/count_tokens").mock(
            return_value=httpx.Response(200, json={"input_tokens": 8})
        )

        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(
            f"/api/providers/credentials/{cred.id}/test-connection/",
            format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["ok"] is True
        assert body["status"] == "ok"
        assert body["latency_ms"] >= 0
        assert body["last_check_at"] is not None
        assert body["error"] == ""

    def test_test_connection_unauth_returns_401(self) -> None:
        from rest_framework.test import APIClient

        cred = _make_credential("anthropic", {"api_key": "sk-ant-test"})
        client = APIClient()
        resp = client.post(
            f"/api/providers/credentials/{cred.id}/test-connection/",
            format="json",
        )
        assert resp.status_code == 401

    def test_test_connection_404_credential_missing(self) -> None:
        from uuid import uuid4

        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        UserModel = get_user_model()
        user = UserModel.objects.create_user(
            username="missing-cred-user",
            email="m@example.com",
            password="x",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(
            f"/api/providers/credentials/{uuid4()}/test-connection/",
            format="json",
        )
        assert resp.status_code == 404

    def test_test_connection_url_mounted_at_correct_path(self) -> None:
        """URL reverse 必须解析到 /api/providers/credentials/<uuid>/test-connection/。"""
        from uuid import uuid4

        from django.urls import reverse

        url = reverse(
            "provider-credential-test-connection",
            kwargs={"credential_id": uuid4()},
        )
        assert url.startswith("/api/providers/credentials/"), url
        assert url.endswith("/test-connection/"), url
