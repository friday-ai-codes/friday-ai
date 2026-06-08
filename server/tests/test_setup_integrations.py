"""Phase 4: 首启向导安全校验 + 飞书 / 向量检索可选配置端点测试。

覆盖 Requirement: SEC-01（密钥安全校验，非阻塞、不回显密钥）、FEISHU-01/02（飞书配置写既有路径 +
App Secret Fernet 密文）、RAG-01/02（键名对齐 SettingKeys + 敏感项密文）。

权限：IsSuperUser。端点为 adrf async，用 DRF APIClient 同步驱动。
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from common.encryption import decrypt_value

SECURITY_URL = "/api/system/security-check/"
FEISHU_URL = "/api/system/setup-feishu/"
RAG_URL = "/api/system/setup-rag/"

INSECURE_SECRET_KEY = "django-insecure-change-me-in-production"

User = get_user_model()


def _superuser():
    return User.objects.create_superuser(username="setup-admin", password="x")


def _client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.mark.django_db(transaction=True)
class TestSecurityCheck:
    @override_settings(SECRET_KEY=INSECURE_SECRET_KEY, FRIDAY_ENCRYPTION_KEY="")
    def test_reports_insecure_defaults(self) -> None:
        """SEC-01：默认 SECRET_KEY + 未设加密密钥 → secure=False，含风险码，且不回显密钥。"""
        resp = _client(_superuser()).get(SECURITY_URL)
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["secure"] is False
        assert body["secret_key_secure"] is False
        assert body["encryption_key_set"] is False
        codes = {r["code"] for r in body["risks"]}
        assert "secret_key_default" in codes
        assert "encryption_key_unset" in codes
        # 绝不回显任何密钥明文
        assert INSECURE_SECRET_KEY not in json.dumps(body)

    @override_settings(
        SECRET_KEY="strong-random-secret-xyz", FRIDAY_ENCRYPTION_KEY="independent-enc-key-abc"
    )
    def test_reports_secure(self) -> None:
        """SEC-01：自定义且相互独立的密钥 → secure=True，风险清单为空。"""
        resp = _client(_superuser()).get(SECURITY_URL)
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["secure"] is True
        assert body["risks"] == []
        assert "strong-random-secret-xyz" not in json.dumps(body)

    @override_settings(SECRET_KEY="same-key-value", FRIDAY_ENCRYPTION_KEY="same-key-value")
    def test_reports_keys_not_independent(self) -> None:
        """SEC-01：加密密钥与 SECRET_KEY 相同 → keys_not_independent 风险。"""
        resp = _client(_superuser()).get(SECURITY_URL)
        body = resp.json()
        assert body["keys_independent"] is False
        assert body["secure"] is False
        codes = {r["code"] for r in body["risks"]}
        assert "keys_not_independent" in codes

    def test_requires_superuser(self) -> None:
        user = User.objects.create_user(username="plain-sec", password="x")
        assert _client(user).get(SECURITY_URL).status_code == 403

    def test_anonymous_rejected(self) -> None:
        assert _client().get(SECURITY_URL).status_code in (401, 403)


@pytest.mark.django_db(transaction=True)
class TestFeishuSetup:
    def test_encrypts_secret_and_aligns_keys(self) -> None:
        """FEISHU-01/02：App ID 明文、App Secret Fernet 密文，键名为既有 SettingKeys。"""
        from system.models import SettingKeys, SystemSetting

        resp = _client(_superuser()).post(
            FEISHU_URL,
            {"app_id": "cli_test12345", "app_secret": "feishu-secret-very-sensitive-0001"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["feishu_configured"] is True

        app_id = SystemSetting.objects.get(key=SettingKeys.FEISHU_APP_ID)
        assert app_id.value == "cli_test12345"
        assert app_id.is_encrypted is False

        secret = SystemSetting.objects.get(key=SettingKeys.FEISHU_APP_SECRET)
        assert secret.is_encrypted is True
        assert "feishu-secret-very-sensitive-0001" not in secret.value
        assert decrypt_value(secret.value) == "feishu-secret-very-sensitive-0001"

    def test_idempotent_retry(self) -> None:
        from system.models import SettingKeys, SystemSetting

        client = _client(_superuser())
        client.post(FEISHU_URL, {"app_id": "cli_a", "app_secret": "s1"}, format="json")
        client.post(FEISHU_URL, {"app_id": "cli_b", "app_secret": "s2"}, format="json")
        assert SystemSetting.objects.filter(key=SettingKeys.FEISHU_APP_ID).count() == 1
        assert SystemSetting.objects.get(key=SettingKeys.FEISHU_APP_ID).value == "cli_b"
        assert (
            decrypt_value(SystemSetting.objects.get(key=SettingKeys.FEISHU_APP_SECRET).value)
            == "s2"
        )

    def test_missing_fields_400(self) -> None:
        resp = _client(_superuser()).post(FEISHU_URL, {"app_id": "cli_x"}, format="json")
        assert resp.status_code == 400

    def test_requires_superuser(self) -> None:
        user = User.objects.create_user(username="plain-feishu", password="x")
        resp = _client(user).post(FEISHU_URL, {"app_id": "cli_x", "app_secret": "s"}, format="json")
        assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
class TestRagSetup:
    def test_aligns_settingkeys_and_encrypts(self) -> None:
        """RAG-01/02：键名对齐 SettingKeys；URL 明文，API Key 密文 + decrypt 还原。"""
        from system.models import SettingKeys, SystemSetting

        resp = _client(_superuser()).post(
            RAG_URL,
            {
                "qdrant_url": "http://qdrant:6333",
                "qdrant_api_key": "qdrant-secret-key-0001",
                "embedding_api_url": "https://api.embed.example/v1",
                "embedding_api_key": "embed-secret-key-0002",
                "embedding_model": "bge-m3",
                "embedding_dimension": 1024,
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["rag_configured"] is True

        url = SystemSetting.objects.get(key=SettingKeys.QDRANT_URL)
        assert url.value == "http://qdrant:6333"
        assert url.is_encrypted is False

        qkey = SystemSetting.objects.get(key=SettingKeys.QDRANT_API_KEY)
        assert qkey.is_encrypted is True
        assert "qdrant-secret-key-0001" not in qkey.value
        assert decrypt_value(qkey.value) == "qdrant-secret-key-0001"

        ekey = SystemSetting.objects.get(key=SettingKeys.EMBEDDING_API_KEY)
        assert ekey.is_encrypted is True
        assert decrypt_value(ekey.value) == "embed-secret-key-0002"

        assert SystemSetting.objects.get(key=SettingKeys.EMBEDDING_MODEL).value == "bge-m3"
        assert SystemSetting.objects.get(key=SettingKeys.EMBEDDING_DIMENSION).value == "1024"

    def test_partial_only_writes_provided(self) -> None:
        """仅 qdrant_url 时不创建空的可选键。"""
        from system.models import SettingKeys, SystemSetting

        resp = _client(_superuser()).post(
            RAG_URL, {"qdrant_url": "http://qdrant:6333"}, format="json"
        )
        assert resp.status_code == 200
        assert SystemSetting.objects.filter(key=SettingKeys.QDRANT_URL).exists()
        assert not SystemSetting.objects.filter(key=SettingKeys.QDRANT_API_KEY).exists()
        assert not SystemSetting.objects.filter(key=SettingKeys.EMBEDDING_API_KEY).exists()

    def test_missing_qdrant_url_400(self) -> None:
        resp = _client(_superuser()).post(RAG_URL, {"embedding_model": "x"}, format="json")
        assert resp.status_code == 400

    def test_requires_superuser(self) -> None:
        user = User.objects.create_user(username="plain-rag", password="x")
        resp = _client(user).post(RAG_URL, {"qdrant_url": "http://q:6333"}, format="json")
        assert resp.status_code == 403

    def test_anonymous_rejected(self) -> None:
        assert _client().post(
            RAG_URL, {"qdrant_url": "http://q:6333"}, format="json"
        ).status_code in (401, 403)
