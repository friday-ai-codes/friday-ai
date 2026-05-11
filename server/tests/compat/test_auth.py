"""OptionalBearerTokenAuth 鉴权桩测试（任务 3 TDD）。
测试覆盖：
 - test_optional_bearer_allowany：OPENAI_COMPAT_API_KEYS="" → 无 Authorization 也能访问
 - test_optional_bearer_deny：OPENAI_COMPAT_API_KEYS="secret" → 无 token 返回 403
 - test_optional_bearer_allow：OPENAI_COMPAT_API_KEYS="secret" → Bearer secret 返回 200
"""
from __future__ import annotations
import json
from unittest.mock import patch
import pytest
from django.test import AsyncClient, override_settings
@pytest.mark.asyncio
@pytest.mark.django_db
async def test_optional_bearer_allowany -> None:
 """OPENAI_COMPAT_API_KEYS 为空 → AllowAny，无 Authorization header 也能访问。"""
 with patch.dict("os.environ", {"OPENAI_COMPAT_API_KEYS": ""}):
 client = AsyncClient
 response = await client.get("/v1/models/")
 assert response.status_code == 200
@pytest.mark.asyncio
@pytest.mark.django_db
async def test_optional_bearer_deny -> None:
 """OPENAI_COMPAT_API_KEYS="secret" 时，无 Authorization header → 403。"""
 with patch.dict("os.environ", {"OPENAI_COMPAT_API_KEYS": "secret"}):
 client = AsyncClient
 response = await client.get("/v1/models/")
 assert response.status_code == 403
@pytest.mark.asyncio
@pytest.mark.django_db
async def test_optional_bearer_allow -> None:
 """OPENAI_COMPAT_API_KEYS="secret"，Authorization: Bearer secret → 200。
 注意：Django AsyncClient 使用 ASGI 协议，HTTP headers 必须通过 headers= 参数传递，
 不能用 HTTP_AUTHORIZATION= 关键字参数（后者会产生 HTTP_HTTP_AUTHORIZATION META 键）。
 """
 with patch.dict("os.environ", {"OPENAI_COMPAT_API_KEYS": "secret"}):
 client = AsyncClient
 response = await client.get(
 "/v1/models/",
 headers={"Authorization": "Bearer secret"},
 )
 assert response.status_code == 200
